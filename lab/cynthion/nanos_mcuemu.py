# Nano S MCU emulator core (Amaranth) — drives a removed ST31 secure element over a
# 3-wire ISO 7816 T=0 link and speaks SEPROXYHAL as the MCU would.
#
# Adapted from the Nano X single-wire McuEmu (ledger_nanox_analysis/lab/cynthion/nanox_bench/
# mcuemu_core.py). Differences for the Nano S / ST31 (all verified on the Baochip bit-bang rig,
# 2026-11-12, and against nanos-nonsecure-firmware source):
#   * 3-wire: we GENERATE the card CLK and RST (the ST31 is externally clocked); I/O is the
#     open-drain half-duplex data line (io_o/io_oe/io_i, external 10k pull-up).
#   * One speed only: the ST31 stays at the ATR etu = Fi/Di = 512/12 = 372 CLK cycles/bit
#     (it echoes PPS but ignores it), so there is no fast-phase switch. etu is tied to CLK:
#     one bit = 372 CLK periods.
#   * Framing = ISO 7816 T=0: 8 data LSB-first + EVEN parity + >=2 stop. (The Nano X core had
#     no parity; the ST31 checks it, so we generate it on TX and verify on RX.)
#   * SESSION_START is the small Nano S blob (kind|features|version), not the 48-B Nano X one.
#   * Control contract (nanos-nonsecure-firmware main.c): after SESSION_START, run the
#     event/command loop — reply DISPLAY_PROCESSED_EVENT to each SCREEN_DISPLAY_STATUS, and
#     after GENERAL_STATUS(LAST_COMMAND) send the next event (a TICKER). No REQUEST_STATUS.
#
# The screen is drawn by the SE over SEPROXYHAL (SCREEN_DISPLAY_STATUS carries BAGL draw
# commands), so capturing RX frames here *is* the screen read — no separate OLED tap needed.
#
# Platform-independent: all pins are plain Signals, so it runs under `amaranth.sim` with a
# fake-SE model (see sim_nanos.py) and needs no hardware. A Cynthion top-level maps io_*/clk_o/
# rst_o to a PMOD and streams captured frames to the host.

from amaranth import *

# ---- SEPROXYHAL frames we transmit (tag | len(2 BE) | payload) ----
# SESSION_START (0x01): kind=00 | features(4BE)=0x00000221 (USB|2 buttons|small screen) |
#                        vlen=04 | VERSION "1.1\0". Accepted by the real ST31 on 2026-11-12.
SESSION_START      = bytes.fromhex('01000a' '00' '00000221' '04' '312e3100')
DISPLAY_PROCESSED  = bytes.fromhex('0d0000')                    # reply to SCREEN_DISPLAY_STATUS
TICKER_EVENT       = bytes.fromhex('0e0004' '00000000')         # 4-B BE ms counter, patched live

_ROM = SESSION_START + DISPLAY_PROCESSED + TICKER_EVENT
OFF_SS, LEN_SS = 0,                     len(SESSION_START)
OFF_DP, LEN_DP = LEN_SS,                len(DISPLAY_PROCESSED)
OFF_TK, LEN_TK = LEN_SS + LEN_DP,       len(TICKER_EVENT)

TAG_SCREEN_DISPLAY = 0x65
TAG_GENERAL_STATUS = 0x60


class NanoSMcuEmu(Elaboratable):
    """ISO 7816 T=0 master + SEPROXYHAL MCU emulator for the Nano S ST31.

    Ports (all in the caller's default sync domain):
      io_i             data line input (sampled)
      io_o, io_oe      data line output + open-drain enable (drive 0 when io_oe & ~io_o)
      clk_o            card clock output (square wave, freq = f_sync / (2*clk_div))
      rst_o            card reset output (active high release: 0 = held in reset)
    Observability / host stream:
      rx_byte_stb, rx_byte     every received byte (route to a host UART to log the link)
      rx_frame_stb, rx_ftag    pulses at each complete RX frame with its tag
      booted                   high once SESSION_START has been sent
    Params:
      clk_div   half-period of the card clock in sync cycles (CLK period = 2*clk_div)
      etu_clk   CLK cycles per bit (ISO 7816 etu); 372 for this card
      rst_clk   CLK cycles to hold RST low before releasing
      tick_div  sync cycles between TICKER events; tick_ms = ms increment per tick
    """

    def __init__(self, clk_div=16, etu_clk=372, rst_clk=4000,
                 tick_div=6_000_000, tick_ms=100, atr_idle=400):
        self.clk_div = clk_div
        self.etu_clk = etu_clk
        self.rst_clk = rst_clk
        self.tick_div = tick_div
        self.tick_ms = tick_ms
        self.atr_idle = atr_idle
        # wire
        self.io_i = Signal(reset=1)
        self.io_o = Signal(reset=1)
        self.io_oe = Signal()
        self.clk_o = Signal()
        self.rst_o = Signal()
        # observability
        self.rx_byte_stb = Signal()
        self.rx_byte = Signal(8)
        self.rx_frame_stb = Signal()
        self.rx_ftag = Signal(8)
        self.rx_perr = Signal()
        self.booted = Signal()
        self.tms = Signal(32)

    def elaborate(self, platform):
        m = Module()
        BD = self.clk_div * 2 * self.etu_clk  # sync cycles per bit (etu)

        # ---------------- card clock generator ----------------
        cdiv = Signal(range(self.clk_div))
        with m.If(cdiv == self.clk_div - 1):
            m.d.sync += [cdiv.eq(0), self.clk_o.eq(~self.clk_o)]
        with m.Else():
            m.d.sync += cdiv.eq(cdiv + 1)

        rom = Array([C(b, 8) for b in _ROM])

        # ---------------- UART byte TX: start + 8 data LSB-first + EVEN parity + 1 stop ----------------
        tx_start = Signal(); tx_data = Signal(8); tx_busy = Signal()
        tdat = Signal(8); tpar = Signal(); tdiv = Signal(range(BD)); tcnt = Signal(4)
        bit_o = Signal(reset=1)
        with m.FSM(name="txbyte") as txf:
            with m.State("IDLE"):
                m.d.comb += bit_o.eq(1)
                with m.If(tx_start):
                    m.d.sync += [tdat.eq(tx_data), tpar.eq(0), tdiv.eq(BD - 1)]
                    m.next = "START"
            with m.State("START"):
                m.d.comb += bit_o.eq(0)
                with m.If(tdiv == 0): m.d.sync += [tdiv.eq(BD - 1), tcnt.eq(0)]; m.next = "DATA"
                with m.Else():        m.d.sync += tdiv.eq(tdiv - 1)
            with m.State("DATA"):
                m.d.comb += bit_o.eq(tdat[0])
                with m.If(tdiv == 0):
                    m.d.sync += [tdat.eq(Cat(tdat[1:8], 0)), tpar.eq(tpar ^ tdat[0]),
                                 tcnt.eq(tcnt + 1), tdiv.eq(BD - 1)]
                    with m.If(tcnt == 7): m.next = "PAR"
                with m.Else():
                    m.d.sync += tdiv.eq(tdiv - 1)
            with m.State("PAR"):
                m.d.comb += bit_o.eq(tpar)                      # even parity
                with m.If(tdiv == 0): m.d.sync += tdiv.eq(BD - 1); m.next = "STOP"
                with m.Else():        m.d.sync += tdiv.eq(tdiv - 1)
            with m.State("STOP"):
                m.d.comb += bit_o.eq(1)
                with m.If(tdiv == 0): m.next = "IDLE"
                with m.Else():        m.d.sync += tdiv.eq(tdiv - 1)
        m.d.comb += tx_busy.eq(~txf.ongoing("IDLE"))

        # ---------------- frame streamer (holds oe across a whole frame) ----------------
        f_start = Signal(); f_off = Signal(range(len(_ROM) + 1)); f_len = Signal(range(len(_ROM) + 1))
        f_done = Signal()
        idx = Signal(range(len(_ROM) + 1)); base = Signal(range(len(_ROM) + 1)); flen = Signal(range(len(_ROM) + 1))
        with m.FSM(name="frame"):
            with m.State("IDLE"):
                with m.If(f_start):
                    m.d.sync += [idx.eq(0), base.eq(f_off), flen.eq(f_len)]
                    m.next = "LOAD"
            with m.State("LOAD"):
                m.d.comb += self.io_oe.eq(1)
                with m.If(idx == flen):
                    m.d.comb += f_done.eq(1)
                    m.next = "IDLE"
                with m.Elif(~tx_busy):
                    tkb = Signal(8)
                    with m.Switch(idx):                         # live ms counter into TICKER payload
                        with m.Case(3): m.d.comb += tkb.eq(self.tms[24:32])
                        with m.Case(4): m.d.comb += tkb.eq(self.tms[16:24])
                        with m.Case(5): m.d.comb += tkb.eq(self.tms[8:16])
                        with m.Case(6): m.d.comb += tkb.eq(self.tms[0:8])
                        with m.Default(): m.d.comb += tkb.eq(rom[base + idx])
                    is_tk = (base == OFF_TK)
                    m.d.comb += [tx_data.eq(Mux(is_tk & (idx >= 3), tkb, rom[base + idx])), tx_start.eq(1)]
                    m.next = "RISE"
            with m.State("RISE"):
                m.d.comb += self.io_oe.eq(1)
                with m.If(tx_busy): m.next = "FALL"
            with m.State("FALL"):
                m.d.comb += self.io_oe.eq(1)
                with m.If(~tx_busy):
                    m.d.sync += idx.eq(idx + 1)
                    m.next = "LOAD"
        m.d.comb += self.io_o.eq(bit_o)

        # ---------------- UART byte RX: 8 data + parity + stop, with parity check ----------------
        rx_s = Signal(reset=1); m.d.sync += rx_s.eq(self.io_i)
        rdiv = Signal(range(BD)); rcnt = Signal(4); rsh = Signal(8); rpar = Signal(); rxbusy = Signal()
        with m.FSM(name="rxbyte"):
            with m.State("IDLE"):
                with m.If(rx_s & ~self.io_i & ~self.io_oe):     # falling edge = start bit (ignore our own TX loopback)
                    m.d.sync += [rdiv.eq(BD // 2 - 1), rxbusy.eq(1), rpar.eq(0)]
                    m.next = "START"
            with m.State("START"):
                with m.If(rdiv == 0):
                    with m.If(~self.io_i): m.d.sync += [rdiv.eq(BD - 1), rcnt.eq(0)]; m.next = "DATA"
                    with m.Else():         m.d.sync += rxbusy.eq(0); m.next = "IDLE"
                with m.Else(): m.d.sync += rdiv.eq(rdiv - 1)
            with m.State("DATA"):
                with m.If(rdiv == 0):
                    m.d.sync += [rsh.eq(Cat(rsh[1:8], self.io_i)), rpar.eq(rpar ^ self.io_i),
                                 rcnt.eq(rcnt + 1), rdiv.eq(BD - 1)]
                    with m.If(rcnt == 7): m.next = "PAR"
                with m.Else(): m.d.sync += rdiv.eq(rdiv - 1)
            with m.State("PAR"):
                with m.If(rdiv == 0):
                    m.d.comb += [self.rx_byte_stb.eq(1), self.rx_byte.eq(rsh),
                                 self.rx_perr.eq(rpar ^ self.io_i)]   # even parity -> xor incl. parity bit == 0
                    m.d.sync += [rdiv.eq(BD - 1)]
                    m.next = "STOP"
                with m.Else(): m.d.sync += rdiv.eq(rdiv - 1)
            with m.State("STOP"):
                with m.If(rdiv == 0): m.d.sync += rxbusy.eq(0); m.next = "IDLE"
                with m.Else():        m.d.sync += rdiv.eq(rdiv - 1)

        # ---------------- RX frame reassembly (tag | len2BE | payload) ----------------
        # Only parse SEPROXYHAL frames once we've booted (sent SESSION_START). Before that the
        # SE's bytes are the raw ISO 7816 ATR, which is NOT tag|len|payload and would desync this.
        rbs = self.rx_byte_stb & self.booted
        rlen = Signal(16); rrem = Signal(16); ftag = Signal(8)
        with m.FSM(name="rxframe"):
            with m.State("TAG"):
                with m.If(rbs): m.d.sync += ftag.eq(self.rx_byte); m.next = "L0"
            with m.State("L0"):
                with m.If(rbs): m.d.sync += rlen.eq(self.rx_byte << 8); m.next = "L1"
            with m.State("L1"):
                with m.If(rbs):
                    tot = (rlen | self.rx_byte)
                    with m.If(tot == 0):
                        m.d.comb += [self.rx_frame_stb.eq(1), self.rx_ftag.eq(ftag)]
                        m.next = "TAG"
                    with m.Else():
                        m.d.sync += rrem.eq(tot); m.next = "PAY"
            with m.State("PAY"):
                with m.If(rbs):
                    with m.If(rrem == 1):
                        m.d.comb += [self.rx_frame_stb.eq(1), self.rx_ftag.eq(ftag)]
                        m.next = "TAG"
                    with m.Else():
                        m.d.sync += rrem.eq(rrem - 1)

        # ---------------- events / timers ----------------
        pend_disp = Signal(); pend_tick = Signal()
        got_screen = self.rx_frame_stb & ((self.rx_ftag & 0x7f) == TAG_SCREEN_DISPLAY)
        got_genstat = self.rx_frame_stb & ((self.rx_ftag & 0x7f) == TAG_GENERAL_STATUS)
        with m.If(got_screen): m.d.sync += pend_disp.eq(1)
        with m.If(got_genstat): m.d.sync += pend_tick.eq(1)

        line_idle = ~rxbusy & self.io_i & ~tx_busy

        # ---------------- top control FSM: reset -> ATR -> SESSION_START -> loop ----------------
        rcnt_rst = Signal(range(max(self.rst_clk, self.atr_idle) + 1))
        tickcnt = Signal(range(self.tick_div + 1))
        with m.If(tickcnt == self.tick_div):
            m.d.sync += [tickcnt.eq(0), self.tms.eq(self.tms + self.tick_ms)]
        with m.Else():
            m.d.sync += tickcnt.eq(tickcnt + 1)

        with m.FSM(name="ctl"):
            with m.State("RESET"):                               # hold RST low, clock running
                m.d.comb += self.rst_o.eq(0)
                with m.If(rcnt_rst == self.rst_clk): m.next = "ATR"
                with m.Else(): m.d.sync += rcnt_rst.eq(rcnt_rst + 1)
            with m.State("ATR"):                                 # release RST, let the SE send its ATR
                m.d.comb += self.rst_o.eq(1)
                # wait for the ATR frame to go by: first byte then a line-idle gap
                with m.If(self.rx_byte_stb): m.next = "ATR_WAIT"
            with m.State("ATR_WAIT"):
                m.d.comb += self.rst_o.eq(1)
                with m.If(self.rx_byte_stb): m.d.sync += rcnt_rst.eq(0)   # reuse counter as idle timer
                with m.Elif(line_idle):
                    with m.If(rcnt_rst == self.atr_idle): m.next = "BOOT"   # idle gap = ATR done
                    with m.Else(): m.d.sync += rcnt_rst.eq(rcnt_rst + 1)
            with m.State("BOOT"):
                m.d.comb += [self.rst_o.eq(1), f_start.eq(1), f_off.eq(OFF_SS), f_len.eq(LEN_SS)]
                m.next = "SENDING"
            with m.State("SENDING"):
                m.d.comb += self.rst_o.eq(1)
                with m.If(f_done): m.d.sync += self.booted.eq(1); m.next = "RUN"
            with m.State("RUN"):
                m.d.comb += self.rst_o.eq(1)
                with m.If(line_idle & pend_disp):
                    m.d.comb += [f_start.eq(1), f_off.eq(OFF_DP), f_len.eq(LEN_DP)]
                    m.d.sync += pend_disp.eq(0); m.next = "TX"
                with m.Elif(line_idle & pend_tick):
                    m.d.comb += [f_start.eq(1), f_off.eq(OFF_TK), f_len.eq(LEN_TK)]
                    m.d.sync += pend_tick.eq(0); m.next = "TX"
            with m.State("TX"):
                m.d.comb += self.rst_o.eq(1)
                with m.If(f_done): m.next = "RUN"
        return m

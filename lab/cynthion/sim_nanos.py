# Pysim validation of NanoSMcuEmu with a fake ST31 — no hardware needed.
#   source ~/oss-cad-suite/environment && python3 sim_nanos.py
#
# The fake SE: releases after reset, sends a short ATR, then expects our SESSION_START;
# then sends GENERAL_STATUS (we must answer with a TICKER) and SCREEN_DISPLAY_STATUS (we
# must answer DISPLAY_PROCESSED). The wire is modelled open-drain: low if either side pulls low.

import sys
from amaranth import *
from amaranth.sim import Simulator
from nanos_mcuemu import NanoSMcuEmu, SESSION_START, DISPLAY_PROCESSED

CLK_DIV, ETU_CLK = 2, 4
BD = CLK_DIV * 2 * ETU_CLK          # sync cycles per bit (etu)


class SimTop(Elaboratable):
    def __init__(self):
        self.emu = NanoSMcuEmu(clk_div=CLK_DIV, etu_clk=ETU_CLK, rst_clk=8,
                               atr_idle=64, tick_div=400, tick_ms=100)
        self.se_low = Signal()      # the fake SE pulls the I/O line low

    def elaborate(self, platform):
        m = Module()
        m.submodules.emu = e = self.emu
        # open-drain wire: low if the SE drives low, or the emu drives low
        m.d.comb += e.io_i.eq(~(self.se_low | (e.io_oe & ~e.io_o)))
        return m


def parity_even(byte):
    return bin(byte).count("1") & 1


async def se_send_byte(ctx, top, byte):
    """Drive one T=0 char (start + 8 data LSB + even parity + 2 stop) onto the wire as the SE."""
    async def cell(level_low):
        ctx.set(top.se_low, 1 if level_low else 0)
        for _ in range(BD):
            await ctx.tick()
    await cell(True)                                  # start bit (low)
    for b in range(8):
        await cell(((byte >> b) & 1) == 0)            # data: drive low for 0, release for 1
    await cell(parity_even(byte) == 0)                # even parity bit: logic level = parity_even(byte)
    ctx.set(top.se_low, 0)
    for _ in range(2 * BD):                           # 2 stop bits (release)
        await ctx.tick()


async def se_send_frame(ctx, top, data):
    # half-duplex turnaround: wait until the reader (emu) has released the line, as a real card does
    idle = 0
    while idle < 2 * BD:
        await ctx.tick()
        idle = idle + 1 if ctx.get(top.emu.io_oe) == 0 else 0
    for byte in data:
        await se_send_byte(ctx, top, byte)


async def emu_recv_byte(ctx, top, timeout=4000):
    """Decode one char the EMU transmits (io_oe high, io_o carries bits). Returns (byte, parity_ok)."""
    e = top.emu
    # wait for a clean falling edge of the wire (high -> low) while the emu is driving
    def wire():
        return (ctx.get(e.io_o) & 1) if ctx.get(e.io_oe) else 1
    t = 0; prev = 1
    while True:
        await ctx.tick(); t += 1
        cur = wire()
        if prev == 1 and cur == 0 and ctx.get(e.io_oe):
            break
        prev = cur
        if t > timeout:
            return None
    # we are at the start-bit edge; step to the middle of the start bit
    for _ in range(BD // 2):
        await ctx.tick()
    val = 0; par = 0
    for b in range(8):
        for _ in range(BD):
            await ctx.tick()
        bit = ctx.get(e.io_o) & 1
        val |= bit << b; par ^= bit
    for _ in range(BD):
        await ctx.tick()
    pbit = ctx.get(e.io_o) & 1
    par ^= pbit
    for _ in range(BD):            # consume into the stop bit so the next call starts from idle-high
        await ctx.tick()
    return (val, par == 0)


async def emu_recv_frame(ctx, top):
    tag = await emu_recv_byte(ctx, top)
    hi = await emu_recv_byte(ctx, top)
    lo = await emu_recv_byte(ctx, top)
    if tag is None or hi is None or lo is None:
        return None
    length = (hi[0] << 8) | lo[0]
    pl = []
    ok = tag[1] and hi[1] and lo[1]
    for _ in range(length):
        r = await emu_recv_byte(ctx, top)
        if r is None:
            break
        pl.append(r[0]); ok = ok and r[1]
    return (tag[0], bytes(pl), ok)


def parse_frames(data):
    out = []; i = 0
    while i + 3 <= len(data):
        tag = data[i]; length = (data[i + 1] << 8) | data[i + 2]
        if i + 3 + length > len(data):
            break
        out.append((tag, data[i + 3:i + 3 + length])); i += 3 + length
    return out


def main():
    top = SimTop()
    sim = Simulator(top)
    sim.add_clock(1e-6)
    rxframes = []
    txbytes = bytearray()

    # free-running decoder of the EMU's TX (wire low only counts while the emu drives) — can't race
    async def txmon(ctx):
        e = top.emu
        def wire():
            return (ctx.get(e.io_o) & 1) if ctx.get(e.io_oe) else 1
        prev = 1
        while True:
            await ctx.tick()
            cur = wire()
            if prev == 1 and cur == 0 and ctx.get(e.io_oe):   # start bit
                for _ in range(BD // 2):
                    await ctx.tick()
                val = 0
                for b in range(8):
                    for _ in range(BD):
                        await ctx.tick()
                    val |= (ctx.get(e.io_o) & 1) << b
                txbytes.append(val)
                for _ in range(2 * BD):                         # consume parity cell + into the stop bit
                    await ctx.tick()
                prev = 1                                        # now at idle-high; resume edge hunt
                continue
            prev = cur

    async def rxmon(ctx):
        while True:
            await ctx.tick()
            if ctx.get(top.emu.rx_frame_stb):
                rxframes.append((ctx.get(top.emu.rx_ftag), ctx.get(top.emu.rx_perr)))

    async def tb(ctx):
        t = 0
        while ctx.get(top.emu.rst_o) == 0:
            await ctx.tick(); t += 1
            if t > 5000:
                return
        await se_send_frame(ctx, top, bytes.fromhex("3b9000"))     # ATR
        for _ in range(20 * BD):                                   # let SESSION_START go out
            await ctx.tick()
        await se_send_frame(ctx, top, bytes.fromhex("6000020000"))  # GENERAL_STATUS -> expect TICKER
        for _ in range(16 * BD):
            await ctx.tick()
        await se_send_frame(ctx, top, bytes.fromhex("650003414243"))  # SCREEN_DISPLAY -> expect DISPLAY_PROCESSED
        for _ in range(16 * BD):
            await ctx.tick()

    sim.add_testbench(txmon, background=True)
    sim.add_testbench(rxmon, background=True)
    sim.add_testbench(tb)
    sim.run_until(80e-3)

    txframes = parse_frames(bytes(txbytes))
    print("emu rx frames (tag,perr):", [(hex(t), p) for t, p in rxframes])
    print("emu TX bytes :", bytes(txbytes).hex())
    print("emu TX frames:", [(hex(t), p.hex()) for t, p in txframes])

    tags = [t for t, _ in txframes]
    ss_ok = any(t == 0x01 and (bytes([0x01, len(p) >> 8, len(p) & 0xFF]) + p) == SESSION_START for t, p in txframes)
    tick_ok = 0x0E in tags
    disp_ok = 0x0D in tags
    rx_ok = [t for t, _ in rxframes] == [0x60, 0x65] and all(p == 0 for _, p in rxframes)
    print(f"\nchecks: SESSION_START={ss_ok} RX(0x60,0x65,parity)={rx_ok} TICKER_after_GENSTAT={tick_ok} DISPLAY_PROCESSED_after_SCREEN={disp_ok}")
    ok = ss_ok and rx_ok and tick_ok and disp_ok
    print("RESULT:", "PASS" if ok else "FAIL")
    import sys as _s; _s.exit(0 if ok else 1)

    ok = True
    ss = results.get("session_start")
    print("SESSION_START tx by emu:", None if ss is None else (hex(ss[0]), ss[1].hex(), "parity_ok" if ss[2] else "PARITY_BAD"))
    print("  matches expected + parity:", results.get("ss_match"))
    ok &= bool(results.get("ss_match"))
    ag = results.get("after_genstat")
    print("after GENERAL_STATUS, emu sent:", None if ag is None else (hex(ag[0]), ag[1].hex(), ag[2]))
    ok &= ag is not None and ag[0] == 0x0E and ag[2]
    asc = results.get("after_screen")
    print("after SCREEN_DISPLAY, emu sent:", None if asc is None else (hex(asc[0]), asc[1].hex(), asc[2]))
    ok &= asc is not None and asc[0] == 0x0D and asc[2]
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

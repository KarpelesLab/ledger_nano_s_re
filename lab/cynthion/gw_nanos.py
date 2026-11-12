# Cynthion r1.4 top-level for the Nano S SEPROXYHAL MCU emulator.
#
# Minimal self-contained ECP5 platform (avoids the luna/amaranth-0.5 `Record` clash) with just
# what we need: the 60 MHz clock, the user LEDs, and PMOD A pins 1/2/3 = RST/CLK/IO.
# Wiring (user, 2026-11-13): A1=RST, A2=CLK, A3=IO (open-drain, external 10k pull-up to 3V3);
# the SE is externally powered, GND common with the Cynthion.
#
# Build + flash (volatile) :
#   source ~/oss-cad-suite/environment
#   python3 gw_nanos.py            # -> build/top.bit
#   apollo configure build/top.bit # load into the FPGA (SRAM; gone on power cycle)
#
# LEDs: LED0 = booted (SESSION_START sent). LED1 toggles on every SE frame received (link alive).
# LED2 toggles on every SCREEN_DISPLAY (0x65) frame — i.e. the SE is drawing the screen.

import os
from amaranth import *
from amaranth.build import Resource, Subsignal, Pins, Clock, Attrs, Connector
from amaranth.vendor import LatticeECP5Platform
from amaranth.lib.fifo import SyncFIFO
from amaranth_boards.resources import LEDResources

from nanos_mcuemu import NanoSMcuEmu, TAG_SCREEN_DISPLAY


class UartTx(Elaboratable):
    """Minimal 8N1 UART transmitter. `divisor` = sync_freq / baud."""
    def __init__(self, divisor):
        self.divisor = divisor
        self.data = Signal(8)
        self.stb = Signal()
        self.rdy = Signal()
        self.tx = Signal(reset=1)

    def elaborate(self, platform):
        m = Module()
        div = Signal(range(self.divisor)); cnt = Signal(4); sh = Signal(8)
        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += [self.tx.eq(1), self.rdy.eq(1)]
                with m.If(self.stb):
                    m.d.sync += [sh.eq(self.data), div.eq(self.divisor - 1), cnt.eq(0)]
                    m.next = "START"
            with m.State("START"):
                m.d.comb += self.tx.eq(0)
                with m.If(div == 0): m.d.sync += div.eq(self.divisor - 1); m.next = "DATA"
                with m.Else():       m.d.sync += div.eq(div - 1)
            with m.State("DATA"):
                m.d.comb += self.tx.eq(sh[0])
                with m.If(div == 0):
                    m.d.sync += [sh.eq(Cat(sh[1:8], 0)), cnt.eq(cnt + 1), div.eq(self.divisor - 1)]
                    with m.If(cnt == 7): m.next = "STOP"
                with m.Else():
                    m.d.sync += div.eq(div - 1)
            with m.State("STOP"):
                m.d.comb += self.tx.eq(1)
                with m.If(div == 0): m.next = "IDLE"
                with m.Else():       m.d.sync += div.eq(div - 1)
        return m


class CynthionR14(LatticeECP5Platform):
    device = "LFE5U-12F"
    package = "BG256"
    speed = os.getenv("ECP5_SPEED_GRADE", "8")
    default_clk = "clk_60MHz"
    resources = [
        Resource("clk_60MHz", 0, Pins("A8", dir="i"), Clock(60e6), Attrs(IO_TYPE="LVCMOS33")),
        *LEDResources(pins="E13 C13 B14 A15 D12 C11", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),
        # PMOD A pins 1/2/3 (balls C9/B9/D11) = RST/CLK/IO
        Resource("sc_rst", 0, Pins("C9", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("sc_clk", 0, Pins("B9", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("sc_io", 0, Pins("D11", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        # UART to the Apollo debug controller -> host CDC-ACM (/dev/ttyACM1)
        Resource("uart", 0,
                 Subsignal("rx", Pins("R14", dir="i")),
                 Subsignal("tx", Pins("T14", dir="o"), Attrs(PULLMODE="UP")),
                 Attrs(IO_TYPE="LVCMOS33")),
    ]
    connectors = [Connector("pmod", 0, "C9 B9 D11 C12 - - C8 D8 D9 C10 - -")]

    def toolchain_program(self, products, name):
        pass  # we flash via apollo, not the platform


class Top(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        # 60 MHz sync domain. CLK = 60MHz/(2*clk_div); clk_div=16 -> 1.875 MHz (ISO 7816 range).
        # etu = 372 CLK cycles. reset held ~0.7 ms; ATR-done after a short idle gap.
        m.submodules.emu = emu = NanoSMcuEmu(
            clk_div=16, etu_clk=372, rst_clk=40_000, atr_idle=300_000,
            tick_div=6_000_000, tick_ms=100,
        )
        # The Apollo UART pins (R14/T14) are shared with JTAG (TDI/TMS). A bitstream that claims
        # T14 breaks `apollo configure` (JTAG), so the UART readback is only usable when the
        # bitstream is loaded from SPI flash, not JTAG. Default build is JTAG-safe (no UART).
        use_uart = os.getenv("UART", "0") == "1"
        rst = platform.request("sc_rst", 0)
        clk = platform.request("sc_clk", 0)
        io = platform.request("sc_io", 0)
        led0 = platform.request("led", 0)
        led1 = platform.request("led", 1)
        led2 = platform.request("led", 2)

        m.d.comb += [
            rst.o.eq(emu.rst_o),
            clk.o.eq(emu.clk_o),
            # open-drain I/O: drive low only; release (Hi-Z, pull-up -> 1) otherwise
            io.o.eq(0),
            io.oe.eq(emu.io_oe & ~emu.io_o),
            emu.io_i.eq(io.i),
            led0.o.eq(emu.booted),
        ]

        if use_uart:
            # Stream every byte the SE sends us out the Apollo UART (60 MHz / 115200 = 521).
            # NOTE: T14 is JTAG TMS, so a UART build must be loaded from SPI flash, not `apollo
            # configure`. Build with UART=1.
            uart = platform.request("uart", 0)
            m.submodules.utx = utx = UartTx(divisor=521)
            m.submodules.fifo = fifo = SyncFIFO(width=8, depth=64)
            m.d.comb += [
                fifo.w_data.eq(emu.rx_byte),
                fifo.w_en.eq(emu.rx_byte_stb),
                utx.data.eq(fifo.r_data),
                utx.stb.eq(fifo.r_rdy & utx.rdy),
                fifo.r_en.eq(fifo.r_rdy & utx.rdy),
                uart.tx.o.eq(utx.tx),
            ]

        with m.If(emu.rx_frame_stb):
            m.d.sync += led1.o.eq(~led1.o)
        with m.If(emu.rx_frame_stb & ((emu.rx_ftag & 0x7f) == TAG_SCREEN_DISPLAY)):
            m.d.sync += led2.o.eq(~led2.o)
        return m


if __name__ == "__main__":
    CynthionR14().build(Top(), name="top", do_program=False)
    print("built build/top.bit")

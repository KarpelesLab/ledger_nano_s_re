# Cynthion r1.4 top: Nano S SEPROXYHAL MCU emulator + reticle USB-CDC-ACM on the AUX port.
#
# The SE's bytes (everything it sends us, incl. SCREEN_DISPLAY = the screen) are streamed out a
# USB serial port on the AUX USB connector, using reticle's usb_cdc_acm_ulpi IP (Verilog, read by
# yosys alongside the Amaranth design). The AUX port enumerates as /dev/ttyACM* (VID 1209 PID 0001)
# with no driver install; `cat /dev/ttyACMx` is the client.
#
# Clocking: the Cynthion PHYs take the 60 MHz ULPI clock FROM the FPGA (clk_dir='o'), so the whole
# design runs on the A8 60 MHz oscillator and we drive that clock out to the aux PHY on D16.
# The Cynthion swaps D+/D- between the PHY and the connector, so we set the PHY's SwapDP/DM
# vendor register (0x39 bit 1) via the IP's VENDOR_ADDR/VENDOR_DATA params.
#
# Build + program:
#   source ~/oss-cad-suite/environment
#   python3 gw_nanos_usb.py
#   /tmp/cargo-target/release/reticle program build_usb/top.bit
# Then read the SE stream:  cat /dev/ttyACM<aux>   (identify by VID:PID 1209:0001)

import os
from amaranth import *
from amaranth.build import Resource, Subsignal, Pins, Clock, Attrs
from amaranth.vendor import LatticeECP5Platform
from amaranth.lib.fifo import SyncFIFO
from amaranth_boards.resources import LEDResources

from nanos_mcuemu import NanoSMcuEmu

RETICLE_IP = os.path.expanduser("~/projects/reticle/ip/usb")
VERILOG = [
    f"{RETICLE_IP}/usb_device_fs/rtl/usb_fs_rx.v",
    f"{RETICLE_IP}/usb_device_fs/rtl/usb_fs_tx.v",
    f"{RETICLE_IP}/usb_device_fs/rtl/usb_ctrl_ep.v",
    f"{RETICLE_IP}/usb_device_fs/rtl/usb_device_fs.v",
    f"{RETICLE_IP}/usb_device_ulpi/rtl/usb_ulpi_link.v",
    f"{RETICLE_IP}/usb_device_ulpi/rtl/usb_device_ulpi.v",
    f"{RETICLE_IP}/usb_cdc_acm/rtl/usb_cdc_req.v",
    f"{RETICLE_IP}/usb_cdc_acm/rtl/usb_cdc_acm.v",
    f"{RETICLE_IP}/usb_cdc_acm/rtl/usb_cdc_acm_ulpi.v",
]


class CynthionR14(LatticeECP5Platform):
    device = "LFE5U-12F"
    package = "BG256"
    speed = os.getenv("ECP5_SPEED_GRADE", "8")
    default_clk = "clk_60MHz"
    resources = [
        Resource("clk_60MHz", 0, Pins("A8", dir="i"), Clock(60e6), Attrs(IO_TYPE="LVCMOS33")),
        *LEDResources(pins="E13 C13 B14 A15 D12 C11", attrs=Attrs(IO_TYPE="LVCMOS33"), invert=True),
        Resource("sc_rst", 0, Pins("C9", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("sc_clk", 0, Pins("B9", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("sc_io", 0, Pins("D11", dir="io"), Attrs(IO_TYPE="LVCMOS33")),
        # AUX ULPI PHY (explicit resources; rst active-low = the IP's ulpi_rst_n directly)
        Resource("aux_ulpi", 0,
                 Subsignal("data", Pins("F16 G15 G16 H15 J15 J16 K15 K16", dir="io")),
                 Subsignal("clk", Pins("D16", dir="o")),
                 Subsignal("dir", Pins("E16", dir="i")),
                 Subsignal("nxt", Pins("F15", dir="i")),
                 Subsignal("stp", Pins("E15", dir="o")),
                 Subsignal("rst", Pins("J13", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33", SLEWRATE="FAST", PULLMODE="NONE")),
    ]
    connectors = []

    def toolchain_program(self, products, name):
        pass


class Top(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        for f in VERILOG:
            platform.add_file(os.path.basename(f), open(f).read())

        m.submodules.emu = emu = NanoSMcuEmu(
            clk_div=16, etu_clk=372, rst_clk=40_000, atr_idle=300_000,
            tick_div=6_000_000, tick_ms=100,
        )
        rst = platform.request("sc_rst", 0)
        clk = platform.request("sc_clk", 0)
        io = platform.request("sc_io", 0)
        ulpi = platform.request("aux_ulpi", 0)
        led0 = platform.request("led", 0)
        led1 = platform.request("led", 1)
        led2 = platform.request("led", 2)
        led3 = platform.request("led", 3)

        m.d.comb += [
            rst.o.eq(emu.rst_o),
            clk.o.eq(emu.clk_o),
            io.o.eq(0),
            io.oe.eq(emu.io_oe & ~emu.io_o),
            emu.io_i.eq(io.i),
            ulpi.clk.o.eq(ClockSignal("sync")),   # source the 60 MHz ULPI clock to the PHY
        ]

        # FIFO of SE->us bytes, drained into the CDC IN (device->host) stream.
        # DIAGNOSTIC: also inject a 0x55 heartbeat every ~0.14 s. If the host sees periodic 0x55,
        # the real-mode read path works; SE bytes appear interspersed when the emulator receives them.
        m.submodules.fifo = fifo = SyncFIFO(width=8, depth=512)
        # status latches so we can see the emulator state over USB (more reliable than LEDs)
        rx_seen = Signal(); frame_seen = Signal()
        with m.If(emu.rx_byte_stb): m.d.sync += rx_seen.eq(1)
        with m.If(emu.rx_frame_stb): m.d.sync += frame_seen.eq(1)
        status = Cat(C(0, 4), emu.booted, rx_seen, frame_seen, C(1, 1))  # 0x80 | flags
        hbcnt = Signal(23)
        m.d.sync += hbcnt.eq(hbcnt + 1)
        hb = hbcnt == 0
        m.d.comb += [
            fifo.w_data.eq(Mux(emu.rx_byte_stb, emu.rx_byte, status)),
            fifo.w_en.eq(emu.rx_byte_stb | hb),
        ]

        # power-on reset (matches the proven reticle reference): hold the USB core in reset
        # until a 1 has shifted through POR flops.
        por = Signal(16)
        m.d.sync += por.eq(Cat(C(1, 1), por[0:15]))
        reset_done = por[15]

        # Hand each FIFO byte to the IN endpoint and commit it with the byte (proven reference
        # pattern in testdata/fpga/cynthion/usb_cdc_uart.v): give = data available & endpoint ready.
        in_ready = Signal()
        give = Signal()
        in_data = Signal(8)
        test = os.getenv("TEST", "0") == "1"
        if test:
            # TEST mode: ignore the SE, flood the CDC with an incrementing byte to prove the USB path
            tb = Signal(8)
            m.d.comb += [give.eq(in_ready), in_data.eq(tb)]
            with m.If(give):
                m.d.sync += tb.eq(tb + 1)
        else:
            m.d.comb += [give.eq(fifo.r_rdy & in_ready), in_data.eq(fifo.r_data)]

        configured = Signal(); phy_ready = Signal()
        m.submodules.cdc = Instance(
            "usb_cdc_acm_ulpi",
            p_VID=0x1209, p_PID=0x0001,
            p_VENDOR_ADDR=0x39, p_VENDOR_DATA=0x06,   # USB3343 SwapDP/DM (value from reticle's working ref)
            i_clk60=ClockSignal("sync"),
            i_rst_n=reset_done,
            i_ulpi_data_i=ulpi.data.i,
            o_ulpi_data_o=ulpi.data.o,
            o_ulpi_data_oe=ulpi.data.oe,
            i_ulpi_dir=ulpi.dir.i,
            i_ulpi_nxt=ulpi.nxt.i,
            o_ulpi_stp=ulpi.stp.o,
            o_ulpi_rst_n=ulpi.rst.o,
            # device -> host: our SE byte stream
            i_in_data=in_data,
            i_in_valid=give,
            o_in_ready=in_ready,
            i_in_commit=give,
            # host -> device: discard
            i_out_ready=Const(1),
            i_serial_state=Const(0b000_0011),
            o_configured=configured,
            o_phy_ready=phy_ready,
        )
        m.d.comb += fifo.r_en.eq(give)

        # diagnostics: latch whether the CDC ever offered in_ready and whether a byte ever transferred
        latch_ready = Signal(); latch_give = Signal()
        with m.If(in_ready):
            m.d.sync += latch_ready.eq(1)
        with m.If(give):
            m.d.sync += latch_give.eq(1)
        m.d.comb += [
            led0.o.eq(emu.booted),       # user LED5
            led1.o.eq(latch_ready),      # user LED4: CDC asserted in_ready at least once
            led2.o.eq(latch_give),       # user LED3: a byte was handed to the CDC at least once
            led3.o.eq(configured),       # user LED2
        ]
        return m


if __name__ == "__main__":
    CynthionR14().build(Top(), name="top", do_program=False, build_dir="build_usb")
    print("built build_usb/top.bit")

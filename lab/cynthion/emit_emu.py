from amaranth.back import verilog
from nanos_mcuemu import NanoSMcuEmu
m = NanoSMcuEmu(clk_div=16, etu_clk=372, rst_clk=40_000, atr_idle=60_000, tick_div=6_000_000, tick_ms=100)
ports = [m.io_i, m.io_o, m.io_oe, m.clk_o, m.rst_o, m.rx_byte, m.rx_byte_stb, m.rx_frame_stb, m.rx_ftag, m.booted]
open("nanos_emu.v","w").write(verilog.convert(m, name="nanos_emu", ports=ports))
print("emitted nanos_emu.v", sum(1 for _ in open("nanos_emu.v")), "lines")

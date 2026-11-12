#!/usr/bin/env python3
"""Bootstrap generator for the KiCad reconstruction of the Ledger Nano S board.

This script builds the *initial* project in kicad/ from measurements taken
on the stitched photos (see docs/kicad.md). Run it only to regenerate from
scratch. It OVERWRITES kicad/ledger_nano_s.{kicad_sch,kicad_pcb} and the
custom libraries, so any manual edits made in KiCad afterwards are lost.

Usage: python3 tools/gen_kicad.py   (needs KiCad 10's pcbnew Python module
and ImageMagick, and expects docs/img/stitched_front.jpg, stitched_front_bare.jpg
and stitched_back.jpg)
"""
import json
import base64, math, os, re, shutil, subprocess, sys, tempfile, uuid

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kicad")
PRJ = "ledger_nano_s"
KILIB = "/usr/share/kicad"
FPLIB = os.path.join(OUT, PRJ + ".pretty")
SYMLIB = os.path.join(OUT, PRJ + ".kicad_sym")

# --------------------------------------------------------------------------
# Geometry (mm). Board origin (top-left corner of the PCB, front view) is
# placed at (OX, OY) in KiCad. +x towards the far end (away from USB),
# +y towards the button edge.
# Measured on the stitched front image at 94.3 px/mm (half-res panorama),
# board corner at (322,143) px.
OX, OY = 100.0, 100.0
BW, BH = 35.66, 12.27
NOTCHES = [(2.19, 0.8), (17.27, 0.8)]       # (x centre, radius) on top edge


def G(x, y):
    """front half-res panorama px -> board mm"""
    return ((x - 322) / 94.3, (y - 143) / 94.3)


def Hb(x, y):
    """back (flopped) half-res panorama px -> board mm (front view coords)"""
    return ((x - 345) / 96.46, (y - 165) / 95.36)


def uid():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Parts: ref, lib:footprint, value, (x,y) mm, rotation, side, symbol
P = []


def part(ref, fp, val, pos, rot=0, side="F", sym=None, note=""):
    P.append(dict(ref=ref, fp=fp, val=val, pos=pos, rot=rot, side=side, sym=sym, note=note))


part("U1", "Package_DFN_QFN:UFQFPN-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm", "STM32F042K6U6",
     G(1197, 732), 180, sym="MCU_ST_STM32F0:STM32F042K6Ux")
part("U2", PRJ + ":ST_DFN8-1EP_4.0x4.2mm_P0.98mm", "ST31 SE (NBO PHL744 7B)", G(1862, 1078), 0,
     sym=PRJ + ":SE_ST31_DFN8")
part("U3", "Package_TO_SOT_SMD:SOT-23-5", "LDO 3.0V (AD30)", G(1912, 485), 0, sym=PRJ + ":LDO_SOT23-5")
part("U4", "Package_DFN_QFN:DFN-8-1EP_4x4mm_P0.8mm_EP2.3x3.24mm", "ST8R00", G(3435, 401), 180,
     sym=PRJ + ":ST8R00")
part("L1", "Inductor_SMD:L_Abracon_ASPI-3012S", "10uH", G(3497, 787), 90, sym="Device:L")
part("J1", "Connector_USB:USB_Micro-B_Molex-105017-0001", "USB_B_Micro", None, -90,
     sym="Connector:USB_B_Micro")
part("J2", PRJ + ":FPC_12P_P0.5mm_Pin1Top", "OLED FPC 12p", G(2225, 785), 0, sym="Connector_Generic:Conn_01x12")
part("S1", PRJ + ":SW_SideTact_P3.8x1.38mm", "SW_Push", G(3145, 1175), 0, sym="Switch:SW_Push")
part("S2", PRJ + ":SW_SideTact_P3.8x1.38mm", "SW_Push", G(1140, 1170), 0, sym="Switch:SW_Push")
for ref, xy, rot, pkg in [
        ("C1", (2945, 648), 0, "0603"), ("C2", (1480, 1095), 90, "0402"), ("C3", (3477, 1035), 90, "0402"),
        ("C5", (967, 395), 0, "0402"), ("C7", (3077, 760), 0, "0603"), ("C8", (3077, 865), 0, "0603"),
        ("C9", (3077, 977), 0, "0603"), ("C10", (1782, 815), 0, "0402"), ("C12", (1660, 482), 0, "0402")]:
    part(ref, "Capacitor_SMD:C_%s_%sMetric" % (pkg, {"0402": "1005", "0603": "1608"}[pkg]), "C?", G(*xy), rot,
         sym="Device:C")
for ref, xy, rot in [("R1", (1632, 815), 0), ("R2", (2920, 375), 90), ("R4", (2995, 375), 90), ("R3", (3070, 545), 0)]:
    part(ref, "Resistor_SMD:R_0402_1005Metric", "R?", G(*xy), rot, sym="Device:R")
# 5-pad programming/test header on the back (pin 1 = dot, nearest USB)
for i, x in enumerate([805, 1045, 1285, 1525, 1765]):
    part("TP%d" % (i + 1), "TestPoint:TestPoint_Pad_D1.5mm", "HDR%d" % (i + 1), Hb(x, 295), 0, "B",
         sym="Connector:TestPoint")
# other solder-bumped test pads on the back
for i, xy in enumerate([(2735, 350), (2500, 520), (1830, 775), (2740, 775), (3185, 770),
                        (2285, 995), (2500, 995), (2735, 995), (3025, 995)]):
    part("TP%d" % (i + 6), "TestPoint:TestPoint_Pad_D1.0mm", "TP", Hb(*xy), 0, "B", sym="Connector:TestPoint")

# Nets traced from the photos (see docs/tracing.md for evidence and confidence).
NETS = {
    "GND": [("J1", "5"), ("J1", "SH"), ("U1", "33"), ("U2", "2"), ("C2", "1"), ("C5", "2"), ("TP3", "1"),
            ("U3", "2"), ("C12", "2")],
    "VBUS": [("J1", "1"), ("U3", "1"), ("U3", "3"), ("C12", "1"),
             ("L1", "1"), ("U4", "4"), ("C3", "2")],
    "+3V0": [("U1", "1"), ("U1", "5"), ("U1", "17"), ("U3", "5"), ("TP1", "1"), ("C5", "1"), ("U2", "7"), ("C2", "2"),
             ("R1", "2"), ("C10", "1"), ("J2", "4"), ("U4", "6")],
    "USB_DM": [("J1", "2"), ("U1", "21")],
    "USB_DP": [("J1", "3"), ("U1", "22")],
    "SWDIO": [("U1", "23"), ("TP4", "1")],
    "SWCLK": [("U1", "24"), ("TP2", "1")],
    "NRST": [("U1", "4"), ("TP5", "1"), ("R1", "1")],
    "SE_CLK": [("U2", "5"), ("U1", "18")],
    "SE_RST": [("U2", "6"), ("U1", "20")],
    "SE_IO": [("U2", "3"), ("U1", "19")],  # PA9 = USART1_TX (back trace, XCF)
    # OLED connector J2 (traced in pics/20261112_183853.xcf)
    "PA0": [("U1", "6"), ("J2", "7")],
    "PA1": [("U1", "7"), ("J2", "5")],
    "PA2": [("U1", "8"), ("J2", "6")],
    "PA5": [("U1", "11"), ("J2", "8")],
    "PA7": [("U1", "13"), ("J2", "9")],
    "J2_P1": [("J2", "1"), ("U4", "8"), ("R3", "2"), ("C1", "2")],
    "J2_P10": [("J2", "10"), ("R2", "2")],
    "J2_P11": [("J2", "11"), ("C7", "1")],
    "J2_P12": [("J2", "12"), ("C8", "1"), ("C9", "1")],
    # ST8R00 boost
    "BOOST_SW": [("U4", "1"), ("L1", "2")],
    "U4_P5": [("U4", "5"), ("R4", "2"), ("R3", "1")],
    # buttons
    "PA15": [("U1", "25"), ("S2", "1")],
    "PB7": [("U1", "30"), ("S1", "1")],  # back trace, XCF
}

# Pads with no drawn trace: the trace drawings cover everything except the GND pour, so
# untraced pads are taken as GND (U1 16/32 = VSS and 31 = BOOT0 by datasheet; the other
# untraced U1 pins are unused GPIOs and stay unconnected). U2: only pin 2 is GND (checked
# on the board); pins 1, 4, 8 and the exposed pad are not connected.
NETS["GND"] += [("C1", "1"), ("C3", "1"), ("C7", "2"), ("C8", "2"), ("C9", "2"), ("C10", "2"),
                ("R2", "1"), ("R4", "1"), ("S1", "2"), ("S2", "2"), ("J1", "4"),
                ("J2", "2"), ("J2", "3"), ("J2", "MP"), ("U1", "16"), ("U1", "31"), ("U1", "32"),
                ("U3", "4"),
                ("U4", "2"), ("U4", "3"), ("U4", "7"), ("U4", "9")]

# Placeholder nets that turned out to be the same as a named net (from the XCF trace overlay).
MERGE = {"N_TP6": "J2_P10", "N_TP7": "PA2", "N_TP8": "PA1", "N_TP9": "PA5", "N_TP10": "J2_P1",
         "N_TP11": "PA0", "N_TP12": "PA7", "N_TP13": "J2_P12", "N_TP14": "J2_P11", "N_V51": "U4_P5", "PA9": "SE_IO", "SE_P3": "SE_IO", "S1_P1": "PB7",
         "U3_P5": "VBUS"}

# Vias found on both sides (board mm, front view) and the net they were traced to.
# None = net not determined. False positives from silkscreen were removed.
VIAS = [
    (3.80, 2.42, "+3V0"), (5.47, 7.49, "SWDIO"), (5.74, 4.16, "SE_CLK"), (5.70, 5.18, "PA9"),
    (5.97, 6.03, "SE_RST"), (5.84, 8.73, "SWCLK"), (5.60, 11.28, "GND"), (6.91, 3.65, "+3V0"),
    (8.19, 5.26, "GND"), (8.18, 6.35, "GND"), (8.17, 7.44, "GND"), (8.54, 2.72, "VBUS"),
    (9.27, 5.17, "GND"), (9.24, 6.26, "GND"), (9.28, 7.43, "GND"), (8.98, 9.86, "PB7"),
    (10.35, 5.26, "GND"), (10.36, 6.36, "GND"), (10.37, 7.43, "GND"), (11.42, 2.66, "VBUS"),
    (11.63, 8.84, "+3V0"), (13.04, 4.69, "PA2"), (12.64, 6.70, "NRST"), (12.93, 8.55, "SE_CLK"),
    (13.18, 9.42, "SE_RST"), (13.77, 6.03, "+3V0"), (16.93, 3.59, "GND"), (16.60, 5.57, "N_TP8"),
    (16.87, 7.30, "GND"), (17.54, 6.18, "PA2"), (19.14, 2.33, "U3_P5"), (18.78, 3.56, "+3V0"),
    (18.75, 5.59, "+3V0"), (19.94, 3.16, "GND"), (19.69, 11.51, "GND"), (21.17, 10.60, "SE_P3"),
    (21.64, 5.11, "N_TP10"), (21.74, 6.62, "N_TP11"), (23.39, 5.29, "N_TP7"), (23.20, 7.42, "N_TP12"),
    (24.28, 4.55, "N_TP9"), (25.24, 3.72, "N_TP6"), (25.92, 11.53, "GND"), (26.57, 3.92, "GND"),
    (27.31, 7.11, "N_TP14"), (26.52, 8.82, "N_TP13"), (27.82, 4.32, "N_V51"), (29.29, 5.37, "N_TP10"),
    (29.65, 1.92, "N_V51"), (29.55, 3.00, "+3V0"), (29.76, 10.22, "S1_P1"), (31.07, 5.14, "GND"),
    (31.32, 8.87, "GND"), (31.56, 6.93, "U3_P5"),
    (32.36, 1.53, "GND"), (32.37, 2.64, "GND"), (32.36, 3.74, "GND"),
    (33.46, 1.55, "GND"), (33.47, 2.64, "GND"), (33.49, 3.70, "GND"),
    # missed by the first pass (thermal-relief GND vias, confirmed on both sides)
    (21.06, 1.08, "GND"), (34.86, 9.20, "GND"),
]
# Back-side test pads whose net is a dedicated trace (pad position -> net)
TP_NETS = {(24.78, 1.94): "N_TP6", (22.34, 3.72): "N_TP7", (15.39, 6.40): "N_TP8", (24.83, 6.40): "N_TP9",
           (29.44, 6.34): "N_TP10", (20.11, 8.70): "N_TP11", (22.34, 8.70): "N_TP12", (24.78, 8.70): "N_TP13",
           (27.78, 8.70): "N_TP14"}

# --------------------------------------------------------------------------
# Custom footprints


def mm(v):
    return pcbnew.FromMM(v)


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def fp_line(fp, layer, a, b, w=0.1):
    s = pcbnew.PCB_SHAPE(fp)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a)); s.SetEnd(V(*b))
    s.SetLayer(layer); s.SetWidth(mm(w))
    fp.Add(s)


def fp_rect(fp, layer, x0, y0, x1, y1, w=0.1):
    for a, b in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        fp_line(fp, layer, a, b, w)


def smd(fp, num, x, y, w, h, shape=pcbnew.PAD_SHAPE_ROUNDRECT):
    p = pcbnew.PAD(fp)
    p.SetNumber(num); p.SetShape(shape); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    p.SetLayerSet(p.SMDMask()); p.SetSize(V(w, h)); p.SetPosition(V(x, y))
    if shape == pcbnew.PAD_SHAPE_ROUNDRECT:
        p.SetRoundRectRadiusRatio(0.25)
    fp.Add(p)
    return p


def pth(fp, num, x, y, w, h, drill):
    p = pcbnew.PAD(fp)
    p.SetNumber(num); p.SetShape(pcbnew.PAD_SHAPE_RECT); p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
    p.SetLayerSet(p.PTHMask()); p.SetSize(V(w, h)); p.SetDrillSize(V(drill, drill)); p.SetPosition(V(x, y))
    fp.Add(p)


def new_fp(name, descr):
    fp = pcbnew.FOOTPRINT(None)
    fp.SetFPID(pcbnew.LIB_ID(PRJ, name))
    fp.SetLibDescription(descr)
    fp.SetAttributes(pcbnew.FP_SMD)
    fp.Reference().SetText("REF**"); fp.Reference().SetLayer(pcbnew.F_SilkS)
    fp.Value().SetText(name); fp.Value().SetLayer(pcbnew.F_Fab)
    return fp



# --------------------------------------------------------------------------
# Simple VRML 3D models for the custom footprints (dimensions from the photos)
SHAPES = os.path.join(OUT, PRJ + ".3dshapes")
COL = {"black": (0.08, 0.08, 0.09), "metal": (0.75, 0.75, 0.78), "gold": (0.85, 0.68, 0.25),
       "white": (0.93, 0.92, 0.88), "kapton": (0.85, 0.62, 0.08), "dark": (0.18, 0.18, 0.2),
       "grey": (0.45, 0.45, 0.48)}


def vrml(name, boxes):
    """boxes: (x0, x1, y0, y1, z0, z1, colour[, transparency]) in footprint mm (y down)."""
    out = ["#VRML V2.0 utf8"]
    for b in boxes:
        x0, x1, y0, y1, z0, z1, c = b[:7]
        tr = b[7] if len(b) > 7 else 0
        k = 1 / 2.54                       # KiCad VRML unit = 0.1 inch
        cx, cy, cz = (x0 + x1) / 2 * k, -(y0 + y1) / 2 * k, (z0 + z1) / 2 * k
        r, g, bl = COL[c]
        out.append("Transform { translation %.4f %.4f %.4f children [ Shape { appearance Appearance { material "
                   "Material { diffuseColor %.3f %.3f %.3f specularColor 0.3 0.3 0.3 shininess 0.4 "
                   "transparency %.2f } } geometry Box { size %.4f %.4f %.4f } } ] }"
                   % (cx, cy, cz, r, g, bl, tr, abs(x1 - x0) * k, abs(y1 - y0) * k, abs(z1 - z0) * k))
    os.makedirs(SHAPES, exist_ok=True)
    open(os.path.join(SHAPES, name + ".wrl"), "w").write("\n".join(out) + "\n")
    return "${KIPRJMOD}/%s.3dshapes/%s.wrl" % (PRJ, name)


def add_model(fp, path):
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = path
    fp.Add3DModel(m)


def model_u2():
    b = [(-2.0, 2.0, -2.1, 2.1, 0.02, 0.55, "black"), (1.35, 1.65, 1.45, 1.75, 0.55, 0.56, "grey")]
    for i in range(4):
        y = (1.5 - i) * 0.98
        for x in (1.75, -2.0):
            b.append((x, x + 0.27, y - 0.17, y + 0.17, 0.0, 0.2, "metal"))
    return vrml("ST_DFN8_4.0x4.2mm", b)


def model_j2():
    b = [(0.6, 5.0, -4.0, 4.0, 0.0, 0.6, "dark"),          # housing
         (1.64, 5.14, -4.64, 4.64, 0.6, 0.95, "white"),     # flip-lock actuator (closed)
         (0.21, 1.64, -4.64, -3.95, 0.0, 0.95, "white"), (0.21, 1.64, 3.95, 4.64, 0.0, 0.95, "white"),
         (2.07, 4.3, -5.43, -4.64, 0.0, 0.15, "metal"), (2.07, 4.3, 4.64, 5.43, 0.0, 0.15, "metal")]
    for i in range(12):
        y = -2.75 + 0.5 * i
        b.append((-0.45, 0.7, y - 0.1, y + 0.1, 0.0, 0.12, "gold"))
    return vrml("FPC_12P_P0.5mm_FlipLock", b)


def model_sw():
    c = -0.5                                                 # body sits ~0.5 mm left of the land centre
    b = [(c - 1.75, c + 1.75, -1.15, 1.3, 0.0, 1.3, "metal"),
         (c - 1.45, c + 1.45, -1.0, 1.25, 1.3, 1.36, "kapton", 0.3),
         (c - 0.32, c + 0.32, 1.3, 1.8, 0.35, 0.95, "dark")]     # side plunger, past the board edge
    for x in (-1.9, 1.9):
        for y in (-0.69, 0.69):
            b.append((x - 0.6, x + 0.6, y - 0.3, y + 0.3, 0.0, 0.15, "metal"))
    return vrml("SW_SideTact_LedgerNanoS", b)

def build_footprints():
    if os.path.isdir(FPLIB):
        shutil.rmtree(FPLIB)
    os.makedirs(FPLIB)
    fps = []

    # U2: ST secure element. Measured on the bare-board photo: 8 pads 1.2x0.75mm,
    # pitch 0.98mm, pad columns 4.0mm apart, plus a 2.1x3.45mm exposed pad (no vias).
    fp = new_fp("ST_DFN8-1EP_4.0x4.2mm_P0.98mm",
                "ST secure element U2, DFN8 4.0x4.2mm body + exposed pad. Land pattern measured from the "
                "bare-board photo: pads 1.2x0.75mm, pitch 0.98mm, columns 4.0mm apart, EP 2.1x3.45mm. "
                "Pin 1 = package dot corner (bottom-right on the board), CCW numbering.")
    pitch, cx = 0.98, 2.0
    ys = [1.5 * pitch, 0.5 * pitch, -0.5 * pitch, -1.5 * pitch]
    for i, y in enumerate(ys):                     # pins 1-4 up the right side
        smd(fp, str(i + 1), cx, y, 1.2, 0.75)
    for i, y in enumerate(reversed(ys)):           # pins 5-8 down the left side
        smd(fp, str(i + 5), -cx, y, 1.2, 0.75)
    smd(fp, "9", 0, 0, 2.1, 3.45, pcbnew.PAD_SHAPE_RECT)
    fp_rect(fp, pcbnew.F_Fab, -2.0, -2.1, 2.0, 2.1)
    fp_line(fp, pcbnew.F_Fab, (1.5, 2.1), (2.0, 1.6))
    fp_rect(fp, pcbnew.F_CrtYd, -2.85, -2.4, 2.85, 2.4, 0.05)
    fp_line(fp, pcbnew.F_SilkS, (2.75, 2.25), (2.75, 2.24), 0.3)  # pin-1 dot
    add_model(fp, model_u2())
    fps.append(fp)

    # J2: 12-pin 0.5mm FPC, contacts on the left, pin 1 at top, mounting tabs to the right
    fp = new_fp("FPC_12P_P0.5mm_Pin1Top",
                "12-pin 0.5mm-pitch flip-lock FPC connector (OLED). Geometry measured from photos: "
                "contact row at x=0, mounting tabs at x=+3.13, y=+-4.54. Pin 1 at top as on board silk. "
                "Tab spacing matches Hirose FH12-12S, but the pin numbering is reversed.")
    fp.SetAttributes(pcbnew.FP_SMD)
    for i in range(12):
        smd(fp, str(i + 1), 0, -2.75 + 0.5 * i, 1.2, 0.3)
    smd(fp, "MP", 3.13, -4.54, 2.1, 1.8, pcbnew.PAD_SHAPE_RECT)
    smd(fp, "MP", 3.13, 4.54, 2.1, 1.8, pcbnew.PAD_SHAPE_RECT)
    fp_rect(fp, pcbnew.F_Fab, 0.4, -5.6, 5.4, 5.6)
    fp_rect(fp, pcbnew.F_CrtYd, -0.8, -6.2, 5.8, 6.2, 0.05)
    fp_line(fp, pcbnew.F_SilkS, (-0.9, -2.75), (-1.3, -2.75), 0.15)
    add_model(fp, model_j2())
    fps.append(fp)

    # S1/S2: side-actuated tact switch, 4 pads 1.75x1.0mm at x=+-1.9, y=+-0.69 (measured on the
    # bare board); the bottom pair (board-edge side) are plated through.
    fp = new_fp("SW_SideTact_P3.8x1.38mm",
                "Side-actuated SMD tact switch (S1/S2). Land pattern measured on the bare board: "
                "4 pads 1.75x1.0mm at x=+-1.9, y=+-0.69; the edge-side pair are plated through-holes. "
                "Actuator protrudes past the board edge (+y).")
    fp.SetAttributes(0)
    smd(fp, "1", -1.9, -0.69, 1.75, 1.0)
    smd(fp, "1", 1.9, -0.69, 1.75, 1.0)
    pth(fp, "2", -1.9, 0.69, 1.75, 1.0, 0.6)
    pth(fp, "2", 1.9, 0.69, 1.75, 1.0, 0.6)
    fp_rect(fp, pcbnew.F_Fab, -1.8, -1.2, 1.8, 1.2)
    fp_rect(fp, pcbnew.F_Fab, -0.8, 1.2, 0.8, 2.0)   # actuator
    fp_rect(fp, pcbnew.F_CrtYd, -3.0, -1.4, 3.0, 2.2, 0.05)
    add_model(fp, model_sw())
    fps.append(fp)

    io = pcbnew.PCB_IO_MGR.FindPlugin(pcbnew.PCB_IO_MGR.KICAD_SEXP)
    for fp in fps:
        io.FootprintSave(FPLIB, fp)


# --------------------------------------------------------------------------
# Custom symbols (generic, pin functions unknown unless observed)


def sym_text(name, pins_left, pins_right, w=10.16, descr="", ref="U", fp=""):
    """pins_*: list of (number, name, etype)"""
    n = max(len(pins_left), len(pins_right))
    h = (n + 1) * 2.54
    top = h / 2
    out = ['\t(symbol "%s"' % name,
           '\t\t(pin_names (offset 1.016))', '\t\t(exclude_from_sim no)', '\t\t(in_bom yes)', '\t\t(on_board yes)']
    for k, v, y in [("Reference", ref, top + 1.27), ("Value", name, -top - 1.27)]:
        out.append('\t\t(property "%s" "%s" (at 0 %.2f 0) (effects (font (size 1.27 1.27))))' % (k, v, y))
    out.append('\t\t(property "Footprint" "%s" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))' % fp)
    out.append('\t\t(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))')
    out.append('\t\t(property "Description" "%s" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))' % descr)
    out.append('\t\t(symbol "%s_0_1" (rectangle (start %.2f %.2f) (end %.2f %.2f) '
               '(stroke (width 0.254) (type default)) (fill (type background))))' % (name, -w / 2, top, w / 2, -top))
    out.append('\t\t(symbol "%s_1_1"' % name)
    for side, pins in [(-1, pins_left), (1, pins_right)]:
        for i, (num, pname, et) in enumerate(pins):
            y = top - 2.54 * (i + 1)
            x = side * (w / 2 + 2.54)
            ang = 0 if side < 0 else 180
            out.append('\t\t\t(pin %s line (at %.2f %.2f %d) (length 2.54) (name "%s" (effects (font (size 1.27 1.27)))) '
                       '(number "%s" (effects (font (size 1.27 1.27)))))' % (et, x, y, ang, pname, num))
    out.append('\t\t)')
    out.append('\t\t(embedded_fonts no)')
    out.append('\t)')
    return "\n".join(out)


def build_symbols():
    syms = [
        sym_text("SE_ST31_DFN8",
                 [("5", "P5_MCU", "bidirectional"), ("6", "P6_MCU", "bidirectional"), ("7", "VCC", "power_in"),
                  ("8", "P8", "unspecified")],
                 [("4", "P4", "unspecified"), ("3", "P3", "bidirectional"), ("2", "GND", "power_in"),
                  ("1", "P1", "unspecified"), ("9", "EP", "passive")],
                 w=17.78,
                 descr="ST31-family secure element (marking NBO PHL744 7B). Pinout from board observation; "
                       "P5/P6 go to the STM32 (I/O and RESET?), P3 unknown destination.",
                 fp=PRJ + ":ST_DFN8-1EP_4.0x4.2mm_P0.98mm"),
        sym_text("ST8R00",
                 [("1", "P1", "unspecified"), ("2", "P2", "unspecified"), ("3", "P3", "unspecified"),
                  ("4", "P4", "unspecified")],
                 [("8", "P8", "unspecified"), ("7", "P7", "unspecified"), ("6", "P6", "unspecified"),
                  ("5", "P5", "unspecified"), ("9", "EP", "passive")],
                 descr="ST8R00 synchronous step-up DC-DC (4-6V in, 6-12V out, DFN8 4x4). "
                       "Pin names TODO from datasheet.",
                 fp="Package_DFN_QFN:DFN-8-1EP_4x4mm_P0.8mm_EP2.3x3.24mm"),
        sym_text("LDO_SOT23-5",
                 [("1", "P1", "unspecified"), ("2", "P2", "unspecified"), ("3", "P3", "unspecified")],
                 [("5", "P5", "unspecified"), ("4", "P4", "unspecified")],
                 descr="SOT-23-5 regulator marked AD30 (likely 3.0V LDO). Pin functions TODO.",
                 fp="Package_TO_SOT_SMD:SOT-23-5"),
    ]
    with open(SYMLIB, "w") as f:
        f.write('(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "gen_kicad.py")\n\t(generator_version "10.0")\n')
        f.write("\n".join(syms))
        f.write("\n)\n")


# --------------------------------------------------------------------------
# Tiny S-expression helpers to pull symbols out of KiCad libraries


def sexpr_block(text, start):
    depth, i, instr = 0, start, False
    while True:
        c = text[i]
        if instr:
            if c == "\\":
                i += 1
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


_libcache = {}


def lib_symbol(libid):
    lib, name = libid.split(":")
    path = SYMLIB if lib == PRJ else os.path.join(KILIB, "symbols", lib + ".kicad_sym")
    if path not in _libcache:
        _libcache[path] = open(path).read()
    text = _libcache[path]
    idx = text.find('(symbol "%s"' % name)
    blk = sexpr_block(text, idx)
    m = re.search(r'\(extends "([^"]+)"\)', blk)
    if m:  # flatten: take the parent body, rename it, keep child's properties
        base = lib_symbol(lib + ":" + m.group(1))
        base = base.replace('(symbol "%s:%s"' % (lib, m.group(1)), '(symbol "%s"' % libid, 1)
        base = base.replace('"%s_' % m.group(1), '"%s_' % name)
        return base
    return blk.replace('(symbol "%s"' % name, '(symbol "%s"' % libid, 1)


def sym_pins(block):
    pins = []
    for m in re.finditer(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\).*?\(number "([^"]*)"', block, re.S):
        pins.append((m.group(4), float(m.group(1)), float(m.group(2)), int(float(m.group(3)))))
    return pins


# --------------------------------------------------------------------------
def build_schematic(sym_uuids):
    root = uid()
    used = sorted(set(p["sym"] for p in P))
    libs = {s: lib_symbol(s) for s in used}
    # net lookup
    pinnet = {}
    for net, pins in NETS.items():
        for ref, num in pins:
            pinnet[(ref, num)] = net

    # layout: simple grid, grouped
    layout = {"U1": (80, 80), "J1": (30, 80), "U2": (150, 70), "U3": (40, 140), "U4": (150, 140), "L1": (130, 130),
              "J2": (220, 80), "S1": (200, 140), "S2": (200, 155)}
    x0, y0 = 30, 175
    misc = [p for p in P if p["ref"] not in layout and not p["ref"].startswith("TP")]
    for i, p in enumerate(sorted(misc, key=lambda p: (p["ref"][0], int(p["ref"][1:])))):
        layout[p["ref"]] = (x0 + 15 * (i % 14), y0)
    tps = [p for p in P if p["ref"].startswith("TP")]
    for i, p in enumerate(sorted(tps, key=lambda p: int(p["ref"][2:]))):
        layout[p["ref"]] = (30 + 15 * (i % 14), 200 + 15 * (i // 14))

    out = ['(kicad_sch', '\t(version 20250114)', '\t(generator "gen_kicad.py")', '\t(generator_version "9.0")',
           '\t(uuid "%s")' % root, '\t(paper "A3")',
           '\t(title_block (title "Ledger Nano S - reconstruction") (comment 1 "Generated from photos; nets are partial, see docs/kicad.md"))',
           '\t(lib_symbols']
    for s in used:
        out.append(libs[s])
    out.append('\t)')

    for p in P:
        sx, sy = layout[p["ref"]]
        sx, sy = round(sx / 1.27) * 1.27, round(sy / 1.27) * 1.27
        pins = sym_pins(libs[p["sym"]])
        su = sym_uuids[p["ref"]]
        out.append('\t(symbol (lib_id "%s") (at %.2f %.2f 0) (unit 1) (exclude_from_sim no) (in_bom yes) '
                   '(on_board yes) (dnp no) (uuid "%s")' % (p["sym"], sx, sy, su))
        props = [("Reference", p["ref"], -6), ("Value", p["val"], 6), ("Footprint", p["fp"], 0)]
        for k, v, dy in props:
            hide = " (hide yes)" if k == "Footprint" else ""
            out.append('\t\t(property "%s" "%s" (at %.2f %.2f 0) (effects (font (size 1.27 1.27))%s))'
                       % (k, v, sx, sy + dy, hide))
        if p["note"]:
            out.append('\t\t(property "Note" "%s" (at %.2f %.2f 0) (effects (font (size 1.27 1.27)) (hide yes)))'
                       % (p["note"], sx, sy))
        for num in sorted(set(n for n, *_ in pins)):
            out.append('\t\t(pin "%s" (uuid "%s"))' % (num, uid()))
        out.append('\t\t(instances (project "%s" (path "/%s" (reference "%s") (unit 1))))' % (PRJ, root, p["ref"]))
        out.append('\t)')
        # labels on connected pins
        seen = set()
        for num, px, py, ang in pins:
            net = pinnet.get((p["ref"], num))
            if not net or (num, px, py) in seen:
                continue
            seen.add((num, px, py))
            ax, ay = sx + px, sy - py
            lang = {0: 180, 180: 0, 90: 270, 270: 90}[ang]
            just = "right" if lang in (180, 270) else "left"
            out.append('\t(label "%s" (at %.2f %.2f %d) (effects (font (size 1.27 1.27)) (justify %s bottom)) (uuid "%s"))'
                       % (net, ax, ay, lang, just, uid()))
    out.append('\t(sheet_instances (path "/" (page "1")))')
    out.append('\t(embedded_fonts no)')
    out.append(')')
    with open(os.path.join(OUT, PRJ + ".kicad_sch"), "w") as f:
        f.write("\n".join(out) + "\n")
    return root


# --------------------------------------------------------------------------
def load_fp(fpid):
    lib, name = fpid.split(":")
    path = FPLIB if lib == PRJ else os.path.join(KILIB, "footprints", lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        sys.exit("footprint not found: " + fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def edge(board, a, b):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(OX + a[0], OY + a[1])); s.SetEnd(V(OX + b[0], OY + b[1]))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05))
    board.Add(s)


def notch(board, xc, r):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_ARC)
    s.SetArcGeometry(V(OX + xc - r, OY), V(OX + xc, OY + r), V(OX + xc + r, OY))
    s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.05))
    board.Add(s)


# Stock footprints whose own 3D model is not shipped with KiCad 10 -> closest shipped model
MODEL_SUB = {"U1": "Package_DFN_QFN.3dshapes/QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm.step",
             "U4": "Package_DFN_QFN.3dshapes/DFN-8-1EP_4x4mm_P0.8mm_EP2.5x3.6mm.step",
             "L1": "Inductor_SMD.3dshapes/L_Changjiang_FNR3012S.step",
             "J1": "Connector_USB.3dshapes/USB_Micro-B_Molex_47346-0001.step"}

# Reference labels as printed on the real board: (x, y, angle) in board mm, measured on the photo
SILK = {"J1": (2.8, 2.6, 0), "C5": (7.0, 1.95, 0), "U1": (10.55, 2.85, 0), "S2": (5.0, 11.2, 90),
        "C12": (13.7, 2.95, 0), "U3": (16.85, 1.65, 0), "C10": (15.5, 6.0, 0), "U2": (18.3, 7.4, 0),
        "R1": (12.75, 8.0, 0), "C2": (13.1, 8.9, 0), "J2": (22.9, 0.8, 0), "R2": (27.35, 1.0, 90),
        "R4": (28.2, 1.0, 90), "U4": (30.1, 1.0, 0), "R3": (29.4, 3.3, 0), "C1": (25.75, 5.3, 0),
        "L1": (31.0, 5.9, 270), "C7": (27.55, 6.6, 0), "C8": (27.55, 7.65, 0), "C9": (27.55, 8.75, 0),
        "C3": (34.3, 9.6, 270), "S1": (34.5, 11.2, 90)}


POWER_NETS = {"VBUS", "+3V0", "GND", "J2_P1", "BOOST_SW"}


def build_pcb(sym_uuids):
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    ls = board.GetEnabledLayers()
    ls.AddLayer(pcbnew.User_1); ls.AddLayer(pcbnew.User_2); ls.AddLayer(pcbnew.User_3)
    board.SetEnabledLayers(ls)
    board.SetLayerName(pcbnew.User_1, "User.PhotoFront")
    board.SetLayerName(pcbnew.User_2, "User.PhotoBack")
    board.SetLayerName(pcbnew.User_3, "User.PhotoFrontBare")

    # outline: top edge with two notches, then right, bottom, left
    xs = [0.0]
    for xc, r in NOTCHES:
        edge(board, (xs[-1], 0), (xc - r, 0))
        notch(board, xc, r)
        xs.append(xc + r)
    edge(board, (xs[-1], 0), (BW, 0))
    edge(board, (BW, 0), (BW, BH))
    edge(board, (BW, BH), (0, BH))
    edge(board, (0, BH), (0, 0))

    nets = {}
    for n in NETS:
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni
    pinnet = {(r, num): n for n, pins in NETS.items() for r, num in pins}

    for p in P:
        fp = load_fp(p["fp"])
        fp.SetReference(p["ref"])
        fp.SetValue(p["val"])
        fp.SetPath(pcbnew.KIID_PATH("/" + sym_uuids[p["ref"]]))
        fp.SetSheetname("Root")
        fp.SetSheetfile(PRJ + ".kicad_sch")
        fp.SetOrientationDegrees(p["rot"])
        if p["ref"] == "J1":
            # anchor on the two oval shell legs (measured on the back photo)
            fp.SetPosition(V(0, 0))
            ov = [pd for pd in fp.Pads() if pd.GetNumber() == "SH" and pd.GetDrillSizeY() > pd.GetDrillSizeX() * 1.5]
            cx = sum(pcbnew.ToMM(pd.GetPosition().x) for pd in ov) / len(ov)
            cy = sum(pcbnew.ToMM(pd.GetPosition().y) for pd in ov) / len(ov)
            tx, ty = Hb(450, 830)
            fp.SetPosition(V(OX + tx - cx, OY + ty - cy))
        else:
            fp.SetPosition(V(OX + p["pos"][0], OY + p["pos"][1]))
        board.Add(fp)
        if p["side"] == "B":
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        for pd in fp.Pads():
            n = pinnet.get((p["ref"], pd.GetNumber()))
            if n:
                pd.SetNet(nets[n])

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in MODEL_SUB:
            fp.Models()[0].m_Filename = "${KICAD10_3DMODEL_DIR}/" + MODEL_SUB[ref]
        t = fp.Reference()
        if ref in SILK:
            x, y, a = SILK[ref]
            t.SetPosition(V(OX + x, OY + y))
            t.SetTextAngleDegrees(a)
            t.SetTextSize(pcbnew.VECTOR2I(mm(0.85), mm(0.95)))
            t.SetTextThickness(mm(0.15))
        else:
            t.SetVisible(False)
        if ref.startswith("TP") and int(ref[2:]) > 5:      # bare solder-bumped pads, no silk ring
            for it in list(fp.GraphicalItems()):
                if it.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                    fp.Remove(it)

    # back silkscreen: pin-1 dot of the SWD header and the date code
    dot = pcbnew.PCB_SHAPE(board)
    dot.SetShape(pcbnew.SHAPE_T_CIRCLE); dot.SetLayer(pcbnew.B_SilkS)
    dot.SetCenter(V(OX + 3.57, OY + 1.14)); dot.SetEnd(V(OX + 3.57 + 0.2, OY + 1.14)); dot.SetWidth(mm(0.4))
    board.Add(dot)
    for txt, x in (("YWX", 21.1), ("1751", 15.1)):
        t = pcbnew.PCB_TEXT(board)
        t.SetText(txt); t.SetLayer(pcbnew.B_SilkS); t.SetMirrored(True)
        t.SetPosition(V(OX + x, OY + 11.05)); t.SetTextSize(pcbnew.VECTOR2I(mm(1.1), mm(1.2)))
        t.SetTextThickness(mm(0.2))
        board.Add(t)

    for x, y, n in VIAS:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(OX + x, OY + y)); v.SetWidth(mm(0.6)); v.SetDrill(mm(0.3))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        if n:
            v.SetNet(nets[n])
        board.Add(v)

    board.GetDesignSettings().m_TrackMinWidth = mm(0.1)
    # copper tracks: hand-traced red layers converted to polylines (tools/tracks.json)
    for t in json.load(open(os.path.join(ROOT, "tools", "tracks.json"))):
        w = t.get("w", 0.3 if t["net"] in POWER_NETS else 0.15)
        for a, b in zip(t["pts"][:-1], t["pts"][1:]):
            tr = pcbnew.PCB_TRACK(board)
            tr.SetStart(V(OX + a[0], OY + a[1])); tr.SetEnd(V(OX + b[0], OY + b[1]))
            tr.SetWidth(mm(w)); tr.SetLayer(pcbnew.F_Cu if t["layer"] == "F" else pcbnew.B_Cu)
            if t["net"]:
                tr.SetNet(nets[t["net"]])
            board.Add(tr)

    # GND pour on both sides (most of the real board is filled copper)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer); z.SetNet(nets["GND"])
        ol = z.Outline(); ol.NewOutline()
        for x, y in ((0, 0), (BW, 0), (BW, BH), (0, BH)):
            ol.Append(V(OX + x, OY + y))
        z.SetLocalClearance(mm(0.15)); z.SetMinThickness(mm(0.1))
        z.SetThermalReliefGap(mm(0.2)); z.SetThermalReliefSpokeWidth(mm(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        board.Add(z)

    path = os.path.join(OUT, PRJ + ".kicad_pcb")
    board.Save(path)
    # zone filling only works on a board loaded from disk (crashes on an in-memory BOARD)
    b2 = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    b2.Save(path)
    return path


def prep_images():
    """Crop/rectify stitched photos to the board with 1 mm margin, 60 px/mm."""
    res = 60.0
    W, H = int(round((BW + 2) * res)), int(round((BH + 2) * res))
    tmp = tempfile.mkdtemp()
    f_in = os.path.join(ROOT, "docs/img/stitched_front.jpg")
    b_in = os.path.join(ROOT, "docs/img/stitched_back.jpg")
    # front: full-res panorama, board corner (644,286), 188.6 px/mm
    s = 188.6
    fo = os.path.join(tmp, "front.jpg")
    subprocess.check_call(["magick", f_in, "-crop", "%dx%d+%d+%d" % ((BW + 2) * s, (BH + 2) * s, 644 - s, 286 - s),
                           "+repage", "-resize", "%dx%d!" % (W, H), "-units", "PixelsPerInch", "-density", "300", "-quality", "85", fo])
    # back: mirror, board bbox (690,330)-(7570,2670) full-res
    sx, sy = (7570 - 690) / BW, (2670 - 330) / BH
    bo = os.path.join(tmp, "back.jpg")
    subprocess.check_call(["magick", b_in, "-flop", "-crop",
                           "%dx%d+%d+%d" % ((BW + 2) * sx, (BH + 2) * sy, 690 - sx, 330 - sy),
                           "+repage", "-resize", "%dx%d!" % (W, H), "-units", "PixelsPerInch", "-density", "300", "-quality", "85", bo])
    # front with components removed: registered onto the same canvas as stitched_front.jpg
    fb = os.path.join(tmp, "front_bare.jpg")
    subprocess.check_call(["magick", os.path.join(ROOT, "docs/img/stitched_front_bare.jpg"), "-crop",
                           "%dx%d+%d+%d" % ((BW + 2) * s, (BH + 2) * s, 644 - s, 286 - s),
                           "+repage", "-resize", "%dx%d!" % (W, H), "-units", "PixelsPerInch", "-density", "300",
                           "-quality", "85", fb])
    return [(fo, "User.1", res), (bo, "User.2", res), (fb, "User.3", res)]


# Board is 0.8 mm (measured), blue mask, white silk, HASL finish
STACKUP = """\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen") (color "White"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "Blue") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "core") (thickness 0.71) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (color "Blue") (thickness 0.01))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen") (color "White"))
\t\t\t(copper_finish "HAL lead-free")
\t\t\t(dielectric_constraints no)
\t\t)
"""


def add_images(pcb_path, imgs):
    blocks = []
    for path, layer, res in imgs:
        # KiCad sizes bitmaps by their PPI (default 300); scale so 1px = 1/res mm
        scale = 300.0 / (res * 25.4)
        data = base64.b64encode(open(path, "rb").read()).decode()
        lines = "\n".join('\t\t\t"%s"' % data[i:i + 76] for i in range(0, len(data), 76))
        blocks.append('\t(image (at %.3f %.3f) (layer "%s") (scale %.6f) (locked yes) (uuid "%s")\n\t\t(data\n%s\n\t\t)\n\t)'
                      % (OX + BW / 2, OY + BH / 2, layer, scale, uid(), lines))
    txt = open(pcb_path).read().rstrip()
    txt = txt.replace("(thickness 1.6)", "(thickness 0.8)", 1)
    txt = txt.replace("\t(setup\n", "\t(setup\n" + STACKUP, 1)
    assert txt.endswith(")")
    txt = txt[:-1] + "\n".join(blocks) + "\n)\n"
    open(pcb_path, "w").write(txt)


def assign_tp_nets():
    for p in P:
        if p["ref"].startswith("TP") and int(p["ref"][2:]) > 5:
            best = min(TP_NETS, key=lambda k: math.hypot(k[0] - p["pos"][0], k[1] - p["pos"][1]))
            if math.hypot(best[0] - p["pos"][0], best[1] - p["pos"][1]) < 0.5:
                NETS.setdefault(TP_NETS[best], []).append((p["ref"], "1"))
    for n in set(TP_NETS.values()) | {v[2] for v in VIAS if v[2]}:
        NETS.setdefault(n, [])
    for src, dst in MERGE.items():
        NETS.setdefault(dst, []).extend(NETS.pop(src, []))
    VIAS[:] = [(x, y, MERGE.get(n, n)) for x, y, n in VIAS]


def main():
    os.makedirs(OUT, exist_ok=True)
    assign_tp_nets()
    build_footprints()
    build_symbols()
    with open(os.path.join(OUT, "fp-lib-table"), "w") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "%s") (type "KiCad") (uri "${KIPRJMOD}/%s.pretty") (options "") (descr "Ledger Nano S custom footprints"))\n)\n' % (PRJ, PRJ))
    with open(os.path.join(OUT, "sym-lib-table"), "w") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "%s") (type "KiCad") (uri "${KIPRJMOD}/%s.kicad_sym") (options "") (descr "Ledger Nano S custom symbols"))\n)\n' % (PRJ, PRJ))
    pro = os.path.join(OUT, PRJ + ".kicad_pro")
    if not os.path.exists(pro):
        shutil.copy(os.path.join(KILIB, "template", "kicad.kicad_pro"), pro)
    sym_uuids = {p["ref"]: uid() for p in P}
    build_schematic(sym_uuids)
    pcb = build_pcb(sym_uuids)
    add_images(pcb, prep_images())
    print("ok:", pcb)


if __name__ == "__main__":
    main()

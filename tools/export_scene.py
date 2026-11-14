#!/usr/bin/env python3
"""Export the KiCad reconstruction as kicad/scene.js for kicad/viewer3d.html.

The scene holds the board outline, copper (tracks, vias, pads, GND pours), silkscreen, the photos of
both sides cropped to the board, a mesh for every part (exported from its KiCad 3D model with
kicad-cli as coloured PLY), and the details shown on hover: what each part is, the name of every pin
and what each net does.

Coordinates are millimetres with x right and y up as in KiCad's top view (board corner at 0, 0), and
z up out of the front side, with the board centred on its middle plane.

Usage: python3 tools/export_scene.py   (needs KiCad 10: its pcbnew module and kicad-cli)
"""
import base64
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(ROOT, "kicad", "ledger_nano_s.kicad_pcb")
OUT = os.path.join(ROOT, "kicad", "scene.js")
OX, OY = 100.0, 100.0          # KiCad position of the board's top-left corner (see gen_kicad.py)
KILIB = "/usr/share/kicad/symbols"

# What each part is, from README.md and docs/tracing.md. Markings are drawn on top of the body.
PARTS = {
    "U1": dict(title="STM32F042K6", package="UFQFPN32, 5 x 5 mm",
               notes="Main (non-secure) MCU, Cortex-M0 with 32 KB flash and crystal-less USB. It owns USB, the "
                     "display and the buttons, and proxies them for the secure element (SEPROXYHAL). Marked "
                     "F042K6 / GQ22Z 1193 / CHN 749 A (2017 week 49).",
               marking="F042K6\nGQ22Z 1193\nCHN 749 A", mark_box=[3.9, 2.4, 0]),
    "U2": dict(title="ST31 secure element", package="DFN8 + EP, 4.0 x 4.2 mm",
               notes="Runs BOLOS and the apps. Talks ISO 7816-3 T=0 to the MCU's USART1 in smartcard mode "
                     "(I/O on pin 3, CLK pin 5, RST pin 6). ATR 3B 90 98 10 00 captured with the chip removed. "
                     "Pinout is MFF2-like with the unused pair moved; only pin 2 is GND, pins 1/4/8 and the "
                     "exposed pad are not connected. Marked NBO / PHL744 / 7B (2017 week 44).",
               marking="NBO\nPHL744\n7B", mark_box=[3.2, 2.4, 0]),
    "U3": dict(title="3.0 V LDO (marked AD30)", package="SOT-23-5",
               notes="VBUS in (pins 1 and 3, enable tied to input) to the +3V0 rail (pin 5) that feeds the MCU, "
                     "the SE and the OLED logic. Output not measured yet.",
               marking="AD30", mark_box=[2.2, 0.9, 90]),
    "U4": dict(title="ST8R00 step-up converter", package="DFN8 + EP, 4 x 4 mm",
               notes="Synchronous PWM boost, 4-6 V in from VBUS, 6-12 V out set by the R3/R4 divider, 1.7 MHz. "
                     "Makes the OLED panel supply (J2 pin 1). Marked 8R00W / MYS749 (2017 week 49).",
               marking="8R00W\nMYS749", mark_box=[3.2, 1.7, 0]),
    "L1": dict(title="10 uH power inductor", package="about 3 x 3 mm, shielded",
               notes="Inductor of the ST8R00 boost converter, from VBUS to its switch pin. Marked 100.",
               marking="100", mark_box=[1.6, 0.9, 0]),
    "J1": dict(title="Micro-USB B receptacle", package="SMD with through-hole shell tabs",
               notes="USB power and data. D- and D+ go straight to the MCU (PA11/PA12); the ID pin is "
                     "untraced (in the GND pour)."),
    "J2": dict(title="OLED display connector", package="12-pin FPC, 0.5 mm pitch, flip-lock",
               notes="Flex of the 128 x 32 monochrome OLED (SSD1306-class controller). Write-only 4-wire SPI "
                     "from SPI1 (PA5 clock, PA7 data) plus three control GPIOs (PA0, PA1, PA2), +3V0 logic "
                     "supply and the boost output for the panel."),
    "S1": dict(title="Right button", package="side-actuated tactile switch",
               notes="Reads on MCU PB7 (traced on the back along the bottom edge); the other side is GND."),
    "S2": dict(title="Left button", package="side-actuated tactile switch",
               notes="Reads on MCU PA15; the other side is GND."),
    "C1": dict(title="Capacitor", package="0603", notes="Boost converter output capacitor (OLED panel supply)."),
    "C2": dict(title="Capacitor", package="0402", notes="Decoupling of the secure element supply (+3V0 at U2 pin 7)."),
    "C3": dict(title="Capacitor", package="0402", notes="VBUS decoupling at the boost converter input."),
    "C5": dict(title="Capacitor", package="0402", notes="+3V0 decoupling at the MCU (next to the SWD header supply)."),
    "C7": dict(title="Capacitor", package="0603", notes="On J2 pin 11, likely the OLED controller's VCOMH capacitor."),
    "C8": dict(title="Capacitor", package="0603", notes="On J2 pin 12 with C9, OLED supply decoupling."),
    "C9": dict(title="Capacitor", package="0603", notes="On J2 pin 12 with C8, OLED supply decoupling."),
    "C10": dict(title="Capacitor", package="0402", notes="+3V0 decoupling."),
    "C12": dict(title="Capacitor", package="0402", notes="LDO (U3) input capacitor, on VBUS."),
    "R1": dict(title="Resistor", package="0402", notes="NRST pull-up to +3V0."),
    "R2": dict(title="Resistor", package="0402", notes="J2 pin 10 to ground: likely the OLED controller's IREF resistor."),
    "R3": dict(title="Resistor", package="0402", notes="Top of the ST8R00 feedback divider, from the boost output."),
    "R4": dict(title="Resistor", package="0402", notes="Bottom of the ST8R00 feedback divider, to ground."),
}
TESTPADS = {
    "TP1": "SWD header pin 1 (dot end): +3V0 supply", "TP2": "SWD header: SWCLK (MCU PA14)",
    "TP3": "SWD header: GND", "TP4": "SWD header: SWDIO (MCU PA13)", "TP5": "SWD header: NRST",
}

# Pin names that are not in a KiCad library symbol (or where it only has placeholders). "?" = inferred.
PIN_NAMES = {
    "U2": {"1": "NC", "2": "GND", "3": "I/O", "4": "NC", "5": "CLK", "6": "RST", "7": "VCC", "8": "NC", "9": "EP (NC)"},
    "U3": {"1": "VIN", "2": "GND", "3": "EN", "4": "NC?", "5": "VOUT"},
    "U4": {"1": "SW?", "4": "VIN?", "5": "FB?", "6": "EN?", "8": "VOUT?", "9": "EP"},
    "J1": {"1": "VBUS", "2": "D-", "3": "D+", "4": "ID", "5": "GND", "SH": "Shield"},
    "J2": {"1": "panel VCC?", "2": "VSS?", "3": "VSS?", "4": "VDD (logic)", "5": "RES# or CS#?", "6": "D/C# or CS#?",
           "7": "RES#/CS#/D/C#?", "8": "SCLK", "9": "SDIN", "10": "IREF?", "11": "VCOMH?", "12": "VCC decoupling?",
           "MP": "mount"},
}
# MCU pin names from the KiCad symbol of the same package
LIB_SYMBOLS = {"U1": ("MCU_ST_STM32F0.kicad_sym", "STM32F042K_4-6_Ux")}

# What each net does, from docs/tracing.md
NETS = {
    "GND": "Ground: the pours on both sides, the MCU and boost exposed pads, U2 pin 2.",
    "VBUS": "USB 5 V: J1 pin 1 to the LDO input (U3) and the boost converter (L1, U4), via the back along the top edge.",
    "+3V0": "3.0 V rail from the LDO (U3 pin 5): MCU supplies, secure element VCC (U2 pin 7), OLED logic (J2 pin 4), "
            "ST8R00 pin 6 (probably its enable) and SWD header pin 1.",
    "USB_DM": "USB D-, J1 to MCU PA11.", "USB_DP": "USB D+, J1 to MCU PA12.",
    "SWDIO": "SWD data: MCU PA13 to SWD header TP4.", "SWCLK": "SWD clock: MCU PA14 to SWD header TP2.",
    "NRST": "MCU reset: SWD header TP5, with R1 pull-up.",
    "SE_CLK": "Secure element clock: MCU PA8 (USART1_CK, smartcard mode) to U2 pin 5, via the back.",
    "SE_RST": "Secure element reset: MCU PA10 (GPIO) to U2 pin 6, via the back.",
    "SE_IO": "Secure element I/O: MCU PA9 (USART1_TX, half-duplex smartcard) to U2 pin 3, along the bottom edge on "
             "the back. ISO 7816-3 T=0 at F/D 512/12; this line carries SEPROXYHAL.",
    "PA0": "OLED control GPIO (reset, chip select or data/command) to J2 pin 7; test pad TP11.",
    "PA1": "OLED control GPIO (reset or chip select) to J2 pin 5; test pad TP8.",
    "PA2": "OLED control GPIO (data/command or chip select) to J2 pin 6; test pad TP7.",
    "PA5": "OLED SPI clock (SPI1_SCK) to J2 pin 8; test pad TP9.",
    "PA7": "OLED SPI data (SPI1_MOSI) to J2 pin 9; test pad TP12.",
    "J2_P1": "Boost converter output (6-12 V, OLED panel VCC): U4 pin 8, R3, C1, J2 pin 1; test pad TP10.",
    "J2_P10": "J2 pin 10 with R2 to ground, likely the OLED controller's IREF; test pad TP6.",
    "J2_P11": "J2 pin 11 with C7 to ground, likely VCOMH; test pad TP14.",
    "J2_P12": "J2 pin 12 with C8 and C9 to ground; test pad TP13.",
    "BOOST_SW": "Boost converter switch node: L1 to U4 pin 1.",
    "U4_P5": "Boost converter feedback: the R3/R4 divider into U4 pin 5.",
    "PA15": "Left button S2 to MCU PA15.", "PB7": "Right button S1 to MCU PB7, along the bottom edge on the back.",
}


mm = pcbnew.ToMM


def P(v):
    return [round(mm(v.x) - OX, 3), round(OY - mm(v.y), 3)]


def ring(chain):
    return [P(chain.CPoint(i)) for i in range(chain.PointCount())]


def lib_pins(fname, sym):
    t = open(os.path.join(KILIB, fname)).read()
    i = t.index('(symbol "%s"' % sym)
    j = t.find('\n\t(symbol "', i + 10)
    return {n: name for name, n in re.findall(r'\(name "([^"]*)".*?\(number "([^"]*)"', t[i:j], re.S)}


def ply_mesh(ref, tmp):
    """The part's 3D model as coloured triangles, without the board (kicad-cli needs the board in the export)."""
    out = os.path.join(tmp, ref + ".ply")
    r = subprocess.run(["kicad-cli", "pcb", "export", "ply", "-f", "--subst-models", "--component-filter", ref,
                        "-o", out, PCB], capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        return None
    lines = open(out).read().split("\n")
    h = lines.index("end_header")
    nv = int(next(l for l in lines if l.startswith("element vertex")).split()[2])
    nf = int(next(l for l in lines if l.startswith("element face")).split()[2])
    verts = [l.split() for l in lines[h + 1:h + 1 + nv]]
    board = {i for i, v in enumerate(verts) if v[6:9] == ["1", "47", "129"]}
    groups = {}          # colour -> list of triangles (vertex positions)
    for l in lines[h + 1 + nv:h + 1 + nv + nf]:
        f = [int(x) for x in l.split()]
        idx = f[1:1 + f[0]]
        if any(i in board for i in idx):
            continue
        col = "#%02x%02x%02x" % tuple(int(c) for c in verts[idx[0]][6:9])
        tri = groups.setdefault(col, [])
        for k in range(1, len(idx) - 1):
            for i in (idx[0], idx[k], idx[k + 1]):
                x, y, z = (float(c) for c in verts[i][:3])
                tri.append((x - OX, y + OY, z - 0.4))
    if not groups:
        return None
    allp = [p for t in groups.values() for p in t]
    lo = [min(p[k] for p in allp) for k in range(3)]
    hi = [max(p[k] for p in allp) for k in range(3)]
    meshes = []
    for col, tri in groups.items():
        # positions quantised to 16 bits over the part's bounding box
        q = []
        for p in tri:
            for k in range(3):
                span = hi[k] - lo[k] or 1
                q.append(round((p[k] - lo[k]) / span * 65535))
        meshes.append({"color": col, "v": base64.b64encode(struct.pack("<%dH" % len(q), *q)).decode()})
    return {"lo": [round(v, 4) for v in lo], "hi": [round(v, 4) for v in hi], "meshes": meshes}


def photos(tmp):
    """The photo underlays embedded in the board (1 mm margin around it, 60 px/mm), cropped to the board."""
    txt = open(PCB).read()
    out = {}
    for layer, key in (("User.3", "front"), ("User.2", "back")):
        m = re.search(r'\(image \(at [^)]*\) \(layer "%s"\)[^\n]*\n\t\t\(data\n(.*?)\n\t\t\)' % re.escape(layer), txt, re.S)
        if not m:
            continue
        raw = os.path.join(tmp, key + "_raw.jpg")
        open(raw, "wb").write(base64.b64decode("".join(re.findall(r'"([^"]*)"', m.group(1)))))
        dst = os.path.join(ROOT, "kicad", "photo_%s.jpg" % key)
        # drop the 1 mm margin; the back photo is already flopped to the front view, as KiCad shows it
        subprocess.check_call(["magick", raw, "-shave", "60x60", "-quality", "85", dst])
        out[key] = os.path.basename(dst)
    return out


def main():
    board = pcbnew.LoadBoard(PCB)
    thick = mm(board.GetDesignSettings().GetBoardThickness())
    tmp = tempfile.mkdtemp()

    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, True)
    scene = {"thickness": thick, "outline": ring(outline.Outline(0)), "tracks": [], "vias": [], "pads": [],
             "fills": [], "silk": [], "parts": [], "nets": NETS, "photos": photos(tmp)}

    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            scene["vias"].append({"at": P(t.GetPosition()), "d": round(mm(t.GetWidth(pcbnew.F_Cu)), 3),
                                  "net": t.GetNetname()})
        else:
            scene["tracks"].append({"a": P(t.GetStart()), "b": P(t.GetEnd()), "w": round(mm(t.GetWidth()), 3),
                                    "side": "front" if t.GetLayer() == pcbnew.F_Cu else "back", "net": t.GetNetname()})

    for z in board.Zones():
        for layer, side in ((pcbnew.F_Cu, "front"), (pcbnew.B_Cu, "back")):
            if not z.IsOnLayer(layer):
                continue
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                rings = [ring(polys.Outline(i))] + [ring(polys.Hole(i, j)) for j in range(polys.HoleCount(i))]
                scene["fills"].append({"side": side, "net": z.GetNetname(), "rings": rings})

    # silkscreen as filled polygons
    for layer, side in ((pcbnew.F_SilkS, "front"), (pcbnew.B_SilkS, "back")):
        ps = pcbnew.SHAPE_POLY_SET()
        items = [d for d in board.GetDrawings() if d.GetLayer() == layer]
        for fp in board.GetFootprints():
            items += [g for g in fp.GraphicalItems() if g.GetLayer() == layer]
            for t in (fp.Reference(), fp.Value()):
                if t.GetLayer() == layer and t.IsVisible():
                    items.append(t)
        for it in items:
            if isinstance(it, (pcbnew.PCB_TEXT, pcbnew.PCB_FIELD)):
                # the shape conversion of a text is its bounding box; this gives the strokes
                it.TransformTextToPolySet(ps, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
            else:
                it.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
        ps.Simplify()
        for i in range(ps.OutlineCount()):
            scene["silk"].append({"side": side, "rings": [ring(ps.Outline(i))] +
                                  [ring(ps.Hole(i, j)) for j in range(ps.HoleCount(i))]})

    pin_names = dict(PIN_NAMES)
    for ref, (f, sym) in LIB_SYMBOLS.items():
        pin_names[ref] = lib_pins(f, sym)

    for fp in board.GetFootprints():
        ref = fp.GetReference()
        side = "back" if fp.IsFlipped() else "front"
        for pad in fp.Pads():
            lay = pad.GetPrincipalLayer()
            sz = pad.GetSize(lay)
            shape = pad.GetShape(lay)
            item = {"ref": ref, "num": pad.GetNumber(), "net": pad.GetNetname(), "side": side, "at": P(pad.GetPosition()),
                    "w": round(mm(sz.x), 3), "h": round(mm(sz.y), 3), "rot": round(pad.GetOrientation().AsDegrees(), 2),
                    "shape": "circle" if shape == pcbnew.PAD_SHAPE_CIRCLE else "oval" if shape == pcbnew.PAD_SHAPE_OVAL else "rect"}
            if pad.HasHole():
                item["both"] = True
            name = pin_names.get(ref, {}).get(pad.GetNumber())
            if name:
                item["pin"] = name
            scene["pads"].append(item)
        if ref.startswith("TP"):
            continue
        info = PARTS.get(ref, {})
        part = {"ref": ref, "side": side, "value": fp.GetValue(), "at": P(fp.GetPosition()),
                "rot": round(fp.GetOrientation().AsDegrees(), 2), **info}
        mesh = ply_mesh(ref, tmp)
        if mesh:
            part["mesh"] = mesh
        scene["parts"].append(part)
        print(ref, "mesh" if mesh else "no mesh", file=sys.stderr)
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref.startswith("TP"):
            for p in scene["pads"]:
                if p["ref"] == ref:
                    p["testpad"] = TESTPADS.get(ref, "Solder-bumped test pad (bed-of-nails test point)")

    with open(OUT, "w") as f:
        f.write("// Scene for viewer3d.html, exported from ledger_nano_s.kicad_pcb by tools/export_scene.py.\n")
        f.write("window.SCENE = " + json.dumps(scene, separators=(",", ":"), ensure_ascii=False) + ";\n")
    print("wrote", OUT, os.path.getsize(OUT), "bytes,",
          {k: len(v) for k, v in scene.items() if isinstance(v, (list, dict))})


if __name__ == "__main__":
    main()

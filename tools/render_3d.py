#!/usr/bin/env python3
"""Render 3D views of the KiCad board to docs/img/render_*.png (photo underlays stripped)."""
import os, re, subprocess, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(ROOT, "kicad", "ledger_nano_s.kicad_pcb")
OUT = os.path.join(ROOT, "docs", "img")
VIEWS = [  # name, extra args
    ("top", ["--side", "top", "--zoom", "2.2", "-w", "2400", "-h", "900"]),
    ("bottom", ["--side", "bottom", "--zoom", "2.2", "-w", "2400", "-h", "900"]),
    ("iso", ["--side", "top", "--rotate", "-50,0,-25", "--perspective", "--zoom", "1.6", "-w", "2400", "-h", "1300"]),
    ("iso_back", ["--side", "bottom", "--rotate", "50,0,25", "--perspective", "--zoom", "1.6", "-w", "2400", "-h", "1300"]),
    ("edge", ["--side", "front", "--zoom", "2.2", "-w", "2400", "-h", "500"]),
]


def strip_images(txt):
    out, i = [], 0
    while True:
        j = txt.find("\n\t(image", i)
        if j < 0:
            out.append(txt[i:]); break
        out.append(txt[i:j]); depth = 0; k = j + 1
        while True:
            c = txt[k]
            depth += c == "("; depth -= c == ")"; k += 1
            if depth == 0: break
        i = k
    return "".join(out)


tmp = tempfile.mkdtemp()
kdir = os.path.join(tmp, "kicad"); shutil.copytree(os.path.join(ROOT, "kicad"), kdir)
pcb = os.path.join(kdir, os.path.basename(PCB))
open(pcb, "w").write(strip_images(open(PCB).read()))
for name, args in VIEWS:
    dst = os.path.join(OUT, "render_%s.png" % name)
    subprocess.check_call(["kicad-cli", "pcb", "render", "-o", dst, "--quality", "high", "--background", "opaque"] + args + [pcb], stdout=subprocess.DEVNULL)
    print(dst)
shutil.rmtree(tmp)

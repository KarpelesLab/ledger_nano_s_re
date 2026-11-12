# KiCad reconstruction

The project is in [`kicad/`](../kicad/) (KiCad 10). Open
`kicad/ledger_nano_s.kicad_pro`.

## What is in it

| Item | State |
|------|-------|
| Board outline | 35.66 × 12.27 mm, with the two clip notches on the top edge. Measured from photos (about ±1%). |
| Footprints | All 31 parts (U1–U4, J1, J2, L1, S1, S2, 9 caps, 4 resistors, 14 back-side test pads) are placed at their measured positions. Accuracy is about ±0.2 mm. |
| Photo underlays | The stitched front photo is on layer **User.1**, the mirrored back photo on **User.2**, and the front with components removed on **User.3** (best for tracing top copper). Both are scaled and aligned to the board outline and locked. Toggle them in the Layers panel to trace copper. |
| Schematic | All symbols, linked to their footprints (F8 / "Update PCB from schematic" works). Nets are attached with labels. |
| Nets | **Partial on purpose.** Only connections that are confirmed or strongly supported are entered (table below). |
| Tracks / vias | **Not routed yet.** That is the next step, tracing over the photo layers. |

Overlay check (the red boxes are the KiCad pad positions drawn on the
photos):

![front, bare](img/kicad_overlay_front_bare.jpg)
![front](img/kicad_overlay_front.jpg)
![back](img/kicad_overlay_back.jpg)

## Nets entered so far

| Net | Members | Basis |
|-----|---------|-------|
| USB_DM / USB_DP | J1.2 / J1.3 → U1 PA11 (21) / PA12 (22) | The STM32F042's USB is fixed to PA11/PA12 |
| VBUS | J1.1 | — |
| GND | J1.5, J1 shell, U1 EP (VSS, pin 33), U2.2, C2.2 | U2.2 seen by user. U1 EP is VSS on the K6Ux package. |
| SE_VCC | U2.7, C2.1 | User saw VCC with a decoupling cap on pin 7 |
| SE_P3, SE_P5, SE_P6 | U2.3 / U2.5 / U2.6 | Pins 5 and 6 go to the STM32 (pins on the STM32 side still unknown) |

## Footprint choices / assumptions

- **U1** `UFQFPN-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm_ThermalVias`, rotated 180°.
  Pin 1 is at the package dot (bottom-right in the photos), so PA11/PA12
  face the USB connector.
- **U2** custom `ST_DFN8-1EP_4.0x4.2mm_P0.98mm`, measured on the bare
  board: 8 pads 1.2 x 0.75 mm, pitch 0.98 mm, columns 4.0 mm apart, plus a
  2.1 x 3.45 mm **exposed pad** (pin 9, no vias, net unknown). The body is
  4.0 x 4.2 mm. Pin 1 is at the dot (bottom-right on the board), numbered
  counter-clockwise. The removed chip, held upright, has the usual ST dot at
  the bottom-left.
- **U3** `SOT-23-5`, pin 1 at the silkscreen dot (top-left).
- **U4** `DFN-8-1EP_4x4mm_P0.8mm_EP2.3x3.24mm` (ST8R00 is DFN8 4×4),
  rotated 180° (dot at bottom-right). The pin functions in its symbol are
  still placeholders.
- **J1** `USB_Micro-B_Molex-105017-0001`. Its THT shell legs (oval pair
  7.0 mm apart, square pair 5.0 mm apart) match the back photo.
- **J2** custom `FPC_12P_P0.5mm_Pin1Top`, 0.5 mm pitch, mounting tabs at
  +-4.54 mm (same spacing as Hirose FH12-12S, but the pin numbering is
  reversed). Pin 1 is at the top to match the board silkscreen.
- **S1/S2** custom `SW_SideTact_P3.8x1.38mm`: 4 pads 1.75 x 1.0 mm. The pair
  on the board-edge side is plated through (they show on the back).
- **L1** `L_Abracon_ASPI-3012S` rotated 90 degrees. The bare board shows its
  two pads are horizontal bars, one above the other.
- **TP1–TP5** = the ringed 5-pad header on the back (TP1 = dot end). TP6–TP14
  are the other solder-bumped back pads.
- Passive values are unknown (`C?`, `R?`). L1 is 10 µH (marking `100`).

## Regenerating

`tools/gen_kicad.py` built the initial project from the measurements. It
**overwrites** the schematic and PCB. From now on, edit in KiCad directly and
only re-run the script to start over.

## Known caveats

- DRC/ERC report many violations: unrouted nets, unknown pins, and stock
  footprints sitting closer to the edge than the default rules allow. This
  is expected at this stage.
- The image scale assumes KiCad sizes the embedded photos at 300 PPI. If the
  photo layers don't line up with the outline when the board is opened in
  the GUI, adjust the image scale (properties of the image) to 0.1969.

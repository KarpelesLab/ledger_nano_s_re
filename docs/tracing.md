# Copper tracing

These connections were traced from the photos: the bare front, the populated
front and the back. All three images were aligned to the board outline. Each
net is marked with a confidence level:

- **H**: the copper path is clearly visible end to end.
- **M**: it is visible, but one end or the exact pin is inferred.
- **L**: it is a best guess and should be checked with a meter.

Every result here should still be checked with a continuity meter.

## Method

1. Detect vias on both sides and pair the ones that match. This gave 60 real
   vias. Silkscreen marks that were picked up as vias were removed. U2's
   exposed pad has **no** vias.
2. Back copper: segment it by colour (copper under the mask is light blue,
   bare laminate is navy). Isolated traces stand out as islands, and
   everything else is the GND pour. See
   [trace_back_islands.jpg](img/trace_back_islands.jpg) and the contrast
   view of the header area
   [trace_back_header.jpg](img/trace_back_header.jpg).
3. Front copper: read by eye on the populated photo, where the traces
   show best under the mask, and on the bare photo, which shows the pads.

## 5-pad header on the back (TP1 = dot end, nearest USB)

| Pad | Net | Path | Conf. |
|-----|-----|------|-------|
| TP1 | **GND** | stub into the back GND pour (via v1 → C5.1) | M |
| TP2 | **SWCLK** | back trace → via (5.84, 8.73) → front → U1.24 (PA14) | M |
| TP3 | **VBUS** | stub onto the v12–v20 back strap; front v12 → C5.2, front v20 → U3 input side | M |
| TP4 | **SWDIO** | back trace → via (5.47, 7.49) → front → U1.23 (PA13) | M |
| TP5 | **NRST** | back trace → via (12.64, 6.70) → front → U1.4 (NRST) | M |

That makes the header a standard SWD port: GND, SWCLK, VCC (VBUS here),
SWDIO, NRST. C5 is VBUS decoupling.

## Other nets

| Net | Members | Conf. | Notes |
|-----|---------|-------|-------|
| USB_DM / USB_DP | J1.2–U1.21, J1.3–U1.22 | H | short direct traces |
| GND | J1 shell/pin 5, U1 EP (3×3 vias), U4 EP (2×3 vias), all thermal-relief vias on the back | H | the back is mostly GND pour |
| +3V0 | U1.1 (VDD), U1.5 (VDDA), U1.17 (VDDIO2, L) + vias (6.91,3.65) (11.63,8.84) (13.77,6.03) (18.78,3.56) (18.75,5.59) (29.55,3.00) | M | one long back trace links all six vias. It reaches the U3 / J2 area and the U4 / R3 area |
| SE_P5 | U2.5 → via (12.93,8.55) → back → via (5.74,4.16) → U1 left side | M | the U1 pin at the far end is not yet resolved (PA8?) |
| SE_P6 | U2.6 → via (13.18,9.42) → back → via (5.97,6.03) → U1.20 (PA10) | M | |
| PA9 | U1.19 → via (5.70,5.18) | M | where it goes on the back is not resolved |
| PA2 | U1.8 → via (13.04,4.69) → back → via (17.54,6.18) | M | towards J2 |
| U3_P5 | U3.5 → via (19.14,2.33) → back (top edge) → via (31.56,6.93) at L1/U4 | M | given where it ends, this may be VBUS feeding the boost, which would make U3.1 something else. **Probe** |
| N_TP6…N_TP14 | each back test pad → its own via (table in `tools/gen_kicad.py`) | H on the back | the front ends (J2 / U4 pins) are not yet traced |

## Not yet resolved

- **J2 (OLED FPC) pins.** The traces from the 12 pins run under the
  connector body into vias (21.6–25.3, 3.7–7.4) and then to the back test
  pads. The pin-by-pin mapping needs a closer photo of the area between J2
  and C1.
- **U4 / R2 / R3 / R4 / L1 / C7–C9.** The populated photo is too dark there.
- **U2 pins 1, 3, 4, 8**, U2's EP, and the copper island on the back under U2.
- **S1 / S2.** Pad 2 of each is GND (plated through into the pour). Pad 1
  goes to the MCU, but which pin is not traced yet.
- Vias (5.60,11.28), (8.98,9.86), (21.17,10.60) and (29.76,10.22) have no
  net assigned.
- DRC reports via (29.29,5.37) touching C1 pad 2. Either C1 is placed about
  0.3 mm off, or that via sits right at the pad. Check this.

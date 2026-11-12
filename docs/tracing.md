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
   vias. U2's exposed pad has **no** vias.
2. Back copper: segment it by colour (copper under the mask is light blue,
   bare laminate is navy). Isolated traces stand out as islands, and
   everything else is the GND pour. See
   [trace_back_islands.jpg](img/trace_back_islands.jpg) and
   [trace_back_header.jpg](img/trace_back_header.jpg).
3. Front copper: the traces were drawn by hand in red over the bare-board
   photos in `pics/20261112_183853.xcf` (layer exported as
   [trace_front_xcf_layer.png](img/trace_front_xcf_layer.png)). Both photo
   layers in that file were registered to the board with SIFT (more than
   3,000 inlier matches each). Each red stroke was then mapped to board mm
   and snapped to the KiCad pads and vias it touches. Check image (red =
   drawn trace, green = KiCad pads, cyan = vias):
   [trace_front_xcf.jpg](img/trace_front_xcf.jpg).

Every front trace that runs to J2 passes through a via, and each of those
vias leads on the back to a solder-bumped test pad. The placeholder test-pad
nets therefore became the J2 / MCU nets below.

## 5-pad header on the back (TP1 = dot end, nearest USB)

| Pad | Net | Path | Conf. |
|-----|-----|------|-------|
| TP1 | **GND** | stub into the back GND pour | M |
| TP2 | **SWCLK** | back trace → via (5.84, 8.73) → U1.24 (PA14) | H |
| TP3 | **VBUS** | back strap → C5.2 / VBUS | M |
| TP4 | **SWDIO** | back trace → via (5.47, 7.49) → U1.23 (PA13) | H |
| TP5 | **NRST** | back trace → via (12.64, 6.70) → U1.4 (NRST), R1.1 | H |

## Power

| Net | Members | Conf. | Notes |
|-----|---------|-------|-------|
| VBUS | J1.1, C5.2, TP3, **U3.1, U3.3**, C12.1, **L1.1, U4.4**, C3.2 | H | Reaches the boost through via (19.14,2.33) → back along the top edge → via (31.56,6.93). |
| +3V0 | **U3.5**, U1.1, U1.5, U1.17, U2.7, C2.2, R1.2, C10.1, J2.4, U4.6 | H | U3 is a SOT-23-5 LDO: pins 1 (VIN) and 3 (EN) on VBUS, pin 2 GND, pin 5 VOUT. |
| GND | J1 shell, U1 EP, U4 EP, U2.2, C2.1, C5.1, U3.2/C12.2, back pour | M | U3.2–C12.2 is drawn. GND on it is inferred, because C12.1 is the VBUS input cap. |
| BOOST_SW | U4.1, L1.2 | H | Switch node: the inductor runs from VBUS (L1.1) to U4.1. |
| U4_P5 | U4.5, R4.2, R3.1 (via 27.82,4.32 → back → via 29.65,1.92) | H | The node between R3 and R4. Probably the ST8R00 **feedback** (FB) pin. |
| J2_P1 | U4.8, R3.2, C1.2, J2.1 (back trace via 29.29,5.37 ↔ via 21.64,5.11, TP10) | H | Probably the **boost output**: it feeds the divider top (R3) and the output cap (C1), and goes to OLED pin 1 (panel VCC). |

`U4.6` ties to +3V0. That makes it most likely the ST8R00 EN pin, so the
boost is always on when USB is powered, and the MCU does not switch it. This
needs to be checked against the datasheet pinout.

## OLED connector J2 (pin 1 = top)

| J2 pin | Net | Other end | Conf. | Guess |
|--------|-----|-----------|-------|-------|
| 1 | J2_P1 | U4.8 / R3 / C1 (boost out), TP10 | H | VCC (panel, 6–12 V) |
| 2, 3 | — | not drawn | — | GND / NC? |
| 4 | +3V0 | via (18.75,5.59) | H | VDD (logic) |
| 5 | PA1 | U1.7, TP8 | H | RES# or CS# (GPIO) |
| 6 | PA2 | U1.8 → back → via (17.54,6.18), TP7 | H | D/C# or CS# (GPIO) |
| 7 | PA0 | U1.6, TP11 | H | RES#/CS#/D/C# (GPIO) |
| 8 | PA5 | U1.11, TP9 | H | **SCLK** (SPI1_SCK) |
| 9 | PA7 | U1.13, TP12 | H | **SDIN** (SPI1_MOSI) |
| 10 | J2_P10 | R2.2, TP6 (thick trace) | H | IREF (resistor R2)? |
| 11 | J2_P11 | C7.1, TP14 | H | VCOMH (cap)? |
| 12 | J2_P12 | C8.1, C9.1, TP13 | H | VCC/VBAT decoupling? |

PA5 and PA7 are the STM32F042 SPI1 SCK/MOSI pins, so the display is driven
by **4-wire SPI**, write-only (no MISO). PA0, PA1 and PA2 are the three
control GPIOs.

## Secure element U2

| Pin | Net | Other end | Conf. |
|-----|-----|-----------|-------|
| 2 | GND | pour | M |
| 3 | SE_P3 | via (21.17,10.60) → back, not resolved | M |
| 5 | SE_P5 | via (12.93,8.55) → back → via (5.74,4.16) → **U1.18 (PA8)** | H |
| 6 | SE_P6 | via (13.18,9.42) → back → via (5.97,6.03) → **U1.20 (PA10)** | H |
| 7 | +3V0 | U1.1, C2.2 decoupling | H |

On the STM32F042, PA8 is USART1_CK (or MCO), PA9 is USART1_TX and PA10 is
USART1_RX. PA8 → U2.5 fits an ISO 7816 **CLK** driven by USART1 in smartcard
mode. In smartcard mode, though, I/O is on TX (PA9), not RX (PA10). PA9 goes
to via (5.70,5.18) and its back route is not resolved yet. It could be the
path to U2.3 (via 21.17,10.60). **Probe PA9 ↔ U2.3.**

## Buttons

| Button | Net | Conf. | Notes |
|--------|-----|-------|-------|
| S2 pad 1 | PA15 (U1.25) | H | |
| S1 pad 1 | S1_P1 → via (29.76,10.22) → back | M | The MCU pin is not traced. U1.30 (PB7) also goes to a via (8.98,9.86) and onto the back, so **PB7 is the likely candidate**. |

Pad 2 of each switch is GND.

## Still open

- **Conflict at C5:** the drawn stroke from via (3.80,2.42) runs through C5.1
  and joins U1.17 / via (6.91,3.65). The back tracing has via (3.80,2.42) on
  GND and via (6.91,3.65) on +3V0. The KiCad netlist keeps them separate.
  Check with a meter.
- The back routes of PA9 and PB7, and of U2.3 and S1.
- J2 pins 2 and 3. U2 pins 1, 4, 8 and the EP. R2.1, R4.1 (probably GND) and
  C7.2/C8.2/C9.2 (probably GND).
- Via (5.60,11.28) has no net.

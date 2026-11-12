# Ledger Nano S — Hardware Reverse Engineering

Notes on the hardware of a Ledger Nano S, starting from photos of the bare
PCB. Raw photos are in [`pics/`](pics/). Zoomed crops of the key parts are in
[`docs/img/`](docs/img/).

> **How sure are we?** Each item below is marked as one of:
> **[confirmed]** (read directly off the board), **[likely]** (strong
> evidence but not checked electrically) or **[hypothesis]** (needs probing).

## Photos

| File | Content |
|------|---------|
| `20261112_174544.JPG` | Back side, far half (button S1 / U4 end) |
| `20261112_174549.JPG` | Back side, USB half (5-pad header, U1 thermal vias) |
| `20261112_174600.JPG` | Front, USB half (J1, U1, U2, U3, S2) |
| `20261112_174607.JPG` | Front, far half (J2, U4, L1, S1) |
| `20261112_174622.JPG` | Front, far half (sharper) |
| `20261112_174629/34/41.JPG` | Front, USB half (several focus/lighting variants) |
| `20261112_183829/53.JPG` | Front, USB half, **components removed** (U1, U2, U3, J1, S2 off) |
| `20261112_183835/41.JPG` | Front, far half, **components removed** (J2, U4, L1, C1, C7-C9, S1 off) |
| `20261112_183926.JPG` | Removed U2 and U1, markings upright (ST pin-1 dot at bottom-left) |

The back-side photos are mirrored compared to the front: on the back the USB
connector is on the right.

## Board overview

- 2-layer-looking (maybe more) blue soldermask PCB, long thin strip that fits
  in the swivel case. Notches along the top edge line up with the case clips.
- All parts are on the front (top) side. The back has only traces, vias, test
  pads and the through-hole legs/tabs of J1 and the buttons.
- PCB date code on the back silkscreen: **`1751`** (likely 2017, week 51),
  next to the literal text `YWX` (probably the fab's year/week template
  label). This fits the component date codes (weeks 744 and 749 of 2017).
- An orange paint dot on the USB shield looks like a factory QC/inspection
  mark.
- The PCB edges are rough and fibrous all around. This could be from
  depanelization or from removing the board from its case.

## KiCad reconstruction

There is a KiCad 10 project in [`kicad/`](kicad/). It has the board outline,
every part placed from the photos, the photos as aligned underlay layers, and
a schematic with the nets known so far. Details and assumptions are in
[docs/kicad.md](docs/kicad.md).

## Bill of materials (as seen)

| Ref | Marking | Package | Identification |
|-----|---------|---------|----------------|
| **U1** | `F042K6` / `GQ22Z 1193` / `CHN 749 A`, ST logo, e3 | UFQFPN32 (5×5 mm) with exposed pad | **STM32F042K6** Cortex-M0, 32 KB Flash, 6 KB RAM, crystal-less USB FS. This is the main (non-secure) MCU. It handles USB, the display and the buttons. Date code 2017 wk 49. **[confirmed]** |
| **U2** | `NBO` / `PHL744` / `7B`, ST logo | DFN8 + exposed pad, **4.0 x 4.2 mm** (measured). Land pattern: pads 1.2 x 0.75 mm, pitch 0.98 mm, 2.1 x 3.45 mm EP with no vias | ST part, probably the **secure element** (ST31H320 family). ST prints internal codes rather than the part number. It is **not** an MFF2 package (MFF2 is 5x6 mm), so its pinout is ST's own (see below). Date 2017 wk 44. **[likely]** |
| **U3** | `AD30` | SOT-23-5 (3+2 leads), pin 1 dot next to "C12" | **3.0 V LDO**: pins 1 (VIN) and 3 (EN) on VBUS with input cap C12, pin 2 GND, pin 5 (VOUT) on the +3V0 rail. **[likely, traced]** |
| **U4** | `8R00W` / `MYS749`, ST logo, e4 | DFN8 4×4 mm with exposed pad (2×3 thermal vias on the back) | **ST8R00**, a synchronous PWM step-up DC-DC converter. Input 4–6 V, so it must run from USB VBUS rather than the 3.0 V rail. Output is set to 6–12 V by a resistor divider. Switches at 1.7 MHz, up to 1 A. Its external parts are L1, C7–C9 and the R2/R4 divider. The 6–12 V output fits an SSD1306-class OLED panel VCC (7–15 V), so it **almost certainly powers the display**. Date 2017 wk 49. **[likely — marking + datasheet]** |
| **L1** | `100` | ~3×3 mm shielded power inductor | 10 µH. It is the inductor for the ST8R00 boost converter. **[likely]** |
| **J1** | — | Micro-USB B receptacle, SMD with through-hole shield tabs | USB power and data. **[confirmed]** |
| **J2** | pin 1 / pin 12 marked | 12-pin FPC/FFC connector, bottom-contact flip-lock | **OLED display** flex. The Nano S panel is a 128×32 monochrome OLED, usually driven by an SSD1306-class controller. **[likely]** |
| **S1, S2** | — | Side-actuated SMD tactile switches (kapton covered) | The two user buttons. **[confirmed]** |
| C2, C3, C5, C7, C8, C9, C10, C12 | — | 0402 / 0603 / 0805 MLCC | Decoupling and bulk caps. C7–C9 (0805) sit at the regulator. |
| C1 | — | 0603 | The cap just left of the "C7" label, next to the "C1" silkscreen (found while placing parts in KiCad). |
| R1, R2, R3, R4 | — | 0402 | R2/R4 are a pair next to U4. They are probably the ST8R00 feedback divider, which sets the output voltage (6–12 V). |

Crops: [U1](docs/img/u1_stm32f042k6.jpg) · [U2](docs/img/u2_marking.jpg) ·
[U3](docs/img/u3_ad30.jpg) · [U4](docs/img/u4_marking.jpg) ·
[J2](docs/img/j2_fpc.jpg) · [L1/C7–C9](docs/img/l1_c7-c9.jpg)

## U2 secure element pinout

U2 is a DFN8 measuring 4.0 × 4.2 mm. That is **not** the MFF2 SIM package
(5×6 mm), so there is no reason to expect the standard MFF2 / ISO 7816
pinout. The pinout is ST's own for this package.

**Pin numbering:** the package dot is at the bottom-right in the front photos,
so going counter-clockwise from the top view:

```
            (towards U1/STM32)
              L1  ┌──────┐  R1
   pin 5 ───► ■   │      │   ■ ◄── pin 4
   pin 6 ───► ■   │  U2  │   ■ ◄── pin 3
   pin 7 ───► ■   │      │   ■ ◄── pin 2
   pin 8 ───► ■   │     •│   ■ ◄── pin 1
              L4  └──────┘  R4   (J2 side)
```

**What the board shows** (traces seen visually, not yet checked with a meter):

| Pin | Observation | Likely function |
|-----|-------------|-----------------|
| 1 | ? | ? |
| 2 | Connected to the ground pour | **GND** |
| 3 | Via to the back, destination not traced yet | I/O? (maybe PA9 / USART1_TX) |
| 4 | ? | ? |
| 5 | STM32 **PA8** (USART1_CK / MCO) | CLK |
| 6 | STM32 **PA10** (USART1_RX) | I/O or RST |
| 7 | +3V0 rail (U3 out, U1.1), decoupled by C2 | **VCC** |
| 8 | ? | ? |

Crop: [u2_context.jpg](docs/img/u2_context.jpg)

The observed GND = 2 / VCC = 7 does not match the standard MFF2 pin mapping
either, which is consistent with this being a different package. The ST31H320
datasheet (NDA-only) would have the real pinout, so we have to map it from the
board.

Pin 5 lands on PA8 (USART1_CK) and pin 6 on PA10 (USART1_RX). That points
to USART1 driving the link, possibly in **smartcard mode** with PA8 as the
clock. In smartcard mode the I/O line is on TX (PA9), and PA9 goes to a via
whose back route is not yet traced. See [docs/tracing.md](docs/tracing.md).

## Back side / test access

- **5-pad row** with silkscreen rings near the top edge (USB half), with a
  dot marking one end. These are round solder-bumped pads, not plated
  through-holes. They form the STM32 **SWD port**: TP1 GND, TP2 SWCLK,
  TP3 VBUS, TP4 SWDIO, TP5 NRST. **[likely, traced]** Crop:
  [back_5pad_header.jpg](docs/img/back_5pad_header.jpg)
- 9 more **solder-bumped test pads** sit on the **OLED connector nets**:
  SPI SCK/MOSI, the PA0/PA1/PA2 control lines, and the J2.1/J2.10–12 power
  pins. They are bed-of-nails test points for the display interface.
  **[likely, traced]**
- **3×3 thermal via grid** = U1 exposed pad. **2×3 via grid** at the far end =
  U4 exposed pad.
- Large oval pads next to the USB end = J1 shield tabs.

## Expected architecture (from public Ledger documentation)

```
 USB ──J1──► STM32F042K6 (U1, "MCU") ◄──ISO7816/SPI-ish──► ST31 Secure Element (U2?)
                 │   │
                 │   └── S1 / S2 buttons
                 └────── J2 ──► 128×32 OLED (SSD1306-class)
 Power: VBUS (5 V) ─► U3 LDO ─► 3.0 V logic (MCU, SE, OLED VDD)
        VBUS (5 V) ─► U4 ST8R00 + L1 boost ─► 6–12 V ─► OLED panel VCC (J2)
```

In the Nano S design the MCU acts as a proxy. It owns USB, the screen and the
buttons. The secure element runs BOLOS and the apps, and it drives the UI
through the MCU (the "SEPROXYHAL" protocol).

## Next steps / TODO

- [ ] Probe the 5-pad header: continuity to U1 pins PA13 (SWDIO), PA14
      (SWCLK) and NRST. Try `st-link`/OpenOCD (it will probably be RDP-locked).
- [ ] U2: confirm GND (2) and VCC (7) with a meter. Trace pin 3. Check if
      pins 1, 4 and 8 are connected. Map pins 5 and 6 to their STM32 pins
      (USART TX/CK in smartcard mode? GPIO?).
- [ ] Sniff the MCU↔SE link (logic analyzer on I/O + CLK) and look for the
      ISO 7816 ATR after reset.
- [ ] Read R2/R4 values (or measure the boost output) and confirm the
      OLED VCC voltage. Check that it reaches J2. Check whether the MCU
      drives the ST8R00 EN pin, which would switch the display power.
- [x] J2 pinout traced: SPI1 (PA5/PA7) + PA0/PA1/PA2 + 3V0 + boost out (see
      [docs/tracing.md](docs/tracing.md)). Still to do: match it against the
      SSD1306 FPC pinouts we know.
- [ ] Measure the U3 output (expected 3.0 V).
- [ ] Find where PA9 and PB7 go on the back (SE I/O? S1?), and check the
      C5 / via conflict noted in docs/tracing.md.
- [ ] Get higher-resolution, non-mirrored back photos for full trace mapping.

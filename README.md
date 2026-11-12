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

## Bill of materials (as seen)

| Ref | Marking | Package | Identification |
|-----|---------|---------|----------------|
| **U1** | `F042K6` / `GQ22Z 1193` / `CHN 749 A`, ST logo, e3 | UFQFPN32 (5×5 mm) with exposed pad | **STM32F042K6** Cortex-M0, 32 KB Flash, 6 KB RAM, crystal-less USB FS. This is the main (non-secure) MCU. It handles USB, the display and the buttons. Date code 2017 wk 49. **[confirmed]** |
| **U2** | `NBO` / `PHL744` / `7B`, ST logo | DFN8 ~5×6 mm (pad layout matches **MFF2**) | ST part, probably the **secure element** (ST31H320 family). ST prints internal codes rather than the part number. The package and pad layout match the ETSI MFF2 form factor (the soldered "SIM chip" package), so it is most likely a smart-card style device with the standard ISO 7816 pinout (see below). Date 2017 wk 44. **[likely]** |
| **U3** | `AD30` | SOT-23-5 (3+2 leads), pin 1 dot next to "C12" | Most likely a **3.0 V LDO** (the "30" suffix is the usual voltage code). Needs a check of the in/out pins. **[likely]** |
| **U4** | `8R00W` / `MYS749`, ST logo, e4 | DFN8 4×4 mm with exposed pad (2×3 thermal vias on the back) | **ST8R00**, a synchronous PWM step-up DC-DC converter. Input 4–6 V, so it must run from USB VBUS rather than the 3.0 V rail. Output is set to 6–12 V by a resistor divider. Switches at 1.7 MHz, up to 1 A. Its external parts are L1, C7–C9 and the R2/R4 divider. The 6–12 V output fits an SSD1306-class OLED panel VCC (7–15 V), so it **almost certainly powers the display**. Date 2017 wk 49. **[likely — marking + datasheet]** |
| **L1** | `100` | ~3×3 mm shielded power inductor | 10 µH. It is the inductor for the ST8R00 boost converter. **[likely]** |
| **J1** | — | Micro-USB B receptacle, SMD with through-hole shield tabs | USB power and data. **[confirmed]** |
| **J2** | pin 1 / pin 12 marked | 12-pin FPC/FFC connector, bottom-contact flip-lock | **OLED display** flex. The Nano S panel is a 128×32 monochrome OLED, usually driven by an SSD1306-class controller. **[likely]** |
| **S1, S2** | — | Side-actuated SMD tactile switches (kapton covered) | The two user buttons. **[confirmed]** |
| C2, C3, C5, C7, C8, C9, C10, C12 | — | 0402 / 0603 / 0805 MLCC | Decoupling and bulk caps. C7–C9 (0805) sit at the regulator. |
| C1 | — | — | Silkscreen sits next to J2, but no part is visible. It is either hidden under the connector or left unpopulated. |
| R1, R2, R3, R4 | — | 0402 | R2/R4 are a pair next to U4. They are probably the ST8R00 feedback divider, which sets the output voltage (6–12 V). |

Crops: [U1](docs/img/u1_stm32f042k6.jpg) · [U2](docs/img/u2_marking.jpg) ·
[U3](docs/img/u3_ad30.jpg) · [U4](docs/img/u4_marking.jpg) ·
[J2](docs/img/j2_fpc.jpg) · [L1/C7–C9](docs/img/l1_c7-c9.jpg)

## U2 secure element: expected MFF2 / ISO 7816 pinout

The table below is the standard MFF2 pin mapping (ETSI TS 102 671). It maps
the ISO 7816 card contacts C1–C8 onto the DFN8 pads. It still has to be
checked on this board **[hypothesis]**:

| DFN pin | ISO 7816 contact | Signal |
|---------|------------------|--------|
| 1 | C5 | GND |
| 2 | C6 | VPP / SWP (often NC) |
| 3 | C7 | I/O (half-duplex data) |
| 4 | C8 | RFU / spare (USB D+ on some SIMs) |
| 5 | C4 | RFU / spare (USB D− on some SIMs) |
| 6 | C3 | CLK |
| 7 | C2 | RST |
| 8 | C1 | VCC |

Pin 1 is the corner next to the dot on the package (bottom right in the
photos). If the pinout holds, the MCU–SE link is probably ISO 7816 driven by
an STM32F042 USART in its built-in **smartcard mode**: USART_TX open-drain to
I/O, USART_CK to CLK, and a GPIO to RST. Two things could suggest a
non-standard link: spare pads C4/C8 being routed, or C6 being used.

## Back side / test access

- **5-pad row** with silkscreen rings near the top edge (USB half), with a dot
  marking one end. These are round pads with solder bumps, not plated
  through-holes. They are almost certainly a **factory programming/test
  header**. Best guess: the STM32 SWD port (SWDIO, SWCLK, NRST, VDD, GND).
  **[hypothesis]** Crop: [back_5pad_header.jpg](docs/img/back_5pad_header.jpg)
- About 12 more **solder-bumped round test pads** without rings are spread
  over the back (mostly the far half). They are likely pogo-pin bed-of-nails
  test points, for example for the SE ISO7816 lines and the display signals.
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
- [ ] Check the U2 MFF2 pinout with a continuity test (GND/VCC first). Then
      map I/O, CLK and RST to U1 pins and see if they land on a USART
      (smartcard mode). Check whether C4/C6/C8 are connected.
- [ ] Sniff the MCU↔SE link (logic analyzer on I/O + CLK) and look for the
      ISO 7816 ATR after reset.
- [ ] Read R2/R4 values (or measure the boost output) and confirm the
      OLED VCC voltage. Check that it reaches J2. Check whether the MCU
      drives the ST8R00 EN pin, which would switch the display power.
- [ ] Map the J2 pinout against the SSD1306 FPC pinouts we know.
- [ ] Measure the U3 output (expected 3.0 V).
- [ ] Get higher-resolution, non-mirrored back photos for full trace mapping.

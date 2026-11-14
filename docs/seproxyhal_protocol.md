# The SEPROXYHAL protocol (Nano S)

SEPROXYHAL ("Secure Element PROXY Hardware Abstraction Layer", "SEPH" in the sources) is the protocol on the
single-wire ISO 7816 link between the secure element (SE, U2) and the MCU (U1). The SE runs the application and
holds the secrets; the MCU is a "dumb" proxy for the hardware it owns — the screen, buttons, USB and (on other
models) BLE/NFC. This document describes the protocol as seen on the wire in the captures (see
[seproxyhal_capture.md](seproxyhal_capture.md)) and as defined in Ledger's published sources
([nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware),
`seproxyhal/include/seproxyhal_protocol.h`).

## Link and framing

- **Physical:** ISO 7816-3, T=0, 8E2 characters on the I/O line, clocked by the MCU (~12 MHz on the Nano S).
  The ATR is sent at 372 clocks/bit; a PPS then switches to **4 clocks/bit (~3 Mbaud)** — Ledger reads Di
  index 8 as 128, not ISO's 12. See [seproxyhal_capture.md](seproxyhal_capture.md) for the startup sequence.
- **Packet framing:** every packet is `tag (1 byte) | length (2 bytes, big endian) | payload`. The length is
  the payload size. Larger transfers (USB/BLE/APDU, flash chunks) are split into several packets.
- **Direction is encoded in the tag range:**
  | Range | Direction | Meaning |
  |---|---|---|
  | `0x01`–`0x2f` | MCU → SE | **Events** (button, ticker, USB/BLE traffic, status, flash chunk) |
  | `0x31`–`0x5f` | SE → MCU | **Commands** (drive screen, USB/BLE config, read flash, power, …) |
  | `0x60`–`0x6f` | SE → MCU | **Statuses** (the reply that ends the SE's turn) |

- **Turn-taking:** the MCU sends one Event, the SE answers with zero or more Commands, then exactly one Status
  (almost always `GENERAL_STATUS`, "last command") that hands the turn back to the MCU. `MORE_TIME` lets the SE
  keep the bus while it is busy. This is why `GENERAL_STATUS` is by far the most common packet in every capture.

## Startup

1. The MCU releases reset and clocks the SE; the SE sends its **ATR** (`3B 90 98 10 00`).
2. **PPS** negotiates the fast rate (`FF 10 98 77`, echoed by the SE).
3. The MCU sends **`SESSION_START_EVENT`** (`0x01`): a kind byte (bit 1 = request BLE, bit 2 = recovery), a
   4-byte feature bitmap, and a length-prefixed version string. On MCU firmware it then adds more
   length-prefixed fields (MCU bootloader version, key ids). The Nano S sends the version NUL-terminated.
   - Feature bits seen: `USB` (`0x01`), `SCREEN_SML` (`0x200`), 2 buttons (`0x2<<4`), and from 1.6 on
     `MCU secure instruction set` (`0x10000000`). Other defined bits: `BLE` `0x02`, `TOUCH` `0x04`,
     `BATTERY` `0x08`, `SCREEN_BIG` `0x100`, `LEDRGB` `0x1000`, `MCU bootloader` `0x20000000`.
4. At boot the SE reads the whole MCU flash to verify it (`UNSEC_CHUNK_READ`/`_EXT`), then drives the screen.

## Tag reference

Tags from `seproxyhal_protocol.h` (published, 1.1-era) plus newer ones named by
[visgrok](https://github.com/KarpelesLab/visgrok)'s decoder. **Obs.** marks tags actually seen in our three
captures (cap1 = MCU 1.6, cap2 = MCU 1.0, cap3 = MCU 1.12 with a firmware update).

### Events (MCU → SE)

| Tag | Name | Obs. | Payload / meaning |
|---|---|---|---|
| `0x01` | SESSION_START_EVENT | 1·2·3 | kind, feature bitmap (4 BE), version string(s) |
| `0x02` | BLE_PAIRING_ATTEMPT / BLE_CONNECTION_EVENT | | BLE (not on Nano S) |
| `0x03` | BLE_WRITE_REQUEST_EVENT | | BLE |
| `0x04` | BLE_READ_REQUEST_EVENT | | BLE |
| `0x05` | BUTTON_PUSH_EVENT | 1·2·3 | button bitmap in bits 1–7 (bit set = pressed); every 100 ms while changing |
| `0x06` | NFC_FIELD_DETECTION_EVENT | | NFC |
| `0x07` | NFC_APDU_RECEIVED_EVENT | | NFC |
| `0x08` | BATTERY_NOTIFICATION_EVENT | | battery (Nano X) |
| `0x09` | M24SR_GPO_CHANGE_EVENT | | NFC chip |
| `0x0a` | M24SR_RESPONSE_APDU_EVENT | 2 | seen once at start on cap2; NFC response APDU transport |
| `0x0b` | BLE_NOTIFY_INDICATE_EVENT | | BLE |
| `0x0c` | FINGER_EVENT | | touch (touch=1, release=2) |
| `0x0d` | DISPLAY_PROCESSED_EVENT | 1·2·3 | MCU finished drawing a Display Status; frees the next Status |
| `0x0e` | TICKER_EVENT | 1·2·3 | `ms_since_power_on` (4 BE); periodic, interval set by SET_TICKER_INTERVAL |
| `0x0f` | USB_EVENT | 1·2·3 | reset(1)/SOF(2)/suspended(4)/resumed(8) |
| `0x10` | USB_EP_XFER_EVENT | 1·2·3 | `ep, dir(setup/in/out), len, data` — a USB transfer the MCU saw |
| `0x11` | BLE_CONNECTION_EVENT | | BLE |
| `0x12` | UNSEC_CHUNK_EVENT | 1·2·3 | **the MCU's reply with flash bytes** (answer to a chunk read) |
| `0x13` | ACK_LINK_SPEED | | ack(1)/nack(0) of a SET_LINK_SPEED |
| `0x14` | BLUENRG_RECV_EVENT / BLE_RECV_EVENT | | BLE transport |
| `0x15` | STATUS_EVENT | | flags, backlight %, LED ARGB, battery mV |
| `0x16` | CAPDU_EVENT | | raw command APDU transport |
| `0x17` | I2C_EVENT | | I2C |
| `0x18`–`0x1f` | BLE_RECV / BOOTLOADER_RAPDU / ITC / POWER_BUTTON / NFC / QI_FLASH_CHECKSUM / NFC / SE_READY_TO_RECEIVE_START_SESSION | | newer events (not on Nano S) |

### Commands (SE → MCU)

| Tag | Name | Obs. | Payload / meaning |
|---|---|---|---|
| `0x31` | MCU / MCU_BOOTLOADER | 3 | MCU control. `0x31`/length 0 "lock"; disabled as a bootloader entry "for security". visgrok labels the MCU-firmware session line from it. |
| `0x32` | UNSEC_CHUNK_READ | 2 | read flash sequentially: `length(2 BE), reset_flag(1)`; first reply carries the signed length |
| `0x33` | UNSEC_CHUNK_READ_EXT | 1·3 | read flash at offset: `length(2 BE), kind(1)`, kind 2 adds `offset(4 BE)`; kind 4 returns the signed length |
| `0x34` | NFC_POWER | | newer |
| `0x38` | BLE_SEND | | BLE |
| `0x3e` | SET_SCREEN_CONFIG | 1·2·3 | `flags(1): pwron 0x80 / rotation / invert`, `brightness %` |
| `0x3f` | SET_LINK_PROP / SET_LINK_SPEED (old) | | link debug mode |
| `0x40` | BLUENRG_SEND | | BLE |
| `0x41`–`0x43` | BLE/NFC service settings | | BLE/NFC |
| `0x44` | BLE_RADIO_POWER | 1·3 | sent "off" on the Nano S (no radio) before USB/power-down |
| `0x45` | NFC_RADIO_POWER | | NFC |
| `0x46` | SE_POWER_OFF | 3 | SE announces it is powering off |
| `0x48` | BLE_NOTIFY_INDICATE / BLE_SECURITY_DB | | BLE |
| `0x49` | BATTERY_CHARGE | | battery |
| `0x4a` | NFC_RAPDU | | NFC |
| `0x4b` | DEVICE_OFF | 3 | power the device off |
| `0x4c` | MORE_TIME | 1·2·3 | keep the bus while the SE is busy (paired with TICKER) |
| `0x4d` | M24SR_C_APDU | | NFC |
| `0x4e` | SET_TICKER_INTERVAL | 1·2·3 | ticker period in ms (100 ms observed) |
| `0x4f` | USB_CONFIG | 1·2·3 | `connect/disconnect/addr/endpoints` — the SE drives the USB device |
| `0x50` | USB_EP_PREPARE | 1·2·3 | `ep, dir(setup/in/out/stall/unstall), len, data` — queue a USB transfer |
| `0x51` | SET_LED | | RGB LED (Nano X) |
| `0x52` | REQUEST_STATUS | | ask for peripheral power / charge state |
| `0x53` | RAPDU | | raw response APDU transport |
| `0x54` | I2C_XFER | | I2C |
| `0x56`–`0x5f` | PLAY_TUNE / SET_SHIP_MODE / QI_FLASH / NBGL_* / SET_TOUCH_STATE / ITC_CMD / DBG_SCREEN_DISPLAY_STATUS / PRINTF | | newer models / debug |

### Statuses (SE → MCU, end the turn)

| Tag | Name | Obs. | Payload / meaning |
|---|---|---|---|
| `0x60` | GENERAL_STATUS | 1·2·3 | `0x0000` = "last command": the SE is done, MCU may send the next Event |
| `0x61` | PAIRING_STATUS | | BLE |
| `0x62`–`0x64` | BLE/NFC read/notify statuses | | BLE/NFC |
| `0x65` | SCREEN_DISPLAY_STATUS | 1·2·3 | **a BAGL element to draw** (rectangle, line, label, icon with bitmap); the Nano S MCU renders the screen from these (see "Higher layers" below). |
| `0x66` | PRINTF_STATUS | | debug text |
| `0x67` | SET_LINK_SPEED | | `mhz(1), etu(1)` — switch the link rate (used after the PPS on newer builds) |
| `0x68` | SCREEN_ANIMATION_STATUS | 1·2 | screen animation (e.g. vertical split slide); replied with a DISPLAY_PROCESSED_EVENT |
| `0x69` | SCREEN_DISPLAY_RAW_STATUS | | raw framebuffer blit: `start/next`, geometry, bpp, palette, packed bitmap |
| `0x6a` | BOOTLOADER_CAPDU_STATUS | | newer |

## What each firmware version actually used

All three captures speak the same core protocol; the differences are at the edges.

| | cap2 — MCU 1.0 / SE 1.3.1 | cap1 — MCU 1.6 | cap3 — MCU 1.12 / SE 1.6.0 |
|---|---|---|---|
| SESSION_START version | "1.0" | "1.6" | "1.12" (+ bootloader 0.11) |
| Feature bitmap | `0x00000221` (USB, 2 buttons, small screen) | `0x10000221` (+ MCU secure instruction set) | `0x10000221` |
| Flash read command | `UNSEC_CHUNK_READ` (0x32, sequential) | `UNSEC_CHUNK_READ_EXT` (0x33, by offset) | `UNSEC_CHUNK_READ_EXT` (0x33) |
| Screen | BAGL display + animation | BAGL display + animation | BAGL display |
| Power-down tags | — | BLE_RADIO_POWER | BLE_RADIO_POWER, SE_POWER_OFF, DEVICE_OFF, MCU "lock" |
| Notes | M24SR_RESPONSE_APDU_EVENT at start; onboarding over USB | PIN then dashboard | includes a firmware update (two host secure-channel sessions) |

Observations:

- **`UNSEC_CHUNK_READ` (0x32) → `UNSEC_CHUNK_READ_EXT` (0x33).** MCU 1.0 uses the old sequential read; 1.6 and
  1.12 use the offset-based read and add the "MCU secure instruction set" feature bit. This is the most visible
  protocol change across versions and lines up with Ledger's 1.4 rework of how the SE authenticates the MCU.
- **No BLE/NFC/touch/battery/LED tags** appear on the Nano S, as expected — those peripherals don't exist. The
  SE still sends `BLE_RADIO_POWER off` at shutdown.
- **`SET_LINK_SPEED` (0x67) was not seen as a packet;** the rate change happens through the ISO 7816 PPS
  instead (visgrok reports it as "link speed: 4 clock cycles per bit").
- **`MCU` (0x31), `SE_POWER_OFF` (0x46), `DEVICE_OFF` (0x4b)** only showed up in cap3, around the firmware
  update and a clean power-down ("lock" then off).

## Higher layers carried over SEPROXYHAL

The protocol is just transport; the interesting content rides on top:

- **Screen (BAGL):** the Nano S MCU has no framebuffer of its own — the SE sends each UI element as a
  `SCREEN_DISPLAY_STATUS`, and the MCU draws it. So everything on screen, including each PIN digit as it is
  entered, crosses this link in clear. visgrok reconstructs the screens (`visgrok screens`).
- **USB:** the SE answers USB enumeration itself; the MCU only forwards `USB_EP_XFER_EVENT` in and
  `USB_EP_PREPARE` out. Device descriptor VID `2c97` / PID `0001`, strings "Ledger" / "Nano S".
- **APDUs:** host↔SE APDUs are reassembled from the USB HID reports (Ledger transport framing, channel +
  `0x05` + sequence + length). Dashboard commands seen: `GET_VERSION`, `VALIDATE_TARGET_ID`,
  `INITIALIZE_AUTHENTICATION`, `VALIDATE_CERTIFICATE`, `ONBOARD`.
- **MCU flash check:** the `UNSEC_CHUNK_*` exchange lets the SE read and verify the MCU firmware signature at
  every boot (see [seproxyhal_capture.md](seproxyhal_capture.md)).

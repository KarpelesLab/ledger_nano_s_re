# SEPROXYHAL capture (MCU ↔ secure element)

A logic analyzer capture of the link between the MCU (U1) and the secure element (U2) of a working Nano S:
power on, PIN entry, the dashboard, then USB being enabled and enumerated by the host.

| | |
|---|---|
| File | `capture-nanos-20261114-163900.vgk` (visgrok, not in this repository: 60 MB) |
| Analyzer | Sipeed SLogic16 U3, 200 MHz, decoded with [visgrok](https://github.com/KarpelesLab/visgrok) |
| Channels | 0 = SE CLK (U2.5 / PA8), 1 = SE I/O (U2.3 / PA9), 2 = SE RST (U2.6 / PA10) |
| Length | 33 s; one SE session of 23.4 s, 50 758 characters, 1 708 SEPROXYHAL packets |

Decoding, with visgrok's `capture_nanos.sh` roles:

```sh
visgrok log capture-nanos-20261114-163900.vgk --uart-proto seproxyhal --timeline
visgrok log capture-nanos-20261114-163900.vgk --uart-proto seproxyhal -o capture.log
visgrok screens capture-nanos-20261114-163900.vgk -o screens
```

## Physical layer

- **Clock:** 11.963 MHz from the MCU's PA8 (USART1_CK in smartcard mode, most likely its 48 MHz clock divided
  by 4), 48% duty. It runs
  from 5.41 s, about 100 ms before reset is released (5.514 s).
- **ATR:** `3B 90 98 10 00`, 0.8 ms after reset, at the default 372 clocks per bit (32.2 kbaud), the same
  ATR as the chip off the board.
- **PPS:** the MCU sends `FF 10 98 77` (T=0, PPS1 = `98`) and the SE echoes it, accepting.
- **After the PPS the link runs at 4 clock cycles per bit, 2.99 Mbaud:** bit cells on the I/O line measure
  335 ns. ISO 7816-3 gives Di index 8 as 12 (F/D = 512/12, 42.7 clocks per bit); Ledger uses it as 128
  (512/128 = 4). The earlier reading of the ATR in the README (about 45.6 kbaud) was wrong.
- Characters are 8E2 (T=0 framing) in both directions on the single I/O line.

## What happens

| Time (s) | Event |
|---|---|
| 5.514 | Reset released, ATR, PPS |
| 5.650 | MCU → SE `SESSION_START_EVENT`: features `0x10000221` (USB, MCU secure instruction set, small screen), SEPROXYHAL version "1.6" |
| 5.657–6.649 | The SE reads the MCU's whole flash (see below) |
| 6.815 | SE → MCU `SET_SCREEN_CONFIG` (power on, brightness 20%), `SET_TICKER_INTERVAL` 100 ms |
| 6.83–15.0 | PIN entry: the SE draws each screen as BAGL elements (`SCREEN_DISPLAY_STATUS`: rectangles, labels, icons), the MCU sends the button presses (`BUTTON_PUSH_EVENT`) |
| 15.07 | Dashboard |
| 15.288 | Only now, after the PIN, the SE turns USB on (`USB_CONFIG` connect) |
| 15.44–15.69 | Enumeration, answered by the SE packet by packet: VID `2c97` PID `0001`, strings "Ledger", "Nano S", "0001", 73-byte configuration with 2 interfaces |
| 21.185 | SE turns USB off and sends `BLE_RADIO_POWER` off (the Nano S has no radio) |
| 28.922 | All lines stop (device unplugged) |

Packet counts: 433 `GENERAL_STATUS`, 244 `DISPLAY_PROCESSED_EVENT`, 243 `SCREEN_DISPLAY_STATUS`, 144 chunk
reads and answers, 136 `TICKER_EVENT` / `MORE_TIME`, 94 `BUTTON_PUSH_EVENT`, 57 `USB_EP_XFER_EVENT`,
44 `USB_EP_PREPARE`, 20 `USB_CONFIG`. No APDU was exchanged with a host.

The MCU holds no state of its own here: it forwards buttons, ticks and USB events and draws what the SE
sends. That also means everything on the screen, **including each PIN digit as it is selected**, crosses
this link in clear as BAGL labels, together with the button presses that choose it.

Dashboard as decoded from the link (the MCU's own fonts and glyphs are not on the wire, so visgrok draws
text with a built-in font):

![dashboard](img/seph_screen_0019.png)
![dashboard](img/seph_screen_0020.png)
![dashboard](img/seph_screen_0021.png)

## The SE reads the MCU firmware at boot

Right after the session starts, the SE reads the entire 32 KB flash of the STM32F042 (0x0000–0x7fff) with
144 `UNSEC_CHUNK_READ_EXT` commands (tag `0x33`), each answered by an `UNSEC_CHUNK_EVENT` (tag `0x12`) with
the bytes. This takes about a second (5.66 to 6.65 s), before the first screen is drawn.

Request arguments: length (2 bytes, big endian), kind (1 byte), then for kind 2 an offset (4 bytes, big
endian). Reads are mostly 240 bytes, in no particular order.

- The first request is kind 4, 4 bytes, no offset; the MCU answers `00 00 7f b8`.
- Every other request is kind 2, a plain read. Together they cover every byte of the flash once or more, with
  no conflicting values.
- At 0x7fb8 the flash holds a DER ECDSA signature (`30 44 02 20 … 02 20 …`, 70 bytes) followed by `ff ff`.
  So 0x7fb8 is the end of the signed area: the SE most likely checks a signature over the MCU firmware at every boot.
- The image starts with a Cortex-M0 vector table: initial SP 0x20001800 (top of the 6 KB of RAM), reset at
  0x080000c1.

### Relation to Ledger's published MCU source

Ledger published the MCU firmware source as
[LedgerHQ/nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware). Its last commit
is version 1.1, from August 2017. The captured image comes from the same codebase and build, but from a later
version, so it is not byte-identical to anything that source builds:

- **Same layout and build.** The source's comment gives the flash as `| vector | bootloader | [gap] |
  seproxyhal | signature |`. Its Makefile merges the bootloader and the SEPROXYHAL firmware with `srec_cat`,
  **fills the unused space with random bytes** (`-random-fill`), and signs the whole thing with
  `signMCUhex.py`: secp256k1 ECDSA over the SHA-256 of the image, then the DER signature followed by `FF`
  bytes. That matches the capture: the bytes from the end of the code (0x7804) to the signature look random,
  and the signature at 0x7fb8 is followed by `ff ff` up to the end of the flash. The random fill also explains
  the "hex digits" and other noise found elsewhere in the image.
- **Same chunk protocol, extended.** In the source, the MCU answers the SE's chunk reads from `_signed`
  (the start of flash) up to the end of the signature, and the first answer starts with the length of the
  signed area as 4 bytes big endian. The capture's kind 4 read returns that same length (0x7fb8).
- **Later version.** The source has only `UNSEC_CHUNK_READ` (0x32, sequential reads with a reset flag) and
  sends version "1.1" with features USB, 2 buttons and small screen. The device sends version **"1.6"**
  (the string is at 0x7800, at the end of its code), sets features bit `0x10000000` (MCU secure instruction
  set), and the SE uses `UNSEC_CHUNK_READ_EXT` (0x33) with explicit offsets.
- **Different signing key and address.** The published Makefile signs at 0x7fb0 with a placeholder key (it
  decodes to "No, we don't put keys on github"). The device's signature is at 0x7fb8, made with Ledger's own key.
- The published bootloader writes a magic value `0x51145E82` next to its boot address; it does not appear in
  the captured image, so the deployed bootloader differs too.

`tools/mcu_flash_from_seph.py` rebuilds the image from a `visgrok log`. The image of the captured device has
SHA-256 `2fa78bebf0f38fadc3836bd47e695d33ed39bf66c1d02476ca9f43bb2a479e46`. It is Ledger's firmware and is
not published here.

## Open questions

- Which curve and key the MCU firmware signature uses, and whether the SE refuses to start with a modified MCU image.
- Whether the random fill differs between devices (it is generated at build time, so probably not).
- Button masks: visgrok reports the first presses as "left (mask 0x02)"; check against which switch (S1 on PB7, S2 on PA15) was pressed.

# SEPROXYHAL capture (MCU ↔ secure element)

A logic analyzer capture of the link between the MCU (U1) and the secure element (U2) of a working Nano S:
power on, PIN entry, the dashboard, then USB being enabled and enumerated by the host. For the protocol itself
— framing, every tag, and which ones each firmware version uses — see
[seproxyhal_protocol.md](seproxyhal_protocol.md).

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

### The signature

Assumed **secp256k1**, as Ledger uses everywhere and as the published `signMCUhex.py` does (it signs with
the `secp256k1` Python module, libsecp256k1). The signature alone cannot prove the curve, but it is consistent:

- r = `4233dca0d1a849b76ed0a6cd4ef5fa04bfceca3eab152362aae5d12d36d22ac8`,
  s = `503dc036973e6934f7565e75e6db34c88accc8f591155c561fcd2f40f009a5b7`
- s is in the lower half of the secp256k1 group order ("low-S"), which libsecp256k1 always produces. A random s
  would be low half the time, so this is only weak evidence.
- The signed message is assumed to be SHA-256 of flash 0x0000–0x7fb7, as in `signMCUhex.py` (the
  build fills every gap, so the image is one area):
  `34c8e1ed994a446ef70c9b256d8a6e01eb949aba4b18b9f9a39b7f3878253103`.

Recovering the public key from (r, s) and that hash on secp256k1 gives two candidates, one of which is
Ledger's MCU signing key if the curve and hash assumptions hold:

```
04 0471bb4a87d8b2b86e3f8c35b88723f2ba853ce315d4ffa326ff3bd3ab4a88a3
   11dcdf0c93880b3693f63fada625693ba7ac9203aa7a91bd68f207b76eceffec
04 317fa61affbb9d93754c03234d9aa594ee7794c30228240fc3be96c70d0c4338
   121de3b01f8f83b4ac616180a78928332d6cbf7bae7b56799c59c92be158dd84
```

Recovery gives two candidates for any curve and any message, so this settles nothing by itself. The test is a
second signed MCU image with a different hash, from another firmware version on another device or from a
Ledger MCU update file. If its candidates share a key with these, that confirms the curve, the hashed
range and Ledger's key all at once.

Neither candidate appears in the MCU image (the check runs in the SE, which holds the key) or in a web search.

Background: Ledger describes this check (the SE asks the MCU to dump its memory, hashes it and checks the
signature at each boot) in its security bulletins
[LSB-002](https://donjon.ledger.com/lsb/002/) and [LSB-005](https://donjon.ledger.com/lsb/005/), which report
that it could be bypassed on older firmware (see also
[Saleem Rashid, 2018](https://saleemrashid.com/2018/03/20/breaking-ledger-security-model/)). The version-1.4
fixes changed how the SE authenticates the MCU, which may be where `UNSEC_CHUNK_READ_EXT` comes from.

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

## Second device: MCU 1.0, SE 1.3.1

`capture-nanos-20261114-174856.vgk` (325 MB, 160 s) is another Nano S, on older firmware: four SE boots, the
last one in recovery mode, onboarded from the host. The host's `GET_VERSION` reads target `0x31100002`,
SE **1.3.1**, flags `0x87` (recovery mode, signed MCU, onboarded, PIN validated), MCU **1.0**.

- **Same physical layer:** 12.05 MHz clock, ATR at 372 clocks per bit, then 4 clocks per bit.
- **Older chunk protocol, exactly as in the published source:** the SE uses `UNSEC_CHUNK_READ` (0x32: length
  and a reset flag, sequential reads). The first answer starts with the signed length, `00 00 7f b0`, then
  the flash. `SESSION_START_EVENT` gives version "1.0" and features `0x00000221` (no "MCU secure" bit).
- **Different image:** all four boots read the same image (0x0000–0x7ff7), but it differs from device 1's
  almost everywhere. It is a different build: the vector table is clean (every unused handler is 0x080000ed),
  and the bootloader's `0x51145E82` magic from the published source is at 0x400.
- **Signature at 0x7fb0, as in the published Makefile,** 70 bytes DER, low-S, followed by `46 46`: ASCII
  "FF" rather than the bytes `ff ff` (an old bug in the signing script?).
- **The two signatures share no recoverable key.** On secp256k1, device 2's signature over SHA-256 of
  0x0000–0x7faf recovers to

  ```
  04 90f5c9d15a0134bb019d2afd0bf297149738459706e7ac5be4abc350a1f81805
     7224fce12ec9a65de18ec34d6e8c24db927835ea1692b14c32e9836a75dad609
  04 d7d934d795bd9cc7751808243b0b900a3ede479de31ebb85d855a897b99a61da
     b2056802abcc4d1fff4a4712661a0bb912cda93f1af68975217414005487be5d
  ```

  None of these is one of device 1's candidates, and neither are the keys recovered with other likely
  messages (length prefixed, double SHA-256) or on P-256.
- **Onboarding over USB in recovery mode:** the host sends a dashboard `ONBOARD` APDU (`E0 D0`) that carries
  the PIN and the recovery phrase in clear. They pass through the MCU like any USB data. The device then asks
  "Allow unknown manager?" and shows the public key of the host's certificate during `VALIDATE_CERTIFICATE`.

## Third capture: a firmware update and MCU 1.12

`capture-nanos-20261114-180148.vgk` (1.25 GB, 730 s) is a longer session that includes an MCU firmware
update. It holds 32 SE boots: a long run of short reset pulses, two host secure-channel sessions (292 then
604 commands, tens of KB each, the actual update payload), and finally boot 32 running the updated firmware.
That boot reports **SEPROXYHAL version 1.12, MCU bootloader 0.11**, and the host reads target `0x31100004`,
**SE 1.6.0, MCU 1.12**, running BOLOS 1.6.0.

- **Same read path as device 1:** boot 32 uses `UNSEC_CHUNK_READ_EXT`, signed length 0x7fb8, and the image
  reads cleanly (0x0000–0x7fff, no conflicts). SHA-256 `6da013f8f3c2376b040112af6d75d13c2e108eda8c4121412ba081188f68bd8f`.
- **A third signing key — and we know which candidate.** The signature is at 0x7fb8, 71 bytes DER (the 1.6
  one was 70), followed by a single `ff`. On secp256k1 over SHA-256 of 0x0000–0x7fb7 it recovers to

  ```
  04 c44aa5822fb392069bd2aeb79898d7b263d7e8fbc4b37e21a4ca5b23d3d2c772
     1451c3eb3ee4b7a448847f1640e129d0302da06ee2edc9c8c354afa997080a6b
  04 d1152ea5fa739fd71d4812d65dfa6fbf9ac31321f368839d42d2209606493d12
     822bd3b885bf7058d19a34c51381335e6150d998312a3b35fd37a086f1308974   ← the real one
  ```

  Recovery always yields two candidates, but the SESSION_START event names the key: on 1.12 the MCU reports
  its app key id as **`f1308974`**, which is exactly the last 4 bytes of the second candidate above
  (`…a086f1308974`). So the second candidate is the actual 1.12 MCU-app signing public key. The SESSION_START
  also carries the bootloader key id **`f4d8aa43`**. Both ids are the *same ones the Nano X sends* (its
  SESSION_START blob `…04f4d8aa4304312e313604f1308974…` pairs bootloader "2.28"→`f4d8aa43` and app
  "1.16"→`f1308974`): the Nano S 1.12 and Nano X MCUs share their bootloader and app signing keys. The
  key id being the pubkey tail also confirms these ids (long treated as opaque in the Nano X capture) are
  simply truncated signing public keys.

### The three versions, their signatures

| Version | SE | Signed length | DER sig | Trailer | Signing key |
|---|---|---|---|---|---|
| MCU 1.0 | 1.3.1 | 0x7fb0 | 70 bytes | `46 46` ("FF") then `ff…` | **Ledger root of trust** (public releases) |
| MCU 1.6 | (cap. 1) | 0x7fb8 | 70 bytes | `ff ff` | other Ledger key (unknown) |
| MCU 1.12 | 1.6.0 | 0x7fb8 | 71 bytes | `ff` | Ledger MCU-app key, id `f1308974` (= Nano X app key) |

## Match against the official release images

Ledger publishes signed MCU images at
[LedgerHQ/nanos-nonsecure-firmware-releases](https://github.com/LedgerHQ/nanos-nonsecure-firmware-releases):
`nanosr1` (version 1.0) and `nanosr11` (version 1.1), each a `token.loadable.signed_perso_11.hex`. These are
the loadable images (the app above the bootloader, 0x08003000 onward); the bootloader at 0x0000–0x3000 is part
of what was signed but is not distributed.

- **Device 2 (MCU 1.0) is the `nanosr1` release.** Over the app region 0x3000–0x7ff8 — all the code **and the
  signature** — the two are byte-for-byte identical. The only difference is six fill bytes at 0x7ff8–0x7ffd,
  past the signature and outside the signed area, where the release hex has `46` ("FF") and the device has `ff`.
  Because an ECDSA signature is tied to one (key, message), identical signature bytes mean the device's full
  signed image (bootloader included) equals the release's, confirming the extraction against an official artifact.

- **The signed message and curve are confirmed.** Grafting device 2's bootloader (0x0000–0x3000) under the
  `nanosr11` app and recovering keys from both releases on secp256k1, over `SHA-256(flash[0:signed_len])` of
  the whole image, gives **one** shared key:

  ```
  04 90f5c9d15a0134bb019d2afd0bf297149738459706e7ac5be4abc350a1f81805
     7224fce12ec9a65de18ec34d6e8c24db927835ea1692b14c32e9836a75dad609
  ```

  This key is documented online as the **Ledger public key (root of trust)** (e.g. Rootstock's
  [pNetwork HSM attestation page](https://dev.rootstock.io/img/rsk/architecture/powpeg-hsm-attestation/pnetwork.html)),
  so the public releases are signed under Ledger's root of trust. Device 2's signature **verifies** under it;
  that it is also the common key of two different releases confirms the curve (secp256k1) and the message
  (SHA-256 of the full flash from 0 to the signed length).

- **Devices 1 and 6 use a different key.** The MCU 1.6 and MCU 1.12 signatures do **not** verify under the
  root-of-trust key, and they share no recovered key with each other. So these units are signed with other
  Ledger key(s), and MCU 1.6 and 1.12 use different keys again — consistent with a key change around
  the 1.4 rework of MCU authentication. The **1.12 key is now known**: the SESSION_START key id `f1308974`
  pins it to the second recovery candidate above (`04 d1152ea5…a086f1308974`), the same MCU-app key the
  Nano X uses. The **1.6 key** is still unresolved: its SESSION_START uses the older format (version string
  only, no key-id fields), so there is no id to compare against its two recovery candidates. Pinning it down
  needs two full-flash captures of the *same* MCU version, or Ledger publishing the key.

- There are no release images in that repository for MCU 1.6 or 1.12 (it stops at 1.1).

## Other MCU 1.6 images (jasonbhwong/Ledger)

A third-party repository, [jasonbhwong/Ledger](https://github.com/jasonbhwong/Ledger) (from the author of
[issue #1](https://github.com/LedgerHQ/nanos-nonsecure-firmware-releases/issues/1) on the releases repo), holds
loadable MCU images that the official releases repo does not:

| File | What it is |
|---|---|
| `mcu_1.6_over_0.8.hex` | MCU **1.6** app for bootloader 0.8, 71-byte signature at 0x7fb8 |
| `mcu_1.6-printf_over_bl_0.8.hex` | a **printf/debug** build of 1.6 (no version string), 70-byte signature |
| `blup_0.8_misc_m1.hex` | a bootloader-0.8 updater (self-contained app, SP marker `0xF00DBABE`) |

- **This 1.6 is a different build from device 1's 1.6.** Over the app region (0x3000–0x7f00), 14 288 of 20 224
  bytes differ, and the signatures differ. Both report version "1.6", so device 1 is a different point release
  or a build over a different bootloader (likely 1.6.1).
- **Their signing key could not be recovered.** These loadable files omit the bootloader (0x0000–0x3000) that is
  part of the signed message (confirmed above with the releases), and none of our captures use bootloader 0.8.
  `blup_0.8` embeds the bootloader, but inside a structured updater app rather than as a clean image, so it is
  not trivially extractable. Recovering the 1.6 key would need the exact bootloader-0.8 bytes, or a full-flash
  capture of a device running this build.

## Open questions

- Whether the SE refuses to start with a modified MCU image.
- The MCU signing key(s) for 1.6 and 1.12 (the root-of-trust key used for the 1.0/1.1 releases is known, above).
- Vector slots 2–10 (NMI, HardFault and the reserved ones) and 12–13 hold random-looking words instead of
  handler addresses, which the random fill of the gaps alone does not explain.
- Whether the random fill differs between devices (it is generated at build time, so probably not).
- Button masks: visgrok reports the first presses as "left (mask 0x02)"; check against which switch (S1 on PB7, S2 on PA15) was pressed.

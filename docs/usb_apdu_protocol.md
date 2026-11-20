# USB, APDUs and the secure channel (Nano S)

What the host says to the Nano S over USB: the HID transport, the dashboard (BOLOS) APDUs such as
`GET_VERSION`, the secure channel (SCP) used for genuine checks, app installs and firmware updates, and the
MCU bootloader's own APDU protocol. The SE↔MCU link underneath is covered in
[seproxyhal_protocol.md](seproxyhal_protocol.md).

Sources:

- **Captures** of the SE↔MCU link (see [seproxyhal_capture.md](seproxyhal_capture.md)). The MCU forwards
  every USB transfer to the SE as SEPROXYHAL packets, so the host's APDUs and the SE's answers are on that
  wire in full. Device 2 (`capture-nanos-20261114-174856.vgk`, SE 1.3.1 / MCU 1.0) has onboarding and four
  secure-channel handshakes; the examples below come from it.
- **[lsdk](https://github.com/KarpelesLab/lsdk)**, a host-side implementation that talks to these devices
  (`src/framing.rs`, `src/os.rs`, `src/scp.rs`, `src/attestation.rs`, `src/loader.rs`, `src/hsm/`).
- **The MCU bootloader source**: Ledger's
  [nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware) and its reconstruction of
  bootloader 0.11 (`build/stm32f042_nanos_bootloader/src/bootloader.c`).

## Layers

```
host ──USB HID (64-byte reports)──▶ MCU (STM32F042) ──SEPROXYHAL, ISO 7816 at 3 Mbaud──▶ SE (ST31)
       channel/tag/seq framing        forwards raw USB                USB_EP_XFER_EVENT / USB_EP_PREPARE
       APDUs: CLA INS P1 P2 Lc data                                    the SE runs the USB device stack
```

In normal operation the MCU doesn't understand USB traffic. It passes every endpoint transfer to the SE as a
`USB_EP_XFER_EVENT` (`0x10`) and sends whatever the SE queues with `USB_EP_PREPARE` (`0x50`). The SE runs
the whole USB device: enumeration, descriptors, HID reports, APDU reassembly. The MCU only answers the host
itself in **bootloader mode** (see [MCU bootloader](#mcu-bootloader-protocol)).

## USB device

The SE enables USB only once the PIN has been entered (`USB_CONFIG` connect; 15.29 s in capture 1, after
the dashboard comes up). Over SEPROXYHAL:

| Packet | Bytes | Meaning |
|---|---|---|
| `USB_EP_XFER_EVENT` | `10 LL LL ep dir len data…` | dir `01` SETUP, `02` IN done, `04` OUT data |
| `USB_EP_PREPARE` | `50 LL LL ep dir len data…` | dir `10` setup, `20` IN (send), `30` OUT (ready to receive), `40` stall, `80` unstall |
| `USB_CONFIG` | `4f LL LL type …` | `01` connect, `02` disconnect, `03` address, `04` endpoints (type `00` off, `01` ctrl, `02` interrupt, `03` bulk) |
| `USB_EVENT` | `0f 00 01 ev` | `01` reset, `02` SOF, `04` suspended, `08` resumed |

Descriptors as served by the SE:

- **Device:** USB 2.00, VID `2c97`, PID `0001`, one configuration. Strings: 1 "Ledger", 2 "Nano S",
  3 "0001", language `0409`.
- **Configuration, SE 1.3.1** (41 bytes, captured): one HID interface, two 64-byte interrupt endpoints, 1 ms:

  ```
  09 02 29 00 01 01 02 c0 32         config: 41 bytes, 1 interface, self-powered, 100 mA
  09 04 00 00 02 03 00 00 02         interface 0: HID, 2 endpoints
  09 21 11 01 00 01 22 22 00         HID 1.11, report descriptor 34 bytes
  07 05 82 03 40 00 01               EP 0x82 IN  interrupt 64 bytes, 1 ms
  07 05 02 03 40 00 01               EP 0x02 OUT interrupt 64 bytes, 1 ms
  ```

- **Configuration, SE 1.4+** (73 bytes, capture 1): two interfaces. The second is most likely the FIDO U2F
  HID interface that firmware 1.4 added; not decoded further.

## HID transport

Each APDU is split into 64-byte HID reports on EP 0x02 (host → device) and EP 0x82 (device → host), with
the same framing both ways (`lsdk/src/framing.rs`):

```
first report : channel(2) = 01 01 | tag(1) = 05 | seq(2) = 00 00 | length(2, BE) | data…
next reports : channel(2) = 01 01 | tag(1) = 05 | seq(2) = n     | data…
```

Reports are zero-padded to 64 bytes. `length` is the length of the whole APDU (or of the response, data +
SW). The first report carries 57 bytes of it, each following one 59.

A captured `GET_VERSION` (SE 1.3.1) as it crosses the SE↔MCU link:

```
MCU→SE USB_EP_XFER_EVENT  10 00 43 | 02 04 40 | 01 01 05 00 00 00 05 e0 01 00 00 00 00 …
                          tag len    ep2 OUT 64   chan  tag seq   len   APDU e0 01 00 00 00
SE→MCU USB_EP_PREPARE     50 00 03 | 02 30 40                       (ep2 ready to receive 64)
SE→MCU USB_EP_PREPARE     50 00 43 | 82 20 40 | 01 01 05 00 00 00 16 31 10 00 02 05 31 2e 33 2e 31
                                     ep 0x82 IN   04 87 00 00 00 04 31 2e 30 00 90 00 00 …
```

## APDUs

Commands are short ISO 7816-4 APDUs: `CLA INS P1 P2 Lc data`, 255 data bytes at most. A command with no
data still sends `Lc = 00`. Responses are `data SW1 SW2`.

Status words you'll see:

| SW | Meaning |
|---|---|
| `9000` | OK |
| `6985` | Conditions not satisfied; also what the user's "reject" on the device returns |
| `5501` | Refused by the user (newer firmware) |
| `5515` | Device locked (PIN not entered) |
| `6700` | Wrong length |
| `6802` | Secure command couldn't be unwrapped (seen on 1.3.1, see below) |
| `6804` | Vendor certificate refused (a custom CA is installed) |
| `6982` | Security status not satisfied |
| `6a80` / `6a84` | Incorrect data / not enough memory |
| `6d00` / `6e00` | INS / CLA not supported. `6e00` on `B0 01` means the dashboard is old (no `B0` class) |
| `6d06`, `6d07` | Device not onboarded |
| `6615`, `6616` | Secure command refused (not on the dashboard, locked, …) |

### Dashboard commands (CLA `E0`)

They are answered by the dashboard (BOLOS UX). An open app answers its own APDUs instead.

| APDU | Name | Data → response |
|---|---|---|
| `E0 01 00 00` | **GET_VERSION** | → version record, [below](#get_version) |
| `E0 02 00 00` | RESET | |
| `E0 04 P1 00` | **VALIDATE_TARGET_ID** | target id (4, BE). First step of the secure channel. P1 `00` normal, `02` Recover channel |
| `E0 50 00 00` | **INITIALIZE_AUTHENTICATION** | host nonce (8) → signer serial (4) ‖ device nonce (8) |
| `E0 51 P1 P2` | **VALIDATE_CERTIFICATE** | host certificate. P1 `00` chain cert, `80` last one (host ephemeral key) |
| `E0 52 P1 00` | **GET_CERTIFICATE** | P1 `00` device certificate, `80` device ephemeral key |
| `E0 53 00 00` | **MUTUAL_AUTHENTICATE** | opens the secure channel |
| `E0 00 00 00` | **SECUINS** | a wrapped secure command, [below](#secure-commands) |
| `E0 D0 id 00` | ONBOARD | `LV(pin) LV(prefix) LV(passphrase) LV(words)`. P1 `00` main, `01` alternate, `02` temporary identity |
| `E0 D2` / `E0 D4` | GET / SET_DEVICE_NAME | name (newer firmware) |
| `E0 D8 00 00` | OPEN_APP | app name (ASCII) |
| `E0 DE` / `E0 DF` | LIST_APPS / continue | → pages of installed apps. The user must allow it |
| `E0 C0`, `C2`, `C6` | ENDORSE_SET_START / _COMMIT / ENDORSEMENT_INFO | user attestation keys (slots 1, 2) |
| `E0 40`, `41`, `44`, `C4`, `C5` | factory: GET_DEVICE_PUBLIC_KEY, SET_CERTIFICATE, FACTORY_TEST, SET/GET_CXPORT | refused once personalised |
| `E0 D6` | SET_SCREEN_SAVER | recovery mode, newer models |
| `E0 10`, `19`, `30`–`34`, `D5` | battery, language packs, BLE MAC | not on the Nano S |

Class `B0` works in any app as well as on the dashboard, but not on 1.3.1:

| APDU | Name | Response |
|---|---|---|
| `B0 01 00 00` | GET_APP_AND_VERSION | `01 LV(name) LV(version) [LV(flags)]`. The dashboard calls itself `BOLOS` |
| `B0 A7 00 00` | QUIT_APP | back to the dashboard |

### GET_VERSION

The response is length-prefixed fields after a 4-byte target id. Which fields come back depends on the
version (`lsdk/src/os.rs`):

```
target_id(4) LV(se_version) LV(se_flags) LV(mcu_version) [LV(mcu_bootloader_version)] …
```

Seen on the Nano S:

| SE | Response |
|---|---|
| 1.3.1 (captured) | `31100002 05"1.3.1" 04 87000000 04"1.0\0"` (20 bytes) |
| 1.6.0 (captured) | `31100004 05"1.6.0" 04 23000000 04"1.12"` (20 bytes) |
| 2.1.0 (captured) | as 1.6.0 plus `04"0.11"`, the MCU bootloader version (25 bytes) |
| MCU bootloader | `01000001 LV(bl_version) 04 f4d8aa43 [SE ATR historical bytes]` ([bootloader](#mcu-bootloader-protocol)) |

- **Target id.** `0x3110000x` is the Nano S SE; `0x31100002` is firmware before 1.4 and `0x31100004` 1.4 on.
  The low nibble picks the secure-channel and app-install variants below (`is_pre_1_4`: `target & 0xf ==
  2`). A target id without `0x3` in the top nibble means the MCU bootloader is answering (`0x01000001`).
- **Version.** A `-osu` suffix means the OS updater is running, mid firmware update.
- **MCU version.** This is what the MCU sent in its `SESSION_START_EVENT` (NUL-terminated on 1.0). The
  bootloader version field was added in SE 2.0.
- **SE flags**, byte 0 (byte 1 and on only on newer firmware):

  | Bit | Meaning | | Bit | Meaning |
  |---|---|---|---|---|
  | `0x80` | PIN validated | | `0x08` | secure channel already allowed since boot |
  | `0x40` | MCU serial number | | `0x04` | onboarded |
  | `0x20` | valid device certificate | | `0x02` | MCU code signed |
  | `0x10` | custom CA allowed | | `0x01` | recovery mode |

  Byte 1 holds the endorsement slots (`01`, `02`). Byte 2: bits 6–5 are the seed length (24/18/12 words),
  bits 4–0 the word being entered. Byte 3: the onboarding step. Captured: `87` (device 2, recovery mode,
  onboarded, PIN entered, signed MCU) and `23` (1.6.0: certificate, signed MCU, recovery mode).

### ONBOARD sends the seed in the clear

`E0 D0` carries the PIN and the recovery phrase as plain length-prefixed ASCII. In capture 2 the host
onboards a device in recovery mode (`04 "1111" 00 00 bb "abandon abandon …"`, 195 bytes). Like all USB
data, it goes through the MCU unencrypted. Only for test devices.

## Secure channel (SCP)

The dashboard only accepts privileged operations (installing or deleting apps, listing them without asking,
custom CA, firmware update) over an authenticated, encrypted channel. Ledger's HSM opens it for the genuine
check, app installs and firmware updates. Any host can open one with its own key: the device then asks the
user to allow an "unknown manager" and shows the host key.

### Handshake

All keys are secp256k1. Signatures are DER ECDSA over SHA-256 of the message shown. Certificates are
`LV(public key, 65 bytes uncompressed) LV(signature)`.

| # | Host → device | Device → host |
|---|---|---|
| 1 | `E0 04 00 00` target id | `9000` |
| 2 | `E0 50 00 00` host nonce Nh (8) | signer serial (4) ‖ device nonce Nd (8) |
| 3 | `E0 51 00 00` host root certificate: `pub_root`, signed over `01 ‖ pub_root` (self-signed, or by a CA). **The device asks the user here.** | `9000`, or `6985` if refused |
| 4 | `E0 51 80 00` host ephemeral certificate: `pub_eh`, signed by the root over `11 ‖ Nh ‖ Nd ‖ pub_eh` | `9000` |
| 5 | `E0 52 00 00` | device certificate `LV(header) LV(pub_dev) LV(sig)`, signed by the issuer over `02 ‖ header ‖ pub_dev` |
| 6 | `E0 52 80 00` | device ephemeral `LV(empty) LV(pub_ed) LV(sig)`, signed by `pub_dev` over `12 ‖ Nd ‖ Nh ‖ pub_ed` |
| 7 | `E0 53 00 00` | `9000`: channel open |

The first byte of each signed message is a role: `01`/`11` for host root and ephemeral, `02`/`12` for the
device's. A Recover orchestrator certified by a custom CA uses `05`/`15` with `P2 = 01`. The Recover channel
exists on newer models; it hasn't been checked on the Nano S.

Step 6 is the proof of possession: the device signs the host's fresh nonce with its certified key. That's
all the **genuine check** needs. lsdk's offline check runs steps 1–6 with a throwaway host key and checks
step 5 against a pinned issuer key. It doesn't need step 7.

**The issuer is Ledger's root of trust.** Device 2's certificate (header `20a8e048b4007d`, 70-byte
signature) verifies under

```
04 90f5c9d15a0134bb019d2afd0bf297149738459706e7ac5be4abc350a1f81805
   7224fce12ec9a65de18ec34d6e8c24db927835ea1692b14c32e9836a75dad609
```

That's the same key that signs MCU 1.0/1.1 ([mcu_firmware/](../mcu_firmware/README.md)). It's also the
issuer key in Ledger's `checkGenuine.py`. So one key certifies both the SE's identity and the early MCU
images. The signer serial returned in step 2 was `00000002`.

Captured on device 2 (SE 1.3.1), the handshake timing shows where the user is involved:

```
135.196  E0 50  nonce d25f63958df45d97           → 00000002 5ce57007a2ceb0e8      (77 ms)
135.277  E0 51 00  root cert, 138 bytes          → 9000 at 139.003  ← user allowed it (3.7 s)
139.015  E0 51 80  ephemeral cert                → 9000                          (145 ms)
139.162  E0 52 00                                → device certificate, 145 bytes   (1 ms)
139.168  E0 52 80                                → device ephemeral, 138 bytes    (84 ms: signing)
139.256  E0 53                                   → 9000                          (79 ms: ECDH)
139.337  E0 00  secure command, 94 bytes         → 6802
```

In a later attempt the user refused at step 3 (`6985` after 1.65 s).

### Session keys and wrapping

Let `S = SHA-256(compressed(ECDH(eh, pub_ed)))`.

- **Firmware 1.4 and later (target id ending in 4):** two AES-128 keys come out of `S`. For index `i` (0
  encryption, 1 MAC): `d_i = SHA-256(be32(i) ‖ retry ‖ S)`, retrying until it is a valid scalar, then
  `k_i = SHA-256(uncompressed(d_i·G))[0:16]`. A secure command is
  `E0 00 00 00 Lc ‖ AES-CBC(k0, pad(ins ‖ data)) ‖ CBC-MAC(k1, ciphertext)[last 14 bytes]`, where pad is
  ISO 7816-4 (`80 00…`). Responses are wrapped the same way. The encryption IV and the MAC IV both start at
  zero and **chain across the whole session**, in both directions. One lost message breaks the channel.
- **Before 1.4 (target id ending in 2, e.g. SE 1.3.1):** the key is `S[0:16]`. It's AES-128-CBC with the
  same padding, one IV chain shared by both directions, and **no MAC**.
- **Recover channel (newer firmware):** AES-SIV with a key from `SHA-256(x ‖ 00000001)`.

The captured 94-byte secure command on 1.3.1 is 5·16 + 14: a 1.4-style ciphertext with a MAC. The 1.3.1
dashboard rejected it with `6802`, as you'd expect from a host using the 1.4+ wrapping on a pre-1.4
device. The plaintext is at most 239 bytes, so the wrapped APDU fits in 255.

### Secure commands

The first plaintext byte of a SECUINS is the secure instruction:

| Ins | Name | Payload |
|---|---|---|
| `05` | SET_LOAD_OFFSET | offset (4, BE), relative to the app base |
| `06` | LOAD | offset in the window (2, BE) ‖ data |
| `07` | FLUSH | write the page buffer to flash |
| `08` | CRC | `00 00` ‖ length (4) ‖ CRC-16/CCITT-FALSE (2) of the window |
| `09` | COMMIT ("boot") | 1.4+: `[LV(CA signature of the app hash)]`; pre-1.4: entry offset (4) `[LV(sig)]` |
| `0b` | CREATE_APP | app header, see below |
| `0c` | DELETE_APP | `LV(name)` |
| `0e` / `0f` | LIST_APPS / continue | → entries (no user prompt) |
| `10` | GET_VERSION | → as the plain GET_VERSION |
| `11` | GET_MEMORY_INFORMATION | → system, apps and free bytes, used and total app slots (5 × u32) |
| `12` / `13` | SETUP / RESET_CUSTOM_CERTIFICATE | `LV(name) LV(pubkey)`: custom CA, recovery mode, the user confirms |
| `14` | DELETE_ALL_APPS | |
| `15` | DELETE_APP_BY_HASH | hash (32) |
| `16` | RESET_ENDORSEMENT | |
| `17` | HASH_FIRMWARE | address (4) ‖ length (4) ‖ zero padding to 24. Vendor HSM only |
| `b0` | MCU_BOOTLOADER | reboot the MCU into its bootloader (firmware update) |
| `d2` / `d3` | RECOVER_SET_CA / _DELETE_CA | Recover channel only |

**Installing an app** (`lsdk/src/loader.rs`): `CREATE_APP`, then for each 64 KiB window `SET_LOAD_OFFSET`,
`LOAD` chunks, `FLUSH`, `CRC`, and finally `COMMIT`. The `CREATE_APP` header changed at 1.4:

- **1.4+:** `[api_level(1)] code_len(4) data_len(4) install_params_len(4) flags(4) entry_offset|1 (4)`. Name,
  version and icon are TLVs in the install-parameters block at the end of the image (tags 1, 2, 3; tag 4 is
  the derivation path restriction). The app hash the device reports is
  `SHA-256(target_id ‖ CREATE_APP params ‖ image)`.
- **Before 1.4:** `length(4) flags(4) LV(name) LV(icon) 01 ff` (`ff` means any curve and any path). The hash
  is `SHA-256(image)`.

Only a channel opened with the vendor HSM key or with the custom CA's private key may install apps.
Opened with any other key, the channel still works for listing, deleting and reading, but installs are
refused.

## The HSM relay

Ledger's HSM is called "scriptrunner": `wss://scriptrunner.api.live.ledger.com/update/<op>?targetId=…&perso=…`
(ops: `genuine`, `install` (also used for uninstalls and firmware), `apps/list`, `endorse`, `mcu`). It holds the vendor manager key and runs the whole session. The host
only relays APDUs (`lsdk/src/hsm/mod.rs`):

```
HSM → host  {"query":"exchange","nonce":n,"data":"<apdu hex>"}
host → HSM  {"nonce":n,"response":"success"|"error","data":"<response hex, no SW>"}
HSM → host  {"query":"bulk","data":["<apdu>",…]}    socket closes, host sends them all
HSM → host  {"query":"success","result":…} | {"query":"error","data":…} | {"query":"warning",…}
```

Everything the HSM sends after `MUTUAL_AUTHENTICATE` is wrapped secure commands. The host can't read them,
and the MCU and the SEPROXYHAL wire see the same ciphertext. The bulk phase carries the bulk of an install
or a firmware update, as a precomputed APDU list.

Capture 3 (`capture-nanos-20261114-180148.vgk`) is a firmware update to SE 1.6.0 / MCU 1.12. It has two such
sessions, 292 and then 604 commands. A Nano S firmware update goes:

1. **OS updater (OSU):** an HSM `install` session loads the `…-osu` firmware. The device asks the user,
   then reboots into the OSU (`GET_VERSION` shows `x.y.z-osu`).
2. **MCU, if the new SE needs a different MCU version:** the device comes back in MCU bootloader mode
   (`GET_VERSION` target `0x01000001`). The secure instruction `b0` is the documented way in; how the MCU is
   actually switched over on the wire hasn't been identified, and SEPROXYHAL `0x31` is disabled as a
   bootloader entry. An HSM `mcu` session then flashes the MCU app in plaintext
   ([below](#mcu-bootloader-protocol)), or from very old bootloaders a newer bootloader first. Repeat while
   the device still reports bootloader mode. Each step reboots.
3. **Final firmware:** on the Nano S the final SE firmware is a separate image. With the OSU running, a
   second `install` session loads it.

## MCU bootloader protocol

In bootloader mode the MCU (bootloader `0x01000001`) answers APDUs itself. From the reconstructed 0.11
source, with CLA `E0`:

| APDU | Name | Notes |
|---|---|---|
| `E0 01 00 00` | GET_VERSION | → `01000001 LV("0.11") 04 f4d8aa43` + the SE's ATR historical bytes |
| `E0 02 00 00` | RESET | leave the bootloader |
| `E0 04 00 00` | VALIDATE_TARGET_ID | must be `01000001` (else `6a84`). Unlocks SECUINS |
| `E0 00 00 00` | SECUINS | **plaintext**, first data byte = instruction: |
| | `05` SELECT_SEGMENT | address (4, BE) |
| | `06` LOAD | offset (2) ‖ data, app area only (`6984` otherwise) |
| | `07` FLUSH | |
| | `09` BOOT | entry (4, ignored). Checks the **RSA-2048** signature (PKCS#1 v1.5, SHA-256, e = 65537) over the app, `6982` if it doesn't verify, then writes the boot magic and starts the app |

Any error resets the state to "target id not validated" (`STATE_ID`). There's no secure channel: what
protects the MCU is the RSA signature at 0x7eb8–0x7fb7, checked by the bootloader, plus the SE's own ECDSA
check of the whole flash at every boot ([seproxyhal_capture.md](seproxyhal_capture.md)). `f4d8aa43` is the
bootloader key id, the same value the MCU puts in its `SESSION_START_EVENT`.

The bootloader takes commands **from two places**:

- **USB:** the same HID framing as above, served by the bootloader's own USB stack.
- **The SE:** at start the bootloader power-cycles the SE. If the ATR is `3B 1x 87 …` (TA1 only, TA1 =
  `0x87`), the SE wants to drive the update itself. The bootloader sends a `SESSION_START_EVENT` with feature
  `0x20000000` (MCU bootloader), version "0.11" and key id `f4d8aa43`. It then takes APDUs wrapped in
  SEPROXYHAL `BOOTLOADER_CAPDU` (`0x6a`) and answers in `BOOTLOADER_RAPDU_EVENT` (`0x19`). The normal SE ATR
  is `3B 90 98 10 00` (TA1 = `0x98`), so this path is never taken in normal boots.

Older bootloaders differ in the details. 0.7 answers GET_VERSION with `01000001 03"0.7" 08 …` and declares 8
flag bytes but sends 3. Old bootloaders only report their own version, not the installed SE firmware, so
the next MCU version has to come from a per-bootloader table (0.6 → MCU 1.5, 0.7 → 1.6, 0.9 → 1.7).

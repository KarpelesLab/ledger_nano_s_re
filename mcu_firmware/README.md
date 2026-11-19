# Nano S MCU firmware images

The non-secure STM32F042 ("MCU") firmware of the Ledger Nano S. These are included **for interoperability** —
anything that stands in for the MCU (an emulator, a test rig, a re-flash) must present the exact bytes the SE
expects. They contain no device secrets: the MCU firmware is the same for every device of a given version and
holds no PIN, seed or per-device key.

They are **Ledger's firmware**, © Ledger, distributed by Ledger under the Apache License 2.0 (source:
[LedgerHQ/nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware)). Ledger itself
publishes some versions as Intel hex in
[LedgerHQ/nanos-nonsecure-firmware-releases](https://github.com/LedgerHQ/nanos-nonsecure-firmware-releases).

Two kinds of artifact live here:

- **Full-flash images** — complete 32 KB flash (0x08000000–0x08007fff), reconstructed from the SE↔MCU
  flash-read exchange in logic-analyzer captures. These are the bytes the SE reads and verifies at every boot;
  their signatures have been checked (see below).
- **Loadables** — the firmware as carried in Ledger's loadable/update container (`F00DBABE`-marked), dumped
  directly. The container→flash mapping and the signatures of these are **not yet worked out** (see
  [Loadables](#loadables-as-dumped)).

## Full-flash images (verified)

| File | Version | Signed length | Signature | Signing key | SHA-256 |
|---|---|---|---|---|---|
| `mcu_nanos_1.0.bin` | MCU 1.0 | 0x7fb0 | 70-byte DER | **Ledger root of trust** | `f8d944ec…fed3624` |
| `mcu_nanos_1.1.bin` | MCU 1.1 | 0x7fb0 | 71-byte DER | **Ledger root of trust** | `f0a372c5…1af3207` |
| `mcu_nanos_1.6.bin` | MCU 1.6 | 0x7fb8 | 70-byte DER | other Ledger key (unknown) | `2fa78beb…a479e46` |
| `mcu_nanos_1.12.bin` | MCU 1.12 | 0x7fb8 | 71-byte DER | Ledger MCU-app key, id `f1308974` (= Nano X) | `6da013f8…f68bd8f` |

Layout of each full image: `vector table | bootloader | gap (random fill) | seproxyhal app | ECDSA signature`.
The flash from 0 to the signed length is covered by a secp256k1 ECDSA signature (over its SHA-256), stored in
DER immediately after, then `0xff` fill to the end. See
[../docs/seproxyhal_capture.md](../docs/seproxyhal_capture.md) for the signature analysis and
[../docs/seproxyhal_protocol.md](../docs/seproxyhal_protocol.md) for the protocol.

## Loadables (as dumped)

Dumped from Ledger's loadable/update container, not reconstructed from a flash read. **These are raw captures;
their exact structure and signatures are still being worked out — do not treat the fields below as verified.**

| File | Version | Bytes | Container | Trailing DER sig | SHA-256 |
|---|---|---|---|---|---|
| `bootloader_nanos_0.6.bin` | MCU bootloader 0.6 | 20480 | `F00DBABE` | 71-byte @0x4fb8 | `f09210ab…19f4c9c` |
| `bootloader_nanos_0.7.bin` | MCU bootloader 0.7 | 20478 | `F00DBABE` | 70-byte @0x4fb8 | `1474a129…0762652` |
| `bootloader_nanos_0.9.bin` | MCU bootloader 0.9 | 20479 | `F00DBABE` | 71-byte @0x4fb8 | `aff46d35…a90e65d` |
| `bootloader_nanos_0.11.bin` | MCU bootloader 0.11 | 20478 | other (no `F00DBABE`) | 70-byte @0x4fb8 | `6e73b5d3…dee44a6` |
| `mcu_nanos_1.4.bin` | MCU app 1.4 | 20478 | `F00DBABE` | 70-byte @0x4fb8 | `64472082…378b4d6` |
| `mcu_nanos_1.5.bin` | MCU app 1.5 | 20479 | `F00DBABE` | 71-byte @0x4fb8 | `60203767…24bfa20` |
| `mcu_nanos_1.7.bin` | MCU app 1.7 | 20478 | `F00DBABE` | 70-byte @0x4fb8 | `f09937f9…fa315b0` |
| `mcu_nanos_1.11.bin` | MCU app 1.11 | 18431 | other (no `F00DBABE`) | 71-byte @0x47b8 | `088d62c4…f1817d4` |

What is known about the container so far:

- The `F00DBABE` loadables begin with the marker in the **first word** (where live flash holds the stack
  pointer), the intact reset vector at +4, then a **fixed ~52-byte header block that is byte-for-byte identical
  across every version** (e.g. the 0.6 bootloader and the 1.7 app share it) — so it is a container header, not
  firmware code. Each contains its version string, and ends with a DER secp256k1 signature.
- The `.11` pair (`bootloader_nanos_0.11.bin`, `mcu_nanos_1.11.bin`) uses a **different container** with no
  `F00DBABE` marker (and 1.11 is shorter, sig at 0x47b8) — a later loadable format.
- They do correspond to real flash: the fixed header block appears inside the verified full `mcu_nanos_1.12.bin`
  at flash **0x3808**. But the mapping is not the naive "app at 0x3000": grafting the known bootloaders under
  that assumption does **not** reproduce a signature that verifies or a key shared across versions. So the
  container layout must be decoded before these signatures can be checked or their keys recovered.

## Provenance

Each full-flash image was reconstructed from the SE↔MCU flash-read exchange in a logic-analyzer capture (see the
capture notes), not dumped from the chip. `tools/mcu_flash_from_seph.py` rebuilds them from a `visgrok` log;
every byte is covered with no conflicting reads.

- **`mcu_nanos_1.0.bin`** is **byte-for-byte identical to Ledger's public `nanosr1` release** (over the
  distributed region, including the signature; only 6 fill bytes past the signature differ). Its signature
  verifies under Ledger's documented root-of-trust key
  `0490f5c9d15a0134bb019d2afd0bf297149738459706e7ac5be4abc350a1f818057224fce12ec9a65de18ec34d6e8c24db927835ea1692b14c32e9836a75dad609`.
  This match confirms the extraction method against an official artifact.
- **`mcu_nanos_1.1.bin`** is **byte-for-byte identical to Ledger's public `nanosr11` release** over the app
  and signature (0x3000–0x7ff7; only the 7 fill bytes at 0x7ff8–0x7ffe differ, past the signature). Its
  signature (71-byte DER at 0x7fb0) **verifies under the same root-of-trust key** over `SHA-256(flash[0:0x7fb0])`.
  Its bootloader region (0x2d0–0x3000) is byte-for-byte identical to `mcu_nanos_1.0.bin`, so 1.0 and 1.1 ship
  the same bootloader. One caveat: the capture lost the first 0x2d0 bytes (they fell in the mangled
  SESSION_START window), so bytes 0x0–0x2d0 here are carried over from the identical 1.0 bootloader; everything
  from 0x2d0 on is captured, and all three boots in the capture agree over it byte-for-byte.
- **`mcu_nanos_1.6.bin`** and **`mcu_nanos_1.12.bin`** are from production units (SE 1.6.0 for 1.12). Ledger has
  not published release images for these versions. Note `mcu_nanos_1.6.bin` is a *different build* from the
  `mcu_1.6_over_0.8.hex` floating around (different bootloader, different signature).
- **`mcu_nanos_1.12.bin`'s signing key is identified:** its SESSION_START reports the MCU-app key id
  `f1308974`, which is the last 4 bytes of the second key recovered from its signature
  (`04 d1152ea5…a086f1308974`) — the same MCU-app key the Ledger Nano X uses. See
  [../docs/seproxyhal_capture.md](../docs/seproxyhal_capture.md).
- **The loadables** (bootloaders 0.6/0.7/0.9/0.11 and apps 1.4/1.5/1.7/1.11) were dumped directly from Ledger's
  loadable container, not reconstructed from a flash read. Their container format is only partly understood (see
  above); their signatures have not been verified and their signing keys are not yet established.

`SHA256SUMS` lists the hashes; `sha256sum -c SHA256SUMS` checks them.

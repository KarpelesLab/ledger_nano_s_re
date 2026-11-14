# Nano S MCU firmware images

The non-secure STM32F042 ("MCU") firmware of the Ledger Nano S, as a full 32 KB flash image
(0x08000000–0x08007fff). These are the images the secure element reads and verifies over the SEPROXYHAL link
at every boot; they are included here **for interoperability** — anything that stands in for the MCU (an
emulator, a test rig, a re-flash) must present the exact bytes the SE expects. They contain no device secrets:
the MCU firmware is the same for every device of a given version and holds no PIN, seed or per-device key.

These are **Ledger's firmware**, © Ledger, distributed by Ledger under the Apache License 2.0 (source:
[LedgerHQ/nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware)). Ledger itself
publishes some of these images as Intel hex in
[LedgerHQ/nanos-nonsecure-firmware-releases](https://github.com/LedgerHQ/nanos-nonsecure-firmware-releases).

## Images

| File | Version | Signed length | Signature | Signing key | SHA-256 |
|---|---|---|---|---|---|
| `mcu_nanos_1.0.bin` | MCU 1.0 | 0x7fb0 | 70-byte DER | **Ledger root of trust** | `f8d944ec…fed3624` |
| `mcu_nanos_1.6.bin` | MCU 1.6 | 0x7fb8 | 70-byte DER | other Ledger key (unknown) | `2fa78beb…a479e46` |
| `mcu_nanos_1.12.bin` | MCU 1.12 | 0x7fb8 | 71-byte DER | other Ledger key (unknown) | `6da013f8…f68bd8f` |

Layout of each image: `vector table | bootloader | gap (random fill) | seproxyhal app | ECDSA signature`.
The flash from 0 to the signed length is covered by a secp256k1 ECDSA signature (over its SHA-256), stored in
DER immediately after, then `0xff` fill to the end. See
[../docs/seproxyhal_capture.md](../docs/seproxyhal_capture.md) for the signature analysis and
[../docs/seproxyhal_protocol.md](../docs/seproxyhal_protocol.md) for the protocol.

## Provenance

Each image was reconstructed from the SE↔MCU flash-read exchange in a logic-analyzer capture (see the capture
notes), not dumped from the chip. `tools/mcu_flash_from_seph.py` rebuilds them from a `visgrok` log; every byte
is covered with no conflicting reads.

- **`mcu_nanos_1.0.bin`** is **byte-for-byte identical to Ledger's public `nanosr1` release** (over the
  distributed region, including the signature; only 6 fill bytes past the signature differ). Its signature
  verifies under Ledger's documented root-of-trust key
  `0490f5c9d15a0134bb019d2afd0bf297149738459706e7ac5be4abc350a1f818057224fce12ec9a65de18ec34d6e8c24db927835ea1692b14c32e9836a75dad609`.
  This match confirms the extraction method against an official artifact.
- **`mcu_nanos_1.6.bin`** and **`mcu_nanos_1.12.bin`** are from production units (SE 1.6.0 for 1.12). Ledger has
  not published release images for these versions. Note `mcu_nanos_1.6.bin` is a *different build* from the
  `mcu_1.6_over_0.8.hex` floating around (different bootloader, different signature).

`SHA256SUMS` lists the hashes; `sha256sum -c SHA256SUMS` checks them.

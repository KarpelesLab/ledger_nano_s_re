# Nano S MCU firmware images

The non-secure STM32F042 ("MCU") firmware of the Ledger Nano S. These are included **for interoperability** —
anything that stands in for the MCU (an emulator, a test rig, a re-flash) must present the exact bytes the SE
expects. They contain no device secrets: the MCU firmware is the same for every device of a given version and
holds no PIN, seed or per-device key.

They are **Ledger's firmware**, © Ledger, distributed by Ledger under the Apache License 2.0 (source:
[LedgerHQ/nanos-nonsecure-firmware](https://github.com/LedgerHQ/nanos-nonsecure-firmware)). Ledger itself
publishes some versions as Intel hex in
[LedgerHQ/nanos-nonsecure-firmware-releases](https://github.com/LedgerHQ/nanos-nonsecure-firmware-releases).

- **`mcu_nanos_*.bin`** — complete 32 KB flash images (0x08000000–0x08007fff). The bytes the SE reads and
  verifies at every boot. **Every one's signature has been verified** (see below).
- **`bootloader_nanos_*.bin`** — MCU bootloaders in Ledger's loadable/update container, as dumped. The
  container format is decoded below; the installed bootloader bytes they carry are what sit at the bottom of
  the matching full images.

## Full-flash images

Each image is `bootloader | app (seproxyhal) | ECDSA signature | 0xff fill`. The flash from 0 to the signed
length is covered by a **secp256k1** ECDSA signature over its SHA-256, DER-encoded immediately after. All
signatures below verify; the signing key moved twice over the version history (root of trust → key A → key B).

| File | Version | Bootloader | Signed length | DER sig | Signing key | SHA-256 |
|---|---|---|---|---|---|---|
| `mcu_nanos_1.0.bin` | 1.0 | (pre-0.6) | 0x7fb0 | 70 B | **root of trust** | `f8d944ec…fed3624` |
| `mcu_nanos_1.1.bin` | 1.1 | (pre-0.6, = 1.0's) | 0x7fb0 | 71 B | **root of trust** | `f0a372c5…1af3207` |
| `mcu_nanos_1.4.bin` | 1.4 | 0.6 | 0x7fb8 | 70 B | **key A** (`04317fa6…`) | `e2791308…0dfa49b7` |
| `mcu_nanos_1.5.bin` | 1.5 | 0.6 | 0x7fb8 | 71 B | **key A** (`04317fa6…`) | `946fd5e6…3c1831b7` |
| `mcu_nanos_1.6.bin` | 1.6 | 0.7 | 0x7fb8 | 70 B | **key A** (`04317fa6…`) | `2fa78beb…a479e46` |
| `mcu_nanos_1.7.bin` | 1.7 | 0.9 | 0x7fb8 | 70 B | **key B** (`f1308974`) | `f8718165…b8cc99fb` |
| `mcu_nanos_1.11.bin` | 1.11 | 0.11 | 0x7fb8 | 71 B | **key B** (`f1308974`) | `e1293c78…87f6ea50` |
| `mcu_nanos_1.12.bin` | 1.12 | 0.11 | 0x7fb8 | 71 B | **key B** (`f1308974`) | `6da013f8…f68bd8f` |

The three signing keys (secp256k1 public keys, uncompressed):

- **Root of trust** — `04 90f5c9d1…a75dad609`. Ledger's documented
  [root-of-trust key](../docs/seproxyhal_capture.md); signs the public 1.0/1.1 releases.
- **Key A** — `04 317fa61affbb9d93754c03234d9aa594ee7794c30228240fc3be96c70d0c433 8121de3b01f8f83b4ac616180a78928332d6cbf7bae7b56799c59c92be158dd84`. Signs MCU 1.4, 1.5, 1.6.
- **Key B** — `04 d1152ea5fa739fd71d4812d65dfa6fbf9ac31321f368839d42d2209606493d12 822bd3b885bf7058d19a34c51381335e6150d998312a3b35fd37a086f1308974`, id (last 4 bytes) **`f1308974`**. Signs
  MCU 1.7, 1.11, 1.12 — the same MCU-app key the **Ledger Nano X** uses.

The bootloader occupies **flash 0x0–0x3000** up to bootloader 0.9, then **0x0–0x3800** from 0.11 on (it grew
0x800; the app start moves with it). 1.0 and 1.1 share one (older) bootloader; 1.4/1.5 use 0.6, 1.6 uses 0.7,
1.7 uses 0.9, and 1.11/1.12 use 0.11.

## Bootloader loadables

`bootloader_nanos_{0.6,0.7,0.9,0.11}.bin` are Ledger's loadable/update containers for the MCU bootloader,
dumped directly. They are **not** flat flash images; the installed bootloader bytes are a slice inside them:

| File | Container | Header | Installed bootloader = bytes | = region in full image |
|---|---|---|---|---|
| `bootloader_nanos_0.6.bin` | `F00DBABE` | 0xa38 | `[0xa38 : 0xa38+0x3000]` | flash 0x0–0x3000 |
| `bootloader_nanos_0.7.bin` | `F00DBABE` | 0xa38 | `[0xa38 : 0xa38+0x3000]` | **= `mcu_nanos_1.6.bin[0:0x3000]`** |
| `bootloader_nanos_0.9.bin` | `F00DBABE` | 0xa38 | `[0xa38 : 0xa38+0x3000]` | flash 0x0–0x3000 |
| `bootloader_nanos_0.11.bin` | other | 0xe3c | `[0xe3c : 0xe3c+0x3800]` | **= `mcu_nanos_1.12.bin[0:0x3800]`** |

See [the capture notes](../docs/seproxyhal_capture.md#loadable-container-format) for how the container was
decoded and how the full images above were reconstructed and verified from these bootloaders plus the app
loadables.

## Provenance

`mcu_nanos_1.0/1.1/1.6/1.12.bin` were reconstructed from the SE↔MCU flash-read exchange in logic-analyzer
captures (see the capture notes); `tools/mcu_flash_from_seph.py` rebuilds them from a `visgrok` log.
`mcu_nanos_1.4/1.5/1.7/1.11.bin` were reconstructed from dumped loadables (the app loadable placed at the app
base, under the matching bootloader loadable) and each **verified** by its signature.

- **`mcu_nanos_1.0.bin`** is byte-for-byte identical to Ledger's public `nanosr1` release; its signature
  verifies under the root-of-trust key. **`mcu_nanos_1.1.bin`** is identical to the `nanosr11` release and
  verifies under the same key. 1.0 and 1.1 share the same bootloader.
- **`mcu_nanos_1.4/1.5/1.6.bin`** verify under **key A** (`04317fa6…`). The 1.4 and 1.5 signatures recover key
  A with bootloader 0.6, and 1.6 with bootloader 0.7 (= the bootloader in its own full image) — a three-way
  agreement on the same key that also disambiguates 1.6's two recovery candidates. No public releases exist for
  these versions.
- **`mcu_nanos_1.7/1.11/1.12.bin`** verify under **key B** (`f1308974`). 1.12's key was already known from its
  SESSION_START (app key id `f1308974`); 1.7 and 1.11 recover the same key (with bootloaders 0.9 and 0.11),
  confirming the key change happened between 1.6 and 1.7. Key B is the MCU-app key the Nano X also uses.
- **`bootloader_nanos_0.7.bin`** and **`bootloader_nanos_0.11.bin`** are confirmed exact: their installed
  regions equal the bootloader of `mcu_nanos_1.6.bin` and `mcu_nanos_1.12.bin` respectively, byte-for-byte.

`SHA256SUMS` lists the hashes; `sha256sum -c SHA256SUMS` checks them.

#!/usr/bin/env python3
"""Rebuild the MCU flash image that the secure element reads over SEPROXYHAL at boot.

At every boot the Nano S SE reads the whole flash of the STM32F042 MCU with UNSEC_CHUNK_READ or
UNSEC_CHUNK_READ_EXT commands, and the MCU answers each one with an UNSEC_CHUNK_EVENT (tag 0x12) carrying
the bytes.
This collects those answers from a `visgrok log` of a capture and writes the image.

Usage:
    visgrok log capture.vgk --uart-proto seproxyhal -o capture.log
    python3 tools/mcu_flash_from_seph.py [--boot N] capture.log mcu_flash.bin

The image is the MCU firmware, which is Ledger's: keep it out of this repository (*.bin is ignored).

Two forms of the read command exist:

- UNSEC_CHUNK_READ (0x32, MCU 1.0, as in LedgerHQ/nanos-nonsecure-firmware): length (2 bytes, big endian)
  and a reset flag (1 byte). Reads are sequential from the start of flash; the answer to the read at offset 0
  starts with the length of the signed area (4 bytes, big endian), then the flash.
- UNSEC_CHUNK_READ_EXT (0x33, MCU 1.6): length (2 bytes), kind (1 byte), then for kind 2 a plain read at an
  offset (4 bytes, big endian). Kind 4 has no offset and returns the 4-byte length of the signed area.

The signed area is followed by a DER ECDSA signature. With several boots in one capture, the image of the
last one is written (--boot N picks another; boots are counted from SESSION_START or the first read).
"""
import re
import sys

HEAD = re.compile(r"\s+([\d.]+)\s+(SE→MCU|MCU→SE) ([A-Z_0-9]+)")
HEX = re.compile(r"^ {10,}(?:[0-9a-f]{4}: )?(?:[0-9a-f]{2} ?)+$")


def packets(path):
    """(time, direction, tag, bytes) for every message in a visgrok log."""
    lines = open(path, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(lines):
        m = HEAD.match(lines[i])
        i += 1
        if not m:
            continue
        hexdump = ""
        while i < len(lines) and HEX.match(lines[i]):
            hexdump += re.sub(r"^\s*[0-9a-f]{4}: ", "", lines[i]) + " "
            i += 1
        yield float(m.group(1)), m.group(2), m.group(3), bytes.fromhex("".join(hexdump.split()))


def images(path):
    """One (image, seen, signed_end, conflicts, reads) per boot: a read at offset 0 after data starts a new one."""
    size = 0x8000
    boots = []

    def new():
        boots.append({"image": bytearray(b"\xff" * size), "seen": bytearray(size), "signed_end": None,
                      "conflicts": 0, "reads": 0})
    request, seq = None, 0
    for _, _, tag, raw in packets(path):
        if tag in ("UNSEC_CHUNK_READ", "UNSEC_CHUNK_READ_EXT"):
            request = (tag, raw[3:])
            continue
        if tag != "UNSEC_CHUNK_EVENT" or not request:
            continue
        kind_tag, args = request
        request = None
        data = raw[3:]
        if kind_tag == "UNSEC_CHUNK_READ":
            if args[2]:
                seq = 0
            offset = seq
            if offset == 0:
                if not boots or boots[-1]["reads"]:
                    new()
                boots[-1]["signed_end"] = int.from_bytes(data[:4], "big")
                data = data[4:]
            seq += len(data)
        elif args[2] == 4:
            if not boots or boots[-1]["reads"]:
                new()
            boots[-1]["signed_end"] = int.from_bytes(data, "big")
            continue
        elif args[2] == 2:
            offset = int.from_bytes(args[3:7], "big")
        else:
            continue
        if not boots:
            new()
        b = boots[-1]
        for k, x in enumerate(data):
            if offset + k >= size:
                break
            if b["seen"][offset + k] and b["image"][offset + k] != x:
                b["conflicts"] += 1
            b["image"][offset + k], b["seen"][offset + k] = x, 1
        b["reads"] += 1
    return boots


def main():
    args = sys.argv[1:]
    pick = -1
    if "--boot" in args:
        i = args.index("--boot")
        pick = int(args[i + 1]) - 1
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    boots = images(args[0])
    if not boots:
        sys.exit("no MCU flash reads found")
    for n, b in enumerate(boots, 1):
        print("boot %d: %d reads, %d of %d bytes covered, %d conflicting bytes%s" % (
            n, b["reads"], sum(b["seen"]), len(b["seen"]), b["conflicts"],
            ", signed area ends at 0x%04x" % b["signed_end"] if b["signed_end"] is not None else ""))
    open(args[1], "wb").write(boots[pick]["image"])
    print("wrote boot %d to %s" % (pick + 1 if pick >= 0 else len(boots), args[1]))


if __name__ == "__main__":
    main()

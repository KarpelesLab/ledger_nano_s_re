#!/usr/bin/env python3
"""Rebuild the MCU flash image that the secure element reads over SEPROXYHAL at boot.

At every boot the Nano S SE reads the whole 32 KB flash of the STM32F042 MCU with UNSEC_CHUNK_READ_EXT
commands (tag 0x33), and the MCU answers each one with an UNSEC_CHUNK_EVENT (tag 0x12) carrying the bytes.
This collects those answers from a `visgrok log` of a capture and writes the image.

Usage:
    visgrok log capture.vgk --uart-proto seproxyhal -o capture.log
    python3 tools/mcu_flash_from_seph.py capture.log mcu_flash.bin

The image is the MCU firmware, which is Ledger's: keep it out of this repository (*.bin is ignored).

Request arguments (after the 3-byte tag and length): length (2 bytes, big endian), kind (1 byte),
offset (4 bytes, big endian) for kind 2, a plain read. Kind 4 has no offset and returns 4 bytes: the
end of the signed area (0x7fb8 on the captured device), where a DER ECDSA signature follows.
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


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    size = 0x8000
    image, seen = bytearray(b"\xff" * size), bytearray(size)
    request, signed_end, conflicts, reads = None, None, 0, 0
    for _, _, tag, raw in packets(sys.argv[1]):
        if tag == "UNSEC_CHUNK_READ_EXT":
            request = raw[3:]
        elif tag == "UNSEC_CHUNK_EVENT" and request:
            data, length, kind = raw[3:], int.from_bytes(request[:2], "big"), request[2]
            if len(data) != length:
                print("short answer: %d of %d bytes" % (len(data), length), file=sys.stderr)
            if kind == 4:
                signed_end = int.from_bytes(data, "big")
            elif kind == 2:
                offset = int.from_bytes(request[3:7], "big")
                for k, b in enumerate(data):
                    if seen[offset + k] and image[offset + k] != b:
                        conflicts += 1
                    image[offset + k], seen[offset + k] = b, 1
                reads += 1
            request = None
    open(sys.argv[2], "wb").write(image)
    print("%d reads, %d of %d bytes covered, %d conflicting bytes%s" % (
        reads, sum(seen), size, conflicts, ", signed area ends at 0x%04x" % signed_end if signed_end is not None else ""))


if __name__ == "__main__":
    main()

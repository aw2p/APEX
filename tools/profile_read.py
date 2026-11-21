#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only onboard profile dump (OpenGG schema-19 documented path).

Cable mode: `00 83 03 <slot> 00 02 <offset LE32>` feature write, then a
642-byte GET_FEATURE whose reply is `00 83 00 <512 data bytes>`.
24 blocks x 512 = 12,288 bytes per slot; slots 1..5.
Absolutely no writes/erases here — read-only by construction.

    python tools/profile_read.py [slot ...]     # default: all 5
"""

import os
import struct
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apexmini import device as D  # noqa: E402

BLOCK = 512
NBLOCKS = 24
PROFILE_LEN = BLOCK * NBLOCKS          # 12288
PACING = 0.035                         # > the 31 ms minimum report interval


def read_slot(dev, slot, verbose=False):
    opcode = 0x83
    blob = bytearray(PROFILE_LEN)
    for bi in range(NBLOCKS):
        off = bi * BLOCK
        buf = bytearray(642)
        buf[0] = 0x00                  # report id
        buf[1] = opcode
        buf[2] = 0x03                  # namespace 3 (keyboard, cable mode)
        buf[3] = slot                  # file id = slot 1..5
        struct.pack_into("<H", buf, 4, BLOCK)
        struct.pack_into("<I", buf, 6, off)
        dev.send_feature(bytes(buf))
        time.sleep(PACING)
        reply = dev.read_input(400, size=642) if False else None
        # reply comes via GET_FEATURE on the 642-byte feature report
        rep = __import__("apexmini.hidapi", fromlist=["get_feature"]).get_feature(dev.dev, 642)
        if len(rep) < 2 or rep[1] != opcode:
            raise RuntimeError("slot %d block %d: bad reply %s" % (slot, bi, rep[:6].hex()))
        if rep[2] != 0x00:
            raise RuntimeError("slot %d block %d: status %02X" % (slot, bi, rep[2]))
        data = rep[3:3 + BLOCK]
        if len(data) != BLOCK:
            raise RuntimeError("slot %d block %d: short data %d" % (slot, bi, len(data)))
        blob[off:off + BLOCK] = data
        if verbose and bi % 6 == 0:
            print("  slot %d block %d/%d" % (slot, bi + 1, NBLOCKS), flush=True)
    return bytes(blob)


def verify(blob):
    if len(blob) != PROFILE_LEN:
        return False, "wrong length"
    stored = struct.unpack_from("<I", blob, 0)[0]
    schema = struct.unpack_from("<I", blob, 4)[0]
    computed = zlib.crc32(blob[8:12280]) & 0xFFFFFFFF
    return (stored == computed and schema == 19), "crc %08X/%08X schema %d" % (
        stored, computed, schema)


def main():
    slots = [int(a) for a in sys.argv[1:] if a.isdigit()] or [1, 2, 3, 4, 5]
    out_dir = os.path.join(D.PR.config_dir() if hasattr(D, "PR") else
                           os.path.expanduser("~/.config/apexmini"), "dumps")
    os.makedirs(out_dir, exist_ok=True)

    devs = D.find_control_devices()
    if not devs:
        sys.exit("no keyboard found")
    dev = D.ApexDevice(devs[0])
    dev.open()
    try:
        for slot in slots:
            print("reading slot %d…" % slot, flush=True)
            blob = read_slot(dev, slot, verbose=True)
            ok, info = verify(blob)
            path = os.path.join(out_dir, "slot%d.bin" % slot)
            with open(path, "wb") as f:
                f.write(blob)
            print("  saved %s — %s (%s)" % (path, "VALID" if ok else "INVALID", info))
    finally:
        # reading should not disturb lighting, but be polite anyway
        try:
            dev.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

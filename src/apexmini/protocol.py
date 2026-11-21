#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Packet builders for the Apex Pro Mini Wireless family.

Everything here is allow-listed: only lighting / brightness / read-only
telemetry opcodes exist.  Profile-flash writes (0x83/0x02/0x03/0x42/0x43/
0xE6/0x53/0x68) are deliberately NOT implemented.

Wire layout cheat sheet (docs/cheatsheet.md):

    direct frame (feature report):
        [00][opcode][count][(usage)(R)(G)(B)] * count | zero padding to length
    control packet (65 bytes in/out; feature-sized for init on some models):
        [00][opcode][...]
"""

import sys
import os

# --- opcodes ---------------------------------------------------------
OP_LEGACY_DIRECT = 0x3A          # Apex 7/Pro/5/7-TKL "gen 1" direct lighting
OP_DIRECT = 0x40                 # Apex 2023/Gen 3 wired direct lighting
OP_DIRECT_WIRELESS = 0x61        # 2023 wireless (dongle, and USB-cable on 1646)
OP_DIRECT_CABLE = 0x21           # wireless board on USB cable (= wireless − 0x40)
OP_INIT = 0x4B                   # enables direct frames (>= fw 1.19.7 family)
OP_CLEAR = 0x41                  # drop direct ownership on wired gen3
OP_RELEASE_WIRELESS = 0x62       # drop direct ownership on wireless (dongle)
OP_RELEASE_CABLE = 0x22          # drop direct ownership on USB-cable mode
OP_PROFILE = 0x89                # select onboard profile slot 1..5
OP_FIRMWARE = 0x90               # firmware string query
OP_BRIGHTNESS_SET = 0x23         # hardware brightness 0..10
OP_BRIGHTNESS_GET = 0xA3         # brightness read-back
# read-only telemetry (dongle):
OP_BATT_WIRE_CONN = 0xBC
OP_BATT_WIRE_BATT = 0xD2
OP_BATT_WIRED = 0x92

# opcodes we will NEVER send (onboard/profile flash realm — read the notes in
# docs/RESEARCH.md; keeping this list here makes the prohibition grep-able):
FORBIDDEN = {0x83, 0x02, 0x03, 0x42, 0x43, 0xE6, 0x53, 0x68}

CONTROL_LEN = 65                 # 1 report-id byte + 64 data bytes

DONGLE_PID = 0x1624              # Apex Pro Mini Wireless, 2.4 GHz dongle
WIRED_MINI_PID = 0x1621          # Apex Pro Mini (wired), by community data
BT_MINI_PID = 0x1626             # Apex Pro Mini Wireless, Bluetooth
APEX9_MINI_PID = 0x1620


def key_table_len(report_len):
    """How many (usage,R,G,B) entries fit into a feature report of `report_len`
    bytes (which includes the report-id byte)."""
    return max(0, (report_len - 3) // 4)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build_direct_frame(opcode, entries, total_len):
    """
    Build one direct-mode lighting frame.

    entries: iterable of (usage:int, r:int, g:int, b:int)
    total_len: full buffer length INCLUDING the report-id byte (feature size + 1)

    Returns bytes of the complete buffer ready for a feature-report write.
    """
    if total_len < 3:
        raise ValueError("total_len too small")
    max_entries = key_table_len(total_len)
    entries = list(entries)
    if len(entries) > max_entries:
        entries = entries[:max_entries]
    buf = bytearray(total_len)
    buf[0] = 0x00              # report id
    buf[1] = opcode
    buf[2] = len(entries)
    off = 3
    for usage, r, g, b in entries:
        if off + 4 > total_len:
            break
        buf[off] = usage & 0xFF
        buf[off + 1] = clamp(r, 0, 255)
        buf[off + 2] = clamp(g, 0, 255)
        buf[off + 3] = clamp(b, 0, 255)
        off += 4
    return bytes(buf)


def build_control(opcode, payload=b"", total_len=CONTROL_LEN):
    """65-byte control packet (report id 0 + opcode + payload)."""
    if opcode in FORBIDDEN:
        raise ValueError("refusing forbidden opcode 0x%02X" % opcode)
    buf = bytearray(total_len)
    buf[0] = 0x00
    buf[1] = opcode
    buf[2 : 2 + len(payload)] = payload
    return bytes(buf)


def build_brightness_set(level10):
    """Hardware brightness 0..10 (0 == keys dark, 10 == max)."""
    return build_control(OP_BRIGHTNESS_SET, bytes([clamp(level10, 0, 10)]))


def build_brightness_get():
    return build_control(OP_BRIGHTNESS_GET)


def build_firmware_query():
    return build_control(OP_FIRMWARE)


def build_release(transport):
    """'stop owning the LEDs' packet per transport."""
    if transport == "wireless":
        return build_control(OP_RELEASE_WIRELESS)
    if transport == "usb":
        return build_control(OP_RELEASE_CABLE)
    return build_control(OP_CLEAR)


def parse_firmware_reply(reply):
    """reply comes from read_timeout(); expect [90 xx 'm.m.m'...]."""
    if not reply:
        return None
    if reply[0] != OP_FIRMWARE:
        return None
    try:
        text = reply[2:].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
        return text
    except Exception:
        return None


def parse_brightness_reply(reply):
    if len(reply) >= 3 and reply[0] == OP_BRIGHTNESS_GET:
        return reply[2]
    return None


def is_ack(reply, opcode):
    """status-0 ACK: [opcode 00 ...] -- a negative response is [opcode FF] or 89-type."""
    return bool(reply) and reply[0] == opcode and len(reply) >= 2 and reply[1] == 0x00


def is_unsupported(reply, opcode):
    return bool(reply) and reply[0] == opcode and len(reply) >= 2 and reply[1] == 0xFF

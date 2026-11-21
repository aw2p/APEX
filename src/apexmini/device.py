#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Device layer: discovery, ownership, and all hardware I/O for the
Apex Pro Mini Wireless (and any sibling Apex keyboard of this generation).

Transport matrix today:

    PID 0x1624  dongle   (verified live: FFC0 control iface @ 1.3,
                          64B in/out + 512B feature, FFC1 notif @ 1.4)
    PID 0x1626  bluetooth (formula not yet tested in the wild)
    PID 0x1621/0x161E  wired  (formula not yet tested in the wild)

The direct-mode packet id differs per transport (0x61 wireless / 0x40 wired /
0x3A legacy).  We auto-probe at connect time: query firmware, then try the
candidate order below, starting with one *harmless black-off* frame; the user
sees only that the keyboard goes dark -- anything weird, we stop, never
escalating.
"""

import os
import sys
import time

from . import hidapi, protocol as P, reportdesc

STEELSERIES_VID = 0x1038

KNOWN_INTERESTING_PIDS = {
    0x161E: ("Apex Pro Mini (wired)", "wired"),
    0x1620: ("Apex 9 Mini", "wired"),
    0x1621: ("Apex Pro Mini (wired 2)", "wired"),
    0x1624: ("Apex Pro Mini Wireless (Dongle)", "wireless"),
    0x1626: ("Apex Pro Mini Wireless (USB cable)", "usb"),
    0x1614: ("Apex Pro TKL", "wired"),
    0x1628: ("Apex Pro TKL (2023)", "wired"),
    0x1630: ("Apex Pro TKL (2023) Wireless", "wireless"),
    0x1632: ("Apex Pro TKL (2023) Wireless", "wireless"),
    0x1642: ("Apex Pro TKL Gen 3", "wired"),
    0x1644: ("Apex Pro TKL Wireless Gen 3 (Dongle)", "wireless"),
    0x1646: ("Apex Pro TKL Wireless Gen 3", "usb"),
}

USAGE_PAGE_CONTROL = 0xFFC0
USAGE_PAGE_NOTIFY = 0xFFC1


class DeviceInfo:
    def __init__(self, path, pid, description, transport, iface, usage_page, usage, hidraw=None):
        self.path = path
        self.pid = pid
        self.description = description
        self.transport = transport
        self.iface = iface
        self.usage_page = usage_page
        self.usage = usage
        self.hidraw = hidraw
        self.feature_len = 0
        self.collections = []
        self.path = path
        self.pid = pid
        self.description = description
        self.transport = transport
        self.iface = iface
        self.usage_page = usage_page
        self.usage = usage
        self.hidraw = hidraw

    def __repr__(self):
        return "DeviceInfo(pid=0x%04X %s transport=%s iface=%s)" % (
            self.pid, self.description, self.transport, self.iface)


def find_control_devices(vid=STEELSERIES_VID, want_pids=None):
    """Enumerate SteelSeries keyboard-family collections and reconstruct the
    one that *is* the light control interface."""
    all_devs = hidapi.enumerate_devices(vid)
    seen_ifaces = {}
    for d in all_devs:
        pid = d["product_id"]
        if pid not in KNOWN_INTERESTING_PIDS:      # exclude headsets/mice etc.
            continue
        if want_pids is not None and pid not in want_pids:
            continue
        ug = d["usage_page"]
        if ug not in (USAGE_PAGE_CONTROL, USAGE_PAGE_NOTIFY):
            continue
        # We only take the control collection (page FFC0).
        if ug != USAGE_PAGE_CONTROL:
            continue
        transport = KNOWN_INTERESTING_PIDS[pid][1]
        sysdir, hidraw = None, None
        try:
            colls, hidraw = reportdesc.collections_for_enum_path(d["path"], usb_iface=d["interface_number"])
        except Exception as e:
            print("reportdesc failed: %r" % e, file=sys.stderr)
        # prefer a collection that has a FEATURE report (the light buffer);
        # Fall back to any - control iface can be idless if we are attached
        # somewhere odd without sysfs.
        has_feat = 0
        if colls:
            for c in colls:
                for (kind, usage), size in c.reports.items():
                    if kind == "feature":
                        has_feat = max(has_feat, size)
        key = (pid, d["interface_number"])
        info = DeviceInfo(
            path=d["path"], pid=pid, description=KNOWN_INTERESTING_PIDS.get(pid, ("?", "?"))[0],
            transport=transport, iface=d["interface_number"],
            usage_page=ug, usage=d["usage"], hidraw=hidraw)
        info.feature_len = has_feat or 641
        info.all_colls = colls
        seen_ifaces[key] = info
    return list(seen_ifaces.values())


class ApexDevice:
    """Open handle + all hardware I/O for one keyboard."""

    def __init__(self, entry: DeviceInfo, verbose=False):
        self.entry = entry
        self.verbose = verbose
        self.dev = None
        self.feature_len = getattr(entry, "feature_len", 512)
        self.fw = None
        self.probe_info = {}

    # -- low level -----------------------------------------------------
    def open(self):
        self.dev = hidapi.open_path(self.entry.path)
        return self

    def close(self):
        if self.dev:
            hidapi.close(self.dev)
            self.dev = None

    def _log(self, *a):
        if self.verbose:
            print("[io]", *a, file=sys.stderr)

    def write_output(self, data):
        self._log("OUT", data[:5].hex(), "…(%d B)" % len(data))
        return hidapi.write_output(self.dev, data)

    def read_input(self, ms=200, size=None):
        size = size or 65
        r = hidapi.read_timeout(self.dev, size, ms)
        if r:
            self._log("IN ", r[:5].hex(), "…(%d B)" % len(r))
        return r

    def send_feature(self, data):
        self._log("FEAT", data[:5].hex(), "…(%d B)" % len(data))
        return hidapi.send_feature(self.dev, data)

    # -- one-time init -------------------------------------------------
    def query_firmware(self):
        out = P.build_firmware_query()
        self.write_output(out)
        # Drain any notification spam, expect [0x90 version]
        for _ in range(6):
            r = self.read_input(150)
            if not r:
                break
            if r and r[0] == P.OP_FIRMWARE:
                self.fw = P.parse_firmware_reply(r)
                return self.fw
        return None

    def send_init(self, total_len=None):
        """init: all-zero [00][0x4B]…… feature report."""
        total_len = total_len or min(self.feature_len + 1, 65)
        buf = bytearray(total_len)
        buf[0] = 0
        buf[1] = P.OP_INIT
        try:
            self.send_feature(bytes(buf))
            time.sleep(0.010)   # OpenRGB's controller "needs a moment".
            return True
        except hidapi.HidError as e:
            # try the full size (some models only accept feature-high packets)
            try:
                full = bytearray(self.feature_len + 1)
                full[0] = 0
                full[1] = P.OP_INIT
                self.send_feature(bytes(full))
                time.sleep(0.010)
                return True
            except hidapi.HidError:
                self.probe_info["init_error"] = str(e)
                return False

    # -- brightness ----------------------------------------------------
    def set_hardware_brightness(self, level10):
        self.write_output(P.build_brightness_set(level10))

    def get_hardware_brightness(self):
        self.write_output(P.build_brightness_get())
        r = self.read_input(150)
        v = P.parse_brightness_reply(r)
        return v

    # -- battery (dongle only) ------------------------------------------
    def query_battery(self):
        if self.entry.transport != "wireless":
            return None
        self.write_output(P.build_control(P.OP_BATT_WIRE_CONN))
        r = self.read_input(150)
        if not (r and r[0] == P.OP_BATT_WIRE_CONN):
            return {"connection": None}
        self.write_output(P.build_control(P.OP_BATT_WIRE_BATT))
        r = self.read_input(150)
        if not r or r[0] != P.OP_BATT_WIRE_BATT:
            return {"connection": r and r[1] == 0}
        return {"connected": bool(r[1] == 0), "raw": list(r)}

    # -- direct lighting ------------------------------------------------
    def send_direct_frame(self, opcode, entries):
        """entries: list of (usage, r, g, b). Sends a full-size feature report."""
        buf = P.build_direct_frame(opcode, entries, self.feature_len + 1)
        return self.send_feature(buf)

    def release_leds(self, transport=None):
        """Hand the lighting back to the keyboard firmware."""
        out = P.build_release(transport or self.entry.transport)
        try:
            self.write_output(out)
            return True
        except hidapi.HidError as e:
            self.probe_info["release_err"] = str(e)
            return False

    # -- full connect sequence ------------------------------------------
    def connect(self, init="auto"):
        self.open()
        self.fw = self.query_firmware()
        if init == "auto":
            self.send_init(65)
        return self

    def pick_opcode_candidates(self):
        """Opcode candidates ordered by hardware-verified knowledge:
        dongle 0x1624 → 0x61 (verified lit); USB-cable 0x1626 → 0x21
        (verified lit; = wireless − 0x40 translation from OpenGG's tables);
        wired family → 0x40 then legacy."""
        t = self.entry.transport
        if t == "wireless":
            return [P.OP_DIRECT_WIRELESS, P.OP_DIRECT, P.OP_LEGACY_DIRECT]
        if t == "usb":
            return [P.OP_DIRECT_CABLE, P.OP_DIRECT_WIRELESS, P.OP_DIRECT, P.OP_LEGACY_DIRECT]
        return [P.OP_DIRECT, P.OP_LEGACY_DIRECT]

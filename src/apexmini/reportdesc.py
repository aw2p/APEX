#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HID report descriptor parser — derives feature/input/output report sizes
per top-level collection, straight from sysfs.

Why we need this:
    The lighting/receipt interface of the Apex family exposes *plain* buffers
    but the exact **feature report length** differs by model (Apex 9 Mini: 512,
    Pro TKL 2023: 642…).  Reading the descriptor from sysfs (readable without
    root) tells us at runtime exactly how big the lighting report is, which
    interface to open, and which usage/page pair to filter on.

History of what we saw live on the ATS-mini (see docs/RESEARCH.md):
    interface 1.3  page FF C0  (F0 input 64, F1 output 64, F2 feature 512)
    interface 1.4  page FF C1  (F0 input 64)     # notification channel
"""

import os
import struct


# --- very small item walker -------------------------------------------
#
# Item format:
#   short items:  0 1 T T  T T D D  (bits 76 = tag, 54 = type, 32 = size)
#   long items:   0 F T T  T T length  (bit7 set)
#
# Main  items: type 0  (collection/input/output/feature/end_collection)
# Global items: type 1  (usage page, report sizes…)
# Local  items: type 2  (usage)
def _iter_items(blob):
    i = 0
    n = len(blob)
    while i < n:
        b = blob[i]
        if b == 0xFE:  # long item
            if i + 2 >= n:
                break
            length = blob[i + 1] | (blob[i + 2] << 8)
            yield i, blob[i + 3 : i + 3 + length], b, 2  # tag unused here
            i += 3 + length
        else:
            size = b & 0x03
            tag = (b >> 4) & 0x0F
            itype = (b >> 2) & 0x03
            data = blob[i + 1 : i + 1 + size]
            yield i, data, tag, itype
            i += 1 + size


def _signed(data):
    if not data:
        return 0
    v = int.from_bytes(data, "little")
    # sign-extend
    bits = len(data) * 8
    if v & (1 << (bits - 1)):
        v -= 1 << bits
    return v


def _unsigned(data):
    if not data:
        return 0
    return int.from_bytes(data, "little")


class Collection:
    """One top-level collection (application) of a device."""

    def __init__(self):
        self.usage_page = None
        self.usage = None
        self.reports = {}  # (kind, usage) -> size of *data* bytes
        self.actual_counts = {}  # (kind, usage) -> Report Count

    @property
    def kind_key(self):
        return (self.usage_page, self.usage)

    def __repr__(self):
        return "Collection(page=%04X usage=%04X reports=%s)" % (
            self.usage_page or 0,
            self.usage or 0,
            {k: v for k, v in sorted(self.reports.items())},
        )


def parse_report_descriptor(blob):
    """
    Returns a list of Collection.  For each top-level collection we record a
    *latest Report Size x Report Count* size per (report kind, usage id):

        kind  -- 'input' / 'output' / 'feature'
        usage -- the last usage id seen (e.g. 0xF0/0xF1/0xF2)
        size  -- parsed "size of one report item": functions use
                 Report Size x Report Count from the *most recent globals*.
    """
    collections = []
    coll_stack = []
    usage_page = 0
    report_id = 0
    report_size = 0
    report_count = 0
    usages = []  # local usages in queue
    usage_min = None
    usage_max = None
    in_collection = 0

    for _pos, data, tag, itype in _iter_items(blob):
        if itype == 1:  # global
            if tag == 0x0:  # usage page
                usage_page = _unsigned(data)
            elif tag == 0x7:  # report size
                report_size = _unsigned(data)
            elif tag == 0x8:  # report id
                report_id = _unsigned(data)
            elif tag == 0x9:  # report count
                report_count = _unsigned(data)
        elif itype == 2:  # local
            if tag == 0x0:  # usage
                usages.append((usage_page, _unsigned(data)))
            elif tag == 0x1:
                usage_min = _unsigned(data)
            elif tag == 0x2:
                usage_max = _unsigned(data)
        elif itype == 0:  # main
            if tag == 0xA:  # collection
                in_collection += 1
                if not coll_stack and in_collection > 0:
                    coll_stack.append(Collection())
                    current = coll_stack[-1]
                    use = usages
                    if len(usages) == 2:
                        current.usage_page, current.usage = use[0][1], use[1][1]
                    elif len(usages) == 1:
                        current.usage_page, current.usage = use[0][0], use[0][1]
                    del usages[:]
            elif tag == 0xC:  # end collection
                if coll_stack:
                    if len(coll_stack) == 1:
                        collections.append(coll_stack.pop())
                        in_collection = 0
                        usage_min = usage_max = None
                    else:
                        coll_stack.pop()
            elif tag in (0x8, 0x9, 0xB):  # input(8) output(9) feature(B)
                if coll_stack:
                    kind = {0x8: "input", 0x9: "output", 0xB: "feature"}[tag]
                    col = coll_stack[-1]
                    # If a specific usage was used, that is our ID for bookkeeping.
                    if usages:
                        last = usages[-1][1]
                    elif usage_min is not None:
                        last = usage_min
                    else:
                        last = 0
                    col.reports[(kind, last)] = report_size * report_count // 8
                    col.actual_counts[(kind, last)] = report_count
                usages = []
                usage_min = usage_max = None
    return collections


# --- sysfs helpers ---------------------------------------------------
def hidraw_sys_dir(hidraw_name):
    """Return the sysfs dir holding report_descriptor for a /dev/hidrawN name."""
    root = "/sys/class/hidraw"
    d = os.path.realpath(os.path.join(root, hidraw_name))
    # The descriptor lives on the HID *device* dir, parent of the hidraw node,
    # e.g.  /sys/.../0003:1038:1624.002E/report_descriptor
    for cand in (d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "report_descriptor")):
            return cand
    return None


def read_descriptor_for_hidraw(hidraw_name):
    d = hidraw_sys_dir(hidraw_name)
    if not d:
        return None
    with open(os.path.join(d, "report_descriptor"), "rb") as f:
        return f.read()


def collections_for_hidraw(hidraw_name):
    blob = read_descriptor_for_hidraw(hidraw_name)
    if blob is None:
        return []
    return parse_report_descriptor(blob)


def best_control_collection(colls, min_feature=512):
    """Pick the Apex lighting/control collection: page 0xFFC0 (or FFC1 for the
    2022 shells) that has a *feature* report of >= min_feature bytes."""
    best = None
    for c in colls:
        if c.usage_page in (0xFFC0, 0xFFC1):
            for (kind, usage), size in c.reports.items():
                if kind == "feature" and size >= min_feature:
                    if best is None or size > best.reports.get(("input", 0), 0):
                        best = c
    return best


def sysfspath_for_enum_path(hidapi_path):
    """
    Accepts both hidapi path flavours on Linux:

      * sysfs flavour: `/sys/devices/.../0003:1038:1624.002E/hidraw/hidraw7`
      * /dev flavour:  `/dev/hidraw7`

    and returns the HID sysfs device dir (the one with report_descriptor).
    """
    p = hidapi_path
    if p.startswith("/dev/hidraw"):
        return hidraw_sys_dir(os.path.basename(p))
    if "/hidraw/" in p:
        parts = p.split("/")
        for i, seg in enumerate(parts):
            if seg == "hidraw" and i >= 1:
                parent = parts[i - 1]
                return os.path.join("/", "sys", "bus", "hid", "devices", parent)
    for seg in p.split("/"):
        if seg.count(":") >= 2 and (seg.startswith("0003:") or seg.startswith("0001:")):
            return os.path.join("/", "sys", "bus", "hid", "devices", seg)
    return None


def collections_for_enum_path(hidapi_path, usb_iface=None):
    """
    Get (collections, hidraw_name) for a hidapi device path, via sysfs.
    """
    sys_dir = sysfspath_for_enum_path(hidapi_path)
    if not sys_dir:
        return [], None
    # find the hidraw node under this hid device dir
    hid_parent = os.path.dirname(sys_dir.rstrip("/"))
    hidraw = None
    for base in (sys_dir, hid_parent):
        if not os.path.isdir(base):
            continue
        hidraw_sub = os.path.join(base, "hidraw")
        if os.path.isdir(hidraw_sub):
            ents = os.listdir(hidraw_sub)
            if ents:
                hidraw = ents[0]
                break
    if hidraw:
        blob = read_descriptor_for_hidraw(hidraw)
        if blob is not None:
            return parse_report_descriptor(blob), hidraw
    # fallback: read the attached hid device dir's own report_descriptor
    rd = os.path.join(sys_dir, "report_descriptor")
    if os.path.isfile(rd):
        with open(rd, "rb") as f:
            return parse_report_descriptor(f.read()), None
    return [], None


# quick CLI: `python -m apexmini.reportdesc --hidraw hidraw7`
def _main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--hidraw", required=True)
    args = ap.parse_args()
    for c in collections_for_hidraw(args.hidraw):
        print(c)


if __name__ == "__main__":
    _main()

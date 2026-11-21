#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared evdev typing feed.

Reads struct input_event off the keyboard's EV_KEY node(s) (no third-party
packages) and calls a callback with the HID usage byte per key-down.
Both the CLI (reactive) and the GUI (preview + engine) use this.
"""

import glob
import os
import re
import select
import struct
import sys
import threading


def find_keyboard_event_nodes(vid="1038"):
    """evdev nodes belonging to our SteelSeries keyboard (any 1038:16xx pid —
    covers wired/dongle/BT re-enumerations; headsets/mice are 1290/18xx+)."""
    nodes = []
    pat = re.compile(r"1038:16[0-9A-Fa-f]{2}\.")
    for dev in os.listdir("/sys/class/hidraw"):
        path = os.path.realpath(os.path.join("/sys/class/hidraw", dev))
        parent = os.path.dirname(os.path.dirname(path))   # 0003:1038:XXXX dir
        if not pat.search(parent):
            continue
        for cand in glob.glob(os.path.join(parent, "input", "input*", "event*")):
            nodes.append("/dev/input/" + os.path.basename(cand))
    return nodes


# ---- Linux keycode -> HID usage --------------------------------------
# HID usages are alphabetical (A=0x04..Z=0x1D); Linux keycodes are in
# physical scan order — a linear offset is WRONG (C=46->0x14='Q' etc).
KEYCODE_TO_USAGE = {
    1: 0x29,                      # ESC
    2: 0x1E, 3: 0x1F, 4: 0x20, 5: 0x21, 6: 0x22, 7: 0x23,
    8: 0x24, 9: 0x25, 10: 0x26, 11: 0x27,          # 1..0
    12: 0x2D, 13: 0x2E,           # minus, equal
    14: 0x2A, 15: 0x2B,           # backspace, tab
    16: 0x14, 17: 0x1A, 18: 0x08, 19: 0x15, 20: 0x17,   # Q W E R T
    21: 0x1C, 22: 0x18, 23: 0x0C, 24: 0x12, 25: 0x13,   # Y U I O P
    26: 0x2F, 27: 0x30,           # [ ]
    28: 0x28, 29: 0xE0,           # enter, lctrl
    30: 0x04, 31: 0x16, 32: 0x07, 33: 0x09, 34: 0x0A,   # A S D F G
    35: 0x0B, 36: 0x0D, 37: 0x0E, 38: 0x0F,             # H J K L
    39: 0x33, 40: 0x34,           # ; '
    41: 0x35, 42: 0xE1, 43: 0x31, # grave, lshift, backslash
    44: 0x1D, 45: 0x1B, 46: 0x06, 47: 0x19, 48: 0x05,   # Z X C V B
    49: 0x11, 50: 0x10,           # N M
    51: 0x36, 52: 0x37, 53: 0x38, # , . /
    54: 0xE5, 56: 0xE2, 57: 0x2C, 58: 0x39,             # rshift, lalt, space, caps
    59: 0x3A, 60: 0x3B, 61: 0x3C, 62: 0x3D, 63: 0x3E, 64: 0x3F,   # F1..F6
    65: 0x40, 66: 0x41, 67: 0x42, 68: 0x43,             # F7..F10
    87: 0x44, 88: 0x45,           # F11, F12
    97: 0xE4, 100: 0xE6,          # rctrl, ralt
    103: 0x52, 105: 0x50, 106: 0x4F, 108: 0x51,         # up left right down
    125: 0xE3, 126: 0xE7,         # lgui, rgui
}


def _usage_for_code(code):
    return KEYCODE_TO_USAGE.get(code)


class TypingFeed:
    """Reads key-down events in a daemon thread; callback(usage)."""

    EV_KEY = 0x01
    EVENT_FMT = "llHHi"

    def __init__(self, callback, event_path=None):
        self.callback = callback
        self.event_path = event_path
        self._stop = threading.Event()
        self._thread = None
        self.node = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        path = self.event_path
        if path is None:
            cands = find_keyboard_event_nodes()
            # prefer nodes the kernel tags as keyboards
            import subprocess
            def is_kbd(n):
                try:
                    r = subprocess.run(["udevadm", "info", "-q", "property", "-n", n],
                                       capture_output=True, text=True, timeout=2)
                    return "ID_INPUT_KEYBOARD=1" in r.stdout
                except Exception:
                    return False
            kbd_nodes = [n for n in cands if is_kbd(n)]
            if not kbd_nodes:
                sys.stderr.write("typing feed: no evdev keyboard node found (pass event_path)\n")
                return
            path = kbd_nodes[0]
        self.node = path
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        partial = b""
        size = struct.calcsize(self.EVENT_FMT)
        try:
            while not self._stop.is_set():
                r, _w, _x = select.select([fd], [], [], 0.25)
                if not r:
                    continue
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not data:
                    continue
                partial += data
                while len(partial) >= size:
                    (_s, _u, etype, code, value) = struct.unpack(self.EVENT_FMT, partial[:size])
                    partial = partial[size:]
                    if etype == self.EV_KEY and value == 1:
                        usage = _usage_for_code(code)
                        if usage is not None:
                            try:
                                self.callback(usage)
                            except Exception:
                                pass
        finally:
            os.close(fd)

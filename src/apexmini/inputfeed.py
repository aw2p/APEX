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


def _usage_for_code(code):
    if 59 <= code <= 68:      # KEY_F1..F10
        return 0x3A + (code - 59)
    if 30 <= code <= 82:      # most printable keys (KEY_A(30) -> 0x04)
        return 4 + (code - 30)
    if code == 14:            # KEY_GRAVE
        return 0x35
    if code == 1:             # KEY_ESC
        return 0x29
    if code in (87, 88):      # F11, F12
        return 0x43 + (code - 87)
    if code == 111:
        return 0x52           # up
    if code == 114:
        return 0x50           # left
    if code == 115:
        return 0x51           # down
    if code == 113:
        return 0x4F           # right
    return None


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

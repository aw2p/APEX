#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests: no HID, no device, no root.  Run with plain python3."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from apexmini import protocol as P
from apexmini import effects as E
from apexmini import keymap as K
from apexmini import reportdesc as RD


# --- sample captured descriptors (live, from the user's own keyboard) ----
DONGLE_CONTROL = bytes.fromhex(
    "06c0ff" "0901"
    "a101"
    "06c1ff" "1500" "26ff00" "7508"
    "09f0" "9540" "8102"
    "09f1" "9540" "9102"
    "09f2" "968102" "b102"      # count = 0x0281 = 641 (live capture!)
    "c0"
)
DONGLE_NOTIFY = bytes.fromhex(
    "06c1ff" "0901"
    "a101"
    "09f0" "1500" "26ff00" "7508"
    "9540" "8102"
    "c0"
)
DONGLE_MOUSE = bytes.fromhex(
    "0501" "0902" "a101" "0901" "a100" "a102"
    "0509" "1901" "2908" "1500" "2501" "9508" "7501" "8102"
    "0501" "0930" "0931" "0160" "8012" "6ff7" "fe10" "75019502" "8106"
    "0938" "1581" "257f" "7508" "9501" "8106" "c0a1" "0205" "0c0a"
    "3802" "1581" "257f" "7508" "9501" "8106" "c0a1" "0206" "8c1f"
    "0f1500" "26007f" "7510" "9501" "8102" "c0c0c0"
)


class TestReportDesc(unittest.TestCase):
    def test_dongle_control_collection(self):
        colls = RD.parse_report_descriptor(DONGLE_CONTROL)
        self.assertEqual(len(colls), 1)
        c = colls[0]
        self.assertEqual(c.usage_page, 0xFFC0)
        self.assertEqual(c.usage, 0x0001)
        # 641-byte feature (live! Matches OpenGG's 'feature length 642'
        # spec for the TKL Wireless Gen3: 641 data + 1 report-id byte)
        self.assertEqual(c.reports[("feature", 0xF2)], 641)
        self.assertEqual(c.reports[("input", 0xF0)], 64)
        self.assertEqual(c.reports[("output", 0xF1)], 64)

    def test_dongle_notify_collection(self):
        colls = RD.parse_report_descriptor(DONGLE_NOTIFY)
        self.assertEqual(len(colls), 1)
        c = colls[0]
        self.assertEqual((c.usage_page, c.usage), (0xFFC1, 0x0001))
        self.assertEqual(c.reports[("input", 0xF0)], 64)

    def test_frame_fits_feature(self):
        # 112-key table must fit into a 642-byte feature report incl. id
        buf = P.build_direct_frame(0x61, [(0x04, 1, 2, 3)] * 112, 642)
        self.assertEqual(buf[2], 112)


class TestProtocol(unittest.TestCase):
    def test_direct_frame_exact_layout(self):
        buf = P.build_direct_frame(0x61, [(0x04, 255, 0, 0), (0x05, 0, 255, 0)], 513)
        self.assertEqual(len(buf), 513)
        self.assertEqual(buf[0], 0x00)
        self.assertEqual(buf[1], 0x61)
        self.assertEqual(buf[2], 2)
        self.assertEqual(buf[3:7], bytes([0x04, 255, 0, 0]))
        self.assertEqual(buf[7:11], bytes([0x05, 0, 255, 0]))
        # everything after entries is zero padding (513 - 11 = 502 bytes)
        self.assertEqual(buf[11:513], b"\x00" * 502)

    def test_direct_frame_clamps_entries(self):
        # 513 bytes -> (513-3)//4 = 127 entries max
        entries = [(0x04, 1, 2, 3)] * 200
        buf = P.build_direct_frame(0x40, entries, 513)
        self.assertEqual(buf[2], 127)
        n_on = sum(1 for i in range(127) if buf[3 + 4 * i] == 0x04)
        self.assertEqual(n_on, 127)

    def test_control_refuses_flash_opcodes(self):
        self.assertRaises(ValueError, P.build_control, 0x83)
        self.assertRaises(ValueError, P.build_control, 0x42)
        self.assertRaises(ValueError, P.build_control, 0xE6)

    def test_known_packets(self):
        f = P.build_firmware_query()
        self.assertEqual(f[:2], b"\x00\x90")
        self.assertEqual(len(f), 65)
        b = P.build_brightness_set(7)
        self.assertEqual(b[:3], b"\x00\x23\x07")
        g = P.build_brightness_get()
        self.assertEqual(g[:2], b"\x00\xa3")
        i = P.build_release("wireless")
        self.assertEqual(i[:2], b"\x00\x62")
        w = P.build_release("wired")
        self.assertEqual(w[:2], b"\x00\x41")

    def test_reply_parsers(self):
        self.assertEqual(P.parse_firmware_reply(bytes.fromhex("9000312e31392e37")), "1.19.7")
        self.assertEqual(P.parse_brightness_reply(bytes.fromhex("a30007")), 7)
        self.assertTrue(P.is_ack(bytes.fromhex("4b00"), 0x4B))
        self.assertTrue(P.is_unsupported(bytes.fromhex("89ff"), 0x89))


class TestEffects(unittest.TestCase):
    def _keys(self):
        return [0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A]

    def test_static(self):
        fx = E.Static(self._keys(), (10, 20, 30))
        out = fx.tick(0.0)
        self.assertEqual(out[0x04], (10, 20, 30))
        self.assertEqual(len(out), len(self._keys()))

    def test_breathing_range(self):
        fx = E.Breathing(self._keys(), (0, 255, 0), period=4.0)
        mx = fx.tick(1.0)
        lo = fx.tick(3.0)
        self.assertGreaterEqual(max(mx[0x04]), max(lo[0x04]))
        self.assertTrue(all(0 <= c <= 255 for u in self._keys() for c in fx.tick(2.3)[u]))

    def test_spectrum_cycles(self):
        fx = E.Spectrum(self._keys(), period=4.0)
        a = fx.tick(0.0)[0x04]
        b = fx.tick(2.0)[0x04]
        self.assertNotEqual(a, b)
        self.assertEqual(fx.tick(0.0)[0x04], fx.tick(4.0)[0x04])

    def test_reactive_decay(self):
        import time
        fx = E.Reactive(self._keys(), color=(255, 64, 0), bg=(4, 4, 4))
        fx.react(0x04)
        t0 = fx.tick(0.1)
        self.assertGreater(t0[0x04][0], 100)
        self.assertEqual(fx.tick(0.0)[0x05], (4, 4, 4))

    def test_parse_color(self):
        self.assertEqual(E.parse_color("red"), (255, 0, 0))
        self.assertEqual(E.parse_color("#1a2b3c"), (26, 43, 60))
        self.assertEqual(E.parse_color("abc"), (170, 187, 204))
        self.assertRaises(ValueError, E.parse_color, "bogus")


class TestKeymap(unittest.TestCase):
    def test_roundtrip(self):
        for name, usage in K.NAME_TO_USAGE.items():
            self.assertEqual(K.usage_for_name(name), usage)
        self.assertEqual(K.usage_for_name("A"), K.NAME_TO_USAGE["a"])
        self.assertEqual(K.name_for_usage(0x04), "A")
        self.assertEqual(K.name_for_usage(0xFB), "LOGO")

    def test_mini_keys_subset_in_generic(self):
        # per-key names must exist for the subset that matters on the mini board
        for name in ("a", "s", "d", "w", "space", "esc", "f1", "f12"):
            self.assertIn(K.NAME_TO_USAGE[name], K.OPENRGB_DIRECT_KEYS)


# FlashGuard: nothing here ever builds forbidden opcodes.
if __name__ == "__main__":
    unittest.main(verbosity=2)

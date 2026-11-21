#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for profiles + engine (no Qt, no HID)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from apexmini import profiles as PR
from apexmini import engine as EN
from apexmini import keymap as K


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_roundtrip(self):
        p = PR.new_profile("test one", "breathing", ["#ff0000", "#0000ff"], speed=1.5, reactive=True)
        path = PR.save(p, self.dir)
        loaded = PR.load(p["name"], self.dir)
        self.assertEqual(loaded["base"]["type"], "breathing")
        self.assertEqual(loaded["base"]["speed"], 1.5)
        self.assertTrue(loaded["reactive"]["enabled"])
        self.assertTrue(os.path.exists(path))

    def test_list_and_delete(self):
        PR.save(PR.new_profile("alpha"), self.dir)
        PR.save(PR.new_profile("beta"), self.dir)
        names = [x["name"] for x in PR.list_profiles(self.dir)]
        self.assertEqual(names, ["alpha", "beta"])
        self.assertTrue(PR.delete("alpha", self.dir))
        self.assertEqual([x["name"] for x in PR.list_profiles(self.dir)], ["beta"])

    def test_sanitize_name(self):
        self.assertEqual(PR.sanitize_name("my/../evil profile!!"), "my_._evil profile__")
        self.assertEqual(PR.sanitize_name("..hidden"), "hidden")
        self.assertEqual(PR.sanitize_name(""), "unnamed")

    def test_validate_clamps(self):
        p = PR.new_profile("x", speed=99, brightness=-5, decay=99)
        v = PR.validate(p)
        self.assertEqual(v["base"]["speed"], 3.0)
        self.assertEqual(v["base"]["brightness"], 0.0)
        self.assertEqual(v["reactive"]["decay"], 8.0)

    def test_bad_type_rejected(self):
        p = PR.new_profile("x", base_type="disco")
        self.assertRaises(ValueError, PR.validate, p)


class TestEngine(unittest.TestCase):
    def test_all_types_produce_112_colors(self):
        for t in PR.BASE_TYPES:
            e = EN.Engine(PR.new_profile("t", t, ["#ff0000", "#0000ff"]))
            cols = e.colors(1.234)
            self.assertEqual(len(cols), len(K.OPENRGB_DIRECT_KEYS), t)
            for u, c in cols.items():
                self.assertTrue(all(0 <= v <= 255 for v in c), (t, u, c))

    def test_reactive_flash_and_decay(self):
        e = EN.Engine(PR.new_profile("t", "static", ["#000000"], reactive=True,
                                     reactive_color="#00ff00", decay=1.0))
        e.note_press(0x04)                      # A
        cols = e.colors(0.2)
        self.assertGreater(cols[0x04][1], 100)  # green component up
        # after full decay the flash is gone (engine prunes expired entries)
        import time as _t
        e.reactive_state[0x04] = _t.monotonic() - 2.0
        cols = e.colors(0.0)
        self.assertEqual(cols[0x04], (0, 0, 0))

    def test_brightness_multiplier(self):
        e = EN.Engine(PR.new_profile("t", "static", ["#ffffff"], brightness=0.5))
        cols = e.colors(0.0)
        r = cols[0x04]
        self.assertTrue(100 <= r[0] <= 140, r)  # ~127.5 ± rounding

    def test_speed_changes_wave(self):
        e1 = EN.Engine(PR.new_profile("t", "wave", ["#ff0000", "#0000ff"], speed=0.05))
        e2 = EN.Engine(PR.new_profile("t", "wave", ["#ff0000", "#0000ff"], speed=3.0))
        c1 = e1.colors(1.0)[0x04]
        c2 = e2.colors(1.0)[0x04]
        self.assertNotEqual(c1, c2)

    def test_set_profile(self):
        e = EN.Engine(PR.new_profile("t", "static", ["#ff0000"]))
        e.set_profile(PR.new_profile("t2", "spectrum", ["#ff0000"]))
        self.assertEqual(e.get_profile()["base"]["type"], "spectrum")


if __name__ == "__main__":
    unittest.main(verbosity=2)

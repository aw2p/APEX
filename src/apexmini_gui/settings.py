#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny settings store: ~/.config/apexmini/settings.json"""

import json
import os

from apexmini import profiles as PR

DEFAULTS = {
    "keyboard_mode": "3d",       # '3d' = real GL keyboard, 'stylized' = painter
    "zoom": 1.0,                 # 0.5 .. 2.2 keyboard zoom
}


def path():
    return os.path.join(PR.config_dir(), "settings.json")


def load():
    s = dict(DEFAULTS)
    try:
        with open(path(), "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    s["keyboard_mode"] = "stylized" if s.get("keyboard_mode") == "stylized" else "3d"
    try:
        s["zoom"] = max(0.5, min(2.2, float(s.get("zoom", 1.0))))
    except (TypeError, ValueError):
        s["zoom"] = 1.0
    return s


def save(settings):
    os.makedirs(PR.config_dir(), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, path())

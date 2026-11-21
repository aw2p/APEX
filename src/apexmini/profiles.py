#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lighting profiles: data model, JSON files in ~/.config/apexmini/profiles.

Schema (v1):
{
  "name": "candlelight",
  "version": 1,
  "base": {
    "type": "candle",            # static | breathing | spectrum | wave | gradient | candle
    "colors": ["#ff6a00", "#ff2b00"],
    "speed": 0.6,                # 0.05 .. 3  (multiplier on time)
    "brightness": 1.0            # 0 .. 1 software multiplier
  },
  "reactive": {
    "enabled": true,
    "color": "#ffb060",          # flash colour on keypress
    "decay": 1.2                 # seconds until a flash fully fades
  },
  "fps": 16
}

Profiles are plain JSON, one file per profile, stored as
``<profiles_dir>/<name>.json``.  The GUI hot-reloads the folder; the daemon
switches profiles by rewriting ``active.json`` (name only) — cheap, robust,
works over any transport the user likes.
"""

import json
import os
import re
import time

BASE_TYPES = ("static", "breathing", "spectrum", "wave", "gradient", "candle")

DEFAULT_PROFILE = {
    "name": "candlelight",
    "version": 1,
    "base": {"type": "candle", "colors": ["#ff6a00", "#ff2b00"], "speed": 1.0, "brightness": 0.9},
    "reactive": {"enabled": True, "color": "#ffb060", "decay": 1.1},
    "fps": 16,
}


def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "apexmini")


def profiles_dir():
    return os.path.join(config_dir(), "profiles")


def active_marker_path():
    return os.path.join(config_dir(), "active.json")


def sanitize_name(name):
    name = re.sub(r"[^\w \-'.()&]", "_", name).strip()
    name = re.sub(r"\.{2,}", ".", name)     # no path traversal ("..")
    name = name.lstrip(".")                 # no dotfile shenanigans
    return name[:64] or "unnamed"


def validate(profile):
    """Raise ValueError on structural nonsense; fill sane defaults otherwise."""
    p = dict(profile)
    p.setdefault("version", 1)
    p["name"] = sanitize_name(str(p.get("name", "unnamed")))
    base = dict(p.get("base") or {})
    base["type"] = base.get("type", "static")
    if base["type"] not in BASE_TYPES:
        raise ValueError("unknown base type %r" % base["type"])
    cols = base.get("colors") or ["#ff6a00"]
    if not isinstance(cols, list) or not cols or not all(isinstance(c, str) for c in cols):
        raise ValueError("base.colors must be a non-empty list of hex strings")
    base["colors"] = cols[:8]
    base["speed"] = max(0.05, min(3.0, float(base.get("speed", 1.0))))
    base["brightness"] = max(0.0, min(1.0, float(base.get("brightness", 1.0))))
    p["base"] = base
    re_ = dict(p.get("reactive") or {})
    re_["enabled"] = bool(re_.get("enabled", False))
    re_["color"] = str(re_.get("color", "#ffb060"))
    re_["decay"] = max(0.15, min(8.0, float(re_.get("decay", 1.2))))
    p["reactive"] = re_
    p["fps"] = max(1, min(60, int(p.get("fps", 16))))
    return p


def save(profile, directory=None):
    p = validate(profile)
    directory = directory or profiles_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, p["name"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load(name, directory=None):
    directory = directory or profiles_dir()
    path = name if os.path.isfile(name) else os.path.join(directory, name + ".json")
    with open(path, "r", encoding="utf-8") as f:
        return validate(json.load(f))


def delete(name, directory=None):
    directory = directory or profiles_dir()
    path = os.path.join(directory, name + ".json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def list_profiles(directory=None):
    """[{name, path, mtime, profile}] sorted by name."""
    directory = directory or profiles_dir()
    out = []
    if os.path.isdir(directory):
        for fn in sorted(os.listdir(directory)):
            if fn.endswith(".json"):
                path = os.path.join(directory, fn)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        p = validate(json.load(f))
                    out.append({"name": p["name"], "path": path, "mtime": os.path.getmtime(path), "profile": p})
                except (ValueError, json.JSONDecodeError, OSError):
                    continue  # skip broken files rather than exploding the UI
    return out


def set_active_name(name):
    os.makedirs(config_dir(), exist_ok=True)
    with open(active_marker_path(), "w", encoding="utf-8") as f:
        json.dump({"name": name, "t": time.time()}, f)


def get_active_name():
    try:
        with open(active_marker_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("name")
    except (OSError, json.JSONDecodeError):
        return None


def import_file(src_path):
    with open(src_path, "r", encoding="utf-8") as f:
        p = validate(json.load(f))
    return save(p)


# --- factory helpers for the GUI builder -------------------------------
def new_profile(name="new profile", base_type="static", colors=("#00d5ff",), speed=1.0,
                brightness=1.0, reactive=False, reactive_color="#ffffff", decay=1.0, fps=16):
    return {
        "name": sanitize_name(name),
        "version": 1,
        "base": {"type": base_type, "colors": list(colors), "speed": speed, "brightness": brightness},
        "reactive": {"enabled": bool(reactive), "color": reactive_color, "decay": decay},
        "fps": fps,
    }

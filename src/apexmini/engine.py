#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lighting engine: profile -> per-key colors -> keyboard frames.

The engine is pure computation plus a thin device loop, so the GUI can use
the *same* computation for its fake-3D preview (engine.colors(t)) while the
device thread streams real frames.

Pipeline (all hardware-validated on the 1624 dongle):
    [00][0x61][count][(usage)(R)(G)(B)]*count | padding  (642-byte feature)
    init 0x4B after (re)connect, release 0x62 on shutdown.
"""

import math
import threading
import time

from . import keymap as K
from . import profiles as PR
from . import effects as EF     # reuse color helpers + FramePump


# ---------------------------------------------------------------------
# base colour functions — (profile, t) -> {usage: (r,g,b)}
# ---------------------------------------------------------------------
def _clamp01(v):
    return max(0.0, min(1.0, v))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _palette(profile):
    cols = [EF.parse_color(c) for c in (profile["base"].get("colors") or ["#ff6a00"])]
    return cols or [(255, 106, 0)]


def base_static(profile, t):
    cols = _palette(profile)
    if len(cols) == 1:
        return {u: cols[0] for u in K.OPENRGB_DIRECT_KEYS}
    # multi-colour: spread as a soft diagonal gradient across the key order
    n = len(K.OPENRGB_DIRECT_KEYS)
    out = {}
    for i, u in enumerate(K.OPENRGB_DIRECT_KEYS):
        x = i / max(1, n - 1)
        seg = x * (len(cols) - 1)
        j = min(len(cols) - 2, int(seg))
        out[u] = _mix(cols[j], cols[j + 1], seg - j)
    return out


def base_gradient(profile, t):
    return base_static(profile, t)


def base_breathing(profile, t):
    cols = _palette(profile)
    speed = profile["base"]["speed"]
    k = (1 + math.sin(2 * math.pi * t * speed / 4.0)) / 2.0
    out = {}
    for i, u in enumerate(K.OPENRGB_DIRECT_KEYS):
        # stagger phases slightly so the pulse ripples rather than blinks
        kk = (1 + math.sin(2 * math.pi * t * speed / 4.0 - i * 0.05)) / 2.0
        c = cols[i % len(cols)]
        out[u] = EF.scale(c, 0.15 + 0.85 * kk)
    return out


def base_spectrum(profile, t):
    speed = profile["base"]["speed"]
    out = {}
    for u in K.OPENRGB_DIRECT_KEYS:
        out[u] = EF.hsv((t * speed / 4.0) % 1.0, 1.0, 1.0)
    return out


def base_wave(profile, t):
    cols = _palette(profile)
    speed = profile["base"]["speed"]
    spread = 18
    out = {}
    for i, u in enumerate(K.OPENRGB_DIRECT_KEYS):
        ph = (t * speed / 4.0 + i / spread) % 1.0
        if len(cols) == 1:
            out[u] = EF.scale(cols[0], 0.25 + 0.75 * (0.5 + 0.5 * math.cos(2 * math.pi * ph)))
        else:
            seg = ph * len(cols)
            j = int(seg) % len(cols)
            jj = (j + 1) % len(cols)
            out[u] = _mix(cols[j], cols[jj], seg - int(seg))
    return out


def base_candle(profile, t):
    # reuse the dedicated Candle effect (ignores palette colours by design)
    if not hasattr(base_candle, "_fx"):
        base_candle._fx = EF.Candle(list(K.OPENRGB_DIRECT_KEYS))
    return base_candle._fx.tick(t * profile["base"]["speed"])


BASE_FNS = {
    "static": base_static,
    "gradient": base_gradient,
    "breathing": base_breathing,
    "spectrum": base_spectrum,
    "wave": base_wave,
    "candle": base_candle,
}


# ---------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------
class Engine:
    """Pure state machine.  Call colors(t) for preview OR stream."""

    def __init__(self, profile=None):
        self.profile = PR.validate(profile or dict(PR.DEFAULT_PROFILE))
        self.reactive_state = {}          # usage -> press-time (monotonic)
        self.lock = threading.Lock()
        self._t0 = time.monotonic()

    # -- profile ------------------------------------------------------
    def set_profile(self, profile):
        p = PR.validate(profile)
        with self.lock:
            # keep flicker continuity for candle
            if p["base"]["type"] != self.profile["base"]["type"]:
                base_candle.__dict__.pop("_fx", None)
            self.profile = p
            self._t0 = time.monotonic()

    def get_profile(self):
        with self.lock:
            return self.profile

    def note_press(self, usage):
        with self.lock:
            self.reactive_state[usage] = time.monotonic()

    # -- colour computation -------------------------------------------
    def colors(self, t=None):
        with self.lock:
            prof = self.profile
            base = BASE_FNS[prof["base"]["type"]](prof, (t if t is not None else time.monotonic() - self._t0))
            re_ = prof["reactive"]
            if re_["enabled"]:
                now = time.monotonic()
                flash = EF.parse_color(re_["color"])
                decay = re_["decay"]
                for u, t0 in list(self.reactive_state.items()):
                    dt = now - t0
                    if dt >= decay:
                        self.reactive_state.pop(u, None)
                        continue
                    k = 1.0 - dt / decay
                    k = k * k                      # ease-out decay
                    base[u] = _mix(base.get(u, (0, 0, 0)), flash, k)
            br = prof["base"]["brightness"]
            if br < 0.999:
                for u in base:
                    base[u] = EF.scale(base[u], br)
            return base

    def frame_entries(self, t=None):
        colors = self.colors(t)
        return [(u, *colors.get(u, (0, 0, 0))) for u in K.OPENRGB_DIRECT_KEYS]

    # -- device streaming ----------------------------------------------
    def stream_forever(self, stop_event, on_status=None, verbose=False):
        """Own the LEDs and stream frames until stop_event is set.
        Reconnects on device errors (replug-proof), releases on exit."""
        from . import device as D
        dev = None
        opcode = None
        last_tick = 0.0
        try:
            while not stop_event.is_set():
                if dev is None:
                    devs = D.find_control_devices()
                    if not devs:
                        if on_status:
                            on_status("waiting for keyboard…")
                        stop_event.wait(1.0)
                        continue
                    dev = D.ApexDevice(devs[0], verbose=verbose)
                    dev.connect()
                    opcode = dev.pick_opcode_candidates()[0]
                    if on_status:
                        on_status("keyboard connected (%s)" % hex(dev.entry.pid))
                fps = self.get_profile()["fps"]
                period = 1.0 / max(1, fps)
                try:
                    now = time.monotonic()
                    if now - last_tick >= period:
                        dev.send_direct_frame(opcode, self.frame_entries())
                        last_tick = now
                    stop_event.wait(min(0.05, max(0.004, period - (time.monotonic() - now))))
                except Exception:
                    try:
                        dev.release_leds()
                    except Exception:
                        pass
                    dev.close()
                    dev = None
                    stop_event.wait(0.8)
        finally:
            if dev is not None:
                try:
                    dev.release_leds()
                except Exception:
                    pass
                dev.close()

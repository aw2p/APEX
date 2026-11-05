#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Software effect engine — computes per-key RGB for every generation of
supported effects and turns it into one direct frame per tick.

All colors are computed at *integer* timing (a monotonically increasing
t in seconds) so animation is consistent regardless of render time.
"""

import colorsys
import math
import time


# ---- color helpers ---------------------------------------------------
def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(max(0, min(1, h)) % 1.0, max(0, min(1, s)), max(0, min(1, v)))
    return (int(r * 255), int(g * 255), int(b * 255))


def scale(c, k):
    return tuple(int(max(0, min(255, ch * k))) for ch in c)


def lerp(a, b, t):
    return tuple(int(sa + (sb - sa) * t) for sa, sb in zip(a, b))


def hex2rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(x * 2 for x in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c):
    return "#%02X%02X%02X" % c


NAMED = {
    "red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    "cyan": (0, 255, 255), "magenta": (255, 0, 255), "yellow": (255, 255, 0),
    "white": (255, 255, 255), "orange": (255, 128, 0), "purple": (128, 0, 255),
    "pink": (255, 105, 180), "off": (0, 0, 0), "black": (0, 0, 0),
}


def parse_color(s):
    name = s.casefold()
    if name in NAMED:
        return NAMED[name]
    try:
        h = s.lstrip("#")
        if len(h) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in h):
            return hex2rgb(h)
    except ValueError:
        pass
    raise ValueError("bad color: %r" % s)


# **** effects --------------------------------------------------------
class Effect:
    """Base class.  tick(t, keys) -> {(usage): (r,g,b)}"""

    needs_keys = True

    def __init__(self, key_usages):
        self.key_usages = list(key_usages)

    def tick(self, t):
        raise NotImplementedError


class Static(Effect):
    def __init__(self, keys, color):
        super().__init__(keys)
        self.color = color

    def tick(self, t):
        return {u: self.color for u in self.key_usages}


class Breathing(Effect):
    """All keys pulsate between off and `color`."""

    def __init__(self, keys, color, period=4.0):
        super().__init__(keys)
        self.color = color
        self.period = period

    def tick(self, t):
        k = (1 + math.sin(2 * math.pi * t / self.period)) / 2  # 0..1
        return {u: scale(self.color, k) for u in self.key_usages}


class Spectrum(Effect):
    """Rainbow over time (all keys the same hue)."""

    def __init__(self, keys, period=4.0):
        super().__init__(keys)
        self.period = period

    def tick(self, t):
        c = hsv((t / self.period) % 1.0, 1.0, 1.0)
        return {u: c for u in self.key_usages}


class Wave(Effect):
    """A rainbow/gradient sweeping across the *keyboard row order*.
    `order` is an iterator of usage keys sorted left-to-right (built from
    keymap MINI_KEYS in "physical-ish" order).  Columns stream one pixel of
    hue per time step across a `spread` of rows."""

    def __init__(self, keys, period=4.0, spread=24, colors=None):
        super().__init__(keys)
        self.period = period
        self.spread = spread
        self.order = keys  # open: ordered list to sweep left-to-right
        self.colors = colors  # None => full rainbow

    def tick(self, t):
        out = {}
        n = len(self.order)
        if n == 0:
            return out
        base_hue = (t / self.period) % 1.0
        for i, u in enumerate(self.order):
            hue = (base_hue + i / max(1, self.spread)) % 1.0
            out[u] = hsv(hue, 1.0, 1.0) if self.colors is None else self.colors[(i // 4) % len(self.colors)]
        return out


class Reactive(Effect):
    """Keys light up on 'press' then fade out.  The caller feeds key-press
    events via `react(usage)`; time-decay handles the fade."""

    def __init__(self, keys, color=(255, 0, 0), decay=1.2, bg=(8, 8, 8), lifetime=1.5):
        super().__init__(keys)
        self.color = color
        self.decay = decay
        self.bg = bg
        self.lifetime = lifetime
        self.state = {}  # usage -> last-activation t

    def react(self, usage):
        self.state[usage] = time.monotonic()

    def tick(self, t):
        now = time.monotonic()
        out = {}
        for u in self.key_usages:
            t0 = self.state.get(u)
            if t0 is None:
                out[u] = self.bg
            else:
                dt = now - t0
                if dt > self.lifetime:
                    out[u] = self.bg
                else:
                    k = 1.0 - dt / self.lifetime
                    out[u] = lerp(self.bg, self.color, k)
        return out


class Candle(Effect):
    """Per-key candlelight: nearly-dark red up to bright amber, each key
    flickering on its own stack of incommensurate sines plus a shared
    'gust' — slow, organic, never repeating visibly (hash-seeded phases)."""

    def __init__(self, keys, seed=3, speed=1.0):
        super().__init__(keys)
        import random
        rng = random.Random(seed)
        self.speed = speed
        self.phase = {}
        self.freq = {}
        self.base = {}
        for u in keys:
            self.phase[u] = (
                rng.uniform(0, 2 * math.pi),
                rng.uniform(0, 2 * math.pi),
                rng.uniform(0, 2 * math.pi),
            )
            self.freq[u] = (
                rng.uniform(0.09, 0.16),   # slow breathing (6–11 s)
                rng.uniform(0.3, 0.55),    # mid flicker (2–3 s)
                rng.uniform(0.9, 1.6),     # quick shimmer (~0.7 s), tiny amplitude
            )
            self.base[u] = 0.28 + 0.42 * rng.random()

    dark = (55, 0, 0)          # near-black red
    mid = (255, 70, 0)         # deep orange
    bright = (255, 140, 25)    # bright amber
    peak = (255, 190, 90)      # occasional hot moment

    @staticmethod
    def _ramp(v):
        # two-segment gradient dark->mid->bright, then a hint of peak
        if v < 0.5:
            t = v / 0.5
            return lerp(Candle.dark, Candle.mid, t)
        if v < 0.9:
            return lerp(Candle.mid, Candle.bright, (v - 0.5) / 0.4)
        return lerp(Candle.bright, Candle.peak, (v - 0.9) / 0.1)

    def tick(self, t):
        now = time.monotonic() * self.speed
        out = {}
        gust = 0.07 * math.sin(2 * math.pi * now / 11.0 + 1.7) \
             + 0.05 * math.sin(2 * math.pi * now / 3.9 + 0.4)
        for u in self.key_usages:
            p1, p2, p3 = self.phase[u]
            f1, f2, f3 = self.freq[u]
            v = self.base[u] + gust \
                + 0.20 * math.sin(2 * math.pi * f1 * now + p1) \
                + 0.14 * math.sin(2 * math.pi * f2 * now + p2) \
                + 0.05 * math.sin(2 * math.pi * f3 * now + p3)
            v = max(0.0, min(1.0, v))
            v = v * v                     # bias toward dim, sharper flare events
            out[u] = self._ramp(v)
        return out


# ---- frame writer ---------------------------------------------------
class FramePump:
    """Owns a device handle and pushes repeated frames at a target Hz.
    Survives device drops by re-discovering + re-initialising the keyboard
    (dongle replug, BT blink) instead of dying."""

    def __init__(self, device, opcode, keys, effect, hz=24):
        self.dev = device
        self.opcode = opcode
        self.keys = list(keys)
        self.effect = effect
        self.period = 1.0 / hz
        self._stop = False
        self._reconnects = 0

    def stop(self):
        self._stop = True

    def once(self):
        colors = self.effect.tick(time.monotonic())
        entries = [(u, *colors.get(u, (0, 0, 0))) for u in self.keys]
        self.dev.send_direct_frame(self.opcode, entries)

    def _rescue(self):
        """Reconnect after a device error (silent best-effort)."""
        import sys as _sys
        try:
            self.dev.close()
        except Exception:
            pass
        for attempt in range(6):
            time.sleep(0.7 * (attempt + 1))
            try:
                from . import device as _D
                devs = _D.find_control_devices()
                if not devs:
                    continue
                fresh = _D.ApexDevice(devs[0], verbose=self.dev.verbose)
                fresh.connect()
                self.dev = fresh
                self._reconnects += 1
                once_more = self.dev.send_direct_frame(self.opcode,
                    [(u, *self.effect.tick(time.monotonic()).get(u, (0, 0, 0))) for u in self.keys])
                if once_more is not None:
                    return True
            except Exception:
                continue
        return False

    def run(self, stop_after=None):
        t0 = time.monotonic()
        fails = 0
        while not self._stop:
            try:
                self.once()
                fails = 0
            except Exception:
                fails += 1
                if fails <= 2:
                    time.sleep(0.1)
                    continue
                if not self._rescue():
                    self._stop = True
                    break
                fails = 0
            time.sleep(self.period)
            if stop_after is not None and time.monotonic() - t0 > stop_after:
                break

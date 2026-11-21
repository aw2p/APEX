#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fake-3D isometric keyboard preview (software rendered).

A 60%-style keycap field drawn as shaded extruded boxes in isometric
projection, lit per-key from the engine's live colour map, plus an ambient
plasma (slow drifting radial glows) behind it in the profile's palette.
Reactive typing flashes keys here exactly as on the real board.

Everything is plain QPainter math — no GL, no assets.
"""

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)

from apexmini import keymap as K

# ---- 60% layout (the Apex Pro Mini Wireless has NO dedicated F row —
# F1..F12 live on the Fn layer; preview mirrors the physical board).
# rows of (key-name-or-None, width-in-units); None = spacer
_ROW0 = [("esc", 1.0), ("1", 1.0), ("2", 1.0), ("3", 1.0), ("4", 1.0),
         ("5", 1.0), ("6", 1.0), ("7", 1.0), ("8", 1.0), ("9", 1.0), ("0", 1.0),
         ("minus", 1.0), ("equal", 1.0), ("backspace", 2.0)]
_ROW1 = [("tab", 1.5), ("q", 1.0), ("w", 1.0), ("e", 1.0), ("r", 1.0), ("t", 1.0),
         ("y", 1.0), ("u", 1.0), ("i", 1.0), ("o", 1.0), ("p", 1.0),
         ("bracketleft", 1.0), ("bracketright", 1.0), ("backslash", 1.5)]
_ROW2 = [("capslock", 1.75), ("a", 1.0), ("s", 1.0), ("d", 1.0), ("f", 1.0), ("g", 1.0),
         ("h", 1.0), ("j", 1.0), ("k", 1.0), ("l", 1.0), ("semicolon", 1.0),
         ("apostrophe", 1.0), ("enter", 2.25)]
_ROW3 = [("lshift", 2.25), ("z", 1.0), ("x", 1.0), ("c", 1.0), ("v", 1.0), ("b", 1.0),
         ("n", 1.0), ("m", 1.0), ("comma", 1.0), ("period", 1.0), ("slash", 1.0),
         ("rshift", 2.75)]
_ROW4 = [("lctrl", 1.25), ("lgui", 1.25), ("lalt", 1.25), ("space", 6.25),
         ("ralt", 1.25), ("fn", 1.25), ("rctrl", 1.25)]

LAYOUT = [_ROW0, _ROW1, _ROW2, _ROW3, _ROW4]


class IsoKey:
    __slots__ = ("usage", "label", "w", "gx", "gy", "phase")

    def __init__(self, usage, label, w, gx, gy):
        self.usage = usage
        self.label = label
        self.w = w
        self.gx = gx          # grid x (units)
        self.gy = gy          # grid y (row index)
        self.phase = random.uniform(0, 2 * math.pi)  # for plasma shimmer


class Keyboard3DPreview:
    """Painter-driven fake-3D keyboard.  Call set_colors(dict) each frame."""

    DEPTH = 0.22          # keycap extrusion height in grid units
    GAP = 0.12            # gap between keycaps (units)

    def __init__(self, widget):
        self.w = widget
        self.colors = {}
        self.keys = []
        self._build_keys()
        self.plasma_t = 0.0
        self.press_glow = {}   # usage -> 0..1 extra glow
        self.lean = (0.0, 0.0)   # (yaw, pitch) offsets from the mouse
        self.light_pos = (0.5, 0.5)   # normalized light position

    def _build_keys(self):
        for gy, row in enumerate(LAYOUT):
            gx = 0.0
            for name, w in row:
                if name is None:
                    gx += w
                    continue
                usage = K.NAME_TO_USAGE.get(name)
                label = K.name_for_usage(usage) if usage else name.upper()
                self.keys.append(IsoKey(usage or 0, label, w, gx, gy))
                gx += w + self.GAP

    # ---- geometry -----------------------------------------------------
    YAW = math.radians(-7)      # slight sideways angle for dynamism
    PITCH = math.radians(62)    # how "from above" we look
    BOARD_W = 15.5              # units
    BOARD_H = 5 * 1.12          # units (5 rows, no F row)
    PLATE_PAD = 0.8             # chassis overhang beyond the keys

    def _camera(self):
        yaw = self.YAW + self.lean[0]
        pitch = self.PITCH + self.lean[1]
        return (math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch))

    def _metrics(self, W, H):
        cs, sn, cp, sp = self._camera()
        cx, cy = self.BOARD_W / 2, self.BOARD_H / 2
        pts = []
        for x in (0.0, self.BOARD_W):
            for y in (0.0, self.BOARD_H):
                dx, dy = x - cx, y - cy
                X1 = dx * cs - dy * sn
                Y1 = dx * sn + dy * cs
                pts.append((X1, Y1 * cp))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        unit = min((W * 0.94) / max(1e-6, w), (H * 0.84) / max(1e-6, h))
        # offsets to center the projected bbox
        self._ox = W / 2 - (min(xs) + max(xs)) / 2 * unit
        self._oy = H * 0.52 - (min(ys) + max(ys)) / 2 * unit
        return unit, cs, sn, cp, sp

    def _project(self, x, y, z, W, H, unit, cs, sn, cp, sp):
        """Camera: center board, yaw around Z, pitch around X."""
        dx = x - self.BOARD_W / 2
        dy = y - self.BOARD_H / 2
        X1 = dx * cs - dy * sn
        Y1 = dx * sn + dy * cs
        sy = Y1 * cp - z * sp
        return X1 * unit + self._ox, sy * unit + self._oy, Y1 * sp + z

    def _key_path(self, key, W, H, unit, cs, sn, cp, sp):
        """Extruded keycap: top face + front + right."""
        x0 = key.gx
        y0 = key.gy * 1.12
        x1 = x0 + key.w - self.GAP
        y1 = y0 + 1.0 - self.GAP
        zt = self.DEPTH
        d = 0.055                   # bevel inset on the top face

        P = lambda x, y, z: self._project(x, y, z, W, H, unit, cs, sn, cp, sp)
        top = [P(x0 + d, y0 + d, zt), P(x1 - d, y0 + d, zt),
               P(x1 - d, y1 - d, zt), P(x0 + d, y1 - d, zt)]
        front = [P(x0, y1, zt), P(x1, y1, zt), P(x1, y1, 0.0), P(x0, y1, 0.0)]
        right = [P(x1, y0, zt), P(x1, y1, zt), P(x1, y1, 0.0), P(x1, y0, 0.0)]
        return top, front, right

    # ---- painting ------------------------------------------------------
    def paint(self, p: QPainter, W, H, accent_a, accent_b, t):
        p.setRenderHint(QPainter.Antialiasing, True)
        self.plasma_t = t

        unit, cs, sn, cp, sp = self._metrics(W, H)

        self._paint_plasma(p, W, H, accent_a, accent_b)
        self._paint_floor_glow(p, W, H, accent_a)
        self._paint_chassis(p, W, H, unit, cs, sn, cp, sp)

        # paint back-to-front: rotate rows, farther (smaller rotated Y) first
        keys_sorted = sorted(self.keys, key=lambda k: k.gx * sn + (k.gy * 1.12) * cs)
        for key in keys_sorted:
            self._paint_key(p, key, W, H, unit, accent_a, cs, sn, cp, sp)

        # soft vignette to keep focus centered (gentle — the tall layout needs it)
        vign = QRadialGradient(QPointF(W * 0.5, H * 0.45), max(W, H) * 1.05)
        vign.setColorAt(0.0, QColor(0, 0, 0, 0))
        vign.setColorAt(1.0, QColor(0, 0, 0, 80))
        p.setBrush(QBrush(vign))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, 0, W, H))

    def _paint_plasma(self, p, W, H, accent_a, accent_b):
        """Three slow drifting radial glows behind the board."""
        for i, (color, spd, ph) in enumerate((
                (accent_a, 0.05, 0.0), (accent_b, 0.037, 2.1), (accent_a, 0.026, 4.4))):
            cx = W * (0.5 + 0.30 * math.sin(self.plasma_t * spd * 2 + ph))
            cy = H * (0.42 + 0.18 * math.cos(self.plasma_t * spd * 1.3 + ph * 1.7))
            r = max(W, H) * (0.34 + 0.05 * math.sin(self.plasma_t * 0.11 + ph))
            g = QRadialGradient(QPointF(cx, cy), r)
            col = QColor(color)
            col.setAlpha(38 if i != 2 else 26)
            g.setColorAt(0.0, col)
            col2 = QColor(color)
            col2.setAlpha(0)
            g.setColorAt(1.0, col2)
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), r, r)

    def _paint_chassis(self, p, W, H, unit, cs, sn, cp, sp):
        """Gunmetal base plate under the keycaps with a lit edge, corner
        screws and a mirrored reflection below."""
        pad = self.PLATE_PAD
        top_pts = [self._project(x, y, self.DEPTH * 0.55, W, H, unit, cs, sn, cp, sp)
                   for x, y in ((-pad, -pad), (self.BOARD_W + pad, -pad),
                                (self.BOARD_W + pad, self.BOARD_H + pad), (-pad, self.BOARD_H + pad))]
        bot_pts = [self._project(x, y, 0.0, W, H, unit, cs, sn, cp, sp)
                   for x, y in ((-pad, -pad), (self.BOARD_W + pad, -pad),
                                (self.BOARD_W + pad, self.BOARD_H + pad), (-pad, self.BOARD_H + pad))]

        def path_of(pts):
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            for pt in pts[1:]:
                path.lineTo(pt[0], pt[1])
            path.closeSubpath()
            return path

        # ---- mirrored reflection under the deck ----
        rp = QPainterPath()
        drop = (bot_pts[3][1] - top_pts[3][1]) * 1.6     # positive: below the deck
        rp.moveTo(bot_pts[3][0], bot_pts[3][1])
        rp.lineTo(bot_pts[2][0], bot_pts[2][1])
        rp.lineTo(bot_pts[2][0], bot_pts[2][1] + drop)
        rp.lineTo(bot_pts[3][0], bot_pts[3][1] + drop)
        rp.closeSubpath()
        rgrad = QLinearGradient(QPointF(bot_pts[3][0], bot_pts[3][1]),
                                QPointF(bot_pts[3][0], bot_pts[3][1] + drop))
        rgrad.setColorAt(0.0, QColor(90, 110, 135, 42))
        rgrad.setColorAt(1.0, QColor(20, 26, 36, 0))
        p.setBrush(QBrush(rgrad))
        p.setPen(Qt.NoPen)
        p.drawPath(rp)

        # side wall (front) — brushed steel
        wall = QPainterPath()
        wall.moveTo(top_pts[3][0], top_pts[3][1])
        wall.lineTo(top_pts[2][0], top_pts[2][1])
        wall.lineTo(bot_pts[2][0], bot_pts[2][1])
        wall.lineTo(bot_pts[3][0], bot_pts[3][1])
        wall.closeSubpath()
        grad = QLinearGradient(QPointF(bot_pts[3][0], bot_pts[3][1]), QPointF(top_pts[3][0], top_pts[3][1]))
        grad.setColorAt(0.0, QColor(6, 8, 11))
        grad.setColorAt(0.5, QColor(14, 17, 23))
        grad.setColorAt(0.52, QColor(44, 52, 66))   # brushed edge catch-light
        grad.setColorAt(0.56, QColor(20, 24, 32))
        grad.setColorAt(1.0, QColor(40, 47, 60))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(0, 0, 0, 110), 1))
        p.drawPath(wall)

        # right wall
        wall2 = QPainterPath()
        wall2.moveTo(top_pts[1][0], top_pts[1][1])
        wall2.lineTo(top_pts[2][0], top_pts[2][1])
        wall2.lineTo(bot_pts[2][0], bot_pts[2][1])
        wall2.lineTo(bot_pts[1][0], bot_pts[1][1])
        wall2.closeSubpath()
        grad2 = QLinearGradient(QPointF(bot_pts[1][0], bot_pts[1][1]), QPointF(top_pts[1][0], top_pts[1][1]))
        grad2.setColorAt(0.0, QColor(5, 6, 9))
        grad2.setColorAt(1.0, QColor(28, 33, 42))
        p.setBrush(QBrush(grad2))
        p.drawPath(wall2)

        # top deck
        deck = QLinearGradient(QPointF(top_pts[0][0], top_pts[0][1]), QPointF(top_pts[3][0], top_pts[3][1]))
        deck.setColorAt(0.0, QColor(16, 19, 26))
        deck.setColorAt(0.55, QColor(24, 28, 37))
        deck.setColorAt(1.0, QColor(13, 15, 21))
        p.setBrush(QBrush(deck))
        p.setPen(QPen(QColor(90, 105, 125, 90), 1.4))
        p.drawPath(path_of(top_pts))

        # deck sheen band (reflection of the environment carrying color)
        sheen = QLinearGradient(QPointF(top_pts[0][0], top_pts[1][1]), QPointF(top_pts[3][0], top_pts[3][1]))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.5, QColor(140, 170, 200, 26))
        sheen.setColorAt(0.52, QColor(200, 220, 245, 40))
        sheen.setColorAt(0.54, QColor(120, 150, 190, 20))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.setPen(Qt.NoPen)
        p.drawPath(path_of(top_pts))

        # hex screws in the corners (metalheart hardware detail)
        for cx, cy in ((top_pts[0][0] + 12, top_pts[0][1] + 14),
                       (top_pts[1][0] - 12, top_pts[1][1] + 14),
                       (top_pts[3][0] + 12, top_pts[3][1] - 14),
                       (top_pts[2][0] - 12, top_pts[2][1] - 14)):
            r = max(3.0, unit * 0.05)
            p.setBrush(QColor(70, 80, 95))
            p.setPen(QPen(QColor(150, 165, 185, 130), 1))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(QColor(20, 24, 32, 170), max(1.0, r * 0.35)))
            p.drawLine(QPointF(cx - r * 0.6, cy), QPointF(cx + r * 0.6, cy))

    def _paint_floor_glow(self, p, W, H, accent):
        grad = QLinearGradient(QPointF(0, H * 0.78), QPointF(0, H))
        c = QColor(accent)
        c.setAlpha(26)
        grad.setColorAt(0.0, c)
        c2 = QColor(accent)
        c2.setAlpha(0)
        grad.setColorAt(1.0, c2)
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, H * 0.78, W, H * 0.22))

    def _paint_key(self, p, key, W, H, unit, accent, cs, sn, cp, sp):
        color = self.colors.get(key.usage)
        if color is None:
            rgb = (18, 20, 26)
        else:
            rgb = color
        top, front, right = self._key_path(key, W, H, unit, cs, sn, cp, sp)

        # reactive press glow underneath
        glow = self.press_glow.get(key.usage, 0.0)
        if glow > 0.01:
            cx = sum(pt[0] for pt in top) / 4.0
            cy = sum(pt[1] for pt in top) / 4.0
            gr = QRadialGradient(QPointF(cx, cy), unit * 1.4 * (0.5 + glow))
            gc = QColor(accent)
            gc.setAlpha(int(90 * glow))
            gr.setColorAt(0.0, gc)
            gc2 = QColor(accent)
            gc2.setAlpha(0)
            gr.setColorAt(1.0, gc2)
            p.setBrush(QBrush(gr))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), unit * 1.4 * (0.5 + glow), unit * 1.4 * (0.5 + glow))

        # side faces (darker, always)
        base = QColor(*rgb)
        front_col = QColor(max(0, rgb[0] * 0.45), max(0, rgb[1] * 0.45), max(0, rgb[2] * 0.5))
        right_col = QColor(max(0, rgb[0] * 0.30), max(0, rgb[1] * 0.30), max(0, rgb[2] * 0.35))
        if color is None:
            front_col = QColor(12, 14, 18)
            right_col = QColor(9, 10, 13)

        for pts, col in ((front, front_col), (right, right_col)):
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            for pt in pts[1:]:
                path.lineTo(pt[0], pt[1])
            path.closeSubpath()
            p.setBrush(QBrush(col))
            p.setPen(QPen(QColor(0, 0, 0, 90), 1))
            p.drawPath(path)

        # top face with a subtle vertical sheen
        grad = QLinearGradient(top[0][0], top[0][1], top[2][0], top[2][1])
        c_hi = QColor(min(255, rgb[0] + 24), min(255, rgb[1] + 24), min(255, rgb[2] + 24))
        grad.setColorAt(0.0, c_hi)
        grad.setColorAt(1.0, base)
        path = QPainterPath()
        path.moveTo(top[0][0], top[0][1])
        for pt in top[1:]:
            path.lineTo(pt[0], pt[1])
        path.closeSubpath()
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawPath(path)

        # chrome specular sweep: a bright diagonal band that follows the light
        lx, ly = self.light_pos
        cx = sum(pt[0] for pt in top) / 4.0
        cy = sum(pt[1] for pt in top) / 4.0
        d = ((cx / max(1, W)) - lx) * 1.4 + ((cy / max(1, H)) - ly) * 1.0
        band = max(0.0, 1.0 - abs(d - 0.15) * 3.2)
        if band > 0.01:
            sweep = QLinearGradient(top[0][0], top[0][1], top[2][0], top[2][1])
            a1 = int(70 * band)
            sweep.setColorAt(0.0, QColor(255, 255, 255, 0))
            sweep.setColorAt(0.48, QColor(255, 255, 255, a1))
            sweep.setColorAt(0.52, QColor(255, 255, 255, int(a1 * 1.5)))
            sweep.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(sweep))
            p.setPen(Qt.NoPen)
            p.drawPath(path)

        # label with a soft shadow for legibility
        if key.usage != K.NAME_TO_USAGE.get("space") and unit > 16:
            cx = sum(pt[0] for pt in top) / 4.0
            cy = sum(pt[1] for pt in top) / 4.0
            lum = rgb[0] * 0.3 + rgb[1] * 0.6 + rgb[2] * 0.1
            f = p.font()
            f.setPixelSize(max(8, int(unit * 0.16)))
            f.setBold(False)
            p.setFont(f)
            # legend glow: key colour bled into the label
            glow_col = QColor(min(255, rgb[0] + 60), min(255, rgb[1] + 60), min(255, rgb[2] + 60), 110)
            p.setPen(QPen(glow_col))
            p.drawText(QRectF(cx - unit - 1, cy - unit * 0.5 - 1, unit * 2, unit), Qt.AlignCenter, key.label)
            p.setPen(QPen(QColor(0, 0, 0, 150)))
            p.drawText(QRectF(cx - unit + 1, cy - unit * 0.5 + 1, unit * 2, unit), Qt.AlignCenter, key.label)
            col = QColor(235, 242, 250, 110 if lum < 90 else 215)
            p.setPen(QPen(col))
            p.drawText(QRectF(cx - unit, cy - unit * 0.5, unit * 2, unit), Qt.AlignCenter, key.label)

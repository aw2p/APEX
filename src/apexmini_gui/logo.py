#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Procedural Metalheart butterfly logo — liquid chrome shards, no assets.

Rendered with plain QPainter: mirrored wing pairs built from tapered chrome
blades (the same silhouette language as the background shard field), chrome
gradients, lens-flare dots, grain.  Usable at any size:

    from apexmini_gui import logo
    pix = logo.render(512)          # QPixmap 512x512
    icon = logo.icon()              # QIcon for window/tray
"""

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)


def _wing_path(side, scale, upper, seed):
    """One wing: angular shard blade with a notch cut into the trailing edge."""
    sgn = 1.0 if side > 0 else -1.0
    path = QPainterPath()
    if upper:
        tipx, tipy = sgn * 2.75 * scale, -2.35 * scale
        c1 = (sgn * 0.9 * scale, -1.75 * scale)
        mid2 = (sgn * 1.75 * scale, -0.05 * scale)
        mid = (sgn * 1.35 * scale, -0.5 * scale)
        root = (sgn * 0.06 * scale, -0.2 * scale)
    else:
        tipx, tipy = sgn * 2.3 * scale, 2.15 * scale
        c1 = (sgn * 0.8 * scale, 1.35 * scale)
        mid2 = (sgn * 1.6 * scale, 0.12 * scale)
        mid = (sgn * 1.25 * scale, 0.55 * scale)
        root = (sgn * 0.06 * scale, 0.2 * scale)

    path.moveTo(*root)
    # leading edge: one aggressive sweep to the tip
    path.quadTo(c1[0], c1[1], tipx, tipy)
    # trailing edge: angular, with a notch (shard cut)
    path.lineTo(mid2[0], mid2[1])
    path.lineTo(mid[0], mid[1])
    path.quadTo(sgn * 0.8 * scale, (0.25 if upper else 0.05) * scale,
                root[0], root[1])
    path.closeSubpath()
    return path


def _paint_chrome(p, path, rect, hue_shift=0.0, seed=1):
    """Fill a path with vertical chrome bands + horizon white + accent."""
    r = rect
    grad = QLinearGradient(r.left(), r.top(), r.right(), r.bottom())
    grad.setColorAt(0.00, QColor("#02040a"))
    grad.setColorAt(0.28, QColor("#1c3346"))
    grad.setColorAt(0.47, QColor("#e8f2fa"))
    grad.setColorAt(0.54, QColor("#5f7d95"))
    grad.setColorAt(0.72, QColor("#0a2537"))
    grad.setColorAt(1.00, QColor("#01030a"))
    p.fillPath(path, QBrush(grad))
    # specular streaks (baked 3D bevel feel)
    p.save()
    p.setClipRect(r)
    streak = QLinearGradient(r.left(), r.top(), r.right(), r.bottom())
    streak.setColorAt(0.0, QColor(255, 255, 255, 0))
    streak.setColorAt(0.5, QColor(255, 255, 255, 90))
    streak.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path, QBrush(streak))
    p.restore()


def render(size=512, bg=True):
    """Return a QPixmap of the butterfly logo at `size`x`size`."""
    pix = QPixmap(size, size)
    pix.fill(QColor("#05070b") if bg else Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    S = size
    scale = S / 6.2
    cx, cy = S * 0.5, S * 0.52

    # ---- ambient glow behind the wings ----
    glow = QRadialGradient(cx, cy, S * 0.5)
    glow.setColorAt(0.0, QColor(40, 90, 130, 70))
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setBrush(glow)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(cx, cy), S * 0.5, S * 0.5)

    # ---- wings: two pairs per side, mirrored (local coords around body) ----
    p.save()
    p.translate(cx, cy)
    for upper in (True, False):
        for side in (-1, 1):
            path = _wing_path(side, scale, upper, seed=hash((side, upper)) % 1000)
            _paint_chrome(p, path, QRectF(-S / 2, -S / 2, S, S))
            # bevel edge
            p.setPen(QPen(QColor(220, 235, 248, 170), max(1.0, S * 0.004)))
            p.drawPath(path)
            # inner shard line (fake 3D crease)
            p.setPen(QPen(QColor(255, 255, 255, 90), max(1.0, S * 0.003)))
            inner = QPainterPath()
            k = 0.55 if upper else 0.5
            inner.moveTo(side * 0.15 * scale, -(0.1 if upper else -0.1) * scale)
            inner.cubicTo(side * 1.0 * scale, -1.2 * scale * k,
                          side * 1.7 * scale, -1.0 * scale * k,
                          side * (2.2 if upper else 1.9) * scale, -(1.6 if upper else 1.1) * scale * k)
            p.drawPath(inner)
    p.restore()

    # ---- body: liquid chrome teardrop ----
    body = QPainterPath()
    body.moveTo(cx, cy - 1.05 * scale)
    body.quadTo(cx + 0.34 * scale, cy, cx, cy + 1.5 * scale)
    body.quadTo(cx - 0.34 * scale, cy, cx, cy - 1.05 * scale)
    body.closeSubpath()
    bgrad = QLinearGradient(cx - 0.3 * scale, cy - scale, cx + 0.3 * scale, cy + scale)
    bgrad.setColorAt(0.0, QColor("#e8f1f8"))
    bgrad.setColorAt(0.45, QColor("#5d7285"))
    bgrad.setColorAt(0.6, QColor("#10161d"))
    bgrad.setColorAt(1.0, QColor("#0a2d44"))
    p.fillPath(body, QBrush(bgrad))
    p.setPen(QPen(QColor(230, 242, 250, 190), max(1.0, S * 0.004)))
    p.drawPath(body)

    # ---- antennae ----
    for side in (-1, 1):
        ant = QPainterPath()
        ant.moveTo(cx, cy - 1.0 * scale)
        ant.quadTo(cx + side * 0.5 * scale, cy - 1.6 * scale,
                   cx + side * 0.95 * scale, cy - 2.05 * scale)
        p.setPen(QPen(QColor("#9fb4c6"), max(1.4, S * 0.006)))
        p.drawPath(ant)
        p.setBrush(QColor("#dfe9f2"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx + side * 0.98 * scale, cy - 2.08 * scale),
                      S * 0.018, S * 0.018)

    # ---- lens flare dots ----
    for fx, fy, fr in ((0.24, 0.3, 0.05), (0.78, 0.62, 0.04), (0.6, 0.22, 0.028)):
        g = QRadialGradient(QPointF(S * fx, S * fy), S * fr)
        g.setColorAt(0.0, QColor(255, 255, 255, 220))
        g.setColorAt(0.35, QColor(120, 200, 255, 90))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(S * fx, S * fy), S * fr, S * fr)

    # ---- film grain ----
    rng = random.Random(7)
    p.setPen(Qt.NoPen)
    for _ in range(int(S * S / 900)):
        a = rng.randint(0, 26)
        p.setBrush(QColor(255, 255, 255, a) if rng.random() > 0.5 else QColor(0, 0, 0, a))
        p.drawRect(QRectF(rng.random() * S, rng.random() * S, 1.2, 1.2))

    p.end()
    return pix


def icon(size=256):
    from PySide6.QtGui import QIcon
    return QIcon(render(size))


if __name__ == "__main__":
    import os
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    out = sys.argv[1] if len(sys.argv) > 1 else "docs/assets/logo.png"
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 512
    render(size).save(out)
    print("saved", out)

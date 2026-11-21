#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the stylized (painter) keyboard running a profile into an
animated GIF — the README preview.

    python tools/spawn.py venv-qt/bin/python tools/make_preview_gif.py \
        docs/assets/preview.gif candle 48
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRadialGradient, QLinearGradient, QBrush
from PySide6.QtWidgets import QApplication

from apexmini import engine as EN
from apexmini import profiles as PR
from apexmini_gui import keyboard3d as K3


def frame_image(W, H):
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor("#05070b"))
    return img


def paint_backdrop(p, W, H, t, accent):
    """Simplified liquid-metal-ish backdrop (fast, painter)."""
    # vertical chrome gradient with a horizon band
    grad = QLinearGradient(0, 0, 0, H)
    grad.setColorAt(0.0, QColor("#04060a"))
    grad.setColorAt(0.55, QColor("#0b1119"))
    grad.setColorAt(0.62, QColor("#5d7488"))
    grad.setColorAt(0.66, QColor("#c9d6e2"))
    grad.setColorAt(0.74, QColor("#1a212c"))
    grad.setColorAt(1.0, QColor("#020407"))
    p.fillRect(0, 0, W, H, grad)
    # drifting glow blobs
    for i in range(3):
        x = W * (0.3 + 0.2 * i) + math.sin(t * 0.35 + i * 2.1) * W * 0.07
        y = H * 0.4 + math.cos(t * 0.27 + i * 1.7) * H * 0.08
        r = min(W, H) * (0.22 + 0.06 * i)
        g = QRadialGradient(x, y, r)
        c = QColor(accent)
        c.setAlpha(34)
        g.setColorAt(0.0, c)
        c2 = QColor(accent)
        c2.setAlpha(0)
        g.setColorAt(1.0, c2)
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, y), r, r)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "docs/assets/preview.gif"
    profile_name = sys.argv[2] if len(sys.argv) > 2 else "candlelight"
    frames_n = int(sys.argv[3]) if len(sys.argv) > 3 else 48
    fps = 20
    W, H = 800, 450

    app = QApplication.instance() or QApplication([])
    try:
        prof = PR.load(profile_name)
    except (OSError, ValueError):
        prof = PR.new_profile(profile_name, "candle", ["#ff6a00", "#ff2b00"])
    eng = EN.Engine(prof)
    k3d = K3.Keyboard3DPreview(None)

    from PySide6.QtGui import QPixmap
    from PIL import Image

    pil_frames = []
    for i in range(frames_n):
        t = i / fps * 4.0          # candle period ~ 4s per loop segment
        img = frame_image(W, H)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        aa, ab = "#ff9a3c", "#ff3c14"
        paint_backdrop(p, W, H, t, aa)
        k3d.colors = eng.colors(t)
        k3d.lean = (math.sin(t * 0.5) * 0.05, 0.0)
        k3d.light_pos = (0.35 + 0.1 * math.sin(t * 0.4), 0.45)
        k3d.paint(p, W, H, aa, ab, t)
        p.end()
        # QImage → PIL
        img.save("/tmp/opencode/_gif_frame.png")
        pil_frames.append(Image.open("/tmp/opencode/_gif_frame.png").convert("P",
            palette=Image.ADAPTIVE).convert("RGB"))

    # adaptive palette from a blend of several frames, dithered conversion
    blend = Image.new("RGB", (W, H))
    step = max(1, len(pil_frames) // 6)
    for k, idx in enumerate(range(0, len(pil_frames), step)[:6]):
        blend = Image.blend(blend, pil_frames[idx], 1.0 / (k + 1))
    pal_img = blend.quantize(colors=255, method=Image.MEDIANCUT)
    gif_frames = [f.convert("P", palette=pal_img, dither=Image.FLOYDSTEINBERG)
                  for f in pil_frames]
    gif_frames[0].save(
        out, save_all=True, append_images=gif_frames[1:],
        duration=int(1000 / fps), loop=0, optimize=True)
    print("saved", out, len(gif_frames), "frames")


if __name__ == "__main__":
    main()

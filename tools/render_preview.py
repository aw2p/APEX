#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick offscreen renderer: builds the 3D preview into a PNG so the visuals
can be iterated without a display (agent-side).  Also handy for the user:
`python tools/render_preview.py out.png [profile.json]`
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QBuffer, QByteArray  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from apexmini import engine as EN, profiles as PR  # noqa: E402
from apexmini_gui import keyboard3d as K3  # noqa: E402
from apexmini_gui import theme  # noqa: E402


def render(out_path, profile, t=1.7, W=1180, H=640, press=None):
    app = QApplication.instance() or QApplication([])
    eng = EN.Engine(profile)
    prev = K3.Keyboard3DPreview(None)
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(theme.DARK_BG))
    p = QPainter(img)
    aa, ab = theme.accents_for_profile(profile)
    if press:
        for u in press:
            prev.press_glow[u] = 0.9
            eng.note_press(u)
    prev.colors = eng.colors(t)
    prev.paint(p, W, H, aa, ab, t)
    p.end()
    img.save(out_path)
    print("saved", out_path)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    out = args[0] if args and args[0].endswith(".png") else "/tmp/opencode/preview.png"
    rest = args[1:] if args and args[0].endswith(".png") else args
    prof = None
    press = []
    for a in rest:
        if a.endswith(".json"):
            prof = PR.load(a)
        else:
            press.append(K3.K.NAME_TO_USAGE.get(a.casefold(), 0))
    if prof is None:
        prof = PR.new_profile("demo", "candle", ["#ff6a00", "#ff2b00"], reactive=True)
    press = [u for u in press if u]
    render(out, prof, press=press)

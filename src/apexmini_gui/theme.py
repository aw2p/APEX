#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metalheart / Neo-Vectorheart theme.

Palette + runtime-adaptive QSS.  Base surfaces are gunmetal chrome (dark,
slightly blue), with bevelled panel edges via QSS gradients.  Two neon
accents (cyan / magenta) form the vectorheart layer; when a profile is
active the accent pair is re-derived from its base colours so the UI
breathes with the keyboard.
"""

DARK_BG = "#0a0d12"
PANEL_BG = "#11151d"
PANEL_BG2 = "#171c26"
PANEL_HI = "#20262f"
EDGE = "#323a47"
EDGE_HI = "#4a5666"
TEXT = "#c8d3e0"
TEXT_DIM = "#6b7684"

CYAN = "#22d3ee"
MAGENTA = "#ff2bd6"

# fallback accent pair when no profile is loaded
ACCENT_A = CYAN
ACCENT_B = MAGENTA


def _lighten(hex_color, amount):
    """Blend a colour toward white by `amount` (0..1)."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return "#%02x%02x%02x" % (r, g, b)


def _desat(hex_color, amount):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    lum = (r * 299 + g * 587 + b * 114) // 1000
    r = int(r + (lum - r) * amount)
    g = int(g + (lum - g) * amount)
    b = int(b + (lum - b) * amount)
    return "#%02x%02x%02x" % (r, g, b)


def accents_for_profile(profile):
    """Adaptive accent pair: primary = brightest base colour (lightened for
    contrast), secondary = complement-ish second colour or magenta."""
    import colorsys
    cols = [c for c in (profile.get("base", {}).get("colors") or []) if isinstance(c, str)]
    if not cols or not all(len(c) >= 7 and c.startswith("#") for c in cols):
        return ACCENT_A, ACCENT_B
    def lum(c):
        return int(c[1:3], 16) * 2 + int(c[3:5], 16) * 5 + int(c[5:7], 16)
    ordered = sorted(cols, key=lum, reverse=True)
    a = _lighten(_desat(ordered[0], 0.15), 0.35)
    if len(ordered) > 1:
        b = _lighten(_desat(ordered[1], 0.15), 0.25)
        # ensure b differs enough from a
        if b.lower() == a.lower():
            h = colorsys.rgb_to_hls(int(ordered[0][1:3], 16) / 255,
                                    int(ordered[0][3:5], 16) / 255,
                                    int(ordered[0][5:7], 16) / 255)[0]
            b = "#%02x%02x%02x" % tuple(int(x * 255) for x in colorsys.hls_to_rgb((h + 0.5) % 1.0, 0.6, 0.9))
    else:
        h = colorsys.rgb_to_hls(int(ordered[0][1:3], 16) / 255,
                                int(ordered[0][3:5], 16) / 255,
                                int(ordered[0][5:7], 16) / 255)[0]
        b = "#%02x%02x%02x" % tuple(int(x * 255) for x in colorsys.hls_to_rgb((h + 0.5) % 1.0, 0.6, 0.9))
    return a, b


def build_qss(accent_a=ACCENT_A, accent_b=ACCENT_B):
    aa, ab = accent_a, accent_b
    aa_dim = _desat(aa, 0.55)
    ab_dim = _desat(ab, 0.55)
    return f"""
* {{
    background: {PANEL_BG};
    color: {TEXT};
    font-family: "Inter", "Noto Sans", sans-serif;
    font-size: 13px;
    selection-background-color: {aa_dim};
    selection-color: {DARK_BG};
}}
QMainWindow, QWidget#root {{ background: {DARK_BG}; }}
QFrame#panel {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {PANEL_BG2}, stop:1 {PANEL_BG});
    border: 1px solid {EDGE};
    border-top-color: {EDGE_HI};
    border-left-color: {EDGE_HI};
    border-radius: 6px;
}}
QLabel {{ background: transparent; }}
QLabel#title {{
    color: {aa};
    font-weight: 600;
    letter-spacing: 2px;
    font-size: 15px;
    background: transparent;
}}
QLabel#subtitle {{ color: {TEXT_DIM}; font-size: 11px; background: transparent; }}
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {PANEL_HI}, stop:1 {PANEL_BG2});
    border: 1px solid {EDGE};
    border-radius: 5px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{
    border: 1px solid {aa_dim};
    color: {aa};
}}
QPushButton:pressed {{ background: {PANEL_BG}; }}
QPushButton#primary {{
    border: 1px solid {aa};
    color: {aa};
    font-weight: 600;
}}
QPushButton#danger:hover {{ border: 1px solid {ab}; color: {ab}; }}
QLineEdit {{
    background: {DARK_BG};
    border: 1px solid {EDGE};
    border-radius: 4px;
    padding: 6px 8px;
}}
QLineEdit:focus {{ border: 1px solid {aa_dim}; }}
QComboBox {{
    background: {PANEL_BG2};
    border: 1px solid {EDGE};
    border-radius: 4px;
    padding: 5px 10px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL_BG2};
    border: 1px solid {EDGE_HI};
    selection-background-color: {aa_dim};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {DARK_BG};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {aa_dim}, stop:1 {aa});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {PANEL_HI};
    border: 1px solid {aa};
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QListWidget {{
    background: {DARK_BG};
    border: 1px solid {EDGE};
    border-radius: 5px;
    padding: 4px;
}}
QListWidget::item {{ padding: 7px 10px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {aa_dim}; color: {DARK_BG}; }}
QListWidget::item:hover {{ background: {PANEL_HI}; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {EDGE_HI};
    border-radius: 3px;
    background: {DARK_BG};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {aa}, stop:1 {ab});
    border: 1px solid {aa};
}}
QStatusBar {{ background: {PANEL_BG}; border-top: 1px solid {EDGE}; }}
QToolTip {{
    background: {PANEL_BG2};
    color: {TEXT};
    border: 1px solid {aa_dim};
    padding: 4px;
}}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {EDGE_HI}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Procedural Metalheart background (GLSL).

Liquid-metal chrome field with aggressive voronoi bevels, a chrome horizon
band, anamorphic lens flare, perspective grid "beams" on the ground and film
grain — all in one fragment shader.  White/black/blue palette with two
adaptive accent uniforms.  Mouse drives a subtle parallax + light position
(the 'lean' the keyboard overlay mirrors).

Falls back to a painter-drawn gradient when GL is unavailable.
"""

import math
import os

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PySide6.QtWidgets import QWidget
from PySide6.QtOpenGLWidgets import QOpenGLWidget

VERT_SRC = """
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

FRAG_SRC = """
#ifdef GL_ES
precision highp float;
#endif
varying vec2 v_uv;
uniform vec2  u_res;
uniform float u_time;
uniform vec2  u_mouse;      // 0..1
uniform vec3  u_accentA;
uniform vec3  u_accentB;
uniform float u_intensity;  // 0..1 overall brightness of the field

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i), b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = rot * p * 2.03 + 11.7;
        a *= 0.5;
    }
    return v;
}
vec2 voronoi(vec2 p) {
    vec2 n = floor(p), f = fract(p);
    float d1 = 8.0, d2 = 8.0;
    for (int j = -1; j <= 1; j++)
    for (int i = -1; i <= 1; i++) {
        vec2 g = vec2(float(i), float(j));
        vec2 o = vec2(hash(n + g), hash(n + g + 19.19));
        float d = length(g + o - f);
        if (d < d1) { d2 = d1; d1 = d; }
        else if (d < d2) { d2 = d; }
    }
    return vec2(d1, d2 - d1);
}

float fbm_at(vec2 p) {
    vec2 q = vec2(fbm(p * 1.3 + u_time * 0.05),
                  fbm(p * 1.3 - u_time * 0.04 + 4.7));
    return fbm(p * 2.1 + q * 1.7 + vec2(u_time * 0.02, -u_time * 0.03));
}

// chrome environment lookup by a "reflection height" in [-1, 1]
vec3 chrome_env(float m, float f) {
    vec3 env = mix(vec3(0.010, 0.016, 0.032), vec3(0.36, 0.46, 0.58), smoothstep(0.05, 0.52, m));
    env = mix(env, vec3(0.92, 0.95, 0.98), pow(max(0.0, 1.0 - abs(m - 0.60) * 4.5), 7.0));
    env += u_accentA * pow(max(0.0, 1.0 - abs(m - 0.78) * 7.0), 6.0) * 0.55;
    env += u_accentB * pow(max(0.0, 1.0 - abs(m - 0.36) * 8.0), 6.0) * 0.40;
    return env * (0.30 + 0.85 * f);
}

// ---- angular shard blades ------------------------------------------
// tapered blade SDF: p in blade-local space; returns signed distance
float blade_sd(vec2 p, float len, float w) {
    float x = p.x, y = p.y;
    // slight curve
    y += 0.25 * x * x / max(len, 0.001);
    float dx = max(abs(x) - len, 0.0);
    return length(vec2(dx, y * 3.2)) - w;
}

// shade one blade: chrome with bevel crest; returns (color, coverage)
vec4 blade(vec2 p, float idx) {
    float t = u_time * 0.05;
    float ang = idx * 2.399 + t * (0.35 + 0.11 * hash(vec2(idx, 1.0)))   // golden-angle fan
                + sin(t * 0.7 + idx) * 0.06
                + (u_mouse.x - 0.5) * 0.35;                              // lean with mouse
    float ca = cos(ang), sa = sin(ang);
    vec2 c = vec2(0.0, -0.02) + 0.05 * vec2(sin(t * 0.23 + idx * 2.0), cos(t * 0.19 + idx));
    vec2 lp = p - c;
    lp = mat2(ca, -sa, sa, ca) * lp;
    float len = 0.55 + 0.35 * hash(vec2(idx, 7.0)) + 0.08 * sin(t * 0.4 + idx * 3.0);
    float w = 0.010 + 0.028 * hash(vec2(idx, 13.0));
    float sd = blade_sd(lp, len, w);
    if (sd > 0.02) return vec4(0.0);
    float cov = smoothstep(0.02, 0.0, sd);

    // fake normal: blade is a beveled prism — crest along its length
    float crest = smoothstep(w * 1.6, 0.0, abs(lp.y));
    float m = mix(0.15 + 0.55 * fbm(lp * 9.0 + idx), 0.62, crest);        // reflection height
    vec3 col = chrome_env(m, fbm(lp * 6.0 + idx * 3.0));

    // hard bevel edges (aggressive): bright rim at the sides, dark just inside
    float rim = smoothstep(w, w * 0.55, abs(lp.y)) * smoothstep(w * 0.55, w * 0.35, abs(lp.y));
    col += vec3(1.0) * rim * 0.85;
    col *= 1.0 - 0.35 * smoothstep(w * 0.5, w * 0.45, abs(lp.y));

    // mouse-driven specular sweep
    vec3 L = normalize(vec3((u_mouse.x - 0.5) * 2.0 + 0.3 * sin(u_time * 0.17), 0.7, 0.8));
    col += vec3(1.0) * pow(max(0.0, 1.0 - abs(lp.y) / w), 8.0) * 0.25
         * (0.4 + 0.6 * abs(sin(ang + (u_mouse.x - 0.5) * 3.0)));

    return vec4(col, cov);
}

void main() {
    vec2 uv = v_uv;
    float aspect = u_res.x / max(1.0, u_res.y);
    vec2 p = (uv - vec2(0.5, 0.46)) * vec2(aspect, 1.0);
    p += (u_mouse - 0.5) * 0.05;             // mouse parallax

    // ---- liquid chrome field + fake normal ----
    float e = 0.018;
    float f  = fbm_at(p * 0.8);
    float fx = fbm_at(p * 0.8 + vec2(e, 0.0));
    float fy = fbm_at(p * 0.8 + vec2(0.0, e));
    vec3 n = normalize(vec3((f - fx) / e, (f - fy) / e, 1.4));

    vec3 view = normalize(vec3(p * 0.35, 1.6));
    vec3 refl = reflect(-view, n);
    float m = clamp(refl.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 col = chrome_env(m, f);

    // moving specular (follows mouse = the 'lean' light)
    vec3 L = normalize(vec3((u_mouse.x - 0.5) * 2.2 + sin(u_time * 0.13) * 0.35,
                            0.55 + (u_mouse.y - 0.5) * 1.2, 0.75));
    float spec = pow(max(dot(n, normalize(L + view)), 0.0), 42.0);
    col += vec3(1.0, 1.0, 1.05) * spec * 1.2;

    // ---- aggressive voronoi bevels (background texture) ----
    vec2 vcell = voronoi(p * 3.1);
    float edge = vcell.y;
    col += vec3(0.9, 0.95, 1.0) * smoothstep(0.14, 0.02, edge) * 0.22;
    col *= 1.0 - 0.45 * smoothstep(0.012, 0.0, edge);

    // ---- the shard burst: one large object at center ----
    // (the burst lives behind the keyboard overlay: shifted left & low)
    vec2 bp = (p - vec2(-0.18, -0.10)) / vec2(aspect * 0.92, 1.0) * 1.6;
    for (int i = 0; i < 9; i++) {
        vec4 bl = blade(bp, float(i));
        col = mix(col, bl.rgb, bl.a);
    }

    // ---- ground grid + beams (vectorheart) ----
    if (uv.y < 0.56) {
        float depth = 1.0 / max(0.04, (0.56 - uv.y));
        vec2 g = vec2((uv.x - 0.5) * aspect * depth * 0.55, depth * 0.5 + u_time * 0.02);
        vec2 gr = abs(fract(g) - 0.5);
        float line = smoothstep(0.46, 0.5, max(gr.x, gr.y));
        float fade = smoothstep(0.56, 0.30, uv.y);
        col = mix(col, u_accentA * 0.85 + col * 0.35, line * fade * 0.16);
    }

    // ---- anamorphic lens flare ----
    vec2 fp = vec2(0.34 + 0.05 * sin(u_time * 0.11), 0.60);
    float streak = exp(-abs((uv.y - fp.y) * 90.0)) * exp(-abs((uv.x - fp.x) * 2.4));
    float core = 1.0 / (1.0 + dot(uv - fp, uv - fp) * 900.0);
    col += (vec3(0.9, 0.95, 1.0) * streak * 0.22 + u_accentA * streak * 0.18 + vec3(1.0) * core * 0.25) * u_intensity;

    // vignette + film grain (keep the rawness)
    float vig = smoothstep(1.15, 0.30, length((uv - vec2(0.5, 0.45)) * vec2(aspect * 0.75, 1.0)));
    col *= 0.35 + 0.65 * vig;
    col += (hash(uv * u_res + fract(u_time)) - 0.5) * 0.035;

    col *= u_intensity;
    gl_FragColor = vec4(col, 1.0);
}
"""


class LiquidMetalBackground(QOpenGLWidget):
    """Fullscreen procedural GL background.  `accentChanged(a, b)` repaints."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prog = None
        self._t0 = 0.0
        self._mouse = (0.5, 0.45)
        self._accents = (0.15, 0.85, 0.95), (0.95, 0.20, 0.80)
        self._intensity = 1.0
        self.setMouseTracking(True)
        fmt = QSurfaceFormat()
        fmt.setSamples(0)
        self.setFormat(fmt)
        self._timer = QTimer(self)
        self._timer.setInterval(33)          # ~30 fps is plenty for a backdrop
        self._timer.timeout.connect(self.update)
        self._timer.start()

    # -- API ---------------------------------------------------------
    def set_accents(self, a_hex, b_hex):
        self._accents = (_hex2rgb(a_hex), _hex2rgb(b_hex))
        self.update()

    def set_intensity(self, v):
        self._intensity = max(0.0, min(1.4, v))

    # -- GL plumbing ---------------------------------------------------
    def initializeGL(self):
        self._prog = QOpenGLShaderProgram(self)
        ok = self._prog.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT_SRC)
        ok = ok and self._prog.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG_SRC)
        if not ok:
            QTimer.singleShot(0, self._swap_to_fallback)
            return
        self._prog.bindAttributeLocation("a_pos", 0)
        self._prog.link()
        self._prog.bind()
        self._u = {n: self._prog.uniformLocation(n) for n in
                   ("u_res", "u_time", "u_mouse", "u_accentA", "u_accentB", "u_intensity")}
        self._prog.release()
        self._t0 = 0.0

        from PySide6.QtOpenGL import QOpenGLBuffer
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._vbo.bind()
        import array
        verts = array.array("f", [
            -1.0, -1.0, 1.0, -1.0, 1.0, 1.0,
            -1.0, -1.0, 1.0, 1.0, -1.0, 1.0,
        ])
        self._vbo.allocate(verts.tobytes(), len(verts) * 4)
        self._vbo.release()

    def _swap_to_fallback(self):
        """Replace ourselves with the painter fallback if GL let us down."""
        parent = self.parentWidget()
        if parent is None:
            return
        fb = PainterFallbackBackground()
        fb.set_accents("#%02x%02x%02x" % tuple(int(c * 255) for c in self._accents[0]),
                       "#%02x%02x%02x" % tuple(int(c * 255) for c in self._accents[1]))
        # swap z-order and geometry with the current stacking
        geo = self.geometry()
        idx = parent.layout().indexOf(self) if parent.layout() else -1
        parent.layout().removeWidget(self) if parent.layout() else None
        self.deleteLater()
        if idx >= 0:
            parent.layout().insertWidget(idx, fb)
        else:
            fb.setParent(parent)
            fb.setGeometry(geo)
        fb.lower()
        try:
            parent.background_widget = fb
        except Exception:
            pass

    def resizeGL(self, w, h):
        pass

    def paintGL(self):
        if self._prog is None or not self._prog.isLinked():
            return
        import time
        if not self._t0:
            self._t0 = time.monotonic()
        self._prog.bind()
        f = self.context().functions()
        w, h = max(1, self.width()), max(1, self.height())
        # NOTE: PySide6 6.12's setUniformValue(loc, float) marshals to 0.0
        # (readback-verified) — raw glUniform is the reliable path.
        f.glUniform2f(self._u["u_res"], float(w), float(h))
        f.glUniform1f(self._u["u_time"], time.monotonic() - self._t0)
        f.glUniform2f(self._u["u_mouse"], self._mouse[0], self._mouse[1])
        a, b = self._accents
        f.glUniform3f(self._u["u_accentA"], a[0], a[1], a[2])
        f.glUniform3f(self._u["u_accentB"], b[0], b[1], b[2])
        f.glUniform1f(self._u["u_intensity"], self._intensity)
        f.glViewport(0, 0, w, h)
        f.glDisable(0x0BC1)   # GL_CULL_FACE
        f.glDisable(0x0B71)   # GL_DEPTH_TEST
        f.glDisable(0x0C11)   # GL_SCISSOR_TEST
        f.glDisable(0x0BE2)   # GL_BLEND
        self._vbo.bind()
        self._prog.enableAttributeArray(0)
        self._prog.setAttributeBuffer(0, 0x1406, 0, 2, 0)   # GL_FLOAT
        f.glDrawArrays(4, 0, 6)      # GL_TRIANGLES
        self._prog.disableAttributeArray(0)
        self._vbo.release()
        self._prog.release()

    # -- mouse ----------------------------------------------------------
    def set_mouse(self, mx, my):
        self._mouse = (max(0.0, min(1.0, mx)), max(0.0, min(1.0, my)))

    def mouseMoveEvent(self, ev):
        self.set_mouse(ev.position().x() / max(1, self.width()),
                       1.0 - ev.position().y() / max(1, self.height()))

    def leaveEvent(self, ev):
        self._mouse = (0.5, 0.45)


def _hex2rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


class PainterFallbackBackground(QWidget):
    """QPainter stand-in when no GL context is available (still procedural:
    layered flowing gradients + bevel bands + grid + grain)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accents = ("#22d3ee", "#ff2bd6")
        self.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def set_accents(self, a, b):
        self._accents = (a, b)
        self.update()

    def paintEvent(self, ev):
        import time
        t = time.monotonic()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, QColor("#05070c"))
        grad.setColorAt(0.62, QColor("#101823"))
        grad.setColorAt(0.66, QColor("#8fa4b4"))
        grad.setColorAt(0.70, QColor("#dfe7ee"))
        grad.setColorAt(0.78, QColor("#1c2530"))
        grad.setColorAt(1.0, QColor("#020408"))
        p.fillRect(self.rect(), grad)
        # flowing bevel blobs
        for i in range(3):
            x = W * (0.2 + 0.3 * i) + math.sin(t * 0.07 + i * 2) * W * 0.08
            y = H * (0.25 + 0.13 * i) + math.cos(t * 0.05 + i * 1.3) * H * 0.06
            r = min(W, H) * (0.24 + 0.07 * i)
            g2 = QRadialGradient(QPointF(x, y), r)
            c = QColor(self._accents[i % 2])
            c.setAlpha(34)
            g2.setColorAt(0.0, c)
            c2 = QColor(self._accents[i % 2])
            c2.setAlpha(0)
            g2.setColorAt(1.0, c2)
            p.setBrush(g2)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), r, r)
        # grid beams
        p.setPen(QPen(QColor(self._accents[0]), 1))
        p.setOpacity(0.05)
        for i in range(14):
            x = W * i / 13.0
            p.drawLine(QPointF(x, H * 0.62), QPointF(W * 0.5 + (x - W * 0.5) * 2.4, H))
        p.end()


def make_background():
    """GL background, or the painter fallback when APEX_NO_GL=1."""
    if os.environ.get("APEX_NO_GL"):
        fb = PainterFallbackBackground()
        fb._gl_ok = False
        return fb
    try:
        w = LiquidMetalBackground()
        w._gl_ok = True
        return w
    except Exception:
        fb = PainterFallbackBackground()
        fb._gl_ok = False
        return fb

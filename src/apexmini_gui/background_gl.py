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

KEY_VERT_SRC = """
// ---- 3D keyboard: chrome keycaps with per-fragment lighting ----------
attribute vec3 a_pos;
attribute vec3 a_nrm;
attribute vec3 a_col;
uniform mat4 u_mvp;
varying vec3 v_n;
varying vec3 v_col;
varying vec3 v_wp;
void main() {
    v_n = a_nrm;              // world space: the camera orbits, the board doesn't
    v_col = a_col;
    v_wp = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

KEY_FRAG_SRC = """
#ifdef GL_ES
precision highp float;
#endif
varying vec3 v_n;
varying vec3 v_col;
varying vec3 v_wp;
uniform vec3 u_cam;
uniform vec3 u_light;
uniform vec3 u_accentA;

void main() {
    vec3 N = normalize(v_n);
    vec3 V = normalize(u_cam - v_wp);
    vec3 L = normalize(u_light);
    float diff = max(dot(N, L), 0.0);
    float m = clamp(reflect(-V, N).y * 0.5 + 0.5, 0.0, 1.0);
    vec3 env = mix(vec3(0.04, 0.055, 0.085), vec3(0.40, 0.50, 0.62), smoothstep(0.08, 0.70, m));
    env = mix(env, vec3(0.92, 0.95, 0.98), pow(max(0.0, 1.0 - abs(m - 0.64) * 3.5), 6.0) * 0.55);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    vec3 c = v_col * (0.26 + 0.50 * diff)             // lambert on the colour
           + v_col * 0.30                              // backlight emissive (they ARE lit keys)
           + env * (0.16 + 0.34 * fres);               // chrome env by facing
    c += vec3(1.0, 1.0, 1.04) * pow(max(dot(normalize(L + V), N), 0.0), 64.0) * 1.15;
    c += u_accentA * fres * 0.20;
    gl_FragColor = vec4(c, 1.0);
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

// ---- shape field: pipes / shards / plates / pebbles -----------------
// tapered blade
float sd_shard(vec2 p, float len, float w) {
    float y = p.y + 0.25 * p.x * p.x / max(len, 0.001);
    float dx = max(abs(p.x) - len, 0.0);
    return length(vec2(dx, y * 3.2)) - w;
}
// round pipe
float sd_pipe(vec2 p, float len, float w) {
    float dx = clamp(p.x, -len, len);
    return length(vec2(p.x - dx, p.y)) - w;
}
// hex plate
float sd_plate(vec2 p, float r) {
    const vec3 k = vec3(-0.866, 0.5, 0.577);
    p = abs(p);
    p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy;
    p -= vec2(clamp(p.x, -k.z * r, k.z * r), r);
    return length(p) * sign(p.y);
}
// fbm-bumped pebble
float sd_pebble(vec2 p, float r) {
    return length(p) - r * (0.82 + 0.35 * fbm(p * 4.5 + 17.31));
}

// shade one chrome shape at signed distance sd with crest width w;
// sideExtrude: baked 3D — darker gradient toward the local -y (underside)
vec4 shape_chrome(vec2 lp, float sd, float w, float idx, float fseed) {
    if (sd > 0.035) return vec4(0.0);
    float cov = smoothstep(0.035, 0.0, sd);
    float crest = smoothstep(w * 1.7, 0.0, abs(lp.y));
    float m = mix(0.12 + 0.55 * fbm(lp * 7.0 + fseed), 0.66, crest);
    vec3 col = chrome_env(m, fbm(lp * 5.0 + fseed * 2.3));
    // baked side shading: the lower half of a shape reads as its extruded flank
    float side = smoothstep(0.0, -w * 1.2, lp.y) * (1.0 - crest);
    col *= 1.0 - 0.55 * side;
    // rim bevel
    float rim = smoothstep(w, w * 0.55, abs(lp.y)) * smoothstep(w * 0.55, w * 0.35, abs(lp.y));
    col += vec3(1.0) * rim * 0.75;
    // mouse-driven specular sweep
    vec3 L = normalize(vec3((u_mouse.x - 0.5) * 2.0 + 0.3 * sin(u_time * 0.17), 0.7, 0.8));
    col += vec3(1.0) * pow(max(0.0, 1.0 - abs(lp.y) / max(w, 0.004)), 8.0) * 0.22
         * (0.4 + 0.6 * abs(sin(idx + (u_mouse.x - 0.5) * 3.0)));
    return vec4(col, cov);
}

// one drifting clump of shapes; returns accumulated (color, coverage)
vec4 clump(vec2 p, float idx, float depth) {
    float t = u_time * 0.05;
    // jittered-grid placement: guarantees spread without overlap
    float gi = mod(idx, 4.0);
    float gj = floor(idx / 4.0);
    float h1 = hash(vec2(idx * 3.7, 1.3));
    float h2 = hash(vec2(idx * 5.1, 7.7));
    float h3 = hash(vec2(idx * 9.3, 3.9));
    vec2 base = (vec2(gi + 0.5 + 0.5 * (h1 - 0.5), gj + 0.5 + 0.5 * (h2 - 0.5)) / 4.0 - 0.5)
              * vec2(3.6, 2.2);
    // cluster center drifts slowly around its home cell
    vec2 c = base
           + 0.16 * vec2(sin(t * (0.10 + 0.08 * h3) + h1 * 9.0),
                         cos(t * (0.07 + 0.06 * h2) + h2 * 7.0))
           - (u_mouse - 0.5) * 0.06 * depth;          // depth parallax
    float rot = t * (0.06 + 0.10 * h1) + h2 * 6.28;
    float cr = cos(rot), sr = sin(rot);
    vec3 acc = vec3(0.0);
    float accov = 0.0;
    for (int j = 0; j < 4; j++) {
        float hj = hash(vec2(idx * 13.7, float(j) * 2.9));
        vec2 o = (vec2(hash(vec2(idx, float(j) + 40.0)),
                       hash(vec2(idx, float(j) + 80.0))) - 0.5) * vec2(0.9, 0.55);
        vec2 lp = p - c - o;
        lp = mat2(cr, -sr, sr, cr) * lp;
        lp *= depth;                                    // depth scale
        float kind = fract(h1 * 3.77 + float(j) * 0.29);   // per-clump variety
        float sd; float w; float len;
        if (kind < 0.30) {                              // shard
            len = 0.18 + 0.30 * hj; w = 0.008 + 0.016 * hj;
            sd = sd_shard(lp, len, w);
        } else if (kind < 0.55) {                       // pipe
            len = 0.12 + 0.22 * hj; w = 0.014 + 0.018 * hj;
            sd = sd_pipe(lp, len, w);
        } else if (kind < 0.78) {                       // hex plate
            float r = 0.075 + 0.14 * hj;
            sd = sd_plate(lp, r);
            w = r * 0.22;
        } else {                                        // pebble
            float r = 0.055 + 0.11 * hj;
            sd = sd_pebble(lp, r);
            w = r * 0.5;
        }
        // baked 3D: dark extruded copy offset behind the face
        vec4 sh = shape_chrome(lp + vec2(0.014, -0.022), sd, w, idx, hj * 40.0);
        if (sh.a > 0.0) {
            vec3 dark = sh.rgb * 0.22;
            acc = mix(acc, dark * depth, sh.a * 0.85 * (1.0 - accov));
            accov = max(accov, sh.a * 0.55);
        }
        vec4 face = shape_chrome(lp, sd, w, idx + float(j), hj * 90.0);
        face.rgb *= mix(0.55, 1.15, depth);             // depth brightness
        acc = mix(acc, face.rgb, face.a * (1.0 - accov * 0.5));
        accov = max(accov, face.a * 0.9);
    }
    return vec4(acc, min(1.0, accov));
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
    vec3 n = normalize(vec3((f - fx) / e, (f - fy) / e, 2.6));

    vec3 view = normalize(vec3(p * 0.35, 1.6));
    vec3 refl = reflect(-view, n);
    float m = clamp(refl.y * 0.5 + 0.5, 0.0, 1.0);
    m = 0.34 + (m - 0.34) * 0.5;                    // compress bands: calm, dark backdrop
    vec3 col = chrome_env(m, f * 0.55 + 0.22);

    // moving specular (follows mouse = the 'lean' light)
    vec3 L = normalize(vec3((u_mouse.x - 0.5) * 2.2 + sin(u_time * 0.13) * 0.35,
                            0.55 + (u_mouse.y - 0.5) * 1.2, 0.75));
    float spec = pow(max(dot(n, normalize(L + view)), 0.0), 42.0);
    col += vec3(1.0, 1.0, 1.05) * spec * 0.75;

    // ---- aggressive voronoi bevels (background texture) ----
    vec2 vcell = voronoi(p * 3.1);
    float edge = vcell.y;
    col += vec3(0.9, 0.95, 1.0) * smoothstep(0.14, 0.02, edge) * 0.13;
    col *= 1.0 - 0.30 * smoothstep(0.012, 0.0, edge);

    // ---- the shape field: drifting clumps of pipes/shards/plates ----
    // depth-sorted: far clusters first, near ones on top; spread across the screen
    for (int k = 0; k < 8; k++) {
        float depth = mix(0.55, 1.35, float(k) / 7.0);
        vec4 cl = clump(p, float(k) + 7.0, depth);
        col = mix(col, cl.rgb, cl.a * 0.92);
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
        self._key_colors = {}
        self._lean = (0.0, 0.0)
        self._zoom = 1.0
        self._show_keyboard = True
        self._lean_smooth = (0.0, 0.0)
        self._kg = None
        self.setMouseTracking(True)
        fmt = QSurfaceFormat()
        fmt.setSamples(4)                # MSAA — real 3D edges need it
        fmt.setDepthBufferSize(24)
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

    def set_key_colors(self, colors):
        """colors: {usage: (r,g,b)} 0-255."""
        self._key_colors = colors

    def set_lean(self, yaw, pitch):
        self._lean = (yaw, pitch)

    def set_zoom(self, z):
        self._zoom = max(0.5, min(2.2, z))

    def set_show_keyboard(self, show):
        self._show_keyboard = bool(show)

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

        # ---- 3D keyboard pass ----
        try:
            self._kg = KeyboardGeometry()
        except Exception:
            self._kg = None
            return
        self._kprog = QOpenGLShaderProgram(self)
        ok = self._kprog.addShaderFromSourceCode(QOpenGLShader.Vertex, KEY_VERT_SRC)
        ok = ok and self._kprog.addShaderFromSourceCode(QOpenGLShader.Fragment, KEY_FRAG_SRC)
        if not ok:
            self._kg = None
            return
        self._kprog.bindAttributeLocation("a_pos", 0)
        self._kprog.bindAttributeLocation("a_nrm", 1)
        self._kprog.bindAttributeLocation("a_col", 2)
        self._kprog.link()
        self._ku = {n: self._kprog.uniformLocation(n) for n in
                    ("u_mvp", "u_cam", "u_light", "u_accentA")}
        self._vbo_pos = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_nrm = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo_col = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        for vbo, arr in ((self._vbo_pos, self._kg.pos_arr),
                         (self._vbo_nrm, self._kg.nrm_arr)):
            vbo.create(); vbo.bind()
            vbo.allocate(arr.tobytes(), arr.buffer_info()[1] * 4)
            vbo.release()
        self._vbo_col.create()
        self._vbo_col.bind()
        empty = _array.array("f", [0.0] * (self._kg.nverts * 3))
        self._vbo_col.allocate(empty.tobytes(), empty.buffer_info()[1] * 4)
        self._vbo_col.release()

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
        t = time.monotonic() - self._t0
        f = self.context().functions()
        w, h = max(1, self.width()), max(1, self.height())

        # smooth the lean toward its target
        tx, ty = self._lean
        cy, cp = self._lean_smooth
        self._lean_smooth = (cy + (tx - cy) * 0.14, cp + (ty - cp) * 0.14)
        lean_yaw, lean_pitch = self._lean_smooth

        # ---- pass 1: liquid-metal background ----
        self._prog.bind()
        # NOTE: PySide6 6.12's setUniformValue(loc, float) marshals to 0.0
        # (readback-verified) — raw glUniform is the reliable path.
        f.glUniform2f(self._u["u_res"], float(w), float(h))
        f.glUniform1f(self._u["u_time"], t)
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

        # ---- pass 2: the 3D keyboard ----
        if self._show_keyboard and self._kg and getattr(self, "_kprog", None) and self._kprog.isLinked():
          try:
                kg = self._kg
                f.glClear(0x00000100)                     # depth buffer
                f.glEnable(0x0B71)                        # GL_DEPTH_TEST
                f.glDepthFunc(0x0203)                     # GL_LEQUAL
                f.glEnable(0x0BE2)                        # GL_BLEND for AA edges
                f.glBlendFunc(1, 0)                       # ONE, ZERO (opaque, but AA samples)
                f.glBlendEquation(0x8006)
                yaw = math.radians(-10) + lean_yaw
                pitch = math.radians(48) + lean_pitch
                target = (kg.BOARD_W / 2, kg.BOARD_H * 0.55, 0.0)
                dist = 15.0
                eye = (target[0] + dist * math.sin(yaw) * math.cos(pitch),
                       target[1] - dist * math.cos(yaw) * math.cos(pitch),
                       target[2] + dist * math.sin(pitch))
                view = _mat_lookat(eye, target, (0.0, 0.0, 1.0))
                proj = _mat_perspective(38.0, w / h, 0.5, 100.0)
                mvp = _mat_mul(proj, view)
                self._kprog.bind()
                f.glUniformMatrix4fv(self._ku["u_mvp"], 1, True, mvp)
                f.glUniform3f(self._ku["u_cam"], *eye)
                lx = target[0] + (self._mouse[0] - 0.5) * 9.0 + math.sin(t * 0.13) * 1.2
                ly = target[1] - 5.5
                lz = target[2] + 4.5 + (self._mouse[1] - 0.5) * 3.0
                f.glUniform3f(self._ku["u_light"], lx, ly, lz)
                a = self._accents[0]
                f.glUniform3f(self._ku["u_accentA"], a[0], a[1], a[2])
                # per-vertex colours from the engine
                colors = {u: (c[0] / 255, c[1] / 255, c[2] / 255)
                          for u, c in (self._key_colors or {}).items()}
                data = kg.color_bytes(colors)
                # order matters: bind VBO → enable attrib → setAttribBuffer → release
                self._vbo_pos.bind()
                self._kprog.enableAttributeArray(0)
                self._kprog.setAttributeBuffer(0, 0x1406, 0, 3, 0)
                self._vbo_pos.release()
                self._vbo_nrm.bind()
                self._kprog.enableAttributeArray(1)
                self._kprog.setAttributeBuffer(1, 0x1406, 0, 3, 0)
                self._vbo_nrm.release()
                self._vbo_col.bind()
                self._vbo_col.write(0, data, len(data))
                self._kprog.enableAttributeArray(2)
                self._kprog.setAttributeBuffer(2, 0x1406, 0, 3, 0)
                f.glDrawArrays(4, 0, kg.nverts)
                self._kprog.disableAttributeArray(0)
                self._kprog.disableAttributeArray(1)
                self._kprog.disableAttributeArray(2)
                self._vbo_col.release()
                self._kprog.release()
                f.glDisable(0x0B71)
                f.glDisable(0x0BE2)
          except Exception as e:
            import sys as _sys
            print("keyboard pass error:", e, file=_sys.stderr, flush=True)

    # ---- legends: project key centres to widget coords ----------------
    def legend_positions(self):
        """[(x, y, usage, w_units)] in widget pixels for the CURRENT camera."""
        if not self._kg:
            return []
        w, h = max(1, self.width()), max(1, self.height())
        yaw = math.radians(-10) + self._lean_smooth[0]
        pitch = math.radians(48) + self._lean_smooth[1]
        kg = self._kg
        target = (kg.BOARD_W / 2, kg.BOARD_H * 0.55, 0.0)
        dist = 15.0 / max(0.4, self._zoom)
        eye = (target[0] + dist * math.sin(yaw) * math.cos(pitch),
               target[1] - dist * math.cos(yaw) * math.cos(pitch),
               target[2] + dist * math.sin(pitch))
        mvp = _mat_mul(_mat_perspective(38.0, w / h, 0.5, 100.0),
                       _mat_lookat(eye, target, (0.0, 0.0, 1.0)))
        out = []
        for (x, y, z, usage) in kg.key_centers:
            # clip
            cx = mvp[0] * x + mvp[4] * y + mvp[8] * z + mvp[12]
            cy = mvp[1] * x + mvp[5] * y + mvp[9] * z + mvp[13]
            cw = mvp[3] * x + mvp[7] * y + mvp[11] * z + mvp[15]
            if cw <= 0.001:
                continue
            out.append((w * 0.5 + w * 0.5 * cx / cw, h * 0.5 - h * 0.5 * cy / cw, usage))
        return out

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

    def set_lean(self, yaw, pitch):
        pass

    def set_key_colors(self, colors):
        self._key_colors = colors

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


# =========================================================================
# 3D keyboard — geometry, camera and render pass
# =========================================================================
import array as _array

KEY_VERT_SRC = KEY_VERT_SRC  # (defined above)


def _mat_mul(a, b):
    """4x4 row-major multiply: a * b."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def _mat_perspective(fovy_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2.0)
    # row-major, column-vector convention (clip = M · v)
    return [
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) / (near - far), 2 * far * near / (near - far),
        0, 0, -1, 0,
    ]


def _mat_lookat(eye, target, up):
    def sub(a, b):
        return [a[i] - b[i] for i in range(3)]

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]]

    def norm(a):
        l = math.sqrt(sum(v * v for v in a)) or 1.0
        return [v / l for v in a]

    def dot(a, b):
        return sum(a[i] * b[i] for i in range(3))

    z = norm(sub(eye, target))          # camera looks down -z
    x = norm(cross(up, z))
    y = cross(z, x)
    return [
        x[0], x[1], x[2], -dot(x, eye),
        y[0], y[1], y[2], -dot(y, eye),
        z[0], z[1], z[2], -dot(z, eye),
        0, 0, 0, 1,
    ]


class KeyboardGeometry:
    """Builds tapered keycap boxes + chassis in board-world units."""

    GAP = 0.12
    DEPTH = 0.30           # keycap height
    TAPER = 0.075          # top-face inset per side
    PLATE_PAD = 0.8
    BOARD_W = 15.5
    BOARD_H = 5 * 1.12

    def __init__(self):
        from apexmini_gui import keyboard3d as K3D
        from apexmini import keymap as K
        self.pos = []
        self.nrm = []
        self.col = []
        self.usage = []            # per-vertex usage id (None = chassis)
        self.key_centers = []      # (x, y, z, usage) top-face centers for legends
        dark = (10 / 255, 12 / 255, 16 / 255)
        self.chassis_color = dark
        zt = self.DEPTH
        d = self.TAPER

        def quad(p0, p1, p2, p3, usage, color):
            n = self._normal(p0, p1, p3)
            for pt in (p0, p1, p2, p0, p2, p3):
                self.pos.extend(pt)
                self.nrm.extend(n)
                self.col.extend(color)
                self.usage.append(usage)

        # chassis: deck top + skirt
        x0, y0 = -self.PLATE_PAD, -self.PLATE_PAD
        x1, y1 = self.BOARD_W + self.PLATE_PAD, self.BOARD_H + self.PLATE_PAD
        zb, zt2 = -0.45, 0.0
        quad((x0, y0, zt2), (x1, y0, zt2), (x1, y1, zt2), (x0, y1, zt2), None, dark)
        quad((x0, y1, zb), (x1, y1, zb), (x1, y1, zt2), (x0, y1, zt2), None, dark)
        quad((x1, y0, zb), (x1, y0, zt2), (x1, y1, zt2), (x1, y1, zb), None, dark)
        quad((x0, y0, zb), (x0, y1, zb), (x0, y1, zt2), (x0, y0, zt2), None, dark)
        quad((x0, y0, zb), (x1, y0, zb), (x1, y0, zt2), (x0, y0, zt2), None, dark)

        gy = 0
        for row in K3D.LAYOUT:
            gx = 0.0
            yy0 = gy * 1.12
            yy1 = yy0 + 1.0
            for name, w in row:
                usage = K.NAME_TO_USAGE.get(name) or 0
                xx0, xx1 = gx, gx + w - self.GAP
                # keycap: base rect at z=0.02, tapered top at zt
                b = [(xx0, yy0, 0.02), (xx1, yy0, 0.02), (xx1, yy1, 0.02), (xx0, yy1, 0.02)]
                t = [(xx0 + d, yy0 + d, zt), (xx1 - d, yy0 + d, zt),
                     (xx1 - d, yy1 - d, zt), (xx0 + d, yy1 - d, zt)]
                c = (46 / 255, 52 / 255, 62 / 255)   # unlit keycap base
                quad(t[0], t[1], t[2], t[3], usage, c)              # top
                quad(b[3], b[2], t[2], t[3], usage, c)              # front
                quad(b[1], b[0], t[0], t[1], usage, c)              # back
                quad(b[0], b[3], t[3], t[0], usage, c)              # left
                quad(b[2], b[1], t[1], t[2], usage, c)              # right
                self.key_centers.append((sum(p[0] for p in t) / 4.0,
                                         sum(p[1] for p in t) / 4.0,
                                         zt + 0.01, usage))
                gx += w + self.GAP
            gy += 1

        self.pos_arr = _array.array("f", self.pos)
        self.nrm_arr = _array.array("f", self.nrm)
        self._col = self.col
        self.nverts = len(self.pos) // 3

    @staticmethod
    def _normal(p0, p1, p2):
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        l = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        return [nx / l, ny / l, nz / l]

    def color_bytes(self, colors, brightness=1.0):
        out = []
        for u in self.usage:
            if u is None:
                c = self.chassis_color
            else:
                c = colors.get(u, (14 / 255, 16 / 255, 20 / 255))
            out.extend((c[0], c[1], c[2]))
        return _array.array("f", out).tobytes()


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

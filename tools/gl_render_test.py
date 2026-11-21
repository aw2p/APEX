#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless GL shader renderer for iterating on the Metalheart background.

Renders background_gl.FRAG_SRC through a bare QOpenGLContext + FBO (bypasses
QOpenGLWidget entirely, works under the offscreen platform).

    python tools/spawn.py venv-qt/bin/python tools/gl_render_test.py out.png [time] [mx my]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
from PySide6.QtWidgets import QApplication

from apexmini_gui import background_gl as BGL


def hex3(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def render(out_path, t=1.7, mx=0.5, my=0.45, W=1180, H=680,
           accent_a="#22d3ee", accent_b="#ff2bd6"):
    """Render ONLY the liquid-metal background shader (headless)."""
    app = QApplication.instance() or QApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    assert surface.isValid(), "offscreen surface invalid"
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    ok = ctx.create()
    if not ok:
        ctx = QOpenGLContext()
        ctx.setFormat(QSurfaceFormat())
        ok = ctx.create()
        assert ok, "no GL context (even unpinned)"
    assert ctx.makeCurrent(surface), "makeCurrent failed"
    f = ctx.functions()

    prog = QOpenGLShaderProgram()
    prog.addShaderFromSourceCode(QOpenGLShader.Vertex, BGL.VERT_SRC)
    ok = prog.addShaderFromSourceCode(QOpenGLShader.Fragment, BGL.FRAG_SRC)
    if not ok:
        print(prog.log())
        sys.exit(1)
    prog.bindAttributeLocation("a_pos", 0)
    prog.link()
    prog.bind()
    u = {n: prog.uniformLocation(n) for n in
         ("u_res", "u_time", "u_mouse", "u_accentA", "u_accentB", "u_intensity")}

    from PySide6.QtOpenGL import QOpenGLFramebufferObject
    fbo = QOpenGLFramebufferObject(W, H)
    fbo.bind()
    f.glViewport(0, 0, W, H)
    f.glDisable(0x0BC1); f.glDisable(0x0B71); f.glDisable(0x0C11); f.glDisable(0x0BE2)
    vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
    vbo.create(); vbo.bind()
    import array
    verts = array.array("f", [-1,-1, 1,-1, 1,1, -1,-1, 1,1, -1,1])
    vbo.allocate(verts.tobytes(), len(verts) * 4)
    prog.enableAttributeArray(0)
    prog.setAttributeBuffer(0, 0x1406, 0, 2, 0)
    # raw glUniform (PySide6 6.12 scalar setUniformValue marshals to 0.0)
    f.glUniform2f(u["u_res"], float(W), float(H))
    f.glUniform1f(u["u_time"], t)
    f.glUniform2f(u["u_mouse"], mx, my)
    a = hex3(accent_a); b = hex3(accent_b)
    f.glUniform3f(u["u_accentA"], a[0], a[1], a[2])
    f.glUniform3f(u["u_accentB"], b[0], b[1], b[2])
    f.glUniform1f(u["u_intensity"], 1.0)
    f.glDrawArrays(4, 0, 6)
    prog.disableAttributeArray(0)
    vbo.release(); prog.release()
    img = fbo.toImage()
    img.save(out_path)
    print("saved", out_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    out = args[0] if args else "/tmp/opencode/gl-bg.png"
    t = float(args[1]) if len(args) > 1 else 1.7
    mx = float(args[2]) if len(args) > 2 else 0.5
    my = float(args[3]) if len(args) > 3 else 0.45
    render(out, t, mx, my)

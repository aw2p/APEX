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


def render(out_path, t=1.7, mx=0.5, my=0.45, W=1180, H=680,
           accent_a="#22d3ee", accent_b="#ff2bd6"):
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
        # retry without a pinned version (driver may refuse 3.3 core here)
        ctx = QOpenGLContext()
        ctx.setFormat(QSurfaceFormat())
        ok = ctx.create()
        assert ok, "no GL context (even unpinned)"
    assert ctx.makeCurrent(surface), "makeCurrent failed"
    print("GL:", QOpenGLContext.currentContext().format().version())
    f = ctx.functions()

    prog = QOpenGLShaderProgram()
    src = BGL.FRAG_SRC
    dbg = os.environ.get("GL_DEBUG", "")
    REPL_TARGET = "    col *= u_intensity;\n    gl_FragColor = vec4(col, 1.0);"
    if dbg == "1":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(v_uv.x, v_uv.y, 0.0, 1.0);")
    elif dbg == "2":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(vec3(f), 1.0);")
    elif dbg == "3":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(vec3(noise(uv * 8.0)), 1.0);")
    elif dbg == "4":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(vec3(hash(uv * 8.0)), 1.0);")
    elif dbg == "5":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(chrome_env(m, f), 1.0);")
    elif dbg == "6":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(vec3(vcell.y * 8.0), 1.0);")
    elif dbg == "7":
        src = src.replace(
            "    // ---- the shard burst: one large object at center ----\n"
            "    for (int i = 0; i < 9; i++) {\n"
            "        vec4 bl = blade(p * vec2(aspect * 0.92, 1.0) * 0.62, float(i));\n"
            "        col = mix(col, bl.rgb, bl.a);\n"
            "    }",
            "    vec3 acc = vec3(0.0);\n"
            "    for (int i = 0; i < 9; i++) {\n"
            "        vec4 bl = blade(p * vec2(aspect * 0.92, 1.0) * 0.62, float(i));\n"
            "        acc = mix(acc, bl.rgb, bl.a);\n"
            "    }\n"
            "    gl_FragColor = vec4(acc, 1.0);\n"
            "    return;")
    elif dbg == "9":
        src = src.replace(
            "    // ---- aggressive voronoi bevels (background texture) ----",
            "    gl_FragColor = vec4(col, 1.0); return;")
    elif dbg == "10":
        src = src.replace(
            "    // ---- the shard burst: one large object at center ----",
            "    gl_FragColor = vec4(col, 1.0); return;")
    elif dbg == "11":
        src = src.replace(
            "    // ---- anamorphic lens flare ----",
            "    gl_FragColor = vec4(col, 1.0); return;")
    elif dbg == "12":
        src = src.replace(
            "    // vignette + film grain (keep the rawness)",
            "    gl_FragColor = vec4(col, 1.0); return;")
    elif dbg == "13":
        before = len(src)
        src = src.replace(
            "    col += (hash(uv * u_res + fract(u_time)) - 0.5) * 0.035;",
            "")
        print("d13 replace changed source:", len(src) != before)
    elif dbg == "14":
        before = len(src)
        src = src.replace(
            "    col *= 0.55 + 0.45 * vig;",
            "")
        print("d14 replace changed source:", len(src) != before)
    elif dbg == "15":
        src = src.replace(REPL_TARGET, "    gl_FragColor = vec4(vec3(vig), 1.0);")
    elif dbg == "16":
        src = src.replace("    col *= u_intensity;", "    col *= 1.0;")
    elif dbg == "17":
        src = src.replace("    col *= u_intensity;", "    col *= 0.5 + 0.5 * u_intensity;")
    prog.addShaderFromSourceCode(QOpenGLShader.Vertex, BGL.VERT_SRC)
    ok = prog.addShaderFromSourceCode(QOpenGLShader.Fragment, src)
    if not ok:
        print(prog.log())
        sys.exit(1)
    prog.bindAttributeLocation("a_pos", 0)
    prog.link()
    prog.bind()
    u = {n: prog.uniformLocation(n) for n in
         ("u_res", "u_time", "u_mouse", "u_accentA", "u_accentB", "u_intensity")}

    def hex3(h):
        h = h.lstrip("#")
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)

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

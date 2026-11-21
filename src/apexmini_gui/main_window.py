#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apexmini-suite GUI — Metalheart / Neo-Vectorheart lighting control.

Window = live fake-3D preview (left) + profile builder (right) + bank (bottom).
Runs the engine in-process (streaming to the keyboard) unless a daemon is
already running, in which case switching a profile just nudges the daemon.

Offscreen screenshot mode for CI/agent iteration:  --screenshot PATH
"""

import os
import sys
import threading
import time

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QBrush
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QPushButton, QSlider, QSpinBox, QStatusBar, QVBoxLayout,
    QWidget, QMessageBox,
)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from apexmini import profiles as PR           # noqa: E402
from apexmini import engine as EN             # noqa: E402
from apexmini import inputfeed                # noqa: E402
from apexmini_gui import theme                # noqa: E402
from apexmini_gui import daemon as DM         # noqa: E402
from apexmini_gui import background_gl as BGL  # noqa: E402
from apexmini_gui import keyboard3d as K3      # noqa: E402  (name lookups for legends)
from apexmini_gui import settings as SET  # noqa: E402


class PreviewWidget(QWidget):
    """Transparent overlay.  Two modes:
      '3d'      — paints key legends at the REAL 3D projected positions
                  (keycaps render in the GL pass);
      'stylized'— paints the painter-rendered fake-3D keyboard itself
                  (the old look), GL draws only the liquid background."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.accent_a, self.accent_b = theme.CYAN, theme.MAGENTA
        self._mouse = (0.5, 0.45)
        self.mode = "3d"
        self.zoom = 1.0
        self.k3d = K3.Keyboard3DPreview(self)
        self._t0 = time.monotonic()
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_accents(self, a, b):
        self.accent_a, self.accent_b = a, b
        self.k3d_ = None

    def set_mode(self, mode):
        self.mode = "stylized" if mode == "stylized" else "3d"
        self.update()

    def set_mouse(self, mx, my):
        self._mouse = (mx, my)

    def set_zoom(self, z):
        self.zoom = z

    def key_pressed(self, usage):
        self.k3d.press_glow[usage] = 1.0

    def _tick(self):
        w = self.window()
        bg = getattr(w, "background", None)
        if self.mode == "3d" and bg is not None:
            bg.set_lean((self._mouse[0] - 0.5) * 0.42, ((1.0 - self._mouse[1]) - 0.5) * 0.30)
            bg.set_key_colors(self.engine.colors())
            bg.set_zoom(self.zoom)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.mode == "stylized":
            # painter keyboard over the liquid background
            self.k3d.lean = ((self._mouse[0] - 0.5) * 0.14, ((1.0 - self._mouse[1]) - 0.5) * 0.10)
            self.k3d.light_pos = self._mouse
            self.k3d.zoom = self.zoom
            self.k3d.colors = self.engine.colors()
            self.k3d.paint(p, self.width(), self.height(), self.accent_a, self.accent_b,
                           time.monotonic() - self._t0)
            p.end()
            return
        w = self.window()
        bg = getattr(w, "background", None)
        if bg is None or not hasattr(bg, "legend_positions"):
            p.end()
            return
        for (x, y, usage) in bg.legend_positions():
            if x < 0 or y < 0 or x > self.width() or y > self.height():
                continue
            c = self.engine.colors().get(usage, (20, 22, 28))
            lum = c[0] * 0.3 + c[1] * 0.6 + c[2] * 0.1
            label = K3.K.name_for_usage(usage)
            f2 = p.font()
            f2.setPixelSize(11)
            p.setFont(f2)
            p.setPen(QPen(QColor(0, 0, 0, 160)))
            p.drawText(QRectF(x - 20 + 1, y - 8 + 1, 40, 16), Qt.AlignCenter, label)
            p.setPen(QPen(QColor(235, 242, 250, 150 if lum < 90 else 230)))
            p.drawText(QRectF(x - 20, y - 8, 40, 16), Qt.AlignCenter, label)
        p.end()


class ColorSwatch(QPushButton):
    """A clickable colour chip; opens QColorDialog."""

    def __init__(self, color="#000000", parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 30)
        self._color = QColor(color)
        self.clicked.connect(self._pick)
        self._update_look()

    def _update_look(self):
        c = self._color.name()
        self.setStyleSheet(
            "QPushButton{background:%s;border:1px solid #323a47;border-radius:4px;}"
            "QPushButton:hover{border:1px solid %s;}" % (c, theme.TEXT_DIM))

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "pick colour")
        if c.isValid():
            self._color = c
            self._update_look()

    def color(self):
        return self._color.name()

    def set_color(self, name):
        self._color = QColor(name)
        self._update_look()


class BuilderPanel(QFrame):
    """Right-hand profile editor."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        title = QLabel("PROFILE BUILDER")
        title.setObjectName("title")
        lay.addWidget(title)

        # keyboard render mode
        self.mode_btn = QPushButton("keyboard: 3D")
        self.mode_btn.setToolTip("toggle between the real-3D and the stylized painter keyboard")
        lay.addWidget(self.mode_btn)

        # name
        row = QHBoxLayout()
        row.addWidget(QLabel("name"))
        self.name_edit = QLineEdit("new profile")
        row.addWidget(self.name_edit, 1)
        lay.addLayout(row)

        # base type
        row = QHBoxLayout()
        row.addWidget(QLabel("animation"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(PR.BASE_TYPES)
        row.addWidget(self.type_combo, 1)
        lay.addLayout(row)

        # palette
        pal_row = QHBoxLayout()
        pal_row.addWidget(QLabel("colours"))
        self.swatches = [ColorSwatch("#ff6a00"), ColorSwatch("#ff2b00"),
                         ColorSwatch("#550000"), ColorSwatch("#ffa040")]
        for s in self.swatches:
            pal_row.addWidget(s)
        lay.addLayout(pal_row)
        hint = QLabel("unused slots stay dim — they're skipped")
        hint.setObjectName("subtitle")
        lay.addWidget(hint)
        self._sync_swatch_state()

        # speed
        lay.addWidget(QLabel("speed"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(5, 300)
        self.speed.setValue(100)
        lay.addWidget(self.speed)

        # brightness
        lay.addWidget(QLabel("brightness"))
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setValue(100)
        lay.addWidget(self.brightness)

        # reactive
        self.reactive_cb = QCheckBox("reactive typing flash")
        lay.addWidget(self.reactive_cb)
        re_row = QHBoxLayout()
        re_row.addWidget(QLabel("flash colour"))
        self.reactive_color = ColorSwatch("#ffb060")
        re_row.addWidget(self.reactive_color)
        re_row.addWidget(QLabel("decay"))
        self.decay = QSlider(Qt.Horizontal)
        self.decay.setRange(2, 60)          # 0.2s .. 6.0s (in tenths)
        self.decay.setValue(12)
        re_row.addWidget(self.decay, 1)
        lay.addLayout(re_row)

        for w in (self.type_combo, self.speed, self.brightness,
                  self.reactive_cb, self.decay):
            pass
        self.type_combo.currentTextChanged.connect(lambda *_: self._sync_swatch_state() or self.changed.emit())
        self.speed.valueChanged.connect(lambda *_: self.changed.emit())
        self.brightness.valueChanged.connect(lambda *_: self.changed.emit())
        self.reactive_cb.toggled.connect(lambda *_: self.changed.emit())
        self.decay.valueChanged.connect(lambda *_: self.changed.emit())
        for s in self.swatches:
            s.clicked.connect(lambda *_: self._sync_swatch_state() or self.changed.emit())
        self.reactive_color.clicked.connect(lambda *_: self.changed.emit())

        lay.addStretch(1)
        self._sync_swatch_state()

    # ---- state <-> widget -------------------------------------------
    def _sync_swatch_state(self):
        t = self.type_combo.currentText()
        passive = t in ("candle", "spectrum")     # these effects own the palette
        for s in self.swatches:
            s.setEnabled(not passive)
            if passive:
                s.setStyleSheet(
                    "QPushButton{background:%s;border:1px dashed #323a47;border-radius:4px;}"
                    % s._color.name())
            else:
                s.setStyleSheet(
                    "QPushButton{background:%s;border:1px solid #323a47;border-radius:4px;}"
                    % s._color.name())

    def to_profile(self):
        colors = [s.color() for s in self.swatches if s.isEnabled()]
        if not colors:
            colors = ["#ff6a00"]
        return PR.new_profile(
            name=self.name_edit.text() or "unnamed",
            base_type=self.type_combo.currentText(),
            colors=colors,
            speed=self.speed.value() / 100.0,
            brightness=self.brightness.value() / 100.0,
            reactive=self.reactive_cb.isChecked(),
            reactive_color=self.reactive_color.color(),
            decay=self.decay.value() / 10.0,
        )

    def from_profile(self, prof):
        self.name_edit.setText(prof["name"])
        self.type_combo.setCurrentText(prof["base"]["type"])
        colors = (prof["base"]["colors"] + ["#111111"] * 4)[:4]
        for s, c in zip(self.swatches, colors):
            s.setEnabled(True)
            s.set_color(c)
        self._sync_swatch_state()
        self.speed.setValue(int(prof["base"]["speed"] * 100))
        self.brightness.setValue(int(prof["base"]["brightness"] * 100))
        self.reactive_cb.setChecked(prof["reactive"]["enabled"])
        self.reactive_color.set_color(prof["reactive"]["color"])
        self.decay.setValue(int(prof["reactive"]["decay"] * 10))


class BankPanel(QFrame):
    """Bottom: saved profiles + actions."""

    apply_requested = Signal(str)      # profile name
    refreshed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.profile_provider = None      # MainWindow wires this to the builder
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("PROFILE BANK")
        t.setObjectName("title")
        head.addWidget(t)
        head.addStretch(1)
        self.btn_apply = QPushButton("apply")
        self.btn_apply.setObjectName("primary")
        self.btn_save = QPushButton("save")
        self.btn_import = QPushButton("import…")
        self.btn_export = QPushButton("export…")
        self.btn_delete = QPushButton("delete")
        self.btn_delete.setObjectName("danger")
        for b in (self.btn_apply, self.btn_save, self.btn_import, self.btn_export, self.btn_delete):
            head.addWidget(b)
        lay.addLayout(head)

        self.listw = QListWidget()
        lay.addWidget(self.listw, 1)

        self.btn_apply.clicked.connect(lambda: self._emit_selected("apply"))
        self.listw.itemDoubleClicked.connect(lambda *_: self._emit_selected("apply"))
        self.btn_save.clicked.connect(self._save)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_import.clicked.connect(self._import)
        self.btn_export.clicked.connect(self._export)

    def _save(self):
        if self.profile_provider is None:
            return
        prof = self.profile_provider()
        PR.save(prof)
        PR.set_active_name(prof["name"])
        self.refresh()
        for i in range(self.listw.count()):
            if self.listw.item(i).text() == prof["name"]:
                self.listw.setCurrentRow(i)
                break

    def selected_name(self):
        it = self.listw.currentItem()
        return it.text() if it else None

    def _emit_selected(self, what):
        name = self.selected_name()
        if name:
            self.apply_requested.emit(name)

    def _delete(self):
        name = self.selected_name()
        if name and PR.delete(name):
            self.refresh()

    def _import(self):
        import json as _json
        path, _ = QFileDialog.getOpenFileName(self, "import profile", "", "JSON (*.json)")
        if path:
            try:
                PR.import_file(path)
                self.refresh()
            except (ValueError, OSError, _json.JSONDecodeError) as e:
                QMessageBox.warning(self, "import failed", str(e))

    def _export(self):
        import json as _json
        name = self.selected_name()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(self, "export profile", name + ".json", "JSON (*.json)")
        if path:
            try:
                prof = PR.load(name)
            except (OSError, ValueError):
                return
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(prof, f, indent=2)

    def refresh(self):
        self.listw.clear()
        for entry in PR.list_profiles():
            QListWidgetItem(entry["name"], self.listw)
        self.refreshed.emit()


# (json import handled locally in the methods that need it)


class MainWindow(QMainWindow):
    def __init__(self, headless=False):
        super().__init__()
        self.setWindowTitle("APEXMINI — metalheart lighting suite")
        self.resize(1180, 680)

        self.engine = EN.Engine()
        self.stop_event = None
        self.stream_thread = None
        self.own_engine = DM.daemon_running() is None
        self.current_profile = PR.load(PR.get_active_name()) if PR.get_active_name() else dict(PR.DEFAULT_PROFILE)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(5, 5, 5, 4)
        root.setSpacing(5)

        # liquid-metal background: opaque child of the transparent central,
        # created first so every content widget stacks above it.
        from apexmini_gui import logo as _logo_mod
        self.logo_label = QLabel(self)
        self.logo_label.setStyleSheet("background: transparent;")
        self.logo_label.setPixmap(_logo_mod.render(128))
        self.logo_label.setFixedSize(64, 64)
        self.logo_label.setScaledContents(True)
        self.logo_label.show()
        self.logo_label.raise_()

        # liquid-metal background: opaque child of the transparent central,
        # created first so every content widget stacks above it.
        self.background = BGL.make_background()
        self.background.setParent(central)
        self.background.lower()
        self.background.setMouseTracking(True)

        def _central_resize(ev):
            self.background.setGeometry(0, 0, central.width(), central.height())
            self.logo_label.move(12, 12)
            self.logo_label.raise_()
            if self._orig_resizeEvent:
                self._orig_resizeEvent(ev)
        self._orig_resizeEvent = central.resizeEvent
        central.resizeEvent = _central_resize
        self._orig_mouse = central.mouseMoveEvent

        def _central_mouse(ev):
            pos = ev.position()
            mx = pos.x() / max(1, central.width())
            my = 1.0 - pos.y() / max(1, central.height())
            self.background.set_mouse(mx, my)
            self.preview.set_mouse(mx, my)
            if self._orig_mouse:
                self._orig_mouse(ev)
        central.mouseMoveEvent = _central_mouse
        central.setMouseTracking(True)

        mid = QHBoxLayout()
        mid.setSpacing(5)
        # left: preview
        self.preview = PreviewWidget(self.engine)
        mid.addWidget(self.preview, 3)

        # right: builder
        self.builder = BuilderPanel()
        mid.addWidget(self.builder, 2)
        root.addLayout(mid, 1)

        # bottom: bank
        self.bank = BankPanel()
        self.bank.profile_provider = lambda: self.builder.to_profile()
        self.bank.setMaximumHeight(170)
        root.addWidget(self.bank, 1)

        # status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel()
        sb.addWidget(self.status_label, 1)
        self.keep_running_cb = QCheckBox("keep lighting when window closes (background)")
        self.keep_running_cb.setChecked(True)
        sb.addPermanentWidget(self.keep_running_cb)

        # user settings (keyboard mode, zoom)
        self.settings = SET.load()
        self.zoom = self.settings["zoom"]

        # wiring
        self.tray = None                       # early: signals may fire during init
        self.builder.changed.connect(self._live_apply)
        self.bank.apply_requested.connect(self._activate_profile)
        self.bank.refreshed.connect(self._refresh_tray)
        PR.ensure_defaults()
        self.bank.refresh()

        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = TrayController(self)
        except Exception:
            pass

        self.feed = None
        self.marker_timer = QTimer(self)
        self.marker_timer.setInterval(500)
        self.marker_timer.timeout.connect(self._check_marker)
        self.marker_timer.start()

        # tilt works over EVERY panel: track + filter all child widgets
        from PySide6.QtCore import QEvent
        for w in central.findChildren(QWidget):
            w.setMouseTracking(True)
            w.installEventFilter(self)

        # keyboard render mode from settings + toggle handler
        self.preview.set_mode(self.settings["keyboard_mode"])
        self.preview.set_zoom(self.zoom)
        self._update_mode_button()
        self.builder.mode_btn.clicked.connect(self._toggle_kbd_mode)

        self._load_current()
        self._start_streaming()
        self._refresh_accents()

    # ---- profile handling ---------------------------------------------
    def _load_current(self):
        self.builder.from_profile(self.current_profile)
        self.engine.set_profile(self.current_profile)
        self.bank.listw.setCurrentItem(None)

    def _live_apply(self):
        prof = self.builder.to_profile()
        self.current_profile = prof
        self.engine.set_profile(prof)
        self._refresh_accents()

    def _activate_profile(self, name):
        try:
            prof = PR.load(name)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "load failed", str(e))
            return
        self.current_profile = prof
        self.builder.from_profile(prof)
        self.engine.set_profile(prof)
        PR.set_active_name(name)
        self._refresh_accents()
        if self.tray:
            self.tray.refresh_profiles()

    def _refresh_accents(self):
        aa, ab = theme.accents_for_profile(self.current_profile)
        self.preview.set_accents(aa, ab)
        if hasattr(self.background, "set_accents"):
            self.background.set_accents(aa, ab)
        if hasattr(self.builder, "set_accents"):
            self.builder.set_accents(aa)
        if hasattr(self.bank, "set_accents"):
            self.bank.set_accents(aa)
        QApplication.instance().setStyleSheet(theme.build_qss(aa, ab))

    # ---- streaming / daemon ---------------------------------------------
    def _start_streaming(self):
        if DM.daemon_running():
            self.status_label.setText(
                "daemon attached (pid %d) — switches nudge the daemon" % DM.daemon_running())
            return
        self.stop_event = threading.Event()
        self.stream_thread = threading.Thread(
            target=self.engine.stream_forever, args=(self.stop_event,), daemon=True)
        self.stream_thread.start()
        self.status_label.setText("engine: streaming in-process (no daemon)")
        self.feed = inputfeed.TypingFeed(self._on_key).start()

    def _on_key(self, usage):
        self.engine.note_press(usage)
        self.engine.note_press(usage)
        if self.settings["keyboard_mode"] == "stylized":
            self.preview.key_pressed(usage)

    def _refresh_tray(self):
        if self.tray:
            self.tray.refresh_profiles()

    def full_quit(self):
        """Real quit: stop streaming, release LEDs, exit."""
        if self.stop_event:
            self.stop_event.set()
        if self.feed:
            self.feed.stop()
        self._keep_running = False
        QApplication.instance().quit()

    def _toggle_kbd_mode(self):
        self.settings["keyboard_mode"] = (
            "stylized" if self.settings["keyboard_mode"] == "3d" else "3d")
        self._update_mode_button()
        self.preview.set_mode(self.settings["keyboard_mode"])
        SET.save(self.settings)

    def _update_mode_button(self):
        self.builder.mode_btn.setText(
            "keyboard: real 3D ⬢  (click → stylized)" if self.settings["keyboard_mode"] == "3d"
            else "keyboard: stylized ✎  (click → real 3D)")

    def eventFilter(self, obj, ev):
        if getattr(self, "_in_filter", False):
            return False
        if ev.type() == QEvent.Wheel:
            dy = ev.angleDelta().y() if hasattr(ev, "angleDelta") else 0
            if dy:
                self.zoom = max(0.5, min(2.2, self.zoom * (1.15 if dy > 0 else 1 / 1.15)))
                self.settings["zoom"] = self.zoom
                self.preview.set_zoom(self.zoom)
                SET.save(self.settings)
            return False
        if ev.type() == QEvent.MouseMove and self.centralWidget() is not None:
            gp = ev.globalPosition()
            cw = self.centralWidget()
            lp = cw.mapFromGlobal(gp.toPoint())
            W, H = max(1, cw.width()), max(1, cw.height())
            mx = max(0.0, min(1.0, lp.x() / W))
            my = max(0.0, min(1.0, 1.0 - lp.y() / H))
            self.background.set_mouse(mx, my)
            self.preview.set_mouse(mx, my)
            return False
        return super().eventFilter(obj, ev)

    def _check_marker(self):
        """External switches (CLI `use`, tray in daemon mode) → load them."""
        try:
            name = PR.get_active_name()
            if name and name != self.current_profile.get("name"):
                self._activate_profile(name)
        except (OSError, ValueError):
            pass

    # ---- lifecycle ------------------------------------------------------
    def closeEvent(self, ev):
        if getattr(self, "_keep_running", True) is False:
            super().closeEvent(ev)
            return
        if self.keep_running_cb.isChecked():
            # minimize to tray/background: keep the stream alive
            ev.ignore()
            self.hide()
            if self.tray:
                self.tray.tray.showMessage(
                    "apexmini", "still lighting in the background — tray icon to reopen",
                    __import__("PySide6.QtWidgets", fromlist=["QSystemTrayIcon"])
                    .QSystemTrayIcon.Information, 2200)
            return
        if self.stop_event:
            self.stop_event.set()
        if self.feed:
            self.feed.stop()
        super().closeEvent(ev)


class TrayController:
    """System tray: quick profile switching without the window."""

    def __init__(self, win):
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu
        self.win = win
        self.menu = QMenu()
        self.profile_menu_actions = []

        self.open_act = self.menu.addAction("open window")
        self.open_act.triggered.connect(win.show)
        self.menu.addSeparator()
        self.profile_header = self.menu.addAction("profiles:")
        self.profile_header.setEnabled(False)
        self.quit_act = self.menu.addAction("quit (release LEDs)")
        self.quit_act.triggered.connect(win.full_quit)

        self.tray = QSystemTrayIcon(_app_icon())
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("apexmini lighting suite")
        self.tray.activated.connect(self._activated)
        self.tray.show()
        self.refresh_profiles()

    def _activated(self, reason):
        if reason == self.tray.Trigger:      # left click
            self.win.show()
            self.win.raise_()

    def refresh_profiles(self):
        from PySide6.QtWidgets import QMenu
        for act in self.profile_menu_actions:
            self.menu.removeAction(act)
            act.deleteLater()
        self.profile_menu_actions = []
        for entry in PR.list_profiles():
            act = self.menu.addAction(entry["name"])
            act.triggered.connect(
                lambda checked=False, name=entry["name"]: self.win._activate_profile(name))
            self.profile_menu_actions.append(act)
            self.menu.insertAction(self.quit_act, act)
        self.menu.removeAction(self.profile_header)
        self.menu.insertAction(self.profile_menu_actions[0] if self.profile_menu_actions
                               else self.quit_act, self.profile_header)


class ChromePanel(QFrame):
    """Custom-painted Metalheart panel: beveled translucent glass, notched
    corner, accent tick, letterspaced title, drop shadow, collapse chevron."""

    HEADER_H = 34

    def __init__(self, title, parent=None, direction="vertical"):
        super().__init__(parent)
        self._title = title.upper()
        self._accent = theme.CYAN
        self._collapsed = False
        self._direction = direction          # 'vertical' (bank) | 'horizontal' (builder)
        self._expanded_size = None
        self._anim = None
        self.setObjectName("chrome")
        self.setFrameShape(QFrame.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QWidget(self)
        self.header.setFixedHeight(self.HEADER_H)
        self.header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(12, 0, 6, 0)
        self.title_label = QLabel(self._title)
        self.title_label.setStyleSheet(
            "background: transparent; color: %s; font-weight: 600; "
            "letter-spacing: 2px; font-size: 13px;" % theme.CYAN)
        hl.addWidget(self.title_label)
        hl.addStretch(1)
        self.collapse_btn = QPushButton("▾" if direction == "vertical" else "▸")
        self.collapse_btn.setFixedSize(26, 24)
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.setStyleSheet(
            "QPushButton { background: transparent; color: %s; border: none; font-size: 13px; }"
            "QPushButton:hover { color: #fff; }" % theme.CYAN)
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        hl.addWidget(self.collapse_btn)
        outer.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setStyleSheet("background: transparent;")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(12, 6, 12, 12)
        self.body_lay.setSpacing(8)
        outer.addWidget(self.body, 1)

        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        # gooey border animation (low fps, only while visible)
        self._phase = 0.0
        self._goo = QTimer(self)
        self._goo.setInterval(66)
        self._goo.timeout.connect(self._goo_tick)
        self._goo.start()

    def _goo_tick(self):
        if self.isVisible() and not self._collapsed:
            self._phase = (self._phase + 0.045) % 1.0
            self.update()

    def _border_point(self, frac, w, h, notch=16.0):
        """point along the panel perimeter at fraction 0..1 (clockwise from
        top-left, following the notched path)."""
        top_len = w - notch
        diag_len = notch * 1.414
        right_len = h - notch
        bot_len = w - 12
        left_len = h - 12
        total = top_len + diag_len + right_len + bot_len + left_len
        d = frac * total
        if d < top_len:
            return d, 0.0
        d -= top_len
        if d < diag_len:
            k = d / diag_len
            return w - notch + k * notch, k * notch
        d -= diag_len
        if d < right_len:
            return w - 0.0, notch + d
        d -= right_len
        if d < bot_len:
            return w - d, h
        d -= bot_len
        if d < left_len:
            return 0.0, h - d
        d -= left_len
        return 0.0, max(0.0, (h - 8) - d * 0.3)

    def _paint_goo(self, p, w, h):
        """shiny liquid-metal comet riding the border (2 heads + tails)."""
        c = QColor(self._accent)
        for k in (0.0, 0.5):
            frac = (self._phase + k) % 1.0
            x, y = self._border_point(frac, w, h)
            r = 16.0
            g = __import__("PySide6.QtGui", fromlist=["QRadialGradient"]).QRadialGradient(x, y, r)
            c1 = QColor(self._accent)
            c1.setAlpha(190)
            g.setColorAt(0.0, c1)
            c2 = QColor(255, 255, 255)
            c2.setAlpha(120)
            g.setColorAt(0.25, c2)
            c3 = QColor(self._accent)
            c3.setAlpha(0)
            g.setColorAt(1.0, c3)
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawEllipse(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(x, y), r, r)

    def set_accents(self, a_hex):
        self._accent = a_hex
        self.title_label.setStyleSheet(
            "background: transparent; color: %s; font-weight: 600; "
            "letter-spacing: 2px; font-size: 13px;" % a_hex)
        self.collapse_btn.setStyleSheet(
            "QPushButton { background: transparent; color: %s; border: none; font-size: 13px; }"
            "QPushButton:hover { color: #fff; }" % a_hex)
        self.update()

    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self.collapse_btn.setText(
            ("▸" if self._collapsed else "▾") if self._direction == "vertical"
            else ("◂" if self._collapsed else "▸"))
        if self._direction == "vertical":
            self._animate("maximumHeight",
                          self.HEADER_H + 8 if self._collapsed else self._expanded_height())
        else:
            self._animate("maximumWidth",
                          self.HEADER_H + 8 if self._collapsed else self._expanded_width())
        QTimer.singleShot(
            220, lambda: self.body.setVisible(not self._collapsed))

    def _expanded_height(self):
        if self._expanded_size is None:
            self._expanded_size = max(self.sizeHint().height(), self.height(), 120)
        return max(90, self._expanded_size)

    def _expanded_width(self):
        if self._expanded_size is None:
            self._expanded_size = max(self.sizeHint().width(), self.width(), 240)
        return max(150, self._expanded_size)

    def _animate(self, prop, target):
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QAbstractAnimation
        self._anim = QPropertyAnimation(self, bytes(prop, "utf-8"))
        self._anim.setDuration(220)
        self._anim.setStartValue(
            self.maximumHeight() if prop == "maximumHeight" else self.maximumWidth())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._anim.deleteLater)
        self._anim.start(QAbstractAnimation.DeleteWhenStopped)
        if prop == "maximumHeight":
            self.setMinimumHeight(min(self.minimumHeight(), target) if self._collapsed else 0)
            if self._collapsed:
                self.setMinimumHeight(target)
        else:
            if self._collapsed:
                self.setMinimumWidth(target)
            else:
                self.setMinimumWidth(0)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        path = QPainterPath()
        notch = 16.0
        path.moveTo(0, 6)
        path.quadTo(0, 0, 6, 0)
        path.lineTo(w - notch, 0)
        path.lineTo(w, notch)
        path.lineTo(w, h - 6)
        path.quadTo(w, h, w - 6, h)
        path.lineTo(6, h)
        path.quadTo(0, h, 0, h - 6)
        path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(24, 29, 39, 228))
        grad.setColorAt(0.5, QColor(17, 21, 29, 216))
        grad.setColorAt(1.0, QColor(11, 14, 20, 230))
        p.fillPath(path, QBrush(grad))

        # bevel: lit top/left, dark bottom/right
        p.setPen(QPen(QColor(90, 104, 124, 150), 1))
        pathL = QPainterPath()
        pathL.moveTo(0.5, h - 8)
        pathL.lineTo(0.5, 6)
        pathL.quadTo(0.5, 0.5, 6, 0.5)
        pathL.lineTo(w - notch, 0.5)
        p.drawPath(pathL)
        p.setPen(QPen(QColor(4, 6, 9, 200), 1))
        pathD = QPainterPath()
        pathD.moveTo(w - notch, 0.5)
        pathD.lineTo(w - 0.5, notch)
        pathD.lineTo(w - 0.5, h - 8)
        pathD.quadTo(w - 0.5, h - 0.5, w - 6, h - 0.5)
        pathD.lineTo(6, h - 0.5)
        pathD.quadTo(0.5, h - 0.5, 0.5, h - 8)
        p.drawPath(pathD)

        self._paint_goo(p, w, h)

        # accent tick under the header + notch edge highlight
        p.setPen(QPen(QColor(self._accent), 2))
        p.drawLine(12, self.HEADER_H - 2, 12 + 26, self.HEADER_H - 2)
        p.setPen(QPen(QColor(self._accent), 1))
        p.drawLine(int(w - notch), 1, int(w - 1), int(notch))
        p.end()


def _app_icon():
    from apexmini_gui import logo
    return logo.icon(256)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    screenshot = None
    if "--screenshot" in argv:
        i = argv.index("--screenshot")
        screenshot = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    app = QApplication(argv)
    app.setApplicationName("apexmini-suite")
    app.setWindowIcon(_app_icon())
    win = MainWindow()
    app.setStyleSheet(theme.build_qss())
    win.show()

    if screenshot:
        def _shot():
            pix = win.grab()
            pix.save(screenshot)
            print("screenshot saved:", screenshot)
            app.quit()
        QTimer.singleShot(600, _shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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
from apexmini_gui import keyboard3d as K3     # noqa: E402
from apexmini_gui import daemon as DM         # noqa: E402


class PreviewWidget(QWidget):
    """Hosts the fake-3D keyboard, repaints at ~30 fps."""

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.k3d = K3.Keyboard3DPreview(self)
        self.accent_a, self.accent_b = theme.CYAN, theme.MAGENTA
        self.setMinimumHeight(320)
        self._t0 = time.monotonic()

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_accents(self, a, b):
        self.accent_a, self.accent_b = a, b

    def _tick(self):
        colors = self.engine.colors()
        self.k3d.colors = colors
        # decay press glows
        for u in list(self.k3d.press_glow):
            self.k3d.press_glow[u] *= 0.92
            if self.k3d.press_glow[u] < 0.02:
                del self.k3d.press_glow[u]
        self.update()

    def key_pressed(self, usage):
        self.k3d.press_glow[usage] = 1.0

    def paintEvent(self, ev):
        p = QPainter(self)
        self.k3d.paint(p, self.width(), self.height(), self.accent_a, self.accent_b,
                       time.monotonic() - self._t0)
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
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        title = QLabel("PROFILE BUILDER")
        title.setObjectName("title")
        lay.addWidget(title)

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
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
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
        self.btn_delete.clicked.connect(self._delete)
        self.btn_import.clicked.connect(self._import)
        self.btn_export.clicked.connect(self._export)

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
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(10)

        mid = QHBoxLayout()
        # left: preview
        self.preview = PreviewWidget(self.engine)
        mid.addWidget(self.preview, 3)

        # right: builder
        self.builder = BuilderPanel()
        mid.addWidget(self.builder, 2)
        root.addLayout(mid, 1)

        # bottom: bank
        self.bank = BankPanel()
        self.bank.setMaximumHeight(180)
        root.addWidget(self.bank, 1)

        # status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel()
        sb.addWidget(self.status_label, 1)
        self.keep_running_cb = QCheckBox("keep lighting when window closes (background)")
        self.keep_running_cb.setChecked(True)
        sb.addPermanentWidget(self.keep_running_cb)

        # wiring
        self.builder.changed.connect(self._live_apply)
        self.bank.apply_requested.connect(self._activate_profile)
        self.bank.refresh()

        self.feed = None
        self.marker_timer = QTimer(self)
        self.marker_timer.setInterval(500)
        self.marker_timer.timeout.connect(self._check_marker)
        self.marker_timer.start()

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

    def _refresh_accents(self):
        aa, ab = theme.accents_for_profile(self.current_profile)
        self.preview.set_accents(aa, ab)
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
        self.preview.key_pressed(usage)

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
        if self.keep_running_cb.isChecked() and self.stop_event is not None:
            # leave streaming alive in background: detach by hiding to tray-ish
            ev.ignore()
            self.hide()
            self.status_label.setText("hidden — still lighting; reopen from taskbar/dock or kill process")
            return
        if self.stop_event:
            self.stop_event.set()
        if self.feed:
            self.feed.stop()
        super().closeEvent(ev)


def _app_icon():
    pix = QPixmap(64, 64)
    pix.fill(QColor("#0a0d12"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#ff6a00"))
    p.setPen(QColor("#22d3ee"))
    p.drawRoundedRect(14, 14, 36, 36, 8, 8)
    p.end()
    return QIcon(pix)


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

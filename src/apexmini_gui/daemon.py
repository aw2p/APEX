#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless profile daemon.

Owns the keyboard, streams the active profile forever, survives replugs,
and switches profiles whenever ~/.config/apexmini/active.json changes
(so `apexmini-suite use NAME`, the tray menu, or the GUI can switch it).

    python -m apexmini_gui daemon
"""

import json
import os
import signal
import sys
import threading
import time

from apexmini import profiles as PR
from apexmini import engine as EN
from apexmini import inputfeed


def pidfile_path():
    return os.path.join(PR.config_dir(), "daemon.pid")


def write_pidfile():
    os.makedirs(PR.config_dir(), exist_ok=True)
    with open(pidfile_path(), "w") as f:
        f.write(str(os.getpid()))


def clear_pidfile():
    try:
        os.remove(pidfile_path())
    except OSError:
        pass


def daemon_running():
    try:
        with open(pidfile_path()) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


class Daemon:
    def __init__(self, verbose=False):
        self.engine = EN.Engine()
        self.stop = threading.Event()
        self.verbose = verbose
        self._active_name = None
        self._marker_mtime = 0.0

    def _watch_marker(self):
        """Poll the active-profile marker; switch on external changes."""
        while not self.stop.is_set():
            try:
                if os.path.exists(PR.active_marker_path()):
                    m = os.path.getmtime(PR.active_marker_path())
                    if m != self._marker_mtime:
                        self._marker_mtime = m
                        name = PR.get_active_name()
                        if name and name != self._active_name:
                            try:
                                prof = PR.load(name)
                                self.engine.set_profile(prof)
                                self._active_name = name
                                print("[daemon] profile ->", name, flush=True)
                            except (OSError, ValueError) as e:
                                print("[daemon] bad profile %r: %s" % (name, e), flush=True)
            except OSError:
                pass
            self.stop.wait(0.4)

    def run(self):
        write_pidfile()
        print("[daemon] apexmini daemon up (pid %d)" % os.getpid(), flush=True)
        # start with the last active profile, if any
        name = PR.get_active_name()
        if name:
            try:
                self.engine.set_profile(PR.load(name))
                self._active_name = name
                self._marker_mtime = os.path.getmtime(PR.active_marker_path())
            except (OSError, ValueError):
                pass
        threading.Thread(target=self._watch_marker, daemon=True).start()
        feed = inputfeed.TypingFeed(self.engine.note_press).start()
        try:
            self.engine.stream_forever(self.stop, on_status=lambda s: print("[daemon]", s, flush=True),
                                       verbose=self.verbose)
        finally:
            clear_pidfile()
            print("[daemon] stopped, LEDs released", flush=True)


def main(argv=None):
    argv = argv or sys.argv[1:]
    verbose = "-v" in argv or "--verbose" in argv
    d = Daemon(verbose=verbose)
    signal.signal(signal.SIGTERM, lambda *_: d.stop.set())
    signal.signal(signal.SIGINT, lambda *_: d.stop.set())
    d.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

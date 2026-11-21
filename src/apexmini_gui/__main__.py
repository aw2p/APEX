#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apexmini-suite command line.

    python -m apexmini_gui              # same as `gui`
    python -m apexmini_gui gui          # window (in-process engine)
    python -m apexmini_gui daemon       # headless daemon (own LEDs until stopped)
    python -m apexmini_gui use NAME     # switch profile (daemon or marker)
    python -m apexmini_gui list         # saved profiles
    python -m apexmini_gui stop         # stop a running daemon
    python -m apexmini_gui status       # what's running / active profile
"""

import os
import signal
import sys

from apexmini import profiles as PR
from apexmini_gui import daemon as DM


def cmd_list(_args):
    entries = PR.list_profiles()
    if not entries:
        print("no profiles saved yet (%s)" % PR.profiles_dir())
        return
    active = PR.get_active_name()
    for e in entries:
        mark = " *" if e["name"] == active else ""
        print("%-24s %-10s%s" % (e["name"], e["profile"]["base"]["type"], mark))


def cmd_use(args):
    if not args:
        sys.exit("usage: apexmini-suite use NAME")
    name = args[0]
    try:
        PR.load(name)
    except (OSError, ValueError) as e:
        sys.exit("profile %r not loadable: %s" % (name, e))
    PR.set_active_name(name)
    pid = DM.daemon_running()
    if pid:
        print("switched; daemon pid %d will pick it up within ~0.5 s" % pid)
    else:
        print("switched (no daemon running; next gui/daemon start uses it)")
    return 0


def cmd_stop(_args):
    pid = DM.daemon_running()
    if not pid:
        print("no daemon running")
        return 0
    os.kill(pid, signal.SIGTERM)
    print("sent SIGTERM to daemon pid %d" % pid)
    return 0


def cmd_status(_args):
    pid = DM.daemon_running()
    print("daemon : %s" % ("running (pid %d)" % pid if pid else "not running"))
    active = PR.get_active_name()
    print("active : %s" % (active or "<none>"))
    print("profiles: %d saved in %s" % (len(PR.list_profiles()), PR.profiles_dir()))
    return 0


def cmd_gui(_args):
    from apexmini_gui import main_window
    return main_window.main()


def cmd_daemon(args):
    return DM.main(args)


COMMANDS = {
    "gui": cmd_gui,
    "daemon": cmd_daemon,
    "use": cmd_use,
    "stop": cmd_stop,
    "status": cmd_status,
    "list": cmd_list,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "gui"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    fn = COMMANDS.get(cmd)
    if not fn:
        sys.exit("unknown command %r (try: gui|daemon|use|stop|status|list)" % cmd)
    return fn(argv) or 0


if __name__ == "__main__":
    sys.exit(main())

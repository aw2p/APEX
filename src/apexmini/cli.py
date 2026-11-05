#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apexmini — RGB control for the SteelSeries Apex Pro Mini Wireless on Linux.

First-build features: single colour, brightness, per-key colours, software
effects, read-only info (firmware, brightness, battery on the dongle).

Design invariants:
    * NO flash/profile writes.  opcodes in protocol.FORBIDDEN are refused at
      every layer — this project never touches onboard storage.
    * On exit we hand the LEDs back to the firmware (release), so the
      keyboard behaves like before we touched it.
    * Every packet is logged when --verbose is set.
"""

import argparse
import signal
import sys
import threading
import time
import os

from . import device as D
from . import keymap as K
from . import effects as E
from . import protocol as P


# ---------------------------------------------------------------------------
def _mkparser():
    ap = argparse.ArgumentParser(
        prog="apexmini",
        description="Apex Pro Mini Wireless RGB controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--quiet", "-q", action="store_true")
    ap.add_argument("--interface", help="force a specific hidraw node (see `list`)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="enumerate Apex control endpoints + info")

    sub.add_parser(
        "info",
        help="firmware / brightness / battery (0x90 / 0xA3 / BC-D2 or 92)")

    p = sub.add_parser("color", help="all keys one colour (direct mode)")
    p.add_argument("color", help="'red', '#RRGGBB', 'RRGGBB'")
    p.add_argument("--seconds", type=float, default=None, help="hold N seconds then release (test mode)")

    sub.add_parser("off", help="all keys black (still owns LEDs)")
    sub.add_parser("onboard", help="release LED ownership to the on-board profile")

    p = sub.add_parser("brightness", help="hardware brightness 0..10 (read-only if no arg)")
    p.add_argument("level", type=int, nargs="?", default=None, choices=range(0, 11))

    p = sub.add_parser("key", help="set per-key colours, e.g. `key a=ff0000 spc=cyan`")
    p.add_argument("specs", nargs="+", metavar="KEY=COLOR")
    p.add_argument("--seconds", type=float, default=None)

    sub.add_parser("keys", help="list all known key names + usage bytes")

    p = sub.add_parser("effect", help="run a software effect (Ctrl-C releases the LEDs)")
    p.add_argument("name", choices=["static", "breathing", "spectrum", "wave", "reactive", "candle"])
    p.add_argument("--color", default="red", help="for static/breathing/reactive (candle ignores it)")
    p.add_argument("--hz", type=float, default=18.0)
    p.add_argument("--seconds", type=float, default=None, help="debug: stop after N seconds")
    p.add_argument("--evdev", default=None, help="input event node for reactive (e.g. /dev/input/event4)")

    p = sub.add_parser("probe", help="send candidate frames (opcode) & report device answers")
    p.add_argument("--color", default="#FF0000")
    p.add_argument("--seconds", type=float, default=4.0, help="hold per candidate before releasing")

    p = sub.add_parser("test-frame", help="low-level: send ONE raw direct frame & print reply")
    p.add_argument("opcode", help="hex opcode, e.g. 0x61")
    p.add_argument("--color", default="red")
    p.add_argument("--count", type=int, default=None, help="override number of entries")
    p.add_argument("--answer-wait", type=int, default=250, help="ms to wait for a reply")

    p = sub.add_parser("emit", help="dev only: print the exact bytes we would send, no device needed")
    p.add_argument("what", choices=["frame"], nargs="?")
    p.add_argument("opcode", help="hex opcode")
    p.add_argument("--color", default="red")
    return ap


# ---------------------------------------------------------------------------
def _choose_device(args):
    devs = D.find_control_devices()
    if not devs:
        sys.exit("No Apex control endpoint found (dongle/cable connected? udev rule installed?)")
    if len(devs) > 1:
        sys.stderr.write("%d control endpoints found:\n" % len(devs))
        for i, d in enumerate(devs):
            sys.stderr.write("  [%d] %s\n" % (i, d))
        if args.interface:
            devs = [d for d in devs if d.hidraw == args.interface]
            if not devs:
                sys.exit("interface %r not among candidates (use `list`)" % args.interface)
        else:
            sys.exit("multiple candidates; use --interface hidrawN to pick (see `list`)")
    return devs[0]


def _open_and_probe(args):
    dev = D.ApexDevice(_choose_device(args), verbose=bool(args.verbose))
    dev.connect()
    return dev


def _full_table(color_map=None):
    """The full 112-entry table (OpenRGB-proven convention. firmware ignores
    usages it doesn't have; per-key addressed by usage id)."""
    color_map = color_map or {}
    return [(u, *color_map.get(u, (0, 0, 0))) for u in K.OPENRGB_DIRECT_KEYS]


# --- commands -----------------------------------------------------------
def cmd_list(args):
    devs = D.find_control_devices()
    if not devs:
        print("none found")
        return
    for d in devs:
        print("%-8s pid=0x%04X %-34s transport=%-8s feature=%sB" % (
            (d.hidraw or "?"), d.pid, d.description, d.transport, getattr(d, "feature_len", "?")))


def cmd_info(args):
    dev = _open_and_probe(args)
    try:
        print("device     : %s" % dev.entry)
        print("firmware   : %s" % (dev.fw or "<no reply>"))
        print("brightness : %s/10" % dev.get_hardware_brightness())
        batt = dev.query_battery()
        if batt:
            print("battery    : %r" % batt)
    finally:
        dev.release_leds()
        dev.close()


def cmd_color(args):
    dev = _open_and_probe(args)
    opcode = dev.pick_opcode_candidates()[0]
    try:
        dev.send_direct_frame(opcode, _full_table({u: E.parse_color(args.color) for u in K.OPENRGB_DIRECT_KEYS}))
        if args.seconds:
            time.sleep(args.seconds)
            dev.release_leds()
            return
        print("set. run `apexmini onboard` (or press Ctrl-C nothing) when done.")
    finally:
        if args.seconds is None:
            pass
        dev.close()


def cmd_off(args):
    dev = _open_and_probe(args)
    try:
        dev.send_direct_frame(dev.pick_opcode_candidates()[0], _full_table())
    finally:
        dev.close()


def cmd_onboard(args):
    dev = _open_and_probe(args)
    try:
        dev.release_leds()
        print("LEDs handed back to on-board firmware.")
    finally:
        dev.close()


def cmd_brightness(args):
    dev = _open_and_probe(args)
    try:
        if args.level is None:
            b = dev.get_hardware_brightness()
            print("brightness : %s/10" % b)
        else:
            dev.set_hardware_brightness(args.level)
            time.sleep(0.15)
            b = dev.get_hardware_brightness()
            print("set -> %s/10 (read-back)" % b)
    finally:
        dev.release_leds()
        dev.close()


def cmd_key(args):
    perkey = {}
    for spec in args.specs:
        if "=" not in spec:
            sys.exit("bad spec %r (want KEY=COLOR)" % spec)
        k, c = spec.split("=", 1)
        usage = K.usage_for_name(k)
        perkey[usage] = E.parse_color(c)
    dev = _open_and_probe(args)
    try:
        dev.send_direct_frame(dev.pick_opcode_candidates()[0], _full_table(perkey))
        if args.seconds:
            time.sleep(args.seconds)
            dev.release_leds()
    finally:
        if args.seconds is None:
            pass
        dev.close()


def cmd_keys(args):
    for name in sorted(K.NAME_TO_USAGE):
        print("%-12s 0x%02X" % (name, K.NAME_TO_USAGE[name]))


# --- evdev tap for reactive ---------------------------------------------
def _find_keyboard_event_nodes():
    """Locate evdev nodes of our keyboard via sysfs."""
    import glob as _glob
    nodes = []
    for dev in os.listdir("/sys/class/hidraw"):
        path = os.path.realpath(os.path.join("/sys/class/hidraw", dev))
        parent = os.path.dirname(os.path.dirname(path))   # 0003:1038:XXXX dir
        if ":1038:" not in parent:
            continue
        base = parent
        while base and base != "/" and not os.path.isdir(os.path.join(base, "input")):
            base = os.path.dirname(base)
        if not base or base == "/":
            continue
        for inp in os.listdir(os.path.join(base, "input")):
            for cand in _glob.glob(os.path.join(base, "input", inp, "event*")):
                nodes.append("/dev/" + os.path.basename(cand))
    return nodes


def _start_input_listener(effect, event_path=None):
    """Raw evdev reader (no third-party packages).  Feeds key-down events into
    effect.react(); needs read access to the event node."""
    import os as _os
    import select
    import struct as _struct

    if event_path is None:
        cands = _find_keyboard_event_nodes()
        if not cands:
            sys.stderr.write("no evdev node found for the keyboard; pass --evdev /dev/input/eventN\n")
            return None
        event_path = cands[0]
        sys.stderr.write("listening on %s\n" % event_path)

    stopped = threading.Event()
    EV_KEY = 0x01
    EVENT_FMT = "llHHi"          # struct input_event on 64-bit Linux
    EVENT_SIZE = _struct.calcsize(EVENT_FMT)

    def run():
        try:
            fd = _os.open(event_path, _os.O_RDONLY | _os.O_NONBLOCK)
        except OSError as e:
            sys.stderr.write("cannot open %r: %s\n" % (event_path, e))
            return
        partial = b""
        while not stopped.is_set():
            try:
                r, _w, _x = select.select([fd], [], [], 0.25)
            except OSError:
                break
            if not r:
                continue
            try:
                data = _os.read(fd, 4096)
            except BlockingIOError:
                continue
            except OSError:
                break
            if not data:
                continue
            partial += data
            while len(partial) >= EVENT_SIZE:
                (_tv_s, _tv_u, etype, code, value) = _struct.unpack(
                    EVENT_FMT, partial[:EVENT_SIZE])
                partial = partial[EVENT_SIZE:]
                if etype != EV_KEY or value != 1:    # key-down only
                    continue
                if 59 <= code <= 68:                 # KEY_F1..F10 -> 0x3A..
                    usage = 0x3A + (code - 59)
                elif 30 <= code <= 82:               # most printable keys
                    usage = 4 + (code - 30)          # KEY_A(30) -> 0x04
                elif code == 14:                     # KEY_GRAVE -> 0x35
                    usage = 0x35
                elif code == 1:                      # KEY_ESC
                    usage = 0x29
                elif code in (87, 88):               # F11, F12
                    usage = 0x43 + (code - 87)
                elif code == 111:
                    usage = 0x52                     # up
                elif code == 114:
                    usage = 0x50                     # left
                elif code == 115:
                    usage = 0x51                     # down
                elif code == 113:
                    usage = 0x4F                     # right
                else:
                    continue
                effect.react(usage)
        _os.close(fd)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    class _L:
        def stop(self):
            stopped.set()
    return _L()


def cmd_effect(args):
    dev = _open_and_probe(args)
    opcode = dev.pick_opcode_candidates()[0]
    ks = K.OPENRGB_DIRECT_KEYS
    c = E.parse_color(args.color)
    listener = None
    if args.name == "static":
        fx = E.Static(ks, c)
    elif args.name == "candle":
        fx = E.Candle(ks)
    elif args.name == "breathing":
        fx = E.Breathing(ks, c)
    elif args.name == "spectrum":
        fx = E.Spectrum(ks)
    elif args.name == "wave":
        fx = E.Wave(ks)
    else:  # reactive
        fx = E.Reactive(ks, color=c)
        listener = _start_input_listener(fx, args.evdev)  # may print hint if missing
    pump = E.FramePump(dev, opcode, ks, fx, hz=args.hz)

    def _omi():
        pump.stop()
    signal.signal(signal.SIGINT, _omi)
    signal.signal(signal.SIGTERM, _omi)
    try:
        pump.run(stop_after=args.seconds)
    finally:
        if args.seconds is None:
            dev.release_leds()
        else:   # debug mode: restore, then release
            dev.send_direct_frame(opcode, _full_table())
            dev.release_leds()
        if listener:
            listener.stop()
        dev.close()


# --- probe --------------------------------------------------------------
def cmd_probe(args):
    dev = _open_and_probe(args)
    opcode_list = dev.pick_opcode_candidates()
    try:
        print("candidates: %s (order auto-picked from transport=%s)" % (
            [hex(o) for o in opcode_list], dev.entry.transport))
        print("feature_len = %d -> total_len = %d, max entries = %d" % (
            dev.feature_len, dev.feature_len + 1, P.key_table_len(dev.feature_len + 1)))
        for opcode in opcode_list:
            cmap = {u: E.parse_color(args.color) for u in K.OPENRGB_DIRECT_KEYS}
            print("\n-- opcode 0x%02X: hold %s for %.1fs — LOOK AT THE BOARD --" % (opcode, args.color, args.seconds))
            dev.send_direct_frame(opcode, _full_table(cmap))
            time.sleep(args.seconds)
            # release and clear the reply queue to start fresh
            dev.release_leds()
            time.sleep(0.2)
            for _ in range(3):
                r = dev.read_input(250)
                if not r:
                    break
                print("   notes: %s" % r.hex())
        print("\ndone.")
    finally:
        dev.release_leds()
        dev.close()


def cmd_test_frame(args):
    opcode = int(args.opcode, 16)
    dev = _open_and_probe(args)
    try:
        if opcode in P.FORBIDDEN:
            print("REFUSED: opcode 0x%02X is in the forbid list (profile/flash writes).\n" % opcode)
            return
        entries = _full_table({u: E.parse_color(args.color) for u in K.OPENRGB_DIRECT_KEYS})
        if args.count is not None:
            entries = entries[:max(0, args.count)]
        print("send: opcode=0x%02X entries=%d total_len=%d" % (
            opcode, len(entries), dev.feature_len + 1))
        dev.send_direct_frame(opcode, entries)
        r = dev.read_input(args.answer_wait)
        print("reply: %s" % (r.hex() if r else "<none>"))
    finally:
        dev.release_leds()
        dev.close()


def cmd_emit(args):
    """Print exact bytes that would be sent, no device needed (offline tests)."""
    opcode = int(args.opcode, 16)
    entries = _full_table({u: E.parse_color(args.color) for u in K.OPENRGB_DIRECT_KEYS})
    for total_len in (642, 513):     # our dongle's feature report; Apex9-Mini size for reference
        buf = P.build_direct_frame(opcode, entries, total_len)
        print("-- total_len=%d entries=%d" % (total_len, len(entries)))
        print("   head:      " + buf[:24].hex())
        print("   payload00: " + buf[3:15].hex())
        print("   tail:      " + buf[-8:].hex())


# --- dispatch ------------------------------------------------------------
COMMANDS = {
    "list": cmd_list,
    "info": cmd_info,
    "color": cmd_color,
    "off": cmd_off,
    "onboard": cmd_onboard,
    "brightness": cmd_brightness,
    "key": cmd_key,
    "keys": cmd_keys,
    "effect": cmd_effect,
    "probe": cmd_probe,
    "test-frame": cmd_test_frame,
    "emit": cmd_emit,
}


def main(argv=None):
    ap = _mkparser()
    args = ap.parse_args(argv)
    return COMMANDS[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())

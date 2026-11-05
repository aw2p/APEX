# Apex Mini RGB — an Apex Pro Mini Wireless lighting controller

Standalone, fully-standalone tool that takes control of the **SteelSeries Apex
Pro Mini Wireless** keyboard lighting *directly over USB HID* on Linux — no
SteelSeries GG, no Windows VM, no onboard-profile gymnastics.

Working out of scope for "GG forever" setups: single solid color, brightness,
per-key colors, and a handful of software effects (breathing / spectrum /
wave / reactive).

## Quick start

```bash
# one-time (asks for sudo):
sudo bash setup/00-grant-access.sh

# then:
cd src
python3 ../tools/apexmini list         # find your control endpoint
python3 ../tools/apexmini info         # firmware/brightness/battery probe
python3 ../tools/apexmini color '#gaussianblue'   # (use a hex/name)
```

Daily driver:

```bash
apexmini color ff8800          # all keys orange
apexmini key a=00ff00 s=00ff00 d=00ff00      # per-key (WASD green, rest black)
apexmini effect spectrum --hz 30             # rainbow sweep, streamed
apexmini onboard                             # release LEDs to onboard profile
```

## Hard safety rules

* The tool **never writes flash / onboard profile storage.** All profile
  relevant opcodes (0x83/0x02/0x03/0x42/0x43/0xE6/0x53/0x68) are banned in the
  core builder (`apexmini/protocol.py::FORBIDDEN`) and tests enforce it.
* On exit, LED ownership is handed back to the firmware (direct frames are
  "temporary"), so your onboard profile keeps working.

## Status — honest floor

| Function   | Wired-dongle on `0x1624` | Notes |
|------------|-----------------|-------|
| Endpoint detect | ✅ live-verified | FFC0 / iface 1.3, 642-B feature |
| Firmware query | ⏳ needs 1 key press to test | output `00 90` reply style like TKL family |
| Direct frame format | ✅ structurally proven | cross-checked vs OpenRGB & OpenGG |
| Direct frame wire test | ⏳ | needs a 1-minute look at the keys |
| Brightness | ⏳ | 0x23 / 0xA3 derived from a recent OpenRGB patch |
| Battery | ⏳ | BC/D2 (dongle), from OpenGG's capture notes |

See `docs/RESEARCH.md` for everything we learned about the protocol, and
`docs/RUNBOOK-TESTING.md` for the short list of what to try first after the
udev rule is installed.

## Layout

```
docs/RESEARCH.md          protocol/protocol findings (the big doc)
docs/RUNBOOK-TESTING.md   what to run when testing on hardware
docs/cheatsheet.md        one-page wire-name cheat sheet
src/apexmini/hidapi.py    ctypes HID layer (libhidapi-hidraw)
src/apexmini/reportdesc.py HID report descriptor parser (sysfs)
src/apexmini/protocol.py  packet builders + forbidden list
src/apexmini/device.py    discovery / open / transport logic
src/apexmini/keymap.py    name<->HID-usage maps
src/apexmini/effects.py   effect engine + color helpers
src/apexmini/cli.py       CLI
tools/apexmini            launcher
tests/test_offline.py     offline unit tests (no hardware)
udev/99-apexmini.rules    access grant
setup/00-grant-access.sh  sudo installer for the rule
```

## Credits / prior art this is built upon

* **OpenRGB** — SteelSeries Apex driver (Gen1/Gen2/Gen3 direct modes, 0x4B init,
  key tables, packet sizing; GPL2 project by CalcProgrammer1, Filipe S.).
* **OpenGG (GUHPY)** — the wireless Gen 3 protocol reference figuring out the
  0x61/0x62 RGB ownership dance, BC/D2 battery/change telemetry.
* **ssgg (Ven0m0)** — Rust SteelSeries replacement whose key tables and packet
  builders were a cross-check second opinion.
* **ApexCtl (AstroSnail)** — the OG Apex Linux controller (gen-0 family).

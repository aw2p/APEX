# Runbook — what to test once access is granted

Everything below assumes `sudo bash setup/00-grant-access.sh` has been run
(reboot not needed; `udevadm trigger` already reprobed), and you are in
`/home/vamp/Projects/STEELSERIES`.

Total budget: ~4 minutes.  Every step is read-mostly; the only *write* is a
single 642-byte lighting frame per candidate, and the runner-up step always
releases the LEDs right after, so nothing persists.

## 0. sanity

```bash
cd src
python3 ../tests/test_offline.py        # should be all OK
python3 -m apexmini.reportdesc --hidraw hidraw7   # expect: page=FFC0 … feature(242): 641
```

## 1. read-only probe (no lighting change)

```bash
python3 ../tools/apexmini list
python3 ../tools/apexmini info
```
Expected: the device line names `Apex Pro Mini Wireless (Dongle)`, transport
`wireless`, feature 641; then a firmware string or `<no reply>`, a brightness
value 0..10, and a battery dict.  Record what you see (this tells us firmware
generation and whether `0x90`/`0xA3`/`BC+D2` talk on your model).

## 2. colour confirmation (the exciting one)

```bash
python3 ../tools/apexmini probe --color '#00FF00'
```
It tries the three candidate opcodes in turn (0x61 → 0x40 → 0x3A), holding
green for 4s each, releasing between candidates and dumping any reply bytes.
If you see the keyboard turn green on one of the candidates, that's the wire
protocol confirmed — tell me which opcode did it, and whether the whole
keyboard or only some keys lit (keys that stay dark tell me the firmware uses
a different key-table count and we adjust `count`).

### Known-good outcomes and what they mean

* **Green = full board on 0x61** → ideal: the OpenRGB/TKL-wireless frame is
  exactly right; we lock it in as default.
* **Green = full board on 0x40** → the dongle treats your wired session as
  gen-2; I'll flip the candidate order.
* **Only some keys green** → count/table mismatch; I switch to count=84
  (GG-style) or the Mini subset and re-run.
* **No reply, no colour anywhere + no errors** → the feature write is being
  silently ignored; next experiment is init `0x4B` at full length
  (642) before frames — one more `apexmini probe` run with that enabled.

## 3. brightness + per-key

```bash
python3 ../tools/apexmini brightness 6
python3 ../tools/apexmini key a=ff0000 s=ff0000 d=ff0000     # WASD… red, rest stays dark? note:
python3 ../tools/apexmini color 00aaff
python3 ../tools/apexmini onboard                             # hand LEDs back to the profile
```
The `key` command lights the *named* keys red and leaves the *remaining*
entries of the 112-entry table black — if everything else was already dark,
the result is "only A S D red".

## 4. effects

```bash
python3 ../tools/apexmini effect spectrum
# Ctrl-C when done — it releases the LEDs back automatically.
```

## 5. report sheet — copy this list and fill it in

```
firmware string:            …
ack after color (broadcast):…
which opcode lit the board:  …
full-board or partial:       …
brightness read-back:        …
battery bytes (dongle):      …
any weird colours:           …
anything else:               …
```

## What actually gets written by this project

| feature | writes |
|---|---|
| color / off / key / effect | one 642-byte feature report (report-id 0, opcode 0x61 or 0x40),  to zero |
| onboard | one 65-byte OUT report `00 62` |
| brightness | 65-byte OUT `00 23 N` + an optional `00 A3` read |
| info | `00 90` / `00 BC`/`00 D2` reads only |

Nothing writes flash, onboard profiles, or anything outside the
`protocol.FORBIDDEN` guard.

# Apex Pro Mini Wireless — protocol research notes

*Last updated: tonight, while the user was out; verified against live hardware
only where marked ✅.*

## 1. What the keyboard is

SteelSeries Apex Pro Mini Wireless ("0x1624 dongle / 0x1626 BT / wired mini
0x1621-family").  OptiPoint analog switches like the Apex Pro TKL 2023; same
Hardware generation.  Officially only changeable on Windows via SteelSeries
GG; no Linux path has shipped (OpenRGB's own table misses the Mini Wireless
PIDs — that hole is what this tool fills).

All findings cross-checked across three reverse-engineered code trees +
published docs (citable sources at the bottom).

## 2. Live enumeration (✅ measured tonight)

`lsusb` shows **1038:1624 SteelSeries ApS Apex Pro Mini Wireless** — that PID
is the **2.4 GHz dongle** (per community PID tables), with 6 HID interfaces:

| hid iface | sys node | on desk | content |
|---|---|---|---|
| 1.0 | `0003:1038:1624.002B` | hidraw2 | mouse+consumer pointer-ish collection with a tiny 2-byte 0xFFC1 extra report |
| 1.1 | `0003:1038:1624.002C` | hidraw3 | boot keyboard |
| 1.2 | `0003:1038:1624.002D` | hidraw4 | consumer (page 000C) |
| 1.3 | `0003:1038:1624.002E` | hidraw7 | **the control/lighting interface** — Usage Page 0xFFC0, Usage 1 |
| 1.4 | `0003:1038:1624.002F` | hidraw8 | notification channel — Usage Page 0xFFC1 (input 64 B) |
| 1.5 | `0003:1038:1624.0030` | hidraw9 | second keyboard collection with a 32-byte NKRO-ish bitmap |

The control interface (1.3) declares:
```
Usage(X)      F0  = Input   64 bytes
Usage(X)      F1  = Output  64 bytes
Usage(X)      F2  = Feature 641 bytes   <- report data bytes
                          (+1 report id byte == 642 total on the wire)
```

**That 642-byte feature report is the number that matters** — it makes this
dongle structurally the *same lighting endpoint family as the Apex Pro TKL
2023 Wireless*, whose feature length is 642 in OpenGG's documentation.  (TIL:
the wire byte `96 81 02` = little-endian count 0x0281 = 641.)

## 3. Lighting = "direct frames"

Direct-mode packets put raw per-key colours in a single feature report:

```
[00][opcode][count][(usage)(R)(G)(B)] * count | zero padding to feature length
```

Candidate opcodes, ordered for our wireless transport:

| opcode | family | notes |
|---|---|---|
| `0x61` | Apex 2023 Wireless (OpenRGB)/wireless TKL (Gen3 OpenGG) | our primary candidate |
| `0x40` | Apex 2023/Gen 3 wired | fallback; also used by Apex 9 (incl. Mini) |
| `0x3A` | legacy Apex 7/Pro/5/7TKL | last resort; same frame layout |

`count` = number of (usage,R,G,B) quadruples.  Proven practice on these
keyboards (OpenRGB sends the full ~112-entry generic table; SSGG's GG-capture
of the wired TKL 2023 shows 0x54=84 entries in GG's own order): firmware
ignores usages it does not carry, colours are *addressed by usage id*, so
packing order does not matter for correctness of per-keycolour.

Key tables used (from OpenRGB & SSGG):
* 112-entry generic Apex codes (0x04..0x52, 0x64, 0xE0..E7, 0xF0, 0x31, 0x87..0x8B, 0x53..0x63, 0xFB logo)
* 84-entry GG-2023-wired order (for reference)

Analog keys have separate per-key settings channels (actuation etc.) — out of
scope for v1.

## 4. Controller sequence on this dongle

Derived from OpenRGB's Apex 2023/Gen3 controller + OpenGG's protocol doc:

1. **Firmware query**: OUT report `[00][90]` (65 B) on the control iface;
   read Interrupt input back on the same iface, expect `[90][00][version...
   ASCII like "3.19.7"]`.  OpenGG notes the reply byte layout is
   `[opcode][status/data][...]`.
2. **Init (0x4B)** feature report `[00][4B]+ zeros`; once after connect on
   Gen2/Gen3 firmware.  The Apex-9-Mini present uses 65-byte for this; we try
   65 bytes first then full-length, both benign.
3. **Direct frames** as above; NO ack reply for them per OpenGG ("temporary
   RGB, no ACK"); lighting "owned" until released.
4. **Release**: `00 62` OUT (wireless) — hands lighting back to onboard
   profile; wired counterparts use `00 41` (clear).  We choose per transport.
   Neither is destructive; OpenRGB's destructor uses 41 for everything.
5. **Brightness**: `00 23 [0..10]` OUT; read back with `00 A3`: reply
   `[A3][00][value]` (v derived from a 2026 OpenRGB patch's probing note).
6. **Battery (dongle only)**: `00 BC` OUT → connection report; then
   `00 D2` OUT → battery bytes (raw; OpenGG says reply second byte is data
   for D2, not status).
7. **Notifications channel (FFC1 input 64 B)**: `[type][value]` where
   type 01 = brightness, 02 = profile-switch (made by Fn keys, not by host).

## 5. Never-touch list

On-board profiles/flash (nothing here is a lighting command):
```
0x83 read profile block      0x02/0x03 receiver erase/write
0x42/0x43 keyboard erase/write (tunnelled)   0xE6 validate   0x53/0x68 activate
```
These live ONLY in OpenGG's capture writeup; implementing them invites
flanked bricks.  Our `protocol.FORBIDDEN` set refuses to build them; unit
tests enforce that these cannot sneak in even from code I don't write.

## 6. Open questions before hardware-test

1. Does the Mini Wireless *dongle* require the `0x4B` init at all
   (wired TKL 2023 did not in a GG capture; OpenRGB sends it for all Gen2/3)?
   → `probe` experiments.
2. Does 112-entry frame size work with the mini's firmware when it answers
   0x54 (84) on the TKL wired?  → try count=112 first; if the board ignores
   us or rejects, try count=84, then count=63 (our_MinI_KEYS list).
3. Does feature length mismatch (we send 642, matching the descriptor) fully
   enable the frame?  The kernel enforces max 642 for hidraw feature writes —
   always derived at runtime from sysfs so it self-corrects for other modes.
4. Do ACK replies come back on the input queue after `0x61` frames (OpenGG
   says no; OpenRGB seems to assume none)?  → observe in `probe`.

## 7. Hardware internals (bonus, from the Zephyr project's board docs)

* MCU: STM32L412RB (Cortex-M4), LED driver: **Lumissil IS31FL3743B** on SPI2,
  onboard config store: **FMSH FM25Q128** 128Mbit serial flash.
* 61 keys on QWERTY (62 with the AZERTY ISO-Enter version), 5-row × 14-col
  key matrix.  The IS31FL3743B has 18 CS lines over the strings of RGB LEDs —
  per-key LED addressing physically goes through that driver.
* The important consequence for us: the host protocol does NOT talk to the
  IS31 driver directly; it walks a higher-level "usage id → LED slot" map —
  which is exactly what the direct frames do, and why unknown usages are
  simply ignored.
* The Zephyr board exists because someone re-implemented the keyboard
  firmware from scratch (requires unsoldering the ROP protection!) — good
  confirmation that the flash-erase/programming area is genuinely risky
  territory we stay out of.

## 8. Sources

* OpenRGB `SteelSeriesApexController.{h,cpp}` (GitHub mirror,
  commit 19112cde) — frame layout, opcodes 0x3A/0x40/0x61, PF lengths, init.
* OpenRGB MR !3142 (filipesn, Apex Pro TKL 2023 Wired/Wireless — new Gen2/Gen3
  protocol) and MR !3143 (metroite, TKL Gen 3); MR !3423/!3434 (Apex 9 length
  corrections); MR !3432 (brightness register 0x23/A3; FFC1 notifications).
* OpenRGB MR !3271 (Gen 3 quirks consolidated into the Apex controller).
* OpenGG `docs/protocol.md` (GUHPY) — wireless transport semantics for TKL-gen3
  (61 = "temporary RGB ownership", 62 release, BC/D2 battery, packet timing).
* SSGG (Ven0m0/steelseriesgg-rs) src/devices/{keyboards/models.rs,
  keyboards/apex_pro_tkl_2023.rs, hid_reports.rs} — per-model Frames table
  (in-repo asserts enumerate every PID's packet id / length / count / init).
* Live sysfs dumps of the user's dongle (this document, section 2).

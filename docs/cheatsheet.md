# -------------------------------------
# Frame cheat sheet for the Apex Pro Mini Wireless family (all values live!)
# Full write-up: docs/RESEARCH.md
# -------------------------------------
# WIRE ADDRESS LAYOUT of every layout-change report from the FFC0 control
# collection (01.?? feature):
#     [report-id 00][opcode]...  feature or output report
#     replies come on the input reports of the same FFC0 collection  [opcode][00][data]
#
# ---- DIRECT (per-key RGB) frames --------------------------------
#    feature report, report-id 0x00
#    [00][opcode][count][usage R G B]... repeat count times
#    candidates for `opcode`:
#        0x40  Pro TKL 2023 / Gen 3            zero-padded to the feature length
#        0x61  wireless (Apex 2023 Wireless)   zero-padded to the feature length
#        0x3A  Legacy Apex 7/Pro/5/7-TKL
#    key count = number of *entries* sent (OpenRGB: 112-127)
#    usage = HID usage byte (0x04..0x4F, modifiers 0xE0..E7, extras 0x31, 0xFB, ...)
#
# ---- control packets --------------------------------------------
#    feature-KEY?
#     0x4B  init (all zero), once after connect, unlocks 0x40/0x61 frames
#     0x41  clear lighting / drop direct ownership FOR WIRED boards
#     0x89  profile select  (responds 89 FF = "no profiles of this family")
#     0x90  firmware queryreply,  OUT-report write, reply[0..] = "1.19.7"-style version string
#    output OF-VALUE extra:
#     0x23  brightness set  (0..10)
#     0xA3  brightness ask, measured -> [A3 00 <0..10>]
#     0x62  wireless release of tint RGB (wireless only, per Opengg gen3 dongle)
#     0xBC  wireless connection status ask (x	Array 00 00 = locked, 01 = paired)
#     0xD2  wireless battery ask           (reply2 = data)
#     0x92  wired  battery ask             (reply2 = data)
#
# ---- notifications (FFC1 input, wireless FFC0 input F0) ----------
#     [type][value]  01 = brightness 0..10
#                    02 = active onboard profile 0..4
#                    04 = OptiPoint mode
#
# ---- SS "profile" flash  *** WE WILL NEVER SEND THESE *** --------
#     0x83 / 0x02 / 0x03 / 0x42 / 0x43 / 0xE6 / 0x53 / 0x68 / ...
#     (read/erase/activate onboard profile slot sel; guarded by allow-list)
# -------------------------------------

#!/usr/bin/env bash
# Grants your user direct read/write access to the SteelSeries Apex Pro Mini
# Wireless hidraw nodes.  MUST be run with sudo, once.
#
#   sudo bash setup/00-grant-access.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE="/etc/udev/rules.d/99-apexmini.rules"

echo "Installing udev rule: $RULE"
sudo cp "$HERE/../udev/99-apexmini.rules" "$RULE"

echo "Reloading udev & reprobing devices…"
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=hidraw || true

echo
echo "Present hidraw group access:"
for h in /dev/hidraw*; do
  v=$(udevadm info -a -q all -n "$h" 2>/dev/null | awk '/idVendor/{print $4; exit}' || true)
  p=$(udevadm info -a -q all -n "$h" 2>/dev/null | awk '/idProduct/{print $4; exit}' || true)
  if [ "${v:-x}" = "'1038'" ] 2>/dev/null; then
    ls -l "$h"
  fi
done

echo
echo "Done.  Try:  cd src && python3 -c 'from apexmini import hidapi; [print(d) for d in hidapi.enumerate_devices(0x1038)]'"

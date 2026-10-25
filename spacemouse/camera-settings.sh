#!/usr/bin/env bash
set -euo pipefail
SPACEMOUSE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
current="$(python3 "$SPACEMOUSE_DIR/camera_gain.py" --show)"
percent="$(python3 -c 'import json,sys; s=json.loads(sys.argv[1]); print(s.get("percent", round(s["pan"]*25*s.get("runtime_scale",1))))' "$current")"
choice="$(kdialog --title 'Fusion-Kamerageschwindigkeit' --inputbox \
  'Kamerageschwindigkeit in Prozent (1–100). Wirksam nach einem Fusion-Neustart.' "$percent")" || exit 0
if ! python3 "$SPACEMOUSE_DIR/camera_gain.py" --queue --percent "$choice"; then
  kdialog --error 'Bitte eine ganze Zahl zwischen 1 und 100 eingeben.'
  exit 1
fi
kdialog --title 'Fusion SpaceMouse' --msgbox 'Gespeichert. Bitte Fusion neu starten, um die neue Kamerageschwindigkeit zu verwenden.'

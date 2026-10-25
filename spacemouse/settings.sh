#!/usr/bin/env bash
set -euo pipefail
SPACEMOUSE_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
choice="$(kdialog --title 'Fusion SpaceMouse' --menu 'Was möchtest du einstellen?' \
  camera 'Kamerageschwindigkeit in Fusion' axes 'Achsen und Tasten')" || exit 0
if [[ "$choice" == camera ]]; then
  exec "$SPACEMOUSE_DIR/camera-settings.sh"
fi
if ! systemctl --user start fusion-spacemouse.service; then
  kdialog --error 'Die SpaceMouse-Anbindung konnte nicht starten. Details: journalctl --user -u fusion-spacemouse.service'
  exit 1
fi
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
export SPNAV_SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/autodesk-fusion-spacemouse/spnav.sock"
export LD_LIBRARY_PATH="$SPACEMOUSE_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$SPACEMOUSE_DIR/spnavcfg" "$@"

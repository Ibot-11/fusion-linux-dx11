#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/autodesk-fusion"
PREFIX_DIR="${FUSION_PREFIX_DIR:-compatdata-exp-dx11}"

if [[ -f "$APP_DIR/prefix-dir" ]]; then PREFIX_DIR="$(cat "$APP_DIR/prefix-dir")"; fi
production="$APP_DIR/$PREFIX_DIR/pfx/drive_c"

FUSION="$(find "$production" -type f -name Fusion360.exe -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
if [[ -z "$FUSION" ]]; then
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --error 'Autodesk Fusion 360 ist in diesem Prefix noch nicht installiert.'
  elif command -v zenity >/dev/null 2>&1; then
    zenity --error --text='Autodesk Fusion 360 ist in diesem Prefix noch nicht installiert.'
  else
    echo "Fehler: Fusion360.exe nicht gefunden in $production" >&2
  fi
  exit 1
fi

mkdir -p "$APP_DIR/logs"

# Rotate fusion.log if it exceeds 20MB
if [[ -f "$APP_DIR/logs/fusion.log" && $(stat -c%s "$APP_DIR/logs/fusion.log" 2>/dev/null || echo 0) -gt 20971520 ]]; then
  mv "$APP_DIR/logs/fusion.log" "$APP_DIR/logs/fusion.log.old"
fi

SPACEMOUSE_PID=''
if [[ -f "$APP_DIR/spacemouse-enabled" ]]; then
  if python3 "$APP_DIR/spacemouse/install-sdk.py" "$FUSION" >> "$APP_DIR/logs/spacemouse-start.log" 2>&1; then
    python3 "$APP_DIR/spacemouse/start.py" >> "$APP_DIR/logs/spacemouse-start.log" 2>&1 &
    SPACEMOUSE_PID=$!
    python3 "$APP_DIR/spacemouse/start.py" --wait || true
  fi
fi

python3 "$APP_DIR/browser-listener.py" &
LISTENER_PID=$!

if [[ -f "$APP_DIR/window-fix.py" ]]; then
  PYTHONPATH="$APP_DIR/vendor" python3 "$APP_DIR/window-fix.py" >> "$APP_DIR/logs/window-fix.log" 2>&1 &
  FIX_PID=$!
else
  FIX_PID=''
fi

if [[ -f "$APP_DIR/panel-fix.exe" ]]; then
  "$APP_DIR/run-proton.sh" --panel-fix >> "$APP_DIR/logs/panel-fix.log" 2>&1 &
  PANEL_PID=$!
else
  PANEL_PID=''
fi

trap 'kill "$LISTENER_PID" ${FIX_PID:+"$FIX_PID"} ${PANEL_PID:+"$PANEL_PID"} ${SPACEMOUSE_PID:+"$SPACEMOUSE_PID"} 2>/dev/null || true' EXIT

cd "$(dirname "$FUSION")"
ARGS=()
for ARG in "$@"; do
  if [[ "$ARG" == /* ]]; then
    ARGS+=("Z:${ARG//\//\\}")
  else
    ARGS+=("$ARG")
  fi
done

if command -v powerprofilesctl >/dev/null 2>&1 &&
   fusion_profiles="$(powerprofilesctl list 2>/dev/null)" &&
   [[ "$fusion_profiles" =~ (^|$'\n')[[:space:]*]*performance: ]]; then
  powerprofilesctl launch --profile performance --reason 'Autodesk Fusion 360' --appid autodesk-fusion "$APP_DIR/run-proton.sh" "$FUSION" "${ARGS[@]}" >> "$APP_DIR/logs/fusion.log" 2>&1
else
  "$APP_DIR/run-proton.sh" "$FUSION" "${ARGS[@]}" >> "$APP_DIR/logs/fusion.log" 2>&1
fi

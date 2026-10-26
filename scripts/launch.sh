#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"
PREFIX_DIR="${FUSION_PREFIX_DIR:-compatdata-exp-dx11}"

if [[ -f "$APP_DIR/prefix-dir" ]]; then PREFIX_DIR="$(cat "$APP_DIR/prefix-dir")"; fi
production="$APP_DIR/$PREFIX_DIR/pfx/drive_c"

FUSION="$(find "$production" -type f -name Fusion360.exe -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)"
if [[ -z "$FUSION" ]]; then
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --error 'Autodesk Fusion is not installed in this prefix.'
  elif command -v zenity >/dev/null 2>&1; then
    zenity --error --text='Autodesk Fusion is not installed in this prefix.'
  else
    echo "Error: Fusion360.exe not found in $production" >&2
  fi
  exit 1
fi

mkdir -p "$APP_DIR/logs"

# Rotate fusion.log if it exceeds 20MB
if [[ -f "$APP_DIR/logs/fusion.log" && $(stat -c%s "$APP_DIR/logs/fusion.log" 2>/dev/null || echo 0) -gt 20971520 ]]; then
  mv "$APP_DIR/logs/fusion.log" "$APP_DIR/logs/fusion.log.old"
fi

unset FUSION_SPACEMOUSE_CAMERA_SCALE FUSION_SPACEMOUSE_CAMERA_BASE FUSION_SPACEMOUSE_CAMERA_SESSION
if [[ -f "$APP_DIR/spacemouse-enabled" ]]; then
  if [[ -f "$APP_DIR/spacemouse/camera_gain.py" ]]; then
    if fusion_camera_session="$(python3 "$APP_DIR/spacemouse/camera_gain.py" --prepare-session 2>> "$APP_DIR/logs/spacemouse-start.log")"; then
      read -r fusion_camera_scale fusion_camera_base fusion_camera_token <<< "$fusion_camera_session"
      export FUSION_SPACEMOUSE_CAMERA_SCALE="$fusion_camera_scale"
      export FUSION_SPACEMOUSE_CAMERA_BASE="$fusion_camera_base"
      export FUSION_SPACEMOUSE_CAMERA_SESSION="$fusion_camera_token"
    else
      kdialog --passivepopup 'Could not apply SpaceMouse camera speed. See the Fusion log.' 10 || true
      exit 1
    fi
  fi
  if ! python3 "$APP_DIR/spacemouse/install-sdk.py" "$FUSION" >> "$APP_DIR/logs/spacemouse-start.log" 2>&1 ||
     ! systemctl --user start fusion-spacemouse.service >> "$APP_DIR/logs/spacemouse-start.log" 2>&1; then
    if command -v kdialog >/dev/null 2>&1; then
      kdialog --passivepopup 'SpaceMouse could not start. See the Fusion SpaceMouse journal.' 10 || true
    fi
  fi
fi

# Ensure no orphaned wineserver from a previous session remains
if ! pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
  PV="${FUSION_PROTON_VERSION:-GE-Proton11-7-x86_64}"
  if [[ -f "$APP_DIR/proton-version" ]]; then PV="$(cat "$APP_DIR/proton-version")"; fi
  for pdir in "$HOME/.local/share/Steam/compatibilitytools.d/$PV" "$HOME/.local/share/Steam/steamapps/common/$PV"; do
    if [[ -x "$pdir/files/bin/wineserver" ]]; then
      WINEPREFIX="$APP_DIR/$PREFIX_DIR/pfx" "$pdir/files/bin/wineserver" -k 2>/dev/null || true
      break
    fi
  done
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

trap 'kill "$LISTENER_PID" ${FIX_PID:+"$FIX_PID"} ${PANEL_PID:+"$PANEL_PID"} 2>/dev/null || true' EXIT

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

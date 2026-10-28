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

fusion_language="${FUSION_LANGUAGE:-}"
manager_settings="${XDG_CONFIG_HOME:-$HOME/.config}/fusion-linux-dx11/Fusion Manager.conf"
if [[ -z "$fusion_language" && -f "$manager_settings" ]]; then
  fusion_language="$(sed -n 's/^language=//p' "$manager_settings" | head -n 1)"
fi
case "$fusion_language" in
  de*) fusion_language=de ;;
  en*) fusion_language=en ;;
  *) fusion_language='' ;;
esac
if [[ -n "$fusion_language" && -f "$APP_DIR/fusion-language.py" ]]; then
  if ! python3 "$APP_DIR/fusion-language.py" --fusion "$FUSION" --language "$fusion_language" >> "$APP_DIR/logs/fusion.log" 2>&1; then
    printf 'Warning: Could not apply the selected Fusion language. See the Fusion log.\n' >&2
  fi
fi

spacemouse_warning() {
  local message="$1"
  if command -v kdialog >/dev/null 2>&1 && kdialog --passivepopup "$message" 10; then
    return
  fi
  if command -v zenity >/dev/null 2>&1 && zenity --warning --text="$message"; then
    return
  fi
  printf 'Warning: %s\n' "$message" >&2
}

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
      spacemouse_warning 'Could not apply SpaceMouse camera speed. See the Fusion log.'
    fi
  fi
  if ! python3 "$APP_DIR/spacemouse/install-sdk.py" "$FUSION" >> "$APP_DIR/logs/spacemouse-start.log" 2>&1 ||
     ! systemctl --user start fusion-spacemouse.service >> "$APP_DIR/logs/spacemouse-start.log" 2>&1; then
    spacemouse_warning 'SpaceMouse could not start. See the Fusion SpaceMouse journal.'
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

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"

STEAM_SEARCH_DIRS=(
  "$HOME/.local/share/Steam"
  "$HOME/.steam/root"
  "$HOME/.steam/steam"
  "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"
)

STEAM_DIR=""
for d in "${STEAM_SEARCH_DIRS[@]}"; do
  if [[ -d "$d" ]]; then
    STEAM_DIR="$d"
    break
  fi
done

stop_prefix_wineserver() {
  local prefix="$1"
  local proton_ver="$2"
  local proton_dir=""
  if [[ -n "$STEAM_DIR" && -d "$STEAM_DIR/compatibilitytools.d/$proton_ver" ]]; then
    proton_dir="$STEAM_DIR/compatibilitytools.d/$proton_ver"
  elif [[ -n "$STEAM_DIR" && -d "$STEAM_DIR/steamapps/common/$proton_ver" ]]; then
    proton_dir="$STEAM_DIR/steamapps/common/$proton_ver"
  fi
  if [[ -n "$proton_dir" && -x "$proton_dir/files/bin/wineserver" && -d "$APP_DIR/$prefix/pfx" ]]; then
    WINEPREFIX="$APP_DIR/$prefix/pfx" "$proton_dir/files/bin/wineserver" -k 2>/dev/null || true
    WINEPREFIX="$APP_DIR/$prefix/pfx" "$proton_dir/files/bin/wineserver" -w 2>/dev/null || true
  fi
}

case "${1:-status}" in
  exp-dx11|experimental|dx11)
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      echo "Bitte zuerst Autodesk Fusion schließen, bevor das Profil gewechselt wird." >&2
      exit 1
    fi
    stop_prefix_wineserver "compatdata" "GE-Proton11-7-x86_64"
    stop_prefix_wineserver "compatdata-exp-dx11" "Proton - Experimental"
    printf 'compatdata-exp-dx11\n' > "$APP_DIR/prefix-dir"
    printf 'Proton - Experimental\n' > "$APP_DIR/proton-version"
    chmod 600 "$APP_DIR/prefix-dir" "$APP_DIR/proton-version"
    echo "Aktiviert: Proton - Experimental + DirectX 11 (Prefix: compatdata-exp-dx11)"
    ;;
  ge-opengl|opengl|stable)
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      echo "Bitte zuerst Autodesk Fusion schließen, bevor das Profil gewechselt wird." >&2
      exit 1
    fi
    stop_prefix_wineserver "compatdata-exp-dx11" "Proton - Experimental"
    stop_prefix_wineserver "compatdata" "GE-Proton11-7-x86_64"
    printf 'compatdata\n' > "$APP_DIR/prefix-dir"
    printf 'GE-Proton11-7-x86_64\n' > "$APP_DIR/proton-version"
    chmod 600 "$APP_DIR/prefix-dir" "$APP_DIR/proton-version"
    echo "Aktiviert: GE-Proton11-7-x86_64 + OpenGL Core Profile (Prefix: compatdata)"
    ;;
  status)
    echo "Aktuelles Prefix : $(cat "$APP_DIR/prefix-dir" 2>/dev/null || echo compatdata-exp-dx11)"
    echo "Aktuelle Proton  : $(cat "$APP_DIR/proton-version" 2>/dev/null || echo Proton - Experimental)"
    ;;
  *)
    echo "Verwendung: $0 {exp-dx11|ge-opengl|status}" >&2
    exit 1
    ;;
esac

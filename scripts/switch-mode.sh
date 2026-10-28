#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"
PROTON_HELPER="$APP_DIR/proton.py"

case "${1:-status}" in
  exp-dx11|experimental|dx11)
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      echo "Close Autodesk Fusion before switching profiles." >&2
      exit 1
    fi
    if ! proton_dir="$(python3 "$PROTON_HELPER" find 'Proton - Experimental')"; then
      echo "Error: Proton Experimental is not installed in Steam or a Steam library." >&2
      exit 1
    fi
    printf 'compatdata-exp-dx11\n' > "$APP_DIR/prefix-dir"
    printf 'Proton - Experimental\n' > "$APP_DIR/proton-version"
    rm -f -- "$APP_DIR/proton-path"
    chmod 600 "$APP_DIR/prefix-dir" "$APP_DIR/proton-version"
    echo "Enabled: Proton - Experimental + DirectX 11 (Prefix: compatdata-exp-dx11)"
    ;;
  ge-opengl|opengl|stable)
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      echo "Close Autodesk Fusion before switching profiles." >&2
      exit 1
    fi
    if ! proton_dir="$(python3 "$PROTON_HELPER" find-ge)"; then
      echo "Error: No installed GE-Proton was found in Steam or a Steam library." >&2
      exit 1
    fi
    proton_version="$(basename -- "$proton_dir")"
    printf 'compatdata\n' > "$APP_DIR/prefix-dir"
    printf '%s\n' "$proton_version" > "$APP_DIR/proton-version"
    rm -f -- "$APP_DIR/proton-path"
    chmod 600 "$APP_DIR/prefix-dir" "$APP_DIR/proton-version"
    echo "Enabled: $proton_version + OpenGL Core Profile (Prefix: compatdata)"
    ;;
  status)
    echo "Current prefix : $(cat "$APP_DIR/prefix-dir" 2>/dev/null || echo compatdata-exp-dx11)"
    echo "Current Proton  : $(cat "$APP_DIR/proton-version" 2>/dev/null || echo Proton - Experimental)"
    ;;
  *)
    echo "Usage: $0 {exp-dx11|ge-opengl|status}" >&2
    exit 1
    ;;
esac

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"
PROTON_HELPER="$APP_DIR/fusion_runtime.py"

case "${1:-status}" in
  fusion|exp-dx11|experimental|dx11)
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      echo "Close Autodesk Fusion before switching profiles." >&2
      exit 1
    fi
    python3 "$PROTON_HELPER" bind "$APP_DIR"
    if [[ ! -f "$APP_DIR/prefix-dir" ]]; then
      printf 'compatdata-exp-dx11\n' > "$APP_DIR/prefix-dir"
      chmod 600 "$APP_DIR/prefix-dir"
    fi
    echo "Enabled: verified Proton-Fusion + DirectX 11"
    ;;
  ge-opengl|opengl|stable)
    echo 'Fusion requires Proton-Fusion; legacy GE-Proton/OpenGL switching is no longer supported.' >&2
    exit 1
    ;;
  status)
    echo "Current prefix : $(cat "$APP_DIR/prefix-dir" 2>/dev/null || echo compatdata-exp-dx11)"
    python3 "$PROTON_HELPER" resolve "$APP_DIR"
    ;;
  *)
    echo "Usage: $0 {fusion|status}" >&2
    exit 1
    ;;
esac

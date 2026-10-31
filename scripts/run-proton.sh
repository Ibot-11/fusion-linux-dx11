#!/usr/bin/env bash
set -euo pipefail
unset QT_QPA_PLATFORM QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"
PREFIX_DIR="${FUSION_PREFIX_DIR:-compatdata-exp-dx11}"
if [[ -f "$APP_DIR/prefix-dir" ]]; then PREFIX_DIR="$(cat "$APP_DIR/prefix-dir")"; fi
STEAM_DIR="$(python3 "$APP_DIR/proton.py" steam || true)"
PROTON_DIR="$(python3 "$APP_DIR/fusion_runtime.py" resolve "$APP_DIR")"

export STEAM_COMPAT_DATA_PATH="$APP_DIR/$PREFIX_DIR"
if [[ -n "$STEAM_DIR" ]]; then
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM_DIR"
fi
if [[ -f "$APP_DIR/spacemouse-enabled" ]]; then
  export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}siappdll=n,b"
fi

# Remove an inherited legacy Fusion layer while preserving unrelated layers.
if [[ -n "${VK_INSTANCE_LAYERS:-}" ]]; then
  IFS=: read -ra fusion_layers <<< "$VK_INSTANCE_LAYERS"
  fusion_kept_layers=()
  for fusion_layer in "${fusion_layers[@]}"; do
    [[ "$fusion_layer" == VK_LAYER_FUSION_present_sync ]] || fusion_kept_layers+=("$fusion_layer")
  done
  export VK_INSTANCE_LAYERS="$(IFS=:; echo "${fusion_kept_layers[*]}")"
fi

# DXVK Configuration
[[ ! -f "$APP_DIR/dxvk.conf" ]] || export DXVK_CONFIG_FILE="$APP_DIR/dxvk.conf"
export DXVK_LOG_PATH="$APP_DIR/logs"
export DXVK_LOG_LEVEL=info

# Load custom GPU overrides if present (e.g. DRI_PRIME, VK_DRIVER_FILES)
if [[ -f "$APP_DIR/gpu.conf" ]]; then
  # shellcheck source=/dev/null
  source "$APP_DIR/gpu.conf"
fi

export BROWSER="$APP_DIR/browser-request.py"
export WINEDEBUG="${WINEDEBUG--all}"

mkdir -p "$STEAM_COMPAT_DATA_PATH" "$DXVK_LOG_PATH"

if [[ "${1:-}" == --set-dpi ]]; then
  DPI="${2:-}"
  case "$DPI" in 96|120|144|168|192) ;; *)
    echo "Error: unsupported Fusion DPI value '$DPI'." >&2
    exit 2
  esac
  export WINEPREFIX="$STEAM_COMPAT_DATA_PATH/pfx"
  export LD_LIBRARY_PATH="$PROTON_DIR/files/lib/x86_64-linux-gnu:$PROTON_DIR/files/lib/i386-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export WINEDLLPATH="$PROTON_DIR/files/lib/vkd3d:$PROTON_DIR/files/lib/wine${WINEDLLPATH:+:$WINEDLLPATH}"
  export WINENTSYNC=1 WINEESYNC=1 WINEFSYNC=1
  WINE="$PROTON_DIR/files/bin/wine"
  "$WINE" reg add "HKEY_CURRENT_USER\\Control Panel\\Desktop" /v LogPixels /t REG_DWORD /d "$DPI" /f >/dev/null
  "$WINE" reg add "HKEY_CURRENT_USER\\Software\\Wine\\Fonts" /v LogPixels /t REG_DWORD /d "$DPI" /f >/dev/null
  echo "Fusion UI scale set to $DPI DPI."
  exit 0
fi

exec "$PROTON_DIR/proton" run "$@"

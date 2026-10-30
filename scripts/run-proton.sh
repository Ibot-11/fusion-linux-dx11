#!/usr/bin/env bash
set -euo pipefail
unset QT_QPA_PLATFORM QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH

APP_DIR="${FUSION_APP_DIR:-$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")}"
PREFIX_DIR="${FUSION_PREFIX_DIR:-compatdata-exp-dx11}"
PROTON_VERSION="${FUSION_PROTON_VERSION:-Proton - Experimental}"

if [[ -f "$APP_DIR/prefix-dir" ]]; then PREFIX_DIR="$(cat "$APP_DIR/prefix-dir")"; fi
if [[ -f "$APP_DIR/proton-version" ]]; then PROTON_VERSION="$(cat "$APP_DIR/proton-version")"; fi

CUSTOM_PROTON="${FUSION_PROTON_PATH:-}"
if [[ -f "$APP_DIR/proton-path" ]]; then CUSTOM_PROTON="$(cat "$APP_DIR/proton-path")"; fi
STEAM_DIR="$(python3 "$APP_DIR/proton.py" steam || true)"
PROTON_DIR="$(python3 "$APP_DIR/proton.py" find "$PROTON_VERSION" "$CUSTOM_PROTON" || true)"

if [[ -z "$PROTON_DIR" ]]; then
  echo "Error: Proton version '$PROTON_VERSION' not found." >&2
  echo "Make sure '$PROTON_VERSION' is installed or select a valid custom Proton path." >&2
  exit 1
fi

export STEAM_COMPAT_DATA_PATH="$APP_DIR/$PREFIX_DIR"
if [[ -n "$STEAM_DIR" ]]; then
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM_DIR"
fi
export PROTON_USE_WINED3D=0
export PROTON_USE_XALIA=0
export NO_AT_BRIDGE=1
export WINEDLLOVERRIDES="bcp47langs=;icuuc,icuin,icudt,d3dcompiler_47=n,b"

if [[ -f "$APP_DIR/spacemouse-enabled" ]]; then
  export WINEDLLOVERRIDES="$WINEDLLOVERRIDES;siappdll=n,b"
fi

# Vulkan Layer for 3D Canvas Presentation Synchronization (fixes snapping cursor lag)
if [[ -f "$APP_DIR/VkLayer_fusion_present_sync.json" ]]; then
  export VK_LAYER_PATH="$APP_DIR${VK_LAYER_PATH:+:$VK_LAYER_PATH}"
  export VK_INSTANCE_LAYERS="VK_LAYER_FUSION_present_sync${VK_INSTANCE_LAYERS:+:$VK_INSTANCE_LAYERS}"
fi

# DXVK Configuration
export DXVK_CONFIG_FILE="$APP_DIR/dxvk.conf"
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

if [[ "${1:-}" == --panel-fix ]]; then
  shift
  for _ in {1..60}; do
    if pgrep -fi "Fusion360\.exe" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  export WINEPREFIX="$STEAM_COMPAT_DATA_PATH/pfx"
  export LD_LIBRARY_PATH="$PROTON_DIR/files/lib/x86_64-linux-gnu:$PROTON_DIR/files/lib/i386-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export WINEDLLPATH="$PROTON_DIR/files/lib/vkd3d:$PROTON_DIR/files/lib/wine${WINEDLLPATH:+:$WINEDLLPATH}"
  export WINENTSYNC=1 WINEESYNC=1 WINEFSYNC=1
  exec "$PROTON_DIR/files/bin/wine" "$APP_DIR/panel-fix.exe" "$@"
fi

exec "$PROTON_DIR/proton" run "$@"

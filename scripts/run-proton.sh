#!/usr/bin/env bash
set -euo pipefail
unset QT_QPA_PLATFORM QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/autodesk-fusion"
PREFIX_DIR="${FUSION_PREFIX_DIR:-compatdata-exp-dx11}"
PROTON_VERSION="${FUSION_PROTON_VERSION:-Proton - Experimental}"

if [[ -f "$APP_DIR/prefix-dir" ]]; then PREFIX_DIR="$(cat "$APP_DIR/prefix-dir")"; fi
if [[ -f "$APP_DIR/proton-version" ]]; then PROTON_VERSION="$(cat "$APP_DIR/proton-version")"; fi

# Steam search paths
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

if [[ -z "$STEAM_DIR" ]]; then
  echo "Fehler: Steam-Verzeichnis konnte nicht gefunden werden." >&2
  exit 1
fi

export STEAM_COMPAT_DATA_PATH="$APP_DIR/$PREFIX_DIR"
export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM_DIR"
export PROTON_USE_WINED3D=0
export PROTON_USE_XALIA=0
export NO_AT_BRIDGE=1
export WINEDLLOVERRIDES="bcp47langs=;icuuc,icuin,icudt=n,b"

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
export DXVK_STATE_CACHE_PATH="$APP_DIR/cache"

# Load custom GPU overrides if present (e.g. DRI_PRIME, VK_DRIVER_FILES)
if [[ -f "$APP_DIR/gpu.conf" ]]; then
  # shellcheck source=/dev/null
  source "$APP_DIR/gpu.conf"
fi

export BROWSER="$APP_DIR/browser-request.py"
export WINEDEBUG=-all

mkdir -p "$STEAM_COMPAT_DATA_PATH" "$DXVK_LOG_PATH" "$DXVK_STATE_CACHE_PATH"

# Locate Proton installation
PROTON_DIR=""
if [[ -d "$STEAM_DIR/compatibilitytools.d/$PROTON_VERSION" ]]; then
  PROTON_DIR="$STEAM_DIR/compatibilitytools.d/$PROTON_VERSION"
elif [[ -d "$STEAM_DIR/steamapps/common/$PROTON_VERSION" ]]; then
  PROTON_DIR="$STEAM_DIR/steamapps/common/$PROTON_VERSION"
elif [[ -d "/usr/share/steam/compatibilitytools.d/$PROTON_VERSION" ]]; then
  PROTON_DIR="/usr/share/steam/compatibilitytools.d/$PROTON_VERSION"
fi

if [[ -z "$PROTON_DIR" ]]; then
  echo "Fehler: Proton-Version '$PROTON_VERSION' nicht gefunden!" >&2
  echo "Bitte stelle sicher, dass Steam und '$PROTON_VERSION' installiert sind." >&2
  exit 1
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

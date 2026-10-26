#!/usr/bin/env bash
set -euo pipefail
APP="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
exec "$APP/fusion-manager" --backend "$APP/manager_backend.py" --target "$APP" "$@"

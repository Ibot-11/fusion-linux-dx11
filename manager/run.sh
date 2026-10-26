#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
make -s -C "$REPO/manager"
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
exec "$REPO/.build/manager/fusion-manager" --backend "$REPO/scripts/manager_backend.py" --repo "$REPO" "$@"

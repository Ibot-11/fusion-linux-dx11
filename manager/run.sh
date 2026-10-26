#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$REPO/.build/manager/fusion-spacemouse-access" || "$REPO/spacemouse/access-helper.cpp" -nt "$REPO/.build/manager/fusion-spacemouse-access" || ! -x "$REPO/.build/manager/fusion-manager" || "$REPO/manager/main.cpp" -nt "$REPO/.build/manager/fusion-manager" ]]; then
  make -C "$REPO/manager"
fi
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
exec "$REPO/.build/manager/fusion-manager" --backend "$REPO/scripts/manager_backend.py" --repo "$REPO" "$@"

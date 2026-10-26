#!/usr/bin/env bash
set -euo pipefail
APP="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$APP/install.sh" ]]; then
  exec "$APP/manager/run.sh" --page spacemouse "$@"
fi
exec "$APP/manager.sh" --page spacemouse "$@"

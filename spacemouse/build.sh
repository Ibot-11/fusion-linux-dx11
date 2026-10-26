#!/usr/bin/env bash
# Build only the Fusion Wine SDK bridge. Input is handled directly through HID (evdev fallback).
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$REPO/.build/spacemouse/runtime/bin"
mkdir -p "$STAGE"
if command -v x86_64-w64-mingw32-g++ >/dev/null; then
  make -C "$REPO/spacemouse/bridge/build-linux" static
  cp "$REPO/spacemouse/bridge/build-linux/dist/siappdll-static.dll" "$STAGE/siappdll.dll"
else
  [[ "$(uname -m)" == x86_64 ]] || { echo 'The bundled SDK DLL requires x86_64.' >&2; exit 1; }
  (cd "$REPO/spacemouse/prebuilt" && sha256sum --check SHA256SUMS)
  cp "$REPO/spacemouse/prebuilt/siappdll.dll" "$STAGE/siappdll.dll"
fi
echo "SpaceMouse SDK built: $STAGE/siappdll.dll (direct HID, evdev fallback)"

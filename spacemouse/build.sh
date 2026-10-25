#!/usr/bin/env bash
# Build only into .build: the source checkout stays clean for future updates.
set -euo pipefail
REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$REPO/.build/spacemouse"
for tool in cc c++ make pkg-config python3; do
  command -v "$tool" >/dev/null || { echo "SpaceMouse benötigt $tool." >&2; exit 1; }
done
pkg-config --exists Qt6Widgets x11 || {
  echo 'SpaceMouse benötigt Qt-6-Widgets- und X11-Entwicklungsdateien (qt6-base-dev / qt6-base, libx11-dev / libx11).' >&2
  exit 1
}
python3 - "$REPO" "$BUILD" <<'PY'
from pathlib import Path
import shutil, sys
repo, build = map(Path, sys.argv[1:])
build.mkdir(parents=True, exist_ok=True)
for name in ('spacenavd', 'libspnav', 'spnavcfg'):
    dest = build / name
    if dest.exists(): shutil.rmtree(dest)
    shutil.copytree(repo / 'third_party/spacenav' / name, dest)
PY
JOBS="${FUSION_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN)}"
STAGE="$BUILD/runtime"
mkdir -p "$STAGE/bin" "$STAGE/lib"
(cd "$BUILD/spacenavd" && ./configure --disable-x11 --disable-debug && make -j"$JOBS")
(cd "$BUILD/libspnav" && ./configure --disable-x11 --disable-debug --prefix="$STAGE" && make -j"$JOBS" && make install)
(cd "$BUILD/spnavcfg" && ./configure --qt6 --disable-debug --prefix="$STAGE" && make -j"$JOBS")
cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 \
  "$REPO/spacemouse/bridge/relay/main.c" -o "$STAGE/bin/spconvd"
cp "$BUILD/spacenavd/spacenavd" "$STAGE/bin/"
cp "$BUILD/spnavcfg/spnavcfg" "$STAGE/bin/"
cp "$REPO/third_party/spacenav/spnavcfg/icons/spnavcfg-256x256.png" "$STAGE/bin/spnavcfg.png"
if command -v x86_64-w64-mingw32-g++ >/dev/null; then
  make -C "$REPO/spacemouse/bridge/build-linux" static
  cp "$REPO/spacemouse/bridge/build-linux/dist/siappdll-static.dll" "$STAGE/bin/siappdll.dll"
else
  [[ "$(uname -m)" == x86_64 ]] || { echo 'Die mitgelieferte SDK-DLL benötigt x86_64.' >&2; exit 1; }
  (cd "$REPO/spacemouse/prebuilt" && sha256sum --check SHA256SUMS)
  cp "$REPO/spacemouse/prebuilt/siappdll.dll" "$STAGE/bin/siappdll.dll"
fi
echo "SpaceMouse gebaut: $STAGE"

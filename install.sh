#!/usr/bin/env bash
# Autodesk Fusion Linux setup and updates. No system packages are installed.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/autodesk-fusion"
MODE="menu"
SPACE="auto"
INSTALLER=""
REQUESTED_PREFIX=""
REQUESTED_PROTON=""
RESUME_ACTION=""
EXPECTED_CLEAN_STATE=""

usage() {
  cat <<'HELP'
Usage: ./install.sh [MODE] [INSTALLATION_FOLDER] [OPTIONS]
  --patch             Set up an existing Fusion installation
  --clean             Run the Autodesk installer and set up the Linux integration
  --resume-clean      Continue an interrupted clean installation
  --retry-installer   Explicitly run the Autodesk installer again when resuming
  --finish-install    Confirm Autodesk setup completed and finish integration
  --update, -u        Update the Git branch and install the new revision
  --apply-update      Apply the current checkout without downloading updates
  --build-layer       Build the Vulkan layer only
  --with-spacemouse   Build and enable SpaceMouse support
  --without-spacemouse Keep the SpaceMouse component unchanged
  --prefix NAME       Prefix folder for a new installation
  --proton FOLDER     Use an installed Proton folder
  --installer FILE    Use an existing Autodesk installer EXE with --clean
  --help, -h          Show help
With no arguments, opens the menu. Updates preserve prefix, Proton, GPU, DXVK
and SpaceMouse settings. Close Fusion before installing or updating.
HELP
}

while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --patch|--clean|--resume-clean|--update|--apply-update|--build-layer|-u)
      [[ "$MODE" == menu ]] || { echo 'Choose only one mode.' >&2; exit 1; }
      MODE="${1#--}"; [[ "$MODE" == -u ]] && MODE=update
      ;;
    --with-spacemouse) SPACE=on ;;
    --without-spacemouse) SPACE=off ;;
    --prefix) shift; REQUESTED_PREFIX="${1:?--prefix requires a folder name}" ;;
    --proton) shift; REQUESTED_PROTON="${1:?--proton requires a folder path}" ;;
    --installer) shift; INSTALLER="${1:?--installer requires a file path}" ;;
    --expected-clean-state) shift; EXPECTED_CLEAN_STATE="${1:?--expected-clean-state requires JSON}" ;;
    --retry-installer|--finish-install)
      [[ -z "$RESUME_ACTION" ]] || { echo 'Choose only one resume action.' >&2; exit 1; }
      [[ "$1" == --retry-installer ]] && RESUME_ACTION=retry || RESUME_ACTION=finish
      ;;
    --*) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    *) TARGET_DIR="$1" ;;
  esac
  shift
done

if [[ "$MODE" == resume-clean && -z "$RESUME_ACTION" ]]; then
  echo 'Choose --retry-installer or --finish-install explicitly.' >&2; exit 1
fi
if [[ "$MODE" != resume-clean && -n "$RESUME_ACTION" ]]; then
  echo 'Resume actions require --resume-clean.' >&2; exit 1
fi
if [[ "$MODE" != resume-clean && -n "$EXPECTED_CLEAN_STATE" ]]; then
  echo '--expected-clean-state requires --resume-clean.' >&2; exit 1
fi

if [[ "$MODE" == menu ]]; then
  echo "Autodesk Fusion Linux – Installer"
  echo '1) Set up an existing installation'
  echo '2) New installation'
  echo '3) Update from the Git repository'
  echo '4) Build the Vulkan layer only'
  echo '5) Exit'
  read -rp 'Choose [1-5]: ' choice
  case "$choice" in
    1) MODE=patch ;; 2) MODE=clean ;; 3) MODE=update ;;
    4) MODE=build-layer ;; 5) exit 0 ;; *) exit 1 ;;
  esac
  if [[ "$MODE" != build-layer ]]; then
    read -rp "Installation folder [$TARGET_DIR]: " chosen
    TARGET_DIR="${chosen:-$TARGET_DIR}"
  fi
fi

command -v python3 >/dev/null || { echo 'Install Python 3 to continue.' >&2; exit 1; }
TARGET_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$TARGET_DIR")"

if [[ "$MODE" == update || "$MODE" == apply-update || "$MODE" == patch ]]; then
  python3 - "$SCRIPT_DIR" "$TARGET_DIR" <<'PYCODE'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
from setup_runtime import require_complete_clean
try:
    require_complete_clean(Path(sys.argv[2]))
except ValueError as error:
    raise SystemExit(str(error))
PYCODE
fi

if [[ "$MODE" == update ]]; then
  command -v git >/dev/null || { echo 'Install Git to continue.' >&2; exit 1; }
  update_args=(--repo "$SCRIPT_DIR" --target "$TARGET_DIR")
  [[ "$SPACE" == on ]] && update_args+=(--with-spacemouse)
  [[ "$SPACE" == off ]] && update_args+=(--without-spacemouse)
  exec python3 "$SCRIPT_DIR/scripts/update.py" "${update_args[@]}"
fi

for tool in cc make; do
  command -v "$tool" >/dev/null || { echo "Install $tool (build-essential / base-devel) to continue." >&2; exit 1; }
done
if [[ "$MODE" == build-layer ]]; then
  make -C "$SCRIPT_DIR/layer"
  exit 0
fi

python3 - "$SCRIPT_DIR" <<'PYCODE'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / 'spacemouse'))
from processes import fusion_running
if fusion_running(): raise SystemExit('Close Fusion before installing or updating.')
PYCODE

if [[ "$MODE" == apply-update && ! -d "$TARGET_DIR" ]]; then
  echo "Installation not found: $TARGET_DIR" >&2; exit 1
fi
if [[ "$MODE" == patch && ! -d "$TARGET_DIR" ]]; then
  echo "Installation not found: $TARGET_DIR; use --clean for a new installation." >&2; exit 1
fi
if [[ "$MODE" == resume-clean && ! -d "$TARGET_DIR" ]]; then
  echo "Installation not found: $TARGET_DIR" >&2; exit 1
fi

PREFIX="${REQUESTED_PREFIX:-compatdata-exp-dx11}"
if [[ -z "$REQUESTED_PREFIX" && "$MODE" != clean && -f "$TARGET_DIR/prefix-dir" ]]; then
  PREFIX="$(cat "$TARGET_DIR/prefix-dir")"
fi
python3 - "$PREFIX" <<'PYCODE'
from pathlib import Path
import sys
p=sys.argv[1]
if not p or Path(p).name != p or p in ('.','..'): raise SystemExit('Invalid prefix folder name.')
PYCODE
if [[ "$MODE" == patch && ! -d "$TARGET_DIR/$PREFIX" ]]; then
  SOURCE_PREFIX="compatdata"
  [[ -f "$TARGET_DIR/prefix-dir" ]] && SOURCE_PREFIX="$(cat "$TARGET_DIR/prefix-dir")"
  python3 - "$SOURCE_PREFIX" <<'PYCODE'
from pathlib import Path
import sys
p=sys.argv[1]
if not p or Path(p).name != p or p in ('.','..'): raise SystemExit('Invalid source prefix folder name.')
PYCODE
  [[ -d "$TARGET_DIR/$SOURCE_PREFIX" ]] || { echo 'No prefix found. Run --clean or correct prefix-dir.' >&2; exit 1; }
  echo "Creating an isolated DX11 prefix from $SOURCE_PREFIX …"
  cp -a --reflink=auto "$TARGET_DIR/$SOURCE_PREFIX" "$TARGET_DIR/$PREFIX"
fi

if [[ -n "$REQUESTED_PROTON" ]]; then
  REQUESTED_PROTON="$(realpath "$REQUESTED_PROTON")"
  [[ -f "$REQUESTED_PROTON/proton" ]] || { echo 'The selected Proton folder does not contain a proton launcher.' >&2; exit 1; }
fi

ENABLE_SPACE=0
if [[ "$MODE" == resume-clean ]]; then
  SPACE="$(python3 - "$TARGET_DIR/clean-install.json" <<'PYCODE'
import json, sys
with open(sys.argv[1]) as file: state = json.load(file)
if not isinstance(state.get('spacemouse'), bool): raise SystemExit('Invalid clean installation state.')
print('on' if state['spacemouse'] else 'off')
PYCODE
)"
  [[ "$SPACE" == on ]] && ENABLE_SPACE=1
elif [[ "$SPACE" == on ]]; then
  ENABLE_SPACE=1
elif [[ "$SPACE" == auto ]]; then
  if [[ -f "$TARGET_DIR/spacemouse/start.py" || -f "$TARGET_DIR/spacemouse-enabled" ]]; then
    SPACE=on
  elif [[ "$MODE" != apply-update && "$MODE" != resume-clean && -t 0 ]]; then
    read -rp 'Install direct SpaceMouse support? [y/N]: ' answer
    if [[ "${answer:-n}" =~ ^[JjYy] ]]; then SPACE=on; ENABLE_SPACE=1; else SPACE=off; fi
  else
    SPACE=off
  fi
fi

for manager_tool in c++ pkg-config; do
  command -v "$manager_tool" >/dev/null || { echo "Fusion Manager requires $manager_tool." >&2; exit 1; }
done
pkg-config --exists Qt6Widgets || { echo 'Fusion Manager requires Qt 6 Widgets development files (qt6-base-dev / qt6-base).' >&2; exit 1; }
make -C "$SCRIPT_DIR/layer"
make -C "$SCRIPT_DIR/manager"
if [[ "$SPACE" == on ]]; then
  command -v systemctl >/dev/null || { echo 'SpaceMouse requires a systemd user session.' >&2; exit 1; }
  bash "$SCRIPT_DIR/spacemouse/build.sh"
fi

if [[ "$MODE" == clean || "$MODE" == resume-clean ]]; then
  clean_args=(--target "$TARGET_DIR" --prefix "$PREFIX")
  if [[ "$MODE" == clean ]]; then
    clean_args+=(--clean-install)
    [[ "$SPACE" == on ]] && clean_args+=(--spacemouse)
    [[ -n "$REQUESTED_PROTON" ]] && clean_args+=(--proton "$REQUESTED_PROTON")
  else
    clean_args+=(--resume-clean "$RESUME_ACTION")
    [[ -n "$EXPECTED_CLEAN_STATE" ]] && clean_args+=(--expected-clean-state "$EXPECTED_CLEAN_STATE")
  fi
  [[ -n "$INSTALLER" ]] && clean_args+=(--installer "$INSTALLER")
  exec python3 -u "$SCRIPT_DIR/scripts/setup_runtime.py" "${clean_args[@]}"
fi

setup_args=(--target "$TARGET_DIR" --prefix "$PREFIX")
[[ "$MODE" == apply-update ]] && setup_args+=(--update)
[[ "$SPACE" == on ]] && setup_args+=(--spacemouse)
[[ "$ENABLE_SPACE" == 1 ]] && setup_args+=(--enable-spacemouse)
python3 "$SCRIPT_DIR/scripts/setup_runtime.py" "${setup_args[@]}"
if [[ -n "$REQUESTED_PROTON" ]]; then
  python3 - "$TARGET_DIR" "$REQUESTED_PROTON" <<'PYCODE'
from pathlib import Path
import sys
app, proton = map(Path, sys.argv[1:])
proton = proton.expanduser().resolve()
if not (proton / 'proton').is_file(): raise SystemExit('The selected Proton folder does not contain a proton launcher.')
(app / 'proton-version').write_text(proton.name + '\n')
(app / 'proton-path').write_text(str(proton) + '\n')
PYCODE
fi

echo 'Done. Manage: fusion-manager; Launch: autodesk-fusion; Update: autodesk-fusion-update'
if [[ "$SPACE" == on ]]; then
  echo 'SpaceMouse: adjust axes, buttons and camera in Fusion Manager. In Fusion, use the Legacy SpaceMouse driver.'
fi

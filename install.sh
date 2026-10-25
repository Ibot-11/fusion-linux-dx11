#!/usr/bin/env bash
# Autodesk Fusion Linux setup and updates. No system packages are installed.
set -euo pipefail
VERSION="1.1.0"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/autodesk-fusion"
MODE="menu"
SPACE="auto"
INSTALLER=""

usage() {
  cat <<'HELP'
Verwendung: ./install.sh [MODUS] [INSTALLATIONSORDNER] [OPTIONEN]
  --patch             Vorhandene Fusion-Installation einrichten
  --clean             Autodesk-Installer starten und Linux-Integration einrichten
  --update, -u        Git-Branch aktualisieren und neuen Repo-Stand installieren
  --apply-update      Aktuellen Checkout lokal anwenden (ohne Git-Download)
  --build-layer       Nur den Vulkan-Layer kompilieren
  --with-spacemouse   SpaceMouse-Unterstützung bauen und aktivieren
  --without-spacemouse SpaceMouse-Komponente nicht installieren/ändern
  --installer DATEI   Vorhandene Autodesk-Installer-EXE für --clean
  --version, -v       Version anzeigen
  --help, -h          Diese Hilfe
Ohne Argumente startet das Menü. Updates behalten Prefix, Proton, GPU-, DXVK-
und SpaceMouse-Einstellungen. Fusion muss vorher vollständig geschlossen sein.
HELP
}

while (($#)); do
  case "$1" in
    --version|-v) echo "fusion-linux-dx11 installer version $VERSION"; exit 0 ;;
    --help|-h) usage; exit 0 ;;
    --patch|--clean|--update|--apply-update|--build-layer|-u)
      [[ "$MODE" == menu ]] || { echo 'Bitte nur einen Modus wählen.' >&2; exit 1; }
      MODE="${1#--}"; [[ "$MODE" == -u ]] && MODE=update
      ;;
    --with-spacemouse) SPACE=on ;;
    --without-spacemouse) SPACE=off ;;
    --installer) shift; INSTALLER="${1:?--installer benötigt einen Dateipfad}" ;;
    --*) echo "Unbekannte Option: $1" >&2; usage; exit 1 ;;
    *) TARGET_DIR="$1" ;;
  esac
  shift
done

if [[ "$MODE" == menu ]]; then
  echo "Autodesk Fusion Linux – Installer v$VERSION"
  echo '1) Vorhandene Installation einrichten'
  echo '2) Frische Neuinstallation'
  echo '3) Installation aus dem Git-Repository aktualisieren'
  echo '4) Nur Vulkan-Layer kompilieren'
  echo '5) Beenden'
  read -rp 'Auswahl [1-5]: ' choice
  case "$choice" in
    1) MODE=patch ;; 2) MODE=clean ;; 3) MODE=update ;;
    4) MODE=build-layer ;; 5) exit 0 ;; *) exit 1 ;;
  esac
  if [[ "$MODE" != build-layer ]]; then
    read -rp "Installationsverzeichnis [$TARGET_DIR]: " chosen
    TARGET_DIR="${chosen:-$TARGET_DIR}"
  fi
fi

command -v python3 >/dev/null || { echo 'Bitte Python 3 installieren.' >&2; exit 1; }
TARGET_DIR="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$TARGET_DIR")"

if [[ "$MODE" == update ]]; then
  command -v git >/dev/null || { echo 'Bitte Git installieren.' >&2; exit 1; }
  update_args=(--repo "$SCRIPT_DIR" --target "$TARGET_DIR")
  [[ "$SPACE" == on ]] && update_args+=(--with-spacemouse)
  [[ "$SPACE" == off ]] && update_args+=(--without-spacemouse)
  exec python3 "$SCRIPT_DIR/scripts/update.py" "${update_args[@]}"
fi

for tool in cc make; do
  command -v "$tool" >/dev/null || { echo "Bitte $tool installieren (build-essential / base-devel)." >&2; exit 1; }
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
if fusion_running(): raise SystemExit('Bitte Fusion vor der Einrichtung/Aktualisierung vollständig schließen.')
PYCODE

if [[ "$MODE" == apply-update && ! -d "$TARGET_DIR" ]]; then
  echo "Installation fehlt: $TARGET_DIR" >&2; exit 1
fi
if [[ "$MODE" == patch && ! -d "$TARGET_DIR" ]]; then
  echo "Installation fehlt: $TARGET_DIR; für eine neue Installation --clean verwenden." >&2; exit 1
fi
if [[ "$MODE" == clean && ( -f "$TARGET_DIR/prefix-dir" || -d "$TARGET_DIR/compatdata-exp-dx11/pfx" ) ]]; then
  echo 'Hier ist bereits eine Installation vorhanden. Bitte --patch oder --update verwenden.' >&2; exit 1
fi

PREFIX="compatdata-exp-dx11"
if [[ "$MODE" == apply-update && -f "$TARGET_DIR/prefix-dir" ]]; then
  PREFIX="$(cat "$TARGET_DIR/prefix-dir")"
elif [[ "$MODE" == patch && ! -d "$TARGET_DIR/$PREFIX" ]]; then
  SOURCE_PREFIX="compatdata"
  [[ -f "$TARGET_DIR/prefix-dir" ]] && SOURCE_PREFIX="$(cat "$TARGET_DIR/prefix-dir")"
  python3 - "$SOURCE_PREFIX" <<'PYCODE'
from pathlib import Path
import sys
p=sys.argv[1]
if not p or Path(p).name != p or p in ('.','..'): raise SystemExit('Ungültiger Quell-Prefix-Ordnername.')
PYCODE
  [[ -d "$TARGET_DIR/$SOURCE_PREFIX" ]] || { echo 'Kein Prefix gefunden. Bitte zuerst --clean ausführen oder prefix-dir korrekt setzen.' >&2; exit 1; }
  echo "Erstelle ein isoliertes DX11-Prefix aus $SOURCE_PREFIX …"
  cp -a --reflink=auto "$TARGET_DIR/$SOURCE_PREFIX" "$TARGET_DIR/$PREFIX"
fi
python3 - "$PREFIX" <<'PYCODE'
from pathlib import Path
import sys
p=sys.argv[1]
if not p or Path(p).name != p or p in ('.','..'): raise SystemExit('Ungültiger Prefix-Ordnername.')
PYCODE

ENABLE_SPACE=0
if [[ "$SPACE" == on ]]; then
  ENABLE_SPACE=1
elif [[ "$SPACE" == auto ]]; then
  if [[ -f "$TARGET_DIR/spacemouse/start.py" || -f "$TARGET_DIR/spacemouse-enabled" ]]; then
    SPACE=on
  elif [[ "$MODE" != apply-update && -t 0 ]]; then
    read -rp 'SpaceMouse-Unterstützung mit Einstellungsdialog installieren? [j/N]: ' answer
    if [[ "${answer:-n}" =~ ^[JjYy] ]]; then SPACE=on; ENABLE_SPACE=1; else SPACE=off; fi
  else
    SPACE=off
  fi
fi

make -C "$SCRIPT_DIR/layer"
if [[ "$SPACE" == on ]]; then
  command -v kdialog >/dev/null || { echo 'Bitte kdialog für den SpaceMouse-Einstellungsdialog installieren.' >&2; exit 1; }
  command -v systemctl >/dev/null || { echo 'SpaceMouse benötigt eine systemd-Benutzersitzung.' >&2; exit 1; }
  bash "$SCRIPT_DIR/spacemouse/build.sh"
fi

setup_args=(--target "$TARGET_DIR" --prefix "$PREFIX" --version "$VERSION")
[[ "$MODE" == apply-update ]] && setup_args+=(--update)
[[ "$SPACE" == on ]] && setup_args+=(--spacemouse)
[[ "$ENABLE_SPACE" == 1 ]] && setup_args+=(--enable-spacemouse)
python3 "$SCRIPT_DIR/scripts/setup_runtime.py" "${setup_args[@]}"

if [[ "$MODE" == clean ]]; then
  if [[ -z "$INSTALLER" ]]; then
    command -v curl >/dev/null || { echo 'Bitte curl installieren oder --installer DATEI angeben.' >&2; exit 1; }
    INSTALLER="$TARGET_DIR/Fusion360installer.exe"
    echo 'Lade den offiziellen Autodesk-Installer herunter …'
    curl --fail --location --retry 2 'https://dl.appstreaming.autodesk.com/production/installers/Fusion360installer.exe' -o "$INSTALLER"
  fi
  [[ -f "$INSTALLER" ]] || { echo "Installer nicht gefunden: $INSTALLER" >&2; exit 1; }
  INSTALLER="$(realpath "$INSTALLER")"
  echo 'Bitte dem Autodesk-Setup folgen und Fusion danach schließen.'
  "$TARGET_DIR/run-proton.sh" "$INSTALLER"
  python3 "$SCRIPT_DIR/scripts/setup_runtime.py" "${setup_args[@]}"
fi

echo 'Fertig. Start: autodesk-fusion; spätere Updates: autodesk-fusion-update'
if [[ "$SPACE" == on ]]; then
  echo 'SpaceMouse: Einstellungen über „Fusion SpaceMouse“. In Fusion den SpaceMouse-Treiber „Ältere / Legacy“ verwenden.'
fi

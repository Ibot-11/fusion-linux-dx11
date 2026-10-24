#!/usr/bin/env bash
# ==============================================================================
# Autodesk Fusion 360 - Linux DirectX 11 & Proton Experimental Setup
# High-Performance CAD/CAM auf Linux ohne Snapping-Lag und ohne MSAA-Blackscreen
# ==============================================================================
set -euo pipefail

VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/autodesk-fusion"

# Farben
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log_err "Erforderlicher Befehl '$1' nicht gefunden. Bitte installiere: $2"
    return 1
  fi
  return 0
}

check_prerequisites() {
  log_info "Überprüfe Systemvoraussetzungen..."
  check_command "gcc" "gcc (Basis-Entwicklungswerkzeuge / base-devel / build-essential)" || exit 1
  check_command "python3" "python3" || exit 1

  # Steam / Proton Check
  local steam_found=0
  local proton_dirs=(
    "$HOME/.local/share/Steam"
    "$HOME/.steam/root"
    "$HOME/.steam/steam"
    "$HOME/.var/app/com.valvesoftware.Steam/.local/share/Steam"
  )
  for s in "${proton_dirs[@]}"; do
    if [[ -d "$s" ]]; then
      steam_found=1
      STEAM_DIR="$s"
      break
    fi
  done

  if [[ $steam_found -eq 0 ]]; then
    log_warn "Steam-Verzeichnis wurde nicht automatisch gefunden."
    log_warn "Stelle sicher, dass Steam installiert ist und 'Proton - Experimental' heruntergeladen wurde."
  else
    log_ok "Steam gefunden unter: $STEAM_DIR"
    if [[ -d "$STEAM_DIR/steamapps/common/Proton - Experimental" ]]; then
      log_ok "'Proton - Experimental' ist in Steam installiert."
    else
      log_warn "'Proton - Experimental' wurde noch nicht in Steam gefunden."
      log_warn "Tipp: Öffne Steam -> Bibliothek -> Werkzeuge -> Installiere 'Proton - Experimental'."
    fi
  fi
}

build_vulkan_layer() {
  log_info "Kompiliere Vulkan-Präsentations-Layer..."
  make -C "$SCRIPT_DIR/layer" clean >/dev/null 2>&1 || true
  make -C "$SCRIPT_DIR/layer"
  if [[ ! -f "$SCRIPT_DIR/layer/libVkLayer_fusion_present_sync.so" ]]; then
    log_err "Vulkan-Layer konnte nicht kompiliert werden."
    exit 1
  fi
  log_ok "Vulkan-Layer erfolgreich gebaut."
}

deploy_desktop_files() {
  log_info "Richte Desktop-Icons und Verknüpfungen ein..."
  local app_dir="$1"
  local apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  local icons_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
  mkdir -p "$apps_dir" "$icons_dir"

  if [[ -f "$SCRIPT_DIR/desktop/autodesk-fusion.png" ]]; then
    cp "$SCRIPT_DIR/desktop/autodesk-fusion.png" "$icons_dir/autodesk-fusion.png"
  fi

  sed "s|@APP_DIR@|$app_dir|g" "$SCRIPT_DIR/desktop/autodesk-fusion.desktop.in" > "$apps_dir/autodesk-fusion.desktop"
  sed "s|@APP_DIR@|$app_dir|g" "$SCRIPT_DIR/desktop/autodesk-fusion-callback.desktop.in" > "$apps_dir/autodesk-fusion-callback.desktop"
  chmod +x "$apps_dir/autodesk-fusion.desktop" "$apps_dir/autodesk-fusion-callback.desktop"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" 2>/dev/null || true
  fi
  log_ok "Desktop-Einträge installiert."
}

apply_dx11_patches() {
  local target="$1"
  local prefix_name="${2:-compatdata-exp-dx11}"
  log_info "Wende DX11-, Layer- und Input-Fixes auf $target an..."

  mkdir -p "$target" "$target/logs" "$target/cache"

  # 1. Vulkan Layer kopieren
  cp "$SCRIPT_DIR/layer/libVkLayer_fusion_present_sync.so" "$target/"
  sed "s|\./libVkLayer_fusion_present_sync\.so|$target/libVkLayer_fusion_present_sync.so|g" \
      "$SCRIPT_DIR/layer/VkLayer_fusion_present_sync.json" > "$target/VkLayer_fusion_present_sync.json"

  # 2. dxvk.conf installieren
  cp "$SCRIPT_DIR/config/dxvk.conf" "$target/dxvk.conf"

  # 3. Falls Production-Verzeichnis existiert, dxvk.conf auch dort spiegeln
  local prod_dir
  prod_dir="$(find "$target/$prefix_name/pfx/drive_c/users" -type d -path "*/Autodesk/webdeploy/production/*" 2>/dev/null | head -1 || true)"
  if [[ -n "$prod_dir" && -d "$prod_dir" ]]; then
    cp "$SCRIPT_DIR/config/dxvk.conf" "$prod_dir/dxvk.conf"
    log_ok "dxvk.conf in Fusion-Production-Ordner platziert: $prod_dir"
  fi

  # 4. Skripte & Binaries installieren
  cp "$SCRIPT_DIR/bin/panel-fix.exe" "$target/" 2>/dev/null || true
  cp "$SCRIPT_DIR/bin/panel-fix.c" "$target/" 2>/dev/null || true
  cp "$SCRIPT_DIR/scripts/run-proton.sh" "$target/run-proton.sh"
  cp "$SCRIPT_DIR/scripts/launch.sh" "$target/launch.sh"
  cp "$SCRIPT_DIR/scripts/switch-mode.sh" "$target/switch-mode.sh"
  cp "$SCRIPT_DIR/scripts/browser-listener.py" "$target/browser-listener.py"
  cp "$SCRIPT_DIR/scripts/browser-request.py" "$target/browser-request.py"
  cp "$SCRIPT_DIR/scripts/callback.py" "$target/callback.py"
  cp "$SCRIPT_DIR/scripts/window-fix.py" "$target/window-fix.py"

  # 5. Vendor-Bibliotheken (python-xlib)
  mkdir -p "$target/vendor"
  cp -r "$SCRIPT_DIR/vendor/"* "$target/vendor/"

  chmod +x "$target"/*.sh "$target"/*.py

  # 6. Symlink in ~/.local/bin
  mkdir -p "$HOME/.local/bin"
  ln -sf "$target/launch.sh" "$HOME/.local/bin/autodesk-fusion"

  # 7. Prefix-Zeiger setzen
  printf '%s\n' "$prefix_name" > "$target/prefix-dir"
  printf 'Proton - Experimental\n' > "$target/proton-version"
  chmod 600 "$target/prefix-dir" "$target/proton-version"

  # 8. Registry optimieren (DragWidth / DragHeight = 10; UseTakeFocus entfernen)
  local user_reg="$target/$prefix_name/pfx/user.reg"
  if [[ -f "$user_reg" ]]; then
    log_info "Optimiere Wine-Registry (Input-Toleranz gegen versehentliche Tangenten-Gesten)..."
    # Entferne evtl. veraltete UseTakeFocus Zeilen
    sed -i '/"UseTakeFocus"/d' "$user_reg"
    # Prüfe [Control Panel\\Desktop]
    if grep -q '\[Control Panel\\\\Desktop\]' "$user_reg"; then
      sed -i '/\[Control Panel\\\\Desktop\]/,/\[/{ /"DragWidth"/d; /"DragHeight"/d; }' "$user_reg"
      sed -i '/\[Control Panel\\\\Desktop\]/a "DragHeight"="10"\n"DragWidth"="10"' "$user_reg"
    fi
    log_ok "Registry erfolgreich angepasst."
  fi

  deploy_desktop_files "$target"
  log_ok "Patch erfolgreich angewendet!"
}

patch_existing() {
  local target="${1:-$TARGET_DIR}"
  if [[ ! -d "$target" ]]; then
    log_err "Zielverzeichnis '$target' existiert nicht!"
    return 1
  fi

  echo ""
  log_info "Vorhandene Installation in: $target"

  # Prüfe vorhandene Prefixe
  local source_prefix="compatdata"
  if [[ ! -d "$target/$source_prefix" ]]; then
    if [[ -d "$target/compatdata-exp-dx11" ]]; then
      source_prefix="compatdata-exp-dx11"
    else
      log_warn "Kein Standard-Prefix ('compatdata') gefunden."
      read -rp "Name des Quell-Prefix-Ordners in $target: " source_prefix
    fi
  fi

  local target_prefix="compatdata-exp-dx11"
  if [[ "$source_prefix" == "compatdata" && ! -d "$target/$target_prefix" ]]; then
    log_info "Klone Quell-Prefix ('$source_prefix') nach '$target_prefix' (Btrfs-Reflink / Copy-on-Write falls möglich)..."
    cp -a --reflink=auto "$target/$source_prefix" "$target/$target_prefix"
    log_ok "Isoliertes DX11-Prefix erstellt: $target/$target_prefix"
  fi

  build_vulkan_layer
  apply_dx11_patches "$target" "$target_prefix"
}

clean_install() {
  local target="${1:-$TARGET_DIR}"
  log_info "Starte Neuinstallation in: $target"
  mkdir -p "$target"

  build_vulkan_layer
  apply_dx11_patches "$target" "compatdata-exp-dx11"

  local installer_path=""
  echo ""
  echo "Für die Installation wird der offizielle Autodesk Fusion 360 Installer benötigt."
  echo "Optionen:"
  echo "  1) Automatisch von Autodesk herunterladen"
  echo "  2) Pfad zu vorhandener Fusion360installer.exe angeben"
  read -rp "Auswahl [1/2]: " inst_choice

  if [[ "$inst_choice" == "2" ]]; then
    read -rp "Pfad zur Installer-Datei: " installer_path
    if [[ ! -f "$installer_path" ]]; then
      log_err "Datei nicht gefunden: $installer_path"
      exit 1
    fi
  else
    log_info "Lade Fusion360installer.exe herunter..."
    installer_path="$target/Fusion360installer.exe"
    curl -L "https://dl.appstreaming.autodesk.com/production/installers/Fusion360installer.exe" -o "$installer_path"
    log_ok "Download abgeschlossen."
  fi

  log_info "Starte Autodesk Fusion Installer mit Proton - Experimental..."
  log_info "Bitte folge dem Setup-Fenster auf dem Bildschirm bis die Installation fertig ist."
  "$target/run-proton.sh" "$installer_path"

  log_info "Installation beendet. Synchronisiere Einstellungen..."
  apply_dx11_patches "$target" "compatdata-exp-dx11"
  log_ok "Alles eingerichtet! Du kannst Fusion nun über das Startmenü oder '~/.local/bin/autodesk-fusion' starten."
}

if [[ "${1:-}" == "--version" || "${1:-}" == "-v" ]]; then
  echo "fusion-linux-dx11 installer version $VERSION"
  exit 0
fi

check_prerequisites

if [[ "${1:-}" == "--patch" ]]; then
  patch_existing "${2:-$TARGET_DIR}"
  exit 0
elif [[ "${1:-}" == "--clean" ]]; then
  clean_install "${2:-$TARGET_DIR}"
  exit 0
fi

echo ""
echo "===================================================================="
echo "  Autodesk Fusion 360 - Linux DX11 / Proton Installer (v$VERSION)"
echo "===================================================================="
echo "1) Vorhandene Fusion-Installation auf DX11 & Snapping-Fix patchen (Empfohlen)"
echo "2) Frische Neuinstallation (Download + Proton Prefix Setup)"
echo "3) Nur Vulkan-Präsentations-Layer neu kompilieren"
echo "4) Beenden"
echo "===================================================================="
read -rp "Bitte wähle eine Option [1-4]: " choice

case "$choice" in
  1)
    read -rp "Pfad zur Fusion-Installation [$TARGET_DIR]: " user_dir
    patch_existing "${user_dir:-$TARGET_DIR}"
    ;;
  2)
    read -rp "Installationsverzeichnis [$TARGET_DIR]: " user_dir
    clean_install "${user_dir:-$TARGET_DIR}"
    ;;
  3)
    build_vulkan_layer
    read -rp "Soll die .so nach $TARGET_DIR kopiert werden? [J/n]: " cp_choice
    if [[ "${cp_choice:-j}" =~ ^[JjYy] ]]; then
      cp "$SCRIPT_DIR/layer/libVkLayer_fusion_present_sync.so" "$TARGET_DIR/"
      log_ok "Kopiert nach $TARGET_DIR/libVkLayer_fusion_present_sync.so"
    fi
    ;;
  4)
    echo "Abgebrochen."
    exit 0
    ;;
  *)
    log_err "Ungültige Auswahl."
    exit 1
    ;;
esac

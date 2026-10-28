# Autodesk Fusion unter Linux — DirectX 11

**English: [README.md](README.md)**

Autodesk Fusion unter Linux mit Proton, DXVK und einem nativen Qt-Manager ausführen. Das Projekt enthält Korrekturen für Darstellung und Eingabe, Unterstützung für die Autodesk-Anmeldung im Browser und eine optionale direkte SpaceMouse-Anbindung.

## Funktionen

- DirectX-11-Darstellung mit Proton Experimental und DXVK
- Grafische Installation, Updates und Laufzeitauswahl mit dem Fusion Manager
- Isolierte Wine-Prefixes und ein OpenGL-Fallback-Profil
- Optionale SpaceMouse-Unterstützung für Achsen, Tasten und Kamerageschwindigkeit
- Manager-Oberfläche auf Deutsch und Englisch

Fusion ist proprietäre Software und nicht Bestandteil dieses Repositories. Ein Autodesk-Konto und eine gültige Fusion-Lizenz sind erforderlich.

## Voraussetzungen

- Eine 64-Bit-Linux-Distribution mit Vulkan-fähigen Grafiktreibern
- Steam mit installiertem **Proton Experimental**
- Python 3, Git, curl, ein C/C++17-Compiler, Make, pkg-config, Qt-6-Widgets-Entwicklungsdateien und Vulkan-Header
- Bash, GNU coreutils, GNU findutils und `xdg-open` (`xdg-utils`)
- Optional für SpaceMouse: eine systemd-Benutzersitzung; Polkit für die einmalige Einrichtung des Gerätezugriffs

Build-Abhängigkeiten installieren:

```bash
# Debian / Ubuntu
sudo apt install build-essential pkg-config python3 git curl xdg-utils qt6-base-dev qt6-base-dev-tools libvulkan-dev

# Fedora
sudo dnf install gcc gcc-c++ make pkgconf-pkg-config python3 git curl xdg-utils qt6-qtbase-devel vulkan-headers

# Arch Linux / CachyOS
sudo pacman -S --needed base-devel pkgconf python git curl xdg-utils qt6-base vulkan-headers
```

Steam starten und unter **Bibliothek → Werkzeuge** das Laufzeitwerkzeug **Proton Experimental** installieren. Außerdem den passenden Vulkan-Treiber für die AMD-, Intel- oder NVIDIA-GPU aus den Paketquellen der Distribution installieren.

## Installation

### 1. Repository herunterladen

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
```

Diesen Checkout behalten: Der Fusion Manager verwendet ihn, um nach Updates zu suchen und diese zu installieren.

### 2. Manager oder Installer starten

Empfohlen ist der grafische Manager:

```bash
./manager/run.sh
```

Alternativ die Installation im Terminal:

```bash
# Neue Installation
./install.sh --clean

# Vorhandene Fusion-Installation einbinden
./install.sh --patch
```

Ohne Argumente öffnet `./install.sh` ein interaktives Menü.

### 3. Fusion installieren oder einbinden

Für eine **neue Installation** im Fusion Manager:

1. **Einrichtung** öffnen und einen leeren Installationsordner auswählen.
2. Die installierte Proton-Laufzeit und optional einen anderen Prefix-Namen wählen.
3. **SpaceMouse einbeziehen** nur aktiviert lassen, wenn diese optionale Anbindung gewünscht ist.
4. **Fusion installieren** wählen und dem offiziellen Autodesk-Installer folgen.
5. Fusion nach Abschluss des Autodesk-Setups schließen.

Um eine **vorhandene Installation einzubinden**, deren Ordner auswählen und **Vorhandene übernehmen** wählen. Standardmäßig wird ein isoliertes `compatdata-exp-dx11`-Prefix erstellt oder verwendet. Vorhandene Prefixes und Dokumente werden nicht ersetzt.

Der standardmäßige Installationsordner ist:

```text
~/.local/share/autodesk-fusion
```

Ein abweichender Ordner kann dem Terminal-Installer übergeben werden:

```bash
./install.sh --clean "/pfad/zu/autodesk-fusion"
```

Ein bereits heruntergeladener Autodesk-Installer lässt sich direkt verwenden:

```bash
./install.sh --clean --installer "/pfad/zu/Fusion360installer.exe"
```

### 4. Fusion starten

Den Anwendungsmenü-Eintrag **Autodesk Fusion** verwenden, im Manager **Fusion starten** wählen oder ausführen:

```bash
autodesk-fusion
```

Für die Autodesk-Anmeldung werden HTTP-/HTTPS-Links über `xdg-open` mit dem Standardbrowser des Desktops geöffnet.

## Verwendung

**Fusion Manager** über das Anwendungsmenü oder mit `fusion-manager` starten.

- **Übersicht:** Fusion starten, Versionen anzeigen und die Linux-Integration aktualisieren.
- **SpaceMouse:** Achsen, Tastenkürzel und Kamerageschwindigkeit konfigurieren.
- **Einrichtung:** Installation, Prefix und Proton-Laufzeit auswählen.
- **Aktivität:** Ausgaben einsehen und den Protokollordner öffnen.

In der Seitenleiste **English** oder **Deutsch** wählen und den Neustart bestätigen. Die Auswahl ändert den Manager und wird beim nächsten Start auf die Fusion-Benutzersprache angewendet.

Zum Wechseln des Grafikprofils Fusion schließen und im Installationsordner `./switch-mode.sh exp-dx11` oder `./switch-mode.sh ge-opengl` ausführen. Das OpenGL-Profil verwendet das neueste installierte GE-Proton und das `compatdata`-Prefix; `./switch-mode.sh status` zeigt die aktive Auswahl.

## Updates

Fusion schließen, **Übersicht** öffnen und **Prüfen** sowie **Aktualisieren** wählen. Alternativ:

```bash
./install.sh --update
```

Updates akzeptieren ausschließlich Fast-Forward-Git-Änderungen und brechen bei lokalen oder unversionierten Dateien ab. Benutzereinstellungen und Prefixes bleiben erhalten. Ersetzte Integrationsdateien werden unter `backups/updates/` gesichert; dies ist keine Sicherung von Fusion-Dokumenten oder des vollständigen Wine-Prefix. Fusion selbst wird durch Autodesk aktualisiert.

Den aktuellen Checkout ohne Herunterladen von Änderungen anwenden:

```bash
./install.sh --apply-update
```

## Optionale SpaceMouse-Unterstützung

SpaceMouse während der Installation aktivieren oder später ergänzen:

```bash
./install.sh --apply-update --with-spacemouse
```

Direkt unterstützt wird **SpaceMouse Wireless mit dem USB Universal Receiver (`256f:c652`)**. Fehlt der direkte Gerätezugriff, im Manager **Gerätezugriff einrichten** wählen, die Polkit-Abfrage bestätigen und den Empfänger neu verbinden. Es wird kein Root-Hintergrunddienst installiert.

Weitere Informationen: [SpaceMouse-Kompatibilität und technische Details](spacemouse/README.md).

## Weitere Informationen

- [Fusion Manager: Bedienung und Tests](manager/README.md)
- [SpaceMouse: Kompatibilität und Diagnose](spacemouse/README.md)

## Lizenz

Der ursprüngliche Starter und der Vulkan-Layer stehen unter der MIT-Lizenz. Der Manager und die SpaceMouse-Brücke verwenden GPL-3.0-or-later; enthaltene Drittkomponenten behalten ihre jeweiligen Lizenzen. Siehe `LICENSE` und die Hinweise unter `spacemouse/`.

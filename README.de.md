# Autodesk Fusion 360 auf Linux (DirectX 11 & Proton Experimental)

[![Release](https://img.shields.io/github/v/release/Ibot-11/fusion-linux-dx11?color=brightgreen)](https://github.com/Ibot-11/fusion-linux-dx11/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-orange.svg)]()
[![Backend: DirectX 11 / DXVK](https://img.shields.io/badge/Graphics-DirectX%2011%20(DXVK)-red.svg)]()

> [!NOTE]
> 🇬🇧 **[Click here for English documentation](README.md)**

Dieses Repository ermöglicht es, **Autodesk Fusion 360** unter Linux mit **DirectX 11 (DXVK)** und **Proton - Experimental** in voller nativer Performance auszuführen – ohne die bekannten Bugs wie schwarze Viewports oder den berüchtigten „Snapping-Cursor-Lag“.

---

## 🚀 Warum dieses Setup?

Traditionell wird Fusion 360 unter Wine/Proton meist mit dem alten **OpenGL Core Profile** betrieben. Das führt häufig zu:
* Träger Navigation und schlechter Framerate bei komplexeren Skizzen und Baugruppen
* Hoher CPU-Last und fehlenden modernen GPU-Features
* Grafikfehlern unter Wayland

Der Wechsel auf DirectX 11 scheiterte bisher meist an zwei kritischen Problemen:
1. **Schwarzer Bildschirm / Viewport:** Wine/DXVK kann Multi-Sample Render Targets (MSAA) in eingebetteten Qt-Child-Windows oft nicht auflösen. Zudem erzwingt Autodesks Cloud-Sync immer wieder Qualitäts-Profile mit MSAA.
2. **Snapping-Bug (Mauszeiger hängt hinterher):** Beim Fangen von Punkten in Skizzen bleibt das Fang-Symbol am alten Punkt kleben, bis man die Maus hin- und herwackelt. Dies liegt daran, dass Wine das Child-Window via `StretchBlt` kopiert, *bevor* die GPU den Vulkan-Frame fertig gezeichnet hat (Frame $N-1$ Bug).
3. **Deadlocks & Klick-Verlust:** Schwebende Maßangaben-Fenster (150×45 px) und versehentlich ausgelöste Tangentenbogen-Gesten („Auto-Arc“) bei Linksklicks.

**Dieses Projekt behebt alle diese Probleme vollständig.**

---

## ✨ Features & Technische Lösungen

* **Eigener Vulkan-Präsentations-Layer (`libVkLayer_fusion_present_sync`):**
  Fängt `vkQueuePresentKHR` ab und synchronisiert die GPU via `vkQueueWaitIdle` – jedoch **ausschließlich auf dem großen 3D-Canvas** ($\ge 500\times 500$ px im Immediate-Modus). Dadurch wird das grüne Fang-Symbol sofort beim Bewegen aktualisiert, ohne Deadlocks bei schwebenden HUD-Fenstern zu verursachen.
* **Nativer Microsoft Direct3D Shader-Compiler (`d3dcompiler_47`):**
  Ersetzt den unvollständigen Wine-Stub durch die offizielle Microsoft `d3dcompiler_47.dll` aus dem Autodesk-Programmverzeichnis. Garantiert fehlerfreie Kompilierung aller HLSL-Shadermodelle für 3D-Körper, Beleuchtung, Kantendarstellung und intakte Tiefenpuffer.
* **Multi-Threading-Sicherheit:**
  `d3d11.enableContextLock = True` verhindert Race-Conditions zwischen dem 3D-Zeichenbereich und den Qt-Overlays.
* **Präzise Klick-Erkennung:**
  Durch Anpassen von `DragWidth` und `DragHeight` auf 10 Pixel in der Wine-Registry werden minimale Handbewegungen beim Linksklick nicht mehr fälschlicherweise als Tangentenbogen-Geste abgebrochen.
* **Proton & NTSync:**
  Volle Nutzung von Kernel-NTSync (z. B. unter CachyOS / Linux 6.x+) für Synchronisations-Performance auf Windows-Niveau.
* **Wayland & SSO-Login:**
  Integrierte Helfer für Autodesk-Browser-Anmeldung (`adsk:` Protokoll-Handler) und Dialogfenster-Management unter KDE Plasma / GNOME.
* **Profil-Umschalter (`switch-mode.sh`):**
  Erlaubt das Umschalten zwischen dem DX11-Modus und dem stabilen OpenGL-Fallback mit einem einzigen Befehl.

---

## 📋 Voraussetzungen

1. **Linux Distribution:** Arch Linux, CachyOS, Fedora, Ubuntu, Debian, SteamOS etc.
2. **Vulkan-Grafiktreiber:** 
   * AMD: Mesa RADV (`vulkan-radeon`)
   * Nvidia: Proprietärer Nvidia-Treiber (`nvidia-utils`)
   * Intel: Mesa ANV (`vulkan-intel`)
3. **Steam:** Installiert mit **Proton - Experimental** (in Steam: Bibliothek $\rightarrow$ Werkzeuge $\rightarrow$ *Proton Experimental* installieren).
4. **Build-Tools:** `gcc`, `make`, `python3`, Vulkan-Entwicklungsheader; `git` für Updates.
5. **Optional SpaceMouse:** `g++`, `pkg-config`, Qt-6-Widgets-Entwicklungswerkzeuge, X11-Entwicklungsheader, `kdialog` und eine systemd-Benutzersitzung. Debian/Ubuntu: `build-essential pkg-config libvulkan-dev qt6-base-dev qt6-base-dev-tools libx11-dev kdialog`; Arch/CachyOS: `base-devel vulkan-headers qt6-base libx11 kdialog`.

---

## 🛠️ Installation

Klone das Repository und starte das Setup-Skript:

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
./install.sh
```

Das Menü bietet Installation, Aktualisierung und separaten Layer-Build:

### Option 1: Vorhandene Installation patchen (Empfohlen)
Falls du Fusion 360 bereits über ein anderes Skript (z. B. cryinkfly / Fusion180) installiert hast:
* Das Skript erstellt ein sicheres, isoliertes Prefix (`compatdata-exp-dx11`), sodass deine bestehende Installation unangetastet bleibt.
* Kompiliert und installiert den Vulkan-Layer.
* Richtet DXVK, Registry-Tweaks und Desktop-Starter ein.

### Option 2: Frische Neuinstallation
* Lädt den offiziellen Autodesk Fusion Installer herunter.
* Initialisiert ein frisches Prefix mit Proton - Experimental.
* Wendet automatisch alle Fixes an und erstellt Startmenü-Einträge.

## Vorhandene Installation aktualisieren

Fusion vorher schließen. Im Installer **Aktualisieren** wählen oder ausführen:

```bash
./install.sh --update
# Bei abweichendem Installationsordner:
./install.sh --update "/pfad/zu/autodesk-fusion"
```

Nach der ersten Einrichtung mit dieser Version gibt es außerdem den Menüeintrag
**Fusion aktualisieren** und den Befehl `autodesk-fusion-update`.

Der Updater holt den vom Checkout verfolgten Git-Branch und führt den **neu
heruntergeladenen Installer** aus. Er akzeptiert ausschließlich Fast-Forward-Updates.
Bei lokalen Änderungen, unversionierten Dateien oder auseinanderlaufender Historie
bricht er ab; er setzt nichts zurück und legt keinen automatischen Stash an.
Wurde der ursprüngliche Checkout gelöscht, kann der installierte Updater dessen
gespeichertes Repo und Branch erneut klonen. Mit `./install.sh --apply-update`
lässt sich der aktuelle lokale Stand ohne Download anwenden.

Erhalten bleiben das aktive Wine-Prefix, die Proton-Version, Modelle, `gpu.conf`,
DXVK-Konfiguration und SpaceMouse-Einstellungen einschließlich einer deaktivierten
Anbindung. Neue DXVK-Vorgaben liegen zum Vergleichen in `dxvk.conf.dist`.
Ersetzte Linux-Programmdateien werden unter `backups/updates/<Zeitstempel>/` im
Installationsordner gesichert. Diese Sicherung enthält Helfer und Einstellungen,
**keine vollständige Kopie des Wine-Prefix oder der Dokumente**. Aktualisiert wird
die Linux-Integration aus diesem Repo; Fusion selbst behält seinen Autodesk-Updater.

## SpaceMouse Wireless

Im Installer SpaceMouse auswählen oder bei einer vorhandenen Installation ergänzen:

```bash
./install.sh --apply-update --with-spacemouse
```

Der Installer baut den privaten FreeSpacenav-Treiber, das Relay und die
Qt-Einstellungsanwendung aus den mitgelieferten Quellen. Die passende x86_64-SDK-DLL
liegt samt vollständigem Quellcode bei; mit installiertem MinGW wird sie neu gebaut.
Der Build benötigt keine weiteren Code-Downloads und installiert keinen Root-Treiber.
Getestet wurde die **SpaceMouse Wireless am USB-Universal-Receiver**.

Im Anwendungsmenü **Fusion SpaceMouse** öffnen: Dort lassen sich Kamerageschwindigkeit,
Achsen und Tasten einstellen. `fusion-spacemouse.service` startet den Treiber bei
Bedarf. Der Gerätezugriff verwendet die Eingaberechte der Desktop-Sitzung. Bei
fehlendem Zugriff helfen `journalctl --user -u fusion-spacemouse.service` und die
Eingabegeräte-Einstellungen der Distribution. Es wird keine global beschreibbare
Geräteregel eingerichtet.

Die Brücke wählt vor dem Fusion-Start automatisch den SpaceMouse-Treiber
**Ältere / Legacy**. Die portable Kameravorgabe ist 25%; vorhandene Einstellungen
bleiben erhalten, auch die hier getesteten 20%. Zwischenwerte benötigen eine für
Fusion **2705.1.30** geprüfte Gleitkomma-Erweiterung. Bei anderen Versionen bleiben
die nativen Stufen 25/50/75/100%; Details stehen in der [SpaceMouse-Anleitung](spacemouse/README.md).
Die Achsenwerte werden ohne reduzierte Treiberempfindlichkeit oder zusätzliche
Bündelung weitergereicht. Moderne 3DxWare-Radialmenüs und vollständige
Anwendungsprofile sind nicht implementiert.

Zum Deaktivieren samt Wiederherstellung des ursprünglichen SDK Fusion schließen:

```bash
python3 ~/.local/share/autodesk-fusion/spacemouse/control.py disable
# Wieder aktivieren:
python3 ~/.local/share/autodesk-fusion/spacemouse/control.py enable
```

`--without-spacemouse` überspringt diese Komponente beim Einrichten/Aktualisieren.
Eine bereits deaktivierte Anbindung bleibt bei normalen Updates deaktiviert.

---

## 🕹️ Profil wechseln (`switch-mode.sh`)

Im Installationsordner (`~/.local/share/autodesk-fusion`) befindet sich das Umschalt-Skript:

```bash
# Auf DirectX 11 umschalten (schnell, snappy, DXVK):
./switch-mode.sh exp-dx11

# Auf OpenGL zurückschalten (Fallback):
./switch-mode.sh ge-opengl

# Aktuellen Status anzeigen:
./switch-mode.sh status
```

---

## 📂 Projektstruktur

```
fusion-linux-dx11/
├── install.sh                  # Interaktives Setup- & Patch-Skript
├── README.md                   # Diese Dokumentation
├── config/
│   └── dxvk.conf               # Optimierte DXVK-Konfiguration
├── layer/
│   ├── Makefile                # Kompilierung des Vulkan-Layers
│   ├── libVkLayer_fusion_present_sync.c # C-Quellcode des Synchronisations-Layers
│   └── VkLayer_fusion_present_sync.json # Manifest für den Vulkan Loader
├── bin/
│   ├── panel-fix.c             # Quellcode für Toolpanel-Management
│   └── panel-fix.exe           # Vorkompilierte Win32-Hilfsanwendung
├── scripts/
│   ├── launch.sh               # Haupt-Starter mit automatischer Log-Rotation
│   ├── run-proton.sh           # Hardware-agnostischer Proton-Starter
│   ├── switch-mode.sh          # Profil-Umschalter
│   ├── browser-listener.py     # Autodesk SSO Login-Server
│   ├── browser-request.py      # Browser-Dispatcher
│   ├── callback.py             # URL-Protokoll-Handler (adsk://)
│   └── window-fix.py           # Wayland Fenster-Verwaltung
├── desktop/
│   ├── autodesk-fusion.png     # Anwendungs-Icon (256x256)
│   ├── autodesk-fusion.desktop.in
│   └── autodesk-fusion-callback.desktop.in
└── vendor/
    └── Xlib/                   # Eingebettetes python-xlib
```

---

## 📄 Lizenz

Der ursprüngliche Linux-Starter und der Vulkan-Layer stehen unter der MIT-Lizenz.
SpaceMouse-Brücke, spacenavd und spnavcfg verwenden GPL-3.0-or-later, libspnav
BSD-3-Clause und MinHook seine eigene BSD-artige Lizenz. Quellen und Lizenztexte
liegen unter `spacemouse/` und `third_party/spacenav/` bei.

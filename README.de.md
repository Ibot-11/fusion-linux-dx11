# Autodesk Fusion 360 auf Linux (DirectX 11 & Proton Experimental)

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
* **Treibereitige MSAA-Sperre (`dxvk.conf`):**
  Durch `d3d11.disableMsaa = True` ignoriert DXVK Anfragen für Multisampling. Der Viewport bleibt dauerhaft glasklar sichtbar – selbst wenn Autodesk Cloud-Sync die Einstellungen überschreibt.
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
4. **Build-Tools:** `gcc`, `make`, `python3`

---

## 🛠️ Installation

Klone das Repository und starte das Setup-Skript:

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
./install.sh
```

Das Menü bietet zwei Hauptoptionen:

### Option 1: Vorhandene Installation patchen (Empfohlen)
Falls du Fusion 360 bereits über ein anderes Skript (z. B. cryinkfly / Fusion180) installiert hast:
* Das Skript erstellt ein sicheres, isoliertes Prefix (`compatdata-exp-dx11`), sodass deine bestehende Installation unangetastet bleibt.
* Kompiliert und installiert den Vulkan-Layer.
* Richtet DXVK, Registry-Tweaks und Desktop-Starter ein.

### Option 2: Frische Neuinstallation
* Lädt den offiziellen Autodesk Fusion Installer herunter.
* Initialisiert ein frisches Prefix mit Proton - Experimental.
* Wendet automatisch alle Fixes an und erstellt Startmenü-Einträge.

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

MIT License – Frei zur Nutzung, Anpassung und Weiterverbreitung.

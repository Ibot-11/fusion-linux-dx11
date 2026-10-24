# Autodesk Fusion 360 on Linux (DirectX 11 & Proton Experimental)

[![Release](https://img.shields.io/github/v/release/Ibot-11/fusion-linux-dx11?color=brightgreen)](https://github.com/Ibot-11/fusion-linux-dx11/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-orange.svg)]()
[![Backend: DirectX 11 / DXVK](https://img.shields.io/badge/Graphics-DirectX%2011%20(DXVK)-red.svg)]()

> [!NOTE]
> 🇩🇪 **[Hier klicken für die deutsche Dokumentation](README.de.md)**

Run **Autodesk Fusion 360** natively on Linux with **DirectX 11 (DXVK)** and **Proton - Experimental** at maximum performance — without the notorious black viewports or the cursor snapping lag.

---

## 🚀 Why this project?

Traditionally, running Fusion 360 under Wine/Proton required falling back to the legacy **OpenGL Core Profile**. This came with severe downsides:
* Choppy navigation, low framerates in complex sketches, and sluggish 3D viewport performance
* Excessive CPU overhead and lack of modern GPU hardware acceleration
* Suboptimal behavior and rendering glitches on Wayland compositors

Attempting to run DirectX 11 via DXVK previously failed due to three critical showstoppers:

1. **Black Screen / Viewport:** Wine/DXVK child-window redirection often fails to resolve Multi-Sample Anti-Aliasing (MSAA) render targets. In addition, Autodesk's Cloud Sync continuously re-enables quality presets with MSAA enabled on startup.
2. **Snapping Cursor Lag (Frame $N-1$ Bug):** When snapping to vertices or edges in sketch mode, the green snap icon remained stuck on the previous position until the user wiggled the mouse. This happened because Wine called `NtGdiStretchBlt` immediately upon presentation without waiting for the asynchronous GPU execution to complete.
3. **Deadlocks & Dropped Clicks:** Floating dimension HUD edit boxes (e.g. `1.50 mm` / `90.0°`) run in tiny FIFO/VSync swapchains, which caused deadlocks with global presentation synchronization, and tight click thresholds accidentally triggered Fusion's "Tangent Arc" gesture instead of placing lines.

**This project completely solves all of these issues.**

---

## ✨ Features & Technical Solutions

* **Custom Native Vulkan Presentation Layer (`libVkLayer_fusion_present_sync`):**
  Intercepts `vkQueuePresentKHR` and calls `vkQueueWaitIdle` **specifically on the main 3D canvas** ($\ge 500\times 500$ px in `IMMEDIATE` mode). Secondary swapchains (floating dimension toolbars, HUDs, FIFO swapchains) are safely ignored. This instantly updates the snapping indicator without wiggling the mouse and without risking deadlocks.
* **Driver-Level MSAA Lock (`dxvk.conf`):**
  `d3d11.disableMsaa = True` tells DXVK to force sample count 1 at the driver level, ensuring the viewport never goes black even if Autodesk Cloud Sync changes options.
* **Multi-Threading Safety:**
  `d3d11.enableContextLock = True` prevents race conditions between the main 3D drawing thread and floating Qt child windows.
* **Reliable Left-Click Registration:**
  Calibrates `DragWidth` and `DragHeight` to `10` in the Wine registry, preventing minimal finger movement during clicking from being falsely interpreted as a cancelled "Auto-Arc" gesture.
* **Kernel NTSync & Proton:**
  Fully compatible with Valve's Proton Experimental and Linux kernel NTSync for Windows-grade synchronization speed and thread responsiveness.
* **Wayland & SSO Browser Authentication:**
  Includes integrated helper scripts for Autodesk SSO login (`adsk:` URL scheme handler) and proper Qt/Wine toolbar management under KDE Plasma and GNOME.
* **Profile Switcher (`switch-mode.sh`):**
  Effortlessly switch between the high-performance DX11 setup and the fallback OpenGL mode with a single command.

---

## 📋 Prerequisites

1. **Linux Distribution:** Arch Linux, CachyOS, Fedora, Ubuntu, Debian, SteamOS, etc.
2. **Vulkan Graphics Drivers:**
   * **AMD:** Mesa RADV (`vulkan-radeon`)
   * **NVIDIA:** Proprietary Nvidia drivers (`nvidia-utils`)
   * **Intel:** Mesa ANV (`vulkan-intel`)
3. **Steam:** Installed with **Proton - Experimental** (In Steam: *Library* $\rightarrow$ *Tools* $\rightarrow$ install *Proton Experimental*).
4. **Build Tools:** `gcc`, `make`, `python3`

---

## 🛠️ Installation

Clone the repository and run the setup script:

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
./install.sh
```

The interactive installer provides two main modes:

### Option 1: Patch an Existing Installation (Recommended)
If you already have Fusion 360 installed via another script (such as cryinkfly's installer or Fusion180):
* Automatically creates an isolated prefix (`compatdata-exp-dx11`), leaving your existing installation intact as a fallback.
* Compiles and installs the native Vulkan presentation layer.
* Applies the DX11 configuration, registry fixes, and desktop shortcuts.

### Option 2: Clean New Installation
* Downloads the official Autodesk Fusion installer.
* Initializes a fresh prefix with Proton - Experimental.
* Applies all DX11 performance optimizations and creates application menu entries.

---

## 🕹️ Switching Profiles (`switch-mode.sh`)

Inside the installation directory (`~/.local/share/autodesk-fusion`), you can switch profiles anytime:

```bash
# Switch to DirectX 11 (High Performance, DXVK, Snapping Fix):
./switch-mode.sh exp-dx11

# Switch back to OpenGL (Safe Fallback):
./switch-mode.sh ge-opengl

# Show current status:
./switch-mode.sh status
```

---

## 📂 Repository Structure

```
fusion-linux-dx11/
├── install.sh                  # Interactive setup and patching script
├── README.md                   # English documentation
├── README.de.md                # German documentation
├── config/
│   └── dxvk.conf               # Tuned DXVK configuration
├── layer/
│   ├── Makefile                # Builds the Vulkan layer in milliseconds
│   ├── libVkLayer_fusion_present_sync.c # C source code for the Vulkan presentation sync layer
│   └── VkLayer_fusion_present_sync.json # Manifest for the Vulkan Loader
├── bin/
│   ├── panel-fix.c             # C source for tool panel management
│   └── panel-fix.exe           # Precompiled Win32 helper application
├── scripts/
│   ├── launch.sh               # Main launcher with automatic log rotation
│   ├── run-proton.sh           # Hardware-agnostic Proton runner (AMD, Nvidia, Intel)
│   ├── switch-mode.sh          # Profile switcher
│   ├── browser-listener.py     # Autodesk SSO login listener
│   ├── browser-request.py      # Browser dispatcher
│   ├── callback.py             # URL protocol handler (adsk://)
│   └── window-fix.py           # Wayland window management
├── desktop/
│   ├── autodesk-fusion.png     # Application icon (256x256)
│   ├── autodesk-fusion.desktop.in
│   └── autodesk-fusion-callback.desktop.in
└── vendor/
    └── Xlib/                   # Embedded python-xlib (zero pip dependency)
```

---

## 📄 License

MIT License – Free to use, modify, and distribute.

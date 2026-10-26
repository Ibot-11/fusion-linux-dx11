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

* **Fusion Manager:**
  Native Qt application for installation, real Fusion/repository versions, Git updates, prefix/Proton selection and SpaceMouse settings.
* **Direct SpaceMouse support:**
  Preferred direct HID reader with zero default deadzone, unchanged hardware counts and a clearly limited evdev fallback; configure axes, buttons and camera speed in one place.
* **Custom Native Vulkan Presentation Layer (`libVkLayer_fusion_present_sync`):**
  Intercepts `vkQueuePresentKHR` and calls `vkQueueWaitIdle` **specifically on the main 3D canvas** ($\ge 500\times 500$ px in `IMMEDIATE` mode). Secondary swapchains (floating dimension toolbars, HUDs, FIFO swapchains) are safely ignored. This instantly updates the snapping indicator without wiggling the mouse and without risking deadlocks.
* **Native Microsoft Direct3D Shader Compiler (`d3dcompiler_47`):**
  Overrides Wine's incomplete built-in compiler with the official Microsoft `d3dcompiler_47.dll` shipped directly inside Autodesk Fusion. Ensures complex 3D HLSL shaders (PBR surfaces, depth testing, visible edges, and lighting) compile with full fidelity and intact depth-stencil buffers.
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
4. **Build tools and Manager:** C/C++17 compiler, `make`, `pkg-config`, `python3`, Qt 6 Widgets development files, Vulkan headers; `git` for updates. Debian/Ubuntu: `build-essential pkg-config libvulkan-dev qt6-base-dev`; Arch/CachyOS: `base-devel vulkan-headers qt6-base`.
5. **Optional SpaceMouse:** a systemd user session and desktop-session read access to the reviewed raw-HID input. A one-time explicit access action uses pkexec/Polkit if needed. No spacenav, uinput, pip or root driver is required.

---

## 🛠️ Installation

Clone the repository and run the setup script:

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
./install.sh
```

The native **Fusion Manager** can be launched before installation with
`./manager/run.sh`, or afterwards with `fusion-manager`. It manages installation,
Git versions/updates, installed Proton/prefixes, launch, status and SpaceMouse.
See [Manager instructions and tests](manager/README.md). The command-line
installer remains available for installation, update and build modes:

### Option 1: Patch an Existing Installation (Recommended)
If you already have Fusion 360 installed via another script (such as cryinkfly's installer or Fusion180):
* Automatically creates an isolated prefix (`compatdata-exp-dx11`), leaving your existing installation intact as a fallback.
* Compiles and installs the native Vulkan presentation layer.
* Applies the DX11 configuration, registry fixes, and desktop shortcuts.

### Option 2: Clean New Installation
* Downloads the official Autodesk Fusion installer.
* Initializes a fresh prefix with Proton - Experimental.
* Applies all DX11 performance optimizations and creates application menu entries.

## Updating an existing installation

Close Fusion, then choose **Update** in the installer or run:

```bash
./install.sh --update
# Custom installation directory:
./install.sh --update "/path/to/autodesk-fusion"
```

After the first setup with this version, **Fusion aktualisieren** is also available
in the application menu, or run `autodesk-fusion-update`.

The updater fetches the current checkout's tracked Git branch, accepts only a
fast-forward, and runs the **newly fetched installer**. It refuses local changes,
untracked files and divergent history; it never resets or stashes your work.
If the original checkout was removed, the installed updater can clone its recorded
repository and branch again. `./install.sh --apply-update` applies the current
checkout without fetching, useful for offline installs and development.

Updates preserve the selected Wine prefix, Proton version, models, `gpu.conf`,
DXVK settings and SpaceMouse settings, including whether SpaceMouse is disabled.
New DXVK defaults are saved as `dxvk.conf.dist` for comparison. Replaced Linux
runtime files are backed up under `backups/updates/<timestamp>/` in the installation
directory. These backups contain helper files and settings, **not a backup of
the complete Wine prefix or your documents**. Autodesk Fusion itself continues to
use Autodesk's own updater; this command updates the Linux integration from this repo.

## SpaceMouse Wireless

Choose SpaceMouse during setup, or add it to an existing installation:

```bash
./install.sh --apply-update --with-spacemouse
```

The installer builds the native Qt Fusion Manager and installs a direct Linux
HID input reader (reviewed USB 256f:c652 profile), an explicitly limited evdev fallback, and the matching open-source Wine SDK DLL. No spacenav
runtime, separate relay or global virtual keyboard is used. MinGW can rebuild
the DLL; a SHA-256-verified x86_64 build is supplied. The tested device is
**SpaceMouse Wireless through the USB Universal Receiver**.

Open **Fusion Manager → SpaceMouse** for live axes, button bindings and camera
speed. Default deadzone is 0; left/right default to ESC/I and act only while
Fusion has focus. The per-user service opens the real input device using the
desktop session's permissions. Missing raw access is shown as **Raw device access required**.
The explicit **Set up access** action uses pkexec with a fixed helper
to add an identity-restricted uaccess rule; reconnect the receiver afterwards.
No world-writable device rule or root daemon is installed. The fallback cuts off
a held state after 250 ms without ABS changes, so full native holding requires HID.
HID motion is forwarded without synthetic repetition; a 250-ms motion-report
safety timeout neutralizes stale input even if battery/status reports continue. Hardware counts are preserved,
including adjacent values, with native [X,-Z,-Y,RX,-RZ,-RY] mapping. The former
±350→±500 integer normalization is removed, so a preserved camera percentage
can feel slower. See [input and migration contracts](spacemouse/README.md).

The bridge selects Fusion's **Legacy / Ältere** SpaceMouse driver before launch.
The portable camera default is 25%; existing settings are kept, including the
tested 20% setting. Speeds between the native steps use a floating-point extension
verified for Fusion **2705.1.30**. Other builds retain native 25/50/75/100% steps;
see [SpaceMouse details](spacemouse/README.md) for compatibility and diagnostics.
**Apply** also updates a supported running Fusion session, with **Live** shown
after confirmation. The same value is saved for future starts. Button mappings
use **Record shortcut…** for individual keys or combinations.
Axis input integers are forwarded without sensitivity reduction or extra batching.
Modern 3DxWare radial menus and full application profiles are not implemented.

To disable and restore the original SDK, close Fusion and run:

```bash
python3 ~/.local/share/autodesk-fusion/spacemouse/control.py disable
# Re-enable:
python3 ~/.local/share/autodesk-fusion/spacemouse/control.py enable
```

`--without-spacemouse` skips that component during setup/update. An already
disabled component remains disabled during normal updates.

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

The original Linux launcher and presentation layer use the MIT license.
The native Manager and SpaceMouse bridge use GPL-3.0-or-later; MinHook retains
its own BSD-style license. Corresponding source and license notices are included
under `spacemouse/`. The formerly vendored spacenav components have been removed.

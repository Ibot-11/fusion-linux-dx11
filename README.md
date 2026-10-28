# Autodesk Fusion on Linux — DirectX 11

**Deutsch: [README.de.md](README.de.md)**

Run Autodesk Fusion on Linux with Proton, DXVK and a native Qt Manager. The project includes viewport and input fixes, Autodesk browser sign-in support and optional direct SpaceMouse integration.

## Features

- DirectX 11 rendering with Proton Experimental and DXVK
- Graphical installation, updates and runtime selection with Fusion Manager
- Isolated Wine prefixes and an OpenGL fallback profile
- Optional SpaceMouse axes, buttons and camera-speed controls
- English and German Manager interface

Fusion is proprietary software and is not included. An Autodesk account and a valid Fusion license are required.

## Requirements

- A 64-bit Linux distribution with Vulkan-capable graphics drivers
- Steam with **Proton Experimental** installed
- Python 3, Git, curl, a C/C++17 compiler, Make, pkg-config, Qt 6 Widgets development files and Vulkan headers
- Bash, GNU coreutils, GNU findutils and `xdg-open` (`xdg-utils`)
- Optional SpaceMouse support: a systemd user session; Polkit for the one-time device-access setup

Install the build dependencies:

```bash
# Debian / Ubuntu
sudo apt install build-essential pkg-config python3 git curl xdg-utils qt6-base-dev qt6-base-dev-tools libvulkan-dev

# Fedora
sudo dnf install gcc gcc-c++ make pkgconf-pkg-config python3 git curl xdg-utils qt6-qtbase-devel vulkan-headers

# Arch Linux / CachyOS
sudo pacman -S --needed base-devel pkgconf python git curl xdg-utils qt6-base vulkan-headers
```

In Steam, enable the Steam client, open **Library → Tools**, and install **Proton Experimental**. Install the appropriate Vulkan driver for your AMD, Intel or NVIDIA GPU using your distribution's packages.

## Installation

### 1. Download this repository

```bash
git clone https://github.com/Ibot-11/fusion-linux-dx11.git
cd fusion-linux-dx11
```

Keep this checkout: Fusion Manager uses it to check for and install updates.

### 2. Start the Manager or installer

The graphical Manager is recommended:

```bash
./manager/run.sh
```

For a terminal installation instead:

```bash
# New installation
./install.sh --clean

# Integrate an existing Fusion installation
./install.sh --patch
```

Without arguments, `./install.sh` opens an interactive menu.

### 3. Install or adopt Fusion

For a **new installation** in Fusion Manager:

1. Open **Setup** and choose an empty installation folder.
2. Select the installed Proton runtime and, optionally, change the prefix name.
3. Leave **Include SpaceMouse** enabled only if you want that optional integration.
4. Choose **Install Fusion** and follow Autodesk's official installer.
5. Close Fusion after Autodesk's setup has finished.

To **adopt an existing installation**, select its folder and choose **Adopt existing**. The default setup creates or uses an isolated `compatdata-exp-dx11` prefix; your existing prefixes and documents are not replaced.

The default installation folder is:

```text
~/.local/share/autodesk-fusion
```

A custom folder can be passed to the terminal installer:

```bash
./install.sh --clean "/path/to/autodesk-fusion"
```

To use an already downloaded Autodesk installer:

```bash
./install.sh --clean --installer "/path/to/Fusion360installer.exe"
```

### 4. Start Fusion

Use the **Autodesk Fusion** application-menu entry, choose **Launch Fusion** in the Manager, or run:

```bash
autodesk-fusion
```

For Autodesk sign-in, HTTP/HTTPS links are opened with the desktop's default browser through `xdg-open`.

## Everyday use

Start **Fusion Manager** from the application menu or run `fusion-manager`.

- **Overview:** start Fusion, inspect versions and update the Linux integration.
- **SpaceMouse:** configure axes, shortcuts and camera speed.
- **Setup:** select the installation, prefix and Proton runtime.
- **Activity:** inspect command output and open the log folder.

Choose **English** or **Deutsch** in the sidebar and confirm the restart. The selection changes the Manager and is applied to Fusion's user language at its next launch.

To switch graphics profiles, close Fusion and run `./switch-mode.sh exp-dx11` or `./switch-mode.sh ge-opengl` from the installation folder. The OpenGL profile uses the newest installed GE-Proton and the `compatdata` prefix; `./switch-mode.sh status` shows the active selection.

## Updates

Close Fusion, open **Overview**, then choose **Check** and **Update**. Alternatively:

```bash
./install.sh --update
```

Updates accept only fast-forward Git changes and stop when the checkout contains local or untracked files. User settings and prefixes are preserved. Replaced integration files are backed up under `backups/updates/`; this is not a backup of Fusion documents or the complete Wine prefix. Fusion itself is updated by Autodesk.

To apply the current checkout without downloading changes:

```bash
./install.sh --apply-update
```

## Optional SpaceMouse support

Enable SpaceMouse during installation or add it later:

```bash
./install.sh --apply-update --with-spacemouse
```

The directly supported configuration is **SpaceMouse Wireless with the USB Universal Receiver (`256f:c652`)**. If raw-device access is missing, use **Set up device access** in the Manager, approve the Polkit prompt, and reconnect the receiver. No root background service is installed.

See [SpaceMouse compatibility and technical details](spacemouse/README.md).

## More information

- [Fusion Manager usage and verification](manager/README.md)
- [SpaceMouse compatibility and diagnostics](spacemouse/README.md)

## License

The original launcher and Vulkan layer are MIT-licensed. The Manager and SpaceMouse bridge use GPL-3.0-or-later; included third-party components retain their respective licenses. See `LICENSE` and the notices under `spacemouse/`.

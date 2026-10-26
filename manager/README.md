# Fusion Manager 1.2.0

A native Linux application for Fusion, repository updates, Proton profiles and
SpaceMouse settings. The interface is English, with a compact dark theme inspired
by Fusion. Help buttons and expandable details keep explanations and diagnostics
out of the main controls.

Requires Qt 6 Widgets, a C++17 compiler, make/pkg-config and Python 3 (stdlib only).
There is no web server, Electron runtime or permanent root service.

The Manager has its own icon for the application menu, window and sidebar.
Its vector source is `desktop/fusion-manager.svg`; the matching PNG is embedded
in the executable and installed separately from Fusion's icon.

```sh
make -C manager
./manager/run.sh
# Select a different installation:
./manager/run.sh --target /path/to/autodesk-fusion
```

After installation, launch **Fusion Manager** from the application menu or run
`fusion-manager`. The application manages four areas:

- **Overview:** Fusion version, integration version, launch and repository updates.
- **SpaceMouse:** axes, inversion, button bindings, camera speed and device status.
- **Setup:** installation location, source checkout, prefix and Proton runtime.
- **Activity:** operation output and access to log files.

## Installation and updates

Choose an existing installation or an empty destination in Setup. A new
installation uses Autodesk's official installer. Steam and a compatible Proton
runtime must already be installed. Existing installations can be configured or
updated without reinstalling Fusion.

The source checkout can be cloned into an empty folder. Checking for updates
performs an explicit Git fetch. Ahead/behind counts reflect the last fetch.
Installing an update uses a fast-forward only; local edits and divergent history
block it. The updater does not reset, stash or switch branches.

Replaced runtime files are backed up under `backups/updates`. Documents and
prefix, Proton, GPU, DXVK and SpaceMouse preferences are preserved. Autodesk
Fusion itself continues to use its own updater. Applying the current checkout
installs the local integration without fetching Git updates.

An active Fusion session blocks installation, integration updates, SDK changes
and profile changes. Device settings can be saved during a session; camera speed
is queued for the next Fusion start. No Fusion process is terminated by the
manager. Only one manager operation per user runs at a time, and closing the
window cannot interrupt an active install or update.

## Device access and precision

The supported Universal Receiver (`256f:c652`, verified 448-byte HID descriptor)
uses direct HID reports. Native signed counts reach the Wine SDK unchanged;
camera speed is applied after integer input. The default deadzone is zero.
Reports are forwarded individually without synthetic repeats. A 250 ms motion
watchdog sends a neutral state and releases buttons if motion reports stop;
battery and vendor-status packets do not extend that deadline.

If HID access is missing, **Set up access** requests administrator approval
through Polkit. A fixed, argumentless helper creates only
`/etc/udev/rules.d/70-fusion-spacemouse.rules` for that receiver and reloads udev
rules. Reconnect the receiver afterward. Access belongs to the active local
desktop session; no world-writable device permissions or root daemon are used.
Cancelling approval leaves permissions unchanged.

The explicitly identified evdev fallback is limited: a steady deflection stops
after 250 ms without an ABS change. Set up direct HID access for held movement.
Unsupported devices are not treated as a verified motion interface.

## Button assignments

Choose **Record shortcut…** under Left or Right, press the desired key or
combination, then release it. Choose **Use shortcut** and **Save input**.
Single keys, F1–F24, navigation keys, number-pad keys and Ctrl/Shift/Alt/Super/AltGr
combinations are supported. Modifiers can also be assigned as held buttons.
**Type shortcut** accepts a shortcut such as `Ctrl+Shift+S` when the desktop
reserves it and prevents recording. Assignments contain one chord, not macros.

Keyboard actions apply while Fusion has focus. Shared modifiers remain held
until both assigned buttons release them. Focus loss, disconnect and shutdown
release held keys. Printable characters follow Fusion's Windows keyboard layout;
characters unavailable in that layout are rejected. Existing button assignments
survive updates.

## Status and diagnostics

Fusion's version comes from the selected executable's `fusion_version.txt` or
validated `version.json`. Integration version and revision come from
`repo-state.json`; missing metadata remains unknown. Repository information comes
from Git, and device status comes from sysfs, access checks and the local bridge.

Live axes use the bridge's status file at 100 ms intervals. Installation, Git and
Proton status refresh every five seconds. Network access occurs on explicit
actions. Launch output is recorded in `logs/manager-launch.log`. Camera settings
below 25% retain the existing signature check for supported Fusion builds.

## Verification

```sh
make -C layer
make -C manager
make -C manager check
bash spacemouse/build.sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s spacemouse/tests -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen ./manager/run.sh --smoke-test --target /tmp/fusion-empty
QT_QPA_PLATFORM=offscreen ./manager/run.sh --screenshot /tmp/fusion-manager.png
```

`--app-dir` aliases `--target`. Use `--page overview|spacemouse|setup|log` and
`--size 1100x850` for reproducible screenshots. Screenshot and smoke modes only
read status: they do not launch Fusion, change permissions or switch services.
Tests use temporary installations, local Git repositories and synthetic input
on private test ports; privileged actions are mocked.

The manager and direct Linux input layer are original implementations under
GPL-3.0-or-later. The reviewed Wine SDK bridge keeps its GPL license; MinHook
retains its own license. Qt is dynamically linked. See
[SpaceMouse documentation](../spacemouse/README.md) and
[bridge license](../spacemouse/bridge/COPYING).

# Fusion Manager

Native Qt 6 application for installing and launching Fusion, selecting Wine prefixes and Proton runtimes, updating this integration and configuring SpaceMouse. The interface is available in English and German.

## Start

```bash
./manager/run.sh
```

After installation, use the **Fusion Manager** application-menu entry or run `fusion-manager`.

Choose **English** or **Deutsch** in the sidebar. Confirm the restart to apply the language; the selection is saved per user and is also applied to Fusion at its next launch. Without a saved selection, German is used for German system locales and English otherwise.

## Pages

- **Overview:** Fusion and integration versions, launch, repository status and updates.
- **SpaceMouse:** device status, axes, button shortcuts and camera speed.
- **Setup:** installation folder, source checkout, prefix, Proton and Fusion UI scaling.
- **Activity:** operation output and log-folder access.

A different installation can be selected in **Setup → Change folders** or on the command line:

```bash
./manager/run.sh --target /path/to/autodesk-fusion
```

## Installation and updates

A new installation downloads Autodesk's official installer unless an existing installer executable is selected. **Adopt existing** configures an existing Fusion installation; **Apply checkout** deploys local changes without fetching Git updates.

**Check** explicitly fetches the configured remote. **Update** accepts only a fast-forward and refuses local changes or divergent history. The footer explains when no update was started or when the checkout is already current. The updater never resets, stashes or switches branches.

Replaced runtime files are backed up under `backups/updates`. Prefixes, documents and Proton, GPU, DXVK and SpaceMouse preferences are preserved. Fusion itself continues to use Autodesk's updater.

Close Fusion before installation, integration updates, SDK changes or runtime changes. Camera speed can be applied while Fusion is running; if live control is unavailable, it takes effect at the next launch. Only one Manager operation runs at a time, and the window cannot be closed during an active operation.

## Fusion display scaling

Fusion takes its interface scale from the Windows DPI stored in the selected Wine prefix. Open **Setup → Scaling**, close Fusion, choose **Automatic** or a fixed value from 100 % to 200 %, then choose **Apply scaling**. Automatic uses the primary display scale reported when it is applied. A 1080p display at 100 % normally uses 100 %; a 4K display at 150 % uses 150 %.

The setting is stored for the selected prefix, applied through Wine's live registry and re-applied whenever Fusion starts. It takes effect after Fusion is restarted. Other prefixes and the Linux desktop scaling are not changed.

## SpaceMouse access and shortcuts

If direct HID access is missing, choose **Set up device access** and approve the Polkit prompt. The argumentless helper installs an identity-restricted `uaccess` rule for the reviewed Universal Receiver. Reconnect the receiver afterwards. Cancelling leaves permissions unchanged; no root daemon is installed.

Use **Record shortcut…** to assign a key or combination to either SpaceMouse button. **Type shortcut** accepts text such as `Ctrl+Shift+S` when the desktop reserves a combination. Keyboard actions apply only while Fusion has focus and are released on focus loss or disconnect.

See [SpaceMouse compatibility, protocols and diagnostics](../spacemouse/README.md) for supported hardware and limitations.

## Logs and diagnostics

The selected installation contains `logs/manager-launch.log` and the other runtime logs. **Activity → Open log folder** opens this location. Version information comes from the selected Fusion executable and `repo-state.json`; repository information comes from Git.

## Build and verification

Requirements: Python 3, a C++17 compiler, Make, pkg-config, Qt 6 Widgets development tools and Vulkan headers.

```bash
make -C layer
make -C manager
make -C manager check
bash spacemouse/build.sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s spacemouse/tests -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen ./manager/run.sh --smoke-test --target /tmp/fusion-empty
QT_QPA_PLATFORM=offscreen ./manager/run.sh --lang de --smoke-test --target /tmp/fusion-empty
```

`--page overview|spacemouse|setup|log` selects the initial page. `--screenshot /path/to/manager.png` and `--size 1100x850` support reproducible captures. Screenshot and smoke modes only read status and do not launch Fusion, change permissions or switch services.

The Manager and direct Linux input layer are GPL-3.0-or-later. Qt is dynamically linked. Third-party license notices are included under `spacemouse/`.

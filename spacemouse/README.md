# Fusion SpaceMouse integration

Use the existing FreeSpacenav driver and Qt `spnavcfg` settings application with
a reviewed version of Lolig4/DD1984's legacy SDK bridge. Fusion must use its
**Legacy SpaceMouse driver** (German: **Ältere**). The launcher selects it before
starting Fusion, preserving other compatibility preferences. This does not
provide the complete modern 3DxWare feature set.

The daemon normalizes the physical device axes; the bridge forwards these six
values, their signs, timing, buttons and stop events without extra remapping or
batching. Defaults use sensitivity 1.0 and dead zone 5. Confirm the final movement
and orbit behavior in Fusion against the desired 3Dconnexion behavior.

`settings.sh` offers camera speed or the official configuration GUI on the private
driver socket. In spnavcfg, click **Save config** to preserve changes across restarts. A systemd user service
owns the driver and relay; it starts when Fusion or the settings app needs it.
The relay listens only on 127.0.0.1:11111. Device access uses the desktop session's
existing ACL; no root daemon or system package changes are needed.

`python3 control.py disable` restores the original Fusion DLL before disabling the
integration. `enable` installs the reviewed DLL and starts the service. Close
Fusion before changing the integration. Original per-version Fusion DLLs are
retained in `backups/`; installer/update snapshots are in `../backups/updates/`.

## Sources and build

- FreeSpacenav/spacenavd: 6cb68b693fc837ba33b7a2fe682f184faf501496 (unchanged)
- FreeSpacenav/libspnav: 476a17b6087146f95799e3a2a12b4d13cb4d2818 (unchanged)
- FreeSpacenav/spnavcfg: 84543beeed78c41796890b67b56b10287ad610fd (unchanged)
- Bridge base: https://codeberg.org/Lolig4/SpaceMouse_Fusion360_Wine,
  commit 8a60078, with existing local changes and the corrections described in
  the review report. MinHook sources are included under bridge/build-linux/.

The native relay builds with a POSIX C compiler:

```
cc -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Werror -O2 bridge/relay/main.c -o spconvd
make -C bridge/build-linux static
```

Rebuilding the DLL requires the MinGW cross compiler. `make` builds only the static variant
and does not download MSVC or accept third-party license terms. Build libspnav
with `--disable-x11` and spnavcfg with Qt 6, placing libspnav on the include/link
path. The installer uses `build.sh` and the corresponding upstream sources under
`../third_party/spacenav/`. A matching prebuilt x86_64 DLL is included under
`prebuilt/` with its SHA-256 for systems without MinGW. New installations default
to 25% camera speed; updates preserve existing settings and disabled state.

## Validation

`tests/test_relay.py` exercises the real relay with fragmented packets, bursts,
stop events, both buttons, EOF, reconnect and port conflicts. Set TEST_RELAY to
the binary path. `tests/test_proton.py` additionally exercises the compiled DLL
with an actual Proton runner; TEST_RUNTIME names the directory containing the
relay, DLL and compiled tests/sdk-probe.exe, and TEST_PROTON_RUNNER names the
Fusion Proton wrapper. The real SpaceMouse service must be stopped for that
isolated test because both use TCP port 11111. Do not run it during Fusion use.

The Windows probe checks all six signed axes, period, zero, button press/release,
peek versus consume, repeated initialization, teardown and reopen. Hardware
recognition and save/restart persistence were also tested. The final physical
navigation behavior in Fusion still requires the user's check.

The driver, GUI and bridge retain their GPL-3.0-or-later licenses; libspnav retains
its BSD-3-Clause license. The repository's original MIT code stays separate.

## Camera speed without reducing input precision

The settings launcher now offers **Fusion camera speed** and **Axes and buttons**.
The former queues Fusion camera gains; the latter opens spnavcfg. Keep
spnavcfg sensitivity at 1.0 when preserving its existing integer input levels.

Fusion 2705.1.30 has three positive integer camera factors, default 4:
`SpacemousePan`, `SpacemouseZoom`, and `SpacemouseRotation`, in
`UISpaceMouseOptionGroup` of `NMachineSpecificOptions.xml`. The checked native
camera code multiplies the unscaled axis value by the factor, then uses double
precision camera math. Using factor 1 instead of 4 gives 25% of the default
camera speed and keeps adjacent integer input levels distinct.

For speeds below 25%, the SDK bridge also adjusts the SpaceMouse camera's shared
double-precision normalizer in process memory: 1024 / 0.8 = 1280 gives 20% with
native factor 1. The six integer axis samples remain unchanged. No Autodesk file
or camera instruction is patched. This extension is deliberately limited to the
audited Fusion build: PE timestamp, image size, the complete camera routine's
SHA-256 and all six division operands must match. Unrecognized builds or an
unexpected normalizer are left untouched and produce an error in fusion.log.
On those builds the native factors still work, with a minimum of 25%.

`camera_gain.py --queue --percent 20` saves the desired percentage.
`--queue --pan 1 --zoom 1 --rotation 1` remains available for separate native gains.
The Fusion launcher applies them before starting Fusion. While Fusion is open,
its XML is not modified; changes take effect after a complete restart. Existing
XML encoding, unrelated preferences and the Legacy driver setting are preserved.
Changed files are backed up under `backups/camera-gain/`. The supported native
factor range is 1..100; values below 1 cannot be represented by these preferences
alone. The camera dialog accepts 1..100% and combines native factors with the
checked floating-point extension when needed. 25/50/75/100% need no extension.

Ten regression tests cover the XML update, original UTF-16 encoding, preserved
preferences, Legacy selection, existing values, all percentages and invalid/ambiguous input.
`tests/camera-scale-probe.cpp` maps the installed Fusion PE as inert data under
Proton, checks its real code signature, the six division operands, the requested
20% ratio and distinct neighboring input levels, and rejects modified builds.
No Fusion code is executed by that probe. Build it with camera_scale.cpp, log.cpp,
the SDK source include path, and -lbcrypt using MinGW.

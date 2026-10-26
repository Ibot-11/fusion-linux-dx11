# Direct SpaceMouse integration

The Linux input reader and settings UI are implemented in this repository.
Runtime input uses Python 3 stdlib and a reviewed direct hidraw profile, with
a clearly limited evdev fallback. spacenavd,
libspnav, spnavcfg, a relay process and a virtual keyboard are not used. The
native Qt 6 Fusion Manager configures the device. The existing reviewed legacy
Wine SDK bridge remains the compatibility layer inside Fusion. This is not a
complete modern 3DxWare implementation; radial menus and application profiles
are outside this component's scope.

## Input contract

The preferred raw input is restricted to the **USB 256f:c652 Universal Receiver**
with the exact reviewed 448-byte report descriptor, SHA-256
`bb0ee519344bed4b7f5f8373fa66e1ea1d658362c5f5f9e00155d2fd61c0bfca`.
Discovery checks the USB HID identity and descriptor, not a device name or
hidraw index. Four other hidraw interfaces on this receiver have different
feature-only descriptors and are not selected. Unknown firmware/descriptors
need an explicitly reviewed profile; the driver does not guess their layout.
The descriptor and a feature-only counterexample are saved under tests/fixtures/.

The profile declares report 1 as six complete signed little-endian 16-bit
values in -350..350 (13 bytes including report ID), and report 3 as two button
bits (3 bytes including report ID). One hidraw read is one report: every valid
motion report, including identical consecutive reports, is forwarded immediately.
No synthetic HID repetition, batching, filtering or input scaling is performed.
Report 0x17 exposes Battery Strength 0..100 plus an uninterpreted vendor bit;
report 0x1b exposes another uninterpreted vendor bit. Neither bit is treated as
a radio-connection signal. Metadata/button/unknown reports never extend the
motion safety deadline. No LED output or feature report is written.

After **250 ms without a motion report while the last deflection is nonzero**,
the bridge sends one neutral packet and releases its held actions. Later valid
motion resumes normally. This deliberately bounds stale input if the radio link
is lost while the USB receiver stays attached. It is a safety policy, not a
claim about the receiver's sampling rate or a diagnosis of radio loss. A valid
zero report and USB disconnect stop immediately. Actual held-cap/report-cadence
and radio-loss behavior still require a physical test after access is configured;
the descriptor alone cannot establish either behavior.

The **evdev fallback is explicitly incomplete**: it accepts recognized
3Dconnexion/Logitech devices with all six ABS_X/Y/Z/RX/RY/RZ capabilities, excluding
virtual button keyboards. SYN_REPORT commits full persistent axis state;
SYN_DROPPED recovers axes/buttons via EVIOCGABS/EVIOCGKEY. Since evdev suppresses
unchanged states, its existing bounded continuation can only estimate timing.
A held deflection is forcibly neutralized after 250 ms without an ABS motion
frame, even if the cap is still held. The GUI therefore shows **Rohzugriff
einrichten** for the recognized c652 when raw access is missing, and explains
that continuous native holding requires the direct HID input. This fallback
must not be described as full original behavior.

### One-time access setup

Nothing is elevated during status, installation or startup. If existing session
ACLs do not grant raw-device read access, explicitly click **Gerätezugriff
einrichten** in the Manager. `pkexec` asks for administrator authorization and
runs the fixed compiled `fusion-spacemouse-access` helper. It accepts no command
arguments, environment-selected target paths, shell text or commands. It can
only create `/etc/udev/rules.d/70-fusion-spacemouse.rules` with this rule and
reload udev rules using the fixed `/usr/bin/udevadm control --reload-rules`:

```udev
SUBSYSTEM=="hidraw", KERNEL=="hidraw*", ATTRS{idVendor}=="256f", ATTRS{idProduct}=="c652", TAG+="uaccess"
```

The rule grants access through the active local seat; it has no MODE=0666 and
creates no root daemon or global keyboard. It applies only to this receiver's
USB identity; descriptor checking still selects only the axis input. Existing
foreign/symlink/unsafe files with the same rule name are refused. **Unplug and
reconnect the receiver afterwards** in an active local desktop session. No
service restart is performed by the access helper. Missing pkexec, cancellation
or denial are reported in the UI/log. If a rule was saved but udev reload failed,
the helper says so; reboot and reconnect before trying raw input.

For the tested Wireless Universal Receiver (USB 256f:c652), the kernel reports
six signed ranges -350..350, fuzz=0, flat=0. Each original hardware count is
preserved. The standard native object-mode mapping is:

| SDK field | evdev source | Sign |
|---|---|---|
| TX | ABS_X | + |
| TY | ABS_Z | − |
| TZ | ABS_Y | − |
| RX | ABS_RX | + |
| RY | ABS_RZ | − |
| RZ | ABS_RY | − |

This reproduces the previous USB coordinate convention, without copying its
integer range conversion from ±350 to ±500. Consequently the same numerical
camera percentage may feel slower after migration. The stored 15%/20% etc.
values are preserved exactly; adjust camera speed if desired, without scaling
or truncating input integers. No additional hardware bits are claimed.

The same signs/permutation apply to both raw-HID fields [X,Y,Z,RX,RY,RZ]
and evdev axes. Axis options are applied after complete report decoding.

Defaults in `device.json`: deadzone 0, all axes enabled, no added inversions,
left button ESC (cancel), right button I (measure). The UI can disable/invert
individual mapped axes, explicitly set a deadzone, and assign a single key or
modifier chord, a native SDK button or no action. The daemon reloads saved settings within one
second. Rebinding a held button retains its original action through release;
identical keys and shared chord modifiers remain held until their last owner
releases. A button holds its shortcut for the duration of the physical press;
it does not run a macro or repeated command sequence.

Existing `ESC`, `I`, `F`, `HOME`, `1`, `2`, `3`, `off` and `sdk` strings stay valid.
A custom shortcut uses `{"key":"S","modifiers":["CTRL","SHIFT"]}`. Modifier names
are `CTRL`, `SHIFT`, `ALT`, `META` and `ALTGR`; use a modifier as `key` for a
modifier-only hold, such as `{"key":"CTRL","modifiers":[]}`. Keys can be one
printable Unicode BMP character or a named key: `ESC`, `TAB`, `ENTER`,
`BACKSPACE`, `DELETE`, `INSERT`, `HOME`, `END`, `PAGEUP`, `PAGEDOWN`, `LEFT`,
`RIGHT`, `UP`, `DOWN`, `PAUSE`, `PRINTSCREEN`, `CAPSLOCK`, `NUMLOCK`,
`SCROLLLOCK`, `MENU`, `SPACE`, `F1`–`F24`, `NUM0`–`NUM9`, `NUMENTER`, `NUMADD`,
`NUMSUBTRACT`, `NUMMULTIPLY`, `NUMDIVIDE`, or `NUMDECIMAL`.

The focused Windows thread's keyboard layout resolves printable characters via
[VkKeyScanExW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-vkkeyscanexw).
Letters resolve in lowercase; explicit `SHIFT` controls case. Punctuation adds
the modifiers required by that layout. `ALTGR` uses left Ctrl and right Alt;
layout-generated Ctrl+Alt resolves to that same pair. An unavailable character
is ignored with a DLL diagnostic; this is a physical shortcut facility, not an
IME/text-composition interface. Desktop/application-reserved shortcuts can be
intercepted or ignored by the operating system. Qt and Wine should use matching
keyboard layouts when assigning layout-dependent punctuation.

## Bridge and lifecycle

`fusion-spacemouse.service` is a per-user service running only `start.py`.
It opens the preferred reviewed HID input (or the limited evdev fallback) and
listens on 127.0.0.1:11111 for Fusion.
There is no spacenav socket. The binary protocol remains eight little-endian
int32 fields: type 0 contains six complete axes plus period; types 1/2 carry
native SDK button down/up. Type 3 remains backward compatible with the old
whitelisted virtual-key packets. New type 4 is
`[4, button_id, down, encoding, key, modifiers, flags, 0]`: button ID 0/1,
boolean down, encoding 0 for a named Windows VK or 1 for a printable BMP
codepoint, modifier bits Ctrl=1/Shift=2/Alt=4/Meta=8/AltGr=16, and flags=1 for
an extended named key (otherwise 0). Modifier-only holds use encoding 0/key 0.
The DLL validates every field and rejects malformed/unrecognized packets.

Keyboard down is accepted only while a window of the actual Fusion process
has foreground focus. Down/up are sent through Win32 SendInput in that process;
repeated physical downs are ignored. Presses retain their resolved keys through
rebinding/layout changes; main keys release before modifiers. Separate physical
buttons share references to overlapping keys (Ctrl+S with Ctrl+Z, or identical
chords), while ordinary Enter and extended keypad Enter remain distinct.
Held keys release on focus loss (checked every
50 ms), socket disconnect or SDK teardown. The DLL reconnects automatically
after a bridge restart, including when the bridge was absent at initialization. TCP fragmentation cannot block that
focus check. No global Linux keyboard device is created. No SDK event is also
sent when a keyboard action is selected.

The launcher selects Fusion's **Legacy / Ältere** driver before starting Fusion.
Enable/disable restores/installs the reviewed SDK through `control.py`, with
per-version original DLL backups under `backups/`. Close Fusion before changing
the integration. Existing camera-gain.json and device.json survive updates;
legacy settings.conf dead-zone and buttons.json ESC/I are imported only if
no device.json exists. Legacy files are left in the update snapshot for review.

## Sources, build and tests

The SDK bridge derives from John Tsiombikas/Luke Nuttall's emulator and
https://codeberg.org/Lolig4/SpaceMouse_Fusion360_Wine (base commit 8a60078),
with the reviewed protocol, lifecycle and camera changes in this repository.
Its license remains GPL-3.0-or-later; included MinHook sources retain their own
BSD-style license. The direct Linux reader does not link to FreeSpacenav.
The obsolete vendored spacenav sources and native relay have been removed.

`bash spacemouse/build.sh` builds only the Wine DLL with MinGW when available,
or validates the matching prebuilt x86_64 DLL using prebuilt/SHA256SUMS. It does
not download code. `make -C manager` builds the native Qt UI separately.
`tests/test_hidraw.py` covers the actual descriptor/profile gate, all six signed
axes and ±1, unchanged reports, buttons, metadata-independent 250-ms watchdog,
zero and disconnect, plus a real report-boundary→daemon→TCP path on a private
port. The access-action tests mock pkexec and never install a real rule.
`tests/test_evdev.py` exercises the fallback decoder, raw count preservation,
coordinate mapping, buttons, frame fragmentation, SYN_DROPPED, held states,
zero, disconnect and an actual pipe→daemon→TCP path on a private test port.
Optional `proton_probe.py` and `keyboard_probe.py` exercise the actual compiled
Windows DLL, six axes, period, native buttons, legacy/custom keys, shared
modifiers, modifier-only holds, keypad Enter, German ?/@ layout mapping and
ä mapping (or safe rejection when Wine exposes no matching key), focus loss,
transport reconnect and teardown. They require a dedicated Wine prefix/display
and a probe DLL compiled with `-DFUSION_BRIDGE_PORT=11112` (or TEST_PORT), so
production port 11111 and a running Fusion session remain untouched.
`tests/test_keybindings.py` validates saved schemas and packet fields and
compiles/runs the actual portable DLL chord tracker using a C++17 compiler.
It covers duplicate/overlapping ownership, release order, rebinding, failed
injection/release retry and packet rejection. Run all reader/binding tests with
`python3 -m unittest discover -s spacemouse/tests -p 'test_*.py'`.

## Camera speed without reducing input precision

The Fusion Manager provides camera speed, axes and button bindings. Camera
settings do not multiply or quantise the six signed hardware input counts.

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

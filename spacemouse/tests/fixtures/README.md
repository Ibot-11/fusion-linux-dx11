# Universal Receiver report descriptors

Read-only snapshots from the locally attached USB 256f:c652 Universal Receiver:

- `universal-receiver-c652.bin`: `/sys/class/hidraw/hidraw0/device/report_descriptor`, 448 bytes, SHA-256 `bb0ee519344bed4b7f5f8373fa66e1ea1d658362c5f5f9e00155d2fd61c0bfca`.
- `universal-receiver-c652-feature.bin`: `/sys/class/hidraw/hidraw1/device/report_descriptor`, 129 bytes, SHA-256 `5b0467034bac822ed8f75982332659f7f3516eb321a9462d1873aca5374d1c39`.

These contain descriptor/profile facts, not captures of user motion or keys.
Only the first descriptor is accepted as the reviewed axis/button input.
The descriptor declares report layouts, signed ranges and usages; it does not
prove report cadence while held or give a meaning to vendor status bits.
Tests use synthetic full HID reports and a private socket/TCP port. They do not
open productive hidraw nodes, install rules, elevate privileges or change services.

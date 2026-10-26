# SPDX-License-Identifier: GPL-3.0-or-later
"""Reviewed direct HID profile for USB Universal Receiver 256f:c652 only.

The descriptor is an identity gate, not a claim about radio/report cadence.
Only report 1 carries motion. HID read boundaries are complete report boundaries.
"""
import hashlib
import os
from pathlib import Path
import struct
import time
from evdev_input import DEFAULTS, transform

VENDOR = 0x256f
PRODUCT = 0xc652
PROFILE = 'universal-receiver-c652-v1'
DESCRIPTOR_SIZE = 448
DESCRIPTOR_SHA256 = 'bb0ee519344bed4b7f5f8373fa66e1ea1d658362c5f5f9e00155d2fd61c0bfca'
MOTION_TIMEOUT = .250
MOTION = struct.Struct('<B6h')


def matches_profile(descriptor, vendor, product, bus=3):
    return (bus == 3 and vendor == VENDOR and product == PRODUCT and
            len(descriptor) == DESCRIPTOR_SIZE and
            hashlib.sha256(descriptor).hexdigest() == DESCRIPTOR_SHA256)


def discover(sysfs=Path('/sys/class/hidraw'), dev=Path('/dev')):
    result = []
    for entry in sorted(Path(sysfs).glob('hidraw*')):
        try:
            device = entry / 'device'
            properties = dict(line.split('=', 1) for line in (device / 'uevent').read_text().splitlines() if '=' in line)
            bus, vendor, product = [int(value, 16) for value in properties['HID_ID'].split(':')]
            if vendor != VENDOR or product != PRODUCT or bus != 3:
                continue
            descriptor = (device / 'report_descriptor').read_bytes()
            if not matches_profile(descriptor, vendor, product, bus):
                continue
            path = Path(dev) / entry.name
            result.append({'path': str(path), 'name': properties.get('HID_NAME', '3Dconnexion Universal Receiver'),
                           'vendor': vendor, 'product': product, 'backend': 'hidraw',
                           'profile': PROFILE, 'descriptor_sha256': DESCRIPTOR_SHA256,
                           'readable': os.access(path, os.R_OK),
                           'axis_info': [dict(minimum=-350, maximum=350) for _ in range(6)]})
        except (OSError, ValueError, KeyError):
            continue
    return result


class MotionWatchdog:
    """One-shot safety neutralization; only genuine motion renews the deadline."""
    def __init__(self, timeout=MOTION_TIMEOUT):
        self.timeout = timeout
        self.deadline = None
        self.tripped = False

    def motion(self, axes, now):
        self.deadline = now + self.timeout if any(axes) else None
        self.tripped = False

    def due(self, now):
        if self.deadline is None or now < self.deadline:
            return False
        self.deadline = None
        self.tripped = True
        return True

    def wait(self, now):
        return min(.05, max(0, self.deadline-now)) if self.deadline is not None else .05


class Decoder:
    def __init__(self, config=None):
        self.config = config or dict(DEFAULTS)
        self.raw = [0]*6
        self.buttons = [False, False]
        self.last_motion = None
        self.period_us = 0
        self.telemetry = {}
        self.ignored_reports = 0

    def feed(self, report, now=None):
        """Decode one whole hidraw read; malformed reports never change state."""
        now = time.monotonic() if now is None else now
        if not report:
            raise OSError('HID device disconnected')
        report_id = report[0]
        if report_id == 1:
            if len(report) != MOTION.size:
                raise ValueError('Incomplete HID motion report; expected 13 bytes.')
            values = list(MOTION.unpack(report)[1:])
            if any(not -350 <= value <= 350 for value in values):
                raise ValueError('HID motion report exceeds the supported ±350 range.')
            self.period_us = max(0, round((now-self.last_motion)*1000000)) if self.last_motion is not None else 0
            self.last_motion = now
            self.raw = values
            yield ('motion', transform(values, self.config), min(2147483647, self.period_us//1000))
        elif report_id == 3:
            if len(report) != 3 or report[1] & 0xfc or report[2]:
                raise ValueError('Invalid HID button report.')
            for index in range(2):
                pressed = bool(report[1] & (1 << index))
                if pressed != self.buttons[index]:
                    self.buttons[index] = pressed
                    yield ('button', index, pressed)
        elif report_id == 0x17:
            if len(report) != 3 or report[1] > 100 or report[2] & 0xfe:
                raise ValueError('Invalid HID battery report.')
            self.telemetry.update(battery_strength=report[1], vendor_27_bit=report[2] & 1)
        elif report_id == 0x1b:
            if len(report) != 2 or report[1] & 0xfe:
                raise ValueError('Invalid HID status report.')
            # The descriptor declares a vendor bit, not its radio semantics.
            self.telemetry['vendor_28_bit'] = report[1] & 1
        else:
            self.ignored_reports += 1

    def neutralize(self):
        """Forget stale input after USB disconnect or motion watchdog expiry."""
        self.raw = [0]*6
        self.last_motion = None
        for index, pressed in enumerate(self.buttons):
            if pressed:
                self.buttons[index] = False
                yield ('button', index, False)
        yield ('motion', [0]*6, 0)

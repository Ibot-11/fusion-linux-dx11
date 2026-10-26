# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct Linux SpaceMouse input. Only SYN_REPORT commits a six-axis sample.

The USB coordinate transform is (X, -Z, -Y, RX, -RZ, -RY), matching
FreeSpacenav's DF_SWAPYZ | DF_INVYZ convention without a runtime dependency.
No sensitivity multiplication, smoothing, resampling or integer quantisation.
"""
import fcntl
import json
import os
from pathlib import Path
import struct

EVENT = struct.Struct('@llHHi')  # Linux input_event; native timeval ABI
PACKET = struct.Struct('<8i')
AXES = ('x', 'y', 'z', 'rx', 'ry', 'rz')
DEFAULTS = {'deadzone': 0, 'enabled': [True] * 6, 'inverted': [False] * 6,
            'buttons': ['ESC', 'I']}


def settings(path):
    value = json.loads(Path(path).read_text()) if Path(path).exists() else {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Ungültige Geräteeinstellungen.')
    result = dict(DEFAULTS, **value)
    if type(result['deadzone']) is not int or not 0 <= result['deadzone'] <= 100:
        raise ValueError('Deadzone muss zwischen 0 und 100 liegen.')
    for name in ('enabled', 'inverted'):
        if not isinstance(result[name], list) or len(result[name]) != 6 or any(type(x) is not bool for x in result[name]):
            raise ValueError('Sechs boolesche Achseneinstellungen erforderlich.')
    if not isinstance(result['buttons'], list) or len(result['buttons']) != 2 or any(x not in ('off', 'sdk', 'ESC', 'I', 'F', 'HOME', '1', '2', '3') for x in result['buttons']):
        raise ValueError('Unbekannte Tastenbelegung.')
    return result


def transform(raw, config):
    mapped = [raw[0], -raw[2], -raw[1], raw[3], -raw[5], -raw[4]]
    return [(-v if config['inverted'][i] else v)
            if config['enabled'][i] and abs(v) > config['deadzone'] else 0
            for i, v in enumerate(mapped)]


def discover(sysfs=Path('/sys/class/input'), dev=Path('/dev/input')):
    devices = []
    for event in sorted(Path(sysfs).glob('event*')):
        try:
            base = event / 'device'
            name = (base / 'name').read_text().strip()
            vendor = int((base / 'id/vendor').read_text().strip(), 16)
            product = int((base / 'id/product').read_text().strip(), 16)
            # ABS_X..ABS_RZ live in the least significant kernel bitmap word.
            bits = int((base / 'capabilities/abs').read_text().split()[-1], 16)
            if vendor not in (0x256f, 0x046d) or bits & 0x3f != 0x3f:
                continue
            if not any(x in name.lower() for x in ('spacemouse', 'spacepilot', 'spacenavigator', '3dconnexion', 'spaceexplorer')):
                continue
            path = Path(dev) / event.name
            devices.append({'path': str(path), 'name': name, 'vendor': vendor,
                            'product': product, 'readable': os.access(path, os.R_OK)})
            if devices[-1]['readable']:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                    try:
                        devices[-1]['axis_info'] = axis_info(fd)
                    finally:
                        os.close(fd)
                except OSError:
                    pass
        except (OSError, ValueError, IndexError):
            continue
    return devices


def axis_info(fd):
    values = []
    for axis in range(6):
        buf = bytearray(24)  # input_absinfo: value, minimum, maximum, fuzz, flat, resolution
        fcntl.ioctl(fd, (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + axis), buf)
        values.append(dict(zip(('value', 'minimum', 'maximum', 'fuzz', 'flat', 'resolution'), struct.unpack('6i', buf))))
    return values


def axis_state(fd):
    """Read the absolute kernel state, including recovery after SYN_DROPPED."""
    return [value['value'] for value in axis_info(fd)]


def button_state(fd):
    buf = bytearray(96)  # KEY_MAX=0x2ff, including BTN_0/BTN_1
    fcntl.ioctl(fd, (2 << 30) | (len(buf) << 16) | (ord('E') << 8) | 0x18, buf)
    return [bool(buf[code // 8] & (1 << (code % 8))) for code in (0x100, 0x101)]


class Decoder:
    def __init__(self, config=None, recover=None):
        self.config = config or dict(DEFAULTS)
        self.raw = [0] * 6
        self.buffer = b''
        self.dirty = False
        self.dropped = False
        self.recover = recover
        self.last_stamp = None
        self.period_us = 0
        self.buttons = [False, False]

    def feed(self, data):
        """Yield ('motion', axes, ms) or ('button', zero_based_index, pressed).

        Arbitrary read fragmentation is supported. A SYN_DROPPED frame never
        leaks partial state; EVIOCGABS obtains the complete next snapshot.
        """
        self.buffer += data
        while len(self.buffer) >= EVENT.size:
            sec, usec, kind, code, value = EVENT.unpack_from(self.buffer)
            self.buffer = self.buffer[EVENT.size:]
            if kind == 0 and code == 3:
                self.dropped = True
                self.dirty = False
            elif kind == 0 and code == 0:
                if self.dropped:
                    if self.recover is None:
                        raise OSError('Input übergelaufen; Gerätezustand muss neu gelesen werden.')
                    self.raw, recovered_buttons = self.recover()
                    for index, pressed in enumerate(recovered_buttons):
                        if self.buttons[index] != pressed:
                            self.buttons[index] = pressed
                            yield ('button', index, pressed)
                    self.dropped = False
                    self.dirty = True
                if self.dirty:
                    stamp = sec * 1000000 + usec
                    self.period_us = max(0, stamp - self.last_stamp) if self.last_stamp is not None else 0
                    period = min(2147483647, self.period_us // 1000)
                    self.last_stamp = stamp
                    self.dirty = False
                    yield ('motion', transform(self.raw, self.config), period)
            elif not self.dropped and kind == 3 and 0 <= code < 6:
                self.raw[code] = value
                self.dirty = True
            elif not self.dropped and kind == 1 and 0x100 <= code <= 0x101 and value in (0, 1):
                index = code - 0x100
                if self.buttons[index] != bool(value):
                    self.buttons[index] = bool(value)
                    yield ('button', index, bool(value))


class HeldMotion:
    """Continue a held absolute deflection when evdev suppresses duplicates.

    Physical reports are never delayed or merged. ABS changes cannot reveal
    every USB report, so longer gaps must not continually lower the repeat rate.
    Learn a conservative cadence from several observations; allow 1 ms for the
    next real frame before synthesizing a repeat. Never produce catch-up bursts.
    """
    def __init__(self):
        self.axes = [0] * 6
        self.interval = .016
        self.observations = []
        self.measured = False
        self.deadline = None

    def update(self, axes, period, now):
        self.axes = list(axes)
        if 1 <= period <= 50:
            self.observations = (self.observations + [period / 1000])[-24:]
            if len(self.observations) >= 3:
                # A lower quartile ignores long gaps caused by suppressed ABS
                # duplicates. A single short outlier cannot set the cadence.
                ordered = sorted(self.observations)
                measured = ordered[len(ordered) // 4]
                self.interval = min(self.interval, measured) if self.measured else measured
                self.measured = True
        self.deadline = now + self.interval + .001 if any(axes) else None

    def due(self, now):
        if self.deadline is None or now < self.deadline:
            return None
        self.deadline = now + self.interval
        return ('motion', list(self.axes), round(self.interval * 1000))

    def timeout(self, now):
        return min(.05, max(0, self.deadline - now)) if self.deadline is not None else .05

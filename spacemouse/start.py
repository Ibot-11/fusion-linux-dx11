#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Direct reviewed HID input, with an explicitly limited evdev fallback."""
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import sys
import tempfile
import time
from evdev_input import DEFAULTS, Decoder, HeldMotion, PACKET, transform, axis_state, button_state, discover, settings
from hidraw_input import Decoder as HidDecoder, MotionWatchdog, discover as discover_hidraw
from keybindings import button_packet
from camera_control import CameraControl

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'autodesk-fusion-spacemouse'
PORT = 11111
stopping = False


def stop(_sig, _frame):
    global stopping
    stopping = True


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), '\0' + address[1:] if address.startswith('@') else address)


def write_status(state):
    fd, name = tempfile.mkstemp(prefix='.status-', dir=RUNTIME)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(dict(state, timestamp=time.time(), pid=os.getpid()), out)
        os.replace(name, RUNTIME / 'status.json')
    finally:
        Path(name).unlink(missing_ok=True)


def open_input(candidate):
    return os.open(candidate['path'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)


def main():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (RUNTIME / 'driver.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('The Fusion SpaceMouse bridge is already running.', file=sys.stderr)
        lock.close()
        return 1
    selector = selectors.DefaultSelector()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    clients = set()
    camera = CameraControl(ROOT.parent, RUNTIME)
    device = None
    decoder = None
    mode = None
    active_actions = {}
    held = HeldMotion()  # Explicit fallback only; HID reports are never repeated.
    watchdog = MotionWatchdog()
    state = {'app': str(ROOT.parent.resolve()), 'connected': False, 'device': None, 'input_backend': None,
             'axes': [0]*6, 'raw': [0]*6, 'buttons': [False, False],
             'clients': 0, 'error': None, 'warning': None, 'samples': 0,
             'motion_watchdog': False, 'telemetry': {}}
    config = dict(DEFAULTS)
    last_config = last_scan = last_status = 0

    def drop(client):
        selector.unregister(client)
        clients.discard(client)
        camera.remove(client)
        client.close()

    def send(client, packet):
        try:
            if client.send(packet) != len(packet):
                drop(client)
        except (BlockingIOError, OSError):
            drop(client)

    def broadcast(packet):
        if packet is None:
            return
        for client in list(clients):
            # Forward each complete report immediately; no queue/batch.
            send(client, packet)

    def release():
        held.update([0]*6, 0, time.monotonic())
        watchdog.motion([0]*6, time.monotonic())
        broadcast(PACKET.pack(0, 0, 0, 0, 0, 0, 0, 0))
        for index, action in active_actions.items():
            broadcast(button_packet(index, False, action))
        active_actions.clear()
        if decoder is not None:
            decoder.raw = [0]*6
            decoder.buttons = [False, False]
            if mode == 'hidraw':
                decoder.last_motion = None
        state.update(axes=[0]*6, raw=[0]*6, buttons=[False, False])

    def disconnect(error):
        nonlocal device, decoder, mode
        release()
        if device is not None:
            selector.unregister(device)
            os.close(device)
        device = decoder = mode = None
        state.update(connected=False, device=None, input_backend=None, error=error, telemetry={})

    def input_event(kind, value, extra, physical=True):
        if kind == 'motion':
            broadcast(PACKET.pack(0, *value, extra))
            if physical:
                now = time.monotonic()
                watchdog.motion(value, now)
                if mode == 'evdev':
                    held.update(value, decoder.period_us / 1000, now)
                state['motion_watchdog'] = False
                state['samples'] += 1
            state.update(axes=value, raw=list(decoder.raw))
        else:
            action = config['buttons'][value] if extra else active_actions.pop(value, 'off')
            if extra:
                active_actions[value] = action
            broadcast(button_packet(value, extra, action))
            state['buttons'][value] = extra

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.bind(('127.0.0.1', PORT))
        server.listen(4)
        server.setblocking(False)
        selector.register(server, selectors.EVENT_READ, 'server')
        notify('READY=1\nSTATUS=Direct HID bridge ready; waiting for a device')
        while not stopping:
            now = time.monotonic()
            camera.tick(send, now)
            if now - last_config > 1:
                last_config = now
                try:
                    config = settings(ROOT / 'device.json')
                    if decoder:
                        if decoder.config != config:
                            decoder.config = config
                            axes = transform(decoder.raw, config)
                            if axes != state['axes']:
                                # Config changes do not prove fresh physical input.
                                input_event('motion', axes, 0, physical=False)
                                if mode == 'evdev':
                                    held.update(axes, 0, now)
                        state['error'] = None
                except (OSError, ValueError, TypeError) as error:
                    state['error'] = str(error)
            if now - last_scan > 1:
                last_scan = now
                hid_devices = discover_hidraw()
                evdev_devices = [dict(d, backend='evdev') for d in discover()]
                devices = hid_devices + evdev_devices
                state['devices'] = devices
                hid_readable = any(d['readable'] for d in hid_devices)
                state['hid_access_required'] = bool(hid_devices) and not hid_readable
                if device is not None and mode == 'evdev' and hid_readable:
                    disconnect(None)  # Switch to raw reports when access becomes available.
                if device is None:
                    for candidate in devices:
                        if not candidate['readable']:
                            continue
                        try:
                            device = open_input(candidate)
                            mode = candidate['backend']
                            decoder = HidDecoder(config) if mode == 'hidraw' else Decoder(config, recover=lambda: (axis_state(device), button_state(device)))
                            held = HeldMotion()
                            if mode == 'evdev':
                                decoder.raw = axis_state(device)
                                initial = transform(decoder.raw, config)
                                held.update(initial, 0, now)
                                watchdog.motion(initial, now)
                                state.update(axes=initial, raw=list(decoder.raw))
                            selector.register(device, selectors.EVENT_READ, 'device')
                            warning = None if mode == 'hidraw' else ('Limited evdev fallback: no reliable HID report timing. '
                                       'Motion stops after 250 ms without an axis change. '
                                       'Use Set up device access to enable held motion.')
                            state.update(connected=True, device=candidate, input_backend=mode,
                                         error=None, warning=warning, motion_watchdog=False)
                            break
                        except OSError as error:
                            if device is not None:
                                os.close(device)
                            device = decoder = mode = None
                            state['error'] = f"{candidate['path']}: {error}"
                if device is None:
                    message = ('Set up device access: the Universal Receiver needs HID read permission.'
                               if hid_devices else 'No readable SpaceMouse with a supported profile found.')
                    state.update(connected=False, device=None, input_backend=None, error=message)
            timeout = watchdog.wait(time.monotonic())
            if mode == 'evdev':
                timeout = min(timeout, held.timeout(time.monotonic()))
            for key, _mask in selector.select(timeout):
                if key.data == 'server':
                    client, _address = server.accept()
                    client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    client.setblocking(False)
                    clients.add(client)
                    camera.add(client)
                    selector.register(client, selectors.EVENT_READ, 'client')
                elif key.data == 'client':
                    try:
                        data = key.fileobj.recv(4096)
                        if not data or not camera.receive(key.fileobj, data):
                            drop(key.fileobj)
                    except (BlockingIOError, OSError):
                        drop(key.fileobj)
                else:
                    try:
                        # hidraw returns one complete report per read. A large
                        # buffer avoids truncating the reviewed 13-byte report.
                        data = os.read(device, 64 if mode == 'hidraw' else 4096)
                        if not data:
                            raise OSError('SpaceMouse disconnected')
                        events = decoder.feed(data, time.monotonic()) if mode == 'hidraw' else decoder.feed(data)
                        for event in events:
                            input_event(*event)
                        if mode == 'hidraw':
                            state['telemetry'] = dict(decoder.telemetry)
                    except (OSError, ValueError) as error:
                        disconnect(str(error))
            # Metadata/button reports and synthetic repeats never renew this.
            if watchdog.due(time.monotonic()):
                release()
                state['motion_watchdog'] = True
            elif mode == 'evdev':
                repeat = held.due(time.monotonic())
                if repeat is not None:
                    broadcast(PACKET.pack(0, *repeat[1], repeat[2]))
            if now - last_status >= .1:
                last_status = now
                state['clients'] = len(clients)
                state['camera_live'] = camera.status()
                write_status(state)
        return 0
    except (OSError, ValueError) as error:
        print(f'SpaceMouse: {error}', file=sys.stderr, flush=True)
        return 1
    finally:
        release()
        if device is not None:
            os.close(device)
        for client in list(clients):
            drop(client)
        server.close()
        selector.close()
        state.update(connected=False, clients=0, error='Bridge stopped')
        state['camera_live'] = camera.status()
        write_status(state)
        lock.close()


if __name__ == '__main__':
    sys.exit(main())

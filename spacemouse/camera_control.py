# SPDX-License-Identifier: GPL-3.0-or-later
"""Session-bound camera requests over the existing fixed-size bridge stream."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import tempfile
import time

PACKET = struct.Struct('<8i')
HELLO, REQUEST, ACK = 5, 6, 7
VERSION = 1
REASONS = {
    1: 'This Fusion camera build is not supported for live speed changes.',
    2: 'The active session has no verified native camera basis. Restart Fusion with the updated launcher.',
    3: 'The camera normalizer changed outside this bridge; it was left untouched.',
    4: 'The SDK rejected an invalid camera request.',
    5: 'The Fusion camera module is not loaded yet.',
}


def runtime_dir():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'autodesk-fusion-spacemouse'


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def session_record(app, runtime=None):
    value = read_json((runtime or runtime_dir()) / 'camera-session.json')
    if not isinstance(value, dict) or value.get('app') != str(Path(app).resolve()):
        return None
    token = value.get('token')
    try:
        if not isinstance(token, str) or len(token) != 32 or len(bytes.fromhex(token)) != 16:
            return None
    except ValueError:
        return None
    if type(value.get('basis')) is not int or not 0 <= value['basis'] <= 4:
        return None
    return value


def fingerprint(record):
    return hashlib.sha256(bytes.fromhex(record['token'])).hexdigest()[:24]


def create_session(app, basis, percent, runtime=None):
    if type(basis) is not int or not 0 <= basis <= 4 or type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError('A live camera session needs a uniform verified native basis and percentage.')
    runtime = runtime or runtime_dir()
    runtime.mkdir(parents=True, mode=0o700, exist_ok=True)
    value = dict(app=str(Path(app).resolve()), basis=basis, percent=percent,
                 token=secrets.token_hex(16), created=time.time())
    fd, name = tempfile.mkstemp(prefix='.camera-session-', dir=runtime)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out)
        os.chmod(name, 0o600)
        os.replace(name, runtime / 'camera-session.json')
    finally:
        Path(name).unlink(missing_ok=True)
    return value


def selected_status(app, driver, target, runtime=None):
    """Never use another installation/session's global runtime status."""
    fallback = dict(state='saved', target_percent=target,
                    reason='Camera speed is saved for the next launch; no current SDK confirmation is available.')
    record = session_record(app, runtime)
    if not record or driver.get('app') != str(Path(app).resolve()):
        return fallback
    stamp = driver.get('timestamp')
    value = driver.get('camera_live')
    if not isinstance(stamp, (int, float)) or not 0 <= time.time() - stamp < 3 or not isinstance(value, dict):
        return fallback
    if value.get('session') != fingerprint(record):
        return fallback
    if value.get('state') not in ('live', 'pending', 'saved', 'unsupported'):
        return fallback
    result = dict(value, target_percent=target)
    if result['state'] == 'unsupported' and value.get('target_percent') != target:
        result.update(state='pending', reason='Waiting for confirmation of the saved camera speed.')
    if result['state'] == 'live' and (result.get('percent') != target or
            not isinstance(result.get('updated'), (int, float)) or not 0 <= time.time()-result['updated'] < 2.5):
        result.update(state='pending', reason='Waiting for confirmation of the saved camera speed.')
    return result


class CameraControl:
    def __init__(self, app, runtime):
        self.app, self.runtime = Path(app).resolve(), Path(runtime)
        self.record, self.target, self.clients = None, None, {}
        self.last_refresh = 0.

    def add(self, client):
        self.refresh()
        self.clients[client] = dict(buffer=b'', authenticated=False, pending=None, ack=None, sent=0.)

    def remove(self, client):
        self.clients.pop(client, None)

    def refresh(self):
        record = session_record(self.app, self.runtime)
        if record != self.record:
            self.record = record
            for client in self.clients.values():
                client.update(authenticated=False, pending=None, ack=None)
        config = read_json(self.app / 'spacemouse/camera-gain.json')
        target = config.get('percent') if isinstance(config, dict) else None
        self.target = target if type(target) is int and 1 <= target <= 100 else None

    def receive(self, client, data, now=None):
        entry = self.clients[client]
        entry['buffer'] += data
        if len(entry['buffer']) > 8192:
            return False
        while len(entry['buffer']) >= PACKET.size:
            packet = PACKET.unpack(entry['buffer'][:PACKET.size])
            entry['buffer'] = entry['buffer'][PACKET.size:]
            if packet[0] == HELLO:
                token = struct.pack('<4i', *packet[2:6]).hex()
                if not self.record or packet[1] != VERSION or not secrets.compare_digest(token, self.record['token']) or packet[6] != self.record['basis'] or packet[7] <= 0:
                    return False
                entry.update(authenticated=True, pid=packet[7], pending=None, ack=None, sent=0.)
            elif packet[0] == ACK and entry['authenticated']:
                pending = entry['pending']
                received = time.monotonic() if now is None else now
                if not pending or not 0 <= received-entry['sent'] < .8 or packet[1:6] != pending['packet'][1:6]:
                    continue  # Stale, duplicated or another request's response.
                if packet[6] not in (0, *REASONS) or (packet[6] == 0 and packet[7] != pending['target']) or (packet[6] != 0 and packet[7] != 0):
                    continue
                entry['ack'] = dict(code=packet[6], percent=packet[7], target=pending['target'], updated=time.time(),
                                    monotonic=received)
                entry['pending'] = None
            else:
                return False
        return True

    def tick(self, send, now=None):
        now = time.monotonic() if now is None else now
        if now-self.last_refresh >= .1:
            self.refresh()
            self.last_refresh = now
        if sum(bool(entry['authenticated']) for entry in self.clients.values()) != 1:
            return  # Never apply one logical session to ambiguous processes.
        for client, entry in list(self.clients.items()):
            if not entry['authenticated'] or not self.target:
                continue
            pending = entry['pending']
            if pending and now - entry['sent'] < .8:
                continue
            ack = entry['ack']
            if not pending and ack and ack['target'] == self.target and now-entry['sent'] < .7:
                continue
            nonce = struct.unpack('<4i', secrets.token_bytes(16))
            request = (REQUEST, secrets.randbelow(0x7ffffffe)+1, *nonce, self.target, 1)
            entry['pending'] = dict(packet=request, target=self.target)
            entry['sent'] = now
            send(client, PACKET.pack(*request))

    def status(self, now=None):
        now = time.monotonic() if now is None else now
        result = dict(state='saved', target_percent=self.target,
                      reason='No session-authenticated Fusion SDK is connected.')
        if not self.record:
            result['reason'] = 'Restart Fusion with the updated launcher to enable verified live camera control.'
            return result
        result['session'] = fingerprint(self.record)
        authenticated = [entry for entry in self.clients.values() if entry['authenticated']]
        if len(authenticated) != 1:
            if len(authenticated) > 1:
                result['reason'] = 'Multiple SDK clients claim this session; live status is not attributed.'
            return result
        entry = authenticated[0]
        result['pid'] = entry['pid']
        if not self.target:
            result.update(state='unsupported', reason='This legacy profile has separate camera gains, without a single saved percentage.')
            return result
        ack = entry['ack']
        if not ack or now-ack['monotonic'] >= 2.5:
            result.update(state='pending' if now-entry['sent'] < 1.6 else 'saved',
                          reason='Waiting for a current camera-control confirmation from the SDK.')
        elif ack['target'] != self.target:
            result.update(state='pending', reason='Applying the saved camera speed.')
        elif ack['code']:
            result.update(state='unsupported', reason=REASONS[ack['code']], updated=ack['updated'])
        else:
            result.update(state='live' if ack['percent'] == self.target else 'pending',
                          percent=ack['percent'], updated=ack['updated'],
                          reason='The SDK confirmed the actual camera normalizer.' if ack['percent'] == self.target else 'Applying the saved camera speed.')
        return result

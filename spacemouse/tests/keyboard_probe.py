"""Optional isolated Proton integration test for focus and transport lifecycle.

Same TEST_RUNTIME / TEST_PROTON_RUNNER / TEST_PORT setup as proton_probe.py.
Compile keyboard-probe.cpp beside the private-port probe DLL first.
"""
import os
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time


def main():
    runtime = Path(os.environ['TEST_RUNTIME']).resolve()
    for name in ('phase-keys', 'phase-restart', 'phase-focus', 'phase-final',
                 'child-ready', 'child-stop', 'child-result'):
        (runtime / name).unlink(missing_ok=True)
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', int(os.environ.get('TEST_PORT', '11112'))))
    server.listen(4)
    server.settimeout(30)
    errors = []

    def wait(name):
        until = time.monotonic() + 30
        while not (runtime / name).exists():
            assert time.monotonic() < until, name
            time.sleep(.01)

    def key(client, vk, down, modifiers=0):
        packet = struct.pack('<8i', 3, vk, down, modifiers, 0, 0, 0, 0)
        client.sendall(packet[:7]); client.sendall(packet[7:])
        time.sleep(.025)

    def feed():
        try:
            client, _ = server.accept()
            with client:
                wait('phase-keys')
                key(client, 0x49, 1); key(client, 0x49, 1); key(client, 0x49, 0)
                key(client, 0x41, 1); key(client, 0x49, 1, 1)
                wait('phase-restart')
                key(client, 0x1b, 1)  # Held Escape must release on lost transport.
            client, _ = server.accept()
            with client:
                key(client, 0x24, 1); key(client, 0x24, 0)
                wait('phase-focus')
                key(client, 0x46, 1)
                wait('child-ready')
                key(client, 0x49, 1); key(client, 0x49, 0)
                wait('phase-final')
                key(client, 0x46, 1)
                client.sendall(b'\0' * 7)  # EOF inside a frame must still release.
            server.close()
        except Exception as error:
            errors.append(repr(error))

    worker = threading.Thread(target=feed, daemon=True)
    worker.start()
    try:
        proc = subprocess.run([os.environ['TEST_PROTON_RUNNER'], str(runtime / 'keyboard-probe.exe')],
                              cwd=runtime, capture_output=True, text=True, timeout=60)
        worker.join(2)
        print(proc.stdout, proc.stderr)
        print((runtime / 'keyboard-probe.log').read_text())
        assert proc.returncode == 0, (proc.returncode, errors)
        assert not errors, errors
        assert (runtime / 'child-result').read_text().strip() == '0'
    finally:
        server.close()


if __name__ == '__main__':
    main()

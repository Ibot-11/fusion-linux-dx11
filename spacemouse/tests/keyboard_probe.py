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
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keybindings import button_packet


def main():
    runtime = Path(os.environ['TEST_RUNTIME']).resolve()
    for name in ('phase-keys', 'phase-chords', 'phase-restart', 'phase-focus', 'phase-final',
                 'phase-teardown', 'phase-terminated',
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

    def chord(client, button, down, key_name, modifiers=()):
        packet=button_packet(button,down,{'key':key_name,'modifiers':list(modifiers)})
        client.sendall(packet[:7]);client.sendall(packet[7:])
        time.sleep(.035)

    def feed():
        try:
            client, _ = server.accept()
            with client:
                wait('phase-keys')
                key(client, 0x49, 1); key(client, 0x49, 1); key(client, 0x49, 0)
                key(client, 0x41, 1); key(client, 0x49, 1, 1)
                wait('phase-chords')
                chord(client,0,True,'S',['CTRL']);chord(client,1,True,'Z',['CTRL'])
                chord(client,0,False,'X',['ALT'])  # Release stored S, regardless of rebinding.
                chord(client,1,False,'Z',['CTRL'])
                chord(client,0,True,'F24',['CTRL','SHIFT']);chord(client,1,True,'F24',['CTRL','SHIFT'])
                chord(client,0,True,'Y')  # Duplicate physical down cannot rebind/repeat.
                chord(client,0,False,'F24',['CTRL','SHIFT']);chord(client,1,False,'F24',['CTRL','SHIFT'])
                chord(client,0,True,'CTRL');chord(client,1,True,'SHIFT',['CTRL'])
                chord(client,0,False,'CTRL');chord(client,1,False,'SHIFT',['CTRL'])
                chord(client,0,True,'ENTER');chord(client,1,True,'NUMENTER')
                chord(client,0,False,'ENTER');chord(client,1,False,'NUMENTER')
                for character,mods in [('A',[]),('ä',[]),('?',[]),('@',['ALTGR'])]:
                    chord(client,0,True,character,mods);chord(client,0,False,character,mods)
                # Protocol validation must ignore invalid IDs, encodings,
                # modifier masks, named extended flags and surrogate chars.
                for bad in [(4,2,1,1,65,0,0,0),(4,0,2,1,65,0,0,0),
                            (4,0,1,1,65,32,0,0),(4,0,1,0,0x24,0,0,0),
                            (4,0,1,1,0xd800,0,0,0),(4,0,1,0,0x24,0,1,1)]:
                    client.sendall(struct.pack('<8i',*bad))
                wait('phase-restart')
                chord(client,0,True,'ESC',['CTRL','SHIFT'])
            client, _ = server.accept()
            with client:
                key(client, 0x24, 1); key(client, 0x24, 0)
                wait('phase-focus')
                chord(client,0,True,'F',['CTRL','SHIFT'])
                wait('child-ready')
                chord(client,1,True,'I',['ALTGR']);chord(client,1,False,'I',['ALTGR'])
                wait('phase-final')
                chord(client,0,True,'F',['CTRL','SHIFT'])
                client.sendall(b'\0' * 7)  # EOF inside a frame must still release.
            client, _ = server.accept()
            with client:
                wait('phase-teardown')
                chord(client,0,True,'G',['CTRL','SHIFT'])
                wait('phase-terminated')
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
        log=runtime/'keyboard-probe.log'
        if log.exists():print(log.read_text())
        assert proc.returncode == 0, (proc.returncode, errors)
        assert not errors, errors
        assert (runtime / 'child-result').read_text().strip() == '0'
    finally:
        server.close()


if __name__ == '__main__':
    main()

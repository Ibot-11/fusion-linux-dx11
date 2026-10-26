"""Optional real Proton DLL probe; uses only a private direct TCP test stream.

Compile the probe DLL with -DFUSION_BRIDGE_PORT=11112 (matching TEST_PORT).
Set TEST_RUNTIME and TEST_PROTON_RUNNER explicitly and run this file directly.
Use an isolated display and Wine prefix; no productive Fusion service is stopped.
"""
import os
from pathlib import Path
import socket
import struct
import subprocess
import threading
import time

def main():
    runtime = Path(os.environ["TEST_RUNTIME"]).resolve()
    runner = os.environ["TEST_PROTON_RUNNER"]
    port = int(os.environ.get("TEST_PORT", "11112"))
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(4)
    server.settimeout(30)
    errors = []
    for cycle in range(2):
        (runtime / f"ready-{cycle}").unlink(missing_ok=True)

    def feed():
        try:
            for cycle in range(2):
                client, _ = server.accept()
                with client:
                    deadline = time.monotonic() + 15
                    while not (runtime / f"ready-{cycle}").exists():
                        assert time.monotonic() < deadline, "Windows test did not become ready"
                        time.sleep(.02)
                    time.sleep(.1)
                    packets = [struct.pack("<8i", 0, 11, -22, 33, -44, 55, -66, 17)] * 6
                    packets += [struct.pack("<8i", 0, 0, 0, 0, 0, 0, 0, 17)]
                    packets += [struct.pack("<8i", t, b, 0, 0, 0, 0, 0, 0) for t, b in ((1,0),(2,0),(1,1),(2,1))]
                    for packet in packets:
                        client.sendall(packet[:3]); client.sendall(packet[3:])
                        time.sleep(.035)
                    while client.recv(32):
                        pass
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=feed, daemon=True)
    thread.start()
    try:
        proc = subprocess.run([runner, str(runtime / "sdk-probe.exe")],
                              cwd=runtime, capture_output=True, text=True, timeout=60)
        print(proc.stdout, proc.stderr)
        log = runtime / "sdk-probe.log"
        if log.exists(): print(log.read_text(), flush=True)
        thread.join(timeout=2)
        assert proc.returncode == 0, f"SDK probe failed: {proc.returncode}, feeder: {errors}"
        assert not errors, errors
        print("PASS: real Proton DLL, six signed axes, period, zero, both buttons, peek, double init/terminate and reopen")
    finally:
        server.close()


if __name__ == '__main__':
    main()

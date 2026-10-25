"""Real Windows DLL -> real native relay -> synthetic spacenav stream."""
import os
from pathlib import Path
import selectors
import socket
import struct
import subprocess
import tempfile
import threading
import time

runtime = Path(os.environ["TEST_RUNTIME"]).resolve()
runner = os.environ["TEST_PROTON_RUNNER"]
with socket.socket() as port_check:
    port_check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        port_check.bind(("127.0.0.1", 11111))
    except OSError:
        raise SystemExit("Isolated test requires TCP port 11111 to be free; close Fusion and stop fusion-spacemouse.service first.")
with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp) / "spnav.sock")
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(4)
    server.settimeout(15)
    reader, writer = os.pipe()
    relay = subprocess.Popen([str(runtime / "spconvd"), "--ready-fd", str(writer)],
                             pass_fds=(writer,), env=dict(os.environ, SPNAV_SOCKET=path))
    os.close(writer)
    probe, _ = server.accept()
    probe.close()
    assert os.read(reader, 1) == b"R"
    os.close(reader)
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
                        # Deliberately split packets across writes.
                        client.sendall(packet[:3]); client.sendall(packet[3:])
                        time.sleep(.035)
                    while client.recv(32):
                        pass
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=feed, daemon=True)
    thread.start()
    try:
        proc = subprocess.Popen([runner, str(runtime / "sdk-probe.exe")],
                                cwd=runtime, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        for line in proc.stdout:
            print(line.rstrip(), flush=True)

        result = proc.wait(timeout=10)
        log = runtime / "sdk-probe.log"
        if log.exists(): print(log.read_text(), flush=True)
        thread.join(timeout=2)
        assert result == 0, f"SDK probe failed: {result}, feeder: {errors}"
        assert not errors, errors
        print("PASS: real Proton DLL, six signed axes, period, zero, both buttons, peek, double init/terminate and reopen")
    finally:
        relay.terminate()
        relay.wait(timeout=2)
        server.close()

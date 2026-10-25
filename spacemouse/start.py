#!/usr/bin/env python3
"""Supervise the private driver and relay; systemd owns their session lifetime."""
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "autodesk-fusion-spacemouse"
SOCKET = RUNTIME / "spnav.sock"
CONFIG = ROOT / "settings.conf"
stopping = False


def stop(_signum, _frame):
    global stopping
    stopping = True


def notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), address)


def prepare_config():
    # spnavcfg saves through the driver to THIS persistent file. Preserve it.
    text = CONFIG.read_text() if CONFIG.exists() else "grab = false\nled = false\ndead-zone = 5\n"
    lines = [line for line in text.splitlines() if line.partition("=")[0].strip() != "socket"]
    text = f"socket = {SOCKET}\n" + "\n".join(lines) + "\n"
    if not CONFIG.exists() or CONFIG.read_text() != text:
        fd, name = tempfile.mkstemp(dir=ROOT, prefix=".settings-")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(text)
            os.replace(name, CONFIG)
        finally:
            Path(name).unlink(missing_ok=True)


def main():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    prepare_config()
    SOCKET.unlink(missing_ok=True)
    children = []
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        driver = subprocess.Popen([str(ROOT / "spacenavd"), "-d", "-c", str(CONFIG),
                                   "-p", str(RUNTIME / "driver.pid")])
        children.append(driver)
        deadline = time.monotonic() + 5
        while not SOCKET.is_socket():
            if stopping or driver.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("SpaceMouse-Treiber wurde nicht bereit; siehe Journal.")
            time.sleep(.05)
        reader, writer = os.pipe()
        try:
            env = os.environ.copy()
            env["SPNAV_SOCKET"] = str(SOCKET)
            relay = subprocess.Popen([str(ROOT / "spconvd"), "--ready-fd", str(writer)],
                                     pass_fds=(writer,), env=env)
            children.append(relay)
        finally:
            os.close(writer)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(reader, selectors.EVENT_READ)
                if not selector.select(5) or os.read(reader, 1) != b"R":
                    raise RuntimeError("SpaceMouse-Relay wurde nicht bereit; siehe Journal.")
        finally:
            os.close(reader)
        notify("READY=1\nSTATUS=SpaceMouse-Treiber und Fusion-Relay bereit")
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("Ein SpaceMouse-Hilfsprogramm wurde unerwartet beendet.")
            time.sleep(.25)
        return 0
    except (OSError, RuntimeError) as error:
        print(error, file=sys.stderr, flush=True)
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        SOCKET.unlink(missing_ok=True)
        (RUNTIME / "driver.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

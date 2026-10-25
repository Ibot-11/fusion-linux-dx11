"""Exercise the real native relay with fragmented stream input, EOF and restart."""
import os
from pathlib import Path
import selectors
import socket
import struct
import subprocess
import tempfile
import unittest

RELAY = Path(os.environ["TEST_RELAY"]).resolve()


class RelayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "driver.sock")
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(self.path)
        self.server.listen(4)
        self.server.settimeout(2)
        reader, writer = os.pipe()
        self.proc = subprocess.Popen([str(RELAY), "--ready-fd", str(writer)],
            pass_fds=(writer,), env=dict(os.environ, SPNAV_SOCKET=self.path))
        os.close(writer)
        probe, _ = self.server.accept()
        probe.close()
        with selectors.DefaultSelector() as selector:
            selector.register(reader, selectors.EVENT_READ)
            self.assertTrue(selector.select(2))
            self.assertEqual(os.read(reader, 1), b"R")
        os.close(reader)
        self.sockets = []

    def tearDown(self):
        for sock in self.sockets:
            sock.close()
        self.proc.terminate()
        self.assertEqual(self.proc.wait(timeout=2), 0)
        self.server.close()
        self.tmp.cleanup()

    def connect(self):
        client = socket.create_connection(("127.0.0.1", 11111), 2)
        driver, _ = self.server.accept()
        client.settimeout(2)
        self.sockets.extend((client, driver))
        return client, driver

    def read_exact(self, client, length):
        data = b""
        while len(data) < length:
            chunk = client.recv(length - len(data))
            self.assertTrue(chunk)
            data += chunk
        return data

    def test_fragmented_motion_and_stop_preserve_all_axes_and_period(self):
        client, driver = self.connect()
        frames = struct.pack("<8i", 0, 11, -22, 33, -44, 55, -66, 17)
        frames += struct.pack("<8i", 0, 0, 0, 0, 0, 0, 0, 19)
        for byte in frames:
            driver.sendall(bytes([byte]))
        self.assertEqual(self.read_exact(client, len(frames)), frames)

    def test_burst_keeps_buttons_motion_order_and_zero(self):
        client, driver = self.connect()
        frames = b"".join(struct.pack("<8i", 0, i, 0, 0, 0, 0, 0, 8) for i in range(100))
        frames += b"".join(struct.pack("<8i", t, b, 0, 0, 0, 0, 0, 0) for t, b in ((1, 0), (2, 0), (1, 1), (2, 1)))
        driver.sendall(frames)
        self.assertEqual(self.read_exact(client, len(frames)), frames)

    def test_eof_mid_packet_does_not_emit_garbage(self):
        client, driver = self.connect()
        driver.sendall(b"\0" * 7)
        driver.shutdown(socket.SHUT_WR)
        self.assertEqual(client.recv(32), b"")

    def test_reconnect_after_client_closes(self):
        client, driver = self.connect()
        client.close()
        driver.close()
        client2, driver2 = self.connect()
        packet = struct.pack("<8i", 0, 1, 2, 3, 4, 5, 6, 20)
        driver2.sendall(packet)
        self.assertEqual(self.read_exact(client2, 32), packet)

    def test_occupied_port_never_signals_readiness(self):
        reader, writer = os.pipe()
        other = subprocess.Popen([str(RELAY), "--ready-fd", str(writer)],
            pass_fds=(writer,), env=dict(os.environ, SPNAV_SOCKET=self.path), stderr=subprocess.PIPE)
        os.close(writer)
        _, errors = other.communicate(timeout=2)
        self.assertNotEqual(other.returncode, 0)
        self.assertIn(b"Address already in use", errors)
        self.assertEqual(os.read(reader, 1), b"")
        os.close(reader)


if __name__ == "__main__":
    unittest.main(verbosity=2)

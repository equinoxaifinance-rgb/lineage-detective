from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "cloudflare-fullstack" / "net_bridge.py"


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix sockets are required")
class NetBridgeIntegrationTests(unittest.TestCase):
    def test_tcp_to_unix_to_tcp_bridge_moves_real_bytes_both_directions(self):
        echo_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        echo_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        echo_listener.bind(("127.0.0.1", 0))
        echo_listener.listen(8)
        echo_port = echo_listener.getsockname()[1]
        stop = threading.Event()

        def echo_server() -> None:
            echo_listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    client, _ = echo_listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    if stop.is_set():
                        break
                    raise
                with client:
                    while True:
                        chunk = client.recv(64 * 1024)
                        if not chunk:
                            break
                        client.sendall(chunk)

        echo_thread = threading.Thread(target=echo_server, daemon=True)
        echo_thread.start()

        port_reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port_reservation.bind(("127.0.0.1", 0))
        outer_port = port_reservation.getsockname()[1]
        port_reservation.close()

        unix_path = Path(tempfile.gettempdir()) / (
            f"lineage-bridge-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
        )
        inner = outer = None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            inner = subprocess.Popen(
                [
                    sys.executable,
                    str(BRIDGE),
                    "inner",
                    "--unix-path",
                    str(unix_path),
                    "--target-port",
                    str(echo_port),
                ],
                creationflags=flags,
            )
            deadline = time.monotonic() + 5
            while not unix_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(unix_path.exists(), "inner bridge did not create socket")

            outer = subprocess.Popen(
                [
                    sys.executable,
                    str(BRIDGE),
                    "outer",
                    "--unix-path",
                    str(unix_path),
                    "--listen-port",
                    str(outer_port),
                ],
                creationflags=flags,
            )
            payload = (b"lineage-detective-real-bridge\x00" * 4096) + b"complete"
            deadline = time.monotonic() + 5
            while True:
                try:
                    client = socket.create_connection(
                        ("127.0.0.1", outer_port), timeout=0.5
                    )
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        self.fail("outer bridge did not accept TCP connections")
                    time.sleep(0.05)

            with client:
                client.settimeout(5)
                client.sendall(payload)
                received = bytearray()
                while len(received) < len(payload):
                    chunk = client.recv(64 * 1024)
                    if not chunk:
                        break
                    received.extend(chunk)
            self.assertEqual(bytes(received), payload)
        finally:
            for process in (outer, inner):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            stop.set()
            echo_listener.close()
            echo_thread.join(timeout=1)
            try:
                unix_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()

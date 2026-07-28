"""Bidirectional TCP/Unix bridge for the isolated DataHub namespace."""
from __future__ import annotations

import argparse
import os
import socket
import threading
from collections.abc import Callable


BUFFER_SIZE = 64 * 1024


def _pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while chunk := source.recv(BUFFER_SIZE):
            destination.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(
    client: socket.socket,
    connect_upstream: Callable[[], socket.socket],
) -> None:
    upstream: socket.socket | None = None
    try:
        upstream = connect_upstream()
        left = threading.Thread(target=_pump, args=(client, upstream), daemon=True)
        right = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()
    except OSError:
        pass
    finally:
        client.close()
        if upstream is not None:
            upstream.close()


def _serve(
    listener: socket.socket,
    connect_upstream: Callable[[], socket.socket],
) -> None:
    listener.listen(128)
    while True:
        client, _ = listener.accept()
        threading.Thread(
            target=_handle,
            args=(client, connect_upstream),
            daemon=True,
        ).start()


def serve_inner(unix_path: str, target_host: str, target_port: int) -> None:
    try:
        os.unlink(unix_path)
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(unix_path)
    os.chmod(unix_path, 0o666)

    def connect_upstream() -> socket.socket:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
        upstream.settimeout(None)
        return upstream

    _serve(listener, connect_upstream)


def serve_outer(listen_host: str, listen_port: int, unix_path: str) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((listen_host, listen_port))

    def connect_upstream() -> socket.socket:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(10)
        upstream.connect(unix_path)
        upstream.settimeout(None)
        return upstream

    _serve(listener, connect_upstream)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("inner", "outer"))
    parser.add_argument("--unix-path", required=True)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=8080)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8080)
    args = parser.parse_args()
    if args.mode == "inner":
        serve_inner(args.unix_path, args.target_host, args.target_port)
    else:
        serve_outer(args.listen_host, args.listen_port, args.unix_path)

if __name__ == "__main__":
    main()
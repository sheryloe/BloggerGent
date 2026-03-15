from __future__ import annotations

import argparse
import socket
import threading


BUFFER_SIZE = 65536


def close_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def forward(source: socket.socket, target: socket.socket) -> None:
    try:
        while True:
            data = source.recv(BUFFER_SIZE)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    finally:
        close_socket(source)
        close_socket(target)


def handle_client(client: socket.socket, target_host: str, target_port: int) -> None:
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=5)
    except OSError:
        close_socket(client)
        return

    upstream.settimeout(None)
    client.settimeout(None)

    thread = threading.Thread(target=forward, args=(client, upstream), daemon=True)
    thread.start()
    forward(upstream, client)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose a local browser CDP port to other network clients.")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9223)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=9222)
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.listen_host, args.listen_port))
        server.listen(32)
        while True:
            client, _ = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(client, args.target_host, args.target_port),
                daemon=True,
            )
            thread.start()


if __name__ == "__main__":
    main()

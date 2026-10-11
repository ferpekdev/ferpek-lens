#!/usr/bin/env python3

import json
import os
import socket
from pathlib import Path

SOCKET_PATH = Path(
    os.environ.get(
        "FERPEK_UPDATER_SOCKET",
        "/run/ferpek-lens/updater.sock",
    )
)

INSTALL_DIR = Path(
    os.environ.get(
        "FERPEK_INSTALL_DIR",
        "/opt/ferpek-lens-server",
    )
)

MAX_REQUEST_SIZE = 4096


def read_installed_version() -> str | None:
    env_file = INSTALL_DIR / ".env"

    if not env_file.is_file():
        return None

    try:
        for raw_line in env_file.read_text().splitlines():
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            key, sep, value = line.partition("=")

            if sep and key.strip() == "FERPEK_VERSION":
                value = value.strip()
                return value or None
    except OSError:
        return None

    return None


def make_response(
    *,
    ok: bool,
    result: dict | None = None,
    error: str | None = None,
) -> bytes:
    payload = {
        "ok": ok,
        "result": result,
        "error": error,
    }

    return (json.dumps(payload) + "\n").encode("utf-8")


def handle_request(raw: bytes) -> bytes:
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return make_response(
            ok=False,
            error="Invalid JSON request.",
        )

    if not isinstance(request, dict):
        return make_response(
            ok=False,
            error="Request must be a JSON object.",
        )

    action = request.get("action")

    if action == "status":
        return make_response(
            ok=True,
            result={
                "service": "ferpek-lens-updater",
                "status": "ready",
                "install_dir": str(INSTALL_DIR),
                "installed_version": read_installed_version(),
            },
        )

    return make_response(
        ok=False,
        error="Unsupported action.",
    )


def main() -> None:
    SOCKET_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o755,
    )

    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    with socket.socket(
        socket.AF_UNIX,
        socket.SOCK_STREAM,
    ) as server:
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o660)

        server.listen(8)

        while True:
            connection, _ = server.accept()

            with connection:
                raw = connection.recv(MAX_REQUEST_SIZE)

                if not raw:
                    continue

                response = handle_request(raw)
                connection.sendall(response)


if __name__ == "__main__":
    main()

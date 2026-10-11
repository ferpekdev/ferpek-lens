#!/usr/bin/env python3

import json
import os
import socket
import tempfile
import time
import urllib.error
import urllib.request
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
MAX_RELEASE_FILE_SIZE = 512 * 1024

REPOSITORY_RAW_BASE = os.environ.get(
    "FERPEK_REPOSITORY_RAW_BASE",
    "https://raw.githubusercontent.com/ferpekdev/ferpek-lens",
)


def parse_version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ValueError("Version must be a string.")

    value = value.strip()

    parts = value.split(".")

    if len(parts) != 3:
        raise ValueError(
            "Version must use MAJOR.MINOR.PATCH format."
        )

    if not all(part.isdigit() for part in parts):
        raise ValueError(
            "Version must contain numeric components only."
        )

    return tuple(int(part) for part in parts)


def validate_release(version: str) -> dict:
    parse_version(version)

    url = (
        f"{REPOSITORY_RAW_BASE}/"
        f"v{version}/deploy/compose.yml"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FERPEK-Lens-Updater",
            "Accept": "text/plain",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10,
        ) as response:
            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length is not None:
                try:
                    if int(content_length) > MAX_RELEASE_FILE_SIZE:
                        raise ValueError(
                            "Release deployment file is too large."
                        )
                except ValueError as exc:
                    if str(exc) == "Release deployment file is too large.":
                        raise

            data = response.read(
                MAX_RELEASE_FILE_SIZE + 1
            )

    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(
                f"FERPEK Lens v{version} was not found."
            ) from exc

        raise ValueError(
            f"Could not validate FERPEK Lens v{version}: "
            f"HTTP {exc.code}."
        ) from exc

    except urllib.error.URLError as exc:
        raise ValueError(
            f"Could not reach the FERPEK release repository: "
            f"{exc.reason}"
        ) from exc

    if len(data) > MAX_RELEASE_FILE_SIZE:
        raise ValueError(
            "Release deployment file is too large."
        )

    try:
        compose = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Release deployment file is not valid UTF-8."
        ) from exc

    required_markers = (
        "name: ferpek-lens",
        "ghcr.io/ferpekdev/ferpek-lens-server:",
        "ghcr.io/ferpekdev/ferpek-lens-web:",
    )

    missing = [
        marker
        for marker in required_markers
        if marker not in compose
    ]

    if missing:
        raise ValueError(
            "Release deployment file is not a valid "
            "FERPEK Lens deployment."
        )

    return {
        "version": version,
        "compose_url": url,
        "validated": True,
    }


def prepare_update_staging(version: str) -> dict:
    parse_version(version)

    release = validate_release(version)

    current_env = INSTALL_DIR / ".env"

    if not current_env.is_file():
        raise ValueError(
            "FERPEK .env file was not found."
        )

    staging_root = INSTALL_DIR / ".update-staging"
    staging_root.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )
    staging_root.chmod(0o700)

    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f"v{version}-",
            dir=staging_root,
        )
    )
    staging_dir.chmod(0o700)

    staged_compose = staging_dir / "compose.yml"
    staged_env = staging_dir / ".env"

    request = urllib.request.Request(
        release["compose_url"],
        headers={
            "User-Agent": "FERPEK-Lens-Updater",
            "Accept": "text/plain",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10,
        ) as response:
            compose_data = response.read(
                MAX_RELEASE_FILE_SIZE + 1
            )
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"Could not download FERPEK Lens v{version}: "
            f"HTTP {exc.code}."
        ) from exc
    except urllib.error.URLError as exc:
        raise ValueError(
            "Could not reach the FERPEK release repository: "
            f"{exc.reason}"
        ) from exc

    if len(compose_data) > MAX_RELEASE_FILE_SIZE:
        raise ValueError(
            "Release deployment file is too large."
        )

    try:
        compose_data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "Release deployment file is not valid UTF-8."
        ) from exc

    staged_compose.write_bytes(
        compose_data
    )
    staged_compose.chmod(0o600)

    current_lines = current_env.read_text(
        encoding="utf-8"
    ).splitlines()

    output_lines = []
    version_replaced = False

    for line in current_lines:
        if (
            not version_replaced
            and line.startswith("FERPEK_VERSION=")
        ):
            output_lines.append(
                f"FERPEK_VERSION={version}"
            )
            version_replaced = True
        else:
            output_lines.append(line)

    if not version_replaced:
        output_lines.insert(
            0,
            f"FERPEK_VERSION={version}",
        )

    staged_env.write_text(
        "\n".join(output_lines) + "\n",
        encoding="utf-8",
    )
    staged_env.chmod(0o600)

    return {
        "target_version": version,
        "staging_dir": str(staging_dir),
        "compose_file": str(staged_compose),
        "env_file": str(staged_env),
    }


def prepare_backup() -> dict:
    env_file = INSTALL_DIR / ".env"
    compose_file = INSTALL_DIR / "compose.yml"

    if not env_file.is_file():
        raise ValueError(
            "FERPEK .env file was not found."
        )

    if not compose_file.is_file():
        raise ValueError(
            "FERPEK compose.yml file was not found."
        )

    timestamp = time.strftime(
        "%Y%m%d-%H%M%S",
        time.localtime(),
    )

    backup_root = INSTALL_DIR / "backups"
    backup_root.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )
    backup_root.chmod(0o700)

    backup_dir = backup_root / timestamp

    if backup_dir.exists():
        raise ValueError(
            "Backup directory already exists."
        )

    backup_dir.mkdir(
        parents=True,
        mode=0o700,
    )

    env_backup = backup_dir / ".env"
    compose_backup = backup_dir / "compose.yml"
    metadata_file = backup_dir / "metadata.json"

    env_backup.write_bytes(
        env_file.read_bytes()
    )
    env_backup.chmod(0o600)

    compose_backup.write_bytes(
        compose_file.read_bytes()
    )
    compose_backup.chmod(0o600)

    installed_version = read_installed_version()

    metadata = {
        "created_at": int(time.time()),
        "installed_version": installed_version,
        "install_dir": str(INSTALL_DIR),
        "files": [
            ".env",
            "compose.yml",
        ],
    }

    metadata_file.write_text(
        json.dumps(
            metadata,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    metadata_file.chmod(0o600)

    return {
        "backup_dir": str(backup_dir),
        "installed_version": installed_version,
        "files": [
            ".env",
            "compose.yml",
            "metadata.json",
        ],
    }


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

    if action == "validate_release":
        target_version = request.get("version")

        try:
            parse_version(target_version)

            release = validate_release(
                target_version
            )

        except ValueError as exc:
            return make_response(
                ok=False,
                error=str(exc),
            )

        return make_response(
            ok=True,
            result={
                "service": "ferpek-lens-updater",
                "action": "validate_release",
                **release,
            },
        )

    if action == "plan_update":
        target_version = request.get("version")
        installed_version = read_installed_version()

        try:
            target_parsed = parse_version(
                target_version
            )
        except ValueError as exc:
            return make_response(
                ok=False,
                error=str(exc),
            )

        if installed_version is None:
            return make_response(
                ok=False,
                error="Installed FERPEK version could not be determined.",
            )

        try:
            installed_parsed = parse_version(
                installed_version
            )
        except ValueError:
            return make_response(
                ok=False,
                error="Installed FERPEK version is invalid.",
            )

        if target_parsed == installed_parsed:
            return make_response(
                ok=False,
                error="Target version is already installed.",
            )

        if target_parsed < installed_parsed:
            return make_response(
                ok=False,
                error="Downgrades are not supported by update.",
            )

        try:
            release = validate_release(
                target_version
            )
        except ValueError as exc:
            return make_response(
                ok=False,
                error=str(exc),
            )

        return make_response(
            ok=True,
            result={
                "service": "ferpek-lens-updater",
                "action": "plan_update",
                "current_version": installed_version,
                "target_version": target_version,
                "install_dir": str(INSTALL_DIR),
                "release": release,
                "steps": [
                    "validate_release",
                    "prepare_backup",
                    "enter_maintenance",
                    "pull_images",
                    "apply_deployment",
                    "health_check",
                    "leave_maintenance",
                ],
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

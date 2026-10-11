#!/usr/bin/env python3

import json
import os
import shutil
import sys
import socket
import subprocess
import tempfile
import threading
import time
import uuid
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

UPDATER_SERVICE_FILE = Path(
    os.environ.get(
        "FERPEK_UPDATER_SERVICE_FILE",
        "/etc/systemd/system/ferpek-lens-updater.service",
    )
)

MAX_REQUEST_SIZE = 4096
MAX_RELEASE_FILE_SIZE = 512 * 1024

UPDATE_STATE_FILE = INSTALL_DIR / "update-state.json"
UPDATE_LOCK = threading.Lock()
UPDATE_STATE_LOCK = threading.Lock()

REPOSITORY_RAW_BASE = os.environ.get(
    "FERPEK_REPOSITORY_RAW_BASE",
    "https://raw.githubusercontent.com/ferpekdev/ferpek-lens",
)


class UpdateTransactionError(RuntimeError):
    def __init__(
        self,
        message: str,
        rollback: dict,
    ) -> None:
        self.message = message
        self.rollback = rollback

        super().__init__(
            json.dumps({
                "message": message,
                "rollback": rollback,
            })
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


def fetch_release_compose(
    version: str,
) -> tuple[dict, bytes]:
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
                    size = int(content_length)
                except ValueError:
                    size = None

                if (
                    size is not None
                    and size > MAX_RELEASE_FILE_SIZE
                ):
                    raise ValueError(
                        "Release deployment file is too large."
                    )

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
            "Could not reach the FERPEK release repository: "
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

    metadata = {
        "version": version,
        "compose_url": url,
        "validated": True,
    }

    return metadata, data


def fetch_release_text_file(
    version: str,
    relative_path: str,
    *,
    description: str,
    required_markers: tuple[str, ...],
) -> tuple[dict, bytes]:
    parse_version(version)

    url = (
        f"{REPOSITORY_RAW_BASE}/"
        f"v{version}/{relative_path}"
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
                    size = int(content_length)
                except ValueError:
                    size = None

                if (
                    size is not None
                    and size > MAX_RELEASE_FILE_SIZE
                ):
                    raise ValueError(
                        f"{description} is too large."
                    )

            data = response.read(
                MAX_RELEASE_FILE_SIZE + 1
            )

    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(
                f"{description} was not found "
                f"for FERPEK Lens v{version}."
            ) from exc

        raise ValueError(
            f"Could not fetch {description} "
            f"for FERPEK Lens v{version}: "
            f"HTTP {exc.code}."
        ) from exc

    except urllib.error.URLError as exc:
        raise ValueError(
            "Could not reach the FERPEK release "
            f"repository while fetching {description}: "
            f"{exc.reason}"
        ) from exc

    if len(data) > MAX_RELEASE_FILE_SIZE:
        raise ValueError(
            f"{description} is too large."
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{description} is not valid UTF-8."
        ) from exc

    missing = [
        marker
        for marker in required_markers
        if marker not in text
    ]

    if missing:
        raise ValueError(
            f"{description} is not a valid "
            "FERPEK Lens release artifact."
        )

    metadata = {
        "version": version,
        "url": url,
        "validated": True,
    }

    return metadata, data


def fetch_release_update_helper(
    version: str,
) -> tuple[dict, bytes]:
    metadata, data = fetch_release_text_file(
        version,
        "deploy/updater/update-helper.py",
        description="FERPEK update helper",
        required_markers=(
            "#!/usr/bin/env python3",
            "ferpek-lens-updater",
            "def main()",
        ),
    )

    try:
        source = data.decode("utf-8")
        compile(
            source,
            "update-helper.py",
            "exec",
        )
    except SyntaxError as exc:
        raise ValueError(
            "FERPEK update helper contains invalid "
            "Python syntax."
        ) from exc

    return metadata, data


def fetch_release_updater_service(
    version: str,
) -> tuple[dict, bytes]:
    return fetch_release_text_file(
        version,
        "deploy/updater/ferpek-lens-updater.service",
        description="FERPEK updater service",
        required_markers=(
            "[Unit]",
            "[Service]",
            "ExecStart=/usr/bin/python3",
            "FERPEK_UPDATER_SOCKET=",
        ),
    )


def validate_release(version: str) -> dict:
    compose_metadata, _ = fetch_release_compose(
        version
    )

    helper_metadata, _ = fetch_release_update_helper(
        version
    )

    service_metadata, _ = fetch_release_updater_service(
        version
    )

    return {
        "version": version,
        "compose_url": compose_metadata["compose_url"],
        "compose": compose_metadata,
        "update_helper": helper_metadata,
        "updater_service": service_metadata,
        "validated": True,
    }


def prepare_update_staging(version: str) -> dict:
    parse_version(version)

    _, compose_data = fetch_release_compose(
        version
    )

    _, helper_data = fetch_release_update_helper(
        version
    )

    _, service_data = fetch_release_updater_service(
        version
    )

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
    staged_helper = staging_dir / "update-helper.py"
    staged_service = (
        staging_dir
        / "ferpek-lens-updater.service"
    )

    staged_compose.write_bytes(
        compose_data
    )
    staged_compose.chmod(0o600)

    staged_helper.write_bytes(
        helper_data
    )
    staged_helper.chmod(0o755)

    service_text = service_data.decode(
        "utf-8"
    )

    rendered_service = service_text.replace(
        "/opt/ferpek-lens-server",
        str(INSTALL_DIR),
    )

    staged_service.write_text(
        rendered_service,
        encoding="utf-8",
    )
    staged_service.chmod(0o644)

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
        "update_helper_file": str(staged_helper),
        "updater_service_file": str(staged_service),
    }


def systemd_daemon_reload() -> None:
    try:
        subprocess.run(
            [
                "systemctl",
                "daemon-reload",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=True,
        )

    except FileNotFoundError as exc:
        raise RuntimeError(
            "systemctl was not found."
        ) from exc

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "systemctl daemon-reload timed out."
        ) from exc

    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.strip()
            or exc.stdout.strip()
            or f"exit code {exc.returncode}"
        )

        raise RuntimeError(
            "systemctl daemon-reload failed: "
            f"{detail}"
        ) from exc


def run_compose(
    arguments: tuple[str, ...],
    *,
    timeout: int,
) -> subprocess.CompletedProcess:
    allowed_commands = {
        ("ps",),
        ("pull",),
        ("up", "-d"),
    }

    if arguments not in allowed_commands:
        raise ValueError(
            "Unsupported Docker Compose operation."
        )

    compose_file = INSTALL_DIR / "compose.yml"
    env_file = INSTALL_DIR / ".env"

    if not compose_file.is_file():
        raise ValueError(
            "FERPEK compose.yml file was not found."
        )

    if not env_file.is_file():
        raise ValueError(
            "FERPEK .env file was not found."
        )

    try:
        return subprocess.run(
            [
                "docker",
                "compose",
                *arguments,
            ],
            cwd=INSTALL_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=True,
        )

    except FileNotFoundError as exc:
        raise RuntimeError(
            "Docker CLI was not found."
        ) from exc

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Docker Compose operation timed out."
        ) from exc

    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.strip()
            or exc.stdout.strip()
            or f"exit code {exc.returncode}"
        )

        raise RuntimeError(
            f"Docker Compose operation failed: {detail}"
        ) from exc


def compose_status() -> str:
    result = run_compose(
        ("ps",),
        timeout=30,
    )

    return result.stdout


def compose_pull() -> str:
    result = run_compose(
        ("pull",),
        timeout=600,
    )

    return result.stdout


def compose_up() -> str:
    result = run_compose(
        ("up", "-d"),
        timeout=300,
    )

    return result.stdout


def read_env_value(
    key: str,
) -> str | None:
    env_file = INSTALL_DIR / ".env"

    if not env_file.is_file():
        return None

    for raw_line in env_file.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        current_key, value = line.split(
            "=",
            1,
        )

        if current_key.strip() == key:
            return value.strip()

    return None


def read_configured_port(
    key: str,
    default: int,
) -> int:
    raw = read_env_value(key)

    if raw is None or raw == "":
        return default

    if not raw.isdigit():
        raise ValueError(
            f"{key} must be a numeric port."
        )

    port = int(raw)

    if port < 1 or port > 65535:
        raise ValueError(
            f"{key} must be between 1 and 65535."
        )

    return port


def wait_for_http(
    url: str,
    *,
    timeout: int,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "FERPEK-Lens-Updater",
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=3,
            ) as response:
                if 200 <= response.status < 400:
                    return

                last_error = (
                    f"HTTP {response.status}"
                )

        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = str(exc)

        time.sleep(2)

    raise RuntimeError(
        f"Health check failed for {url}: "
        f"{last_error or 'timeout'}"
    )


def check_ferpek_health(
    *,
    timeout: int = 90,
) -> dict:
    server_port = read_configured_port(
        "FERPEK_PORT",
        8000,
    )

    web_port = read_configured_port(
        "FERPEK_WEB_PORT",
        5173,
    )

    wait_for_http(
        f"http://127.0.0.1:{server_port}/health",
        timeout=timeout,
    )

    wait_for_http(
        f"http://127.0.0.1:{web_port}/",
        timeout=timeout,
    )

    return {
        "server": {
            "port": server_port,
            "status": "healthy",
        },
        "web": {
            "port": web_port,
            "status": "healthy",
        },
    }


def replace_file_atomically(
    source: Path,
    destination: Path,
    *,
    mode: int = 0o600,
) -> None:
    if not source.is_file():
        raise ValueError(
            f"Source file was not found: {source}"
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())

        temp_path.chmod(mode)

        os.replace(
            temp_path,
            destination,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


def cleanup_staging_directory(
    staging_dir: Path,
) -> None:
    staging_root = (
        INSTALL_DIR / ".update-staging"
    ).resolve()

    staging_dir = Path(
        staging_dir
    ).resolve()

    if staging_dir == staging_root:
        raise RuntimeError(
            "Refusing to remove the staging root directory."
        )

    try:
        staging_dir.relative_to(
            staging_root
        )
    except ValueError as exc:
        raise RuntimeError(
            "Staging directory is outside "
            "the FERPEK staging directory."
        ) from exc

    if not staging_dir.exists():
        return

    if not staging_dir.is_dir():
        raise RuntimeError(
            "Staging path is not a directory."
        )

    shutil.rmtree(
        staging_dir
    )

    try:
        staging_root.rmdir()
    except OSError:
        pass


def prune_update_backups(
    *,
    keep: int = 5,
    protected_paths: tuple[Path, ...] = (),
) -> list[str]:
    if keep < 1:
        raise ValueError(
            "Backup retention must keep at least one backup."
        )

    backup_root = (
        INSTALL_DIR / "backups"
    ).resolve()

    if not backup_root.exists():
        return []

    if not backup_root.is_dir():
        raise RuntimeError(
            "FERPEK backup path is not a directory."
        )

    protected = set()

    for protected_path in protected_paths:
        resolved = Path(
            protected_path
        ).resolve()

        try:
            resolved.relative_to(
                backup_root
            )
        except ValueError as exc:
            raise RuntimeError(
                "Protected backup path is outside "
                "the FERPEK backup directory."
            ) from exc

        protected.add(
            resolved
        )

    candidates = []

    for path in backup_root.iterdir():
        if not path.is_dir():
            continue

        try:
            time.strptime(
                path.name,
                "%Y%m%d-%H%M%S",
            )
        except ValueError:
            continue

        candidates.append(
            path
        )

    candidates.sort(
        key=lambda path: path.name,
        reverse=True,
    )

    retained = {
        path.resolve()
        for path in candidates[:keep]
    }

    retained.update(
        protected
    )

    removed = []

    for path in candidates:
        resolved = path.resolve()

        if resolved in retained:
            continue

        shutil.rmtree(
            path
        )

        removed.append(
            str(path)
        )

    return removed


def update_housekeeping(
    state: dict,
) -> None:
    recovery = state.get("recovery")

    if not isinstance(recovery, dict):
        recovery = {}

    status = state.get("status")

    staging_dir_value = recovery.get(
        "staging_dir"
    )

    backup_dir_value = recovery.get(
        "backup_dir"
    )

    recovery_pending = status in {
        "interrupted",
        "recovery_required",
    }

    if (
        not recovery_pending
        and isinstance(staging_dir_value, str)
        and staging_dir_value
    ):
        cleanup_staging_directory(
            Path(staging_dir_value)
        )

    protected_paths = ()

    if (
        recovery_pending
        and isinstance(backup_dir_value, str)
        and backup_dir_value
    ):
        protected_paths = (
            Path(backup_dir_value),
        )

    prune_update_backups(
        keep=5,
        protected_paths=protected_paths,
    )


def run_update_housekeeping(
    state: dict,
) -> None:
    try:
        update_housekeeping(
            state
        )
    except Exception as exc:
        print(
            "FERPEK updater housekeeping warning: "
            f"{exc}",
            file=sys.stderr,
            flush=True,
        )


def apply_staged_deployment(
    staging_dir: Path,
) -> None:
    staging_dir = Path(staging_dir)

    staged_env = staging_dir / ".env"
    staged_compose = staging_dir / "compose.yml"
    staged_helper = staging_dir / "update-helper.py"
    staged_service = (
        staging_dir
        / "ferpek-lens-updater.service"
    )

    replace_file_atomically(
        staged_env,
        INSTALL_DIR / ".env",
        mode=0o600,
    )

    replace_file_atomically(
        staged_compose,
        INSTALL_DIR / "compose.yml",
        mode=0o600,
    )

    replace_file_atomically(
        staged_helper,
        INSTALL_DIR / "update-helper.py",
        mode=0o755,
    )

    replace_file_atomically(
        staged_service,
        UPDATER_SERVICE_FILE,
        mode=0o644,
    )


def restore_deployment_backup(
    backup_dir: Path,
) -> None:
    backup_dir = Path(backup_dir)

    backup_env = backup_dir / ".env"
    backup_compose = backup_dir / "compose.yml"
    backup_helper = backup_dir / "update-helper.py"
    backup_service = (
        backup_dir
        / "ferpek-lens-updater.service"
    )

    replace_file_atomically(
        backup_env,
        INSTALL_DIR / ".env",
        mode=0o600,
    )

    replace_file_atomically(
        backup_compose,
        INSTALL_DIR / "compose.yml",
        mode=0o600,
    )

    replace_file_atomically(
        backup_helper,
        INSTALL_DIR / "update-helper.py",
        mode=0o755,
    )

    replace_file_atomically(
        backup_service,
        UPDATER_SERVICE_FILE,
        mode=0o644,
    )


def prepare_backup() -> dict:
    env_file = INSTALL_DIR / ".env"
    compose_file = INSTALL_DIR / "compose.yml"
    helper_file = INSTALL_DIR / "update-helper.py"
    service_file = UPDATER_SERVICE_FILE

    required_files = (
        (
            env_file,
            "FERPEK .env file was not found.",
        ),
        (
            compose_file,
            "FERPEK compose.yml file was not found.",
        ),
        (
            helper_file,
            "FERPEK update helper was not found.",
        ),
        (
            service_file,
            "FERPEK updater service file was not found.",
        ),
    )

    for path, error in required_files:
        if not path.is_file():
            raise ValueError(error)

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

    backup_files = (
        (
            env_file,
            backup_dir / ".env",
        ),
        (
            compose_file,
            backup_dir / "compose.yml",
        ),
        (
            helper_file,
            backup_dir / "update-helper.py",
        ),
        (
            service_file,
            backup_dir
            / "ferpek-lens-updater.service",
        ),
    )

    for source, destination in backup_files:
        destination.write_bytes(
            source.read_bytes()
        )
        destination.chmod(0o600)

    installed_version = read_installed_version()

    metadata = {
        "created_at": int(time.time()),
        "installed_version": installed_version,
        "install_dir": str(INSTALL_DIR),
        "updater_service_file": str(
            UPDATER_SERVICE_FILE
        ),
        "files": [
            ".env",
            "compose.yml",
            "update-helper.py",
            "ferpek-lens-updater.service",
        ],
    }

    metadata_file = backup_dir / "metadata.json"

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
            "update-helper.py",
            "ferpek-lens-updater.service",
            "metadata.json",
        ],
    }


def perform_update(
    version: str,
) -> dict:
    target_parsed = parse_version(version)

    installed_version = read_installed_version()

    if installed_version is None:
        raise ValueError(
            "Installed FERPEK version could not be determined."
        )

    try:
        installed_parsed = parse_version(
            installed_version
        )
    except ValueError as exc:
        raise ValueError(
            "Installed FERPEK version is invalid."
        ) from exc

    if target_parsed == installed_parsed:
        raise ValueError(
            "Target version is already installed."
        )

    if target_parsed < installed_parsed:
        raise ValueError(
            "Downgrades are not supported by update."
        )

    backup = prepare_backup()

    set_update_recovery_context(
        previous_version=installed_version,
        backup_dir=backup["backup_dir"],
        phase="backup_ready",
    )

    staging = prepare_update_staging(
        version
    )

    set_update_recovery_context(
        previous_version=installed_version,
        backup_dir=backup["backup_dir"],
        phase="backup_ready",
        staging_dir=staging["staging_dir"],
    )

    deployment_mutation_started = False

    try:
        set_update_recovery_context(
            previous_version=installed_version,
            backup_dir=backup["backup_dir"],
            phase="mutation_started",
            staging_dir=staging["staging_dir"],
        )

        deployment_mutation_started = True

        apply_staged_deployment(
            Path(staging["staging_dir"])
        )

        systemd_daemon_reload()

        compose_pull()
        compose_up()

        health = check_ferpek_health()

        actual_version = read_installed_version()

        if actual_version != version:
            raise RuntimeError(
                "Installed version does not match "
                "the requested target version."
            )

        return {
            "service": "ferpek-lens-updater",
            "action": "update",
            "status": "success",
            "previous_version": installed_version,
            "installed_version": actual_version,
            "backup_dir": backup["backup_dir"],
            "health": health,
        }

    except Exception as update_error:
        rollback = {
            "attempted": False,
            "status": "not_required",
            "error": None,
        }

        if deployment_mutation_started:
            rollback["attempted"] = True

            try:
                restore_deployment_backup(
                    Path(backup["backup_dir"])
                )

                systemd_daemon_reload()

                compose_pull()
                compose_up()

                rollback_health = (
                    check_ferpek_health()
                )

                restored_version = (
                    read_installed_version()
                )

                if restored_version != installed_version:
                    raise RuntimeError(
                        "Rollback version verification failed."
                    )

                rollback.update({
                    "status": "success",
                    "restored_version":
                        restored_version,
                    "health": rollback_health,
                })

            except Exception as rollback_error:
                rollback.update({
                    "status": "failed",
                    "error": str(
                        rollback_error
                    ),
                })

        raise UpdateTransactionError(
            str(update_error),
            rollback,
        ) from update_error


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


def write_update_state(
    state: dict,
) -> None:
    UPDATE_STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, temp_name = tempfile.mkstemp(
        prefix=".update-state.",
        suffix=".tmp",
        dir=UPDATE_STATE_FILE.parent,
    )

    temp_path = Path(temp_name)

    try:
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                state,
                handle,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        temp_path.chmod(0o600)

        os.replace(
            temp_path,
            UPDATE_STATE_FILE,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


def read_update_state() -> dict | None:
    with UPDATE_STATE_LOCK:
        if not UPDATE_STATE_FILE.is_file():
            return None

        try:
            state = json.loads(
                UPDATE_STATE_FILE.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return {
                "status": "unknown",
                "error":
                    "Update state could not be read.",
            }

        if not isinstance(state, dict):
            return {
                "status": "unknown",
                "error":
                    "Update state is invalid.",
            }

        return state


def set_update_state(
    state: dict,
) -> None:
    with UPDATE_STATE_LOCK:
        write_update_state(state)


def set_update_recovery_context(
    *,
    previous_version: str,
    backup_dir: str,
    phase: str,
    staging_dir: str | None = None,
) -> None:
    state = read_update_state()

    if state is None:
        raise RuntimeError(
            "Update state is unavailable."
        )

    if state.get("status") != "running":
        raise RuntimeError(
            "Update recovery context can only be "
            "changed while an update is running."
        )

    updated_state = dict(state)
    updated_state["recovery"] = {
        "previous_version": previous_version,
        "backup_dir": backup_dir,
        "phase": phase,
        "staging_dir": staging_dir,
    }

    set_update_state(
        updated_state
    )


def run_update_job(
    operation_id: str,
    version: str,
) -> None:
    started_at = int(time.time())

    set_update_state({
        "operation_id": operation_id,
        "status": "running",
        "target_version": version,
        "started_at": started_at,
        "finished_at": None,
        "result": None,
        "error": None,
    })

    try:
        result = perform_update(
            version
        )

        current_state = read_update_state() or {}

        success_state = {
            "operation_id": operation_id,
            "status": "success",
            "target_version": version,
            "started_at": started_at,
            "finished_at": int(time.time()),
            "result": result,
            "error": None,
        }

        recovery = current_state.get(
            "recovery"
        )

        if recovery is not None:
            success_state["recovery"] = recovery

        set_update_state(
            success_state
        )

        run_update_housekeeping(
            success_state
        )

    except UpdateTransactionError as exc:
        current_state = read_update_state() or {}

        rollback_failed = (
            exc.rollback.get("attempted") is True
            and exc.rollback.get("status") == "failed"
        )

        failed_state = {
            "operation_id": operation_id,
            "status": (
                "recovery_required"
                if rollback_failed
                else "failed"
            ),
            "target_version": version,
            "started_at": started_at,
            "finished_at": int(time.time()),
            "result": {
                "rollback": exc.rollback,
            },
            "error": str(exc),
        }

        recovery = current_state.get(
            "recovery"
        )

        if recovery is not None:
            failed_state["recovery"] = recovery

        set_update_state(
            failed_state
        )

        run_update_housekeeping(
            failed_state
        )

    except Exception as exc:
        current_state = read_update_state() or {}

        failed_state = {
            "operation_id": operation_id,
            "status": "failed",
            "target_version": version,
            "started_at": started_at,
            "finished_at": int(time.time()),
            "result": None,
            "error": str(exc),
        }

        recovery = current_state.get(
            "recovery"
        )

        if recovery is not None:
            failed_state["recovery"] = recovery

        set_update_state(
            failed_state
        )

        run_update_housekeeping(
            failed_state
        )

    finally:
        UPDATE_LOCK.release()


def start_update_job(
    version: str,
) -> dict:
    parse_version(version)

    existing_state = read_update_state()

    if (
        existing_state is not None
        and existing_state.get("status")
        in {
            "interrupted",
            "recovery_required",
        }
    ):
        raise RuntimeError(
            "The previous update requires recovery "
            "before another update can be started."
        )

    if not UPDATE_LOCK.acquire(
        blocking=False
    ):
        raise RuntimeError(
            "An update is already in progress."
        )

    operation_id = uuid.uuid4().hex

    try:
        set_update_state({
            "operation_id": operation_id,
            "status": "starting",
            "target_version": version,
            "started_at": int(time.time()),
            "finished_at": None,
            "result": None,
            "error": None,
        })

        worker = threading.Thread(
            target=run_update_job,
            args=(
                operation_id,
                version,
            ),
            name="ferpek-lens-update",
            daemon=True,
        )

        worker.start()

    except Exception:
        UPDATE_LOCK.release()
        raise

    return {
        "operation_id": operation_id,
        "status": "started",
        "target_version": version,
    }


def recover_update() -> dict:
    state = read_update_state()

    if state is None:
        raise RuntimeError(
            "There is no interrupted update to recover."
        )

    if state.get("status") not in {
        "interrupted",
        "recovery_required",
    }:
        raise RuntimeError(
            "The current update state does not require recovery."
        )

    recovery = state.get("recovery")

    recovery_action = "stabilize"

    if recovery is not None:
        if not isinstance(recovery, dict):
            raise RuntimeError(
                "Interrupted update recovery context is invalid."
            )

        previous_version = recovery.get(
            "previous_version"
        )
        backup_dir_value = recovery.get(
            "backup_dir"
        )
        phase = recovery.get(
            "phase"
        )

        if phase not in {
            "backup_ready",
            "mutation_started",
        }:
            raise RuntimeError(
                "Interrupted update recovery phase is invalid."
            )

        if not isinstance(previous_version, str):
            raise RuntimeError(
                "Interrupted update previous version is invalid."
            )

        try:
            parse_version(
                previous_version
            )
        except ValueError as exc:
            raise RuntimeError(
                "Interrupted update previous version is invalid."
            ) from exc

        if not isinstance(backup_dir_value, str):
            raise RuntimeError(
                "Interrupted update backup path is invalid."
            )

        backup_root = (
            INSTALL_DIR / "backups"
        ).resolve()

        backup_dir = Path(
            backup_dir_value
        ).resolve()

        try:
            backup_dir.relative_to(
                backup_root
            )
        except ValueError as exc:
            raise RuntimeError(
                "Interrupted update backup path is outside "
                "the FERPEK backup directory."
            ) from exc

        if not backup_dir.is_dir():
            raise RuntimeError(
                "Interrupted update backup directory "
                "was not found."
            )

        if phase == "mutation_started":
            restore_deployment_backup(
                backup_dir
            )

            systemd_daemon_reload()

            recovery_action = "rollback"

    compose_pull()
    compose_up()

    health = check_ferpek_health()

    installed_version = read_installed_version()

    if installed_version is None:
        raise RuntimeError(
            "Installed FERPEK version could not be determined."
        )

    try:
        parse_version(
            installed_version
        )
    except ValueError as exc:
        raise RuntimeError(
            "Installed FERPEK version is invalid."
        ) from exc

    if (
        recovery is not None
        and recovery.get("phase") == "mutation_started"
        and installed_version
        != recovery["previous_version"]
    ):
        raise RuntimeError(
            "Interrupted update rollback version "
            "verification failed."
        )

    recovered_state = dict(state)

    recovered_state.update({
        "status": "recovered",
        "finished_at": int(time.time()),
        "result": {
            "installed_version":
                installed_version,
            "recovery_action":
                recovery_action,
            "health": health,
        },
        "error": None,
    })

    set_update_state(
        recovered_state
    )

    run_update_housekeeping(
        recovered_state
    )

    return {
        "service": "ferpek-lens-updater",
        "action": "recover_update",
        "status": "recovered",
        "installed_version": installed_version,
        "recovery_action": recovery_action,
        "health": health,
    }


def recover_interrupted_update_state() -> None:
    state = read_update_state()

    if state is None:
        return

    if state.get("status") not in {
        "starting",
        "running",
    }:
        return

    recovered_state = dict(state)

    recovered_state.update({
        "status": "interrupted",
        "finished_at": int(time.time()),
        "error": (
            "The update helper restarted while an update "
            "was in progress. The update state is uncertain "
            "and automatic continuation was not attempted."
        ),
    })

    set_update_state(
        recovered_state
    )


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

    if action == "start_update":
        target_version = request.get("version")

        try:
            job = start_update_job(
                target_version
            )
        except (
            ValueError,
            RuntimeError,
        ) as exc:
            return make_response(
                ok=False,
                error=str(exc),
            )

        return make_response(
            ok=True,
            result={
                "service": "ferpek-lens-updater",
                "action": "start_update",
                **job,
            },
        )

    if action == "update_status":
        state = read_update_state()

        if state is None:
            state = {
                "status": "idle",
                "operation_id": None,
                "target_version": None,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }

        return make_response(
            ok=True,
            result={
                "service": "ferpek-lens-updater",
                "action": "update_status",
                **state,
            },
        )

    if action == "recover_update":
        try:
            result = recover_update()
        except RuntimeError as exc:
            return make_response(
                ok=False,
                error=str(exc),
            )

        return make_response(
            ok=True,
            result=result,
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
                    "prepare_staging",
                    "apply_deployment",
                    "reload_systemd",
                    "pull_images",
                    "start_services",
                    "health_check",
                    "verify_version",
                ],
            },
        )

    return make_response(
        ok=False,
        error="Unsupported action.",
    )


def main() -> None:
    recover_interrupted_update_state()

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

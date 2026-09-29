#!/usr/bin/env python3

import json
import re
import os
import platform
import queue

try:
    from ferpek_lens.pack_engine import PackEngine
except ModuleNotFoundError:
    from rosetta_lens.pack_engine import PackEngine
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.5.0"

SERVER_URL = os.environ.get(
    "FERPEK_SERVER",
    os.environ.get("ROSETTA_SERVER", ""),
).rstrip("/")

TOKEN = os.environ.get(
    "FERPEK_ENROLL_TOKEN",
    os.environ.get("ROSETTA_ENROLL_TOKEN", ""),
)

CONFIG_DIR = (
    Path("/etc/ferpek")
    if Path("/etc/ferpek").exists()
    else Path("/etc/rosetta")
)

STATE_DIR = (
    Path("/var/lib/ferpek")
    if Path("/var/lib/ferpek").exists()
    else Path("/var/lib/rosetta")
)

CREDENTIALS_FILE = CONFIG_DIR / "agent.json"
ENVIRONMENT_FILE = CONFIG_DIR / "environment"
FILE_OFFSETS_FILE = STATE_DIR / "file_offsets.json"
PACK_STATE_FILE = STATE_DIR / "pack_state.json"
PACKS_DIR = STATE_DIR / "packs"

CONFIG_REFRESH_INTERVAL = 10
FILE_POLL_INTERVAL = 1
MAX_FILE_LINES_PER_CYCLE = 200
SEND_INTERVAL = 2
PACK_STATE_FLUSH_INTERVAL = 2
MAX_BATCH_SIZE = 100

EVENT_QUEUE = queue.Queue(maxsize=5000)

SOURCE_FAMILIES = {
    "authentication": "authentication",
    "auth-file": "authentication",

    "journal-system": "system",
    "syslog-file": "system",

    "kernel": "kernel",
    "cron": "cron",
    "service-errors": "service-errors",

    "mail-file": "mail",

    "apache-access": "web-access",
    "nginx-access": "web-access",

    "apache-error": "web-error",
    "nginx-error": "web-error",

    "fail2ban": "security",
}


def source_family(source_key):
    return SOURCE_FAMILIES.get(
        source_key,
        source_key,
    )


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

        super().__init__(
            f"API returned HTTP {status_code}: {detail}"
        )


FERPEK_LOG_MARKER = "[ferpek-agent]"


def log(message: str):
    print(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{FERPEK_LOG_MARKER} {message}",
        flush=True,
    )


def api_request(
    method: str,
    path: str,
    data=None,
    agent_key: str | None = None,
):
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"FERPEK-Agent/{VERSION}",
    }

    if agent_key:
        headers["Authorization"] = f"Bearer {agent_key}"

    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        SERVER_URL + path,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read()

            if not content:
                return {}

            return json.loads(content.decode("utf-8"))

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise ApiError(exc.code, detail) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach FERPEK Server: {exc.reason}"
        ) from exc


def pack_directories_equal(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False

    left_files = {
        path.relative_to(left)
        for path in left.rglob("*")
        if path.is_file()
    }

    right_files = {
        path.relative_to(right)
        for path in right.rglob("*")
        if path.is_file()
    }

    if left_files != right_files:
        return False

    for relative_path in left_files:
        try:
            if (
                (left / relative_path).read_bytes()
                != (right / relative_path).read_bytes()
            ):
                return False
        except OSError:
            return False

    return True


def sync_packs(agent_key):
    response = api_request(
        "GET",
        "/api/v1/agent/packs",
        agent_key=agent_key,
    )

    packs = response.get(
        "packs",
        [],
    )

    PACKS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    received_ids = set()
    changed = False

    for pack in packs:
        pack_id = pack.get("id")
        version = str(
            pack.get(
                "version",
                "",
            )
        )
        files = pack.get(
            "files",
            {},
        )

        if not pack_id:
            continue

        received_ids.add(pack_id)

        pack_dir = PACKS_DIR / pack_id

        temporary_dir = PACKS_DIR / (
            f".{pack_id}.tmp"
        )

        if temporary_dir.exists():
            import shutil
            shutil.rmtree(temporary_dir)

        temporary_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        for relative_name, content in files.items():
            relative_path = Path(relative_name)

            if relative_path.is_absolute():
                raise RuntimeError(
                    f"Invalid pack path: {relative_name}"
                )

            if ".." in relative_path.parts:
                raise RuntimeError(
                    f"Invalid pack path: {relative_name}"
                )

            destination = (
                temporary_dir
                / relative_path
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_text(
                content,
                encoding="utf-8",
            )

        version_file = (
            temporary_dir
            / ".ferpek-version"
        )

        version_file.write_text(
            version,
            encoding="utf-8",
        )

        if (
            pack_dir.exists()
            and pack_directories_equal(
                temporary_dir,
                pack_dir,
            )
        ):
            import shutil
            shutil.rmtree(temporary_dir)
        else:
            if pack_dir.exists():
                import shutil
                shutil.rmtree(pack_dir)

            temporary_dir.replace(
                pack_dir
            )

            changed = True

            log(
                f"Pack synchronized: "
                f"{pack_id} {version}"
            )

    # Remove packs no longer published by server.
    for local_pack in PACKS_DIR.iterdir():
        if not local_pack.is_dir():
            continue

        if local_pack.name.startswith("."):
            continue

        if local_pack.name not in received_ids:
            import shutil

            shutil.rmtree(
                local_pack
            )

            changed = True

            log(
                f"Pack removed: "
                f"{local_pack.name}"
            )

    return len(received_ids), changed


def get_os_info():
    data = {}

    try:
        with open("/etc/os-release", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                data[key] = value.strip('"')

    except OSError:
        pass

    return {
        "os_name": data.get(
            "PRETTY_NAME",
            platform.system(),
        ),
        "os_version": data.get(
            "VERSION_ID",
            "",
        ),
    }


def detect_machine_type():
    try:
        result = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        virtualization = result.stdout.strip()

        if (
            result.returncode == 0
            and virtualization not in ("", "none")
        ):
            return f"virtual:{virtualization}"

    except (OSError, subprocess.SubprocessError):
        pass

    return "physical-or-unknown"


def clear_enrollment_token():
    global TOKEN

    TOKEN = ""

    if ENVIRONMENT_FILE.exists():
        ENVIRONMENT_FILE.write_text(
            f"FERPEK_SERVER={SERVER_URL}\n",
            encoding="utf-8",
        )

        os.chmod(
            ENVIRONMENT_FILE,
            0o600,
        )


def remove_credentials():
    try:
        CREDENTIALS_FILE.unlink()
    except FileNotFoundError:
        pass


def enroll():
    if not SERVER_URL:
        raise RuntimeError(
            "FERPEK_SERVER is not configured"
        )

    if not TOKEN:
        raise RuntimeError(
            "FERPEK_ENROLL_TOKEN is not configured"
        )

    hostname = socket.getfqdn() or socket.gethostname()
    os_info = get_os_info()

    log(f"Enrolling host {hostname}...")

    response = api_request(
        "POST",
        "/api/v1/enroll",
        {
            "hostname": hostname,
            "token": TOKEN,
            "os_name": os_info["os_name"],
            "os_version": os_info["os_version"],
            "agent_version": VERSION,
        },
    )

    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    credentials = {
        "server": SERVER_URL,
        "agent_id": response["agent_id"],
        "agent_key": response["agent_key"],
    }

    CREDENTIALS_FILE.write_text(
        json.dumps(
            credentials,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.chmod(
        CREDENTIALS_FILE,
        0o600,
    )

    log(
        f"Enrollment successful. "
        f"Agent ID: {response['agent_id']}"
    )

    clear_enrollment_token()

    return credentials


def load_credentials():
    global SERVER_URL

    if not CREDENTIALS_FILE.exists():
        return None

    credentials = json.loads(
        CREDENTIALS_FILE.read_text(
            encoding="utf-8"
        )
    )

    SERVER_URL = credentials["server"].rstrip("/")

    return credentials


def update_metadata(agent_key: str):
    os_info = get_os_info()

    api_request(
        "POST",
        "/api/v1/agent/metadata",
        {
            "os_name": os_info["os_name"],
            "os_version": os_info["os_version"],
            "agent_version": VERSION,
            "machine_type": detect_machine_type(),
        },
        agent_key,
    )


def discover_sources(agent_key: str):
    sources = [
        {
            "source_key": "authentication",
            "name": "Authentication",
            "source_type": "journal",
            "enabled": True,
            "send_events": True,
            "discovered": False,
        },
        {
            "source_key": "kernel",
            "name": "Kernel",
            "source_type": "journal",
            "enabled": True,
            "send_events": True,
            "discovered": False,
        },
        {
            "source_key": "cron",
            "name": "Cron",
            "source_type": "journal",
            "enabled": True,
            "send_events": True,
            "discovered": False,
        },
        {
            "source_key": "service-errors",
            "name": "Service errors",
            "source_type": "journal",
            "enabled": True,
            "send_events": True,
            "discovered": False,
        },
        {
            "source_key": "journal-system",
            "name": "System journal",
            "source_type": "journal",
            "enabled": False,
            "send_events": False,
            "discovered": False,
        },
    ]

    known_files = [
        (
            "fail2ban",
            "Fail2ban",
            "/var/log/fail2ban.log",
        ),
        (
            "auth-file",
            "Authentication log",
            "/var/log/auth.log",
        ),
        (
            "syslog-file",
            "Syslog",
            "/var/log/syslog",
        ),
        (
            "mail-file",
            "Mail log",
            "/var/log/mail.log",
        ),
        (
            "nginx-access",
            "nginx access log",
            "/var/log/nginx/access.log",
        ),
        (
            "nginx-error",
            "nginx error log",
            "/var/log/nginx/error.log",
        ),
        (
            "apache-access",
            "Apache access log",
            "/var/log/apache2/access.log",
        ),
        (
            "apache-error",
            "Apache error log",
            "/var/log/apache2/error.log",
        ),
    ]

    for source_key, name, path in known_files:
        if Path(path).is_file():
            sources.append(
                {
                    "source_key": source_key,
                    "name": name,
                    "source_type": "file",
                    "path": path,
                    "enabled": False,
                    "send_events": False,
                    "discovered": True,
                }
            )

    response = api_request(
        "POST",
        "/api/v1/sources/discover",
        {
            "sources": sources,
        },
        agent_key,
    )

    log(
        f"Reported {response['received']} log sources"
    )


def get_config(agent_key: str):
    return api_request(
        "GET",
        "/api/v1/agent/config",
        agent_key=agent_key,
    )


def priority_to_severity(priority):
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return "info"

    if priority <= 2:
        return "critical"

    if priority <= 4:
        return "warning"

    return "info"


def classify_journal_event(entry):
    comm = str(entry.get("_COMM", "")).lower()
    identifier = str(
        entry.get("SYSLOG_IDENTIFIER", "")
    ).lower()

    unit = str(
        entry.get("_SYSTEMD_UNIT", "")
    ).lower()

    transport = str(
        entry.get("_TRANSPORT", "")
    ).lower()

    message = str(
        entry.get("MESSAGE", "")
    )

    message_lower = message.lower()

    auth_programs = {
        "sshd",
        "sshd-session",
        "sudo",
        "su",
        "login",
        "systemd-logind",
        "polkitd",
    }

    cron_programs = {
        "cron",
        "crond",
        "anacron",
    }

    if (
        comm in auth_programs
        or identifier in auth_programs
    ):
        return "authentication"

    if transport == "kernel":
        return "kernel"

    if (
        comm in cron_programs
        or identifier in cron_programs
        or unit.startswith("cron.")
    ):
        return "cron"

    priority = entry.get("PRIORITY")

    try:
        priority_number = int(priority)
    except (TypeError, ValueError):
        priority_number = 7

    service_error_terms = (
        "failed to start",
        "failed with result",
        "dependency failed",
        "entered failed state",
        "start request repeated too quickly",
        "main process exited",
    )

    if (
        priority_number <= 3
        or any(
            term in message_lower
            for term in service_error_terms
        )
    ):
        return "service-errors"

    return "journal-system"


def journal_timestamp(entry):
    realtime = entry.get("__REALTIME_TIMESTAMP")

    if realtime:
        try:
            return int(int(realtime) / 1_000_000)
        except (TypeError, ValueError):
            pass

    return int(time.time())


def normalize_journal_event(entry):
    message = str(
        entry.get("MESSAGE", "")
    ).strip()

    if not message:
        return None

    source_key = classify_journal_event(entry)

    service = (
        entry.get("SYSLOG_IDENTIFIER")
        or entry.get("_COMM")
        or entry.get("_SYSTEMD_UNIT")
        or ""
    )

    metadata = {
        "pid": entry.get("_PID"),
        "uid": entry.get("_UID"),
        "unit": entry.get("_SYSTEMD_UNIT"),
        "comm": entry.get("_COMM"),
        "identifier": entry.get("SYSLOG_IDENTIFIER"),
        "transport": entry.get("_TRANSPORT"),
        "priority": entry.get("PRIORITY"),
    }

    metadata = {
        key: value
        for key, value in metadata.items()
        if value not in (None, "")
    }

    return {
        "source_key": source_key,
        "timestamp": journal_timestamp(entry),
        "service": str(service),
        "severity": priority_to_severity(
            entry.get("PRIORITY")
        ),
        "message": message,
        "metadata": json.dumps(
            metadata,
            separators=(",", ":"),
        ),
    }


def load_file_offsets():
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not FILE_OFFSETS_FILE.exists():
        return {}

    try:
        data = json.loads(
            FILE_OFFSETS_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

    except (OSError, json.JSONDecodeError):
        pass

    return {}


def save_file_offsets(states):
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = FILE_OFFSETS_FILE.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            states,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary.replace(FILE_OFFSETS_FILE)


def initialize_file_offset(
    source,
    states,
    start_at_end=True,
):
    path = Path(source["path"])

    try:
        stat = path.stat()
    except OSError:
        return False

    offset = stat.st_size if start_at_end else 0

    states[source["source_key"]] = {
        "path": str(path),
        "inode": stat.st_ino,
        "offset": offset,
    }

    save_file_offsets(states)

    if start_at_end:
        log(
            f"File source enabled: {source['name']} "
            f"({path}) - starting at current end"
        )

    return True


def file_event_severity(message):
    value = message.lower()

    critical_terms = (
        "panic",
        "fatal",
        "out of memory",
        "oom-kill",
    )

    warning_terms = (
        "error",
        "failed",
        "failure",
        "denied",
        "warning",
    )

    if any(term in value for term in critical_terms):
        return "critical"

    if any(term in value for term in warning_terms):
        return "warning"

    return "info"


def normalize_file_event(source, line):
    message = line.decode(
        "utf-8",
        errors="replace",
    ).rstrip("\r\n")

    if not message:
        return None

    if FERPEK_LOG_MARKER in message:
        return None

    return {
        "source_key": source["source_key"],
        "source_family": source_family(source["source_key"]),
        "timestamp": int(time.time()),
        "service": source["source_key"],
        "severity": file_event_severity(message),
        "message": message,
        "metadata": json.dumps(
            {
                "path": source["path"],
                "collector": "file",
            },
            separators=(",", ":"),
        ),
    }


def poll_file_sources(
    enabled_sources,
    states,
):
    changed = False

    for source in enabled_sources.values():
        if source.get("source_type") != "file":
            continue

        path_value = source.get("path")

        if not path_value:
            continue

        path = Path(path_value)
        source_key = source["source_key"]

        try:
            stat = path.stat()
        except OSError:
            continue

        state = states.get(source_key)

        if state is None:
            initialize_file_offset(
                source,
                states,
                start_at_end=True,
            )
            continue

        # logrotate: same configured path now points at a new inode.
        if state.get("inode") != stat.st_ino:
            log(
                f"Log rotation detected for {source['name']} "
                f"({path})"
            )

            state = {
                "path": str(path),
                "inode": stat.st_ino,
                "offset": 0,
            }

            states[source_key] = state
            changed = True

        offset = int(
            state.get(
                "offset",
                0,
            )
        )

        # File was truncated in place.
        if stat.st_size < offset:
            log(
                f"Log truncation detected for {source['name']} "
                f"({path})"
            )

            offset = 0
            state["offset"] = 0
            changed = True

        if stat.st_size == offset:
            continue

        try:
            with path.open("rb") as file:
                file.seek(offset)

                lines_read = 0

                while lines_read < MAX_FILE_LINES_PER_CYCLE:
                    line = file.readline()

                    if not line:
                        break

                    event = normalize_file_event(
                        source,
                        line,
                    )

                    if event is not None:
                        try:
                            EVENT_QUEUE.put(
                                event,
                                timeout=1,
                            )
                        except queue.Full:
                            log(
                                "Event queue full; "
                                "dropping file event"
                            )

                    lines_read += 1

                state["offset"] = file.tell()
                state["inode"] = stat.st_ino
                state["path"] = str(path)

                changed = True

        except OSError as exc:
            log(
                f"Could not read {path}: {exc}"
            )

    if changed:
        save_file_offsets(states)


def journal_collector(stop_event):
    log("Starting journald collector")

    command = [
        "journalctl",
        "--follow",
        "--lines=0",
        "--output=json",
        "--no-pager",
    ]

    while not stop_event.is_set():
        process = None

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            if process.stdout is None:
                raise RuntimeError(
                    "journalctl stdout is unavailable"
                )

            for line in process.stdout:
                if stop_event.is_set():
                    break

                line = line.strip()

                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                unit = str(
                    entry.get("_SYSTEMD_UNIT", "")
                ).lower()

                if unit in {
                    "ferpek-agent.service",
                    "rosetta-agent.service",
                }:
                    continue

                message = str(
                    entry.get("MESSAGE", "")
                )

                if FERPEK_LOG_MARKER in message:
                    continue

                event = normalize_journal_event(entry)

                if event is None:
                    continue

                event["source_family"] = source_family(
                    event["source_key"]
                )

                try:
                    EVENT_QUEUE.put(
                        event,
                        timeout=1,
                    )
                except queue.Full:
                    log(
                        "Event queue full; dropping journal event"
                    )

        except Exception as exc:
            if not stop_event.is_set():
                log(
                    f"Journald collector error: {exc}"
                )

                time.sleep(5)

        finally:
            if process is not None:
                try:
                    process.terminate()
                except OSError:
                    pass


DEDUPE_WINDOW_SECONDS = 3.0


def canonical_event_message(message):
    value = str(message).strip()

    # RFC3339 / rsyslog-style file log:
    # 2026-09-27T13:00:00+01:00 host sshd[123]: message
    value = re.sub(
        r'^'
        r'\d{4}-\d{2}-\d{2}T\S+\s+'
        r'\S+\s+'
        r'[^:\s]+(?:\[\d+\])?:\s*',
        '',
        value,
    )

    # Traditional syslog:
    # Sep 27 13:00:00 host sshd[123]: message
    value = re.sub(
        r'^'
        r'[A-Z][a-z]{2}\s+'
        r'\d{1,2}\s+'
        r'\d{2}:\d{2}:\d{2}\s+'
        r'\S+\s+'
        r'[^:\s]+(?:\[\d+\])?:\s*',
        '',
        value,
    )

    return value


def is_cross_source_duplicate(event, cache):
    family = event.get(
        "source_family",
        event.get("source_key", ""),
    )

    source_key = event.get("source_key", "")

    canonical = canonical_event_message(
        event.get("message", "")
    )

    if not family or not source_key or not canonical:
        return False

    now = time.monotonic()

    key = (
        family,
        canonical,
    )

    seen_sources = cache.setdefault(
        key,
        {},
    )

    expired = [
        source
        for source, seen_at in seen_sources.items()
        if now - seen_at > DEDUPE_WINDOW_SECONDS
    ]

    for source in expired:
        seen_sources.pop(source, None)

    duplicate = any(
        source != source_key
        for source in seen_sources
    )

    seen_sources[source_key] = now

    # Prevent stale fingerprints from growing forever.
    if len(cache) > 5000:
        stale_keys = []

        for cache_key, sources in cache.items():
            if not any(
                now - seen_at <= DEDUPE_WINDOW_SECONDS
                for seen_at in sources.values()
            ):
                stale_keys.append(cache_key)

        for cache_key in stale_keys:
            cache.pop(cache_key, None)

    return duplicate


def enabled_sources_from_config(config):
    return {
        source["source_key"]: source
        for source in config["sources"]
        if source["enabled"]
    }


def send_relevant(
    agent_key,
    event,
    relevant_events,
):
    if not relevant_events:
        return

    payload = []

    for relevant in relevant_events:
        payload.append(
            {
                "source_key": event.get(
                    "source_key",
                    "",
                ),
                "timestamp": int(
                    event.get(
                        "timestamp",
                        time.time(),
                    )
                ),
                "pack_id": relevant.get(
                    "pack",
                    "",
                ),
                "rule_id": relevant.get(
                    "rule_id",
                    "",
                ),
                "service": relevant.get(
                    "service",
                    "",
                ),
                "severity": relevant.get(
                    "severity",
                    "info",
                ),
                "title": relevant.get(
                    "title",
                    "",
                ),
                "detail": relevant.get(
                    "detail",
                    "",
                ),
                "fields": relevant.get(
                    "fields",
                    {},
                ),
                "source_message": event.get(
                    "message",
                    "",
                ),
            }
        )

    response = api_request(
        "POST",
        "/api/v1/relevant",
        {
            "events": payload,
        },
        agent_key,
    )

    log(
        f"Relevant events sent: "
        f"{response.get('stored', len(payload))}"
    )


def send_findings(agent_key, findings):
    if not findings:
        return

    response = api_request(
        "POST",
        "/api/v1/findings",
        {
            "findings": findings,
        },
        agent_key,
    )

    log(
        f"Findings sent: {response.get('received', len(findings))}"
    )


def send_event_batch(agent_key, events):
    if not events:
        return

    response = api_request(
        "POST",
        "/api/v1/events",
        {
            "events": events,
        },
        agent_key,
    )

    log(
        f"Events sent: {response.get('stored', 0)} "
        f"stored / {response.get('received', len(events))} received"
    )


def main():
    log(
        f"FERPEK Agent {VERSION} starting"
    )

    credentials = load_credentials()
    config = None

    if credentials is None:
        credentials = enroll()

    else:
        agent_key = credentials["agent_key"]

        try:
            config = get_config(agent_key)

        except ApiError as exc:
            if exc.status_code != 401:
                raise

            log(
                "Stored agent credentials were rejected "
                "by the server."
            )

            if not TOKEN:
                raise RuntimeError(
                    "Agent credentials have been revoked. "
                    "Use Add Host in the FERPEK WebUI and "
                    "run the new installation command."
                )

            log(
                "New enrollment token detected. "
                "Re-enrolling host..."
            )

            remove_credentials()
            credentials = enroll()

    agent_key = credentials["agent_key"]

    update_metadata(agent_key)
    discover_sources(agent_key)

    config = get_config(agent_key)

    log(
        f"Connected to FERPEK Server: {SERVER_URL}"
    )

    log(
        f"Host: {config['hostname']}"
    )

    enabled_sources = enabled_sources_from_config(
        config
    )

    try:
        pack_count, _ = sync_packs(
            agent_key
        )

        log(
            f"FERPEK Lens synchronized "
            f"{pack_count} pack(s)"
        )

    except Exception as exc:
        log(
            f"Could not synchronize packs: {exc}"
        )

    pack_engine = PackEngine(
        PACKS_DIR,
        PACK_STATE_FILE,
    )
    pack_engine.load()
    pack_engine.load_state()

    loaded_rules = pack_engine.describe()

    log(
        f"FERPEK Lens loaded {len(loaded_rules)} rule(s)"
    )

    for rule in loaded_rules:
        log(
            f"Pack rule: {rule['pack']} / {rule['id']}"
        )

    log(
        "Enabled sources: "
        + ", ".join(
            sorted(enabled_sources.keys())
        )
    )

    file_offsets = load_file_offsets()

    # Sources that are already enabled when the process starts keep
    # their persisted offsets. Sources enabled later start at EOF.
    active_file_sources = {
        source_key
        for source_key, source in enabled_sources.items()
        if source.get("source_type") == "file"
    }

    stop_event = threading.Event()

    journal_thread = threading.Thread(
        target=journal_collector,
        args=(stop_event,),
        daemon=True,
        name="journald-collector",
    )

    journal_thread.start()

    last_config_refresh = 0
    last_send = time.time()
    last_pack_state_flush = time.monotonic()
    pending_events = []

    # Short-lived fingerprints used only to prevent equivalent
    # sources from counting the same event twice in PackEngine.
    pack_dedupe_cache = {}

    try:
        while True:
            now = time.time()

            if (
                now - last_config_refresh
                >= CONFIG_REFRESH_INTERVAL
            ):
                try:
                    config = get_config(agent_key)

                    new_enabled_sources = (
                        enabled_sources_from_config(config)
                    )

                    current_file_sources = {
                        source_key
                        for source_key, source
                        in new_enabled_sources.items()
                        if source.get("source_type") == "file"
                    }

                    newly_enabled_files = (
                        current_file_sources
                        - active_file_sources
                    )

                    for source_key in newly_enabled_files:
                        initialize_file_offset(
                            new_enabled_sources[source_key],
                            file_offsets,
                            start_at_end=True,
                        )

                    active_file_sources = current_file_sources
                    enabled_sources = new_enabled_sources

                    pack_count, packs_changed = sync_packs(
                        agent_key
                    )

                    if packs_changed:
                        pack_engine.load()

                        loaded_rules = pack_engine.describe()

                        log(
                            f"FERPEK Lens reloaded "
                            f"{pack_count} pack(s), "
                            f"{len(loaded_rules)} rule(s)"
                        )

                    last_config_refresh = now

                except ApiError as exc:
                    if exc.status_code == 401:
                        log(
                            "Agent credentials have been revoked. "
                            "Re-add this host from the WebUI."
                        )

                        time.sleep(60)
                        continue

                    log(
                        f"Configuration error: {exc}"
                    )

                except Exception as exc:
                    log(
                        f"Configuration error: {exc}"
                    )

            poll_file_sources(
                enabled_sources,
                file_offsets,
            )

            try:
                event = EVENT_QUEUE.get(
                    timeout=0.5,
                )

                source_config = enabled_sources.get(
                    event["source_key"]
                )

                if source_config:
                    duplicate_for_pack = (
                        is_cross_source_duplicate(
                            event,
                            pack_dedupe_cache,
                        )
                    )

                    if duplicate_for_pack:
                        try:
                            metadata = json.loads(
                                event.get("metadata", "")
                                or "{}"
                            )

                            if not isinstance(metadata, dict):
                                metadata = {}

                        except (
                            json.JSONDecodeError,
                            TypeError,
                        ):
                            metadata = {}

                        metadata["duplicate_for_analysis"] = True
                        metadata["duplicate_family"] = event.get(
                            "source_family",
                            event.get("source_key", ""),
                        )

                        event["metadata"] = json.dumps(
                            metadata,
                            separators=(",", ":"),
                        )

                        result = {
                            "relevant": [],
                            "findings": [],
                        }
                    else:
                        result = pack_engine.process_event(
                            event
                        )

                    findings = result.get(
                        "findings",
                        [],
                    )

                    relevant = result.get(
                        "relevant",
                        [],
                    )

                    if relevant:
                        try:
                            send_relevant(
                                agent_key,
                                event,
                                relevant,
                            )
                        except Exception as exc:
                            log(
                                f"Could not send relevant events: {exc}"
                            )

                    if findings:
                        try:
                            send_findings(
                                agent_key,
                                findings,
                            )
                        except Exception as exc:
                            log(
                                f"Could not send findings: {exc}"
                            )

                    if source_config["send_events"]:
                        pending_events.append(event)

            except queue.Empty:
                pass

            if (
                time.monotonic()
                - last_pack_state_flush
                >= PACK_STATE_FLUSH_INTERVAL
            ):
                try:
                    pack_engine.save_state()
                except Exception as exc:
                    log(
                        f"Could not save pack state: {exc}"
                    )

                last_pack_state_flush = (
                    time.monotonic()
                )

            should_send = (
                len(pending_events) >= MAX_BATCH_SIZE
                or (
                    pending_events
                    and now - last_send >= SEND_INTERVAL
                )
            )

            if should_send:
                try:
                    send_event_batch(
                        agent_key,
                        pending_events,
                    )

                    pending_events = []
                    last_send = time.time()

                except Exception as exc:
                    log(
                        f"Could not send events: {exc}"
                    )

                    time.sleep(2)

    finally:
        try:
            pack_engine.save_state(force=True)
        except Exception as exc:
            log(
                f"Could not save final pack state: {exc}"
            )

        stop_event.set()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        sys.exit(0)

    except Exception as exc:
        log(
            f"Fatal error: {exc}"
        )

        sys.exit(1)

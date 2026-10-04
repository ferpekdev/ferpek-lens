#!/usr/bin/env python3

import hashlib
import json
import re
import os
import platform
import queue
import sqlite3

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

import yaml

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
SPOOL_DB_FILE = STATE_DIR / "spool.db"

CONFIG_REFRESH_INTERVAL = 10
FILE_POLL_INTERVAL = 1
MAX_FILE_LINES_PER_CYCLE = 200
SEND_INTERVAL = 2
PACK_STATE_FLUSH_INTERVAL = 2
MAX_BATCH_SIZE = 100

EVENT_QUEUE = queue.Queue(maxsize=5000)

def spool_db():
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(
        SPOOL_DB_FILE,
        timeout=5,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA journal_mode=WAL"
    )
    conn.execute(
        "PRAGMA synchronous=FULL"
    )
    conn.execute(
        "PRAGMA busy_timeout=5000"
    )
    conn.execute(
        "PRAGMA foreign_keys=ON"
    )

    return conn


def initialize_spool():
    with spool_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                source_key TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(collection_events)"
            )
        }

        if "queued" not in columns:
            conn.execute(
                """
                ALTER TABLE collection_events
                ADD COLUMN queued INTEGER NOT NULL DEFAULT 0
                """
            )

        # A previous process may have died with events marked queued.
        conn.execute(
            """
            UPDATE collection_events
            SET queued = 0
            WHERE processed = 0
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL UNIQUE,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_retry_at INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(event_id)
                    REFERENCES collection_events(event_id)
                    ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_retry
            ON outbox(next_retry_at, id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_collection_processed
            ON collection_events(processed, id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collector_checkpoints (
                source_key TEXT PRIMARY KEY,
                checkpoint_type TEXT NOT NULL,
                checkpoint_value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )


def journal_event_id(cursor):
    value = f"journal:{cursor}"

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def file_event_id(
    source_key,
    inode,
    offset,
):
    value = (
        f"file:{source_key}:"
        f"{inode}:{offset}"
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def spool_event(event_id, event):
    payload = json.dumps(
        event,
        separators=(",", ":"),
    )

    with spool_db() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO collection_events
                (
                    event_id,
                    source_key,
                    payload,
                    created_at
                )
            VALUES (?, ?, ?, ?)
            """,
            (
                event_id,
                event["source_key"],
                payload,
                int(time.time()),
            ),
        )

        return cursor.rowcount > 0


def claim_spool_event(event_id):
    with spool_db() as conn:
        cursor = conn.execute(
            """
            UPDATE collection_events
            SET queued = 1
            WHERE event_id = ?
              AND processed = 0
              AND queued = 0
            """,
            (event_id,),
        )

        return cursor.rowcount > 0


def release_spool_event(event_id):
    with spool_db() as conn:
        conn.execute(
            """
            UPDATE collection_events
            SET queued = 0
            WHERE event_id = ?
              AND processed = 0
            """,
            (event_id,),
        )


def refill_event_queue(limit=500):
    available = EVENT_QUEUE.maxsize - EVENT_QUEUE.qsize()

    if available <= 0:
        return 0

    limit = min(
        limit,
        available,
    )

    with spool_db() as conn:
        rows = conn.execute(
            """
            SELECT
                event_id,
                payload
            FROM collection_events
            WHERE processed = 0
              AND queued = 0
            ORDER BY id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    added = 0

    for row in rows:
        event_id = row["event_id"]

        if not claim_spool_event(event_id):
            continue

        try:
            event = json.loads(
                row["payload"]
            )
            event["event_id"] = event_id

            EVENT_QUEUE.put_nowait(event)
            added += 1

        except (
            json.JSONDecodeError,
            queue.Full,
        ):
            release_spool_event(
                event_id
            )

            if EVENT_QUEUE.full():
                break

    return added



def mark_spool_event_processed(event_id):
    with spool_db() as conn:
        conn.execute(
            """
            UPDATE collection_events
            SET
                processed = 1,
                queued = 0
            WHERE event_id = ?
            """,
            (event_id,),
        )


def stable_output_id(
    kind,
    event_id,
    payload,
):
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    value = (
        f"{kind}:{event_id}:"
        f"{canonical}"
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def persist_event_outputs(
    event,
    relevant_events,
    findings,
    send_raw,
):
    event_id = event.get("event_id")

    if not event_id:
        raise RuntimeError(
            "Cannot persist outputs without event_id"
        )

    now = int(time.time())

    raw_payload = {
        "event_id": event_id,
        "source_key": event.get(
            "source_key",
            "",
        ),
        "timestamp": int(
            event.get(
                "timestamp",
                now,
            )
        ),
        "service": event.get(
            "service",
            "",
        ),
        "severity": event.get(
            "severity",
            "info",
        ),
        "message": event.get(
            "message",
            "",
        ),
        "metadata": event.get(
            "metadata",
            "",
        ),
    }

    relevant_payloads = []

    for relevant in relevant_events:
        payload = {
            "source_key": event.get(
                "source_key",
                "",
            ),
            "timestamp": int(
                event.get(
                    "timestamp",
                    now,
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

        output_id = stable_output_id(
            "relevant",
            event_id,
            payload,
        )

        payload["event_id"] = output_id

        relevant_payloads.append(
            (
                output_id,
                payload,
            )
        )

    finding_payloads = []

    for finding in findings:
        payload = dict(finding)

        output_id = stable_output_id(
            "finding",
            event_id,
            payload,
        )

        payload["detection_id"] = output_id

        finding_payloads.append(
            (
                output_id,
                payload,
            )
        )

    with spool_db() as conn:
        if send_raw:
            conn.execute(
                """
                INSERT OR IGNORE INTO outbox
                    (
                        item_id,
                        event_id,
                        kind,
                        payload,
                        created_at
                    )
                VALUES (?, ?, 'event', ?, ?)
                """,
                (
                    f"event:{event_id}",
                    event_id,
                    json.dumps(
                        raw_payload,
                        separators=(",", ":"),
                    ),
                    now,
                ),
            )

        for output_id, payload in relevant_payloads:
            conn.execute(
                """
                INSERT OR IGNORE INTO outbox
                    (
                        item_id,
                        event_id,
                        kind,
                        payload,
                        created_at
                    )
                VALUES (?, ?, 'relevant', ?, ?)
                """,
                (
                    f"relevant:{output_id}",
                    event_id,
                    json.dumps(
                        payload,
                        separators=(",", ":"),
                    ),
                    now,
                ),
            )

        for output_id, payload in finding_payloads:
            conn.execute(
                """
                INSERT OR IGNORE INTO outbox
                    (
                        item_id,
                        event_id,
                        kind,
                        payload,
                        created_at
                    )
                VALUES (?, ?, 'finding', ?, ?)
                """,
                (
                    f"finding:{output_id}",
                    event_id,
                    json.dumps(
                        payload,
                        separators=(",", ":"),
                    ),
                    now,
                ),
            )

        conn.execute(
            """
            UPDATE collection_events
            SET processed = 1
            WHERE event_id = ?
            """,
            (event_id,),
        )


def load_due_outbox(limit=100):
    now = int(time.time())

    with spool_db() as conn:
        return conn.execute(
            """
            SELECT
                id,
                item_id,
                event_id,
                kind,
                payload,
                attempts
            FROM outbox
            WHERE next_retry_at <= ?
            ORDER BY id
            LIMIT ?
            """,
            (
                now,
                limit,
            ),
        ).fetchall()


def delete_outbox_rows(row_ids):
    if not row_ids:
        return

    placeholders = ",".join(
        "?"
        for _ in row_ids
    )

    with spool_db() as conn:
        conn.execute(
            f"""
            DELETE FROM outbox
            WHERE id IN ({placeholders})
            """,
            row_ids,
        )


def retry_outbox_rows(rows):
    now = int(time.time())

    with spool_db() as conn:
        for row in rows:
            attempts = int(row["attempts"]) + 1

            delay = min(
                300,
                2 ** min(
                    attempts,
                    8,
                ),
            )

            conn.execute(
                """
                UPDATE outbox
                SET
                    attempts = ?,
                    next_retry_at = ?
                WHERE id = ?
                """,
                (
                    attempts,
                    now + delay,
                    row["id"],
                ),
            )


def cleanup_spool():
    with spool_db() as conn:
        cursor = conn.execute(
            """
            DELETE FROM collection_events
            WHERE processed = 1
              AND NOT EXISTS (
                  SELECT 1
                  FROM outbox
                  WHERE outbox.event_id =
                        collection_events.event_id
              )
            """
        )

        return cursor.rowcount


def flush_outbox(agent_key):
    rows = load_due_outbox(
        MAX_BATCH_SIZE
    )

    if not rows:
        return 0

    groups = {
        "event": [],
        "relevant": [],
        "finding": [],
    }

    for row in rows:
        if row["kind"] in groups:
            groups[row["kind"]].append(row)

    sent = 0

    endpoints = {
        "event": (
            "/api/v1/events",
            "events",
        ),
        "relevant": (
            "/api/v1/relevant",
            "events",
        ),
        "finding": (
            "/api/v1/findings",
            "findings",
        ),
    }

    for kind, group in groups.items():
        if not group:
            continue

        path, payload_key = endpoints[kind]

        payloads = []

        try:
            for row in group:
                payloads.append(
                    json.loads(
                        row["payload"]
                    )
                )

            api_request(
                "POST",
                path,
                {
                    payload_key: payloads,
                },
                agent_key,
            )

            delete_outbox_rows(
                [
                    row["id"]
                    for row in group
                ]
            )

            sent += len(group)

        except Exception as exc:
            retry_outbox_rows(group)

            log(
                f"Could not flush {kind} outbox: "
                f"{exc}"
            )

    return sent


def save_collector_checkpoint(
    source_key,
    checkpoint_type,
    checkpoint_value,
):
    with spool_db() as conn:
        conn.execute(
            """
            INSERT INTO collector_checkpoints
                (
                    source_key,
                    checkpoint_type,
                    checkpoint_value,
                    updated_at
                )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                checkpoint_type = excluded.checkpoint_type,
                checkpoint_value = excluded.checkpoint_value,
                updated_at = excluded.updated_at
            """,
            (
                source_key,
                checkpoint_type,
                str(checkpoint_value),
                int(time.time()),
            ),
        )


def load_collector_checkpoint(source_key):
    with spool_db() as conn:
        row = conn.execute(
            """
            SELECT
                checkpoint_type,
                checkpoint_value
            FROM collector_checkpoints
            WHERE source_key = ?
            """,
            (source_key,),
        ).fetchone()

    if row is None:
        return None

    return {
        "type": row["checkpoint_type"],
        "value": row["checkpoint_value"],
    }


def spool_counts():
    with spool_db() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*)
            FROM collection_events
            WHERE processed = 0
            """
        ).fetchone()[0]

        outbox = conn.execute(
            """
            SELECT COUNT(*)
            FROM outbox
            """
        ).fetchone()[0]

    return pending, outbox


DYNAMIC_SOURCE_FAMILIES = {}


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


def load_pack_source_families():
    families = {}

    if not PACKS_DIR.exists():
        return families

    for pack_dir in PACKS_DIR.iterdir():
        if not pack_dir.is_dir():
            continue

        manifest_path = pack_dir / "manifest.yaml"

        if not manifest_path.is_file():
            continue

        try:
            manifest = yaml.safe_load(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            log(
                f"Could not read pack family metadata "
                f"from {pack_dir.name}: {exc}"
            )
            continue

        if not isinstance(manifest, dict):
            continue

        platforms = manifest.get(
            "platforms",
            {},
        )

        if not isinstance(platforms, dict):
            continue

        for platform_config in platforms.values():
            if not isinstance(
                platform_config,
                dict,
            ):
                continue

            sources = platform_config.get(
                "sources",
                [],
            )

            if not isinstance(sources, list):
                continue

            for source in sources:
                if not isinstance(source, dict):
                    continue

                source_id = str(
                    source.get("id", "")
                ).strip()

                family = str(
                    source.get("family", "")
                ).strip()

                if source_id and family:
                    families[source_id] = family

    return families


def refresh_pack_source_families():
    global DYNAMIC_SOURCE_FAMILIES

    DYNAMIC_SOURCE_FAMILIES = (
        load_pack_source_families()
    )

    return DYNAMIC_SOURCE_FAMILIES


def source_family(source_key):
    if source_key in DYNAMIC_SOURCE_FAMILIES:
        return DYNAMIC_SOURCE_FAMILIES[
            source_key
        ]

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


def get_pack_catalog(agent_key: str):
    return api_request(
        "GET",
        "/api/v1/agent/pack-catalog",
        agent_key=agent_key,
    )


def journal_unit_exists(unit: str) -> bool:
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                unit,
                "--property=LoadState",
                "--value",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if result.returncode != 0:
        return False

    load_state = result.stdout.strip().lower()

    return load_state not in {
        "",
        "not-found",
    }


def discover_pack_source(source: dict):
    source_id = str(
        source.get("id", "")
    ).strip()

    result = {
        "source_id": source_id,
        "detected": False,
        "source_type": "",
        "source_value": "",
    }

    discovery = source.get(
        "discovery",
        [],
    )

    if not isinstance(discovery, list):
        return result

    for candidate in discovery:
        if not isinstance(candidate, dict):
            continue

        candidate_type = str(
            candidate.get("type", "")
        ).strip().lower()

        if candidate_type == "journal":
            for unit in candidate.get(
                "units",
                [],
            ):
                unit = str(unit).strip()

                if not unit:
                    continue

                if journal_unit_exists(unit):
                    result.update(
                        {
                            "detected": True,
                            "source_type": "journal",
                            "source_value": unit,
                        }
                    )

                    return result

        if candidate_type == "file":
            for file_path in candidate.get(
                "paths",
                [],
            ):
                file_path = str(
                    file_path
                ).strip()

                if not file_path:
                    continue

                if Path(file_path).is_file():
                    result.update(
                        {
                            "detected": True,
                            "source_type": "file",
                            "source_value": file_path,
                        }
                    )

                    return result

    return result


def discover_pack_catalog(agent_key: str):
    catalog = get_pack_catalog(
        agent_key
    )

    results = []

    for pack in catalog.get(
        "packs",
        [],
    ):
        pack_id = str(
            pack.get("id", "")
        ).strip()

        if not pack_id:
            continue

        source_results = []

        for source in pack.get(
            "sources",
            [],
        ):
            if not isinstance(source, dict):
                continue

            source_results.append(
                discover_pack_source(source)
            )

        detected = (
            bool(source_results)
            and all(
                source["detected"]
                for source in source_results
            )
        )

        results.append(
            {
                "pack_id": pack_id,
                "supported": True,
                "detected": detected,
                "sources": source_results,
            }
        )

    response = api_request(
        "POST",
        "/api/v1/agent/pack-discovery",
        {
            "packs": results,
        },
        agent_key,
    )

    log(
        f"Reported discovery for "
        f"{response['received']} pack(s)"
    )

    return results


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
        "platform": platform.system().lower(),
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
            "platform": os_info["platform"],
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
            "platform": os_info["platform"],
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
                    line_offset = file.tell()
                    line = file.readline()

                    if not line:
                        break

                    event = normalize_file_event(
                        source,
                        line,
                    )

                    if event is not None:
                        event_id = file_event_id(
                            source_key,
                            stat.st_ino,
                            line_offset,
                        )

                        event["event_id"] = event_id

                        persisted = spool_event(
                            event_id,
                            event,
                        )

                        if (
                            persisted
                            and claim_spool_event(
                                event_id
                            )
                        ):
                            try:
                                EVENT_QUEUE.put(
                                    event,
                                    timeout=1,
                                )
                            except queue.Full:
                                release_spool_event(
                                    event_id
                                )

                                log(
                                    "Event queue full; "
                                    "file event remains "
                                    "in durable spool"
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

    while not stop_event.is_set():
        process = None

        try:
            checkpoint = load_collector_checkpoint(
                "journald"
            )

            command = [
                "journalctl",
                "--follow",
                "--output=json",
                "--no-pager",
            ]

            if (
                checkpoint
                and checkpoint["type"] == "cursor"
                and checkpoint["value"]
            ):
                command.append(
                    f"--after-cursor={checkpoint['value']}"
                )
            else:
                command.append("--lines=0")

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

                cursor = str(
                    entry.get("__CURSOR", "")
                )

                if not cursor:
                    continue

                unit = str(
                    entry.get("_SYSTEMD_UNIT", "")
                ).lower()

                if unit in {
                    "ferpek-agent.service",
                    "rosetta-agent.service",
                }:
                    save_collector_checkpoint(
                        "journald",
                        "cursor",
                        cursor,
                    )
                    continue

                message = str(
                    entry.get("MESSAGE", "")
                )

                if FERPEK_LOG_MARKER in message:
                    save_collector_checkpoint(
                        "journald",
                        "cursor",
                        cursor,
                    )
                    continue

                event = normalize_journal_event(entry)

                if event is None:
                    save_collector_checkpoint(
                        "journald",
                        "cursor",
                        cursor,
                    )
                    continue

                event["source_family"] = source_family(
                    event["source_key"]
                )

                event_id = journal_event_id(cursor)
                event["event_id"] = event_id

                persisted = spool_event(
                    event_id,
                    event,
                )

                save_collector_checkpoint(
                    "journald",
                    "cursor",
                    cursor,
                )

                if (
                    persisted
                    and claim_spool_event(
                        event_id
                    )
                ):
                    try:
                        EVENT_QUEUE.put(
                            event,
                            timeout=1,
                        )
                    except queue.Full:
                        release_spool_event(
                            event_id
                        )

                        log(
                            "Event queue full; "
                            "journal event remains "
                            "in durable spool"
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



def main():
    log(
        f"FERPEK Agent {VERSION} starting"
    )

    initialize_spool()

    pending_spool, pending_outbox = spool_counts()

    log(
        f"Durable spool ready: "
        f"{pending_spool} pending event(s), "
        f"{pending_outbox} outbox item(s)"
    )

    recovered = refill_event_queue(
        EVENT_QUEUE.maxsize
    )

    if recovered:
        log(
            f"Recovered {recovered} "
            f"event(s) from durable spool"
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

    try:
        discover_pack_catalog(
            agent_key
        )
    except Exception as exc:
        log(
            f"Could not discover packs: {exc}"
        )

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

        families = refresh_pack_source_families()

        log(
            f"Loaded {len(families)} "
            f"pack source family mapping(s)"
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

                    try:
                        discover_pack_catalog(
                            agent_key
                        )
                    except Exception as exc:
                        log(
                            f"Could not discover packs: {exc}"
                        )

                    pack_count, packs_changed = sync_packs(
                        agent_key
                    )

                    if packs_changed:
                        families = (
                            refresh_pack_source_families()
                        )

                        log(
                            f"Loaded {len(families)} "
                            f"pack source family mapping(s)"
                        )

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

                    try:
                        persist_event_outputs(
                            event,
                            relevant,
                            findings,
                            bool(
                                source_config[
                                    "send_events"
                                ]
                            ),
                        )
                    except Exception as exc:
                        log(
                            f"Could not persist event outputs: {exc}"
                        )

                        event_id = event.get(
                            "event_id"
                        )

                        if event_id:
                            release_spool_event(
                                event_id
                            )

                        log(
                            "Event remains in durable spool"
                        )

                        time.sleep(1)

                else:
                    event_id = event.get(
                        "event_id"
                    )

                    if event_id:
                        mark_spool_event_processed(
                            event_id
                        )

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

            refill_event_queue()

            if now - last_send >= SEND_INTERVAL:
                try:
                    sent = flush_outbox(
                        agent_key
                    )

                    if sent:
                        log(
                            f"Outbox sent: "
                            f"{sent} item(s)"
                        )

                    cleanup_spool()

                    if sent < MAX_BATCH_SIZE:
                        last_send = time.time()

                except Exception as exc:
                    log(
                        f"Could not flush outbox: {exc}"
                    )

                    last_send = time.time()

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

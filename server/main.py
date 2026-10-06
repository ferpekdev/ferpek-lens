import os
import json
import urllib.error
import urllib.parse
import urllib.request
"""
FERPEK Server

Recebe eventos e findings de FERPEK Agents.

Modelo:
  Host/Agent
    -> Log Sources
    -> Events
    -> Findings

Os agentes iniciam sempre a comunicação com o servidor.
Nenhuma porta precisa de ser aberta nos hosts monitorizados.
"""

import os
import re
import secrets
import hashlib
import sqlite3
import ssl
import threading
import time
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from ldap3 import BASE, SUBTREE, Connection, Server, Tls, NONE
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from fastapi.responses import FileResponse
from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
import json

import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion

DB_PATH = os.environ.get("DB_PATH", "/data/ferpek.db")
SECRET_KEY_PATH = Path(
    os.environ.get(
        "FERPEK_SECRET_KEY_PATH",
        "/data/ferpek-secret.key",
    )
)

INSTALLED_PACKS_PATH = Path("/data/packs")
PACK_ENGINE_PATH = Path("/app/ferpek_lens/pack_engine.py")

PACK_REGISTRY_URL = os.environ.get(
    "PACK_REGISTRY_URL",
    "https://raw.githubusercontent.com/ferpekdev/ferpek-lens-packs/main/index.json",
)

EVENT_RETENTION_DAYS = 14
RESOLVED_FINDING_RETENTION_DAYS = 90
RETENTION_CLEANUP_INTERVAL = 3600

retention_stop_event = threading.Event()

SERVER_VERSION = "0.4.1"

app = FastAPI(
    title="ferpek-server",
    version=SERVER_VERSION,
)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)



def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with db() as conn:
        # Existing table: retained for compatibility.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,
                agent_key TEXT NOT NULL UNIQUE,
                enrolled_at INTEGER NOT NULL,
                last_seen INTEGER
            )
        """)

        # Add host metadata without destroying existing data.
        if not column_exists(conn, "agents", "os_name"):
            conn.execute("ALTER TABLE agents ADD COLUMN os_name TEXT")

        if not column_exists(conn, "agents", "os_version"):
            conn.execute("ALTER TABLE agents ADD COLUMN os_version TEXT")

        if not column_exists(conn, "agents", "agent_version"):
            conn.execute("ALTER TABLE agents ADD COLUMN agent_version TEXT")

        if not column_exists(conn, "agents", "machine_type"):
            conn.execute("ALTER TABLE agents ADD COLUMN machine_type TEXT")

        if not column_exists(conn, "agents", "platform"):
            conn.execute("ALTER TABLE agents ADD COLUMN platform TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                pattern_id TEXT NOT NULL,
                service TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT,
                suggest TEXT,
                source_line TEXT,
                received_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                FOREIGN KEY(agent_id) REFERENCES agents(id)
            )
        """)

        if not column_exists(conn, "findings", "group_key"):
            conn.execute(
                "ALTER TABLE findings ADD COLUMN group_key TEXT NOT NULL DEFAULT ''"
            )

        if not column_exists(conn, "findings", "first_seen"):
            conn.execute(
                "ALTER TABLE findings ADD COLUMN first_seen INTEGER"
            )

        if not column_exists(conn, "findings", "last_seen"):
            conn.execute(
                "ALTER TABLE findings ADD COLUMN last_seen INTEGER"
            )

        if not column_exists(conn, "findings", "detection_count"):
            conn.execute(
                "ALTER TABLE findings ADD COLUMN detection_count INTEGER NOT NULL DEFAULT 1"
            )

        if not column_exists(conn, "findings", "resolved_at"):
            conn.execute(
                "ALTER TABLE findings ADD COLUMN resolved_at INTEGER"
            )

        conn.execute(
            """
            UPDATE findings
            SET
                first_seen = COALESCE(first_seen, received_at),
                last_seen = COALESCE(last_seen, received_at)
            """
        )


        # Historical resolved findings predate resolved_at.
        # Their exact resolution time is unknown, so received_at
        # is used only as a migration fallback.
        conn.execute(
            """
            UPDATE findings
            SET resolved_at = received_at
            WHERE status = 'resolved'
              AND resolved_at IS NULL
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_findings_status_resolved_at
            ON findings(status, resolved_at)
            """
        )


        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_findings_unique_open_group
            ON findings(
                agent_id,
                pattern_id,
                group_key
            )
            WHERE status = 'open'
            """
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS enrollment_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                used_at INTEGER
            )
        """)
        if not column_exists(conn, "enrollment_tokens", "agent_id"):
            conn.execute(
                "ALTER TABLE enrollment_tokens ADD COLUMN agent_id INTEGER"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # ------------------------------------------------------------------
        # Web authentication / RBAC
        # ------------------------------------------------------------------

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                display_name TEXT,
                email TEXT,
                auth_type TEXT NOT NULL DEFAULT 'local',
                password_hash TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_login_at INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                builtin INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                permission_key TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_groups (
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                PRIMARY KEY(user_id, group_id),
                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(group_id)
                    REFERENCES groups(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_permissions (
                group_id INTEGER NOT NULL,
                permission_id INTEGER NOT NULL,
                PRIMARY KEY(group_id, permission_id),
                FOREIGN KEY(group_id)
                    REFERENCES groups(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(permission_id)
                    REFERENCES permissions(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS directory_user_groups (
                user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                PRIMARY KEY(user_id, group_id),
                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(group_id)
                    REFERENCES groups(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                directory_checked_at INTEGER,
                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            )
        """)

        if not column_exists(
            conn,
            "web_sessions",
            "directory_checked_at",
        ):
            conn.execute(
                """
                ALTER TABLE web_sessions
                ADD COLUMN directory_checked_at INTEGER
                """
            )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_sessions_token_hash
            ON web_sessions(token_hash)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_web_sessions_user_id
            ON web_sessions(user_id)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase
            ON users(username COLLATE NOCASE)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pack_states (
                pack_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL
            )
        """)

        now = int(time.time())

        rbac_permissions = {
            "users.view": "View users",
            "users.manage": "Create, edit and disable users",
            "groups.view": "View groups and permissions",
            "groups.manage": "Create and edit groups and permissions",

            "hosts.view": "View monitored hosts",
            "hosts.manage": "Change host and source configuration",
            "hosts.delete": "Delete monitored hosts",

            "findings.view": "View findings",
            "findings.resolve": "Resolve findings",

            "logs.view": "View raw and relevant log activity",

            "packs.view": "View installed packs",
            "packs.manage": "Install, edit, enable and remove packs",

            "settings.view": "View FERPEK settings",
            "settings.manage": "Change general FERPEK settings",
            "settings.auth_manage": "Manage authentication providers",
        }

        for permission_key, description in rbac_permissions.items():
            conn.execute(
                """
                INSERT INTO permissions
                    (permission_key, description)
                VALUES (?, ?)
                ON CONFLICT(permission_key)
                DO UPDATE SET
                    description = excluded.description
                """,
                (
                    permission_key,
                    description,
                ),
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO groups
                (
                    name,
                    description,
                    builtin,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, 1, ?, ?)
            """,
            (
                "Administrators",
                "Full access to FERPEK",
                now,
                now,
            ),
        )

        administrators_group = conn.execute(
            """
            SELECT id
            FROM groups
            WHERE name = 'Administrators'
            """
        ).fetchone()

        if administrators_group:
            conn.execute(
                """
                INSERT OR IGNORE INTO group_permissions
                    (group_id, permission_id)
                SELECT ?, id
                FROM permissions
                """,
                (administrators_group["id"],),
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (key, value, updated_at)
            VALUES
                ('event_retention_days', '14', ?)
            """,
            (now,),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (key, value, updated_at)
            VALUES
                ('relevant_retention_days', '30', ?)
            """,
            (now,),
        )


        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (key, value, updated_at)
            VALUES
                ('resolved_finding_retention_days', '90', ?)
            """,
            (now,),
        )


        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (key, value, updated_at)
            VALUES
                ('allow_community_packs', '0', ?)
            """,
            (now,),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO settings
                (key, value, updated_at)
            VALUES
                ('allow_local_packs', '1', ?)
            """,
            (now,),
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS log_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                path TEXT,
                unit TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                send_events INTEGER NOT NULL DEFAULT 1,
                discovered INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(agent_id, source_key),
                FOREIGN KEY(agent_id) REFERENCES agents(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_pack_assignments (
                agent_id INTEGER NOT NULL,
                pack_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(agent_id, pack_id),
                FOREIGN KEY(agent_id) REFERENCES agents(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_pack_discovery (
                agent_id INTEGER NOT NULL,
                pack_id TEXT NOT NULL,
                supported INTEGER NOT NULL DEFAULT 0,
                detected INTEGER NOT NULL DEFAULT 0,
                source_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_value TEXT NOT NULL DEFAULT '',
                checked_at INTEGER NOT NULL,
                PRIMARY KEY(agent_id, pack_id),
                FOREIGN KEY(agent_id) REFERENCES agents(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_pack_source_discovery (
                agent_id INTEGER NOT NULL,
                pack_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                detected INTEGER NOT NULL DEFAULT 0,
                source_type TEXT NOT NULL DEFAULT '',
                source_value TEXT NOT NULL DEFAULT '',
                checked_at INTEGER NOT NULL,
                PRIMARY KEY(agent_id, pack_id, source_id),
                FOREIGN KEY(agent_id) REFERENCES agents(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                event_time INTEGER NOT NULL,
                service TEXT,
                severity TEXT,
                message TEXT NOT NULL,
                metadata TEXT,
                received_at INTEGER NOT NULL,
                FOREIGN KEY(agent_id) REFERENCES agents(id)
            )
        """)


        conn.execute("""
            CREATE TABLE IF NOT EXISTS relevant_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                event_time INTEGER NOT NULL,
                pack_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                service TEXT,
                severity TEXT,
                title TEXT NOT NULL,
                detail TEXT,
                fields TEXT,
                source_message TEXT,
                received_at INTEGER NOT NULL,
                FOREIGN KEY(agent_id) REFERENCES agents(id)
            )
        """)

        if not column_exists(conn, "events", "event_id"):
            conn.execute(
                "ALTER TABLE events ADD COLUMN event_id TEXT"
            )

        if not column_exists(conn, "relevant_events", "event_id"):
            conn.execute(
                "ALTER TABLE relevant_events ADD COLUMN event_id TEXT"
            )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_agent_event_id
            ON events(agent_id, event_id)
            WHERE event_id IS NOT NULL
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relevant_agent_event_id
            ON relevant_events(agent_id, event_id)
            WHERE event_id IS NOT NULL
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS finding_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL,
                detection_id TEXT NOT NULL,
                finding_id INTEGER,
                received_at INTEGER NOT NULL,
                UNIQUE(agent_id, detection_id),
                FOREIGN KEY(agent_id) REFERENCES agents(id),
                FOREIGN KEY(finding_id) REFERENCES findings(id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_finding_detections_received_at
            ON finding_detections(received_at)
            """
        )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_agent_time
            ON events(agent_id, event_time DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_source_time
            ON events(source_key, event_time DESC)
        """)


        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relevant_agent_time
            ON relevant_events(agent_id, event_time DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_relevant_received_at
            ON relevant_events(received_at DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_findings_agent_time
            ON findings(agent_id, received_at DESC)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_received_at
            ON events(received_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_findings_status_received_at
            ON findings(status, received_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_findings_open_group
            ON findings(agent_id, pattern_id, group_key, status)
        """)



def get_setting_text(
    key: str,
    default: str = "",
) -> str:
    try:
        with db() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return default

        return str(row["value"])

    except sqlite3.Error:
        return default


def set_setting(
    conn: sqlite3.Connection,
    key: str,
    value: str,
    now: int,
):
    conn.execute(
        """
        INSERT INTO settings
            (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (
            key,
            value,
            now,
        ),
    )


def get_secret_fernet() -> Fernet:
    SECRET_KEY_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not SECRET_KEY_PATH.exists():
        key = Fernet.generate_key()

        fd = os.open(
            SECRET_KEY_PATH,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL,
            0o600,
        )

        try:
            os.write(fd, key)
        finally:
            os.close(fd)

    key = SECRET_KEY_PATH.read_bytes().strip()

    try:
        return Fernet(key)
    except Exception as exc:
        raise RuntimeError(
            "Invalid FERPEK secret key"
        ) from exc


def encrypt_secret(value: str) -> str:
    return (
        get_secret_fernet()
        .encrypt(value.encode("utf-8"))
        .decode("ascii")
    )


def decrypt_secret(value: str) -> str:
    if not value:
        return ""

    try:
        return (
            get_secret_fernet()
            .decrypt(value.encode("ascii"))
            .decode("utf-8")
        )
    except InvalidToken as exc:
        raise RuntimeError(
            "Could not decrypt FERPEK secret"
        ) from exc


def get_setting_int(key: str, default: int) -> int:
    try:
        with db() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return default

        return int(row["value"])

    except (
        ValueError,
        TypeError,
        sqlite3.Error,
    ):
        return default


def get_setting_bool(key: str, default: bool) -> bool:
    try:
        with db() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM settings
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return default

        return str(row["value"]).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    except sqlite3.Error:
        return default


def cleanup_retention():
    now = int(time.time())

    event_retention_days = get_setting_int(
        "event_retention_days",
        EVENT_RETENTION_DAYS,
    )

    relevant_retention_days = get_setting_int(
        "relevant_retention_days",
        30,
    )

    resolved_finding_retention_days = get_setting_int(
        "resolved_finding_retention_days",
        RESOLVED_FINDING_RETENTION_DAYS,
    )

    event_cutoff = (
        now
        - event_retention_days * 24 * 60 * 60
    )

    relevant_cutoff = (
        now
        - relevant_retention_days * 24 * 60 * 60
    )

    finding_cutoff = (
        now
        - resolved_finding_retention_days
        * 24 * 60 * 60
    )

    with db() as conn:
        events_deleted = conn.execute(
            """
            DELETE FROM events
            WHERE received_at < ?
            """,
            (event_cutoff,),
        ).rowcount

        relevant_deleted = conn.execute(
            """
            DELETE FROM relevant_events
            WHERE received_at < ?
            """,
            (relevant_cutoff,),
        ).rowcount

        conn.execute(
            """
            DELETE FROM finding_detections
            WHERE finding_id IN (
                SELECT id
                FROM findings
                WHERE status = 'resolved'
                  AND resolved_at IS NOT NULL
                  AND resolved_at < ?
            )
            """,
            (finding_cutoff,),
        )

        findings_deleted = conn.execute(
            """
            DELETE FROM findings
            WHERE status = 'resolved'
              AND resolved_at IS NOT NULL
              AND resolved_at < ?
            """,
            (finding_cutoff,),
        ).rowcount

    if events_deleted or relevant_deleted or findings_deleted:
        print(
            "[FERPEK Retention] "
            f"deleted {events_deleted} event(s), "
            f"{relevant_deleted} relevant event(s), "
            f"{findings_deleted} resolved finding(s)",
            flush=True,
        )


def retention_worker():
    while not retention_stop_event.is_set():
        try:
            cleanup_retention()
        except Exception as exc:
            print(
                f"[FERPEK Retention] cleanup failed: {exc}",
                flush=True,
            )

        retention_stop_event.wait(
            RETENTION_CLEANUP_INTERVAL
        )


@app.on_event("startup")
def on_startup():
    init_db()

    retention_stop_event.clear()

    retention_thread = threading.Thread(
        target=retention_worker,
        daemon=True,
        name="retention-cleanup",
    )

    retention_thread.start()


@app.on_event("shutdown")
def on_shutdown():
    retention_stop_event.set()


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

def hash_local_password(password: str) -> str:
    salt = secrets.token_bytes(16)

    n = 16384
    r = 8
    p = 1

    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=64,
    )

    return (
        f"scrypt${n}${r}${p}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_local_password(
    password: str,
    stored_hash: str,
) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = (
            stored_hash.split("$", 5)
        )

        if algorithm != "scrypt":
            return False

        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )

        return secrets.compare_digest(
            digest,
            bytes.fromhex(digest_hex),
        )
    except Exception:
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


class FirstRunSetup(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    display_name: str = Field(
        default="",
        max_length=128,
    )
    email: str = Field(
        default="",
        max_length=254,
    )
    password: str = Field(
        min_length=12,
        max_length=256,
    )


class LoginRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=64,
    )
    password: str = Field(
        min_length=1,
        max_length=256,
    )


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(
        min_length=1,
        max_length=256,
    )
    new_password: str = Field(
        min_length=12,
        max_length=256,
    )


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    display_name: str = Field(
        default="",
        max_length=128,
    )
    email: str = Field(
        default="",
        max_length=254,
    )
    password: str = Field(
        min_length=12,
        max_length=256,
    )
    group_ids: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    display_name: Optional[str] = Field(
        default=None,
        max_length=128,
    )
    email: Optional[str] = Field(
        default=None,
        max_length=254,
    )
    password: Optional[str] = Field(
        default=None,
        min_length=12,
        max_length=256,
    )
    enabled: Optional[bool] = None
    group_ids: Optional[list[int]] = None


class LDAPSettings(BaseModel):
    enabled: bool = False

    provider_type: str = Field(
        default="ldap",
        pattern=r"^(ldap|active_directory)$",
    )

    host: str = Field(
        default="",
        max_length=255,
    )

    port: int = Field(
        default=389,
        ge=1,
        le=65535,
    )

    security: str = Field(
        default="plain",
        pattern=r"^(plain|starttls|ldaps)$",
    )

    base_dn: str = Field(
        default="",
        max_length=512,
    )

    bind_dn: str = Field(
        default="",
        max_length=512,
    )

    bind_password: Optional[str] = Field(
        default=None,
        max_length=1024,
    )

    clear_bind_password: bool = False

    user_search_base: str = Field(
        default="",
        max_length=512,
    )

    user_filter: str = Field(
        default="(uid={username})",
        max_length=512,
    )

    username_attribute: str = Field(
        default="uid",
        min_length=1,
        max_length=128,
    )

    group_mappings: dict[str, int] = Field(
        default_factory=dict,
    )


class LDAPTestUserRequest(BaseModel):
    username: str = Field(
        min_length=1,
        max_length=128,
    )
    password: str = Field(
        min_length=1,
        max_length=1024,
    )


class PackSettings(BaseModel):
    allow_community_packs: bool = False
    allow_local_packs: bool = True


class RetentionSettings(BaseModel):
    event_retention_days: int = Field(
        default=14,
        ge=1,
        le=3650,
    )

    relevant_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
    )

    resolved_finding_retention_days: int = Field(
        default=90,
        ge=1,
        le=3650,
    )


class EnrollRequest(BaseModel):
    hostname: str
    token: str
    os_name: str = ""
    os_version: str = ""
    platform: str = ""
    agent_version: str = ""


class EnrollResponse(BaseModel):
    agent_id: int
    agent_key: str


class FindingIn(BaseModel):
    detection_id: str | None = None
    pattern_id: str
    group_key: str = ""
    service: str
    severity: str
    title: str
    detail: str = ""
    suggest: str = ""
    source_line: str = ""


class FindingsBatch(BaseModel):
    findings: list[FindingIn]


class EventIn(BaseModel):
    event_id: str | None = None
    source_key: str
    timestamp: int
    service: str = ""
    severity: str = "info"
    message: str
    metadata: str = ""


class EventsBatch(BaseModel):
    events: list[EventIn] = Field(max_length=500)


class RelevantEventIn(BaseModel):
    event_id: str | None = None
    source_key: str
    timestamp: int
    pack_id: str
    rule_id: str
    service: str = ""
    severity: str = "info"
    title: str
    detail: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    source_message: str = ""


class RelevantEventsBatch(BaseModel):
    events: list[RelevantEventIn] = Field(max_length=500)


class SourceIn(BaseModel):
    source_key: str
    name: str
    source_type: str
    path: str = ""
    unit: str = ""
    enabled: bool = True
    send_events: bool = True
    discovered: bool = False


class SourcesBatch(BaseModel):
    sources: list[SourceIn]


class AgentMetadata(BaseModel):
    os_name: str = ""
    os_version: str = ""
    platform: str = ""
    agent_version: str = ""
    machine_type: str = ""


class AgentPackAssignmentPayload(BaseModel):
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class AgentPackSourceDiscoveryResult(BaseModel):
    source_id: str
    detected: bool
    source_type: str = ""
    source_value: str = ""


class AgentPackDiscoveryResult(BaseModel):
    pack_id: str
    supported: bool
    detected: bool
    sources: list[AgentPackSourceDiscoveryResult] = Field(
        default_factory=list,
        max_length=100,
    )


class AgentPackDiscoveryBatch(BaseModel):
    packs: list[AgentPackDiscoveryResult] = Field(
        max_length=200
    )


# ---------------------------------------------------------------------------
# Agent authentication
# ---------------------------------------------------------------------------

def get_agent(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            401,
            "Falta o header Authorization: Bearer <agent_key>",
        )

    agent_key = authorization.removeprefix("Bearer ").strip()

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_key = ?",
            (agent_key,),
        ).fetchone()

        if not row:
            raise HTTPException(401, "agent_key inválido")

        now = int(time.time())

        conn.execute(
            "UPDATE agents SET last_seen = ? WHERE id = ?",
            (now, row["id"]),
        )

        agent = dict(row)
        agent["last_seen"] = now
        return agent


# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": SERVER_VERSION,
    }

@app.get("/install-agent.sh", include_in_schema=False)
def download_agent_installer():
    return FileResponse(
        "/app/install-agent.sh",
        media_type="text/x-shellscript",
        filename="install-agent.sh",
    )


@app.get("/agent.py", include_in_schema=False)
def download_agent():
    return FileResponse(
        "/app/agent.py",
        media_type="text/x-python",
        filename="agent.py",
    )


class EnrollmentTokenStatusRequest(BaseModel):
    token: str


def hash_enrollment_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Web authentication - first run
# ---------------------------------------------------------------------------

@app.get("/api/v1/auth/setup")
def get_auth_setup_status():
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM users"
        ).fetchone()

    return {
        "setup_required": row["total"] == 0,
    }


@app.post("/api/v1/auth/setup")
def complete_auth_setup(setup: FirstRunSetup):
    username = setup.username.strip().lower()
    display_name = setup.display_name.strip()
    email = setup.email.strip()

    with db() as conn:
        # Prevent two concurrent requests from both becoming
        # the first administrator.
        conn.execute("BEGIN IMMEDIATE")

        user_count = conn.execute(
            "SELECT COUNT(*) AS total FROM users"
        ).fetchone()["total"]

        if user_count != 0:
            raise HTTPException(
                409,
                "FERPEK initial setup has already been completed",
            )

        administrators = conn.execute(
            """
            SELECT id
            FROM groups
            WHERE name = 'Administrators'
            """
        ).fetchone()

        if administrators is None:
            raise HTTPException(
                500,
                "Administrators group is missing",
            )

        now = int(time.time())
        password_hash = hash_local_password(
            setup.password
        )

        cursor = conn.execute(
            """
            INSERT INTO users
                (
                    username,
                    display_name,
                    email,
                    auth_type,
                    password_hash,
                    enabled,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, ?, 'local', ?, 1, ?, ?)
            """,
            (
                username,
                display_name,
                email,
                password_hash,
                now,
                now,
            ),
        )

        user_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO user_groups
                (user_id, group_id)
            VALUES (?, ?)
            """,
            (
                user_id,
                administrators["id"],
            ),
        )

    return {
        "ok": True,
        "user": {
            "id": user_id,
            "username": username,
            "display_name": display_name,
            "email": email,
            "auth_type": "local",
            "groups": ["Administrators"],
        },
    }


@app.post("/api/v1/auth/login")
def login(
    credentials: LoginRequest,
    response: Response,
):
    login_identifier = credentials.username.strip()

    if not login_identifier:
        raise HTTPException(
            401,
            "Invalid username or password",
        )

    # Resolve explicit provider prefix
    forced_auth_type = None
    username = login_identifier

    login_identifier_lower = login_identifier.lower()

    if login_identifier_lower.startswith("local:"):
        forced_auth_type = "local"
        username = login_identifier[6:].strip()

    elif login_identifier_lower.startswith("ldap:"):
        forced_auth_type = "ldap"
        username = login_identifier[5:].strip()

    elif login_identifier_lower.startswith("ad:"):
        forced_auth_type = "active_directory"
        username = login_identifier[3:].strip()

    if not username:
        raise HTTPException(
            401,
            "Invalid username or password",
        )

    ldap_user = None
    user = None

    # Look for a local identity unless a directory provider was forced
    if forced_auth_type not in {
        "ldap",
        "active_directory",
    }:
        with db() as conn:
            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE username = ? COLLATE NOCASE
                  AND auth_type = 'local'
                """,
                (username,),
            ).fetchone()

    # Local authentication
    if (
        forced_auth_type == "local"
        or (
            forced_auth_type is None
            and user is not None
        )
    ):
        if user is None:
            raise HTTPException(
                401,
                "Invalid username or password",
            )
        if (
            not bool(user["enabled"])
            or not user["password_hash"]
            or not verify_local_password(
                credentials.password,
                user["password_hash"],
            )
        ):
            raise HTTPException(
                401,
                "Invalid username or password",
            )

    # Directory authentication
    else:
        provider_type = get_setting_text(
            "ldap_provider_type",
            "ldap",
        ).strip()

        directory_auth_type = (
            "active_directory"
            if provider_type == "active_directory"
            else "ldap"
        )

        # Reject a forced provider that is not configured
        if (
            forced_auth_type in {
                "ldap",
                "active_directory",
            }
            and forced_auth_type != directory_auth_type
        ):
            raise HTTPException(
                401,
                "Invalid username or password",
            )

        if not get_setting_bool(
            "ldap_enabled",
            False,
        ):
            raise HTTPException(
                401,
                "Invalid username or password",
            )

        # Existing LDAP users may be disabled explicitly
        # by a FERPEK administrator.
        if (
            user is not None
            and user["auth_type"] == directory_auth_type
            and not bool(user["enabled"])
        ):
            raise HTTPException(
                401,
                "Invalid username or password",
            )

        try:
            ldap_user = authenticate_ldap_user(
                username,
                credentials.password,
            )
        except RuntimeError as exc:
            print(
                "[FERPEK LDAP] "
                f"login authentication error: {exc}",
                flush=True,
            )

            raise HTTPException(
                503,
                "Authentication service unavailable",
            )

        if ldap_user is None:
            raise HTTPException(
                401,
                "Invalid username or password",
            )

        now = int(time.time())

        ldap_username = (
            ldap_user["username"].strip()
            or username
        )

        display_name = (
            ldap_user["display_name"].strip()
            or ldap_username
        )

        email = ldap_user["email"].strip()

        directory_groups = ldap_user.get(
            "groups",
            [],
        )

        with db() as conn:
            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE username = ? COLLATE NOCASE
                  AND auth_type = ?
                """,
                (
                    username,
                    directory_auth_type,
                ),
            ).fetchone()

            if user is None:
                # Check the username returned by LDAP too,
                # in case its canonical form differs.
                canonical_user = conn.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE username = ? COLLATE NOCASE
                      AND auth_type = ?
                    """,
                    (
                        ldap_username,
                        directory_auth_type,
                    ),
                ).fetchone()

                if canonical_user is not None:
                    user = canonical_user

            if user is None:
                cursor = conn.execute(
                    """
                    INSERT INTO users
                        (
                            username,
                            display_name,
                            email,
                            auth_type,
                            password_hash,
                            enabled,
                            created_at,
                            updated_at
                        )
                    VALUES (?, ?, ?, ?, NULL, 1, ?, ?)
                    """,
                    (
                        ldap_username,
                        display_name,
                        email,
                        directory_auth_type,
                        now,
                        now,
                    ),
                )

                user_id = cursor.lastrowid

            else:
                if user["auth_type"] != directory_auth_type:
                    raise HTTPException(
                        401,
                        "Invalid username or password",
                    )

                if not bool(user["enabled"]):
                    raise HTTPException(
                        401,
                        "Invalid username or password",
                    )

                user_id = user["id"]

                conn.execute(
                    """
                    UPDATE users
                    SET
                        display_name = ?,
                        email = ?,
                        password_hash = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        display_name,
                        email,
                        now,
                        user_id,
                    ),
                )

            sync_directory_user_groups(
                conn,
                user_id,
                directory_groups,
            )

            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()

    # -----------------------------------------------------
    # FERPEK Lens session
    # -----------------------------------------------------

    token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(token)

    now = int(time.time())
    expires_at = now + (12 * 60 * 60)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO web_sessions
                (
                    token_hash,
                    user_id,
                    created_at,
                    expires_at,
                    last_seen_at
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                token_hash,
                user["id"],
                now,
                expires_at,
                now,
            ),
        )

        conn.execute(
            """
            UPDATE users
            SET
                last_login_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                now,
                user["id"],
            ),
        )

    response.set_cookie(
        key="ferpek_session",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "auth_type": user["auth_type"],
        },
    }

def get_web_user(
    ferpek_session: Optional[str] = Cookie(None),
):
    if not ferpek_session:
        raise HTTPException(
            401,
            "Not authenticated",
        )

    token_hash = hash_session_token(
        ferpek_session
    )
    now = int(time.time())

    with db() as conn:
        row = conn.execute(
            """
            SELECT
                users.*,
                web_sessions.id AS session_id,
                web_sessions.expires_at,
                web_sessions.directory_checked_at
            FROM web_sessions
            JOIN users
              ON users.id = web_sessions.user_id
            WHERE web_sessions.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if (
            row is None
            or not bool(row["enabled"])
            or row["expires_at"] <= now
        ):
            if row is not None:
                conn.execute(
                    """
                    DELETE FROM web_sessions
                    WHERE id = ?
                    """,
                    (row["session_id"],),
                )

            raise HTTPException(
                401,
                "Session expired or invalid",
            )

        conn.execute(
            """
            UPDATE web_sessions
            SET last_seen_at = ?
            WHERE id = ?
            """,
            (
                now,
                row["session_id"],
            ),
        )

        if row["auth_type"] == "active_directory":
            directory_checked_at = (
                row["directory_checked_at"] or 0
            )

            if now - directory_checked_at >= 600:
                try:
                    directory_user = authenticate_ldap_user(
                        row["username"],
                        None,
                    )
                except RuntimeError as exc:
                    print(
                        "[FERPEK LDAP] "
                        f"session revalidation failed: {exc}",
                        flush=True,
                    )

                    raise HTTPException(
                        503,
                        "Authentication service unavailable",
                    )

                if (
                    directory_user is None
                    or not directory_user.get(
                        "enabled",
                        True,
                    )
                ):
                    conn.execute(
                        """
                        DELETE FROM web_sessions
                        WHERE user_id = ?
                        """,
                        (row["id"],),
                    )

                    raise HTTPException(
                        401,
                        "Session expired or invalid",
                    )

                sync_directory_user_groups(
                    conn,
                    row["id"],
                    directory_user.get(
                        "groups",
                        [],
                    ),
                )

                conn.execute(
                    """
                    UPDATE web_sessions
                    SET directory_checked_at = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        row["session_id"],
                    ),
                )

        groups = [
            group["name"]
            for group in conn.execute(
                """
                SELECT groups.name
                FROM groups
                JOIN user_groups
                  ON user_groups.group_id = groups.id
                WHERE user_groups.user_id = ?
                ORDER BY groups.name
                """,
                (row["id"],),
            ).fetchall()
        ]

        permissions = [
            permission["permission_key"]
            for permission in conn.execute(
                """
                SELECT DISTINCT permissions.permission_key
                FROM permissions
                JOIN group_permissions
                  ON group_permissions.permission_id = permissions.id
                JOIN user_groups
                  ON user_groups.group_id = group_permissions.group_id
                WHERE user_groups.user_id = ?
                ORDER BY permissions.permission_key
                """,
                (row["id"],),
            ).fetchall()
        ]

    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "email": row["email"],
        "auth_type": row["auth_type"],
        "groups": groups,
        "permissions": permissions,
    }


def require_permission(permission_key: str):
    def dependency(
        user: dict = Depends(get_web_user),
    ):
        if permission_key not in user["permissions"]:
            raise HTTPException(
                403,
                f"Missing permission: {permission_key}",
            )

        return user

    return dependency


@app.post("/api/v1/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: dict = Depends(get_web_user),
    ferpek_session: Optional[str] = Cookie(None),
):
    if current_user["auth_type"] != "local":
        raise HTTPException(
            400,
            "Password is managed by the authentication provider",
        )

    if not ferpek_session:
        raise HTTPException(
            401,
            "Not authenticated",
        )

    now = int(time.time())
    current_session_hash = hash_session_token(
        ferpek_session
    )

    with db() as conn:
        user = conn.execute(
            """
            SELECT
                id,
                password_hash
            FROM users
            WHERE id = ?
            """,
            (current_user["id"],),
        ).fetchone()

        if user is None:
            raise HTTPException(
                404,
                "User not found",
            )

        if not verify_local_password(
            payload.current_password,
            user["password_hash"],
        ):
            raise HTTPException(
                400,
                "Current password is incorrect",
            )

        if verify_local_password(
            payload.new_password,
            user["password_hash"],
        ):
            raise HTTPException(
                400,
                "New password must be different from the current password",
            )

        conn.execute(
            """
            UPDATE users
            SET
                password_hash = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                hash_local_password(
                    payload.new_password
                ),
                now,
                current_user["id"],
            ),
        )

        conn.execute(
            """
            DELETE FROM web_sessions
            WHERE user_id = ?
              AND token_hash != ?
            """,
            (
                current_user["id"],
                current_session_hash,
            ),
        )

    return {
        "ok": True,
    }


@app.get("/api/v1/auth/me")
def auth_me(
    user: dict = Depends(get_web_user),
):
    return user


@app.post("/api/v1/auth/logout")
def logout(
    response: Response,
    ferpek_session: Optional[str] = Cookie(None),
):
    if ferpek_session:
        token_hash = hash_session_token(
            ferpek_session
        )

        with db() as conn:
            conn.execute(
                """
                DELETE FROM web_sessions
                WHERE token_hash = ?
                """,
                (token_hash,),
            )

    response.delete_cookie(
        key="ferpek_session",
        path="/",
    )

    return {
        "ok": True,
    }


# ---------------------------------------------------------------------------
# Users / Groups / Permissions
# ---------------------------------------------------------------------------

@app.get(
    "/api/v1/users",
    dependencies=[
        Depends(require_permission("users.view"))
    ],
)
def list_users():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                email,
                auth_type,
                enabled,
                created_at,
                updated_at,
                last_login_at
            FROM users
            ORDER BY username COLLATE NOCASE
            """
        ).fetchall()

        users = []

        for row in rows:
            groups = [
                group["name"]
                for group in conn.execute(
                    """
                    SELECT groups.name
                    FROM groups
                    JOIN user_groups
                      ON user_groups.group_id = groups.id
                    WHERE user_groups.user_id = ?
                    ORDER BY groups.name
                    """,
                    (row["id"],),
                ).fetchall()
            ]

            users.append(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "email": row["email"],
                    "auth_type": row["auth_type"],
                    "enabled": bool(row["enabled"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "last_login_at": row["last_login_at"],
                    "groups": groups,
                }
            )

    return {
        "users": users,
    }


@app.post(
    "/api/v1/users",
    dependencies=[
        Depends(require_permission("users.manage"))
    ],
)
def create_user(
    payload: UserCreate,
):
    username = payload.username.strip().lower()
    display_name = payload.display_name.strip()
    email = payload.email.strip()
    group_ids = list(dict.fromkeys(payload.group_ids))
    now = int(time.time())

    with db() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()

        if existing is not None:
            raise HTTPException(
                409,
                "Username already exists",
            )

        if group_ids:
            placeholders = ",".join("?" for _ in group_ids)

            valid_group_ids = {
                row["id"]
                for row in conn.execute(
                    f"""
                    SELECT id
                    FROM groups
                    WHERE id IN ({placeholders})
                    """,
                    group_ids,
                ).fetchall()
            }

            if valid_group_ids != set(group_ids):
                raise HTTPException(
                    400,
                    "One or more groups do not exist",
                )

        cursor = conn.execute(
            """
            INSERT INTO users
                (
                    username,
                    display_name,
                    email,
                    auth_type,
                    password_hash,
                    enabled,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, ?, 'local', ?, 1, ?, ?)
            """,
            (
                username,
                display_name,
                email,
                hash_local_password(payload.password),
                now,
                now,
            ),
        )

        user_id = cursor.lastrowid

        for group_id in group_ids:
            conn.execute(
                """
                INSERT INTO user_groups
                    (user_id, group_id)
                VALUES (?, ?)
                """,
                (
                    user_id,
                    group_id,
                ),
            )

        groups = [
            row["name"]
            for row in conn.execute(
                """
                SELECT groups.name
                FROM groups
                JOIN user_groups
                  ON user_groups.group_id = groups.id
                WHERE user_groups.user_id = ?
                ORDER BY groups.name
                """,
                (user_id,),
            ).fetchall()
        ]

    return {
        "id": user_id,
        "username": username,
        "display_name": display_name,
        "email": email,
        "auth_type": "local",
        "enabled": True,
        "groups": groups,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }


@app.patch(
    "/api/v1/users/{user_id}",
)
def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: dict = Depends(
        require_permission("users.manage")
    ),
):
    now = int(time.time())

    with db() as conn:
        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if user is None:
            raise HTTPException(
                404,
                "User not found",
            )

        is_local_user = user["auth_type"] == "local"

        if not is_local_user and any(
            value is not None
            for value in (
                payload.username,
                payload.display_name,
                payload.email,
                payload.password,
            )
        ):
            raise HTTPException(
                400,
                "Directory identity fields cannot be edited locally",
            )

        username = (
            payload.username.strip().lower()
            if is_local_user and payload.username is not None
            else user["username"]
        )

        display_name = (
            payload.display_name.strip()
            if is_local_user and payload.display_name is not None
            else user["display_name"]
        )

        email = (
            payload.email.strip()
            if is_local_user and payload.email is not None
            else user["email"]
        )

        enabled = (
            payload.enabled
            if payload.enabled is not None
            else bool(user["enabled"])
        )

        if (
            user_id == current_user["id"]
            and not enabled
        ):
            raise HTTPException(
                400,
                "You cannot disable your own account",
            )

        duplicate = conn.execute(
            """
            SELECT id
            FROM users
            WHERE username = ? COLLATE NOCASE
              AND id != ?
            """,
            (
                username,
                user_id,
            ),
        ).fetchone()

        if duplicate is not None:
            raise HTTPException(
                409,
                "Username already exists",
            )

        current_group_ids = {
            row["id"]
            for row in conn.execute(
                """
                SELECT groups.id
                FROM groups
                JOIN user_groups
                  ON user_groups.group_id = groups.id
                WHERE user_groups.user_id = ?
                """,
                (user_id,),
            ).fetchall()
        }

        if payload.group_ids is None:
            new_group_ids = current_group_ids
        else:
            new_group_ids = set(payload.group_ids)

            if new_group_ids:
                placeholders = ",".join(
                    "?" for _ in new_group_ids
                )

                valid_group_ids = {
                    row["id"]
                    for row in conn.execute(
                        f"""
                        SELECT id
                        FROM groups
                        WHERE id IN ({placeholders})
                        """,
                        tuple(new_group_ids),
                    ).fetchall()
                }

                if valid_group_ids != new_group_ids:
                    raise HTTPException(
                        400,
                        "One or more groups do not exist",
                    )

        administrators = conn.execute(
            """
            SELECT id
            FROM groups
            WHERE name = 'Administrators'
            """
        ).fetchone()

        administrator_group_id = (
            administrators["id"]
            if administrators is not None
            else None
        )

        is_administrator = (
            administrator_group_id is not None
            and administrator_group_id
            in current_group_ids
        )

        remains_administrator = (
            administrator_group_id is not None
            and administrator_group_id
            in new_group_ids
            and enabled
        )

        if is_administrator and not remains_administrator:
            other_active_admins = conn.execute(
                """
                SELECT COUNT(DISTINCT users.id) AS total
                FROM users
                JOIN user_groups
                  ON user_groups.user_id = users.id
                JOIN groups
                  ON groups.id = user_groups.group_id
                WHERE groups.name = 'Administrators'
                  AND users.enabled = 1
                  AND users.id != ?
                """,
                (user_id,),
            ).fetchone()["total"]

            if other_active_admins == 0:
                raise HTTPException(
                    400,
                    "Cannot remove or disable the last active administrator",
                )

        password_hash = user["password_hash"]
        password_changed = (
            is_local_user
            and payload.password is not None
        )

        if password_changed:
            password_hash = hash_local_password(
                payload.password
            )

        conn.execute(
            """
            UPDATE users
            SET
                username = ?,
                display_name = ?,
                email = ?,
                password_hash = ?,
                enabled = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                username,
                display_name,
                email,
                password_hash,
                1 if enabled else 0,
                now,
                user_id,
            ),
        )

        if payload.group_ids is not None:
            conn.execute(
                """
                DELETE FROM user_groups
                WHERE user_id = ?
                """,
                (user_id,),
            )

            for group_id in sorted(new_group_ids):
                conn.execute(
                    """
                    INSERT INTO user_groups
                        (user_id, group_id)
                    VALUES (?, ?)
                    """,
                    (
                        user_id,
                        group_id,
                    ),
                )

        if not enabled or password_changed:
            conn.execute(
                """
                DELETE FROM web_sessions
                WHERE user_id = ?
                """,
                (user_id,),
            )

        groups = [
            row["name"]
            for row in conn.execute(
                """
                SELECT groups.name
                FROM groups
                JOIN user_groups
                  ON user_groups.group_id = groups.id
                WHERE user_groups.user_id = ?
                ORDER BY groups.name
                """,
                (user_id,),
            ).fetchall()
        ]

        updated = conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                email,
                auth_type,
                enabled,
                created_at,
                updated_at,
                last_login_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

    return {
        "id": updated["id"],
        "username": updated["username"],
        "display_name": updated["display_name"],
        "email": updated["email"],
        "auth_type": updated["auth_type"],
        "enabled": bool(updated["enabled"]),
        "created_at": updated["created_at"],
        "updated_at": updated["updated_at"],
        "last_login_at": updated["last_login_at"],
        "groups": groups,
    }


@app.delete(
    "/api/v1/users/{user_id}",
)
def delete_user(
    user_id: int,
    current_user: dict = Depends(
        require_permission("users.manage")
    ),
):
    if user_id == current_user["id"]:
        raise HTTPException(
            400,
            "You cannot delete your own account",
        )

    with db() as conn:
        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if user is None:
            raise HTTPException(
                404,
                "User not found",
            )

        if user["auth_type"] != "local":
            raise HTTPException(
                400,
                "Directory-managed users cannot be deleted. Disable the account instead.",
            )

        is_administrator = conn.execute(
            """
            SELECT 1
            FROM user_groups
            JOIN groups
              ON groups.id = user_groups.group_id
            WHERE user_groups.user_id = ?
              AND groups.name = 'Administrators'
            """,
            (user_id,),
        ).fetchone() is not None

        if is_administrator and bool(user["enabled"]):
            other_active_admins = conn.execute(
                """
                SELECT COUNT(DISTINCT users.id) AS total
                FROM users
                JOIN user_groups
                  ON user_groups.user_id = users.id
                JOIN groups
                  ON groups.id = user_groups.group_id
                WHERE groups.name = 'Administrators'
                  AND users.enabled = 1
                  AND users.id != ?
                """,
                (user_id,),
            ).fetchone()["total"]

            if other_active_admins == 0:
                raise HTTPException(
                    400,
                    "Cannot delete the last active administrator",
                )

        conn.execute(
            """
            DELETE FROM users
            WHERE id = ?
            """,
            (user_id,),
        )

    return {
        "ok": True,
    }



class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
    )
    permissions: Optional[list[str]] = None


def get_group_payload(
    conn: sqlite3.Connection,
    group_id: int,
):
    row = conn.execute(
        """
        SELECT
            id,
            name,
            description,
            builtin,
            created_at,
            updated_at
        FROM groups
        WHERE id = ?
        """,
        (group_id,),
    ).fetchone()

    if row is None:
        return None

    permissions = [
        permission["permission_key"]
        for permission in conn.execute(
            """
            SELECT permissions.permission_key
            FROM permissions
            JOIN group_permissions
              ON group_permissions.permission_id =
                 permissions.id
            WHERE group_permissions.group_id = ?
            ORDER BY permissions.permission_key
            """,
            (group_id,),
        ).fetchall()
    ]

    member_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM user_groups
        WHERE group_id = ?
        """,
        (group_id,),
    ).fetchone()["count"]

    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "builtin": bool(row["builtin"]),
        "member_count": member_count,
        "permissions": permissions,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def validate_group_permissions(
    conn: sqlite3.Connection,
    permission_keys: list[str],
):
    unique_keys = sorted(set(permission_keys))

    if not unique_keys:
        return []

    placeholders = ",".join(
        "?" for _ in unique_keys
    )

    rows = conn.execute(
        f"""
        SELECT id, permission_key
        FROM permissions
        WHERE permission_key IN ({placeholders})
        """,
        unique_keys,
    ).fetchall()

    found = {
        row["permission_key"]: row["id"]
        for row in rows
    }

    missing = [
        key
        for key in unique_keys
        if key not in found
    ]

    if missing:
        raise HTTPException(
            400,
            "Unknown permissions: "
            + ", ".join(missing),
        )

    return [
        (found[key], key)
        for key in unique_keys
    ]


@app.post(
    "/api/v1/groups",
    dependencies=[
        Depends(require_permission("groups.manage"))
    ],
)
def create_group(req: GroupCreate):
    now = int(time.time())
    name = req.name.strip()
    description = req.description.strip()

    if not name:
        raise HTTPException(
            400,
            "Group name is required",
        )

    with db() as conn:
        duplicate = conn.execute(
            """
            SELECT id
            FROM groups
            WHERE name = ? COLLATE NOCASE
            """,
            (name,),
        ).fetchone()

        if duplicate is not None:
            raise HTTPException(
                409,
                "A group with this name already exists",
            )

        validated_permissions = (
            validate_group_permissions(
                conn,
                req.permissions,
            )
        )

        cur = conn.execute(
            """
            INSERT INTO groups
                (
                    name,
                    description,
                    builtin,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, 0, ?, ?)
            """,
            (
                name,
                description,
                now,
                now,
            ),
        )

        group_id = cur.lastrowid

        for permission_id, _ in validated_permissions:
            conn.execute(
                """
                INSERT INTO group_permissions
                    (
                        group_id,
                        permission_id
                    )
                VALUES (?, ?)
                """,
                (
                    group_id,
                    permission_id,
                ),
            )

        return get_group_payload(
            conn,
            group_id,
        )


@app.patch(
    "/api/v1/groups/{group_id}",
    dependencies=[
        Depends(require_permission("groups.manage"))
    ],
)
def update_group(
    group_id: int,
    req: GroupUpdate,
):
    now = int(time.time())

    with db() as conn:
        group = conn.execute(
            """
            SELECT *
            FROM groups
            WHERE id = ?
            """,
            (group_id,),
        ).fetchone()

        if group is None:
            raise HTTPException(
                404,
                "Group not found",
            )

        if bool(group["builtin"]):
            raise HTTPException(
                400,
                "Built-in groups cannot be modified",
            )

        new_name = (
            req.name.strip()
            if req.name is not None
            else group["name"]
        )

        if not new_name:
            raise HTTPException(
                400,
                "Group name is required",
            )

        duplicate = conn.execute(
            """
            SELECT id
            FROM groups
            WHERE name = ? COLLATE NOCASE
              AND id != ?
            """,
            (
                new_name,
                group_id,
            ),
        ).fetchone()

        if duplicate is not None:
            raise HTTPException(
                409,
                "A group with this name already exists",
            )

        new_description = (
            req.description.strip()
            if req.description is not None
            else group["description"]
        )

        validated_permissions = None

        if req.permissions is not None:
            validated_permissions = (
                validate_group_permissions(
                    conn,
                    req.permissions,
                )
            )

        conn.execute(
            """
            UPDATE groups
            SET
                name = ?,
                description = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_description,
                now,
                group_id,
            ),
        )

        if validated_permissions is not None:
            conn.execute(
                """
                DELETE FROM group_permissions
                WHERE group_id = ?
                """,
                (group_id,),
            )

            for permission_id, _ in validated_permissions:
                conn.execute(
                    """
                    INSERT INTO group_permissions
                        (
                            group_id,
                            permission_id
                        )
                    VALUES (?, ?)
                    """,
                    (
                        group_id,
                        permission_id,
                    ),
                )

        return get_group_payload(
            conn,
            group_id,
        )


@app.delete(
    "/api/v1/groups/{group_id}",
    dependencies=[
        Depends(require_permission("groups.manage"))
    ],
)
def delete_group(group_id: int):
    with db() as conn:
        group = conn.execute(
            """
            SELECT *
            FROM groups
            WHERE id = ?
            """,
            (group_id,),
        ).fetchone()

        if group is None:
            raise HTTPException(
                404,
                "Group not found",
            )

        if bool(group["builtin"]):
            raise HTTPException(
                400,
                "Built-in groups cannot be deleted",
            )

        conn.execute(
            """
            DELETE FROM user_groups
            WHERE group_id = ?
            """,
            (group_id,),
        )

        conn.execute(
            """
            DELETE FROM group_permissions
            WHERE group_id = ?
            """,
            (group_id,),
        )

        conn.execute(
            """
            DELETE FROM groups
            WHERE id = ?
            """,
            (group_id,),
        )

    return {
        "ok": True,
    }


@app.get(
    "/api/v1/groups",
    dependencies=[
        Depends(require_permission("groups.view"))
    ],
)
def list_groups():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                name,
                description,
                builtin,
                created_at,
                updated_at
            FROM groups
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()

        groups = []

        for row in rows:
            permissions = [
                permission["permission_key"]
                for permission in conn.execute(
                    """
                    SELECT permissions.permission_key
                    FROM permissions
                    JOIN group_permissions
                      ON group_permissions.permission_id =
                         permissions.id
                    WHERE group_permissions.group_id = ?
                    ORDER BY permissions.permission_key
                    """,
                    (row["id"],),
                ).fetchall()
            ]

            member_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM user_groups
                WHERE group_id = ?
                """,
                (row["id"],),
            ).fetchone()["count"]

            groups.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "builtin": bool(row["builtin"]),
                    "member_count": member_count,
                    "permissions": permissions,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )

    return {
        "groups": groups,
    }


@app.get(
    "/api/v1/permissions",
    dependencies=[
        Depends(require_permission("groups.view"))
    ],
)
def list_permissions():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                permission_key,
                description
            FROM permissions
            ORDER BY permission_key
            """
        ).fetchall()

    return {
        "permissions": [
            {
                "id": row["id"],
                "permission_key": row["permission_key"],
                "description": row["description"],
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

@app.post("/api/v1/enrollment-tokens", dependencies=[Depends(require_permission("hosts.manage"))])
def create_enrollment_token():
    now = int(time.time())
    expires_at = now + 900
    token = "enr_" + secrets.token_urlsafe(24)
    token_hash = hash_enrollment_token(token)

    with db() as conn:
        conn.execute(
            """
            INSERT INTO enrollment_tokens
                (token, created_at, expires_at)
            VALUES (?, ?, ?)
            """,
            (token_hash, now, expires_at),
        )

    return {
        "token": token,
        "expires_at": expires_at,
        "expires_in": 900,
    }

@app.post("/api/v1/enrollment-tokens/status")
def enrollment_token_status(
    req: EnrollmentTokenStatusRequest,
):
    now = int(time.time())
    token = req.token

    with db() as conn:
        row = conn.execute(
            """
            SELECT
                enrollment_tokens.created_at,
                enrollment_tokens.expires_at,
                enrollment_tokens.used_at,
                enrollment_tokens.agent_id,
                agents.hostname,
                agents.os_name,
                agents.os_version,
                agents.agent_version,
                agents.last_seen
            FROM enrollment_tokens
            LEFT JOIN agents
                ON agents.id = enrollment_tokens.agent_id
            WHERE enrollment_tokens.token IN (?, ?)
            """,
            (
                hash_enrollment_token(token),
                token,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(404, "Token não encontrado")

    if row["agent_id"] is not None:
        return {
            "status": "enrolled",
            "agent": {
                "id": row["agent_id"],
                "hostname": row["hostname"],
                "os_name": row["os_name"],
                "os_version": row["os_version"],
                "agent_version": row["agent_version"],
                "last_seen": row["last_seen"],
            },
        }

    if row["used_at"] is not None:
        return {
            "status": "used",
            "expires_in": 0,
        }

    if row["expires_at"] < now:
        return {
            "status": "expired",
            "expires_in": 0,
        }

    return {
        "status": "waiting",
        "expires_in": max(0, row["expires_at"] - now),
    }

@app.post("/api/v1/enroll", response_model=EnrollResponse)
def enroll(req: EnrollRequest):
    now = int(time.time())

    with db() as conn:
        token_row = conn.execute(
            """
            SELECT *
            FROM enrollment_tokens
            WHERE token IN (?, ?)
            """,
            (
                hash_enrollment_token(req.token),
                req.token,
            ),
        ).fetchone()

        if not token_row:
            raise HTTPException(
                403,
                "Token de enrolamento inválido",
            )

        if token_row["used_at"] is not None:
            raise HTTPException(
                403,
                "Token de enrolamento já utilizado",
            )

        if token_row["expires_at"] < now:
            raise HTTPException(
                403,
                "Token de enrolamento expirado",
            )

        reservation = conn.execute(
            """
            UPDATE enrollment_tokens
            SET used_at = ?
            WHERE id = ?
              AND used_at IS NULL
              AND expires_at >= ?
            """,
            (
                now,
                token_row["id"],
                now,
            ),
        )

        if reservation.rowcount != 1:
            current_token = conn.execute(
                """
                SELECT used_at, expires_at
                FROM enrollment_tokens
                WHERE id = ?
                """,
                (token_row["id"],),
            ).fetchone()

            if (
                current_token
                and current_token["used_at"] is not None
            ):
                raise HTTPException(
                    403,
                    "Token de enrolamento já utilizado",
                )

            if (
                current_token
                and current_token["expires_at"] < now
            ):
                raise HTTPException(
                    403,
                    "Token de enrolamento expirado",
                )

            raise HTTPException(
                403,
                "Token de enrolamento inválido",
            )

        agent_key = secrets.token_hex(24)

        cur = conn.execute(
            """
            INSERT INTO agents
                (
                    hostname,
                    agent_key,
                    enrolled_at,
                    last_seen,
                    os_name,
                    os_version,
                    platform,
                    agent_version
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.hostname,
                agent_key,
                now,
                now,
                req.os_name,
                req.os_version,
                req.platform,
                req.agent_version,
            ),
        )

        agent_id = cur.lastrowid

        conn.execute(
            """
            UPDATE enrollment_tokens
            SET agent_id = ?
            WHERE id = ?
              AND used_at = ?
            """,
            (
                agent_id,
                token_row["id"],
                now,
            ),
        )

    return EnrollResponse(
        agent_id=agent_id,
        agent_key=agent_key,
    )



# ---------------------------------------------------------------------------
# Agent metadata
# ---------------------------------------------------------------------------

@app.post("/api/v1/agent/metadata")
def update_agent_metadata(
    metadata: AgentMetadata,
    agent: dict = Depends(get_agent),
):
    with db() as conn:
        conn.execute(
            """
            UPDATE agents
            SET os_name = ?,
                os_version = ?,
                platform = ?,
                agent_version = ?,
                machine_type = ?
            WHERE id = ?
            """,
            (
                metadata.os_name,
                metadata.os_version,
                metadata.platform,
                metadata.agent_version,
                metadata.machine_type,
                agent["id"],
            ),
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

@app.post("/api/v1/sources/discover")
def discover_sources(
    batch: SourcesBatch,
    agent: dict = Depends(get_agent),
):
    now = int(time.time())

    with db() as conn:
        for source in batch.sources:
            existing = conn.execute(
                """
                SELECT id
                FROM log_sources
                WHERE agent_id = ? AND source_key = ?
                """,
                (agent["id"], source.source_key),
            ).fetchone()

            if existing:
                # Discovery must not overwrite the user's enabled/send_events
                # choices after initial creation.
                conn.execute(
                    """
                    UPDATE log_sources
                    SET name = ?,
                        source_type = ?,
                        path = ?,
                        unit = ?,
                        discovered = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        source.name,
                        source.source_type,
                        source.path,
                        source.unit,
                        int(source.discovered),
                        now,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO log_sources
                        (
                            agent_id,
                            source_key,
                            name,
                            source_type,
                            path,
                            unit,
                            enabled,
                            send_events,
                            discovered,
                            created_at,
                            updated_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent["id"],
                        source.source_key,
                        source.name,
                        source.source_type,
                        source.path,
                        source.unit,
                        int(source.enabled),
                        int(source.send_events),
                        int(source.discovered),
                        now,
                        now,
                    ),
                )

    return {"received": len(batch.sources)}


@app.get("/api/v1/agent/config")
def get_agent_config(agent: dict = Depends(get_agent)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                source_key,
                name,
                source_type,
                path,
                unit,
                enabled,
                send_events,
                discovered
            FROM log_sources
            WHERE agent_id = ?
            ORDER BY name
            """,
            (agent["id"],),
        ).fetchall()

    return {
        "agent_id": agent["id"],
        "hostname": agent["hostname"],
        "sources": [
            {
                **dict(row),
                "enabled": bool(row["enabled"]),
                "send_events": bool(row["send_events"]),
                "discovered": bool(row["discovered"]),
            }
            for row in rows
        ],
    }


def is_pack_source_manual_config_valid(
    source: dict,
    config: dict,
) -> bool:
    manual = source.get("manual")

    if not isinstance(manual, dict):
        return False

    fields = manual.get("fields", [])

    if not isinstance(fields, list) or not fields:
        return False

    source_id = str(
        source.get("id", "")
    ).strip()

    config_sources = config.get(
        "sources",
        {},
    )

    if not isinstance(config_sources, dict):
        return False

    source_config = config_sources.get(
        source_id,
        {},
    )

    if not isinstance(source_config, dict):
        return False

    for field in fields:
        if not isinstance(field, dict):
            continue

        field_id = str(
            field.get("id", "")
        ).strip()

        field_type = str(
            field.get(
                "type",
                "text",
            )
        ).strip().lower()

        required = bool(
            field.get(
                "required",
                False,
            )
        )

        value_present = (
            field_id in source_config
        )

        value = source_config.get(
            field_id
        )

        if required and not value_present:
            return False

        if not value_present:
            continue

        if field_type in {
            "text",
            "path",
            "secret",
        }:
            if not isinstance(value, str):
                return False

            if required and not value.strip():
                return False

        elif field_type == "number":
            if (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    (int, float),
                )
            ):
                return False

        elif field_type == "boolean":
            if not isinstance(
                value,
                bool,
            ):
                return False

        elif field_type == "select":
            options = field.get(
                "options",
                [],
            )

            if value not in options:
                return False

    return True


def evaluate_pack_activation_readiness(
    manifest: dict,
    agent_platform: str,
    discovery_by_source: dict,
    config: dict,
    discovery_checked: bool,
):
    platforms = manifest.get("platforms")

    if not isinstance(platforms, dict):
        return {
            "status": "unknown",
            "can_activate": True,
            "reason": None,
        }

    platform_config = platforms.get(
        agent_platform
    )

    if not isinstance(platform_config, dict):
        return {
            "status": "unavailable",
            "can_activate": False,
            "reason": "platform_not_supported",
        }

    sources = platform_config.get(
        "sources",
        [],
    )

    if not isinstance(sources, list):
        return {
            "status": "unknown",
            "can_activate": True,
            "reason": None,
        }

    has_declarative_source = False
    used_manual_config = False

    for source in sources:
        if not isinstance(source, dict):
            continue

        source_id = str(
            source.get("id", "")
        ).strip()

        if not source_id:
            continue

        discovery = source.get(
            "discovery",
            [],
        )

        has_discovery = (
            isinstance(discovery, list)
            and bool(discovery)
        )

        manual = source.get("manual")

        has_manual = False

        if isinstance(manual, dict):
            fields = manual.get(
                "fields",
                [],
            )

            has_manual = (
                isinstance(fields, list)
                and bool(fields)
            )

        if not has_discovery and not has_manual:
            continue

        has_declarative_source = True

        discovery_row = discovery_by_source.get(
            source_id
        )

        if (
            discovery_row is not None
            and bool(discovery_row["detected"])
        ):
            continue

        if is_pack_source_manual_config_valid(
            source,
            config,
        ):
            used_manual_config = True
            continue

        if has_discovery and not discovery_checked:
            return {
                "status": "unknown",
                "can_activate": False,
                "reason": "discovery_pending",
            }

        if has_manual:
            return {
                "status": "needs_configuration",
                "can_activate": False,
                "reason": (
                    "source_requires_configuration:"
                    f"{source_id}"
                ),
            }

        return {
            "status": "unavailable",
            "can_activate": False,
            "reason": (
                "source_not_detected:"
                f"{source_id}"
            ),
        }

    if not has_declarative_source:
        return {
            "status": "unknown",
            "can_activate": True,
            "reason": None,
        }

    if used_manual_config:
        return {
            "status": "configured",
            "can_activate": True,
            "reason": None,
        }

    return {
        "status": "detected",
        "can_activate": True,
        "reason": None,
    }


def get_pack_configuration_schema(
    manifest: dict,
    platform_name: str,
):
    platforms = manifest.get("platforms")

    if not isinstance(platforms, dict):
        return []

    platform_config = platforms.get(platform_name)

    if not isinstance(platform_config, dict):
        return []

    sources = platform_config.get("sources")

    if not isinstance(sources, list):
        return []

    schema = []

    for source in sources:
        if not isinstance(source, dict):
            continue

        source_id = str(source.get("id") or "").strip()

        if not source_id:
            continue

        manual = source.get("manual")

        if not isinstance(manual, dict):
            continue

        fields = manual.get("fields")

        if not isinstance(fields, list) or not fields:
            continue

        schema.append(
            {
                "source_id": source_id,
                "fields": fields,
            }
        )

    return schema


@app.get(
    "/api/v1/agents/{agent_id}/packs",
    dependencies=[
        Depends(require_permission("hosts.view"))
    ],
)
def list_agent_packs(agent_id: int):
    with db() as conn:
        agent = conn.execute(
            """
            SELECT *
            FROM agents
            WHERE id = ?
            """,
            (agent_id,),
        ).fetchone()

        if agent is None:
            raise HTTPException(
                404,
                "Host não encontrado",
            )

        assignments = {
            row["pack_id"]: row
            for row in conn.execute(
                """
                SELECT *
                FROM agent_pack_assignments
                WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchall()
        }

        discovery_rows = {
            row["pack_id"]: row
            for row in conn.execute(
                """
                SELECT *
                FROM agent_pack_discovery
                WHERE agent_id = ?
                """,
                (agent_id,),
            ).fetchall()
        }

        source_rows = conn.execute(
            """
            SELECT *
            FROM agent_pack_source_discovery
            WHERE agent_id = ?
            ORDER BY pack_id, source_id
            """,
            (agent_id,),
        ).fetchall()

    discovered_sources = {}

    for row in source_rows:
        discovered_sources.setdefault(
            row["pack_id"],
            [],
        ).append(
            {
                "source_id": row["source_id"],
                "detected": bool(row["detected"]),
                "source_type": row["source_type"],
                "source_value": row["source_value"],
                "checked_at": row["checked_at"],
            }
        )

    packs = []

    for pack_dir in iter_pack_dirs():
        if not pack_dir.is_dir():
            continue

        if pack_dir.is_symlink():
            continue

        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        pack_id = str(manifest["id"])
        assignment = assignments.get(pack_id)

        allowed = is_pack_allowed(manifest)
        globally_enabled = is_pack_enabled(pack_id)
        server_compatible = (
            is_pack_server_compatible(manifest)
        )
        agent_compatible = (
            is_pack_agent_compatible(
                manifest,
                str(
                    agent["agent_version"]
                    or ""
                ),
            )
        )
        platform_supported = (
            is_pack_platform_compatible(
                manifest,
                str(
                    agent["platform"]
                    or ""
                ),
            )
        )

        config = {}

        if assignment is not None:
            try:
                parsed = json.loads(
                    assignment["config_json"]
                    or "{}"
                )

                if isinstance(parsed, dict):
                    config = parsed
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                config = {}

        discovery = discovery_rows.get(pack_id)

        discovery_by_source = {
            item["source_id"]: item
            for item in discovered_sources.get(
                pack_id,
                [],
            )
        }

        platform_name = str(
            agent["platform"] or ""
        ).strip().lower()

        readiness = evaluate_pack_activation_readiness(
            manifest,
            platform_name,
            discovery_by_source,
            config,
            discovery is not None,
        )

        configuration_schema = (
            get_pack_configuration_schema(
                manifest,
                platform_name,
            )
        )

        discovery_status = readiness["status"]
        can_activate = readiness["can_activate"]

        if not (
            allowed
            and globally_enabled
            and server_compatible
            and agent_compatible
            and platform_supported
        ):
            discovery_status = "unavailable"
            can_activate = False

        packs.append(
            {
                "id": pack_id,
                "name": manifest.get(
                    "name",
                    pack_id,
                ),
                "version": str(
                    manifest.get(
                        "version",
                        "",
                    )
                ),
                "origin": str(
                    manifest.get(
                        "origin",
                        "local",
                    )
                ),
                "category": manifest.get(
                    "category",
                    {},
                ),
                "globally_enabled": (
                    globally_enabled
                ),
                "allowed": allowed,
                "server_compatible": (
                    server_compatible
                ),
                "agent_compatible": (
                    agent_compatible
                ),
                "platform_supported": (
                    platform_supported
                ),
                "assigned": (
                    assignment is not None
                ),
                "enabled": bool(
                    assignment["enabled"]
                )
                if assignment is not None
                else False,
                "config": config,
                "configuration_schema": (
                    configuration_schema
                ),
                "discovery_status": discovery_status,
                "can_activate": can_activate,
                "activation_reason": readiness["reason"],
                "discovery_checked_at": (
                    discovery["checked_at"]
                    if discovery is not None
                    else None
                ),
                "detected_sources": (
                    discovered_sources.get(
                        pack_id,
                        [],
                    )
                ),
            }
        )

    packs.sort(
        key=lambda pack: str(
            pack["name"]
        ).lower()
    )

    return {
        "agent_id": agent_id,
        "packs": packs,
    }


@app.put(
    "/api/v1/agents/{agent_id}/packs/{pack_id}",
    dependencies=[
        Depends(require_permission("hosts.manage"))
    ],
)
def update_agent_pack(
    agent_id: int,
    pack_id: str,
    payload: AgentPackAssignmentPayload,
):
    with db() as conn:
        agent = conn.execute(
            """
            SELECT *
            FROM agents
            WHERE id = ?
            """,
            (agent_id,),
        ).fetchone()

    if agent is None:
        raise HTTPException(
            404,
            "Host não encontrado",
        )

    pack_dir = None
    manifest = None

    for candidate in iter_pack_dirs():
        candidate_manifest = read_pack_manifest(
            candidate
        )

        if candidate_manifest is None:
            continue

        if (
            str(candidate_manifest.get("id"))
            == pack_id
        ):
            pack_dir = candidate
            manifest = candidate_manifest
            break

    if pack_dir is None or manifest is None:
        raise HTTPException(
            404,
            "Pack não encontrado",
        )

    if payload.enabled:
        if not is_pack_allowed(manifest):
            raise HTTPException(
                409,
                "Pack blocked by policy",
            )

        if not is_pack_enabled(pack_id):
            raise HTTPException(
                409,
                "Pack is globally disabled",
            )

        if not is_pack_server_compatible(
            manifest
        ):
            raise HTTPException(
                409,
                "Pack is not compatible with this server",
            )

        if not is_pack_agent_compatible(
            manifest,
            str(
                agent["agent_version"]
                or ""
            ),
        ):
            raise HTTPException(
                409,
                "Pack is not compatible with this agent",
            )

        if not is_pack_platform_compatible(
            manifest,
            str(
                agent["platform"]
                or ""
            ),
        ):
            raise HTTPException(
                409,
                "Pack is not compatible with this host platform",
            )

        platform_name = str(
            agent["platform"] or ""
        ).strip().lower()

        with db() as conn:
            pack_discovery = conn.execute(
                """
                SELECT *
                FROM agent_pack_discovery
                WHERE agent_id = ?
                  AND pack_id = ?
                """,
                (
                    agent_id,
                    pack_id,
                ),
            ).fetchone()

            source_rows = conn.execute(
                """
                SELECT *
                FROM agent_pack_source_discovery
                WHERE agent_id = ?
                  AND pack_id = ?
                """,
                (
                    agent_id,
                    pack_id,
                ),
            ).fetchall()

        discovery_by_source = {
            row["source_id"]: row
            for row in source_rows
        }

        readiness = evaluate_pack_activation_readiness(
            manifest,
            platform_name,
            discovery_by_source,
            payload.config,
            pack_discovery is not None,
        )

        if not readiness["can_activate"]:
            reason = readiness["reason"]

            if reason == "discovery_pending":
                detail = (
                    "Pack discovery has not completed yet"
                )

            elif (
                isinstance(reason, str)
                and reason.startswith(
                    "source_requires_configuration:"
                )
            ):
                source_id = reason.split(
                    ":",
                    1,
                )[1]

                detail = (
                    "Pack source was not detected "
                    "and requires configuration: "
                    f"{source_id}"
                )

            elif (
                isinstance(reason, str)
                and reason.startswith(
                    "source_not_detected:"
                )
            ):
                source_id = reason.split(
                    ":",
                    1,
                )[1]

                detail = (
                    "Pack source was not detected: "
                    f"{source_id}"
                )

            elif reason == "platform_not_supported":
                detail = (
                    "Pack is not compatible with "
                    "this host platform"
                )

            else:
                detail = "Pack cannot be activated"

            raise HTTPException(
                409,
                detail,
            )

    try:
        config_json = json.dumps(
            payload.config,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            400,
            f"Invalid pack configuration: {exc}",
        )

    now = int(time.time())

    with db() as conn:
        conn.execute(
            """
            INSERT INTO agent_pack_assignments
                (
                    agent_id,
                    pack_id,
                    enabled,
                    config_json,
                    created_at,
                    updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, pack_id)
            DO UPDATE SET
                enabled = excluded.enabled,
                config_json = excluded.config_json,
                updated_at = excluded.updated_at
            """,
            (
                agent_id,
                pack_id,
                int(payload.enabled),
                config_json,
                now,
                now,
            ),
        )

    return {
        "ok": True,
        "agent_id": agent_id,
        "pack_id": pack_id,
        "enabled": payload.enabled,
        "config": payload.config,
    }


@app.get("/api/v1/agents/{agent_id}/sources", dependencies=[Depends(require_permission("hosts.view"))])
def list_agent_sources(agent_id: int):
    with db() as conn:
        agent = conn.execute(
            "SELECT id FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()

        if not agent:
            raise HTTPException(404, "Host não encontrado")

        rows = conn.execute(
            """
            SELECT *
            FROM log_sources
            WHERE agent_id = ?
            ORDER BY name
            """,
            (agent_id,),
        ).fetchall()

    return [
        {
            **dict(row),
            "enabled": bool(row["enabled"]),
            "send_events": bool(row["send_events"]),
            "discovered": bool(row["discovered"]),
        }
        for row in rows
    ]


@app.patch("/api/v1/agents/{agent_id}/sources/{source_key}", dependencies=[Depends(require_permission("hosts.manage"))])
def update_agent_source(
    agent_id: int,
    source_key: str,
    enabled: Optional[bool] = None,
    send_events: Optional[bool] = None,
):
    if enabled is None and send_events is None:
        raise HTTPException(400, "Nenhuma alteração pedida")

    with db() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM log_sources
            WHERE agent_id = ? AND source_key = ?
            """,
            (agent_id, source_key),
        ).fetchone()

        if not row:
            raise HTTPException(404, "Source não encontrada")

        new_enabled = int(enabled) if enabled is not None else row["enabled"]
        new_send_events = (
            int(send_events)
            if send_events is not None
            else row["send_events"]
        )

        conn.execute(
            """
            UPDATE log_sources
            SET enabled = ?,
                send_events = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_enabled,
                new_send_events,
                int(time.time()),
                row["id"],
            ),
        )

    return {"ok": True}


def get_directory_available_groups():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                name,
                builtin
            FROM groups
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()

    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "builtin": bool(row["builtin"]),
        }
        for row in rows
    ]


@app.get(
    "/api/v1/settings/authentication/ldap",
    dependencies=[
        Depends(
            require_permission(
                "settings.auth_manage"
            )
        )
    ],
)
def get_ldap_settings():
    encrypted_password = get_setting_text(
        "ldap_bind_password",
        "",
    )

    provider_type = get_setting_text(
        "ldap_provider_type",
        "ldap",
    )

    default_user_filter = (
        "(|(sAMAccountName={username})(userPrincipalName={username}))"
        if provider_type == "active_directory"
        else "(uid={username})"
    )

    default_username_attribute = (
        "sAMAccountName"
        if provider_type == "active_directory"
        else "uid"
    )

    return {
        "enabled": get_setting_bool(
            "ldap_enabled",
            False,
        ),
        "provider_type": get_setting_text(
            "ldap_provider_type",
            "ldap",
        ),
        "host": get_setting_text(
            "ldap_host",
            "",
        ),
        "port": get_setting_int(
            "ldap_port",
            389,
        ),
        "security": get_setting_text(
            "ldap_security",
            "plain",
        ),
        "base_dn": get_setting_text(
            "ldap_base_dn",
            "",
        ),
        "bind_dn": get_setting_text(
            "ldap_bind_dn",
            "",
        ),
        "bind_password_configured": bool(
            encrypted_password
        ),
        "user_search_base": get_setting_text(
            "ldap_user_search_base",
            "",
        ),
        "user_filter": get_setting_text(
            "ldap_user_filter",
            default_user_filter,
        ),
        "username_attribute": get_setting_text(
            "ldap_username_attribute",
            default_username_attribute,
        ),
        "group_mappings": json.loads(
            get_setting_text(
                "ldap_group_mappings",
                "{}",
            )
        ),
        "available_groups": get_directory_available_groups(),
    }


@app.put(
    "/api/v1/settings/authentication/ldap",
    dependencies=[
        Depends(
            require_permission(
                "settings.auth_manage"
            )
        )
    ],
)
def update_ldap_settings(
    settings: LDAPSettings,
):
    host = settings.host.strip()
    base_dn = settings.base_dn.strip()
    bind_dn = settings.bind_dn.strip()
    user_search_base = (
        settings.user_search_base.strip()
    )
    user_filter = settings.user_filter.strip()
    username_attribute = (
        settings.username_attribute.strip()
    )

    if settings.enabled:
        if not host:
            raise HTTPException(
                400,
                "LDAP host is required when LDAP is enabled",
            )

        if not base_dn:
            raise HTTPException(
                400,
                "LDAP Base DN is required when LDAP is enabled",
            )

        if not user_filter:
            raise HTTPException(
                400,
                "LDAP user filter is required",
            )

        if "{username}" not in user_filter:
            raise HTTPException(
                400,
                "LDAP user filter must contain {username}",
            )

        if not username_attribute:
            raise HTTPException(
                400,
                "LDAP username attribute is required",
            )

    group_mappings = {
        str(directory_group).strip(): int(group_id)
        for directory_group, group_id
        in settings.group_mappings.items()
        if str(directory_group).strip()
    }

    with db() as conn:
        if group_mappings:
            group_ids = sorted(set(group_mappings.values()))

            placeholders = ",".join(
                "?" for _ in group_ids
            )

            valid_group_ids = {
                int(row["id"])
                for row in conn.execute(
                    f"""
                    SELECT id
                    FROM groups
                    WHERE id IN ({placeholders})
                    """,
                    group_ids,
                ).fetchall()
            }

            if valid_group_ids != set(group_ids):
                raise HTTPException(
                    400,
                    "One or more FERPEK groups do not exist",
                )

    now = int(time.time())

    values = {
        "ldap_enabled": (
            "1" if settings.enabled else "0"
        ),
        "ldap_provider_type": settings.provider_type,
        "ldap_host": host,
        "ldap_port": str(settings.port),
        "ldap_security": settings.security,
        "ldap_base_dn": base_dn,
        "ldap_bind_dn": bind_dn,
        "ldap_user_search_base": user_search_base,
        "ldap_user_filter": user_filter,
        "ldap_username_attribute": username_attribute,
        "ldap_group_mappings": json.dumps(
            group_mappings,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }

    with db() as conn:
        for key, value in values.items():
            set_setting(
                conn,
                key,
                value,
                now,
            )

        if settings.clear_bind_password:
            conn.execute(
                """
                DELETE FROM settings
                WHERE key = 'ldap_bind_password'
                """
            )

        elif settings.bind_password is not None:
            password = settings.bind_password

            if password:
                set_setting(
                    conn,
                    "ldap_bind_password",
                    encrypt_secret(password),
                    now,
                )
            else:
                conn.execute(
                    """
                    DELETE FROM settings
                    WHERE key = 'ldap_bind_password'
                    """
                )

    return get_ldap_settings()


@app.post(
    "/api/v1/settings/authentication/ldap/test",
    dependencies=[
        Depends(
            require_permission(
                "settings.auth_manage"
            )
        )
    ],
)
def test_ldap_connection(
    settings: LDAPSettings,
):
    host = settings.host.strip()

    if not host:
        raise HTTPException(
            400,
            "LDAP host is required",
        )

    password = settings.bind_password

    if password is None:
        encrypted_password = get_setting_text(
            "ldap_bind_password",
            "",
        )

        if encrypted_password:
            try:
                password = decrypt_secret(
                    encrypted_password
                )
            except RuntimeError:
                raise HTTPException(
                    500,
                    "Could not read the stored LDAP bind password",
                )

    use_ssl = settings.security == "ldaps"

    tls = None

    if settings.security in {
        "starttls",
        "ldaps",
    }:
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=os.environ.get(
                "LDAP_CA_CERT"
            ),
        )

    server = Server(
        host,
        port=settings.port,
        use_ssl=use_ssl,
        tls=tls,
        get_info=NONE,
        connect_timeout=5,
    )

    connection = Connection(
        server,
        user=settings.bind_dn.strip() or None,
        password=password or None,
        receive_timeout=5,
        raise_exceptions=True,
    )

    stage = "connect"

    try:
        connection.open()

        if settings.security == "starttls":
            stage = "starttls"
            connection.start_tls()

        stage = "bind"
        connection.bind()

        base_dn = settings.base_dn.strip()

        if not base_dn:
            raise HTTPException(
                400,
                "Base DN is required.",
            )

        user_search_base = (
            settings.user_search_base.strip()
            or base_dn
        )

        user_filter = settings.user_filter.strip()

        if not user_filter:
            raise HTTPException(
                400,
                "User filter is required.",
            )

        if "{username}" not in user_filter:
            raise HTTPException(
                400,
                "User filter must contain {username}.",
            )

        username_attribute = (
            settings.username_attribute.strip()
        )

        if not username_attribute:
            raise HTTPException(
                400,
                "Username attribute is required.",
            )

        # Verify Base DN.
        stage = "base_dn"

        base_found = connection.search(
            search_base=base_dn,
            search_filter="(objectClass=*)",
            search_scope=BASE,
            attributes=["1.1"],
        )

        if not base_found:
            raise HTTPException(
                400,
                "Base DN was not found in the directory.",
            )

        # Verify user search base.
        stage = "user_search_base"

        search_base_found = connection.search(
            search_base=user_search_base,
            search_filter="(objectClass=*)",
            search_scope=BASE,
            attributes=["1.1"],
        )

        if not search_base_found:
            raise HTTPException(
                400,
                "User search base was not found in the directory.",
            )

        # Validate user-filter syntax.
        stage = "user_filter"

        test_filter = user_filter.replace(
            "{username}",
            "__ferpek_test__",
        )

        connection.search(
            search_base=user_search_base,
            search_filter=test_filter,
            search_scope=SUBTREE,
            attributes=[username_attribute],
        )

        return {
            "ok": True,
            "message": "LDAP configuration validated successfully.",
        }

    except HTTPException:
        raise

    except LDAPException as exc:
        print(
            "[FERPEK LDAP] "
            f"validation failed during {stage}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        messages = {
            "connect": (
                "Could not connect to the LDAP server. "
                "Check the host and port."
            ),
            "starttls": (
                "Could not establish StartTLS. "
                "Check the TLS configuration and certificate."
            ),
            "bind": (
                "LDAP bind failed. "
                "Check the Bind DN and Bind password."
            ),
            "base_dn": (
                "Base DN was not found in the directory."
            ),
            "user_search_base": (
                "User search base was not found in the directory."
            ),
            "user_filter": (
                "User filter is invalid or could not be "
                "evaluated by the directory."
            ),
        }

        raise HTTPException(
            400,
            messages.get(
                stage,
                "LDAP configuration validation failed.",
            ),
        )

    except OSError as exc:
        print(
            "[FERPEK LDAP] "
            f"connection error during {stage}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        raise HTTPException(
            400,
            "Could not connect to the LDAP server. "
            "Check the host and port.",
        )

    finally:
        try:
            connection.unbind()
        except Exception:
            pass


def sync_directory_user_groups(
    conn: sqlite3.Connection,
    user_id: int,
    directory_group_dns: list[str],
):
    provider_type = get_setting_text(
        "ldap_provider_type",
        "ldap",
    ).strip()

    if provider_type != "active_directory":
        return

    try:
        raw_mappings = json.loads(
            get_setting_text(
                "ldap_group_mappings",
                "{}",
            )
        )
    except (TypeError, ValueError):
        raw_mappings = {}

    if not isinstance(raw_mappings, dict):
        raw_mappings = {}

    normalized_memberships = {
        str(group_dn).strip().casefold()
        for group_dn in directory_group_dns
        if str(group_dn).strip()
    }

    desired_group_ids = set()

    for directory_group, group_id in raw_mappings.items():
        directory_group = str(
            directory_group
        ).strip()

        if not directory_group:
            continue

        if (
            directory_group.casefold()
            not in normalized_memberships
        ):
            continue

        try:
            desired_group_ids.add(int(group_id))
        except (TypeError, ValueError):
            continue

    # Do not trust stale/deleted FERPEK group IDs.
    if desired_group_ids:
        placeholders = ",".join(
            "?" for _ in desired_group_ids
        )

        valid_group_ids = {
            int(row["id"])
            for row in conn.execute(
                f"""
                SELECT id
                FROM groups
                WHERE id IN ({placeholders})
                """,
                tuple(sorted(desired_group_ids)),
            ).fetchall()
        }

        desired_group_ids &= valid_group_ids

    current_directory_group_ids = {
        int(row["group_id"])
        for row in conn.execute(
            """
            SELECT group_id
            FROM directory_user_groups
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    }

    groups_to_remove = (
        current_directory_group_ids
        - desired_group_ids
    )

    groups_to_add = (
        desired_group_ids
        - current_directory_group_ids
    )

    # Remove memberships that were previously managed by AD.
    for group_id in sorted(groups_to_remove):
        conn.execute(
            """
            DELETE FROM directory_user_groups
            WHERE user_id = ?
              AND group_id = ?
            """,
            (
                user_id,
                group_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM user_groups
            WHERE user_id = ?
              AND group_id = ?
            """,
            (
                user_id,
                group_id,
            ),
        )

    # Add memberships currently provided by AD.
    for group_id in sorted(groups_to_add):
        conn.execute(
            """
            INSERT OR IGNORE INTO user_groups
                (user_id, group_id)
            VALUES (?, ?)
            """,
            (
                user_id,
                group_id,
            ),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO directory_user_groups
                (user_id, group_id)
            VALUES (?, ?)
            """,
            (
                user_id,
                group_id,
            ),
        )


def authenticate_ldap_user(
    username: str,
    password: Optional[str],
):
    host = get_setting_text(
        "ldap_host",
        "",
    ).strip()

    port = get_setting_int(
        "ldap_port",
        389,
    )

    security = get_setting_text(
        "ldap_security",
        "plain",
    )

    base_dn = get_setting_text(
        "ldap_base_dn",
        "",
    ).strip()

    bind_dn = get_setting_text(
        "ldap_bind_dn",
        "",
    ).strip()

    user_search_base = get_setting_text(
        "ldap_user_search_base",
        "",
    ).strip() or base_dn

    provider_type = get_setting_text(
        "ldap_provider_type",
        "ldap",
    ).strip()

    default_user_filter = (
        "(|(sAMAccountName={username})(userPrincipalName={username}))"
        if provider_type == "active_directory"
        else "(uid={username})"
    )

    default_username_attribute = (
        "sAMAccountName"
        if provider_type == "active_directory"
        else "uid"
    )

    display_name_attribute = (
        "displayName"
        if provider_type == "active_directory"
        else "cn"
    )

    user_filter = get_setting_text(
        "ldap_user_filter",
        default_user_filter,
    ).strip()

    username_attribute = get_setting_text(
        "ldap_username_attribute",
        default_username_attribute,
    ).strip()

    search_attributes = [
        username_attribute,
        display_name_attribute,
        "mail",
    ]

    if provider_type == "active_directory":
        search_attributes.extend(
            [
                "memberOf",
                "userAccountControl",
            ]
        )

    encrypted_bind_password = get_setting_text(
        "ldap_bind_password",
        "",
    )

    if not host:
        raise RuntimeError(
            "LDAP server is not configured."
        )

    if not base_dn:
        raise RuntimeError(
            "LDAP Base DN is not configured."
        )

    if not user_search_base:
        raise RuntimeError(
            "LDAP User search base is not configured."
        )

    if "{username}" not in user_filter:
        raise RuntimeError(
            "LDAP User filter is not configured correctly."
        )

    if not username_attribute:
        raise RuntimeError(
            "LDAP Username attribute is not configured."
        )

    bind_password = ""

    if encrypted_bind_password:
        bind_password = decrypt_secret(
            encrypted_bind_password
        )

    tls = None

    if security in {
        "starttls",
        "ldaps",
    }:
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=os.environ.get(
                "LDAP_CA_CERT"
            ),
        )

    server = Server(
        host,
        port=port,
        use_ssl=security == "ldaps",
        tls=tls,
        get_info=NONE,
        connect_timeout=5,
    )

    directory_connection = Connection(
        server,
        user=bind_dn or None,
        password=bind_password or None,
        receive_timeout=5,
        raise_exceptions=True,
    )

    stage = "connect"

    try:
        directory_connection.open()

        if security == "starttls":
            stage = "starttls"
            directory_connection.start_tls()

        stage = "service_bind"
        directory_connection.bind()

        safe_username = escape_filter_chars(
            username.strip()
        )

        search_filter = user_filter.replace(
            "{username}",
            safe_username,
        )

        stage = "search"

        directory_connection.search(
            search_base=user_search_base,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=search_attributes,
            size_limit=2,
        )

        entries = list(
            directory_connection.entries
        )

        if len(entries) == 0:
            return None

        if len(entries) > 1:
            raise RuntimeError(
                "LDAP user search returned multiple entries."
            )

        entry = entries[0]
        user_dn = str(entry.entry_dn)

        def attribute_value(name: str) -> str:
            try:
                value = entry[name].value

                if value is None:
                    return ""

                return str(value)
            except Exception:
                return ""

        def attribute_values(name: str) -> list[str]:
            try:
                values = entry[name].values

                if not values:
                    return []

                return [
                    str(value)
                    for value in values
                    if value is not None
                ]
            except Exception:
                return []

        resolved_username = (
            attribute_value(username_attribute)
            or username.strip()
        )

        display_name = (
            attribute_value(display_name_attribute)
            or resolved_username
        )

        email = attribute_value("mail")

        directory_groups = (
            attribute_values("memberOf")
            if provider_type == "active_directory"
            else []
        )

        directory_enabled = True

        if provider_type == "active_directory":
            account_control = attribute_value(
                "userAccountControl"
            )

            try:
                directory_enabled = not (
                    int(account_control) & 2
                )
            except (TypeError, ValueError):
                directory_enabled = True

        directory_user = {
            "username": resolved_username,
            "display_name": display_name,
            "email": email,
            "dn": user_dn,
            "groups": directory_groups,
            "enabled": directory_enabled,
        }

    except LDAPException as exc:
        print(
            "[FERPEK LDAP] "
            f"user lookup failed during {stage}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        raise RuntimeError(
            "Could not search the LDAP directory."
        ) from exc

    finally:
        try:
            directory_connection.unbind()
        except Exception:
            pass

    if password is None:
        return directory_user

    if not directory_enabled:
        return None

    user_connection = Connection(
        server,
        user=user_dn,
        password=password,
        receive_timeout=5,
        raise_exceptions=True,
    )

    try:
        user_connection.open()

        if security == "starttls":
            user_connection.start_tls()

        user_connection.bind()

    except LDAPException as exc:
        print(
            "[FERPEK LDAP] "
            "user bind failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return None

    finally:
        try:
            user_connection.unbind()
        except Exception:
            pass

    return directory_user


@app.post(
    "/api/v1/settings/authentication/ldap/test-user",
    dependencies=[
        Depends(
            require_permission(
                "settings.auth_manage"
            )
        )
    ],
)
def test_ldap_user(
    payload: LDAPTestUserRequest,
):
    username = payload.username.strip()

    if not username:
        raise HTTPException(
            400,
            "Username is required.",
        )

    try:
        user = authenticate_ldap_user(
            username,
            payload.password,
        )

    except RuntimeError as exc:
        raise HTTPException(
            400,
            str(exc),
        )

    if user is None:
        raise HTTPException(
            401,
            "User was not found or the password is incorrect.",
        )

    return {
        "ok": True,
        "message": "LDAP user authentication successful.",
        "user": user,
    }


@app.get("/api/v1/settings/packs", dependencies=[Depends(require_permission("settings.view"))])
def get_pack_settings():
    return {
        "allow_community_packs": get_setting_bool(
            "allow_community_packs",
            False,
        ),
        "allow_local_packs": get_setting_bool(
            "allow_local_packs",
            True,
        ),
    }


@app.put("/api/v1/settings/packs", dependencies=[Depends(require_permission("settings.manage"))])
def update_pack_settings(
    settings: PackSettings,
):
    now = int(time.time())

    values = {
        "allow_community_packs": (
            "1" if settings.allow_community_packs else "0"
        ),
        "allow_local_packs": (
            "1" if settings.allow_local_packs else "0"
        ),
    }

    with db() as conn:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO settings
                    (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    value,
                    now,
                ),
            )

    return {
        "ok": True,
        **settings.model_dump(),
    }


@app.get("/api/v1/settings/retention", dependencies=[Depends(require_permission("settings.view"))])
def get_retention_settings():
    return {
        "event_retention_days": get_setting_int(
            "event_retention_days",
            EVENT_RETENTION_DAYS,
        ),
        "relevant_retention_days": get_setting_int(
            "relevant_retention_days",
            30,
        ),
        "resolved_finding_retention_days": get_setting_int(
            "resolved_finding_retention_days",
            RESOLVED_FINDING_RETENTION_DAYS,
        ),
    }


@app.put("/api/v1/settings/retention", dependencies=[Depends(require_permission("settings.manage"))])
def update_retention_settings(
    settings: RetentionSettings,
):
    now = int(time.time())

    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings
                (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                "event_retention_days",
                str(settings.event_retention_days),
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO settings
                (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                "relevant_retention_days",
                str(settings.relevant_retention_days),
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO settings
                (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                "resolved_finding_retention_days",
                str(
                    settings.resolved_finding_retention_days
                ),
                now,
            ),
        )

    return {
        "ok": True,
        "event_retention_days": (
            settings.event_retention_days
        ),
        "relevant_retention_days": (
            settings.relevant_retention_days
        ),
        "resolved_finding_retention_days": (
            settings.resolved_finding_retention_days
        ),
    }


# ---------------------------------------------------------------------------
# Relevant events / Activity
# ---------------------------------------------------------------------------

@app.post("/api/v1/relevant")
def post_relevant_events(
    batch: RelevantEventsBatch,
    agent: dict = Depends(get_agent),
):
    now = int(time.time())

    stored = 0
    duplicates = 0

    with db() as conn:
        for event in batch.events:
            severity_value = event.severity.strip().lower()

            severity_aliases = {
                "crit": "critical",
                "critical": "critical",
                "warn": "warning",
                "warning": "warning",
                "info": "info",
                "informational": "info",
            }

            severity = severity_aliases.get(
                severity_value,
                severity_value,
            )

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO relevant_events
                    (
                        agent_id,
                        event_id,
                        source_key,
                        event_time,
                        pack_id,
                        rule_id,
                        service,
                        severity,
                        title,
                        detail,
                        fields,
                        source_message,
                        received_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent["id"],
                    event.event_id,
                    event.source_key,
                    event.timestamp,
                    event.pack_id,
                    event.rule_id,
                    event.service,
                    severity,
                    event.title,
                    event.detail,
                    json.dumps(
                        event.fields,
                        separators=(",", ":"),
                    ),
                    event.source_message,
                    now,
                ),
            )

            if cursor.rowcount == 0:
                duplicates += 1
            else:
                stored += 1

    return {
        "received": len(batch.events),
        "stored": stored,
        "duplicates": duplicates,
    }


@app.get("/api/v1/relevant", dependencies=[Depends(require_permission("logs.view"))])
def list_relevant_events(
    agent_id: Optional[int] = None,
    source: Optional[str] = None,
    service: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    query = """
        SELECT
            relevant_events.*,
            agents.hostname
        FROM relevant_events
        JOIN agents
          ON agents.id = relevant_events.agent_id
        WHERE 1 = 1
    """

    params = []

    if agent_id is not None:
        query += " AND relevant_events.agent_id = ?"
        params.append(agent_id)

    if source:
        query += " AND relevant_events.source_key = ?"
        params.append(source)

    if service:
        query += " AND LOWER(relevant_events.service) = LOWER(?)"
        params.append(service)

    if severity:
        query += " AND LOWER(relevant_events.severity) = LOWER(?)"
        params.append(severity)

    if since is not None:
        query += " AND relevant_events.event_time >= ?"
        params.append(since)

    if until is not None:
        query += " AND relevant_events.event_time <= ?"
        params.append(until)

    if search:
        query += """
            AND (
                relevant_events.title LIKE ?
                OR relevant_events.detail LIKE ?
                OR relevant_events.source_message LIKE ?
                OR agents.hostname LIKE ?
            )
        """
        search_value = f"%{search}%"
        params.extend([
            search_value,
            search_value,
            search_value,
            search_value,
        ])

    query += """
        ORDER BY relevant_events.event_time DESC
        LIMIT ?
    """
    params.append(limit)

    with db() as conn:
        rows = conn.execute(
            query,
            params,
        ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Events / Log Explorer
# ---------------------------------------------------------------------------

@app.post("/api/v1/events")
def post_events(
    batch: EventsBatch,
    agent: dict = Depends(get_agent),
):
    now = int(time.time())

    accepted = 0
    duplicates = 0

    with db() as conn:
        configured_sources = {
            row["source_key"]: bool(row["send_events"])
            for row in conn.execute(
                """
                SELECT source_key, send_events
                FROM log_sources
                WHERE agent_id = ?
                """,
                (agent["id"],),
            ).fetchall()
        }

        for event in batch.events:
            if not configured_sources.get(
                event.source_key,
                False,
            ):
                continue

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO events
                    (
                        agent_id,
                        event_id,
                        source_key,
                        event_time,
                        service,
                        severity,
                        message,
                        metadata,
                        received_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent["id"],
                    event.event_id,
                    event.source_key,
                    event.timestamp,
                    event.service,
                    event.severity,
                    event.message,
                    event.metadata,
                    now,
                ),
            )

            if cursor.rowcount == 0:
                duplicates += 1
            else:
                accepted += 1

    return {
        "received": len(batch.events),
        "stored": accepted,
        "duplicates": duplicates,
    }


@app.get("/api/v1/events", dependencies=[Depends(require_permission("logs.view"))])
def list_events(
    agent_id: Optional[int] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    query = """
        SELECT
            events.*,
            agents.hostname
        FROM events
        JOIN agents ON agents.id = events.agent_id
        WHERE 1 = 1
    """

    params = []

    if agent_id is not None:
        query += " AND events.agent_id = ?"
        params.append(agent_id)

    if source:
        query += " AND events.source_key = ?"
        params.append(source)

    if search:
        query += " AND events.message LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY events.event_time DESC LIMIT ?"
    params.append(limit)

    with db() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@app.post("/api/v1/findings")
def post_findings(
    batch: FindingsBatch,
    agent: dict = Depends(get_agent),
):
    now = int(time.time())

    created = 0
    updated = 0
    duplicates = 0

    with db() as conn:
        for finding in batch.findings:
            if finding.detection_id:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO finding_detections
                        (
                            agent_id,
                            detection_id,
                            finding_id,
                            received_at
                        )
                    VALUES (?, ?, NULL, ?)
                    """,
                    (
                        agent["id"],
                        finding.detection_id,
                        now,
                    ),
                )

                if cursor.rowcount == 0:
                    duplicates += 1
                    continue

            severity_value = finding.severity.strip().lower()

            severity_aliases = {
                "crit": "critical",
                "critical": "critical",
                "warn": "warning",
                "warning": "warning",
                "info": "info",
                "informational": "info",
            }

            severity = severity_aliases.get(
                severity_value,
                severity_value,
            )

            existing = conn.execute(
                """
                SELECT id
                FROM findings
                WHERE agent_id = ?
                  AND pattern_id = ?
                  AND group_key = ?
                  AND status = 'open'
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    agent["id"],
                    finding.pattern_id,
                    finding.group_key,
                ),
            ).fetchone()

            if existing:
                finding_id = existing["id"]

                conn.execute(
                    """
                    UPDATE findings
                    SET
                        service = ?,
                        severity = ?,
                        title = ?,
                        detail = ?,
                        suggest = ?,
                        source_line = ?,
                        last_seen = ?,
                        received_at = ?,
                        detection_count = detection_count + 1
                    WHERE id = ?
                    """,
                    (
                        finding.service,
                        severity,
                        finding.title,
                        finding.detail,
                        finding.suggest,
                        finding.source_line,
                        now,
                        now,
                        finding_id,
                    ),
                )

                updated += 1

            else:
                cursor = conn.execute(
                    """
                    INSERT INTO findings
                        (
                            agent_id,
                            pattern_id,
                            group_key,
                            service,
                            severity,
                            title,
                            detail,
                            suggest,
                            source_line,
                            received_at,
                            first_seen,
                            last_seen,
                            detection_count
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        agent["id"],
                        finding.pattern_id,
                        finding.group_key,
                        finding.service,
                        severity,
                        finding.title,
                        finding.detail,
                        finding.suggest,
                        finding.source_line,
                        now,
                        now,
                        now,
                    ),
                )

                finding_id = cursor.lastrowid
                created += 1

            if finding.detection_id:
                conn.execute(
                    """
                    UPDATE finding_detections
                    SET finding_id = ?
                    WHERE agent_id = ?
                      AND detection_id = ?
                    """,
                    (
                        finding_id,
                        agent["id"],
                        finding.detection_id,
                    ),
                )

    return {
        "received": len(batch.findings),
        "created": created,
        "updated": updated,
        "duplicates": duplicates,
    }


@app.get("/api/v1/findings", dependencies=[Depends(require_permission("findings.view"))])
def list_findings(
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    query = """
        SELECT
            findings.*,
            agents.hostname
        FROM findings
        JOIN agents ON agents.id = findings.agent_id
        WHERE 1 = 1
    """

    params = []

    if status:
        query += " AND findings.status = ?"
        params.append(status)

    if agent_id is not None:
        query += " AND findings.agent_id = ?"
        params.append(agent_id)

    query += " ORDER BY received_at DESC LIMIT ?"
    params.append(limit)

    with db() as conn:
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


@app.post("/api/v1/findings/{finding_id}/resolve", dependencies=[Depends(require_permission("findings.resolve"))])
def resolve_finding(finding_id: int):
    now = int(time.time())

    with db() as conn:
        result = conn.execute(
            """
            UPDATE findings
            SET
                status = 'resolved',
                resolved_at = COALESCE(resolved_at, ?)
            WHERE id = ?
            """,
            (
                now,
                finding_id,
            ),
        )

        if result.rowcount == 0:
            raise HTTPException(404, "Finding não encontrado")

    return {
        "ok": True,
        "resolved_at": now,
    }


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

@app.get("/api/v1/agents", dependencies=[Depends(require_permission("hosts.view"))])
def list_agents():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                agents.id,
                agents.hostname,
                agents.enrolled_at,
                agents.last_seen,
                agents.os_name,
                agents.os_version,
                agents.agent_version,
                agents.machine_type,

                SUM(
                    CASE
                        WHEN findings.status = 'open'
                         AND findings.severity = 'critical'
                        THEN 1 ELSE 0
                    END
                ) AS critical_count,

                SUM(
                    CASE
                        WHEN findings.status = 'open'
                         AND findings.severity = 'warning'
                        THEN 1 ELSE 0
                    END
                ) AS warning_count

            FROM agents

            LEFT JOIN findings
                ON findings.agent_id = agents.id

            GROUP BY agents.id
            ORDER BY agents.hostname
            """
        ).fetchall()

    return [dict(row) for row in rows]
@app.delete("/api/v1/agents/{agent_id}", dependencies=[Depends(require_permission("hosts.delete"))])
def delete_agent(agent_id: int):
    with db() as conn:
        agent = conn.execute(
            """
            SELECT id, hostname
            FROM agents
            WHERE id = ?
            """,
            (agent_id,),
        ).fetchone()

        if not agent:
            raise HTTPException(404, "Host não encontrado")

        # Remove all data belonging to this host.
        conn.execute(
            "DELETE FROM events WHERE agent_id = ?",
            (agent_id,),
        )

        conn.execute(
            "DELETE FROM relevant_events WHERE agent_id = ?",
            (agent_id,),
        )

        conn.execute(
            "DELETE FROM finding_detections WHERE agent_id = ?",
            (agent_id,),
        )

        conn.execute(
            "DELETE FROM findings WHERE agent_id = ?",
            (agent_id,),
        )

        conn.execute(
            "DELETE FROM log_sources WHERE agent_id = ?",
            (agent_id,),
        )

        # Keep historical enrollment tokens, but remove their link
        # to a host that no longer exists.
        conn.execute(
            """
            UPDATE enrollment_tokens
            SET agent_id = NULL
            WHERE agent_id = ?
            """,
            (agent_id,),
        )

        conn.execute(
            "DELETE FROM agents WHERE id = ?",
            (agent_id,),
        )

    return {
        "ok": True,
        "deleted_agent_id": agent_id,
        "hostname": agent["hostname"],
    }



def read_pack_manifest(pack_dir: Path):
    manifest_path = pack_dir / "manifest.yaml"

    if not manifest_path.is_file():
        return None

    try:
        manifest = yaml.safe_load(
            manifest_path.read_text(
                encoding="utf-8"
            )
        ) or {}
    except Exception as exc:
        raise HTTPException(
            500,
            f"Invalid pack manifest {pack_dir.name}: {exc}",
        )

    pack_id = manifest.get("id")
    version = manifest.get("version")

    if not pack_id or not version:
        raise HTTPException(
            500,
            f"Pack {pack_dir.name} has no id or version",
        )

    return manifest


def is_pack_enabled(pack_id: str) -> bool:
    try:
        with db() as conn:
            row = conn.execute(
                '''
                SELECT enabled
                FROM pack_states
                WHERE pack_id = ?
                ''',
                (pack_id,),
            ).fetchone()

        if row is None:
            return True

        return bool(row["enabled"])

    except sqlite3.Error:
        return True


def is_pack_allowed(manifest: dict) -> bool:
    origin = str(
        manifest.get("origin", "local")
    ).strip().lower()

    if origin == "official":
        return True

    if origin == "community":
        return get_setting_bool(
            "allow_community_packs",
            False,
        )

    if origin in {
        "local",
        "private",
    }:
        return get_setting_bool(
            "allow_local_packs",
            True,
        )

    # Unknown origins are treated conservatively
    # as local/private packs.
    return get_setting_bool(
        "allow_local_packs",
        True,
    )



def version_matches(
    version: str,
    requirement: str,
) -> bool:
    if not requirement:
        return True

    try:
        return Version(version) in SpecifierSet(requirement)
    except (
        InvalidVersion,
        ValueError,
    ):
        return False


def get_pack_compatibility(manifest: dict) -> dict:
    compatibility = manifest.get(
        "compatibility",
        {},
    )

    if not isinstance(compatibility, dict):
        return {}

    return compatibility


def is_pack_server_compatible(
    manifest: dict,
) -> bool:
    compatibility = get_pack_compatibility(
        manifest
    )

    requirement = str(
        compatibility.get("server", "")
    ).strip()

    return version_matches(
        SERVER_VERSION,
        requirement,
    )


def is_pack_agent_compatible(
    manifest: dict,
    agent_version: str,
) -> bool:
    compatibility = get_pack_compatibility(
        manifest
    )

    requirement = str(
        compatibility.get("agent", "")
    ).strip()

    if not requirement:
        return True

    if not agent_version:
        return False

    return version_matches(
        agent_version,
        requirement,
    )




def is_pack_platform_compatible(
    manifest: dict,
    agent_platform: str,
) -> bool:
    platforms = manifest.get("platforms")

    if platforms is None:
        return True

    if not isinstance(platforms, dict):
        return False

    normalized = str(
        agent_platform or ""
    ).strip().lower()

    # Keep compatibility with agents that have not
    # reported their platform yet.
    if not normalized:
        return True

    return normalized in {
        str(name).strip().lower()
        for name in platforms
    }


def validate_pack_rule(rule: dict, rule_name: str):
    if not isinstance(rule, dict):
        raise HTTPException(
            400,
            f"{rule_name} must contain a YAML object",
        )

    rule_id = str(rule.get("id", "")).strip()

    if not rule_id:
        raise HTTPException(
            400,
            f"{rule_name} has no id",
        )

    sources = rule.get("sources", [])
    source_family = rule.get("source_family")

    if not sources and not source_family:
        raise HTTPException(
            400,
            f"{rule_id}: no sources or source_family configured",
        )

    if sources and not isinstance(sources, list):
        raise HTTPException(
            400,
            f"{rule_id}: sources must be a list",
        )

    match = rule.get("match")

    if not isinstance(match, dict):
        raise HTTPException(
            400,
            f"{rule_id}: match must be an object",
        )

    pattern = match.get("regex")

    if not pattern:
        raise HTTPException(
            400,
            f"{rule_id}: match.regex missing",
        )

    try:
        re.compile(str(pattern))
    except re.error as exc:
        raise HTTPException(
            400,
            f"{rule_id}: invalid regex: {exc}",
        )

    relevant = rule.get("relevant")

    if relevant is not None and not isinstance(
        relevant,
        dict,
    ):
        raise HTTPException(
            400,
            f"{rule_id}: relevant must be an object",
        )

    finding = rule.get("finding")

    if finding is not None and not isinstance(
        finding,
        dict,
    ):
        raise HTTPException(
            400,
            f"{rule_id}: finding must be an object",
        )

    aggregate = rule.get("aggregate")

    if aggregate is not None:
        if not isinstance(aggregate, dict):
            raise HTTPException(
                400,
                f"{rule_id}: aggregate must be an object",
            )

        for field in (
            "threshold",
            "window_seconds",
            "cooldown_seconds",
        ):
            if field not in aggregate:
                continue

            try:
                value = int(aggregate[field])
            except (TypeError, ValueError):
                raise HTTPException(
                    400,
                    f"{rule_id}: aggregate.{field} must be an integer",
                )

            if value < 0:
                raise HTTPException(
                    400,
                    f"{rule_id}: aggregate.{field} cannot be negative",
                )

        if (
            "threshold" in aggregate
            and int(aggregate["threshold"]) < 1
        ):
            raise HTTPException(
                400,
                f"{rule_id}: aggregate.threshold must be at least 1",
            )


def validate_pack_platforms(platforms: dict):
    if not isinstance(platforms, dict):
        raise HTTPException(
            400,
            "Pack platforms must be an object",
        )

    if not platforms:
        raise HTTPException(
            400,
            "Pack platforms cannot be empty",
        )

    supported_platforms = {
        "linux",
        "windows",
        "freebsd",
    }

    field_types = {
        "text",
        "path",
        "number",
        "boolean",
        "select",
        "secret",
    }

    for platform_name, platform in platforms.items():
        platform_name = str(platform_name).strip().lower()

        if platform_name not in supported_platforms:
            raise HTTPException(
                400,
                f"Unsupported pack platform: {platform_name}",
            )

        if not isinstance(platform, dict):
            raise HTTPException(
                400,
                f"Platform {platform_name} must be an object",
            )

        sources = platform.get("sources")

        if not isinstance(sources, list) or not sources:
            raise HTTPException(
                400,
                f"Platform {platform_name} requires sources",
            )

        source_ids = set()

        for source in sources:
            if not isinstance(source, dict):
                raise HTTPException(
                    400,
                    f"Platform {platform_name} sources must be objects",
                )

            source_id = str(
                source.get("id", "")
            ).strip()

            if not source_id:
                raise HTTPException(
                    400,
                    f"Platform {platform_name} source requires id",
                )

            if source_id in source_ids:
                raise HTTPException(
                    400,
                    (
                        f"Duplicate source id {source_id} "
                        f"in platform {platform_name}"
                    ),
                )

            source_ids.add(source_id)

            family = source.get("family")

            if family is not None:
                if (
                    not isinstance(family, str)
                    or not family.strip()
                ):
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id} "
                            "family must be a non-empty string"
                        ),
                    )

            discovery = source.get(
                "discovery",
                [],
            )

            if discovery is not None:
                if not isinstance(discovery, list):
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id} "
                            "discovery must be a list"
                        ),
                    )

                for entry in discovery:
                    if not isinstance(entry, dict):
                        raise HTTPException(
                            400,
                            (
                                f"{platform_name}.{source_id} "
                                "discovery entries must be objects"
                            ),
                        )

                    discovery_type = str(
                        entry.get("type", "")
                    ).strip().lower()

                    if discovery_type not in {
                        "file",
                        "journal",
                    }:
                        raise HTTPException(
                            400,
                            (
                                f"{platform_name}.{source_id} "
                                "discovery type must be "
                                "file or journal"
                            ),
                        )

                    if discovery_type == "file":
                        paths = entry.get("paths")

                        if (
                            not isinstance(paths, list)
                            or not paths
                            or not all(
                                isinstance(item, str)
                                and item.strip()
                                for item in paths
                            )
                        ):
                            raise HTTPException(
                                400,
                                (
                                    f"{platform_name}.{source_id} "
                                    "file discovery requires paths"
                                ),
                            )

                    if discovery_type == "journal":
                        units = entry.get("units")

                        if (
                            not isinstance(units, list)
                            or not units
                            or not all(
                                isinstance(item, str)
                                and item.strip()
                                for item in units
                            )
                        ):
                            raise HTTPException(
                                400,
                                (
                                    f"{platform_name}.{source_id} "
                                    "journal discovery requires units"
                                ),
                            )

            manual = source.get("manual")

            if manual is None:
                continue

            if not isinstance(manual, dict):
                raise HTTPException(
                    400,
                    (
                        f"{platform_name}.{source_id} "
                        "manual must be an object"
                    ),
                )

            fields = manual.get(
                "fields",
                [],
            )

            if not isinstance(fields, list):
                raise HTTPException(
                    400,
                    (
                        f"{platform_name}.{source_id} "
                        "manual.fields must be a list"
                    ),
                )

            field_ids = set()

            for field in fields:
                if not isinstance(field, dict):
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id} "
                            "manual fields must be objects"
                        ),
                    )

                field_id = str(
                    field.get("id", "")
                ).strip()

                label = str(
                    field.get("label", "")
                ).strip()

                field_type = str(
                    field.get("type", "")
                ).strip().lower()

                if not field_id or not label:
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id} "
                            "manual field requires id and label"
                        ),
                    )

                if field_id in field_ids:
                    raise HTTPException(
                        400,
                        (
                            f"Duplicate manual field id "
                            f"{field_id}"
                        ),
                    )

                field_ids.add(field_id)

                if field_type not in field_types:
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id} "
                            f"invalid field type: {field_type}"
                        ),
                    )

                if (
                    "required" in field
                    and not isinstance(
                        field["required"],
                        bool,
                    )
                ):
                    raise HTTPException(
                        400,
                        (
                            f"{platform_name}.{source_id}."
                            f"{field_id} required must be boolean"
                        ),
                    )

                if field_type == "select":
                    options = field.get("options")

                    if (
                        not isinstance(options, list)
                        or not options
                        or not all(
                            isinstance(item, str)
                            and item.strip()
                            for item in options
                        )
                    ):
                        raise HTTPException(
                            400,
                            (
                                f"{platform_name}.{source_id}."
                                f"{field_id} select requires options"
                            ),
                        )


def validate_pack_manifest(manifest: dict):
    if not isinstance(manifest, dict):
        raise HTTPException(
            400,
            "manifest.yaml must contain a YAML object",
        )

    pack_id = str(
        manifest.get("id", "")
    ).strip()

    name = str(
        manifest.get("name", "")
    ).strip()

    version = str(
        manifest.get("version", "")
    ).strip()

    if not pack_id:
        raise HTTPException(
            400,
            "Pack manifest requires id",
        )

    if not name:
        raise HTTPException(
            400,
            "Pack manifest requires name",
        )

    if not version:
        raise HTTPException(
            400,
            "Pack manifest requires version",
        )

    if not all(
        char.isalnum() or char in {"-", "_"}
        for char in pack_id
    ):
        raise HTTPException(
            400,
            "Pack id may contain only letters, numbers, - and _",
        )

    try:
        Version(version)
    except InvalidVersion:
        raise HTTPException(
            400,
            f"Invalid pack version: {version}",
        )

    origin = str(
        manifest.get("origin", "local")
    ).strip().lower()

    if origin not in {
        "official",
        "community",
        "local",
        "private",
    }:
        raise HTTPException(
            400,
            "Pack origin must be one of: "
            "official, community, local, private",
        )

    category = manifest.get("category")

    if not isinstance(category, dict):
        raise HTTPException(
            400,
            "Pack category must be an object",
        )

    category_id = str(
        category.get("id", "")
    ).strip()

    category_label = str(
        category.get("label", "")
    ).strip()

    if not category_id or not category_label:
        raise HTTPException(
            400,
            "Pack category requires id and label",
        )

    sources = manifest.get("sources")
    platforms = manifest.get("platforms")

    if sources is None and platforms is None:
        raise HTTPException(
            400,
            "Pack requires sources or platforms",
        )

    if sources is not None:
        if not isinstance(sources, list):
            raise HTTPException(
                400,
                "Pack sources must be a list",
            )

        if not sources:
            raise HTTPException(
                400,
                "Pack sources cannot be empty",
            )

        if not all(
            isinstance(source, str) and source.strip()
            for source in sources
        ):
            raise HTTPException(
                400,
                (
                    "Pack sources must contain only "
                    "non-empty strings"
                ),
            )

    if platforms is not None:
        validate_pack_platforms(
            platforms
        )

    compatibility = manifest.get("compatibility")

    if not isinstance(compatibility, dict):
        raise HTTPException(
            400,
            "Pack compatibility must be an object",
        )

    for target in ("server", "agent"):
        requirement = compatibility.get(target)

        if requirement is None:
            continue

        if not isinstance(requirement, str):
            raise HTTPException(
                400,
                f"Pack compatibility.{target} must be a string",
            )

        try:
            SpecifierSet(requirement)
        except ValueError:
            raise HTTPException(
                400,
                f"Invalid compatibility.{target}: {requirement}",
            )

    for field in (
        "author",
        "description",
    ):
        value = manifest.get(field)

        if value is not None and not isinstance(value, str):
            raise HTTPException(
                400,
                f"Pack {field} must be a string",
            )

    return pack_id, version


class PackFilesPayload(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)


class PackStatePayload(BaseModel):
    enabled: bool


def validate_pack_directory(pack_dir: Path):
    manifest_path = pack_dir / "manifest.yaml"

    if not manifest_path.is_file():
        raise HTTPException(
            400,
            "Pack must contain manifest.yaml",
        )

    try:
        manifest = yaml.safe_load(
            manifest_path.read_text(
                encoding="utf-8"
            )
        ) or {}
    except Exception as exc:
        raise HTTPException(
            400,
            f"Invalid manifest.yaml: {exc}",
        )

    pack_id, version = validate_pack_manifest(
        manifest
    )

    rules_dir = pack_dir / "rules"
    rule_ids = set()

    if rules_dir.is_dir():
        for rule_path in sorted(
            list(rules_dir.glob("*.yaml"))
            + list(rules_dir.glob("*.yml"))
        ):
            try:
                rule = yaml.safe_load(
                    rule_path.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception as exc:
                raise HTTPException(
                    400,
                    f"Invalid YAML file "
                    f"{rule_path.name}: {exc}",
                )

            validate_pack_rule(
                rule,
                f"rules/{rule_path.name}",
            )

            rule_id = str(
                rule.get("id", "")
            ).strip()

            if not rule_id.startswith(f"{pack_id}."):
                raise HTTPException(
                    400,
                    f"Rule id must start with {pack_id}.: {rule_id}",
                )

            if rule_id in rule_ids:
                raise HTTPException(
                    400,
                    f"Duplicate rule id: {rule_id}",
                )

            rule_ids.add(rule_id)

    if not is_pack_server_compatible(
        manifest
    ):
        raise HTTPException(
            400,
            f"Pack {pack_id} {version} is not compatible "
            f"with FERPEK Server {SERVER_VERSION}",
        )

    return manifest


def validate_pack_archive(archive_path: Path):
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except zipfile.BadZipFile:
        raise HTTPException(400, "Invalid .pack archive")

    with archive:
        members = archive.infolist()

        if not members:
            raise HTTPException(400, "Pack archive is empty")

        for member in members:
            name = member.filename

            path = Path(name)

            if path.is_absolute() or ".." in path.parts:
                raise HTTPException(
                    400,
                    f"Unsafe path in pack: {name}",
                )

            mode = (member.external_attr >> 16) & 0o170000

            if mode == 0o120000:
                raise HTTPException(
                    400,
                    f"Symlinks are not allowed in packs: {name}",
                )

        names = {
            member.filename.rstrip("/")
            for member in members
            if not member.is_dir()
        }

        if "manifest.yaml" not in names:
            raise HTTPException(
                400,
                "Pack must contain manifest.yaml at archive root",
            )

        try:
            manifest = yaml.safe_load(
                archive.read("manifest.yaml").decode("utf-8")
            ) or {}
        except Exception as exc:
            raise HTTPException(
                400,
                f"Invalid manifest.yaml: {exc}",
            )

        pack_id, version = validate_pack_manifest(
            manifest
        )

        for name in sorted(names):
            if not name.endswith(".yaml"):
                continue

            try:
                document = yaml.safe_load(
                    archive.read(name).decode("utf-8")
                )
            except Exception as exc:
                raise HTTPException(
                    400,
                    f"Invalid YAML file {name}: {exc}",
                )

            if name.startswith("rules/"):
                validate_pack_rule(
                    document,
                    name,
                )

                rule_id = str(
                    document.get("id", "")
                ).strip()

                if not rule_id.startswith(
                    f"{pack_id}."
                ):
                    raise HTTPException(
                        400,
                        f"Rule id must start with {pack_id}.: {rule_id}",
                    )

        return manifest


def iter_pack_dirs():
    if not INSTALLED_PACKS_PATH.exists():
        return

    for pack_dir in sorted(INSTALLED_PACKS_PATH.iterdir()):
        if not pack_dir.is_dir():
            continue

        if pack_dir.is_symlink():
            continue

        if pack_dir.name.startswith("."):
            continue

        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        pack_id = manifest.get("id")

        if not pack_id:
            continue

        yield pack_dir


def get_pack_dir(pack_id: str) -> Path:
    pack_id = str(pack_id).strip()

    if not pack_id:
        raise HTTPException(
            400,
            "Pack id is required",
        )

    if not all(
        char.isalnum() or char in {"-", "_"}
        for char in pack_id
    ):
        raise HTTPException(
            400,
            "Invalid pack id",
        )

    for pack_dir in iter_pack_dirs():
        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        if str(manifest.get("id", "")).strip() == pack_id:
            return pack_dir

    raise HTTPException(
        404,
        f"Pack {pack_id} not found",
    )


@app.get("/api/v1/packs/{pack_id}/files", dependencies=[Depends(require_permission("packs.view"))])
def list_pack_files(pack_id: str):
    # Future permission:
    # packs.read

    pack_dir = get_pack_dir(pack_id)

    files = []

    for file_path in sorted(pack_dir.rglob("*")):
        if not file_path.is_file():
            continue

        if file_path.is_symlink():
            continue

        relative = file_path.relative_to(pack_dir)

        if relative.name.startswith("."):
            continue

        if relative.suffix not in {".yaml", ".yml"}:
            continue

        files.append(str(relative))

    return {
        "id": pack_id,
        "files": files,
    }


@app.get("/api/v1/packs/{pack_id}/files/{file_path:path}", dependencies=[Depends(require_permission("packs.view"))])
def read_pack_file(pack_id: str, file_path: str):
    # Future permission:
    # packs.read

    pack_dir = get_pack_dir(pack_id)

    requested = Path(file_path)

    if requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(
            400,
            "Invalid pack file path",
        )

    target = (pack_dir / requested).resolve()

    try:
        target.relative_to(pack_dir.resolve())
    except ValueError:
        raise HTTPException(
            400,
            "Invalid pack file path",
        )

    if not target.is_file():
        raise HTTPException(
            404,
            "Pack file not found",
        )

    if target.is_symlink():
        raise HTTPException(
            400,
            "Symlinked pack files are not allowed",
        )

    if target.suffix not in {".yaml", ".yml"}:
        raise HTTPException(
            400,
            "Only YAML pack files may be read",
        )

    try:
        content = target.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError:
        raise HTTPException(
            400,
            "Pack file is not valid UTF-8",
        )

    return {
        "id": pack_id,
        "path": str(requested),
        "content": content,
    }


@app.put("/api/v1/packs/{pack_id}/files", dependencies=[Depends(require_permission("packs.manage"))])
def save_pack_changes(
    pack_id: str,
    payload: PackFilesPayload,
):
    # Future permission:
    # packs.edit

    source_pack_dir = get_pack_dir(pack_id)
    source_manifest = read_pack_manifest(source_pack_dir)

    if source_manifest is None:
        raise HTTPException(
            400,
            "Pack manifest not found",
        )

    source_origin = str(
        source_manifest.get("origin", "local")
    ).strip().lower()

    if not payload.files:
        raise HTTPException(
            400,
            "No pack files supplied",
        )

    INSTALLED_PACKS_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".save-{pack_id}-",
            dir=INSTALLED_PACKS_PATH,
        )
    )

    backup_dir = None

    try:
        for source in source_pack_dir.rglob("*"):
            if not source.is_file():
                continue

            if source.is_symlink():
                continue

            relative = source.relative_to(
                source_pack_dir
            )

            destination = (
                staging_dir / relative
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )

        for file_path, content in payload.files.items():
            requested = Path(file_path)

            if (
                requested.is_absolute()
                or ".." in requested.parts
            ):
                raise HTTPException(
                    400,
                    "Invalid pack file path",
                )

            if requested.suffix not in {
                ".yaml",
                ".yml",
            }:
                raise HTTPException(
                    400,
                    "Only YAML pack files may be edited",
                )

            target = (
                staging_dir / requested
            ).resolve()

            try:
                target.relative_to(
                    staging_dir.resolve()
                )
            except ValueError:
                raise HTTPException(
                    400,
                    "Invalid pack file path",
                )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                content,
                encoding="utf-8",
            )

        manifest = validate_pack_directory(
            staging_dir
        )

        if str(manifest["id"]).strip() != pack_id:
            raise HTTPException(
                400,
                "Pack id cannot be changed",
            )

        origin = str(
            manifest.get("origin", "local")
        ).strip().lower()

        if origin != source_origin:
            raise HTTPException(
                400,
                "Pack origin cannot be changed",
            )

        destination = (
            INSTALLED_PACKS_PATH / pack_id
        )

        if destination.exists():
            backup_dir = (
                INSTALLED_PACKS_PATH
                / f".backup-{pack_id}-{int(time.time())}"
            )

            os.replace(
                destination,
                backup_dir,
            )

        try:
            os.replace(
                staging_dir,
                destination,
            )
            staging_dir = None
        except Exception:
            if (
                backup_dir is not None
                and backup_dir.exists()
                and not destination.exists()
            ):
                os.replace(
                    backup_dir,
                    destination,
                )
                backup_dir = None

            raise

        if (
            backup_dir is not None
            and backup_dir.exists()
        ):
            shutil.rmtree(
                backup_dir,
                ignore_errors=True,
            )
            backup_dir = None

        return {
            "ok": True,
            "id": pack_id,
            "version": str(manifest["version"]),
            "saved": True,
        }

    finally:
        if (
            staging_dir is not None
            and staging_dir.exists()
        ):
            shutil.rmtree(
                staging_dir,
                ignore_errors=True,
            )

        if (
            backup_dir is not None
            and backup_dir.exists()
        ):
            shutil.rmtree(
                backup_dir,
                ignore_errors=True,
            )


@app.post("/api/v1/packs/{pack_id}/validate", dependencies=[Depends(require_permission("packs.manage"))])
def validate_pack_changes(
    pack_id: str,
    payload: PackFilesPayload,
):
    # Future permission:
    # packs.edit

    pack_dir = get_pack_dir(pack_id)

    if not payload.files:
        raise HTTPException(
            400,
            "No pack files supplied",
        )

    with tempfile.TemporaryDirectory(
        prefix=f"ferpek-validate-{pack_id}-"
    ) as temporary:
        temporary_dir = Path(temporary)

        for source in pack_dir.rglob("*"):
            if not source.is_file():
                continue

            if source.is_symlink():
                continue

            relative = source.relative_to(
                pack_dir
            )

            destination = (
                temporary_dir / relative
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(
                source,
                destination,
            )

        for file_path, content in payload.files.items():
            requested = Path(file_path)

            if (
                requested.is_absolute()
                or ".." in requested.parts
            ):
                raise HTTPException(
                    400,
                    "Invalid pack file path",
                )

            if requested.suffix not in {
                ".yaml",
                ".yml",
            }:
                raise HTTPException(
                    400,
                    "Only YAML pack files may be edited",
                )

            target = (
                temporary_dir / requested
            ).resolve()

            try:
                target.relative_to(
                    temporary_dir.resolve()
                )
            except ValueError:
                raise HTTPException(
                    400,
                    "Invalid pack file path",
                )

            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            target.write_text(
                content,
                encoding="utf-8",
            )

        manifest = validate_pack_directory(
            temporary_dir
        )

        if str(manifest["id"]).strip() != pack_id:
            raise HTTPException(
                400,
                "Pack id cannot be changed",
            )

    return {
        "valid": True,
        "id": pack_id,
        "version": str(manifest["version"]),
    }


def install_pack_archive(
    archive_path: Path,
    allow_official: bool = False,
    force_replace: bool = False,
):
    max_uncompressed_size = 25 * 1024 * 1024
    max_files = 250

    staging_dir = None
    backup_dir = None

    try:
        manifest = validate_pack_archive(
            archive_path
        )

        pack_id = str(manifest["id"]).strip()
        version = str(manifest["version"]).strip()

        origin = str(
            manifest.get("origin", "local")
        ).strip().lower()

        if origin == "official" and not allow_official:
            raise HTTPException(
                400,
                (
                    "Uploaded packs cannot declare "
                    "origin official"
                ),
            )

        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            files = [
                member
                for member in archive.infolist()
                if not member.is_dir()
            ]

            if len(files) > max_files:
                raise HTTPException(
                    400,
                    "Pack contains too many files",
                )

            uncompressed_size = sum(
                member.file_size
                for member in files
            )

            if uncompressed_size > max_uncompressed_size:
                raise HTTPException(
                    413,
                    "Pack exceeds the 25 MB uncompressed limit",
                )

            staging_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".install-{pack_id}-",
                    dir=INSTALLED_PACKS_PATH,
                )
            )

            for member in archive.infolist():
                if member.is_dir():
                    continue

                destination = (
                    staging_dir / member.filename
                )

                destination.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                with archive.open(member) as source:
                    with destination.open("wb") as target:
                        shutil.copyfileobj(
                            source,
                            target,
                        )

        installed_manifest = validate_pack_directory(
            staging_dir
        )

        if installed_manifest["id"] != pack_id:
            raise HTTPException(
                400,
                "Pack id changed during installation",
            )

        destination = (
            INSTALLED_PACKS_PATH / pack_id
        )

        install_action = "installed"

        if destination.exists():
            current_manifest = read_pack_manifest(
                destination
            )

            if current_manifest is None:
                raise HTTPException(
                    400,
                    "Existing installed pack is invalid",
                )

            current_version = str(
                current_manifest.get(
                    "version",
                    "",
                )
            ).strip()

            try:
                incoming_version = Version(version)
                installed_version = Version(
                    current_version
                )
            except InvalidVersion:
                raise HTTPException(
                    400,
                    "Existing installed pack has an invalid version",
                )

            if not force_replace:
                if incoming_version == installed_version:
                    raise HTTPException(
                        409,
                        (
                            f"Pack {pack_id} version "
                            f"{version} is already installed"
                        ),
                    )

                if incoming_version < installed_version:
                    raise HTTPException(
                        409,
                        (
                            "Pack downgrade is not allowed: "
                            f"{current_version} -> {version}"
                        ),
                    )

                install_action = "updated"
            else:
                install_action = "restored"

            backup_dir = (
                INSTALLED_PACKS_PATH
                / f".backup-{pack_id}-{int(time.time())}"
            )

            os.replace(
                destination,
                backup_dir,
            )

        try:
            os.replace(
                staging_dir,
                destination,
            )
            staging_dir = None
        except Exception:
            if (
                backup_dir is not None
                and backup_dir.exists()
                and not destination.exists()
            ):
                os.replace(
                    backup_dir,
                    destination,
                )
                backup_dir = None

            raise

        if (
            backup_dir is not None
            and backup_dir.exists()
        ):
            shutil.rmtree(
                backup_dir,
                ignore_errors=True,
            )
            backup_dir = None

        return {
            "ok": True,
            "id": pack_id,
            "version": version,
            "installed": True,
            "action": install_action,
        }

    finally:
        if (
            staging_dir is not None
            and staging_dir.exists()
        ):
            shutil.rmtree(
                staging_dir,
                ignore_errors=True,
            )

        if (
            backup_dir is not None
            and backup_dir.exists()
        ):
            shutil.rmtree(
                backup_dir,
                ignore_errors=True,
            )


@app.post("/api/v1/packs/install", dependencies=[Depends(require_permission("packs.manage"))])
async def install_pack(file: UploadFile = File(...)):
    # Future permission:
    # packs.install

    filename = file.filename or ""

    if not filename.lower().endswith(".pack"):
        raise HTTPException(
            400,
            "Uploaded file must use the .pack extension",
        )

    INSTALLED_PACKS_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    max_archive_size = 10 * 1024 * 1024
    archive_path = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix=".upload-",
            suffix=".pack",
            dir=INSTALLED_PACKS_PATH,
            delete=False,
        ) as temporary:
            archive_path = Path(temporary.name)
            total = 0

            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                total += len(chunk)

                if total > max_archive_size:
                    raise HTTPException(
                        413,
                        "Pack archive exceeds the 10 MB limit",
                    )

                temporary.write(chunk)

        return install_pack_archive(
            archive_path,
            allow_official=False,
        )

    finally:
        await file.close()

        if (
            archive_path is not None
            and archive_path.exists()
        ):
            archive_path.unlink(
                missing_ok=True
            )


@app.put("/api/v1/packs/{pack_id}/state", dependencies=[Depends(require_permission("packs.manage"))])
def set_pack_state(
    pack_id: str,
    payload: PackStatePayload,
):
    pack_dir = get_pack_dir(pack_id)

    manifest = read_pack_manifest(pack_dir)

    if manifest is None:
        raise HTTPException(
            404,
            "Pack manifest not found",
        )

    now = int(time.time())

    with db() as conn:
        conn.execute(
            """
            INSERT INTO pack_states (
                pack_id,
                enabled,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(pack_id)
            DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                pack_id,
                1 if payload.enabled else 0,
                now,
            ),
        )

    return {
        "id": pack_id,
        "enabled": payload.enabled,
    }


@app.post("/api/v1/packs/{pack_id}/revert", dependencies=[Depends(require_permission("packs.manage"))])
def revert_pack_to_official(pack_id: str):
    pack_id = str(pack_id).strip()

    if not pack_id:
        raise HTTPException(
            400,
            "Pack id is required",
        )

    if not all(
        char.isalnum() or char in {"-", "_"}
        for char in pack_id
    ):
        raise HTTPException(
            400,
            "Invalid pack id",
        )

    installed_dir = INSTALLED_PACKS_PATH / pack_id

    if (
        not installed_dir.is_dir()
        or installed_dir.is_symlink()
    ):
        raise HTTPException(
            404,
            "Installed pack not found",
        )

    registry = fetch_pack_registry()

    entry = next(
        (
            item
            for item in registry["packs"]
            if (
                isinstance(item, dict)
                and str(item.get("id", "")).strip()
                == pack_id
                and str(item.get("origin", "")).strip().lower()
                == "official"
            )
        ),
        None,
    )

    if entry is None:
        raise HTTPException(
            404,
            "Official pack not found in registry",
        )

    archive_path = None

    try:
        archive_path = download_registry_pack(entry)

        result = install_pack_archive(
            archive_path,
            allow_official=True,
            force_replace=True,
        )

        result["reverted"] = True
        return result
    finally:
        if (
            archive_path is not None
            and archive_path.exists()
        ):
            archive_path.unlink(
                missing_ok=True
            )


@app.delete("/api/v1/packs/{pack_id}", dependencies=[Depends(require_permission("packs.manage"))])
def delete_pack(pack_id: str):
    # Future permission: packs.delete
    pack_id = str(pack_id).strip()

    if not pack_id:
        raise HTTPException(
            400,
            "Pack id is required",
        )

    if not all(
        char.isalnum() or char in {"-", "_"}
        for char in pack_id
    ):
        raise HTTPException(
            400,
            "Invalid pack id",
        )

    installed_dir = INSTALLED_PACKS_PATH / pack_id

    if not installed_dir.exists():
        raise HTTPException(
            404,
            "Installed pack not found",
        )

    if (
        not installed_dir.is_dir()
        or installed_dir.is_symlink()
    ):
        raise HTTPException(
            400,
            "Invalid installed pack",
        )

    manifest = read_pack_manifest(
        installed_dir
    )

    if (
        manifest is None
        or str(manifest.get("id", "")).strip()
        != pack_id
    ):
        raise HTTPException(
            400,
            "Invalid installed pack",
        )

    shutil.rmtree(installed_dir)

    with db() as conn:
        conn.execute(
            """
            DELETE FROM agent_pack_source_discovery
            WHERE pack_id = ?
            """,
            (pack_id,),
        )

        conn.execute(
            """
            DELETE FROM agent_pack_discovery
            WHERE pack_id = ?
            """,
            (pack_id,),
        )

        conn.execute(
            """
            DELETE FROM agent_pack_assignments
            WHERE pack_id = ?
            """,
            (pack_id,),
        )

        conn.execute(
            """
            DELETE FROM pack_states
            WHERE pack_id = ?
            """,
            (pack_id,),
        )

    return {
        "ok": True,
        "id": pack_id,
        "deleted": True,
    }


def fetch_pack_registry():
    max_registry_size = 2 * 1024 * 1024

    request = urllib.request.Request(
        PACK_REGISTRY_URL,
        headers={
            "User-Agent": f"FERPEK-Lens/{SERVER_VERSION}",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10,
        ) as response:
            content = response.read(
                max_registry_size + 1
            )
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            502,
            f"Pack registry returned HTTP {exc.code}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            502,
            f"Pack registry unavailable: {exc.reason}",
        ) from exc

    if len(content) > max_registry_size:
        raise HTTPException(
            502,
            "Pack registry response exceeds size limit",
        )

    try:
        registry = json.loads(
            content.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            502,
            "Pack registry returned invalid JSON",
        ) from exc

    if not isinstance(registry, dict):
        raise HTTPException(
            502,
            "Invalid pack registry",
        )

    if registry.get("schema_version") != 1:
        raise HTTPException(
            502,
            "Unsupported pack registry schema",
        )

    packs = registry.get("packs")

    if not isinstance(packs, list):
        raise HTTPException(
            502,
            "Invalid pack registry pack list",
        )

    return registry


def download_registry_pack(entry: dict) -> Path:
    pack_id = str(
        entry.get("id", "")
    ).strip()

    version = str(
        entry.get("version", "")
    ).strip()

    download = str(
        entry.get("download", "")
    ).strip()

    expected_sha256 = str(
        entry.get("sha256", "")
    ).strip().lower()

    expected_size = entry.get("size")

    origin = str(
        entry.get("origin", "")
    ).strip().lower()

    if not pack_id or not version:
        raise HTTPException(
            502,
            "Registry pack is missing id or version",
        )

    if origin != "official":
        raise HTTPException(
            502,
            "Registry pack is not marked official",
        )

    if not download:
        raise HTTPException(
            502,
            "Registry pack is missing download path",
        )

    if (
        len(expected_sha256) != 64
        or any(
            char not in "0123456789abcdef"
            for char in expected_sha256
        )
    ):
        raise HTTPException(
            502,
            "Registry pack has invalid SHA-256",
        )

    if (
        not isinstance(expected_size, int)
        or expected_size <= 0
        or expected_size > 10 * 1024 * 1024
    ):
        raise HTTPException(
            502,
            "Registry pack has invalid size",
        )

    download_url = urllib.parse.urljoin(
        PACK_REGISTRY_URL,
        download,
    )

    parsed_registry = urllib.parse.urlparse(
        PACK_REGISTRY_URL
    )
    parsed_download = urllib.parse.urlparse(
        download_url
    )

    if parsed_download.scheme not in {"http", "https"}:
        raise HTTPException(
            502,
            "Registry pack download URL is invalid",
        )

    if (
        parsed_registry.scheme == "https"
        and parsed_download.scheme != "https"
    ):
        raise HTTPException(
            502,
            "Registry pack download cannot downgrade HTTPS",
        )

    if (
        parsed_download.scheme != parsed_registry.scheme
        or parsed_download.netloc != parsed_registry.netloc
    ):
        raise HTTPException(
            502,
            "Registry pack download must use the registry origin",
        )

    request = urllib.request.Request(
        download_url,
        headers={
            "User-Agent": f"FERPEK-Lens/{SERVER_VERSION}",
            "Accept": "application/octet-stream",
        },
    )

    INSTALLED_PACKS_PATH.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = None

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            with tempfile.NamedTemporaryFile(
                prefix=".registry-",
                suffix=".pack",
                dir=INSTALLED_PACKS_PATH,
                delete=False,
            ) as temporary:
                temporary_path = Path(
                    temporary.name
                )

                digest = hashlib.sha256()
                total = 0

                while True:
                    chunk = response.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    total += len(chunk)

                    if total > 10 * 1024 * 1024:
                        raise HTTPException(
                            413,
                            "Registry pack exceeds 10 MB limit",
                        )

                    digest.update(chunk)
                    temporary.write(chunk)

        if total != expected_size:
            raise HTTPException(
                502,
                "Registry pack size does not match catalog",
            )

        actual_sha256 = digest.hexdigest()

        if actual_sha256 != expected_sha256:
            raise HTTPException(
                502,
                "Registry pack SHA-256 does not match catalog",
            )

        manifest = validate_pack_archive(
            temporary_path
        )

        if str(manifest["id"]).strip() != pack_id:
            raise HTTPException(
                502,
                "Registry pack id does not match catalog",
            )

        if str(manifest["version"]).strip() != version:
            raise HTTPException(
                502,
                "Registry pack version does not match catalog",
            )

        if str(
            manifest.get("origin", "")
        ).strip().lower() != "official":
            raise HTTPException(
                502,
                "Registry pack manifest is not official",
            )

        return temporary_path

    except urllib.error.HTTPError as exc:
        raise HTTPException(
            502,
            f"Pack download returned HTTP {exc.code}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            502,
            f"Pack download failed: {exc.reason}",
        ) from exc
    except Exception:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink(
                missing_ok=True
            )
        raise


def get_registry_pack_status(entry: dict):
    pack_id = str(
        entry.get("id", "")
    ).strip()

    version = str(
        entry.get("version", "")
    ).strip()

    if not pack_id or not version:
        return "invalid", None

    compatibility = entry.get(
        "compatibility",
        {},
    )

    if not isinstance(compatibility, dict):
        compatibility = {}

    server_spec = str(
        compatibility.get("server", "")
    ).strip()

    if server_spec:
        try:
            if Version(SERVER_VERSION) not in SpecifierSet(
                server_spec
            ):
                return "incompatible", None
        except Exception:
            return "invalid", None

    local_manifest = None
    candidate = INSTALLED_PACKS_PATH / pack_id

    if (
        candidate.is_dir()
        and not candidate.is_symlink()
    ):
        manifest = read_pack_manifest(candidate)

        if (
            manifest is not None
            and str(
                manifest.get("id", "")
            ).strip() == pack_id
        ):
            local_manifest = manifest

    if local_manifest is None:
        return "available", None

    local_version = str(
        local_manifest.get(
            "version",
            "",
        )
    ).strip()

    try:
        registry_version = Version(version)
        installed_version = Version(
            local_version
        )
    except InvalidVersion:
        return "invalid", local_version

    if registry_version > installed_version:
        return "update_available", local_version

    if registry_version < installed_version:
        return "local_newer", local_version

    return "installed", local_version


@app.post(
    "/api/v1/packs/registry/{pack_id}/install",
    dependencies=[
        Depends(
            require_permission("packs.manage")
        )
    ],
)
def install_registry_pack(pack_id: str):
    pack_id = str(pack_id).strip()

    if not pack_id:
        raise HTTPException(
            400,
            "Pack id is required",
        )

    if not all(
        char.isalnum() or char in {"-", "_"}
        for char in pack_id
    ):
        raise HTTPException(
            400,
            "Invalid pack id",
        )

    registry = fetch_pack_registry()

    entry = next(
        (
            item
            for item in registry["packs"]
            if (
                isinstance(item, dict)
                and str(item.get("id", "")).strip()
                == pack_id
            )
        ),
        None,
    )

    if entry is None:
        raise HTTPException(
            404,
            "Pack not found in official registry",
        )

    status, installed_version = (
        get_registry_pack_status(entry)
    )

    if status == "invalid":
        raise HTTPException(
            502,
            "Registry pack metadata is invalid",
        )

    if status == "incompatible":
        raise HTTPException(
            409,
            "Pack is not compatible with this server",
        )

    if status == "installed":
        raise HTTPException(
            409,
            (
                f"Pack {pack_id} version "
                f"{entry['version']} is already installed"
            ),
        )

    if status == "local_newer":
        raise HTTPException(
            409,
            (
                f"Installed pack version "
                f"{installed_version} is newer than "
                f"registry version {entry['version']}"
            ),
        )

    archive_path = None

    try:
        archive_path = download_registry_pack(
            entry
        )

        return install_pack_archive(
            archive_path,
            allow_official=True,
        )
    finally:
        if (
            archive_path is not None
            and archive_path.exists()
        ):
            archive_path.unlink(
                missing_ok=True
            )


@app.get(
    "/api/v1/packs/registry",
    dependencies=[
        Depends(
            require_permission("packs.view")
        )
    ],
)
def list_registry_packs():
    registry = fetch_pack_registry()
    packs = []

    for entry in registry["packs"]:
        if not isinstance(entry, dict):
            continue

        status, installed_version = (
            get_registry_pack_status(entry)
        )

        pack = dict(entry)
        pack["status"] = status
        pack["installed_version"] = (
            installed_version
        )

        packs.append(pack)

    packs.sort(
        key=lambda pack: str(
            pack.get("name", pack.get("id", ""))
        ).lower()
    )

    return {
        "schema_version": registry[
            "schema_version"
        ],
        "registry_url": PACK_REGISTRY_URL,
        "packs": packs,
    }


@app.get("/api/v1/packs", dependencies=[Depends(require_permission("packs.view"))])
def list_packs():
    packs = []

    for pack_dir in iter_pack_dirs():
        if not pack_dir.is_dir():
            continue

        if pack_dir.is_symlink():
            continue

        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        allowed = is_pack_allowed(
            manifest
        )

        server_compatible = (
            is_pack_server_compatible(
                manifest
            )
        )

        enabled = is_pack_enabled(
            manifest["id"]
        )

        blocked_reason = ""

        if not allowed:
            blocked_reason = "policy"
        elif not server_compatible:
            blocked_reason = (
                "server_incompatible"
            )

        rules_dir = pack_dir / "rules"

        rule_count = 0

        if rules_dir.is_dir():
            rule_count = len(
                list(
                    rules_dir.glob("*.yaml")
                )
            )

        category = manifest.get(
            "category",
            {},
        )

        if not isinstance(category, dict):
            category = {}

        packs.append(
            {
                "id": manifest["id"],
                "name": manifest.get(
                    "name",
                    manifest["id"],
                ),
                "version": str(
                    manifest["version"]
                ),
                "author": manifest.get(
                    "author",
                    "",
                ),
                "description": manifest.get(
                    "description",
                    "",
                ),
                "origin": manifest.get(
                    "origin",
                    "local",
                ),
                "category": {
                    "id": category.get(
                        "id",
                        "other",
                    ),
                    "label": category.get(
                        "label",
                        "Other",
                    ),
                },
                "sources": manifest.get(
                    "sources",
                    [],
                ),
                "compatibility": manifest.get(
                    "compatibility",
                    {},
                ),
                "rule_count": rule_count,
                "installed": True,
                "enabled": enabled,
                "allowed": allowed,
                "server_compatible": server_compatible,
                "effective_enabled": (
                    enabled
                    and allowed
                    and server_compatible
                ),
                "blocked_reason": blocked_reason,
                "overridden": False,
                "capabilities": {
                    "edit": True,
                    "revert": (
                        str(
                            manifest.get(
                                "origin",
                                "local",
                            )
                        ).strip().lower()
                        == "official"
                    ),
                    "delete": True,
                },
            }
        )

    return {
        "packs": packs,
    }


# ---------------------------------------------------------------------------
# FERPEK Lens
# ---------------------------------------------------------------------------

@app.get("/pack-engine.py", include_in_schema=False)
def download_pack_engine():
    return FileResponse(
        PACK_ENGINE_PATH,
        media_type="text/x-python",
        filename="pack_engine.py",
    )


@app.get("/api/v1/agent/pack-catalog")
def get_agent_pack_catalog(
    agent=Depends(get_agent),
):
    packs = []

    agent_platform = str(
        agent.get("platform") or ""
    ).strip().lower()

    if not agent_platform:
        return {"packs": []}

    for pack_dir in iter_pack_dirs():
        if not pack_dir.is_dir():
            continue

        if pack_dir.is_symlink():
            continue

        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        platforms = manifest.get("platforms")

        if not isinstance(platforms, dict):
            continue

        if not is_pack_allowed(manifest):
            continue

        pack_id = str(manifest["id"])

        if not is_pack_enabled(pack_id):
            continue

        if not is_pack_server_compatible(manifest):
            continue

        if not is_pack_agent_compatible(
            manifest,
            str(agent.get("agent_version") or ""),
        ):
            continue

        if not is_pack_platform_compatible(
            manifest,
            agent_platform,
        ):
            continue

        platform_config = platforms.get(
            agent_platform
        )

        if not isinstance(platform_config, dict):
            continue

        packs.append(
            {
                "id": pack_id,
                "name": manifest.get(
                    "name",
                    pack_id,
                ),
                "version": str(
                    manifest.get(
                        "version",
                        "",
                    )
                ),
                "platform": agent_platform,
                "sources": platform_config.get(
                    "sources",
                    [],
                ),
            }
        )

    packs.sort(
        key=lambda pack: str(
            pack["name"]
        ).lower()
    )

    return {"packs": packs}


@app.post("/api/v1/agent/pack-discovery")
def report_agent_pack_discovery(
    batch: AgentPackDiscoveryBatch,
    agent=Depends(get_agent),
):
    now = int(time.time())

    catalog = get_agent_pack_catalog(
        agent=agent
    )

    valid_sources = {
        str(pack["id"]): {
            str(source.get("id", "")).strip()
            for source in pack.get("sources", [])
            if str(source.get("id", "")).strip()
        }
        for pack in catalog["packs"]
    }

    with db() as conn:
        for result in batch.packs:
            pack_id = result.pack_id.strip()

            if pack_id not in valid_sources:
                raise HTTPException(
                    400,
                    (
                        "Pack is not available for "
                        f"discovery: {pack_id}"
                    ),
                )

            seen_source_ids = set()

            for source in result.sources:
                source_id = source.source_id.strip()

                if not source_id:
                    raise HTTPException(
                        400,
                        "Discovery source id cannot be empty",
                    )

                if source_id in seen_source_ids:
                    raise HTTPException(
                        400,
                        (
                            "Duplicate discovery source: "
                            f"{pack_id}/{source_id}"
                        ),
                    )

                seen_source_ids.add(source_id)

                if source_id not in valid_sources[pack_id]:
                    raise HTTPException(
                        400,
                        (
                            "Unknown discovery source: "
                            f"{pack_id}/{source_id}"
                        ),
                    )

            conn.execute(
                """
                INSERT INTO agent_pack_discovery
                    (
                        agent_id,
                        pack_id,
                        supported,
                        detected,
                        source_id,
                        source_type,
                        source_value,
                        checked_at
                    )
                VALUES (?, ?, ?, ?, '', '', '', ?)
                ON CONFLICT(agent_id, pack_id)
                DO UPDATE SET
                    supported = excluded.supported,
                    detected = excluded.detected,
                    source_id = '',
                    source_type = '',
                    source_value = '',
                    checked_at = excluded.checked_at
                """,
                (
                    agent["id"],
                    pack_id,
                    int(result.supported),
                    int(result.detected),
                    now,
                ),
            )

            conn.execute(
                """
                DELETE FROM agent_pack_source_discovery
                WHERE agent_id = ?
                  AND pack_id = ?
                """,
                (
                    agent["id"],
                    pack_id,
                ),
            )

            for source in result.sources:
                conn.execute(
                    """
                    INSERT INTO agent_pack_source_discovery
                        (
                            agent_id,
                            pack_id,
                            source_id,
                            detected,
                            source_type,
                            source_value,
                            checked_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent["id"],
                        pack_id,
                        source.source_id.strip(),
                        int(source.detected),
                        source.source_type.strip(),
                        source.source_value.strip(),
                        now,
                    ),
                )

    return {
        "received": len(batch.packs),
    }


@app.get("/api/v1/agent/packs")
def get_agent_packs(agent=Depends(get_agent)):
    packs = []

    with db() as conn:
        assignment_rows = conn.execute(
            """
            SELECT *
            FROM agent_pack_assignments
            WHERE agent_id = ?
              AND enabled = 1
            """,
            (agent["id"],),
        ).fetchall()

        assignments = {
            row["pack_id"]: row
            for row in assignment_rows
        }

        pack_discovery_rows = {
            row["pack_id"]: row
            for row in conn.execute(
                """
                SELECT *
                FROM agent_pack_discovery
                WHERE agent_id = ?
                """,
                (agent["id"],),
            ).fetchall()
        }

        source_discovery_rows = conn.execute(
            """
            SELECT *
            FROM agent_pack_source_discovery
            WHERE agent_id = ?
            """,
            (agent["id"],),
        ).fetchall()

    discovery_by_pack = {}

    for row in source_discovery_rows:
        discovery_by_pack.setdefault(
            row["pack_id"],
            {},
        )[row["source_id"]] = row

    for pack_dir in iter_pack_dirs():
        if not pack_dir.is_dir():
            continue

        if pack_dir.is_symlink():
            continue

        manifest = read_pack_manifest(pack_dir)

        if manifest is None:
            continue

        pack_id = str(manifest["id"])

        assignment = assignments.get(pack_id)

        if assignment is None:
            continue

        if not is_pack_allowed(manifest):
            continue

        if not is_pack_enabled(manifest["id"]):
            continue

        if not is_pack_server_compatible(manifest):
            continue

        if not is_pack_agent_compatible(
            manifest,
            str(agent.get("agent_version") or ""),
        ):
            continue

        if not is_pack_platform_compatible(
            manifest,
            str(agent.get("platform") or ""),
        ):
            continue

        try:
            config = json.loads(
                assignment["config_json"]
                or "{}"
            )

            if not isinstance(config, dict):
                config = {}

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            config = {}

        pack_discovery = pack_discovery_rows.get(
            pack_id
        )

        readiness = evaluate_pack_activation_readiness(
            manifest,
            str(
                agent.get("platform") or ""
            ).strip().lower(),
            discovery_by_pack.get(
                pack_id,
                {},
            ),
            config,
            pack_discovery is not None,
        )

        if not readiness["can_activate"]:
            continue

        version = manifest["version"]

        files = {}

        for file_path in sorted(
            pack_dir.rglob("*.yaml")
        ):
            if not file_path.is_file():
                continue

            if file_path.is_symlink():
                continue

            try:
                resolved = file_path.resolve()
                resolved.relative_to(
                    pack_dir.resolve()
                )
            except ValueError:
                continue

            relative_path = file_path.relative_to(
                pack_dir
            ).as_posix()

            try:
                content = file_path.read_text(
                    encoding="utf-8"
                )

                # Validate every YAML file before sending it.
                yaml.safe_load(content)

            except Exception as exc:
                raise HTTPException(
                    500,
                    (
                        f"Invalid YAML in "
                        f"{pack_id}/{relative_path}: {exc}"
                    ),
                )

            files[relative_path] = content

        runtime_sources = []

        platform_name = str(
            agent.get("platform") or ""
        ).strip().lower()

        platforms = manifest.get(
            "platforms",
            {},
        )

        platform_config = (
            platforms.get(platform_name, {})
            if isinstance(platforms, dict)
            else {}
        )

        declarative_sources = (
            platform_config.get("sources", [])
            if isinstance(platform_config, dict)
            else []
        )

        for source in declarative_sources:
            if not isinstance(source, dict):
                continue

            source_id = str(
                source.get("id", "")
            ).strip()

            if not source_id:
                continue

            source_name = str(
                source.get("name")
                or source_id
            )

            discovery_row = (
                discovery_by_pack
                .get(pack_id, {})
                .get(source_id)
            )

            runtime_source = None

            if (
                discovery_row is not None
                and bool(discovery_row["detected"])
            ):
                source_type = str(
                    discovery_row["source_type"]
                    or ""
                ).strip()

                source_value = str(
                    discovery_row["source_value"]
                    or ""
                ).strip()

                if source_type == "journal":
                    runtime_source = {
                        "source_key": source_id,
                        "name": source_name,
                        "source_type": "journal",
                        "path": None,
                        "unit": source_value,
                        "enabled": True,
                        "send_events": True,
                        "discovered": True,
                    }

                elif source_type == "file":
                    runtime_source = {
                        "source_key": source_id,
                        "name": source_name,
                        "source_type": "file",
                        "path": source_value,
                        "unit": None,
                        "enabled": True,
                        "send_events": True,
                        "discovered": True,
                    }

            elif is_pack_source_manual_config_valid(
                source,
                config,
            ):
                config_sources = config.get(
                    "sources",
                    {},
                )

                source_config = (
                    config_sources.get(
                        source_id,
                        {},
                    )
                    if isinstance(
                        config_sources,
                        dict,
                    )
                    else {}
                )

                manual = source.get(
                    "manual",
                    {},
                )

                fields = (
                    manual.get("fields", [])
                    if isinstance(manual, dict)
                    else []
                )

                for field in fields:
                    if not isinstance(field, dict):
                        continue

                    if (
                        str(
                            field.get(
                                "type",
                                "",
                            )
                        ).strip().lower()
                        != "path"
                    ):
                        continue

                    field_id = str(
                        field.get("id", "")
                    ).strip()

                    value = str(
                        source_config.get(
                            field_id,
                            "",
                        )
                    ).strip()

                    if not value:
                        continue

                    runtime_source = {
                        "source_key": source_id,
                        "name": source_name,
                        "source_type": "file",
                        "path": value,
                        "unit": None,
                        "enabled": True,
                        "send_events": True,
                        "discovered": False,
                    }

                    break

            if runtime_source is not None:
                runtime_sources.append(
                    runtime_source
                )

        packs.append(
            {
                "id": pack_id,
                "name": manifest.get(
                    "name",
                    pack_id,
                ),
                "version": str(version),
                "files": files,
                "runtime_sources": runtime_sources,
            }
        )

    return {
        "packs": packs,
    }

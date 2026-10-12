#!/bin/sh

set -eu

SOURCE_VERSION="0.4.2"
TARGET_VERSION="0.4.3"

INSTALL_DIR="/opt/ferpek-lens-server"
REPOSITORY_RAW_BASE="https://raw.githubusercontent.com/ferpekdev/ferpek-lens"
TARGET_REF="v${TARGET_VERSION}"

SERVICE_NAME="ferpek-lens-updater.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

BACKUP_DIR=""
ROLLBACK_REQUIRED=0


log() {
    printf '%s\n' "$*"
}


fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}


usage() {
    cat <<'USAGE'
FERPEK Lens 0.4.2 -> 0.4.3 updater bootstrap

Usage:
  bootstrap-0.4.3.sh [options]

Options:
  --install-dir PATH    FERPEK Lens installation directory.
                        Default: /opt/ferpek-lens-server

  -h, --help            Show this help message.

This bootstrap is only intended for existing FERPEK Lens 0.4.2
installations. It installs the host-side updater infrastructure required
by FERPEK Lens 0.4.3 and later releases.
USAGE
}


while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-dir)
            [ "$#" -ge 2 ] ||
                fail "--install-dir requires a value."

            INSTALL_DIR="$2"
            shift 2
            ;;

        -h|--help)
            usage
            exit 0
            ;;

        *)
            fail "Unknown option: $1"
            ;;
    esac
done


if [ "$(id -u)" -ne 0 ]; then
    fail "This bootstrap must be run as root or with sudo."
fi


command -v docker >/dev/null 2>&1 ||
    fail "Docker is not installed."

docker compose version >/dev/null 2>&1 ||
    fail "Docker Compose is not available."

command -v curl >/dev/null 2>&1 ||
    fail "curl is required."

command -v python3 >/dev/null 2>&1 ||
    fail "python3 is required."

command -v systemctl >/dev/null 2>&1 ||
    fail "systemd is required."


COMPOSE_FILE="$INSTALL_DIR/compose.yml"
ENV_FILE="$INSTALL_DIR/.env"
HELPER_FILE="$INSTALL_DIR/update-helper.py"

[ -f "$COMPOSE_FILE" ] ||
    fail "FERPEK compose.yml was not found in $INSTALL_DIR."

[ -f "$ENV_FILE" ] ||
    fail "FERPEK .env was not found in $INSTALL_DIR."


env_value() {
    KEY="$1"

    sed -n \
        "s/^${KEY}=//p" \
        "$ENV_FILE" |
        tail -n 1
}


CURRENT_VERSION="$(env_value FERPEK_VERSION)"
FERPEK_WEB_PORT="$(env_value FERPEK_WEB_PORT)"
FERPEK_PORT="$(env_value FERPEK_PORT)"


[ "$CURRENT_VERSION" = "$SOURCE_VERSION" ] ||
    fail "This bootstrap requires FERPEK_VERSION=$SOURCE_VERSION. Found: ${CURRENT_VERSION:-unset}"

case "$FERPEK_WEB_PORT" in
    ''|*[!0-9]*)
        fail "Invalid or missing FERPEK_WEB_PORT in $ENV_FILE."
        ;;
esac

case "$FERPEK_PORT" in
    ''|*[!0-9]*)
        fail "Invalid or missing FERPEK_PORT in $ENV_FILE."
        ;;
esac


if [ ! -d "$INSTALL_DIR" ]; then
    fail "Installation directory does not exist: $INSTALL_DIR"
fi


cd "$INSTALL_DIR"


PROJECT_NAME="$(
    docker compose config \
        --format json 2>/dev/null |
    python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("name", ""))
'
)"


[ "$PROJECT_NAME" = "ferpek-lens" ] ||
    fail "Unexpected Docker Compose project name: ${PROJECT_NAME:-unknown}"


SERVER_CONTAINER="$(
    docker compose ps -q server
)"

[ -n "$SERVER_CONTAINER" ] ||
    fail "FERPEK Lens server container was not found."


INSTALLED_VERSION="$(
    curl -fsS \
        "http://127.0.0.1:${FERPEK_PORT}/health" |
    python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("version", ""))
'
)"


[ "$INSTALLED_VERSION" = "$SOURCE_VERSION" ] ||
    fail "Running FERPEK Lens version is $INSTALLED_VERSION, expected $SOURCE_VERSION."


DATA_MOUNT="$(
    docker inspect "$SERVER_CONTAINER" \
        --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}'
)"


[ -n "$DATA_MOUNT" ] ||
    fail "Could not identify the FERPEK Lens data volume."


log ""
log "FERPEK Lens updater bootstrap"
log "============================="
log ""
log "Installation:   $INSTALL_DIR"
log "Current:        $SOURCE_VERSION"
log "Target:         $TARGET_VERSION"
log "Compose project: $PROJECT_NAME"
log "Data volume:    $DATA_MOUNT"
log ""


TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
BACKUP_DIR="$INSTALL_DIR/.bootstrap-${SOURCE_VERSION}-to-${TARGET_VERSION}-${TIMESTAMP}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

cp -p "$COMPOSE_FILE" \
    "$BACKUP_DIR/compose.yml"

cp -p "$ENV_FILE" \
    "$BACKUP_DIR/.env"

if [ -f "$HELPER_FILE" ]; then
    cp -p "$HELPER_FILE" \
        "$BACKUP_DIR/update-helper.py"
fi

if [ -f "$SERVICE_PATH" ]; then
    cp -p "$SERVICE_PATH" \
        "$BACKUP_DIR/$SERVICE_NAME"
fi


STAGING_DIR="$INSTALL_DIR/.bootstrap-staging"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
chmod 700 "$STAGING_DIR"


cleanup_staging() {
    rm -rf "$STAGING_DIR"
}


rollback() {
    if [ "$ROLLBACK_REQUIRED" -ne 1 ]; then
        return
    fi

    log ""
    log "Update failed. Rolling back to FERPEK Lens $SOURCE_VERSION..."

    systemctl disable --now "$SERVICE_NAME" \
        >/dev/null 2>&1 || true

    cp -p \
        "$BACKUP_DIR/compose.yml" \
        "$COMPOSE_FILE"

    cp -p \
        "$BACKUP_DIR/.env" \
        "$ENV_FILE"

    if [ -f "$BACKUP_DIR/update-helper.py" ]; then
        cp -p \
            "$BACKUP_DIR/update-helper.py" \
            "$HELPER_FILE"
    else
        rm -f "$HELPER_FILE"
    fi

    if [ -f "$BACKUP_DIR/$SERVICE_NAME" ]; then
        cp -p \
            "$BACKUP_DIR/$SERVICE_NAME" \
            "$SERVICE_PATH"
    else
        rm -f "$SERVICE_PATH"
    fi

    systemctl daemon-reload || true

    cd "$INSTALL_DIR"

    docker compose up -d \
        --remove-orphans || true

    cleanup_staging

    log ""
    log "Rollback completed."
    log "Backup retained at:"
    log "  $BACKUP_DIR"
}


on_exit() {
    STATUS="$?"

    if [ "$STATUS" -ne 0 ]; then
        rollback
    fi

    exit "$STATUS"
}


trap on_exit EXIT INT TERM


log "[1/7] Downloading FERPEK Lens $TARGET_VERSION deployment artifacts..."

curl -fsSL \
    "$REPOSITORY_RAW_BASE/$TARGET_REF/deploy/compose.yml" \
    -o "$STAGING_DIR/compose.yml"

curl -fsSL \
    "$REPOSITORY_RAW_BASE/$TARGET_REF/deploy/updater/update-helper.py" \
    -o "$STAGING_DIR/update-helper.py"

curl -fsSL \
    "$REPOSITORY_RAW_BASE/$TARGET_REF/deploy/updater/ferpek-lens-updater.service" \
    -o "$STAGING_DIR/$SERVICE_NAME"


[ -s "$STAGING_DIR/compose.yml" ] ||
    fail "Downloaded compose.yml is empty."

[ -s "$STAGING_DIR/update-helper.py" ] ||
    fail "Downloaded update-helper.py is empty."

[ -s "$STAGING_DIR/$SERVICE_NAME" ] ||
    fail "Downloaded updater service is empty."


log "[2/7] Validating updater artifacts..."

python3 -m py_compile \
    "$STAGING_DIR/update-helper.py"

grep -q \
    'ghcr.io/ferpekdev/ferpek-lens-server:${FERPEK_VERSION:-latest}' \
    "$STAGING_DIR/compose.yml" ||
    fail "Downloaded compose.yml does not contain the expected server image."

grep -q \
    'ghcr.io/ferpekdev/ferpek-lens-web:${FERPEK_VERSION:-latest}' \
    "$STAGING_DIR/compose.yml" ||
    fail "Downloaded compose.yml does not contain the expected web image."

grep -q \
    'FERPEK_UPDATER_SOCKET=/run/ferpek-lens/updater.sock' \
    "$STAGING_DIR/compose.yml" ||
    fail "Downloaded compose.yml does not contain updater socket configuration."

grep -q \
    '/run/ferpek-lens:/run/ferpek-lens:ro' \
    "$STAGING_DIR/compose.yml" ||
    fail "Downloaded compose.yml does not mount the updater socket."


python3 - "$STAGING_DIR/$SERVICE_NAME" "$INSTALL_DIR" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
install_dir = sys.argv[2]

text = source.read_text()

text = text.replace(
    "/opt/ferpek-lens-server",
    install_dir,
)

source.write_text(text)
PY


grep -Fq \
    "ExecStart=/usr/bin/python3 $INSTALL_DIR/update-helper.py" \
    "$STAGING_DIR/$SERVICE_NAME" ||
    fail "Updater service was not rendered correctly."


log "[3/7] Preparing FERPEK Lens $TARGET_VERSION configuration..."

cp -p \
    "$ENV_FILE" \
    "$STAGING_DIR/.env"

python3 - "$STAGING_DIR/.env" "$TARGET_VERSION" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
version = sys.argv[2]

lines = path.read_text().splitlines()

result = []
replaced = False

for line in lines:
    if line.startswith("FERPEK_VERSION="):
        result.append(f"FERPEK_VERSION={version}")
        replaced = True
    else:
        result.append(line)

if not replaced:
    result.append(f"FERPEK_VERSION={version}")

path.write_text("\n".join(result) + "\n")
PY

chmod 600 "$STAGING_DIR/.env"


log "[4/7] Pulling FERPEK Lens $TARGET_VERSION images..."

docker pull \
    "ghcr.io/ferpekdev/ferpek-lens-server:$TARGET_VERSION"

docker pull \
    "ghcr.io/ferpekdev/ferpek-lens-web:$TARGET_VERSION"


ROLLBACK_REQUIRED=1


log "[5/7] Installing updater infrastructure..."

cp \
    "$STAGING_DIR/compose.yml" \
    "$COMPOSE_FILE"

chmod 644 "$COMPOSE_FILE"

cp \
    "$STAGING_DIR/.env" \
    "$ENV_FILE"

chmod 600 "$ENV_FILE"

cp \
    "$STAGING_DIR/update-helper.py" \
    "$HELPER_FILE"

chmod 755 "$HELPER_FILE"

cp \
    "$STAGING_DIR/$SERVICE_NAME" \
    "$SERVICE_PATH"

chmod 644 "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"


log "[6/7] Starting FERPEK Lens $TARGET_VERSION..."

cd "$INSTALL_DIR"

docker compose up -d \
    --remove-orphans


log "[7/7] Verifying FERPEK Lens $TARGET_VERSION..."

ATTEMPTS=0
MAX_ATTEMPTS=45

while [ "$ATTEMPTS" -lt "$MAX_ATTEMPTS" ]; do
    if curl -fsS \
        "http://127.0.0.1:${FERPEK_PORT}/health" \
        >/dev/null 2>&1
    then
        break
    fi

    ATTEMPTS=$((ATTEMPTS + 1))
    sleep 2
done


HEALTH="$(
    curl -fsS \
        "http://127.0.0.1:${FERPEK_PORT}/health"
)"


RUNNING_VERSION="$(
    printf '%s' "$HEALTH" |
    python3 -c '
import json
import sys

data = json.load(sys.stdin)
print(data.get("version", ""))
'
)"


[ "$RUNNING_VERSION" = "$TARGET_VERSION" ] ||
    fail "FERPEK Lens reported version $RUNNING_VERSION after the update."


WEB_ATTEMPTS=0

while [ "$WEB_ATTEMPTS" -lt "$MAX_ATTEMPTS" ]; do
    if curl -fsS \
        "http://127.0.0.1:${FERPEK_WEB_PORT}/" \
        >/dev/null 2>&1
    then
        break
    fi

    WEB_ATTEMPTS=$((WEB_ATTEMPTS + 1))
    sleep 2
done


curl -fsS \
    "http://127.0.0.1:${FERPEK_WEB_PORT}/" \
    >/dev/null ||
    fail "FERPEK Lens WebUI is not reachable."


systemctl is-active --quiet "$SERVICE_NAME" ||
    fail "FERPEK Lens updater service is not active."


SOCKET="/run/ferpek-lens/updater.sock"

[ -S "$SOCKET" ] ||
    fail "FERPEK Lens updater socket was not created."


NEW_SERVER_CONTAINER="$(
    docker compose ps -q server
)"

NEW_DATA_MOUNT="$(
    docker inspect "$NEW_SERVER_CONTAINER" \
        --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}'
)"


[ "$NEW_DATA_MOUNT" = "$DATA_MOUNT" ] ||
    fail "FERPEK Lens data volume changed during the update."


ROLLBACK_REQUIRED=0

cleanup_staging

trap - EXIT INT TERM


log ""
log "FERPEK Lens bootstrap completed successfully."
log ""
log "Version:"
log "  $SOURCE_VERSION -> $TARGET_VERSION"
log ""
log "Data volume preserved:"
log "  $DATA_MOUNT"
log ""
log "Updater service:"
log "  active"
log ""
log "Backup retained at:"
log "  $BACKUP_DIR"
log ""
log "Future compatible FERPEK Lens updates can be managed"
log "from Settings -> Updates."

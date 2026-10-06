#!/bin/sh

set -eu

INSTALL_DIR="/opt/ferpek"
FERPEK_VERSION="latest"
FERPEK_WEB_PORT="5173"
FERPEK_PORT="8000"

REPOSITORY_RAW_BASE="https://raw.githubusercontent.com/ferpekdev/ferpek-lens"

usage() {
    cat <<'USAGE'
FERPEK Lens Server installer

Usage:
  install-server.sh [options]

Options:
  --version VERSION       FERPEK Lens version to install.
                          Default: latest

  --web-port PORT         Web interface port.
                          Default: 5173

  --server-port PORT      Server API and Agent communication port.
                          Default: 8000

  --install-dir PATH      Installation directory.
                          Default: /opt/ferpek

  -h, --help              Show this help message.
USAGE
}

log() {
    printf '%s\n' "$*"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --version)
            [ "$#" -ge 2 ] || fail "--version requires a value."
            FERPEK_VERSION="$2"
            shift 2
            ;;
        --web-port)
            [ "$#" -ge 2 ] || fail "--web-port requires a value."
            FERPEK_WEB_PORT="$2"
            shift 2
            ;;
        --server-port)
            [ "$#" -ge 2 ] || fail "--server-port requires a value."
            FERPEK_PORT="$2"
            shift 2
            ;;
        --install-dir)
            [ "$#" -ge 2 ] || fail "--install-dir requires a value."
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

case "$FERPEK_WEB_PORT" in
    ''|*[!0-9]*) fail "Invalid web port: $FERPEK_WEB_PORT" ;;
esac

case "$FERPEK_PORT" in
    ''|*[!0-9]*) fail "Invalid server port: $FERPEK_PORT" ;;
esac

if [ "$FERPEK_WEB_PORT" -lt 1 ] || [ "$FERPEK_WEB_PORT" -gt 65535 ]; then
    fail "Web port must be between 1 and 65535."
fi

if [ "$FERPEK_PORT" -lt 1 ] || [ "$FERPEK_PORT" -gt 65535 ]; then
    fail "Server port must be between 1 and 65535."
fi

if [ "$FERPEK_WEB_PORT" = "$FERPEK_PORT" ]; then
    fail "Web and server ports must be different."
fi

if [ "$(id -u)" -ne 0 ]; then
    fail "This installer must be run as root or with sudo."
fi

log ""
log "FERPEK Lens Server installer"
log "============================"
log ""

if [ -f "$INSTALL_DIR/compose.yml" ] || [ -f "$INSTALL_DIR/.env" ]; then
    fail "FERPEK Lens already appears to be installed in $INSTALL_DIR."
fi

if [ ! -r /etc/os-release ]; then
    fail "Unable to determine the operating system."
fi

. /etc/os-release

case "${ID:-}" in
    debian|ubuntu)
        ;;
    *)
        case " ${ID_LIKE:-} " in
            *" debian "*)
                ;;
            *)
                fail "This installer currently supports Debian-based Linux systems only."
                ;;
        esac
        ;;
esac

ARCH="$(uname -m)"

case "$ARCH" in
    x86_64|amd64)
        ;;
    *)
        fail "This FERPEK Lens release currently supports amd64 systems only. Detected: $ARCH"
        ;;
esac

install_base_dependencies() {
    log "[1/7] Installing required system packages..."

    export DEBIAN_FRONTEND=noninteractive

    apt-get update
    apt-get install -y ca-certificates curl
}

install_docker() {
    if command -v docker >/dev/null 2>&1; then
        log "[2/7] Docker is already installed."
        return
    fi

    log "[2/7] Installing Docker..."

    export DEBIAN_FRONTEND=noninteractive

    apt-get update
    apt-get install -y docker.io

    systemctl enable --now docker
}

install_compose() {
    if docker compose version >/dev/null 2>&1; then
        log "[3/7] Docker Compose is already available."
        return
    fi

    log "[3/7] Installing Docker Compose..."

    export DEBIAN_FRONTEND=noninteractive

    if apt-get install -y docker-compose-v2 2>/dev/null; then
        :
    elif apt-get install -y docker-compose-plugin 2>/dev/null; then
        :
    elif apt-get install -y docker-compose 2>/dev/null; then
        :
    else
        fail "Could not install Docker Compose."
    fi

    docker compose version >/dev/null 2>&1 ||
        fail "Docker Compose was installed but 'docker compose' is not available."
}

install_base_dependencies
install_docker
install_compose

if ! systemctl is-active --quiet docker; then
    log "Starting Docker..."
    systemctl enable --now docker
fi

log "[4/7] Preparing installation directory..."

mkdir -p "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"

log "[5/7] Downloading FERPEK Lens deployment configuration..."

if [ "$FERPEK_VERSION" = "latest" ]; then
    DEPLOY_REF="main"
else
    DEPLOY_REF="v$FERPEK_VERSION"
fi

COMPOSE_URL="$REPOSITORY_RAW_BASE/$DEPLOY_REF/deploy/compose.yml"

log "Using deployment definition from: $DEPLOY_REF"

curl -fsSL \
    "$COMPOSE_URL" \
    -o "$INSTALL_DIR/compose.yml"

[ -s "$INSTALL_DIR/compose.yml" ] ||
    fail "Downloaded compose.yml is empty."

cat > "$INSTALL_DIR/.env" <<EOF_ENV
FERPEK_VERSION=$FERPEK_VERSION
FERPEK_WEB_PORT=$FERPEK_WEB_PORT
FERPEK_PORT=$FERPEK_PORT
PACK_REGISTRY_URL=https://raw.githubusercontent.com/ferpekdev/ferpek-lens-packs/main/index.json
EOF_ENV

chmod 600 "$INSTALL_DIR/.env"

log "[6/7] Pulling FERPEK Lens container images..."

cd "$INSTALL_DIR"

docker compose pull

log "[7/7] Starting FERPEK Lens..."

docker compose up -d

log ""
log "Waiting for FERPEK Lens to become healthy..."

ATTEMPTS=0
MAX_ATTEMPTS=30

while [ "$ATTEMPTS" -lt "$MAX_ATTEMPTS" ]; do
    if curl -fsS "http://127.0.0.1:$FERPEK_PORT/health" >/dev/null 2>&1; then
        break
    fi

    ATTEMPTS=$((ATTEMPTS + 1))
    sleep 2
done

if ! curl -fsS "http://127.0.0.1:$FERPEK_PORT/health" >/dev/null 2>&1; then
    log ""
    docker compose ps || true
    log ""
    docker compose logs --tail 50 || true
    fail "FERPEK Lens did not become healthy."
fi

WEB_ATTEMPTS=0

while [ "$WEB_ATTEMPTS" -lt "$MAX_ATTEMPTS" ]; do
    if curl -fsS "http://127.0.0.1:$FERPEK_WEB_PORT/" >/dev/null 2>&1; then
        break
    fi

    WEB_ATTEMPTS=$((WEB_ATTEMPTS + 1))
    sleep 2
done

if ! curl -fsS "http://127.0.0.1:$FERPEK_WEB_PORT/" >/dev/null 2>&1; then
    fail "FERPEK Lens server is healthy, but the web interface is not reachable."
fi

HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

log ""
log "FERPEK Lens installed successfully."
log ""
log "Installation directory:"
log "  $INSTALL_DIR"
log ""
log "Web interface:"
log "  http://localhost:$FERPEK_WEB_PORT"

if [ -n "$HOST_IP" ]; then
    log "  http://$HOST_IP:$FERPEK_WEB_PORT"
fi

log ""
log "Agent/API endpoint:"
log "  Port $FERPEK_PORT"
log ""
log "Container status:"
docker compose ps
log ""
log "Open the web interface to complete the initial FERPEK Lens setup."

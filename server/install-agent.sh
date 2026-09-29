#!/bin/sh
set -eu

SERVER=""
TOKEN=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --server)
            SERVER="$2"
            shift 2
            ;;
        --token)
            TOKEN="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "FERPEK Agent installer must run as root." >&2
    exit 1
fi

if [ -z "$SERVER" ]; then
    echo "Missing --server" >&2
    exit 1
fi

if [ -z "$TOKEN" ]; then
    echo "Missing --token" >&2
    exit 1
fi

echo
echo "FERPEK Agent Installer"
echo "======================="
echo

echo "[1/7] Installing dependencies..."

if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3 python3-yaml
else
    echo "Unsupported distribution for automatic dependency installation." >&2
    echo "Install Python 3 and PyYAML manually." >&2
    exit 1
fi

echo "[2/7] Creating directories..."

mkdir -p /opt/ferpek/ferpek_lens
mkdir -p /etc/ferpek
mkdir -p /var/lib/ferpek/packs

echo "[3/7] Downloading FERPEK Agent..."

python3 - "$SERVER" <<'PYEOF'
import sys
import urllib.request

server = sys.argv[1].rstrip("/")

urllib.request.urlretrieve(
    server + "/agent.py",
    "/opt/ferpek/agent.py",
)

urllib.request.urlretrieve(
    server + "/pack-engine.py",
    "/opt/ferpek/ferpek_lens/pack_engine.py",
)
PYEOF

touch /opt/ferpek/ferpek_lens/__init__.py

chmod 755 /opt/ferpek/agent.py

echo "[4/7] Creating configuration..."

cat > /etc/ferpek/environment <<EOF2
FERPEK_SERVER=$SERVER
FERPEK_ENROLL_TOKEN=$TOKEN
EOF2

chmod 600 /etc/ferpek/environment

echo "[5/7] Installing systemd service..."

cat > /etc/systemd/system/ferpek-agent.service <<'EOF2'
[Unit]
Description=FERPEK Infrastructure Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/ferpek/environment
ExecStart=/usr/bin/python3 /opt/ferpek/agent.py
Restart=on-failure
RestartSec=5

User=root

[Install]
WantedBy=multi-user.target
EOF2

systemctl daemon-reload
systemctl enable ferpek-agent.service

echo "[6/7] Starting FERPEK Agent..."

systemctl restart ferpek-agent.service

echo "[7/7] Verifying FERPEK Agent..."

sleep 2

if systemctl is-active --quiet ferpek-agent.service; then
    echo
    echo "FERPEK Agent installed successfully."
    echo
    systemctl --no-pager --full status ferpek-agent.service || true
else
    echo
    echo "FERPEK Agent failed to start."
    echo
    journalctl -u ferpek-agent.service -n 30 --no-pager || true
    exit 1
fi

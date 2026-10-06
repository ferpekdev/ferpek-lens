#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "FERPEK Lens documentation"
echo "http://0.0.0.0:8001"
echo

exec docker run --rm -it \
  -p 8001:8000 \
  -v "$ROOT_DIR:/docs" \
  -w /docs \
  python:3.12-slim \
  sh -c '
    pip install --quiet --disable-pip-version-check -r docs/requirements.txt &&
    mkdocs serve --dev-addr=0.0.0.0:8000
  '

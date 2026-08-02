#!/usr/bin/env bash
# Kept so existing habits and cron entries keep working. The logic moved to backup.py,
# which runs on the windows development machine as well as in the container.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=$(command -v python3 || command -v python)
exec "$PYTHON" scripts/backup.py "$@"

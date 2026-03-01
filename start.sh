#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

[ -d ".venv" ] && source .venv/bin/activate
[ -d "venv" ] && source venv/bin/activate

export http_proxy="" https_proxy="" HTTP_PROXY="" HTTPS_PROXY="" NO_PROXY="*"

echo "=== SmartInvest v2.0 ==="
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000

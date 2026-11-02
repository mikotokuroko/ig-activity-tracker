#!/bin/zsh
set -e
cd "$(dirname "$0")"
export UV_CACHE_DIR="$PWD/.uv-cache"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python tracker.py configure
.venv/bin/python tracker.py login
.venv/bin/python tracker.py telegram-setup
if .venv/bin/python tracker.py check; then
  echo 'First scan complete. Hosting is not configured yet. Press Enter to close.'
else
  echo 'First scan did not finish successfully. Login and Telegram are saved.'
  echo 'Use Check.command to retry without logging in again. Press Enter to close.'
  read
  exit 1
fi
read

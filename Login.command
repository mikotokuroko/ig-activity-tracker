#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python tracker.py login
echo 'Press Enter to close.'
read

#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python tracker.py telegram-setup
echo 'Press Enter to close.'
read

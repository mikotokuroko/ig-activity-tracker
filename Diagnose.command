#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python -u diagnose_followers.py
result=$?
echo 'Diagnostic finished. Press Enter to close.'
read
exit "$result"

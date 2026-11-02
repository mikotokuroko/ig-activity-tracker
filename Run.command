#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python -u tracker.py run
printf '\nWorker stopped. Press Enter to close.\n'
read

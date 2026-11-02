#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python -u tracker.py check "$@"
result=$?
if [ "$result" -ne 0 ]; then
  echo "Check incomplete (exit $result). No setup success is being claimed."
fi
echo 'Press Enter to close.'
read
exit "$result"

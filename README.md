# Instagram Activity Tracker

Tracks follower and following lists through `instagrapi`, an unofficial Instagram API client. Saves SQLite history, exports JSON, and sends changes to a Telegram bot.

## Setup

On macOS, install [uv](https://docs.astral.sh/uv/), then double-click `Setup.command`. It prompts for the target username, request-delay preference, Instagram login and Telegram bot pairing. Create your bot with Telegram’s `@BotFather` first.

After setup, run `Check.command` for a single check. Login and Telegram pairing are saved; no need to repeat setup.

```sh
# Change target and delay preference
.venv/bin/python tracker.py configure

# Check with only the one-second base pause; saves this preference
.venv/bin/python tracker.py check --no-extra-delay

# Restore the additional 2–4-second delay
.venv/bin/python tracker.py check --extra-delay

# Run checks every 24 hours
.venv/bin/python tracker.py run
```

## Included

- Up to five passes per incomplete list, merged by account ID; stops after two passes recover nothing new.
- Incomplete scans preserve the baseline. Removal alerts require absence in two complete checks.
- `data/followers-following.json`: latest lists, counts, pass statistics and completeness.
- `Diagnose.command`: compares follower endpoints and saves page diagnostics.
- `Login.command`, `Telegram.command`: repeat login or bot pairing separately.
- `Export.command`: runs a check and exports JSON.
- `mcp_server.py`: read-only `tracker_status` and `recent_snapshots` tools over stdio.
- Docker Compose worker with persistent `./data` and restart policy.

For hosting, securely copy the project and local `data/` directory to your server, stop any local worker, then run `docker compose up -d --build`.

The `data/` directory contains credentials and account records and is excluded from Git and Docker builds. Keep it private. Instagram can return incomplete lists or request verification; API errors pause the tracker. Count matching is a consistency check, not an atomic snapshot.

## Tests

```sh
.venv/bin/python -m unittest -v
```

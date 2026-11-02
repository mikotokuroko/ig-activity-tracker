# Instagram Activity Tracker

Tracks follower and following lists through `instagrapi`, an unofficial Instagram API client. Saves SQLite history, exports JSON, and sends changes to a Telegram bot.

## Setup

On macOS, install [uv](https://docs.astral.sh/uv/), then double-click `Setup.command`. It prompts for the target username, tracking mode, request-delay preference, Instagram login and Telegram bot pairing. Create your bot with Telegram’s `@BotFather` first.

Double-click `Run.command` to run the local worker and register the Telegram command menu. Keep the Mac awake and the Terminal window open. It tracks one selected account at a time; switch it with `/target`. `/status` replies only while the host is running.

After setup, use Telegram `/check` or `tracker.py check` for a single check. Login and Telegram pairing are saved; no need to repeat setup.

```sh
# Change target, tracking mode and delay preference
.venv/bin/python tracker.py configure

# Counts only (fast; no username lists)
.venv/bin/python tracker.py check --mode counts

# Full lists and username changes, with a terminal progress bar
.venv/bin/python tracker.py check --mode names

# Check with only the one-second base pause; saves this preference
.venv/bin/python tracker.py check --no-extra-delay

# Restore the additional 2–4-second delay
.venv/bin/python tracker.py check --extra-delay

# Run checks every 24 hours
.venv/bin/python tracker.py run
```

Mode and delay choices are saved for subsequent checks. Use `tracker.py --help` for CLI options.

## Included

- Up to five passes per incomplete list, merged by account ID; stops after two passes recover nothing new.
- Incomplete scans preserve the baseline. Removal alerts require absence in two complete checks.
- Names mode: `data/followers-following.json` stores lists, counts, pass statistics and completeness.
- Counts mode: `data/counts.json` stores totals; Telegram reports count changes. Count history is separate from username history.
- `mcp_server.py`: read-only `tracker_status` and `recent_snapshots` tools over stdio.
- Telegram command menu: `/help`, `/status`, `/target username`, `/mode counts|names`, `/delay on|off`, `/interval hours`, `/check`, `/pause`, `/resume`, restricted to the paired private chat. The worker polls every ten seconds between scans; commands wait while a scan is running.


The `data/` directory contains credentials and account records and is excluded from Git. Keep it private. Instagram can return incomplete lists or request verification; API errors pause the tracker. Count matching is a consistency check, not an atomic snapshot.

## Tests

```sh
.venv/bin/python -m unittest -v
```

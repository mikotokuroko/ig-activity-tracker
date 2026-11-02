# Instagram tracker

Tracks the Instagram username you choose using your authenticated Instagram session. Saves follower and following snapshots in SQLite, compares stable user IDs, and sends observed additions, removals and renames to your Telegram private chat. The first scan establishes a baseline. The default interval is 24 hours.

## Local setup

Double-click `Setup.command`. It installs dependencies with uv, prompts for the target username and optional extra delay, asks for Instagram login in Terminal, pairs your Telegram bot and runs the first scan. Passwords and verification codes use hidden prompts. Create a bot through Telegram's @BotFather first; enter its token only in the local prompt. Pairing requires a unique `/start` message from the intended private chat.

For separate steps:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python tracker.py configure
.venv/bin/python tracker.py login
.venv/bin/python tracker.py telegram-setup
.venv/bin/python tracker.py check
.venv/bin/python tracker.py status
```

## Hosted server

Use a Linux server with Docker Compose and persistent disk. Copy this project and the locally created `data/` directory to a private directory on the server using SSH/SCP. The data directory contains the reusable Instagram session and Telegram credentials; do not upload it to GitHub or attach it to chat. Stop any local worker before transferring the database. Restrict the server directory to its owner.

```sh
docker compose up -d --build
docker compose logs --tail=30
```

The worker starts on boot through Docker's restart policy. `./data` persists across container replacement. No inbound ports are needed. To inspect state:

```sh
docker compose exec tracker python tracker.py status
```

For expired login, stop the hosted worker, run local `login`, securely replace only the hosted `session.json`, then run `docker compose run --rm tracker python tracker.py resume` and restart. For a rate-limit pause, wait until the restriction clears before resuming. A cloud IP may trigger an additional Instagram verification; a local session is not proof that the same session works on the server.

## MCP

The included MCP server reads stored results; it does not need to run for scheduled tracking. For a local MCP client configure the command as this project's absolute `.venv/bin/python` path, with the absolute `mcp_server.py` path as its argument. Set `TRACKER_DATA` if the database lives elsewhere. For a hosted database, run the stdio process over authenticated SSH. No public unauthenticated MCP endpoint is provided.

Tools: `tracker_status`, `recent_snapshots`.

## Behavior and limits

Double-click `Export.command` to fetch and export both lists using the saved session. Every scan that reaches the final count check writes `data/followers-following.json`, including incomplete results. It contains user IDs, usernames, fetched/profile counts, timestamps, and completeness flags for each list. The latest export replaces the previous export. An incomplete export does not become a tracking baseline. The export launcher also performs the normal check and may send the normal Telegram alert if that check succeeds.

Double-click `Check.command` to retry the first scan using the saved login and Telegram pairing. It prints collection progress and exact fetched/before/after counts. `data/last_scan.json` contains count diagnostics and pagination flags, with no usernames or credentials. A rejected scan exits nonzero; setup no longer reports success after rejection.

Incomplete reads or counts changing during collection are rejected. The previous baseline remains intact. Equal counts alone cannot prove a list is complete: Instagram's pagination is not an atomic snapshot. Removed accounts can represent unfollows, deactivation, blocking, or other changes.

Login/API errors pause collection and queue one alert. Pending Telegram messages are retried independently every minute. Delivery is at least once: a crash or timeout after Telegram receives a message but before local acknowledgement can cause a duplicate. Without Telegram configuration alerts remain queued locally. There is no history before the first scan.

`data/config.json` stores target, interval and Telegram configuration; `session.json` holds Instagram authentication; `tracker.sqlite3` holds history and pending alerts. Back up the data directory privately. Stop the worker before changing configuration. Run `tracker.py configure` to change the target; its numeric ID is resolved again on the next check. History remains separated by account ID.

This uses Instagram's unofficial API; restrictions or API changes may require manual intervention. It performs no Instagram follow, unfollow, post or message actions.

## Validation

```sh
.venv/bin/python -m unittest -v
```

Offline tests cover equal-count replacements, renames, baseline handling, incomplete scans, changing counts, Telegram retry and login-error pauses. Live retrieval must be checked with your own session. Hosted Docker deployment is separate from local setup.

### Multi-pass recovery

Each check merges up to five full passes per incomplete list by numeric account ID. It stops when the profile count is reached or two consecutive passes add no accounts. Profile counts are checked between retries and at the end. Results from earlier checks are never used to fill gaps. The JSON export includes per-pass rows, newly recovered accounts and unique totals. An incomplete check preserves the existing baseline.

Removal alerts require absence in two consecutive complete checks; reappearance during confirmation does not generate an added alert. Equal counts cannot exclude membership changes during a scan. Your own account is included when returned by Instagram, regardless of whether the website displays a Follow button.

### Request pacing

The one-second instagrapi request pause is always retained. The additional random 2–4-second delay defaults to enabled. Select it during `configure`, or save your preference when checking:

```sh
.venv/bin/python tracker.py check --no-extra-delay
.venv/bin/python tracker.py check --extra-delay
```

The setting applies to subsequent runs too. Instagram may still request verification at either speed.

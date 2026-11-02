"""Personal Instagram relationship snapshots and Telegram notifications."""
import argparse
import contextlib
import fcntl
import getpass
import json
import logging
import os
import re
from pathlib import Path
import secrets
import sys
import sqlite3
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('TRACKER_DATA', ROOT / 'data'))


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2))
    tmp.chmod(0o600)
    tmp.replace(path)


def config():
    p = DATA / 'config.json'
    return {'interval_hours': 24, 'extra_delay': True, **(json.loads(p.read_text()) if p.exists() else {})}


def configure():
    cfg = config()
    current = cfg.get('target', '')
    target = input(f'Instagram username to track [{current}]: ').strip().lstrip('@') or current
    if not re.fullmatch(r'[A-Za-z0-9_.]{1,30}', target):
        raise ValueError('Enter an Instagram username, not a URL.')
    target = target.lower()
    answer = input('Extra 2–4 second request delay? [Y/n]: ').strip().lower()
    if answer not in ('', 'y', 'yes', 'n', 'no'):
        raise ValueError('Enter y or n.')
    if target != current:
        with database() as db:
            db.execute("DELETE FROM state WHERE key IN ('target_id', 'last_attempt', 'last_success', 'last_error')")
    cfg.update(target=target, extra_delay=answer not in ('n', 'no'))
    save_json(DATA / 'config.json', cfg)
    print(f'Saved target @{target}; extra delay {"on" if cfg["extra_delay"] else "off"}.')


def database():
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'tracker.sqlite3')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS snapshots (
      id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, at TEXT NOT NULL, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS outbox (
      id INTEGER PRIMARY KEY, body TEXT NOT NULL, sent_at TEXT);
    CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    return db


def state(db, key, value=None):
    if value is None:
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else None
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, value))


def differences(old, new):
    result = []
    for kind in ('followers', 'following'):
        before, after = old[kind], new[kind]
        for uid in sorted(after.keys() - before.keys()):
            result.append(f'{kind}: added @{after[uid]}')
        for uid in sorted(before.keys() - after.keys()):
            result.append(f'{kind}: removed @{before[uid]}')
        for uid in sorted(before.keys() & after.keys()):
            if before[uid] != after[uid]:
                result.append(f'{kind}: renamed @{before[uid]} → @{after[uid]}')
    return result


def record(db, target_id, target, data):
    prev = db.execute('SELECT at,data FROM snapshots WHERE target_id=? ORDER BY id DESC LIMIT 1',
                      (target_id,)).fetchone()
    stamp = now()
    pending_key = f'pending_removals:{target_id}'
    pending = json.loads(state(db, pending_key) or '{}')
    next_pending = {}
    lines = []
    if prev:
        old = json.loads(prev[1])
        for kind in ('followers', 'following'):
            waiting = pending.get(kind, {})
            # A reappearing account was never reported removed.
            comparison = {**waiting, **old[kind]}
            lines.extend(f'{kind}: added @{data[kind][key]}'
                         for key in sorted(data[kind].keys() - comparison.keys()))
            lines.extend(f'{kind}: renamed @{comparison[key]} → @{data[kind][key]}'
                         for key in sorted(data[kind].keys() & comparison.keys())
                         if comparison[key] != data[kind][key])
            lines.extend(f'{kind}: removed @{waiting[key]}'
                         for key in sorted(waiting.keys() - data[kind].keys()))
            next_pending[kind] = {key: old[kind][key]
                                  for key in old[kind].keys() - data[kind].keys()}
    else:
        lines = ['Baseline saved. Future checks will report changes.']
    with db:
        state(db, pending_key, json.dumps(next_pending))
        db.execute('INSERT INTO snapshots(target_id,at,data) VALUES (?,?,?)',
                   (target_id, stamp, json.dumps(data)))
        if lines:
            header = f'@{target} · {stamp}\nFollowers: {len(data["followers"])} · Following: {len(data["following"])}\n'
            if prev:
                header += f'Compared with {prev[0]}\nObserved list changes; removal does not establish its cause.\n'
            # Keep messages below Telegram's length limit; send each chunk once.
            chunk = header
            for line in lines:
                if len(chunk) + len(line) > 3500:
                    db.execute('INSERT INTO outbox(body) VALUES (?)', (chunk,))
                    chunk = header
                chunk += line + '\n'
            db.execute('INSERT INTO outbox(body) VALUES (?)', (chunk,))


def telegram(token, method, payload):
    req = Request(f'https://api.telegram.org/bot{token}/{method}',
                  data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=40) as response:
            result = json.load(response)
    except Exception:
        raise RuntimeError('Telegram request failed; credentials and request URLs omitted.') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram rejected the request.')
    return result['result']


def flush(db, cfg):
    if not cfg.get('telegram_token') or not cfg.get('telegram_chat_id'):
        return
    for row_id, body in db.execute('SELECT id,body FROM outbox WHERE sent_at IS NULL ORDER BY id').fetchall():
        telegram(cfg['telegram_token'], 'sendMessage', {'chat_id': cfg['telegram_chat_id'],
                 'text': body, 'link_preview_options': {'is_disabled': True}})
        with db:
            db.execute('UPDATE outbox SET sent_at=? WHERE id=?', (now(), row_id))


class IncompleteRead(Exception):
    pass


def collect(client, uid):
    print('Reading profile counts…', flush=True)
    before = client.user_info_v1(uid)
    data = {}
    report = {'started_at': now(), 'lists': {}}
    for kind, field in [('followers', 'follower_count'), ('following', 'following_count')]:
        expected = getattr(before, field)
        print(f'Reading {kind}: profile reports {expected}…', flush=True)
        data[kind] = {}
        passes, stagnant = [], 0
        count_changed = False
        last_response = {}
        for attempt in range(1, 6):
            previous = len(data[kind])
            rows_read = 0
            rows = getattr(client, f'iter_user_{kind}_v1')(uid, amount=0, page_size=100)
            for u in rows:
                rows_read += 1
                data[kind][str(u.pk)] = u.username
            last_response = getattr(client, 'last_json', {}) or {}
            gained = len(data[kind]) - previous
            passes.append({'pass': attempt, 'rows': rows_read, 'new': gained,
                           'unique_total': len(data[kind])})
            print(f'{kind}: pass {attempt}, {gained} new, {len(data[kind])}/{expected} unique.', flush=True)
            stagnant = stagnant + 1 if gained == 0 else 0
            if len(data[kind]) >= expected or stagnant >= 2 or attempt == 5:
                break
            current = client.user_info_v1(uid)
            if getattr(current, field) != expected:
                count_changed = True
                break
        report['lists'][kind] = {
            'before': expected, 'fetched': len(data[kind]), 'passes': passes,
            'count_changed': count_changed,
            'has_next_cursor': bool(last_response.get('next_max_id')),
            'limited': last_response.get('should_limit_list_of_followers'),
        }
        print(f'{kind}: fetched {len(data[kind])} / expected {expected}.', flush=True)
    print('Rechecking profile counts…', flush=True)
    after = client.user_info_v1(uid)
    issues = []
    for kind, field in [('followers', 'follower_count'), ('following', 'following_count')]:
        report['lists'][kind]['after'] = getattr(after, field)
        if report['lists'][kind]['count_changed'] or getattr(before, field) != getattr(after, field) or len(data[kind]) != getattr(after, field):
            reason = 'count changed during scan' if getattr(before, field) != getattr(after, field) else 'incomplete list'
            issues.append(f'{kind}: fetched {len(data[kind])}, profile before={getattr(before, field)}, after={getattr(after, field)} ({reason})')
    report['finished_at'] = now()
    report['complete'] = not issues
    save_json(DATA / 'last_scan.json', report)
    export = {
        'target_id': str(uid),
        'started_at': report['started_at'],
        'finished_at': report['finished_at'],
        'complete': report['complete'],
        'issues': issues,
    }
    for kind in ('followers', 'following'):
        counts = report['lists'][kind]
        export[kind] = {
            **counts,
            'complete': not counts['count_changed'] and counts['before'] == counts['after'] == counts['fetched'],
            'accounts': [{'id': user_id, 'username': username}
                         for user_id, username in sorted(data[kind].items())],
        }
    export_path = DATA / 'followers-following.json'
    save_json(export_path, export)
    print(f'JSON exported: {export_path}', flush=True)
    if issues:
        raise IncompleteRead('; '.join(issues) + '. Baseline preserved; no snapshot saved.')
    return data


def new_client():
    from instagrapi import Client
    # Suppress third-party response logs, which can contain account/session data.
    logging.disable(logging.CRITICAL)
    client = Client()
    client.request_timeout = 1
    client.delay_range = [2, 4] if config()['extra_delay'] else None
    client.challenge_code_handler = lambda *args: (_ for _ in ()).throw(RuntimeError('Interactive login required'))
    return client


def check(db, cfg):
    if state(db, 'paused'):
        return 'Paused: run local login again, then resume.'
    client = new_client()
    try:
        client.load_settings(DATA / 'session.json')
        uid = state(db, 'target_id')
        if not uid:
            uid = str(client.user_info_by_username_v1(cfg['target']).pk)
            with db:
                state(db, 'target_id', uid)
        data = collect(client, uid)
        record(db, uid, cfg['target'], data)
        with db:
            state(db, 'last_success', now())
            db.execute('DELETE FROM state WHERE key="last_error"')
        save_json(DATA / 'session.json', client.get_settings())
        return 'Complete snapshot saved.'
    except IncompleteRead as exc:
        with db:
            state(db, 'last_error', str(exc))
        return str(exc)
    except Exception as exc:
        # Stop rather than repeatedly hit login challenges or rate limits.
        reason = type(exc).__name__
        with db:
            state(db, 'paused', reason)
            state(db, 'last_error', reason)
            db.execute('INSERT INTO outbox(body) VALUES (?)',
                       (f'Instagram tracker paused ({reason}). Inspect locally and log in again if needed. No list changes inferred.',))
        return f'Paused ({reason}).'


def login():
    from instagrapi.exceptions import TwoFactorRequired
    client = new_client()
    if (DATA / 'session.json').exists():
        client.load_settings(DATA / 'session.json')
    username = input('Instagram login username: ').strip()
    password = getpass.getpass('Instagram password (hidden, not saved): ')
    client.challenge_code_handler = lambda *args: getpass.getpass('Instagram email/SMS verification code: ')
    try:
        client.login(username, password)
    except TwoFactorRequired:
        client.login(username, password, verification_code=getpass.getpass('2FA code: '))
    save_json(DATA / 'session.json', client.get_settings())
    with database() as db:
        db.execute('DELETE FROM state WHERE key="paused"')
    print('Session saved locally. Password was not saved.')


def setup_telegram():
    cfg = config()
    token = getpass.getpass('Bot token from @BotFather (hidden): ').strip()
    bot = telegram(token, 'getMe', {})
    nonce = secrets.token_hex(8)
    print(f'Open https://t.me/{bot["username"]} and send: /start {nonce}')
    print('Waiting up to five minutes for that private-chat message…')
    deadline, offset = time.monotonic() + 300, 0
    while time.monotonic() < deadline:
        for update in telegram(token, 'getUpdates', {'offset': offset, 'timeout': 20, 'allowed_updates': ['message']}):
            offset = update['update_id'] + 1
            msg = update.get('message', {})
            if msg.get('chat', {}).get('type') == 'private' and msg.get('text') == f'/start {nonce}':
                cfg.update(telegram_token=token, telegram_chat_id=msg['chat']['id'])
                save_json(DATA / 'config.json', cfg)
                telegram(token, 'sendMessage', {'chat_id': cfg['telegram_chat_id'], 'text': 'Instagram tracker connected. Alerts will appear here.'})
                print('Telegram private chat verified and saved.')
                return
    raise RuntimeError('No matching Telegram start message received. Run telegram-setup again.')


def status():
    with database() as db:
        return {'target': config().get('target'), 'state': dict(db.execute('SELECT key,value FROM state')),
                'snapshots': db.execute('SELECT count(*) FROM snapshots').fetchone()[0],
                'pending_alerts': db.execute('SELECT count(*) FROM outbox WHERE sent_at IS NULL').fetchone()[0]}


def main():
    os.umask(0o077)
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['configure', 'login', 'telegram-setup', 'check', 'run', 'status', 'resume'])
    parser.add_argument('--extra-delay', action=argparse.BooleanOptionalAction, default=None,
                        help='Save whether to add 2–4 seconds per request (one-second base pause remains).')
    args = parser.parse_args()
    if args.command == 'status':
        print(json.dumps(status(), indent=2)); return
    with (DATA / 'worker.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another tracker process is running. Stop it before setup/check.') from None
        if args.extra_delay is not None:
            cfg = config()
            cfg['extra_delay'] = args.extra_delay
            save_json(DATA / 'config.json', cfg)
        if args.command == 'configure':
            configure(); return
        if args.command in ('check', 'run') and not config().get('target'):
            if not sys.stdin.isatty():
                raise RuntimeError('Run tracker.py configure interactively first.')
            configure()
        if args.command == 'login':
            login(); return
        if args.command == 'telegram-setup':
            setup_telegram(); return
        with contextlib.closing(database()) as db:
            if args.command == 'resume':
                with db:
                    db.execute('DELETE FROM state WHERE key="paused"')
                print('Resumed.'); return
            while True:
                cfg = config()
                last = state(db, 'last_attempt')
                due = not last or time.time() - float(last) >= max(1, cfg['interval_hours']) * 3600
                if args.command == 'check' or due:
                    with db:
                        state(db, 'last_attempt', str(time.time()))
                    print(check(db, cfg), flush=True)
                try:
                    flush(db, cfg)
                except RuntimeError as exc:
                    print(str(exc), flush=True)
                    if args.command == 'check':
                        return 3
                if args.command == 'check':
                    return 2 if state(db, 'last_error') or state(db, 'paused') else 0
                time.sleep(60)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}. Check setup locally; no credentials printed.')
        raise SystemExit(1)

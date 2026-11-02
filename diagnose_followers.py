"""Compare authenticated follower endpoints; save only sanitized page diagnostics."""
import fcntl
import json
import os
import sys
from pathlib import Path
import tracker


def fetch(client, uid, strategy, expected, progress=print):
    accounts, pages, seen_cursors = {}, [], set()
    cursor = None
    # Budget for the observed 25-row server pages, with room for overlap.
    # A budget exit is always incomplete, even when a continuation exists.
    for page in range(1, max(30, ((expected + 24) // 25) * 3) + 1):
        if strategy == 'v1_chronological':
            params = {'count': 100, 'rank_token': client.rank_token,
                      'search_surface': 'follow_list_page', 'query': '',
                      'enable_groups': 'true', 'order': 'date_followed_latest'}
            if cursor:
                params['max_id'] = cursor
            response = client.private_request(f'friendships/{uid}/followers/', params=params)
        else:
            result = client.private_graphql_followers_list(
                uid, client.rank_token, max_id=cursor, order='date_followed_latest')
            response = client._private_graphql_root(result, 'xdt_api__v1__friendships__followers')
        if not isinstance(response, dict) or not isinstance(response.get('users'), list):
            raise RuntimeError('Unexpected follower response structure')
        rows = response['users']
        previous = len(accounts)
        for row in rows:
            uid_value = row.get('pk') or row.get('id')
            if uid_value is None or not isinstance(row.get('username'), str):
                raise RuntimeError('Unexpected account record')
            accounts[str(uid_value)] = row['username']
        next_cursor = response.get('next_max_id')
        repeated = bool(next_cursor) and str(next_cursor) in seen_cursors
        details = {'page': page, 'returned': len(rows), 'new': len(accounts) - previous,
                   'duplicates': len(rows) - (len(accounts) - previous),
                   'unique_total': len(accounts), 'has_next': bool(next_cursor),
                   'repeated_cursor': repeated,
                   'limited': response.get('should_limit_list_of_followers'),
                   'has_more': response.get('has_more')}
        pages.append(details)
        progress(f'{strategy}: page {page}, new {details["new"]}, duplicates {details["duplicates"]}, total {len(accounts)}/{expected}, next={bool(next_cursor)}')
        if not next_cursor:
            return accounts, pages, 'no_next_cursor'
        if repeated:
            return accounts, pages, 'repeated_cursor'
        if not rows:
            return accounts, pages, 'empty_page_with_cursor'
        seen_cursors.add(str(next_cursor))
        cursor = next_cursor
    return accounts, pages, 'page_budget'


def main():
    os.umask(0o077)
    tracker.DATA.mkdir(parents=True, exist_ok=True)
    report = {'started_at': tracker.now(), 'attempts': []}
    path = tracker.DATA / 'follower-diagnosis.json'
    with (tracker.DATA / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        c = tracker.new_client()
        c.load_settings(tracker.DATA / 'session.json')
        with tracker.database() as db:
            uid = tracker.state(db, 'target_id')
            if tracker.state(db, 'paused'):
                print('Tracker is paused. Resolve its recorded error before diagnosing.'); return 2
        if not uid:
            raise RuntimeError('Run initial setup before diagnosis')
        for strategy in ('v1_chronological', 'graphql_chronological'):
            attempt = {'strategy': strategy}
            report['attempts'].append(attempt)
            try:
                before = c.user_info_v1(uid).follower_count
                accounts, pages, termination = fetch(c, uid, strategy, before,
                                                     progress=lambda s: print(s, flush=True))
                after = c.user_info_v1(uid).follower_count
                complete = before == after == len(accounts) and termination == 'no_next_cursor'
                attempt.update(before=before, after=after, fetched=len(accounts),
                               pages=pages, termination=termination, complete=complete)
                tracker.save_json(tracker.DATA / f'followers-{strategy}.json',
                                  {'at': tracker.now(), 'complete': complete,
                                   'accounts': [{'id': k, 'username': v} for k, v in accounts.items()]})
                tracker.save_json(path, report)
                if complete:
                    print(f'PASS: {strategy} returned all {after} accounts. Diagnostic saved: {path}')
                    print('No baseline or configuration changed. This result can now guide the fix.')
                    return 0
                print(f'INCOMPLETE: {strategy} returned {len(accounts)}/{after}; {termination}', flush=True)
            except Exception as exc:
                # Do not switch endpoints after a challenge, restriction or transport error.
                attempt['error_type'] = type(exc).__name__
                tracker.save_json(path, report)
                print(f'STOPPED: {type(exc).__name__}. Diagnostic saved: {path}')
                return 2
    print(f'Neither endpoint returned a complete list. Diagnostic saved: {path}')
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}; no credential details printed.')
        sys.exit(2)

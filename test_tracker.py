import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = tracker.DATA
        tracker.DATA = Path(self.tmp.name)
        self.db = tracker.database()

    def tearDown(self):
        self.db.close()
        tracker.DATA = self.old
        self.tmp.cleanup()

    def test_multipass_recovers_by_id_including_self(self):
        passes = iter([[1, 2, 2], [2, 3]])
        client = SimpleNamespace(user_info_v1=lambda uid: SimpleNamespace(follower_count=3, following_count=0),
            iter_user_followers_v1=lambda *a, **k: iter(SimpleNamespace(pk=i, username=f'u{i}') for i in next(passes)),
            iter_user_following_v1=lambda *a, **k: iter([]))
        result = tracker.collect(client, '10')
        self.assertEqual(set(result['followers']), {'1', '2', '3'})
        export = json.loads((tracker.DATA / 'followers-following.json').read_text())
        self.assertEqual([p['new'] for p in export['followers']['passes']], [2, 1])
        self.assertTrue(export['complete'])

    def test_no_progress_stops_and_next_check_starts_empty(self):
        calls = []
        def rows(*a, **k):
            calls.append(1)
            return iter([SimpleNamespace(pk=1, username='a')])
        client = SimpleNamespace(user_info_v1=lambda uid: SimpleNamespace(follower_count=2, following_count=0),
            iter_user_followers_v1=rows, iter_user_following_v1=lambda *a, **k: iter([]))
        for _ in range(2):
            with self.assertRaises(tracker.IncompleteRead): tracker.collect(client, '10')
        self.assertEqual(len(calls), 6)

    def test_removal_requires_two_checks_and_is_sent_once(self):
        for followers in ({'1': 'a'}, {}, {}, {}):
            tracker.record(self.db, '10', 'test', {'followers': followers, 'following': {}})
            if self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0] == 2:
                self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        messages = [r[0] for r in self.db.execute('SELECT body FROM outbox')]
        self.assertEqual(sum('removed @a' in m for m in messages), 1)

    def test_reappearing_account_has_no_false_add_or_remove(self):
        for followers in ({'1': 'a'}, {}, {'1': 'a'}):
            tracker.record(self.db, '10', 'test', {'followers': followers, 'following': {}})
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_configure_changes_target_and_preserves_credentials(self):
        tracker.save_json(tracker.DATA / 'config.json', {'target': 'old', 'telegram_token': 'fake'})
        with self.db:
            tracker.state(self.db, 'target_id', '99')
        with patch('builtins.input', side_effect=['@new.name', 'n']):
            tracker.configure()
        self.assertEqual(tracker.config()['target'], 'new.name')
        self.assertFalse(tracker.config()['extra_delay'])
        self.assertEqual(tracker.config()['telegram_token'], 'fake')
        self.assertIsNone(tracker.state(self.db, 'target_id'))

    def test_request_pacing_option_retains_one_second(self):
        for enabled in (True, False):
            tracker.save_json(tracker.DATA / 'config.json', {'extra_delay': enabled})
            with patch('instagrapi.Client') as factory:
                client = tracker.new_client()
                self.assertEqual(client.request_timeout, 1)
                self.assertEqual(client.delay_range, [2, 4] if enabled else None)

    def test_equal_count_replacement_and_rename(self):
        old = {'followers': {'1': 'a', '2': 'b'}, 'following': {}}
        new = {'followers': {'1': 'renamed', '3': 'c'}, 'following': {}}
        self.assertEqual(tracker.differences(old, new), [
            'followers: added @c', 'followers: removed @b', 'followers: renamed @a → @renamed'])

    def test_baseline_then_unchanged_has_one_alert(self):
        data = {'followers': {'1': 'a'}, 'following': {}}
        tracker.record(self.db, '10', 'test', data)
        tracker.record(self.db, '10', 'test', data)
        self.assertEqual(self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_partial_read_rejected(self):
        client = SimpleNamespace(user_info_v1=lambda uid: SimpleNamespace(follower_count=2, following_count=0),
            iter_user_followers_v1=lambda *a, **k: iter([SimpleNamespace(pk=1, username='a')]),
            iter_user_following_v1=lambda *a, **k: iter([]))
        with self.assertRaises(tracker.IncompleteRead):
            tracker.collect(client, '10')

    def test_changes_during_scan_rejected(self):
        counts = iter([1, 2])
        client = SimpleNamespace(user_info_v1=lambda uid: SimpleNamespace(follower_count=next(counts), following_count=0),
            iter_user_followers_v1=lambda *a, **k: iter([SimpleNamespace(pk=1, username='a')]),
            iter_user_following_v1=lambda *a, **k: iter([]))
        with self.assertRaises(tracker.IncompleteRead):
            tracker.collect(client, '10')

    def test_send_failure_preserves_outbox_then_success_marks_sent(self):
        tracker.record(self.db, '10', 'test', {'followers': {}, 'following': {}})
        cfg = {'telegram_token': 'fake', 'telegram_chat_id': 1}
        with patch.object(tracker, 'telegram', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                tracker.flush(self.db, cfg)
        self.assertIsNone(self.db.execute('SELECT sent_at FROM outbox').fetchone()[0])
        with patch.object(tracker, 'telegram', return_value={}) as send:
            tracker.flush(self.db, cfg)
            tracker.flush(self.db, cfg)
            self.assertEqual(send.call_count, 1)

    def test_challenge_pauses_without_false_changes(self):
        client = SimpleNamespace(load_settings=lambda path: (_ for _ in ()).throw(RuntimeError('secret')))
        with patch.object(tracker, 'new_client', return_value=client):
            self.assertEqual(tracker.check(self.db, {'target': 'test'}), 'Paused (RuntimeError).')
            tracker.check(self.db, {'target': 'test'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 0)
        self.assertNotIn('secret', self.db.execute('SELECT body FROM outbox').fetchone()[0])

    def test_check_cli_rejected_scan_returns_failure(self):
        tracker.save_json(tracker.DATA / "config.json", {"target": "test"})
        with patch('sys.argv', ['tracker.py', 'check']), patch.object(tracker, 'new_client') as factory, patch.object(tracker, 'collect', side_effect=tracker.IncompleteRead('Incomplete list')), patch.object(tracker, 'flush'):
            factory.return_value.user_info_by_username_v1.return_value.pk = '1'
            self.assertEqual(tracker.main(), 2)

    def test_incomplete_error_identifies_counts(self):
        client = SimpleNamespace(user_info_v1=lambda uid: SimpleNamespace(follower_count=2, following_count=0),
            iter_user_followers_v1=lambda *a, **k: iter([SimpleNamespace(pk=1, username='a')]),
            iter_user_following_v1=lambda *a, **k: iter([]))
        with self.assertRaisesRegex(tracker.IncompleteRead, r'followers: fetched 1, profile before=2, after=2'):
            tracker.collect(client, '10')
        exported = json.loads((tracker.DATA / 'followers-following.json').read_text())
        self.assertFalse(exported['complete'])
        self.assertFalse(exported['followers']['complete'])
        self.assertTrue(exported['following']['complete'])
        self.assertEqual(exported['followers']['accounts'], [{'id': '1', 'username': 'a'}])
        self.assertEqual(self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

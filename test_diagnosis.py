import unittest
from types import SimpleNamespace
from diagnose_followers import fetch


class DiagnosisTests(unittest.TestCase):
    def test_server_returns_25_despite_requesting_100(self):
        responses = iter([
            dict(users=[{'pk': i + 1, 'username': f'u{i}'} for i in range(start, min(start + 25, 355))],
                 **({'next_max_id': str(start + 25)} if start + 25 < 355 else {}))
            for start in range(0, 355, 25)
        ])
        client = SimpleNamespace(rank_token='fixture', private_request=lambda *a, **k: next(responses))
        accounts, pages, reason = fetch(client, '10', 'v1_chronological', 355, lambda s: None)
        self.assertEqual(reason, 'no_next_cursor')
        self.assertEqual(len(accounts), 355)

    def test_overlapping_pages_and_order(self):
        responses = iter([
            {'users': [{'pk': 1, 'username': 'a'}, {'pk': 2, 'username': 'b'}], 'next_max_id': 'second'},
            {'users': [{'pk': 2, 'username': 'b'}, {'pk': 3, 'username': 'c'}]},
        ])
        calls = []
        def request(endpoint, params):
            calls.append(params)
            return next(responses)
        client = SimpleNamespace(rank_token='fixture', private_request=request)
        accounts, pages, reason = fetch(client, '10', 'v1_chronological', 3, lambda s: None)
        self.assertEqual(len(accounts), 3)
        self.assertEqual(pages[1]['duplicates'], 1)
        self.assertEqual(calls[1]['max_id'], 'second')
        self.assertTrue(all(p['order'] == 'date_followed_latest' for p in calls))
        self.assertEqual(reason, 'no_next_cursor')

    def test_repeated_cursor_ends_without_claiming_completion(self):
        client = SimpleNamespace(rank_token='fixture', private_request=lambda *a, **k:
            {'users': [{'pk': 1, 'username': 'a'}], 'next_max_id': 'same'})
        _, pages, reason = fetch(client, '10', 'v1_chronological', 3, lambda s: None)
        self.assertEqual(len(pages), 2)
        self.assertEqual(reason, 'repeated_cursor')

    def test_graphql_uses_full_response_without_slicing(self):
        client = SimpleNamespace(rank_token='fixture',
            private_graphql_followers_list=lambda *a, **k: {'users': [{'pk': 1, 'username': 'a'}]},
            _private_graphql_root=lambda value, key: value)
        accounts, _, reason = fetch(client, '10', 'graphql_chronological', 1, lambda s: None)
        self.assertEqual(accounts, {'1': 'a'})
        self.assertEqual(reason, 'no_next_cursor')

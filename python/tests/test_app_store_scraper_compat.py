"""Offline only: exported rows are real; reply/error variants are synthetic."""
import copy
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app_store_scraper_compat import ACTOR, AppStore

ROWS = json.loads((Path(__file__).parent / 'fixtures/apple_reviews.json').read_text())['rows']


class CompatibilityTests(unittest.TestCase):
    def app(self, rows=None, run=None):
        client = Mock()
        client.actor.return_value.call.return_value = run or SimpleNamespace(
            status='SUCCEEDED', default_dataset_id='offline-board-export')
        client.dataset.return_value.iterate_items.return_value = iter(copy.deepcopy(ROWS if rows is None else rows))
        return AppStore('US', 'spotify', 324684580, client=client), client

    def test_one_import_swap_board_rows(self):
        app, client = self.app()
        self.assertIsNone(app.review(how_many=2, sleep=5))
        self.assertEqual(app.reviews_count, 2)
        expected = next(r for r in ROWS if r['appId'] == '324684580')
        self.assertEqual(app.reviews[0], dict(date=datetime(2026, 10, 11, 11, 42, 25),
            review=expected['text'], rating=expected['rating'], isEdited=expected['isEdited'],
            title=expected['title'], userName=None))
        client.actor.assert_called_once_with(ACTOR)
        client.actor.return_value.call.assert_called_once_with(run_input={
            'apps':['324684580'], 'countries':['us'], 'maxReviewsPerApp':2,
            'sort':'newest', 'onlyNew':False}, max_total_charge_usd=Decimal('1.00'))

    def test_all_nine_real_rows(self):
        for app_id in dict.fromkeys(r['appId'] for r in ROWS):
            with self.subTest(app_id=app_id):
                app, client = self.app()
                app.app_id = int(app_id)
                app.review(how_many=100)
                originals = [r for r in ROWS if r['appId'] == app_id]
                self.assertEqual(app.reviews_count, len(originals))
                self.assertEqual([r['review'] for r in app.reviews], [r['text'] for r in originals])
                self.assertTrue(all(isinstance(r['date'], datetime) and r['date'].tzinfo is None for r in app.reviews))

    def test_after_inclusive_naive(self):
        app, client = self.app()
        app.review(after=datetime(2026,10,11,11,42,25))
        self.assertEqual(app.reviews_count, 1)
        self.assertEqual(client.actor.return_value.call.call_args.kwargs['run_input']['sinceDate'], '2026-10-11')

    def test_after_aware_utc_conversion(self):
        app, client = self.app()
        app.review(after=datetime(2026,10,11,13,42,25,tzinfo=timezone(timedelta(hours=2))))
        self.assertEqual(app.reviews_count, 1)

    def test_append_and_count(self):
        app, client = self.app()
        app.review(2)
        client.dataset.return_value.iterate_items.return_value = iter(copy.deepcopy(ROWS))
        app.review(1)
        self.assertEqual(app.reviews_count, 3)
        self.assertEqual(client.actor.return_value.call.call_count, 2)

    def test_reply_shape_synthetic_not_board_claim(self):
        row = copy.deepcopy(ROWS[0])
        row.update(developerReply='Thanks', developerReplyDate='2026-10-12T00:00:00Z')
        app, client = self.app([row])
        app.review(1)
        self.assertEqual(app.reviews[0]['developerResponse'],
            {'id':None, 'body':'Thanks', 'modified':'2026-10-12T00:00:00Z'})

    def test_charge_override(self):
        app, client = self.app()
        app.max_total_charge_usd = Decimal('0.25')
        app.review(1)
        self.assertEqual(client.actor.return_value.call.call_args.kwargs['max_total_charge_usd'], Decimal('0.25'))

    def test_default_capped(self):
        app, client = self.app()
        app.review()
        self.assertEqual(client.actor.return_value.call.call_args.kwargs['run_input']['maxReviewsPerApp'], 5000)

    def test_empty_success(self):
        app, client = self.app([])
        app.review(1)
        self.assertEqual(app.reviews_count, 0)

    def test_failed_run_raises(self):
        for run in [SimpleNamespace(status='FAILED'), SimpleNamespace(status='TIMED-OUT')]:
            app, client = self.app(run=run)
            with self.assertRaisesRegex(RuntimeError, 'did not succeed'): app.review(1)
            client.dataset.assert_not_called()

    def test_no_run(self):
        app, client = self.app()
        client.actor.return_value.call.return_value = None
        with self.assertRaises(RuntimeError): app.review(1)

    def test_missing_dataset(self):
        app, client = self.app(run=SimpleNamespace(status='SUCCEEDED'))
        with self.assertRaisesRegex(RuntimeError, 'no dataset'): app.review(1)

    def test_legacy_sdk_dict(self):
        app, client = self.app(run={'status':'SUCCEEDED','defaultDatasetId':'offline-board-export'})
        app.review(1)
        self.assertEqual(app.reviews_count, 1)

    def test_error_row_does_not_mutate_state(self):
        app, client = self.app([ROWS[0], {'error':'source refused'}])
        with self.assertRaisesRegex(RuntimeError, 'source refused'): app.review(3)
        self.assertEqual(app.reviews, [])
        self.assertEqual(app.reviews_count, 0)

    def test_invalid_date_is_explicit(self):
        row = dict(ROWS[0], date='not-a-date')
        app, client = self.app([row])
        with self.assertRaises(ValueError): app.review(1)
        self.assertEqual(app.reviews_count, 0)

    def test_input_validation_no_actor_call(self):
        app, client = self.app()
        for value in [0,-1,1.5,True]:
            with self.assertRaises(ValueError): app.review(value)
        with self.assertRaises(TypeError): app.review(after='2026-10-11')
        client.actor.assert_not_called()

    def test_constructor_validation(self):
        for app_id in [None,'ios:324684580','324684580x']:
            with self.assertRaises(ValueError): AppStore('us','spotify',app_id)
        for charge in [0,-1,'NaN','Infinity']:
            with self.assertRaises(ValueError): AppStore('us','spotify',324684580,max_total_charge_usd=charge)

    def test_missing_token_no_network(self):
        with patch.dict('os.environ', {}, clear=True):
            app = AppStore('us','spotify',324684580)
            with self.assertRaisesRegex(RuntimeError,'APIFY_TOKEN'): app.review(1)

    def test_wrong_store_and_country_excluded(self):
        rows = [dict(ROWS[0], store='google'),dict(ROWS[0],country='gb'),ROWS[0]]
        app, client = self.app(rows)
        app.review(3)
        self.assertEqual(app.reviews_count, 1)


if __name__ == '__main__':
    unittest.main()

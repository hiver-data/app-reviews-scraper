"""Offline only: the fixture rows are real output of the Actor's code (local run, 2026-10-14)."""
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from play_package_names import ACTOR, COLUMNS, search_play

ROWS = json.loads((Path(__file__).parent / "fixtures/play_search_rows.json").read_text())["rows"]


class PlayPackageNameTests(unittest.TestCase):
    def client(self, run=None):
        client = Mock()
        client.actor.return_value.call.return_value = run or SimpleNamespace(
            status="SUCCEEDED", default_dataset_id="offline")
        client.dataset.return_value.iterate_items.return_value = iter(ROWS)
        return client

    def test_input_sent_to_actor(self):
        client = self.client()
        search_play(client, ["spotify", "duolingo", "whatsapp", "calm"], top=3)
        client.actor.assert_called_once_with(ACTOR)
        client.actor.return_value.call.assert_called_once_with(run_input={
            "stores": ["google_play"], "searchTerms": ["spotify", "duolingo", "whatsapp", "calm"],
            "maxResultsPerTerm": 3, "country": "us", "language": "en"}, max_total_charge_usd=Decimal("0.10"))

    def test_top_hit_has_package_name(self):
        rows = search_play(self.client(), ["spotify", "duolingo", "whatsapp", "calm"], top=3)
        top = {r["searchTerm"]: r["appId"] for r in rows if r["rank"] == 1}
        self.assertEqual(top, {"spotify": "com.spotify.music", "duolingo": "com.duolingo",
                               "whatsapp": "com.whatsapp", "calm": "com.calm.android"})
        self.assertTrue(all(r["appId"] for r in rows))
        self.assertTrue(all(list(r) == COLUMNS for r in rows))

    def test_failed_run_raises(self):
        with self.assertRaises(RuntimeError):
            search_play(self.client(SimpleNamespace(status="FAILED", default_dataset_id=None)), ["Spotify"])


if __name__ == "__main__":
    unittest.main()

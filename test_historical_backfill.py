import unittest

import pandas as pd

from historical_backfill import build_equity


class HistoricalBackfillTests(unittest.TestCase):
    def test_overlapping_positions_fix_risk_when_opened(self):
        events = pd.DataFrame([
            {
                "timestamp": "2026-01-01", "exit_date": "2026-01-03", "symbol": "AAA", "tf": "1d",
                "strategy": "Confluence", "r_mult": 1.0, "outcome": "时间止损",
            },
            {
                "timestamp": "2026-01-02", "exit_date": "2026-01-04", "symbol": "BBB", "tf": "1d",
                "strategy": "Confluence", "r_mult": -1.0, "outcome": "止损",
            },
        ])
        ledger = build_equity(events)
        exits = ledger[ledger["event_type"] == "exit"].reset_index(drop=True)

        self.assertEqual(exits["risk_dollars"].tolist(), [750.0, 750.0])
        self.assertEqual(exits["equity_after"].tolist(), [100750.0, 100000.0])

    def test_duplicate_active_position_is_not_opened_twice(self):
        events = pd.DataFrame([
            {
                "timestamp": "2026-01-01", "exit_date": "2026-01-04", "symbol": "AAA", "tf": "1d",
                "strategy": "Confluence", "r_mult": 1.0, "outcome": "时间止损",
            },
            {
                "timestamp": "2026-01-02", "exit_date": "2026-01-03", "symbol": "AAA", "tf": "1d",
                "strategy": "Confluence", "r_mult": 2.0, "outcome": "时间止损",
            },
        ])
        ledger = build_equity(events)

        self.assertIn("skip_duplicate_active", ledger["decision"].tolist())
        self.assertEqual((ledger["event_type"] == "exit").sum(), 1)


if __name__ == "__main__":
    unittest.main()

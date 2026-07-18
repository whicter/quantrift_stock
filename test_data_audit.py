import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import data_audit
import fetch_ib_data
from fetch_ib_data import merge_bars


class DataAuditTests(unittest.TestCase):
    def test_stale_daily_file_requires_ib_refresh(self):
        with TemporaryDirectory() as directory, patch.object(data_audit, "DATA_DIR", Path(directory)):
            path = Path(directory) / "TEST_1d.csv"
            pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-06-01"])).to_csv(path)
            row = data_audit.audit_symbol("TEST", "1d", pd.Timestamp("2026-07-18"))
            self.assertEqual(row["status"], "needs_ib_refresh")

    def test_audit_reads_recorded_data_source(self):
        with TemporaryDirectory() as directory, patch.object(data_audit, "DATA_DIR", Path(directory)):
            path = Path(directory) / "TEST_1d.csv"
            pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-07-17"])).to_csv(path)
            (Path(directory) / ".data_sources.json").write_text('{"TEST|1d": {"source": "yfinance"}}')
            row = data_audit.audit_symbol("TEST", "1d", pd.Timestamp("2026-07-18"))
            self.assertEqual(row["source"], "yfinance")

    def test_four_hour_is_excluded_from_ib_requests(self):
        audit = pd.DataFrame([
            {"symbol": "TEST", "tf": "1h", "status": "needs_ib_refresh", "start": "", "end": ""},
            {"symbol": "TEST", "tf": "4h", "status": "needs_ib_refresh", "start": "", "end": ""},
        ])
        plan = data_audit.ib_refresh_plan(audit)
        self.assertEqual(plan["ib_tf"].tolist(), ["1h"])

    def test_ib_merge_prefers_new_bar_and_preserves_old_history(self):
        old = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        new = pd.DataFrame({"Close": [12.0, 13.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-03"]))
        merged = merge_bars(old, new)
        self.assertEqual(merged["Close"].tolist(), [10.0, 12.0, 13.0])

    def test_ib_request_has_a_bounded_timeout(self):
        class FakeIB:
            def qualifyContracts(self, contract):
                return [contract]

            def reqHistoricalData(self, contract, **kwargs):
                self.kwargs = kwargs
                return []

        ib = FakeIB()
        with patch.object(fetch_ib_data, "Stock", return_value=object()), patch.object(fetch_ib_data.time, "sleep"):
            self.assertIsNone(fetch_ib_data.fetch_bars(ib, "TEST", "1d"))
        self.assertEqual(ib.kwargs["timeout"], fetch_ib_data.REQUEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()

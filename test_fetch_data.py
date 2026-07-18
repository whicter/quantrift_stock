import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import fetch_data


class FetchDataTests(unittest.TestCase):
    def test_merge_prefers_fresh_yfinance_bar(self):
        old = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        new = pd.DataFrame({"Close": [12.0, 13.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-03"]))
        merged = fetch_data.merge_bars(old, new)
        self.assertEqual(merged["Close"].tolist(), [10.0, 12.0, 13.0])

    def test_save_merge_preserves_history_and_records_yfinance_source(self):
        with TemporaryDirectory() as directory:
            data_dir = Path(directory)
            path = data_dir / "TEST_1d.csv"
            pd.DataFrame({"Close": [10.0]}, index=pd.to_datetime(["2026-01-01"])).to_csv(path)
            incoming = pd.DataFrame({"Close": [11.0]}, index=pd.to_datetime(["2026-01-02"]))
            with patch.object(fetch_data, "SOURCE_MANIFEST", data_dir / ".data_sources.json"):
                saved = fetch_data.save_bars(path, incoming, "TEST", "1d", merge=True)
            self.assertEqual(len(saved), 2)
            manifest = json.loads((data_dir / ".data_sources.json").read_text())
            self.assertEqual(manifest["TEST|1d"]["source"], "yfinance")

    def test_intraday_download_uses_bounded_request_timeout(self):
        frame = pd.DataFrame(
            {"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]},
            index=pd.date_range("2026-01-01", periods=1, freq="h", tz="America/New_York"),
        )
        with patch.object(fetch_data.yf, "download", return_value=frame) as download:
            fetch_data.download_1h("TEST", "2023-01-01")
        self.assertEqual(download.call_args.kwargs["timeout"], fetch_data.REQUEST_TIMEOUT)
        self.assertEqual(download.call_args.kwargs["period"], "729d")


if __name__ == "__main__":
    unittest.main()

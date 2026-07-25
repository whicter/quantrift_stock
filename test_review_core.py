import json
import unittest

import pandas as pd

from meta_label import MIN_SAMPLES, train
from review_core import eval_confluence, eval_mr, eval_rsi2, evaluate


def _price(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="D"))


class ReviewCoreTests(unittest.TestCase):
 def test_confluence_staged_weighted_r(self):
    price = _price([
        {"Open": 100, "High": 101, "Low": 99, "Close": 100},
        {"Open": 101, "High": 102, "Low": 100, "Close": 101},  # TP1
        {"Open": 103, "High": 104, "Low": 102, "Close": 103},  # TP2
        {"Open": 102, "High": 103, "Low": 100, "Close": 101},  # SSL exit
    ])
    price["utTS"] = 98
    price["sslExit"] = [99, 100, 102, 102]
    row = {"bar_date": "2026-01-01", "entry_price": 100, "atr": 1, "tp1": 101, "tp2": 103,
           "sl": 98, "direction": "做多", "params_json": json.dumps({"use_fixed_initial_sl": True})}
    result = eval_confluence(row, price, 3)
    self.assertEqual(result["outcome"], "SSL追踪出场")
    self.assertEqual(result["r_mult"], 1.66)


 def test_rsi2_split_exit_and_time_stop(self):
    price = _price([
        {"Open": 100, "High": 101, "Low": 99, "Close": 100},
        {"Open": 101, "High": 102, "Low": 100, "Close": 101},
        {"Open": 103, "High": 104, "Low": 102, "Close": 103},
    ])
    row = {"bar_date": "2026-01-01", "entry_price": 100, "atr": 1, "direction": "做多",
           "params_json": json.dumps({"use_split_exit": True, "rsi2_half_exit": 0, "atr_trail_mult": 10, "atr_sl_mult": 2})}
    result = eval_rsi2(row, price, 2)
    self.assertEqual(result["outcome"], "时间止损")
    self.assertGreater(result["r_mult"], 0)


 def test_mr_atr_trail_exit(self):
    price = _price([
        {"Open": 100, "High": 101, "Low": 99, "Close": 100},
        {"Open": 103, "High": 104, "Low": 102, "Close": 103},  # ratchets trail up
        {"Open": 100, "High": 101, "Low": 98, "Close": 99},    # trail hit
    ])
    price["_atr"] = 1.0
    row = {"bar_date": "2026-01-01", "entry_price": 100, "atr": 1, "direction": "做多",
           "params_json": json.dumps({"atr_trail_mult": 2.0, "atr_sl_mult": 5.0})}
    result = eval_mr(row, price, 3)
    self.assertEqual(result["outcome"], "ATR追踪出场")
    # trail after bar2 = 103 - 2*1 = 101; bar3 close 99 < 101 -> exit at 99
    self.assertEqual(result["r_mult"], -1.0)


 def test_evaluate_does_not_route_mrvl_wideexit_to_mr(self):
    """'MRVL_WideExit' contains the substring 'mr' and must stay on the Confluence path."""
    price = _price([
        {"Open": 100, "High": 101, "Low": 99, "Close": 100},
        {"Open": 101, "High": 102, "Low": 100, "Close": 101},
    ])
    row = {"strategy": "MRVL_WideExit", "bar_date": "2026-01-01", "entry_price": 100,
           "atr": 1, "tp1": 105, "tp2": 110, "sl": 95, "direction": "做多"}
    result = evaluate(row, price, 2)
    self.assertIn("ambiguity", result)  # only eval_confluence's return shape has this key


 def test_meta_label_refuses_small_sample(self):
    from pathlib import Path
    result = train(pd.DataFrame({"r_mult": [1.0] * (MIN_SAMPLES - 1)}), Path("/tmp/meta-label-test.json"))
    self.assertFalse(result["trained"])


if __name__ == "__main__":
    unittest.main()

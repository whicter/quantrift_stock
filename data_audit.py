"""Audit locally stored historical bars and prepare a non-destructive IB refresh plan.

This script never connects to IB and never changes data/*.csv.  It reports
coverage first so a separate, explicit IB fetch can fill only verified gaps.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml


DATA_DIR = Path("data")
LOG_DIR = Path("logs")
TIMEFRAMES = ("1h", "4h", "1d")
FRESHNESS_DAYS = {"1h": 3, "4h": 3, "1d": 3}


def configured_symbols() -> list[str]:
    with open("config.yaml") as fh:
        cfg = yaml.safe_load(fh)
    symbols: set[str] = set()
    for group in cfg["symbols"].values():
        symbols.update(group)
    # Shadow-only candidate whose data is outside the primary live pool.
    symbols.add("RKLB")
    return sorted(symbols)


def audit_symbol(symbol: str, tf: str, now: pd.Timestamp) -> dict:
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    row = {"symbol": symbol, "tf": tf, "path": str(path), "exists": path.exists()}
    if not path.exists():
        return {**row, "bars": 0, "start": "", "end": "", "status": "missing", "source": "unknown"}
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        index = pd.to_datetime(df.index).tz_localize(None).sort_values()
        if index.empty:
            return {**row, "bars": 0, "start": "", "end": "", "status": "empty", "source": "unknown"}
        end = pd.Timestamp(index.max()).normalize()
        stale_after = now.normalize() - timedelta(days=FRESHNESS_DAYS[tf])
        return {
            **row,
            "bars": len(df),
            "start": index.min().strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "status": "fresh" if end >= stale_after else "needs_ib_refresh",
            # Existing CSV predates source manifests, so provenance is unknown.
            "source": "legacy_unknown",
        }
    except Exception as exc:
        return {**row, "bars": 0, "start": "", "end": "", "status": f"invalid: {exc}", "source": "unknown"}


def build_audit(now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="America/Los_Angeles").tz_localize(None)
    rows = [audit_symbol(symbol, tf, now) for symbol in configured_symbols() for tf in TIMEFRAMES]
    return pd.DataFrame(rows)


def ib_refresh_plan(audit: pd.DataFrame) -> pd.DataFrame:
    """One row per source request.  4h refreshes are derived from 1h."""
    stale = audit[audit["status"].isin(["missing", "needs_ib_refresh"])].copy()
    stale = stale[stale["tf"] != "4h"]
    stale["ib_tf"] = stale["tf"]
    stale["action"] = "fetch_and_merge"
    stale["output"] = stale.apply(lambda r: f"data/{r.symbol}_{r.tf}.csv", axis=1)
    return stale[["symbol", "ib_tf", "status", "start", "end", "action", "output"]].sort_values(["ib_tf", "symbol"])


def main() -> None:
    parser = argparse.ArgumentParser(description="历史数据覆盖审计（只读）")
    parser.add_argument("--write", action="store_true", help="写入 logs/data_coverage.csv 与 logs/ib_refresh_plan.csv")
    args = parser.parse_args()
    audit = build_audit()
    plan = ib_refresh_plan(audit)
    print(audit[["symbol", "tf", "bars", "start", "end", "status", "source"]].to_string(index=False))
    print(f"\n需 IB 补拉：{len(plan)} 个原始周期请求；4h 将由 1h 重采样。")
    if args.write:
        LOG_DIR.mkdir(exist_ok=True)
        audit.to_csv(LOG_DIR / "data_coverage.csv", index=False)
        plan.to_csv(LOG_DIR / "ib_refresh_plan.csv", index=False)
        print("已写入 logs/data_coverage.csv 和 logs/ib_refresh_plan.csv")


if __name__ == "__main__":
    main()

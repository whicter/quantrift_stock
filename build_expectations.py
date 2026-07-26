"""
build_expectations.py — 从历史回放账本生成策略期望表

用途：
  衰减监控此前用 0R 中性基线判定红黄绿，含义是"最近是否亏钱"，在震荡期会把
  所有组合刷红；换成本表后，判定变为"是否显著差于该 (策略,标的,周期) 组合
  自身的历史表现"。

数据源：
  logs/backfill_signal_log.csv —— historical_backfill.py --write 产出的逐 bar
  历史回放，参数完整（含 params_json），不受实盘早期记录缺快照的影响。

用法：
  python build_expectations.py            # 重新生成 strategy_expectations.json
  python build_expectations.py --min-n 50 # 提高最小样本量门槛
"""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

BACKFILL_PATH = Path("logs/backfill_signal_log.csv")
# Tracked in git (logs/*.csv and logs/*.log are ignored), since the monitor's
# verdicts are only reproducible alongside the table that produced them.
OUTPUT_PATH = Path("strategy_expectations.json")
# 25 rather than 30: several live combinations (RSI2 MRVL/MU/SMH 1d) have 25-27
# replayed trades, and excluding them would leave the monitor on a 0R placeholder
# for exactly the combinations it is meant to grade.
DEFAULT_MIN_N = 25


def build(min_n: int = DEFAULT_MIN_N) -> dict:
    if not BACKFILL_PATH.exists():
        raise SystemExit(f"❌ {BACKFILL_PATH} 不存在，请先运行 historical_backfill.py --write")

    df = pd.read_csv(BACKFILL_PATH)
    # Shadow variants are experiments, not the live routing; excluding them keeps
    # the baseline aligned with what STRATEGY_MAP actually dispatches.
    df = df[(~df["strategy"].str.endswith("_shadow")) & df["r_mult"].notna()].copy()

    grouped = (df.groupby(["strategy", "symbol", "tf"])["r_mult"]
               .agg(count="count", mean="mean", std="std")
               .reset_index())
    kept = grouped[grouped["count"] >= min_n].copy()
    kept["std"] = kept["std"].fillna(0.0)

    expectations: dict = {}
    for _, row in kept.iterrows():
        (expectations.setdefault(row["strategy"], {})
                     .setdefault(row["symbol"], {})[row["tf"]]) = {
            "n": int(row["count"]),
            "mean_r": round(float(row["mean"]), 4),
            "std_r": round(float(row["std"]), 4),
        }

    return {
        "_meta": {
            "generated_from": str(BACKFILL_PATH),
            "generated_at": date.today().isoformat(),
            "min_samples": min_n,
            "total_decided_rows": int(len(df)),
            "combinations": int(len(kept)),
            "note": ("Per-(strategy, symbol, timeframe) expectations from historical "
                     "replay, used as the decay-monitor baseline instead of a 0R placeholder."),
        },
        "expectations": expectations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成策略期望表")
    parser.add_argument("--min-n", type=int, default=DEFAULT_MIN_N,
                        help=f"每个组合的最小样本量（默认 {DEFAULT_MIN_N}）")
    args = parser.parse_args()

    payload = build(args.min_n)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    meta = payload["_meta"]
    print(f"✅ 已生成 {OUTPUT_PATH}")
    print(f"   已决回放 {meta['total_decided_rows']} 条 → {meta['combinations']} 个组合（N≥{meta['min_samples']}）")
    for strategy, symbols in payload["expectations"].items():
        combos = sum(len(tfs) for tfs in symbols.values())
        print(f"   {strategy}: {len(symbols)} 个标的 / {combos} 个组合")


if __name__ == "__main__":
    main()

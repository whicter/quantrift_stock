"""
validate_watchlist.py — 对 watchlist 批次接入的标的补做上线验证

背景：
  原主池标的均通过 0-30bps 成本压力测试 + Walk-forward 分段验证（见 LEARNING.md
  「上线验证结论」），但 2026-07-25 四个 watchlist 批次接入的标的全部未做。其中
  网格优化救回的 36 个属单样本内寻优，过拟合风险最高。

两项检验：
  1. 成本压力：在 0/5/10/20/30 bps 佣金下重跑，看 Sharpe 衰减是否可接受。
     IB 实际 round-trip 约 5-10bps，故以 10bps 仍达标为合格线。
  2. Walk-forward：按时间前 60% 训练 / 后 40% 测试，检验样本外是否维持。
     两段样本量不足则标记 insufficient 而非强行给结论。

用法：
  python validate_watchlist.py                    # 全量（后台跑，约数十分钟）
  python validate_watchlist.py --symbol AAOI      # 单标的
  python validate_watchlist.py --strategy rsi2    # 只验证某策略
"""

import argparse
import json
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

import backtest_runner as br
import rsi2_backtest as r2
import mr_backtest as mrb
import breakout_backtest as bo
from alert_engine import BREAKOUT_PARAMS, MR_PARAMS, RSI2_PARAMS, STRATEGY_MAP
from param_loader import get_params

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

COST_BPS = [0, 5, 10, 20, 30]
# IB round-trip is roughly 5-10bps, so a strategy that dies before 10bps is not
# tradable regardless of how good its zero-cost Sharpe looks.
PASS_BPS = 10
PASS_SHARPE = 0.6
TRAIN_FRAC = 0.6
MIN_SEGMENT_TRADES = 15

OUTPUT_PATH = Path("watchlist_validation.csv")


def _run(strategy: str, symbol: str, tf: str, df, df_qqq, df_vix, overrides: dict | None = None):
    """Run one backtest, returning its result dict or None."""
    overrides = overrides or {}
    if strategy == "confluence":
        params = {**get_params(symbol, tf), **overrides}
        return br.run_backtest(symbol, tf, params, df_qqq=df_qqq, df_override=df)
    if strategy == "rsi2":
        params = {**r2.DEFAULT_PARAMS[tf], **RSI2_PARAMS.get((symbol, tf), {}), **overrides}
        return r2.run_one(df, params, df_qqq, df_vix, is_benchmark=False, is_sector_etf=False)
    if strategy == "mr":
        params = {**mrb.DEFAULT_PARAMS[tf], **MR_PARAMS.get((symbol, tf), {}), **overrides}
        return mrb.run_one(df, params)
    if strategy == "breakout":
        params = {**bo.DEFAULT_PARAMS, **BREAKOUT_PARAMS.get(symbol, {}), **overrides}
        return bo.run_one(df, params)
    return None


def _load(strategy: str, symbol: str, tf: str):
    if strategy == "breakout":
        return bo.load_data(symbol)
    if strategy == "mr":
        return mrb.load_data(symbol, tf)
    return r2.load_data(symbol, tf)


def validate_one(strategy: str, symbol: str, tf: str, df_qqq_cache: dict, df_vix) -> dict | None:
    df = _load(strategy, symbol, tf)
    if df is None or len(df) < 260:
        return None
    df_qqq = df_qqq_cache.get(tf)

    row = {"symbol": symbol, "tf": tf, "strategy": strategy}

    # --- cost pressure ---
    for bps in COST_BPS:
        res = _run(strategy, symbol, tf, df, df_qqq, df_vix, {"commission": bps / 10000})
        row[f"sharpe_{bps}bps"] = round(res["sharpe"], 3) if res else None
        if bps == 0:
            row["n"] = res["n"] if res else 0
            row["dd"] = round(res["dd"], 1) if res else None

    at_pass = row.get(f"sharpe_{PASS_BPS}bps")
    row["cost_verdict"] = ("pass" if at_pass is not None and at_pass >= PASS_SHARPE
                           else "insufficient" if at_pass is None else "fail")

    # --- walk-forward ---
    split = int(len(df) * TRAIN_FRAC)
    tr = _run(strategy, symbol, tf, df.iloc[:split], df_qqq, df_vix)
    te = _run(strategy, symbol, tf, df.iloc[split:], df_qqq, df_vix)
    row["train_sharpe"] = round(tr["sharpe"], 3) if tr else None
    row["train_n"] = tr["n"] if tr else 0
    row["test_sharpe"] = round(te["sharpe"], 3) if te else None
    row["test_n"] = te["n"] if te else 0

    if not te or te["n"] < MIN_SEGMENT_TRADES or not tr or tr["n"] < MIN_SEGMENT_TRADES:
        # Too few trades in a segment says nothing about robustness either way.
        row["wf_verdict"] = "insufficient"
    elif te["sharpe"] >= PASS_SHARPE:
        row["wf_verdict"] = "pass"
    elif te["sharpe"] >= tr["sharpe"] * 0.5:
        row["wf_verdict"] = "marginal"
    else:
        row["wf_verdict"] = "fail"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="watchlist 标的上线验证")
    parser.add_argument("--symbol", type=str, default="")
    parser.add_argument("--strategy", type=str, default="")
    args = parser.parse_args()

    watchlist = set(cfg["symbols"].get("watchlist_2026_07", []))
    targets = []
    for (symbol, tf), strategy in STRATEGY_MAP.items():
        if ":" in tf or symbol not in watchlist:
            continue
        if args.symbol and symbol != args.symbol.upper():
            continue
        if args.strategy and strategy != args.strategy:
            continue
        targets.append((strategy, symbol, tf))
    for symbol in BREAKOUT_PARAMS:
        if symbol in watchlist and not args.strategy or args.strategy == "breakout":
            if symbol in watchlist and (not args.symbol or symbol == args.symbol.upper()):
                targets.append(("breakout", symbol, "1d"))

    targets = sorted(set(targets))
    print(f"待验证组合: {len(targets)}", flush=True)

    df_qqq_cache = {tf: r2.load_data("QQQ", tf) for tf in ("1h", "4h", "1d")}
    df_vix = r2.load_vix()

    rows = []
    for i, (strategy, symbol, tf) in enumerate(targets, 1):
        try:
            row = validate_one(strategy, symbol, tf, df_qqq_cache, df_vix)
            if row:
                rows.append(row)
        except Exception as exc:
            print(f"  ⚠ {symbol} {tf} {strategy}: {exc}", flush=True)
        if i % 10 == 0 or i == len(targets):
            print(f"  进度 {i}/{len(targets)}（{len(rows)} 条结果）", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f"\n✅ 已写入 {OUTPUT_PATH}（{len(out)} 条）")
    if not out.empty:
        print("\n成本压力:", dict(out["cost_verdict"].value_counts()))
        print("Walk-forward:", dict(out["wf_verdict"].value_counts()))


if __name__ == "__main__":
    main()

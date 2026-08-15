"""
confluence_direction_test.py — Confluence 做多/做空腿分离验证（研究脚本）

背景（2026-08-15 周度复盘）：
  实盘 90 天 Confluence 做多 N=90 均R +0.44，做空 N=119 均R -0.44——做空腿看似
  在拖累整体。但"两个月实盘"不足以推翻一个回测验证过的策略腿：这两个月是单边
  牛市，做空天然吃亏；而且 6-7 月的部分信号是已知 bug 产物（默认路由缺口、半根
  bar 触发、数据截断，见 TASK.md ⑦⑨）。

  本脚本用历史数据回答："关掉做空"到底是改善还是损害。

方法：
  对每个已路由的 Confluence (symbol, tf)，跑两组配置：
    both — 当前实盘配置（allow_short=True）
    long — 只做多（allow_short=False）
  每组都做 0-30bps 成本压力 + 60/40 walk-forward，口径与 validate_watchlist.py 一致。

  判定不看单一 Sharpe 差值，而看"关掉做空后是否在成本压力和样本外都更好"——
  只有一致变好才建议关，否则维持现状（避免用近期实盘噪音改结构）。

用法：
  python confluence_direction_test.py
  python confluence_direction_test.py --symbol SMCI
"""

import argparse
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

import backtest_runner as br
import rsi2_backtest as r2
from alert_engine import STRATEGY_MAP
from param_loader import get_params

COST_BPS = [0, 10, 30]
PASS_BPS = 10
TRAIN_FRAC = 0.6
MIN_SEGMENT_TRADES = 15
OUT_PATH = "logs/confluence_direction_test.csv"


def _run(symbol, tf, df, df_qqq, overrides):
    params = {**get_params(symbol, tf), **overrides}
    return br.run_backtest(symbol, tf, params, df_qqq=df_qqq, df_override=df)


def evaluate(symbol: str, tf: str, df, df_qqq, allow_short: bool) -> dict:
    ov = {"allow_short": allow_short}
    row = {}
    for bps in COST_BPS:
        res = _run(symbol, tf, df, df_qqq, {**ov, "commission": bps / 10000})
        row[f"s{bps}"] = round(res["sharpe"], 3) if res else None
        if bps == 0:
            row["n"] = res["n"] if res else 0
            row["dd"] = round(res["dd"], 1) if res else None

    split = int(len(df) * TRAIN_FRAC)
    tr = _run(symbol, tf, df.iloc[:split], df_qqq, ov)
    te = _run(symbol, tf, df.iloc[split:], df_qqq, ov)
    row["train"] = round(tr["sharpe"], 3) if tr else None
    row["train_n"] = tr["n"] if tr else 0
    row["test"] = round(te["sharpe"], 3) if te else None
    row["test_n"] = te["n"] if te else 0
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="")
    args = ap.parse_args()

    targets = sorted({(s, tf) for (s, tf), strat in STRATEGY_MAP.items()
                      if strat == "confluence" and ":" not in tf
                      and (not args.symbol or s == args.symbol.upper())})
    print(f"待验证 Confluence 组合: {len(targets)}", flush=True)

    qqq = {tf: r2.load_data("QQQ", tf) for tf in ("1h", "4h", "1d")}
    rows = []
    for i, (symbol, tf) in enumerate(targets, 1):
        df = r2.load_data(symbol, tf)
        if df is None or len(df) < 260:
            print(f"  {symbol} {tf}: 数据不足，跳过", flush=True)
            continue
        try:
            both = evaluate(symbol, tf, df, qqq.get(tf), True)
            lng = evaluate(symbol, tf, df, qqq.get(tf), False)
        except Exception as exc:
            print(f"  ⚠ {symbol} {tf}: {exc}", flush=True)
            continue

        # 一致性判定：关空后必须在成本压力关和样本外同时不劣化才建议关。
        both_cost, long_cost = both[f"s{PASS_BPS}"], lng[f"s{PASS_BPS}"]
        both_test, long_test = both["test"], lng["test"]
        seg_ok = (lng["train_n"] >= MIN_SEGMENT_TRADES and lng["test_n"] >= MIN_SEGMENT_TRADES
                  and both["train_n"] >= MIN_SEGMENT_TRADES and both["test_n"] >= MIN_SEGMENT_TRADES)
        if None in (both_cost, long_cost):
            verdict = "insufficient"
        elif not seg_ok:
            verdict = "insufficient_wf"
        elif long_cost > both_cost and (long_test or -9) >= (both_test or -9):
            verdict = "long_only_better"
        elif both_cost > long_cost and (both_test or -9) >= (long_test or -9):
            verdict = "keep_short"
        else:
            verdict = "mixed"

        rows.append({"symbol": symbol, "tf": tf,
                     "both_10bps": both_cost, "long_10bps": long_cost,
                     "both_n": both["n"], "long_n": lng["n"],
                     "both_test": both_test, "long_test": long_test,
                     "both_dd": both["dd"], "long_dd": lng["dd"],
                     "verdict": verdict})
        print(f"  [{i}/{len(targets)}] {symbol} {tf}: both={both_cost} long={long_cost} → {verdict}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_PATH, index=False)
    print(f"\n已写入 {OUT_PATH}（{len(out)} 条）")
    if not out.empty:
        print("\n判定分布:", dict(out["verdict"].value_counts()))
        print("\n建议关掉做空的组合:")
        print(out[out.verdict == "long_only_better"].to_string(index=False) or "（无）")


if __name__ == "__main__":
    main()

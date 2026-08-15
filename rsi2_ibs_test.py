"""
rsi2_ibs_test.py — RSI2 基线 vs RSI2+IBS 过滤器对比（研究脚本）

背景（2026-08-15 周度复盘）：
  影子策略 RSI2_IBS_shadow（在 RSI2 信号基础上额外要求 IBS<0.2，即收盘落在当根
  bar 低位的"恐慌式收盘"）实盘表现 N=19 胜率89% 均R+1.83，高于正式 RSI2 的
  N=66 胜率85% 均R+1.38。但 19 条已决样本远不足以下结论——用户明确指出
  "本质是不是先认真回测"，本脚本用历史数据回答。

  注意：IBS 影子是 RSI2 信号的**子集**（同一条信号多记一笔），不是独立策略。
  "转正"意味着把 IBS<0.2 变成 RSI2 的必要条件，代价是信号量大幅减少。

方法：对每个已路由的 RSI2 (symbol, tf)，跑 baseline 与 +IBS 两组，各做
  0-30bps 成本压力 + 60/40 walk-forward，口径与 validate_watchlist.py 一致。

用法：
  python rsi2_ibs_test.py
"""

import warnings

import pandas as pd

warnings.filterwarnings("ignore")

import rsi2_backtest as r2
from alert_engine import (BENCHMARK_SYMBOLS, RSI2_PARAMS, SECTOR_ETF_SYMBOLS,
                          STRATEGY_MAP)

COST_BPS = [0, 10, 30]
PASS_BPS = 10
PASS_SHARPE = 0.6
TRAIN_FRAC = 0.6
MIN_SEGMENT_TRADES = 15
OUT_PATH = "logs/rsi2_ibs_test.csv"


def evaluate(symbol, tf, df, df_qqq, df_vix, use_ibs: bool) -> dict:
    base = {**r2.DEFAULT_PARAMS[tf], **RSI2_PARAMS.get((symbol, tf), {}),
            "use_ibs_filter": use_ibs}
    is_bm = symbol in BENCHMARK_SYMBOLS
    is_etf = symbol in SECTOR_ETF_SYMBOLS

    def run(d, p):
        return r2.run_one(d, p, df_qqq, df_vix, is_benchmark=is_bm, is_sector_etf=is_etf)

    row = {}
    for bps in COST_BPS:
        res = run(df, {**base, "commission": bps / 10000})
        row[f"s{bps}"] = round(res["sharpe"], 3) if res else None
        if bps == 0:
            row["n"] = res["n"] if res else 0
            row["wr"] = res["wr"] if res else None
            row["dd"] = round(res["dd"], 1) if res else None

    split = int(len(df) * TRAIN_FRAC)
    tr, te = run(df.iloc[:split], base), run(df.iloc[split:], base)
    row["train"] = round(tr["sharpe"], 3) if tr else None
    row["train_n"] = tr["n"] if tr else 0
    row["test"] = round(te["sharpe"], 3) if te else None
    row["test_n"] = te["n"] if te else 0
    return row


def main():
    targets = sorted({(s, tf) for (s, tf), strat in STRATEGY_MAP.items()
                      if strat == "rsi2" and ":" not in tf})
    print(f"待对比 RSI2 组合: {len(targets)}", flush=True)

    qqq = {tf: r2.load_data("QQQ", tf) for tf in ("1h", "4h", "1d")}
    vix = r2.load_vix()

    rows = []
    for i, (symbol, tf) in enumerate(targets, 1):
        df = r2.load_data(symbol, tf)
        if df is None or len(df) < 260:
            continue
        try:
            base = evaluate(symbol, tf, df, qqq.get(tf), vix, False)
            ibs = evaluate(symbol, tf, df, qqq.get(tf), vix, True)
        except Exception as exc:
            print(f"  ⚠ {symbol} {tf}: {exc}", flush=True)
            continue

        b10, i10 = base[f"s{PASS_BPS}"], ibs[f"s{PASS_BPS}"]
        if i10 is None:
            verdict = "ibs_too_few"      # IBS 过滤后信号量低于回测最小笔数
        elif b10 is None:
            verdict = "base_too_few"
        elif i10 > b10 and (ibs["test"] or -9) >= (base["test"] or -9):
            verdict = "ibs_better"
        elif b10 > i10:
            verdict = "baseline_better"
        else:
            verdict = "mixed"

        rows.append({"symbol": symbol, "tf": tf,
                     "base_10bps": b10, "ibs_10bps": i10,
                     "base_n": base["n"], "ibs_n": ibs["n"],
                     "base_wr": base["wr"], "ibs_wr": ibs["wr"],
                     "base_test": base["test"], "ibs_test": ibs["test"],
                     "verdict": verdict})
        print(f"  [{i}/{len(targets)}] {symbol} {tf}: base={b10}(N={base['n']}) "
              f"ibs={i10}(N={ibs['n']}) → {verdict}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT_PATH, index=False)
    print(f"\n已写入 {OUT_PATH}（{len(out)} 条）")
    if not out.empty:
        print("\n判定分布:", dict(out["verdict"].value_counts()))
        keep = out[out.base_n > 0]
        print(f"\n信号量影响：baseline 合计 {int(keep.base_n.sum())} 笔 → "
              f"+IBS 合计 {int(keep.ibs_n.sum())} 笔")


if __name__ == "__main__":
    main()

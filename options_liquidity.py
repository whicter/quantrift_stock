"""
options_liquidity.py — 筛出期权流动性足够做模拟/实盘的已路由标的

背景（2026-08-15）：用户提出"信号触发时模拟买期权、到止盈位出场、看盈亏"。
可行性排查发现真正的拦路虎不是 theta 而是**流动性**：45DTE 附近 102 个已路由
标的中 76 个 ATM 未平仓量 < 50。OI 这么薄意味着买卖价差可能吃掉 10-20% 权利金，
模拟出的盈亏会严重失真，实盘更无法执行。

本脚本按每条路由**自身的持仓上限**匹配到期区间（而非按周期一刀切），
统计 ATM 合约的 OI 与价差，输出可用子集。

DTE 选择依据（实测持仓中位数，来自 22,851 条历史回放）：
  1h 中位 2.0 交易日 / 上限 6.9  → 30-45 DTE
  4h 中位 6.5 交易日 / 上限 10   → 45 DTE
  1d 中位 10  交易日 / 上限 10   → 45-60 DTE
  1d RSI2-Trend 上限 30 交易日    → 90 DTE（⚠️ 期权库目前最长仅采集到 76 DTE）
  1d MR 上限 60 交易日            → 120 DTE（同样超出采集范围）
经验法则 DTE ≈ 3-4× 预期持仓，使出场时点仍在 30DTE 衰减陡坡之外。

数据源：quantrift_options-lab 的 Railway PostgreSQL（只读）。
本脚本不下单、不写期权库，只读取并输出报告。

用法：
  python options_liquidity.py                  # 全部已路由标的
  python options_liquidity.py --min-oi 500     # 自定义门槛
"""

import argparse
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
from dotenv import load_dotenv

OPTIONS_ENV = Path("/Users/congrenhan/Documents/quantrift_options-lab/collector/.env")
OUT_PATH = Path("logs/options_liquidity.csv")

# 每个持仓上限（交易日）对应的目标到期区间
def dte_window(hold_days: float) -> tuple[int, int]:
    target = max(30, hold_days * 3.5)
    return int(target * 0.7), int(target * 1.4)


def load_routes() -> pd.DataFrame:
    """列出所有实盘路由及其持仓上限（交易日）。"""
    import mr_backtest as mrb
    import rsi2_backtest as r2
    from review_core import BARS_PER_DAY
    from alert_engine import (BREAKOUT_PARAMS, MR_PARAMS, RSI2_PARAMS,
                              STRATEGY_MAP)
    from param_loader import get_params

    rows = []
    for (symbol, tf), strat in STRATEGY_MAP.items():
        if ":" in tf:
            continue
        bpd = BARS_PER_DAY.get(tf, 1)
        if strat == "rsi2":
            bars = {**r2.DEFAULT_PARAMS[tf], **RSI2_PARAMS.get((symbol, tf), {})}["max_hold_bars"]
        elif strat == "mr":
            bars = {**mrb.DEFAULT_PARAMS[tf], **MR_PARAMS.get((symbol, tf), {})}["max_hold_bars"]
        else:
            # Confluence 无时间止损，用复盘 fallback（约两周）作为期权久期依据
            bars = {"1h": 70, "4h": 20, "1d": 10}.get(tf, 10)
        rows.append(dict(symbol=symbol, tf=tf, strategy=strat, hold_days=round(bars / bpd, 1)))
    for symbol, p in BREAKOUT_PARAMS.items():
        rows.append(dict(symbol=symbol, tf="1d", strategy="breakout",
                         hold_days=float(p.get("max_hold_bars", 20))))
    return pd.DataFrame(rows).drop_duplicates(subset=["symbol", "tf", "strategy"])


def fetch_liquidity(symbols: set[str]) -> pd.DataFrame:
    load_dotenv(OPTIONS_ENV)
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("未找到期权库 DATABASE_URL")
    import psycopg2
    conn = psycopg2.connect(url, connect_timeout=30)
    q = """
        SELECT c.symbol,
               (c.expiry - s.snapshot_ts::date) AS dte,
               c.open_interest, c.volume, c.bid, c.ask
          FROM option_contract_snapshots c
          JOIN option_chain_snapshots s ON c.snapshot_id = s.id
         WHERE c.option_right = 'C'
           AND c.delta BETWEEN 0.40 AND 0.60      -- ATM 附近
           AND (c.expiry - s.snapshot_ts::date) BETWEEN 20 AND 120
    """
    df = pd.read_sql(q, conn)
    conn.close()
    return df[df.symbol.isin(symbols)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-oi", type=int, default=500,
                    help="ATM 未平仓量门槛（默认500）")
    args = ap.parse_args()

    routes = load_routes()
    print(f"已路由组合 {len(routes)} 条，唯一标的 {routes.symbol.nunique()} 个", flush=True)

    liq = fetch_liquidity(set(routes.symbol))
    print(f"期权库命中 {liq.symbol.nunique()} 个标的，{len(liq):,} 条 ATM 合约快照", flush=True)

    out = []
    for _, r in routes.iterrows():
        lo, hi = dte_window(r.hold_days)
        sub = liq[(liq.symbol == r.symbol) & (liq.dte.between(lo, hi))]
        if sub.empty:
            out.append({**r.to_dict(), "dte_lo": lo, "dte_hi": hi, "oi": None,
                        "spread_pct": None, "verdict": "无到期覆盖"})
            continue
        oi = float(sub.open_interest.max())
        # 价差：只有约8%的行有 bid/ask，能算就算，算不了如实留空
        pr = sub.dropna(subset=["bid", "ask"])
        pr = pr[(pr.ask > 0) & (pr.bid > 0)]
        spread = float(((pr.ask - pr.bid) / ((pr.ask + pr.bid) / 2) * 100).median()) if len(pr) else None
        verdict = ("可用" if oi >= args.min_oi else
                   "偏薄" if oi >= 100 else "太薄")
        out.append({**r.to_dict(), "dte_lo": lo, "dte_hi": hi,
                    "oi": oi, "spread_pct": round(spread, 1) if spread else None,
                    "verdict": verdict})

    df = pd.DataFrame(out).sort_values(["verdict", "oi"], ascending=[True, False])
    OUT_PATH.parent.mkdir(exist_ok=True)
    df.to_csv(OUT_PATH, index=False)

    print(f"\n判定分布: {dict(df.verdict.value_counts())}")
    ok = df[df.verdict == "可用"]
    print(f"\n=== 可用于期权模拟的路由（OI≥{args.min_oi}）：{len(ok)} 条 / "
          f"{ok.symbol.nunique()} 个标的 ===")
    if not ok.empty:
        print(ok[["symbol", "tf", "strategy", "hold_days", "dte_lo", "dte_hi",
                  "oi", "spread_pct"]].to_string(index=False))
    print(f"\n完整结果: {OUT_PATH}")


if __name__ == "__main__":
    main()

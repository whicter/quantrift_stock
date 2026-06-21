"""
param_optimizer.py — 网格搜索，为每个标的 × 周期找最优参数

扫描参数：adx_threshold × ut_key × min_score
目标：最大化 Sharpe，同时过滤掉交易笔数太少（< 20）的结果

用法：
  python param_optimizer.py --symbol NVDA
  python param_optimizer.py --symbol NVDA --tf 1h
  python param_optimizer.py --symbols AAPL MSFT GOOGL AMZN META NVDA TSLA
"""

import argparse
import itertools
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest
from indicators import compute_signals
from param_loader import get_params
from strategy import ConfluenceStrategy

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
TIMEFRAMES = ["1h", "4h", "1d"]

# ── 扫描网格 ─────────────────────────────────────────────────────────────
GRID = {
    "adx_threshold": [15.0, 20.0, 25.0, 30.0],
    "ut_key":        [1.0, 1.5, 2.0, 2.5, 3.0],
    "min_score":     [4, 5, 6],
}

MIN_TRADES = 20   # 少于此笔数的结果忽略


# ── 策略类 ───────────────────────────────────────────────────────────────

class _S(ConfluenceStrategy):
    pass


def set_params(p: dict):
    _S.min_score           = int(p.get("min_score", 5))
    _S.adx_threshold       = float(p.get("adx_threshold", 25.0))
    _S.use_adx             = bool(p.get("use_adx", True))
    _S.use_bbmc_dir        = bool(p.get("use_bbmc_dir", True))
    _S.use_vol             = bool(p.get("use_vol", True))
    _S.vol_mult            = float(p.get("vol_mult", 1.0))
    _S.allow_short         = bool(p.get("allow_short", True))
    _S.reversal_score      = int(p.get("reversal_score", 2))
    _S.conflict_threshold  = int(p.get("conflict_threshold", 2))
    _S.use_squeeze_mr      = bool(p.get("use_squeeze_mr", False))
    _S.use_staged_tp       = bool(p.get("use_staged_tp", True))
    _S.atr_tp1_mult        = float(p.get("atr_tp1_mult", 1.0))
    _S.atr_tp2_mult        = float(p.get("atr_tp2_mult", 2.0))
    _S.tp1_portion         = float(p.get("tp1_portion", 0.34))
    _S.use_trend_filter    = bool(p.get("use_trend_filter", False))
    _S.allow_reversal_flip = bool(p.get("allow_reversal_flip", True))
    _S.n_contracts         = int(p.get("n_contracts", 1))
    _S.contract_size       = int(p.get("contract_size", 1))


def load_data(symbol: str, tf: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    df.columns = [c.capitalize() for c in df.columns]
    if "Volume" not in df.columns:
        df["Volume"] = 0
    return df


def run_one(df_raw: pd.DataFrame, params: dict) -> dict | None:
    try:
        df_sig = compute_signals(df_raw, params)
        set_params(params)
        bt = Backtest(
            df_sig, _S,
            cash=float(params.get("cash", 100_000)),
            commission=float(params.get("commission", 0.001)),
            margin=float(params.get("margin", 0.5)),
            exclusive_orders=True,
            finalize_trades=True,
        )
        st = bt.run()
        n = int(st.get("# Trades", 0))
        if n < MIN_TRADES:
            return None
        trades = st["_trades"]
        wins   = trades[trades["PnL"] > 0]["PnL"]
        losses = trades[trades["PnL"] < 0]["PnL"]
        avg_w  = wins.mean()   if len(wins)   else 0
        avg_l  = losses.mean() if len(losses) else 0
        rr     = abs(avg_w / avg_l) if avg_l != 0 else 0
        return {
            "sharpe": round(st.get("Sharpe Ratio", 0), 3),
            "ret":    round(st.get("Return [%]", 0), 2),
            "dd":     round(st.get("Max. Drawdown [%]", 0), 2),
            "wr":     round(st.get("Win Rate [%]", 0), 1),
            "pf":     round(st.get("Profit Factor", 0), 2),
            "rr":     round(rr, 2),
            "n":      n,
        }
    except Exception:
        return None


def optimize(symbol: str, tf: str) -> dict | None:
    df_raw = load_data(symbol, tf)
    if df_raw is None or len(df_raw) < 50:
        print(f"  {symbol} {tf}: 无数据，跳过")
        return None

    base_params = get_params(symbol, tf)

    keys   = list(GRID.keys())
    values = list(GRID.values())
    combos = list(itertools.product(*values))
    total  = len(combos)

    best_sharpe = -999
    best_result = None
    best_combo  = None

    for i, combo in enumerate(combos, 1):
        params = base_params.copy()
        for k, v in zip(keys, combo):
            params[k] = v

        r = run_one(df_raw, params)
        if r is None:
            continue
        if r["sharpe"] > best_sharpe:
            best_sharpe = r["sharpe"]
            best_result = r
            best_combo  = dict(zip(keys, combo))

        if i % 20 == 0:
            print(f"    {symbol} {tf}: {i}/{total} 完成，当前最优 Sharpe={best_sharpe:.3f}", end="\r")

    print(f"    {symbol} {tf}: {total}/{total} 完成，最优 Sharpe={best_sharpe:.3f}  " + " " * 10)

    if best_result is None:
        print(f"  {symbol} {tf}: 所有组合交易笔数不足 {MIN_TRADES}，无有效结果")
        return None

    return {**best_combo, **best_result}


def print_best(symbol: str, tf: str, r: dict):
    print(
        f"  {'最优':>2} | adx≥{r['adx_threshold']:.0f}  ut_key={r['ut_key']}  min_score={r['min_score']}"
        f"  →  Sharpe={r['sharpe']:.3f}  MaxDD={r['dd']:.1f}%  WR={r['wr']:.1f}%  "
        f"PF={r['pf']:.2f}  N={r['n']}"
    )


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbol",  help="单标的，如 NVDA")
    group.add_argument("--symbols", nargs="+", help="多标的，如 AAPL MSFT GOOGL")
    parser.add_argument("--tf", help="单周期，如 1h / 4h / 1d（不指定则跑全部）")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else [s.upper() for s in args.symbols]
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    n_combos = len(list(itertools.product(*GRID.values())))
    print(f"网格大小：{n_combos} 组合  标的：{symbols}  周期：{tfs}")
    print(f"总计：{n_combos * len(symbols) * len(tfs)} 次回测\n")

    all_best = []

    for symbol in symbols:
        print(f"\n{'─'*60}")
        print(f"  {symbol}")
        print(f"{'─'*60}")
        for tf in tfs:
            r = optimize(symbol, tf)
            if r:
                print_best(symbol, tf, r)
                all_best.append({"symbol": symbol, "tf": tf, **r})

    if not all_best:
        print("\n无有效结果")
        return

    # 输出汇总
    print(f"\n{'═'*60}")
    print("  汇总（按 Sharpe 降序）")
    print(f"{'═'*60}")
    df = pd.DataFrame(all_best).sort_values("sharpe", ascending=False)
    for _, row in df.iterrows():
        print(
            f"  {row['symbol']:<6} {row['tf']:<4} "
            f"adx≥{row['adx_threshold']:.0f}  ut_key={row['ut_key']}  min_score={int(row['min_score']):<2}"
            f"  Sharpe={row['sharpe']:.3f}  DD={row['dd']:.1f}%  WR={row['wr']:.1f}%  N={int(row['n'])}"
        )

    # 保存
    out_path = Path("logs/optimized_params.csv")
    out_path.parent.mkdir(exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\n结果已保存至 {out_path}")

    # 提示如何写入 config.yaml
    print(f"\n{'─'*60}")
    print("  将以下内容复制到 config.yaml → symbol_params 节：")
    print(f"{'─'*60}")
    for _, row in df.iterrows():
        print(f"  {row['symbol']}:")
        print(f"    {row['tf']}:")
        print(f"      adx_threshold: {row['adx_threshold']:.1f}")
        print(f"      ut_key: {row['ut_key']}")
        print(f"      min_score: {int(row['min_score'])}")


if __name__ == "__main__":
    main()

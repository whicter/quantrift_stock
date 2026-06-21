"""
mr_backtest.py — 均值回归策略回测 & 参数优化

用法：
  python mr_backtest.py                         # 全量跑 MR 候选标的
  python mr_backtest.py --symbol MSFT           # 单标的
  python mr_backtest.py --symbol MSFT --tf 1h   # 单标的单周期
  python mr_backtest.py --optimize              # 网格搜索最优参数
  python mr_backtest.py --optimize --symbol MSFT
"""

import argparse
import itertools
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest
from mr_signals import compute_mr_signals
from mr_strategy import MeanReversionStrategy

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
TIMEFRAMES = ["1h", "4h", "1d"]

# MR 策略适用的候选标的（趋势跟踪策略失效的品种）
MR_SYMBOLS = ["MSFT", "AMZN", "GOOGL", "META", "AAPL", "SPY", "QQQ", "SOXX", "SMH"]

# ── 默认参数 ─────────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "1h": {
        "bb_len": 20, "bb_mult": 2.0,
        "rsi_len": 14, "rsi_os": 40.0, "rsi_ob": 60.0,
        "adx_len": 14, "adx_max": 25.0,
        "ci_len": 14, "ci_threshold": 50.0, "use_ci": False,
        "vol_len": 20, "trend_filter_len": 200,
        "atr_trail_mult": 2.5, "atr_sl_mult": 2.0, "max_hold_bars": 48,
        "use_trend_filter": True, "allow_short": False,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
    "4h": {
        "bb_len": 20, "bb_mult": 2.0,
        "rsi_len": 14, "rsi_os": 40.0, "rsi_ob": 60.0,
        "adx_len": 14, "adx_max": 25.0,
        "ci_len": 14, "ci_threshold": 50.0, "use_ci": False,
        "vol_len": 20, "trend_filter_len": 100,
        "atr_trail_mult": 2.5, "atr_sl_mult": 2.0, "max_hold_bars": 20,
        "use_trend_filter": True, "allow_short": False,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
    "1d": {
        "bb_len": 20, "bb_mult": 2.0,
        "rsi_len": 14, "rsi_os": 40.0, "rsi_ob": 60.0,
        "adx_len": 14, "adx_max": 25.0,
        "ci_len": 14, "ci_threshold": 50.0, "use_ci": False,
        "vol_len": 20, "trend_filter_len": 200,
        "atr_trail_mult": 2.5, "atr_sl_mult": 2.0, "max_hold_bars": 60,
        "use_trend_filter": True, "allow_short": False,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
}

# ── 优化网格 ─────────────────────────────────────────────────────────────
GRID = {
    "bb_mult":      [1.5, 2.0, 2.5],
    "rsi_os":       [30.0, 35.0, 40.0],
    "adx_max":      [20.0, 25.0, 30.0],
    "atr_sl_mult":  [1.5, 2.0, 2.5],
    "max_hold_bars":[10, 20, 30],
}

MIN_TRADES = 15


# ── 策略类（参数注入用）────────────────────────────────────────────────────
class _MR(MeanReversionStrategy):
    pass


def set_params(p: dict):
    _MR.bb_len            = int(p.get("bb_len", 20))
    _MR.bb_mult           = float(p.get("bb_mult", 2.0))
    _MR.rsi_os            = float(p.get("rsi_os", 40.0))
    _MR.rsi_ob            = float(p.get("rsi_ob", 60.0))
    _MR.adx_max           = float(p.get("adx_max", 25.0))
    _MR.use_ci            = bool(p.get("use_ci", False))
    _MR.use_trend_filter  = bool(p.get("use_trend_filter", True))
    _MR.atr_trail_mult    = float(p.get("atr_trail_mult", 2.5))
    _MR.atr_sl_mult       = float(p.get("atr_sl_mult", 2.0))
    _MR.max_hold_bars     = int(p.get("max_hold_bars", 30))
    _MR.allow_short       = bool(p.get("allow_short", False))
    _MR.n_contracts       = int(p.get("n_contracts", 1))
    _MR.contract_size     = int(p.get("contract_size", 1))


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
        df_sig = compute_mr_signals(df_raw, params)
        set_params(params)
        bt = Backtest(
            df_sig, _MR,
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
    except Exception as e:
        return None


HDR = (f"{'标的':<6} {'周期':<4} {'收益%':>7} {'Sharpe':>7} "
       f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
SEP = "─" * 60


def print_result(symbol, tf, r):
    print(f"{symbol:<6} {tf:<4} {r['ret']:>7.1f} {r['sharpe']:>7.2f} "
          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5} {r['pf']:>5.2f} {r['rr']:>5.2f}")


def run_backtest_mode(symbols, tfs):
    all_results = []
    for tf in tfs:
        print(f"\n{'═'*60}")
        print(f"  均值回归 周期：{tf}")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 50:
                print(f"{sym:<6} {tf:<4}  — 无数据")
                continue
            params = DEFAULT_PARAMS[tf].copy()
            r = run_one(df_raw, params)
            if r is None:
                print(f"{sym:<6} {tf:<4}  — 信号不足（< {MIN_TRADES} 笔）")
                continue
            print_result(sym, tf, r)
            all_results.append({"symbol": sym, "tf": tf, **r})

    if len(all_results) > 1:
        ranked = sorted(all_results, key=lambda x: x["sharpe"], reverse=True)
        print(f"\n{'═'*60}")
        print("  最终排名（Sharpe 降序）")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for r in ranked:
            print_result(r["symbol"], r["tf"], r)

        out = Path("logs/mr_backtest_results.csv")
        out.parent.mkdir(exist_ok=True)
        pd.DataFrame(all_results).to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")


def run_optimize_mode(symbols, tfs):
    keys   = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    total  = len(combos)
    print(f"网格大小：{total} 组合  标的：{symbols}  周期：{tfs}")
    print(f"总计：{total * len(symbols) * len(tfs)} 次回测\n")

    all_best = []

    for sym in symbols:
        print(f"\n{'─'*60}\n  {sym}\n{'─'*60}")
        for tf in tfs:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 50:
                print(f"  {sym} {tf}: 无数据，跳过")
                continue

            base = DEFAULT_PARAMS[tf].copy()
            best_sharpe = -999
            best_result = None
            best_combo  = None

            for i, combo in enumerate(combos, 1):
                params = base.copy()
                for k, v in zip(keys, combo):
                    params[k] = v
                r = run_one(df_raw, params)
                if r and r["sharpe"] > best_sharpe:
                    best_sharpe = r["sharpe"]
                    best_result = r
                    best_combo  = dict(zip(keys, combo))
                if i % 30 == 0:
                    print(f"    {sym} {tf}: {i}/{total}  最优 Sharpe={best_sharpe:.3f}", end="\r")

            print(f"    {sym} {tf}: 完成  最优 Sharpe={best_sharpe:.3f}  " + " " * 20)
            if best_result:
                bc = best_combo
                print(f"  最优 | bb_mult={bc['bb_mult']}  rsi_os={bc['rsi_os']}"
                      f"  adx_max={bc['adx_max']}  sl={bc['atr_sl_mult']}×ATR"
                      f"  hold≤{bc['max_hold_bars']}  →"
                      f"  Sharpe={best_result['sharpe']:.3f}  WR={best_result['wr']:.1f}%"
                      f"  RR={best_result['rr']:.2f}  N={best_result['n']}")
                all_best.append({"symbol": sym, "tf": tf, **best_combo, **best_result})

    if not all_best:
        print("无有效结果")
        return

    df = pd.DataFrame(all_best).sort_values("sharpe", ascending=False)
    print(f"\n{'═'*60}")
    print("  优化汇总（Sharpe 降序）")
    print(f"{'═'*60}")
    for _, row in df.iterrows():
        print(f"  {row['symbol']:<6} {row['tf']:<4}"
              f"  bb×{row['bb_mult']}  rsi_os={row['rsi_os']}"
              f"  adx<{row['adx_max']}  sl={row['atr_sl_mult']}×  hold≤{int(row['max_hold_bars'])}"
              f"  →  Sharpe={row['sharpe']:.3f}  WR={row['wr']:.1f}%  N={int(row['n'])}")

    out = Path("logs/mr_optimized_params.csv")
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的")
    parser.add_argument("--tf", help="单周期 1h/4h/1d")
    parser.add_argument("--optimize", action="store_true", help="网格搜索最优参数")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else MR_SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    if args.optimize:
        run_optimize_mode(symbols, tfs)
    else:
        run_backtest_mode(symbols, tfs)


if __name__ == "__main__":
    main()

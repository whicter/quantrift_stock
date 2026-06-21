"""
ema_backtest.py — EMA Pullback 策略回测 & 参数优化

用法：
  python ema_backtest.py                         # 全量跑所有目标标的
  python ema_backtest.py --symbol MSFT           # 单标的
  python ema_backtest.py --symbol MSFT --tf 1d   # 单标的单周期
  python ema_backtest.py --optimize              # 网格搜索最优参数
  python ema_backtest.py --optimize --symbol MSFT --tf 1d
"""

import argparse
import itertools
import warnings
from pathlib import Path

import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest
from ema_signals import compute_ema_signals
from ema_strategy import EMABounceStrategy

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR  = Path(cfg["data"]["dir"])
TIMEFRAMES = ["1h", "4h", "1d"]

# EMA Pullback 适用品种：大市值慢牛股 + 宽基 ETF
EMA_SYMBOLS = ["MSFT", "AMZN", "GOOGL", "META", "AAPL", "SPY", "QQQ", "SOXX", "SMH"]

# ── 默认参数（按周期） ─────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "1h": {
        "ema_fast_len": 21, "ema_mid_len": 50, "ema_slow_len": 200,
        "atr_len": 14, "rsi_len": 14,
        "rsi_dip": 48.0, "touch_band": 0.003,
        "atr_trail_mult": 2.0, "atr_sl_mult": 1.5,
        "max_hold_bars": 48,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
    "4h": {
        "ema_fast_len": 21, "ema_mid_len": 50, "ema_slow_len": 200,
        "atr_len": 14, "rsi_len": 14,
        "rsi_dip": 50.0, "touch_band": 0.003,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5,
        "max_hold_bars": 30,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
    "1d": {
        "ema_fast_len": 21, "ema_mid_len": 50, "ema_slow_len": 200,
        "atr_len": 14, "rsi_len": 14,
        "rsi_dip": 52.0, "touch_band": 0.003,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5,
        "max_hold_bars": 60,
        "n_contracts": 1, "contract_size": 1,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
    },
}

# ── 优化网格 ──────────────────────────────────────────────────────────────
GRID = {
    "rsi_dip":        [45.0, 50.0, 55.0],
    "atr_trail_mult": [2.0, 2.5, 3.0],
    "ema_fast_len":   [13, 21],
    "atr_sl_mult":    [1.0, 1.5, 2.0],
}

MIN_TRADES = 10   # 大市值慢牛信号少，门槛适当降低


class _EMA(EMABounceStrategy):
    pass


def set_params(p: dict):
    _EMA.ema_fast_len   = int(p.get("ema_fast_len", 21))
    _EMA.ema_mid_len    = int(p.get("ema_mid_len", 50))
    _EMA.ema_slow_len   = int(p.get("ema_slow_len", 200))
    _EMA.rsi_dip        = float(p.get("rsi_dip", 52.0))
    _EMA.touch_band     = float(p.get("touch_band", 0.003))
    _EMA.atr_trail_mult = float(p.get("atr_trail_mult", 2.5))
    _EMA.atr_sl_mult    = float(p.get("atr_sl_mult", 1.5))
    _EMA.max_hold_bars  = int(p.get("max_hold_bars", 60))
    _EMA.n_contracts    = int(p.get("n_contracts", 1))
    _EMA.contract_size  = int(p.get("contract_size", 1))


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
        df_sig = compute_ema_signals(df_raw, params)
        set_params(params)
        bt = Backtest(
            df_sig, _EMA,
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
        print(f"  EMA Pullback 周期：{tf}")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 250:
                print(f"{sym:<6} {tf:<4}  — 无数据（需 >250 根 bar 预热 200 EMA）")
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

        out = Path("logs/ema_backtest_results.csv")
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
            if df_raw is None or len(df_raw) < 250:
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
                if i % 18 == 0:
                    print(f"    {sym} {tf}: {i}/{total}  最优 Sharpe={best_sharpe:.3f}", end="\r")

            print(f"    {sym} {tf}: 完成  最优 Sharpe={best_sharpe:.3f}" + " " * 20)
            if best_result:
                bc = best_combo
                print(f"  最优 | ema_fast={bc['ema_fast_len']}  rsi_dip={bc['rsi_dip']}"
                      f"  trail={bc['atr_trail_mult']}×ATR  sl={bc['atr_sl_mult']}×ATR"
                      f"  →  Sharpe={best_result['sharpe']:.3f}  WR={best_result['wr']:.1f}%"
                      f"  RR={best_result['rr']:.2f}  N={best_result['n']}")
                all_best.append({"symbol": sym, "tf": tf, **bc, **best_result})

    if not all_best:
        print("无有效结果")
        return

    df = pd.DataFrame(all_best).sort_values("sharpe", ascending=False)
    print(f"\n{'═'*60}")
    print("  优化汇总（Sharpe 降序）")
    print(f"{'═'*60}")
    for _, row in df.iterrows():
        print(f"  {row['symbol']:<6} {row['tf']:<4}"
              f"  ema={int(row['ema_fast_len'])}  rsi_dip={row['rsi_dip']}"
              f"  trail={row['atr_trail_mult']}×  sl={row['atr_sl_mult']}×"
              f"  →  Sharpe={row['sharpe']:.3f}  WR={row['wr']:.1f}%  N={int(row['n'])}")

    out = Path("logs/ema_optimized_params.csv")
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的，如 MSFT")
    parser.add_argument("--tf", help="单周期 1h/4h/1d")
    parser.add_argument("--optimize", action="store_true", help="网格搜索最优参数")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else EMA_SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    if args.optimize:
        run_optimize_mode(symbols, tfs)
    else:
        run_backtest_mode(symbols, tfs)


if __name__ == "__main__":
    main()

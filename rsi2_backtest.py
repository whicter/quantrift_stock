"""
rsi2_backtest.py — Connors RSI2 策略回测（含 QQQ 市场过滤 + 相对强度）

新增过滤器：
  QQQ 市场环境：QQQ > 100 SMA → risk-on，才允许做多
  相对强度：个股 60 日收益 > QQQ 60 日收益 → 跑赢大盘才入场

用法：
  python rsi2_backtest.py
  python rsi2_backtest.py --symbol MSFT --tf 1d
  python rsi2_backtest.py --optimize
  python rsi2_backtest.py --optimize --symbol MSFT --tf 1d
"""

import argparse
import itertools
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

from backtesting import Backtest, Strategy
from indicators import _atr, _sma

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR   = Path(cfg["data"]["dir"])
TIMEFRAMES = ["1h", "4h", "1d"]
SYMBOLS    = ["MSFT", "AMZN", "GOOGL", "META", "AAPL", "SPY", "QQQ", "SOXX", "SMH"]

# QQQ/SPY 本身就是基准，不做相对强度过滤
BENCHMARK_SYMBOLS = {"QQQ", "SPY"}

DEFAULT_PARAMS = {
    "1h": {
        "sma_slow": 200, "qqq_sma": 100, "rs_len": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 70.0,
        "atr_trail_mult": 2.0, "atr_sl_mult": 1.5, "max_hold_bars": 48,
        "use_qqq_filter": True, "use_rs_filter": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 1, "contract_size": 1,
    },
    "4h": {
        "sma_slow": 200, "qqq_sma": 100, "rs_len": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 70.0,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20,
        "use_qqq_filter": True, "use_rs_filter": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 1, "contract_size": 1,
    },
    "1d": {
        "sma_slow": 200, "qqq_sma": 100, "rs_len": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 70.0,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 10,
        "use_qqq_filter": True, "use_rs_filter": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 1, "contract_size": 1,
    },
}

GRID = {
    "rsi2_entry":     [5.0, 10.0, 15.0],
    "rsi2_exit":      [60.0, 70.0, 80.0],
    "atr_trail_mult": [2.0, 2.5, 3.0],
    "max_hold_bars":  [5, 10, 15],
}

MIN_TRADES = 15


# ── 信号计算 ───────────────────────────────────────────────────────────────
def _rsi2(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(2).mean()
    loss  = (-delta.clip(upper=0)).rolling(2).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


def compute_signals(df: pd.DataFrame, params: dict,
                    df_qqq: pd.DataFrame | None = None,
                    is_benchmark: bool = False) -> pd.DataFrame:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    sma_slow = int(params.get("sma_slow", 200))
    qqq_sma  = int(params.get("qqq_sma",  100))
    rs_len   = int(params.get("rs_len",   60))

    result = df.copy()
    result["sma200"] = _sma(close, sma_slow)
    result["rsi2"]   = _rsi2(close)
    result["atrVal"] = _atr(high, low, close, 14)

    # ── QQQ 市场环境 + 相对强度 ──────────────────────────────────────────
    if df_qqq is not None and not is_benchmark:
        qqq_close  = df_qqq["Close"].reindex(df.index, method="ffill")
        qqq_sma_line = _sma(qqq_close, qqq_sma)

        # risk-on: QQQ > 100 SMA
        result["qqq_regime"]  = (qqq_close > qqq_sma_line).astype(float)

        # 相对强度：个股 60 日收益率 - QQQ 60 日收益率
        stock_ret = close.pct_change(rs_len)
        qqq_ret   = qqq_close.pct_change(rs_len)
        result["rs60"]        = stock_ret - qqq_ret
        result["rs_positive"] = (result["rs60"] > 0).astype(float)
    else:
        # 基准品种或无 QQQ 数据：跳过这两个过滤
        result["qqq_regime"]  = 1.0
        result["rs_positive"] = 1.0
        result["rs60"]        = 0.0

    return result


# ── 策略类 ─────────────────────────────────────────────────────────────────
class RSI2Strategy(Strategy):
    sma_slow:       int   = 200
    rsi2_entry:     float = 10.0
    rsi2_exit:      float = 70.0
    atr_trail_mult: float = 2.5
    atr_sl_mult:    float = 1.5
    max_hold_bars:  int   = 10
    use_qqq_filter: bool  = True   # QQQ > 100 SMA 才允许做多
    use_rs_filter:  bool  = True   # 个股跑赢 QQQ 才入场
    n_contracts:    int   = 1
    contract_size:  int   = 1

    def init(self):
        self._trail_stop = 0.0
        self._bars_held  = 0
        self._trade_size = (self.n_contracts * self.contract_size
                            if self.n_contracts > 0 else None)

    def next(self):
        if len(self.data.Close) < self.sma_slow + 5:
            return

        close  = self.data.Close[-1]
        sma200 = float(self.data.sma200[-1])
        rsi2   = float(self.data.rsi2[-1])
        atr    = float(self.data.atrVal[-1])

        if any(math.isnan(v) for v in [sma200, rsi2, atr]):
            return
        if atr <= 0:
            atr = close * 0.01

        # ── 持仓管理 ──────────────────────────────────────────────────────
        if self.position:
            self._bars_held += 1
            candidate = close - self.atr_trail_mult * atr
            if candidate > self._trail_stop:
                self._trail_stop = candidate

            if close < self._trail_stop or rsi2 > self.rsi2_exit \
                    or self._bars_held >= self.max_hold_bars:
                self.position.close()
                self._trail_stop = 0.0
                self._bars_held  = 0
            return

        # ── 入场过滤 ──────────────────────────────────────────────────────
        if close <= sma200:
            return
        if rsi2 >= self.rsi2_entry:
            return

        # QQQ 市场环境过滤
        if self.use_qqq_filter and not bool(self.data.qqq_regime[-1]):
            return

        # 相对强度过滤（跑赢 QQQ）
        if self.use_rs_filter and not bool(self.data.rs_positive[-1]):
            return

        self._trail_stop = close - self.atr_sl_mult * atr
        self._bars_held  = 0
        self.buy(size=self._trade_size)


# ── 回测运行器 ─────────────────────────────────────────────────────────────
class _S(RSI2Strategy):
    pass


def set_params(p: dict):
    _S.sma_slow       = int(p.get("sma_slow", 200))
    _S.rsi2_entry     = float(p.get("rsi2_entry", 10.0))
    _S.rsi2_exit      = float(p.get("rsi2_exit", 70.0))
    _S.atr_trail_mult = float(p.get("atr_trail_mult", 2.5))
    _S.atr_sl_mult    = float(p.get("atr_sl_mult", 1.5))
    _S.max_hold_bars  = int(p.get("max_hold_bars", 10))
    _S.use_qqq_filter = bool(p.get("use_qqq_filter", True))
    _S.use_rs_filter  = bool(p.get("use_rs_filter", True))
    _S.n_contracts    = int(p.get("n_contracts", 1))
    _S.contract_size  = int(p.get("contract_size", 1))


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


def run_one(df_raw: pd.DataFrame, params: dict,
            df_qqq: pd.DataFrame | None = None,
            is_benchmark: bool = False) -> dict | None:
    try:
        df_sig = compute_signals(df_raw, params, df_qqq, is_benchmark)
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


HDR = (f"{'标的':<6} {'周期':<4} {'收益%':>7} {'Sharpe':>7} "
       f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
SEP = "─" * 60


def print_result(symbol, tf, r):
    print(f"{symbol:<6} {tf:<4} {r['ret']:>7.1f} {r['sharpe']:>7.2f} "
          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5} {r['pf']:>5.2f} {r['rr']:>5.2f}")


def run_backtest_mode(symbols, tfs):
    all_results = []
    for tf in tfs:
        df_qqq = load_data("QQQ", tf)
        print(f"\n{'═'*60}")
        print(f"  RSI2 + QQQ过滤 + 相对强度  周期：{tf}")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 250:
                print(f"{sym:<6} {tf:<4}  — 无数据")
                continue
            is_bm  = sym in BENCHMARK_SYMBOLS
            params = DEFAULT_PARAMS[tf].copy()
            if is_bm:
                params["use_rs_filter"] = False
            r = run_one(df_raw, params, df_qqq, is_bm)
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
        out = Path("logs/rsi2_backtest_results.csv")
        out.parent.mkdir(exist_ok=True)
        pd.DataFrame(all_results).to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")


def run_optimize_mode(symbols, tfs):
    keys   = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    total  = len(combos)
    print(f"网格大小：{total} 组合  总计：{total*len(symbols)*len(tfs)} 次\n")
    all_best = []
    for sym in symbols:
        is_bm = sym in BENCHMARK_SYMBOLS
        print(f"\n{'─'*60}\n  {sym}\n{'─'*60}")
        for tf in tfs:
            df_raw = load_data(sym, tf)
            df_qqq = load_data("QQQ", tf)
            if df_raw is None or len(df_raw) < 250:
                continue
            base = DEFAULT_PARAMS[tf].copy()
            if is_bm:
                base["use_rs_filter"] = False
            best_sharpe, best_result, best_combo = -999, None, None
            for i, combo in enumerate(combos, 1):
                params = {**base, **dict(zip(keys, combo))}
                r = run_one(df_raw, params, df_qqq, is_bm)
                if r and r["sharpe"] > best_sharpe:
                    best_sharpe = r["sharpe"]
                    best_result = r
                    best_combo  = dict(zip(keys, combo))
                if i % 27 == 0:
                    print(f"    {sym} {tf}: {i}/{total}  最优={best_sharpe:.3f}", end="\r")
            print(f"    {sym} {tf}: 完成  最优 Sharpe={best_sharpe:.3f}" + " " * 20)
            if best_result:
                bc = best_combo
                print(f"  最优 | entry={bc['rsi2_entry']}  exit={bc['rsi2_exit']}"
                      f"  trail={bc['atr_trail_mult']}×  hold≤{bc['max_hold_bars']}"
                      f"  → Sharpe={best_result['sharpe']:.3f}  WR={best_result['wr']:.1f}%"
                      f"  RR={best_result['rr']:.2f}  N={best_result['n']}")
                all_best.append({"symbol": sym, "tf": tf, **bc, **best_result})
    if not all_best:
        print("无有效结果")
        return
    df = pd.DataFrame(all_best).sort_values("sharpe", ascending=False)
    print(f"\n{'═'*60}\n  优化汇总（Sharpe 降序）\n{'═'*60}")
    for _, row in df.iterrows():
        print(f"  {row['symbol']:<6} {row['tf']:<4}"
              f"  entry={row['rsi2_entry']}  exit={row['rsi2_exit']}"
              f"  trail={row['atr_trail_mult']}×  hold≤{int(row['max_hold_bars'])}"
              f"  → Sharpe={row['sharpe']:.3f}  WR={row['wr']:.1f}%  N={int(row['n'])}")
    out = Path("logs/rsi2_optimized_params.csv")
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument("--tf")
    parser.add_argument("--optimize", action="store_true")
    args = parser.parse_args()
    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES
    if args.optimize:
        run_optimize_mode(symbols, tfs)
    else:
        run_backtest_mode(symbols, tfs)


if __name__ == "__main__":
    main()

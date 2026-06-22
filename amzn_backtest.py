"""
amzn_backtest.py — AMZN 专项策略：距 20 日高点回撤 + RSI 恢复

背景：
  AMZN 在 ConfluenceStrategy 和 RSI2 v2 下 Sharpe 上限 0.27，两套通用策略均失效。
  AMZN 的结构特征：
    - 大区间震荡 + 阶段性突破
    - 回调时往往有支撑（不是无底洞）
    - RSI2 < 5 时过于极端，40-55 区间的"恢复中"信号更稳

策略逻辑：
  入场条件：
    1. close > 200SMA（大趋势向上）
    2. 当前收盘价 距 20 日最高价 回撤 pullback_pct_lo ~ pullback_pct_hi 之间
       例：-10% ~ -5%（意味着从高点下来了 5-10%）
    3. RSI(14) 在 rsi_lo ~ rsi_hi 范围（默认 40-55，恢复但未超买）
    4. Market Regime Score >= min_market_score（QQQ 过滤）

  出场条件（三选一先触发）：
    1. 价格回到 20 日最高价（目标实现）
    2. 时间止损：持仓超过 max_hold_bars 根 K
    3. ATR 追踪止损：price < trail_stop（仅向上移动）

用法：
  python amzn_backtest.py                  # 默认参数
  python amzn_backtest.py --optimize       # 网格搜索
  python amzn_backtest.py --symbol GOOGL   # 测试其他标的
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
from indicators import _atr, _sma, _rsi

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])

DEFAULT_SYMBOL = "AMZN"
DEFAULT_TF     = "1d"

DEFAULT_PARAMS = {
    "sma_slow":        200,
    "sma_mid":         100,
    "rsi_len":         14,
    "rsi_lo":          40.0,   # RSI 下限（不能太超卖）
    "rsi_hi":          55.0,   # RSI 上限（不能太强，要处于恢复阶段）
    "pullback_lo":     0.03,   # 距 20 日高点最低回撤（3%）
    "pullback_hi":     0.12,   # 距 20 日高点最高回撤（12%）
    "high_window":     20,     # 计算高点用的窗口（20 日）
    "atr_trail_mult":  2.0,    # ATR 追踪止损倍数
    "atr_sl_mult":     1.5,    # 初始固定止损（入场 ATR 倍数）
    "max_hold_bars":   15,     # 时间止损（日线 = 15 个交易日）
    "min_market_score": 2,
    "qqq_sma100":      100,
    "qqq_sma200":      200,
    "qqq_sma20":       20,
    "qqq_sma50":       50,
    "cash":            100000,
    "commission":      0.001,
    "margin":          0.5,
}

OPTIMIZE_GRID = {
    "pullback_lo":      [0.03, 0.05, 0.08],
    "pullback_hi":      [0.08, 0.12, 0.18],
    "rsi_lo":           [35.0, 40.0, 45.0],
    "rsi_hi":           [50.0, 55.0, 60.0],
    "atr_trail_mult":   [1.5, 2.0, 2.5],
    "max_hold_bars":    [10, 15, 20],
    "min_market_score": [1, 2, 3],
}

MIN_TRADES = 15


# ── 信号计算 ───────────────────────────────────────────────────────────────
def compute_signals(df: pd.DataFrame, params: dict,
                    df_qqq: pd.DataFrame | None = None) -> pd.DataFrame:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    result = df.copy()
    result["sma200"]   = _sma(close, int(params["sma_slow"]))
    result["sma100"]   = _sma(close, int(params["sma_mid"]))
    result["rsiVal"]   = _rsi(close, int(params["rsi_len"]))
    result["atrVal"]   = _atr(high, low, close, 14)

    # 20 日滚动最高价（入场当日用 shift(1) 避免未来函数）
    hw = int(params["high_window"])
    result["high20"]   = close.rolling(hw, min_periods=hw).max().shift(1)

    # 回撤比例：(close - high20) / high20，负值表示低于高点
    result["pullback_pct"] = (close - result["high20"]) / result["high20"]

    # Market Regime Score
    if df_qqq is not None:
        qqq_close  = df_qqq["Close"].reindex(df.index, method="ffill")
        qqq_sma20  = _sma(qqq_close, int(params.get("qqq_sma20",  20)))
        qqq_sma50  = _sma(qqq_close, int(params.get("qqq_sma50",  50)))
        qqq_sma100 = _sma(qqq_close, int(params.get("qqq_sma100", 100)))
        qqq_sma200 = _sma(qqq_close, int(params.get("qqq_sma200", 200)))
        qqq_ret5   = qqq_close.pct_change(5)
        qqq_low20  = qqq_close.rolling(20).min().shift(1)
        market_score = (
            (qqq_close > qqq_sma100).astype(int) +
            (qqq_close > qqq_sma200).astype(int) +
            (qqq_sma20  > qqq_sma50).astype(int) +
            (qqq_ret5   > 0).astype(int)          -
            (qqq_close  < qqq_low20).astype(int)
        ).astype(float)
    else:
        market_score = pd.Series(4.0, index=close.index)
    result["market_score"] = market_score

    return result


# ── 策略类 ─────────────────────────────────────────────────────────────────
class AMZNPullbackStrategy(Strategy):
    sma_slow:          int   = 200
    rsi_lo:            float = 40.0
    rsi_hi:            float = 55.0
    pullback_lo:       float = 0.03
    pullback_hi:       float = 0.12
    atr_trail_mult:    float = 2.0
    atr_sl_mult:       float = 1.5
    max_hold_bars:     int   = 15
    min_market_score:  int   = 2

    def init(self):
        self._trail_stop = 0.0
        self._init_stop  = 0.0
        self._bars_held  = 0

    def _reset(self):
        self._trail_stop = 0.0
        self._init_stop  = 0.0
        self._bars_held  = 0

    def next(self):
        if len(self.data.Close) < self.sma_slow + 5:
            return

        close      = self.data.Close[-1]
        sma200     = float(self.data.sma200[-1])
        rsi        = float(self.data.rsiVal[-1])
        atr        = float(self.data.atrVal[-1])
        high20     = float(self.data.high20[-1])
        pb_pct     = float(self.data.pullback_pct[-1])
        mkt_score  = float(self.data.market_score[-1])

        if any(math.isnan(v) for v in [sma200, rsi, atr, high20, pb_pct]):
            return
        if atr <= 0:
            atr = close * 0.01

        # ── 持仓管理 ──────────────────────────────────────────────────────
        if self.position:
            self._bars_held += 1

            # ATR 追踪止损（只向上移动）
            candidate = close - self.atr_trail_mult * atr
            if candidate > self._trail_stop:
                self._trail_stop = candidate

            hit_trail  = close < self._trail_stop
            hit_init   = close < self._init_stop   # 初始止损（更宽）
            hit_time   = self._bars_held >= self.max_hold_bars
            hit_target = close >= high20            # 回到 20 日高点

            if hit_init or hit_trail or hit_time or hit_target:
                self.position.close()
                self._reset()
            return

        # ── 入场过滤 ──────────────────────────────────────────────────────
        # 1. 大趋势
        if close <= sma200:
            return

        # 2. Market Regime Score
        if math.isnan(mkt_score) or mkt_score < self.min_market_score:
            return

        # 3. 回撤区间（-pullback_hi ~ -pullback_lo，负值=低于高点）
        if not (-self.pullback_hi <= pb_pct <= -self.pullback_lo):
            return

        # 4. RSI 在恢复区间（不过冷，也不过热）
        if not (self.rsi_lo <= rsi <= self.rsi_hi):
            return

        # 入场
        self._init_stop  = close - self.atr_sl_mult * atr
        self._trail_stop = self._init_stop
        self._bars_held  = 0
        size = max(2, int(self.equity * 0.95 / close))
        self.buy(size=size)


# ── 回测运行器 ─────────────────────────────────────────────────────────────
class _S(AMZNPullbackStrategy):
    pass


def set_params(p: dict):
    _S.sma_slow         = int(p.get("sma_slow", 200))
    _S.rsi_lo           = float(p.get("rsi_lo", 40.0))
    _S.rsi_hi           = float(p.get("rsi_hi", 55.0))
    _S.pullback_lo      = float(p.get("pullback_lo", 0.03))
    _S.pullback_hi      = float(p.get("pullback_hi", 0.12))
    _S.atr_trail_mult   = float(p.get("atr_trail_mult", 2.0))
    _S.atr_sl_mult      = float(p.get("atr_sl_mult", 1.5))
    _S.max_hold_bars    = int(p.get("max_hold_bars", 15))
    _S.min_market_score = int(p.get("min_market_score", 2))


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


def run_one(symbol: str, tf: str, params: dict) -> dict | None:
    df_raw = load_data(symbol, tf)
    if df_raw is None or len(df_raw) < 250:
        return None
    df_qqq = load_data("QQQ", tf)
    try:
        df_sig = compute_signals(df_raw, params, df_qqq)
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
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def run_optimize(symbol: str, tf: str):
    keys   = list(OPTIMIZE_GRID.keys())
    combos = list(itertools.product(*OPTIMIZE_GRID.values()))
    # 过滤无效组合：pullback_lo < pullback_hi, rsi_lo < rsi_hi
    combos = [c for c in combos
              if dict(zip(keys, c))["pullback_lo"] < dict(zip(keys, c))["pullback_hi"]
              and dict(zip(keys, c))["rsi_lo"] < dict(zip(keys, c))["rsi_hi"]]
    total  = len(combos)
    print(f"\n{symbol} {tf} 网格搜索：{total} 个有效组合\n")

    best_sharpe, best_r, best_c = -999, None, None
    all_results = []
    for i, combo in enumerate(combos, 1):
        params = {**DEFAULT_PARAMS, **dict(zip(keys, combo))}
        r = run_one(symbol, tf, params)
        if r and r["sharpe"] > best_sharpe:
            best_sharpe = r["sharpe"]
            best_r = r
            best_c = dict(zip(keys, combo))
        if i % 50 == 0:
            print(f"  进度 {i}/{total}  当前最优 Sharpe={best_sharpe:.3f}", end="\r")
        if r:
            all_results.append({**dict(zip(keys, combo)), **r})

    print(f"\n  完成  最优 Sharpe={best_sharpe:.3f}" + " " * 30)
    if best_r:
        print(f"\n  最优参数：")
        print(f"  pullback {best_c['pullback_lo']*100:.0f}%~{best_c['pullback_hi']*100:.0f}%"
              f"  RSI {best_c['rsi_lo']:.0f}-{best_c['rsi_hi']:.0f}"
              f"  trail={best_c['atr_trail_mult']}×  hold≤{best_c['max_hold_bars']}"
              f"  score≥{best_c['min_market_score']}")
        print(f"  Sharpe={best_r['sharpe']}  WR={best_r['wr']}%  RR={best_r['rr']}  N={best_r['n']}")

    if all_results:
        df = pd.DataFrame(all_results).sort_values("sharpe", ascending=False)
        out = Path(f"logs/amzn_optimize_{symbol}_{tf}.csv")
        out.parent.mkdir(exist_ok=True)
        df.to_csv(out, index=False)
        print(f"\n  Top 5:")
        print(f"  {'pb_lo':>5} {'pb_hi':>5} {'rsi_lo':>6} {'rsi_hi':>6}"
              f" {'trail':>6} {'hold':>5} {'score':>5}"
              f" | {'Sharpe':>7} {'WR%':>6} {'N':>4} {'RR':>5}")
        print("  " + "─" * 75)
        for _, row in df.head(5).iterrows():
            print(f"  {row['pullback_lo']*100:>5.0f}% {row['pullback_hi']*100:>4.0f}%"
                  f" {row['rsi_lo']:>6.0f} {row['rsi_hi']:>6.0f}"
                  f" {row['atr_trail_mult']:>6.1f}× {int(row['max_hold_bars']):>5}"
                  f" {int(row['min_market_score']):>5}"
                  f" | {row['sharpe']:>7.3f} {row['wr']:>6.1f} {int(row['n']):>4}"
                  f" {row['rr']:>5.2f}")
        print(f"\n  完整结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--tf",     default=DEFAULT_TF, choices=["1h", "4h", "1d"])
    parser.add_argument("--optimize", action="store_true")
    args = parser.parse_args()

    sym = args.symbol.upper()
    tf  = args.tf

    if args.optimize:
        run_optimize(sym, tf)
    else:
        print(f"\n{sym} {tf} 默认参数回测：")
        r = run_one(sym, tf, DEFAULT_PARAMS)
        if r:
            print(f"  Sharpe={r['sharpe']}  WR={r['wr']}%  N={r['n']}"
                  f"  RR={r['rr']}  MaxDD={r['dd']}%  PF={r['pf']}")
        else:
            print("  数据不足或信号不足")


if __name__ == "__main__":
    main()

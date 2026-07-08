"""
breakout_backtest.py — 52周高点突破策略回测

信号逻辑：
  - 基础：close > rolling_max(High, 252).shift(1)（今日收盘创新高）
  - 确认版：连续 confirm_days 日收盘均在252日最高价以上
  - 出场：ATR 追踪止损 + 时间止损（max_hold_bars）

用法：
  python breakout_backtest.py                     # 全标的
  python breakout_backtest.py --symbol NVDA
  python breakout_backtest.py --confirm 2         # 2日确认
  python breakout_backtest.py --optimize          # 网格优化
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

DATA_DIR = Path(cfg["data"]["dir"])

SYMBOLS = (
    cfg["symbols"].get("momentum",   [])
    + cfg["symbols"].get("high_vol", [])
    + cfg["symbols"].get("storage",  [])
    + cfg["symbols"].get("mega_cap", [])
    + cfg["symbols"].get("watch",    [])
)

MIN_TRADES = 8  # 52W突破信号稀少，降低最小笔数要求

DEFAULT_PARAMS = {
    "confirm_days":   1,      # 1=当日突破即入场，2=次日确认
    "atr_trail_mult": 2.5,
    "atr_sl_mult":    1.5,    # 初始止损
    "max_hold_bars":  20,     # 最大持仓天数（日线）
    "use_vol_filter": False,  # 突破日成交量 > 20日均量×1.5
    "sma_trend":      200,    # 大趋势过滤（close > SMA200）
}

GRID = {
    "confirm_days":   [1, 2],
    "atr_trail_mult": [2.0, 2.5, 3.0],
    "max_hold_bars":  [10, 15, 20],
    "use_vol_filter": [False, True],
}


# ── 信号计算 ─────────────────────────────────────────────────────────────────

def compute_breakout_signals(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    close  = df["Close"]
    high   = df["High"]
    volume = df["Volume"].replace(0, np.nan)

    result = df.copy()

    # 252日最高价（shift 避免 lookahead：用前一日及以前的 high 判断）
    high_252 = high.rolling(252, min_periods=200).max().shift(1)
    result["high_252"] = high_252

    # 基础突破信号（当日收盘 > 252日最高）
    bo = (close > high_252).astype(int)

    # N日连续确认
    confirm = int(params.get("confirm_days", 1))
    if confirm >= 2:
        # 连续 confirm_days 日都是突破状态
        result["breakout"] = bo.rolling(confirm).min().fillna(0).astype(int)
    else:
        result["breakout"] = bo

    # ATR
    result["atrVal"] = _atr(high, df["Low"], close, 14)

    # SMA200（大趋势）
    result["sma200"] = _sma(close, int(params.get("sma_trend", 200)))

    # 成交量放量
    vol_avg = volume.rolling(20).mean()
    result["vol_surge"] = (volume > vol_avg * 1.5).astype(int).fillna(0)

    return result


# ── 策略类 ───────────────────────────────────────────────────────────────────

class BreakoutStrategy(Strategy):
    confirm_days:   int   = 1
    atr_trail_mult: float = 2.5
    atr_sl_mult:    float = 1.5
    max_hold_bars:  int   = 20
    use_vol_filter: bool  = False

    def init(self):
        self._trail_stop = 0.0
        self._bars_held  = 0

    def _reset(self):
        self._trail_stop = 0.0
        self._bars_held  = 0

    def next(self):
        if len(self.data.Close) < 210:
            return

        close  = self.data.Close[-1]
        atr    = float(self.data.atrVal[-1])
        sma200 = float(self.data.sma200[-1])

        if any(math.isnan(v) for v in [atr, sma200]):
            return
        if atr <= 0:
            atr = close * 0.01

        # ── 持仓管理 ──────────────────────────────────────────────────────
        if self.position:
            self._bars_held += 1
            candidate = close - self.atr_trail_mult * atr
            if candidate > self._trail_stop:
                self._trail_stop = candidate

            if close < self._trail_stop or self._bars_held >= self.max_hold_bars:
                self.position.close()
                self._reset()
            return

        # ── 入场条件 ──────────────────────────────────────────────────────
        if close <= sma200:
            return
        if not bool(self.data.breakout[-1]):
            return
        if self.use_vol_filter and not bool(self.data.vol_surge[-1]):
            return

        self._trail_stop = close - self.atr_sl_mult * atr
        self._bars_held  = 0
        size = max(1, int(self.equity * 0.95 / close))
        self.buy(size=size)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

class _S(BreakoutStrategy):
    pass


def set_params(p: dict):
    _S.confirm_days   = int(p.get("confirm_days",   1))
    _S.atr_trail_mult = float(p.get("atr_trail_mult", 2.5))
    _S.atr_sl_mult    = float(p.get("atr_sl_mult",    1.5))
    _S.max_hold_bars  = int(p.get("max_hold_bars",   20))
    _S.use_vol_filter = bool(p.get("use_vol_filter", False))


def load_data(symbol: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_1d.csv"
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
        df_sig = compute_breakout_signals(df_raw, params)
        set_params(params)
        bt = Backtest(
            df_sig, _S,
            cash=100_000,
            commission=0.001,
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
            "sharpe": round(st.get("Sharpe Ratio",        0), 3),
            "ret":    round(st.get("Return [%]",          0), 2),
            "dd":     round(st.get("Max. Drawdown [%]",   0), 2),
            "wr":     round(st.get("Win Rate [%]",        0), 1),
            "pf":     round(st.get("Profit Factor",       0), 2),
            "rr":     round(rr, 2),
            "n":      n,
        }
    except Exception:
        return None


HDR = (f"{'标的':<6} {'确认':>3} {'收益%':>7} {'Sharpe':>7} "
       f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
SEP = "─" * 62


def print_result(symbol, r, extra=""):
    print(f"{symbol:<6} {extra:>3} {r['ret']:>7.1f} {r['sharpe']:>7.3f} "
          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5} {r['pf']:>5.2f} {r['rr']:>5.2f}")


# ── 主模式 ───────────────────────────────────────────────────────────────────

def run_backtest_mode(symbols, params):
    confirm = int(params.get("confirm_days", 1))
    vol_tag = "  vol✓" if params.get("use_vol_filter") else ""
    print(f"\n{'═'*62}")
    print(f"  52周高点突破  日线  confirm={confirm}日{vol_tag}")
    print(f"  trail×{params['atr_trail_mult']}  hold≤{params['max_hold_bars']}d")
    print(f"{'═'*62}")
    print(HDR); print(SEP)

    all_results = []
    for sym in symbols:
        df_raw = load_data(sym)
        if df_raw is None or len(df_raw) < 260:
            print(f"{sym:<6}   — 数据不足")
            continue
        r = run_one(df_raw, params)
        if r is None:
            print(f"{sym:<6}   — 信号不足（< {MIN_TRADES} 笔）")
        else:
            print_result(sym, r, str(confirm))
            all_results.append({"symbol": sym, **r})

    if len(all_results) > 1:
        ranked = sorted(all_results, key=lambda x: x["sharpe"], reverse=True)
        print(f"\n{'═'*62}")
        print("  排名（Sharpe 降序）")
        print(f"{'═'*62}")
        print(HDR); print(SEP)
        for r in ranked:
            print_result(r["symbol"], r, "")
    return all_results


def run_compare_mode(symbols):
    """对比 1日 vs 2日确认版本"""
    all_rows = []
    print(f"\n{'═'*70}")
    print("  52周突破：1日 vs 2日确认对比")
    print(f"{'═'*70}")
    hdr = f"{'标的':<6} {'确认':>4} {'Sharpe':>7} {'WR%':>6} {'N':>5} {'RR':>5} {'MaxDD%':>8}"
    print(hdr); print("─"*70)

    for sym in symbols:
        df_raw = load_data(sym)
        if df_raw is None or len(df_raw) < 260:
            continue
        for confirm in [1, 2]:
            params = {**DEFAULT_PARAMS, "confirm_days": confirm}
            r = run_one(df_raw, params)
            tag = f"{confirm}日"
            if r:
                print(f"{sym:<6} {tag:>4} {r['sharpe']:>7.3f} {r['wr']:>6.1f}"
                      f" {r['n']:>5} {r['rr']:>5.2f} {r['dd']:>8.1f}")
                all_rows.append({"symbol": sym, "confirm_days": confirm, **r})
            else:
                print(f"{sym:<6} {tag:>4}  — 信号不足（< {MIN_TRADES} 笔）")

    if all_rows:
        df = pd.DataFrame(all_rows)
        print(f"\n{'═'*70}")
        print("  Sharpe 增量摘要（2日 - 1日）")
        print(f"{'═'*70}")
        pivot = df.pivot_table(index="symbol", columns="confirm_days", values="sharpe")
        if 1 in pivot.columns and 2 in pivot.columns:
            pivot["delta"] = pivot[2] - pivot[1]
            pivot.columns = ["confirm_1d", "confirm_2d", "delta"]
            print(pivot.sort_values("delta", ascending=False).round(3).to_string())
    return all_rows


def run_optimize_mode(symbols):
    keys   = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    print(f"网格大小：{len(combos)} 组合  总计：{len(combos)*len(symbols)} 次\n")

    all_best = []
    for sym in symbols:
        df_raw = load_data(sym)
        if df_raw is None or len(df_raw) < 260:
            continue
        best_sharpe, best_r, best_p = -999, None, None
        for combo in combos:
            params = {**DEFAULT_PARAMS, **dict(zip(keys, combo))}
            r = run_one(df_raw, params)
            if r and r["sharpe"] > best_sharpe:
                best_sharpe = r["sharpe"]
                best_r, best_p = r, dict(zip(keys, combo))
        if best_r:
            vol_tag = "  vol✓" if best_p.get("use_vol_filter") else ""
            print(f"{sym:<6}  confirm={best_p['confirm_days']}日"
                  f"  trail={best_p['atr_trail_mult']}×"
                  f"  hold≤{best_p['max_hold_bars']}{vol_tag}"
                  f"  → Sharpe={best_r['sharpe']:.3f}"
                  f"  WR={best_r['wr']:.1f}%  N={best_r['n']}")
            all_best.append({"symbol": sym, **best_p, **best_r})
        else:
            print(f"{sym:<6}  — 无有效结果")

    if all_best:
        out = Path("logs/breakout_optimized.csv")
        out.parent.mkdir(exist_ok=True)
        pd.DataFrame(all_best).to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",   help="单标的")
    parser.add_argument("--confirm",  type=int, default=1, help="连续确认天数（默认1）")
    parser.add_argument("--trail",    type=float, default=2.5, help="ATR trail 倍数")
    parser.add_argument("--hold",     type=int, default=20, help="最大持仓天数")
    parser.add_argument("--vol",      action="store_true", help="启用成交量放量过滤")
    parser.add_argument("--compare",  action="store_true", help="对比1日 vs 2日确认")
    parser.add_argument("--optimize", action="store_true", help="网格优化")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS

    if args.compare:
        run_compare_mode(symbols)
    elif args.optimize:
        run_optimize_mode(symbols)
    else:
        params = {
            **DEFAULT_PARAMS,
            "confirm_days":   args.confirm,
            "atr_trail_mult": args.trail,
            "max_hold_bars":  args.hold,
            "use_vol_filter": args.vol,
        }
        run_backtest_mode(symbols, params)


if __name__ == "__main__":
    main()

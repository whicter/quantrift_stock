"""
rsi2_backtest.py — Connors RSI2 策略回测 v2

v2 改进（相比 v1）：
  1. Market Regime Score：6 维打分替换单条件 QQQ > 100SMA
     +1 QQQ > 100SMA, +1 QQQ > 200SMA, +1 QQQ 20SMA > 50SMA,
     +1 QQQ 5日收益 > 0, -1 VIX > 20（如有数据）, -1 QQQ 跌破前20日低点
  2. Pullback Location Filter：close > 100SMA AND close < 20SMA
  3. 加权 RS 过滤：RS_Score = 0.4×RS_20 + 0.6×RS_60
     ETF（SOXX/SMH）改用 close > 100SMA，不与 QQQ 比较
  4. 分批出场模型 C：RSI2 > 80 出半仓，ATR trail 出剩余
  5. 时间止损换算：4h 用 bars 数（12-24 ≈ 6-12 交易日）

用法：
  python rsi2_backtest.py
  python rsi2_backtest.py --symbol MSFT --tf 4h
  python rsi2_backtest.py --optimize
  python rsi2_backtest.py --optimize --symbol MSFT --tf 4h
  python rsi2_backtest.py --compare-exit          # 对比出场模型 A vs C
  python rsi2_backtest.py --compare-exit --tf 1d
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
SYMBOLS    = ["MSFT", "GOOGL", "META", "AAPL", "SPY", "QQQ", "SOXX", "SMH",
              "MRVL", "NVDA", "MU"]
# AMZN 已从主策略池删除（Sharpe 上限 0.27）
# TSLA 独立处理，不在此池
# MRVL/NVDA/MU：测试 RSI2 v2 能否补充或替代 ConfluenceStrategy 弱项周期

BENCHMARK_SYMBOLS  = {"QQQ", "SPY"}    # 本身就是基准，跳过 RS 过滤
SECTOR_ETF_SYMBOLS = {"SOXX", "SMH"}   # RS 用自身趋势（> 100SMA），不比 QQQ

DEFAULT_PARAMS = {
    "1h": {
        "sma_slow": 200, "sma_mid": 100, "sma_fast": 20,
        "qqq_sma_fast": 20, "qqq_sma_mid": 50, "qqq_sma_slow": 100, "qqq_sma_200": 200,
        "rs_len_short": 20, "rs_len_long": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 80.0, "rsi2_half_exit": 80.0,
        "atr_trail_mult": 2.0, "atr_sl_mult": 1.5, "max_hold_bars": 48,
        "min_market_score": 2,
        "use_qqq_filter": True, "use_rs_filter": True,
        "use_pullback_filter": False, "use_split_exit": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 0, "contract_size": 1,
    },
    "4h": {
        "sma_slow": 200, "sma_mid": 100, "sma_fast": 20,
        "qqq_sma_fast": 20, "qqq_sma_mid": 50, "qqq_sma_slow": 100, "qqq_sma_200": 200,
        "rs_len_short": 20, "rs_len_long": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 80.0, "rsi2_half_exit": 80.0,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20,
        "min_market_score": 2,
        "use_qqq_filter": True, "use_rs_filter": True,
        "use_pullback_filter": False, "use_split_exit": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 0, "contract_size": 1,
    },
    "1d": {
        "sma_slow": 200, "sma_mid": 100, "sma_fast": 20,
        "qqq_sma_fast": 20, "qqq_sma_mid": 50, "qqq_sma_slow": 100, "qqq_sma_200": 200,
        "rs_len_short": 20, "rs_len_long": 60,
        "rsi2_entry": 10.0, "rsi2_exit": 80.0, "rsi2_half_exit": 80.0,
        "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 10,
        "min_market_score": 2,
        "use_qqq_filter": True, "use_rs_filter": True,
        "use_pullback_filter": False, "use_split_exit": True,
        "cash": 100000, "commission": 0.001, "margin": 0.5,
        "n_contracts": 0, "contract_size": 1,
    },
}

# 优化网格（162 组合 = 3^4 × 2）
# 注意：use_split_exit=True 时，rsi2_exit 不生效（只有 rsi2_half_exit=80 生效）
# rsi2_half_exit 固定 80，需要对比时改为 [70, 80, 85] 加入 GRID
GRID = {
    "rsi2_entry":          [5.0, 10.0, 15.0],
    "atr_trail_mult":      [2.0, 2.5, 3.0],
    "max_hold_bars":       [5, 10, 15],
    "min_market_score":    [1, 2, 3],
    "use_pullback_filter": [False, True],
    "use_vol_score":       [False, True],   # 成交量放量加分（vol > 20日均量 × 1.5）
}

# 出场模型对比（--compare-exit）
EXIT_MODELS = {
    "A": {"use_split_exit": False, "rsi2_exit": 80.0},   # RSI2>80 全出
    "C": {"use_split_exit": True,  "rsi2_half_exit": 80.0},  # RSI2>80 出半 + ATR trail 出剩余
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
                    df_vix: pd.DataFrame | None = None,
                    is_benchmark: bool = False,
                    is_sector_etf: bool = False) -> pd.DataFrame:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    result = df.copy()
    result["sma200"]  = _sma(close, int(params.get("sma_slow", 200)))
    result["sma100"]  = _sma(close, int(params.get("sma_mid",  100)))
    result["sma20"]   = _sma(close, int(params.get("sma_fast",  20)))
    result["rsi2"]    = _rsi2(close)
    result["atrVal"]  = _atr(high, low, close, 14)

    # Pullback location filter：中期趋势完整 + 短期超卖位置
    result["pullback_ok"] = (
        (close > result["sma100"]) & (close < result["sma20"])
    ).astype(float)

    # 成交量放量：当日量 > N 日均量 × mult（用于入场加分）
    volume  = df["Volume"].replace(0, np.nan)
    vol_len = int(params.get("vol_len", 20))
    vol_mult = float(params.get("vol_mult", 1.5))
    vol_avg = volume.rolling(vol_len).mean()
    result["vol_surge"] = (volume > vol_avg * vol_mult).astype(float).fillna(0)

    # ── Market Regime Score + RS 过滤 ────────────────────────────────────
    if df_qqq is not None and not is_benchmark:
        qqq_close = df_qqq["Close"].reindex(df.index, method="ffill")

        qqq_sma20  = _sma(qqq_close, int(params.get("qqq_sma_fast",  20)))
        qqq_sma50  = _sma(qqq_close, int(params.get("qqq_sma_mid",   50)))
        qqq_sma100 = _sma(qqq_close, int(params.get("qqq_sma_slow", 100)))
        qqq_sma200 = _sma(qqq_close, int(params.get("qqq_sma_200",  200)))
        qqq_ret5   = qqq_close.pct_change(5)
        qqq_low20  = qqq_close.rolling(20).min().shift(1)

        market_score = (
            (qqq_close > qqq_sma100).astype(int) +
            (qqq_close > qqq_sma200).astype(int) +
            (qqq_sma20  > qqq_sma50).astype(int) +
            (qqq_ret5   > 0).astype(int)
        ).astype(float)

        # VIX 组件（如有数据则加入；否则 max_score=4，阈值 2 仍有效）
        if df_vix is not None:
            vix_close = df_vix["Close"].reindex(df.index, method="ffill")
            market_score -= (vix_close > 20).astype(float)
            market_score -= (qqq_close < qqq_low20).astype(float)

        result["market_score"] = market_score

        # RS 过滤
        if is_sector_etf:
            # 行业 ETF：用自身 100SMA 代替 RS vs QQQ
            result["rs_positive"] = (close > result["sma100"]).astype(float)
            result["rs_score"]    = 0.0
        else:
            rs_s = int(params.get("rs_len_short", 20))
            rs_l = int(params.get("rs_len_long",  60))
            rs_20    = close.pct_change(rs_s) - qqq_close.pct_change(rs_s)
            rs_60    = close.pct_change(rs_l) - qqq_close.pct_change(rs_l)
            rs_score = 0.4 * rs_20 + 0.6 * rs_60
            result["rs_score"]    = rs_score
            result["rs_positive"] = (rs_score > 0).astype(float)
    else:
        # 基准品种或无 QQQ 数据：跳过过滤
        result["market_score"] = 4.0
        result["rs_positive"]  = 1.0
        result["rs_score"]     = 0.0

    return result


# ── 策略类 ─────────────────────────────────────────────────────────────────
class RSI2Strategy(Strategy):
    sma_slow:            int   = 200
    rsi2_entry:          float = 10.0
    rsi2_exit:           float = 80.0    # 模型 A 全出阈值
    rsi2_half_exit:      float = 80.0    # 模型 C 出半仓阈值
    atr_trail_mult:      float = 2.5
    atr_sl_mult:         float = 1.5
    max_hold_bars:       int   = 10
    min_market_score:    int   = 2
    use_qqq_filter:      bool  = True
    use_rs_filter:       bool  = True
    use_pullback_filter: bool  = True
    use_split_exit:      bool  = True    # True=模型C，False=模型A
    use_vol_score:       bool  = False   # 成交量放量时 market_score +1
    n_contracts:         int   = 0       # 0=全仓，支持 position.close(0.5)
    contract_size:       int   = 1

    def init(self):
        self._trail_stop  = 0.0
        self._bars_held   = 0
        self._half_closed = False

    def _reset(self):
        self._trail_stop  = 0.0
        self._bars_held   = 0
        self._half_closed = False

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

            # ATR 追踪止损（只向上移动）
            candidate = close - self.atr_trail_mult * atr
            if candidate > self._trail_stop:
                self._trail_stop = candidate

            # 模型 C：RSI2 > half_exit 时出半仓
            if self.use_split_exit and not self._half_closed:
                if rsi2 > self.rsi2_half_exit:
                    self.position.close(0.5)
                    self._half_closed = True
                    return

            # 全部出场
            hit_trail = close < self._trail_stop
            hit_time  = self._bars_held >= self.max_hold_bars
            hit_rsi   = (not self.use_split_exit) and rsi2 > self.rsi2_exit

            if hit_trail or hit_time or hit_rsi:
                self.position.close()
                self._reset()
            return

        # ── 入场过滤 ──────────────────────────────────────────────────────
        # 大趋势
        if close <= sma200:
            return

        # Pullback location：close > 100SMA AND close < 20SMA
        if self.use_pullback_filter and not bool(self.data.pullback_ok[-1]):
            return

        # RSI2 超卖
        if rsi2 >= self.rsi2_entry:
            return

        # Market Regime Score（+ 可选成交量加分）
        if self.use_qqq_filter:
            score = float(self.data.market_score[-1])
            if self.use_vol_score:
                score += float(self.data.vol_surge[-1])
            if math.isnan(score) or score < self.min_market_score:
                return

        # 相对强度
        if self.use_rs_filter and not bool(self.data.rs_positive[-1]):
            return

        self._trail_stop  = close - self.atr_sl_mult * atr
        self._bars_held   = 0
        self._half_closed = False
        # n_contracts=0 → 按权益动态计算（保证至少 2 股，支持半仓出场）
        if self.n_contracts > 0:
            size = self.n_contracts * self.contract_size
        else:
            size = max(2, int(self.equity * 0.95 / close))
        self.buy(size=size)


# ── 回测运行器 ─────────────────────────────────────────────────────────────
class _S(RSI2Strategy):
    pass


def set_params(p: dict):
    _S.sma_slow            = int(p.get("sma_slow", 200))
    _S.rsi2_entry          = float(p.get("rsi2_entry", 10.0))
    _S.rsi2_exit           = float(p.get("rsi2_exit", 80.0))
    _S.rsi2_half_exit      = float(p.get("rsi2_half_exit", 80.0))
    _S.atr_trail_mult      = float(p.get("atr_trail_mult", 2.5))
    _S.atr_sl_mult         = float(p.get("atr_sl_mult", 1.5))
    _S.max_hold_bars       = int(p.get("max_hold_bars", 10))
    _S.min_market_score    = int(p.get("min_market_score", 2))
    _S.use_qqq_filter      = bool(p.get("use_qqq_filter", True))
    _S.use_rs_filter       = bool(p.get("use_rs_filter", True))
    _S.use_pullback_filter = bool(p.get("use_pullback_filter", True))
    _S.use_split_exit      = bool(p.get("use_split_exit", True))
    _S.use_vol_score       = bool(p.get("use_vol_score", False))
    _S.n_contracts         = int(p.get("n_contracts", 0))
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


def load_vix() -> pd.DataFrame | None:
    """VIX 始终用日线，reindex 到目标周期时 ffill"""
    path = DATA_DIR / "VIX_1d.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    df.columns = [c.capitalize() for c in df.columns]
    return df


def run_one(df_raw: pd.DataFrame, params: dict,
            df_qqq: pd.DataFrame | None = None,
            df_vix: pd.DataFrame | None = None,
            is_benchmark: bool = False,
            is_sector_etf: bool = False) -> dict | None:
    try:
        df_sig = compute_signals(df_raw, params, df_qqq, df_vix, is_benchmark, is_sector_etf)
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


def _setup_sym(sym, tf, params):
    """准备单标的回测所需的数据和参数"""
    is_bm  = sym in BENCHMARK_SYMBOLS
    is_etf = sym in SECTOR_ETF_SYMBOLS
    p = params.copy()
    if is_bm:
        p["use_rs_filter"] = False
    return is_bm, is_etf, p


def run_backtest_mode(symbols, tfs):
    df_vix = load_vix()
    vix_note = "" if df_vix is None else " +VIX"
    all_results = []
    for tf in tfs:
        df_qqq = load_data("QQQ", tf)
        print(f"\n{'═'*60}")
        print(f"  RSI2 v2（Regime Score{vix_note} + Pullback + 分批出场）  周期：{tf}")
        print(f"{'═'*60}")
        print(HDR)
        print(SEP)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 250:
                print(f"{sym:<6} {tf:<4}  — 无数据")
                continue
            is_bm, is_etf, params = _setup_sym(sym, tf, DEFAULT_PARAMS[tf])
            r = run_one(df_raw, params, df_qqq, df_vix, is_bm, is_etf)
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
        out = Path("logs/rsi2_v2_backtest_results.csv")
        out.parent.mkdir(exist_ok=True)
        pd.DataFrame(all_results).to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")


def run_optimize_mode(symbols, tfs):
    keys   = list(GRID.keys())
    combos = list(itertools.product(*GRID.values()))
    total  = len(combos)
    print(f"网格大小：{total} 组合  总计：{total*len(symbols)*len(tfs)} 次\n")
    df_vix   = load_vix()
    all_best = []
    for sym in symbols:
        print(f"\n{'─'*60}\n  {sym}\n{'─'*60}")
        for tf in tfs:
            df_raw = load_data(sym, tf)
            df_qqq = load_data("QQQ", tf)
            if df_raw is None or len(df_raw) < 250:
                continue
            is_bm, is_etf, base = _setup_sym(sym, tf, DEFAULT_PARAMS[tf])
            best_sharpe, best_result, best_combo = -999, None, None
            for i, combo in enumerate(combos, 1):
                params = {**base, **dict(zip(keys, combo))}
                r = run_one(df_raw, params, df_qqq, df_vix, is_bm, is_etf)
                if r and r["sharpe"] > best_sharpe:
                    best_sharpe = r["sharpe"]
                    best_result = r
                    best_combo  = dict(zip(keys, combo))
                if i % 27 == 0:
                    print(f"    {sym} {tf}: {i}/{total}  最优={best_sharpe:.3f}", end="\r")
            print(f"    {sym} {tf}: 完成  最优 Sharpe={best_sharpe:.3f}" + " " * 20)
            if best_result:
                bc = best_combo
                vol_tag = "  vol✓" if bc.get("use_vol_score") else ""
                print(f"  最优 | entry={bc['rsi2_entry']}"
                      f"  trail={bc['atr_trail_mult']}×  hold≤{bc['max_hold_bars']}"
                      f"  score≥{bc['min_market_score']}{vol_tag}"
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
              f"  entry={row['rsi2_entry']}"
              f"  trail={row['atr_trail_mult']}×  hold≤{int(row['max_hold_bars'])}"
              f"  score≥{int(row['min_market_score'])}"
              f"  → Sharpe={row['sharpe']:.3f}  WR={row['wr']:.1f}%  N={int(row['n'])}")
    out = Path("logs/rsi2_v2_optimized_params.csv")
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\n结果已保存至 {out}")


def run_compare_exit_mode(symbols, tfs):
    """对比出场模型 A（RSI2>80全出）vs C（RSI2>80出半 + ATR trail 出剩余）"""
    df_vix   = load_vix()
    all_rows = []
    for tf in tfs:
        df_qqq = load_data("QQQ", tf)
        print(f"\n{'═'*70}")
        print(f"  出场模型对比 A vs C  周期：{tf}")
        print(f"{'═'*70}")
        hdr = (f"{'标的':<6} {'模型':<3} {'收益%':>7} {'Sharpe':>7} "
               f"{'MaxDD%':>8} {'胜率%':>6} {'笔数':>5} {'PF':>5} {'RR':>5}")
        print(hdr)
        print("─" * 70)
        for sym in symbols:
            df_raw = load_data(sym, tf)
            if df_raw is None or len(df_raw) < 250:
                continue
            is_bm, is_etf, base = _setup_sym(sym, tf, DEFAULT_PARAMS[tf])
            for model_name, overrides in EXIT_MODELS.items():
                params = {**base, **overrides}
                r = run_one(df_raw, params, df_qqq, df_vix, is_bm, is_etf)
                if r:
                    print(f"{sym:<6} {model_name:<3} {r['ret']:>7.1f} {r['sharpe']:>7.2f} "
                          f"{r['dd']:>8.1f} {r['wr']:>6.1f} {r['n']:>5}"
                          f" {r['pf']:>5.2f} {r['rr']:>5.2f}")
                    all_rows.append({"symbol": sym, "tf": tf, "model": model_name, **r})
                else:
                    print(f"{sym:<6} {model_name:<3}  — 信号不足")

    if all_rows:
        df = pd.DataFrame(all_rows)
        # 对比摘要：每个标的 A vs C 的 Sharpe 差值
        print(f"\n{'═'*70}")
        print("  A vs C Sharpe 对比（C-A > 0 说明分批出场更好）")
        print(f"{'═'*70}")
        pivot = df.pivot_table(index=["symbol", "tf"], columns="model", values="sharpe")
        if "A" in pivot.columns and "C" in pivot.columns:
            pivot["C-A"] = pivot["C"] - pivot["A"]
            pivot_sorted = pivot.sort_values("C-A", ascending=False)
            print(pivot_sorted.to_string())
        out = Path("logs/rsi2_exit_comparison.csv")
        out.parent.mkdir(exist_ok=True)
        df.to_csv(out, index=False)
        print(f"\n结果已保存至 {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument("--tf")
    parser.add_argument("--optimize",     action="store_true")
    parser.add_argument("--compare-exit", action="store_true", dest="compare_exit")
    parser.add_argument("--cost-test",    action="store_true", dest="cost_test",
                        help="成本压力测试：0/5/10/20/30 bps（需指定 --symbol --tf）")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else SYMBOLS
    tfs     = [args.tf] if args.tf else TIMEFRAMES

    if args.optimize:
        run_optimize_mode(symbols, tfs)
    elif args.compare_exit:
        run_compare_exit_mode(symbols, tfs)
    elif args.cost_test:
        if not args.symbol or not args.tf:
            parser.error("--cost-test 需要指定 --symbol 和 --tf")
        sym = args.symbol.upper()
        tf  = args.tf
        df_raw = load_data(sym, tf)
        df_qqq = load_data("QQQ", tf)
        df_vix = load_vix()
        if df_raw is None or len(df_raw) < 250:
            print("数据不足")
            return
        is_bm, is_etf, base = _setup_sym(sym, tf, DEFAULT_PARAMS[tf])
        bps_levels = [0, 5, 10, 20, 30]
        print(f"\n{'═'*60}")
        print(f"  RSI2 v2 成本压力测试：{sym} {tf}")
        print(f"{'═'*60}")
        print(f"{'bps':>5} {'Sharpe':>7} {'WR%':>6} {'笔数':>5} {'RR':>5} {'MaxDD%':>8}")
        print("─" * 45)
        for bps in bps_levels:
            params = {**base, "commission": bps / 10000}
            r = run_one(df_raw, params, df_qqq, df_vix, is_bm, is_etf)
            if r:
                flag = "  ✅" if r["sharpe"] >= 0.7 else "  ❌"
                print(f"{bps:>5} {r['sharpe']:>7.2f} {r['wr']:>6.1f} {r['n']:>5} "
                      f"{r['rr']:>5.2f} {r['dd']:>8.1f}{flag}")
            else:
                print(f"{bps:>5}  — 信号不足")
    else:
        run_backtest_mode(symbols, tfs)


if __name__ == "__main__":
    main()

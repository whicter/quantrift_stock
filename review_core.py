"""Shared, deterministic signal replay used by review and paper portfolio.

This module deliberately models alerts only.  It never sends orders or talks to
IB; its job is to make the post-alert accounting match the strategy rules.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd


STAGED_PORTIONS = (0.34, 0.33, 0.33)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def signal_params(row: pd.Series | dict) -> dict:
    """Use the immutable alert snapshot when present, then fall back safely."""
    raw = row.get("params_json", "")
    if raw:
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            pass
    return {}


# Per-day bar counts under regular trading hours, used to express a holding cap
# in trading days.  4h yields 2 bars/day (08:00, 12:00) -- not 6 -- because RTH
# is only 6.5 hours long.
BARS_PER_DAY = {"1h": 7, "4h": 2, "1d": 1}

# Fallback holding caps mirroring each strategy's own backtest defaults, used
# only when a signal predates params_json or was logged without one.
#   RSI2  -> rsi2_backtest.DEFAULT_PARAMS[tf]["max_hold_bars"]
#   MR    -> mr_backtest.DEFAULT_PARAMS[tf]["max_hold_bars"]
#   Breakout -> breakout_backtest.DEFAULT_PARAMS["max_hold_bars"] (daily only)
# Confluence has no max_hold_bars parameter at all -- it exits via staged TP and
# the utTS/sslExit trail.  The replay still needs a bound, so these approximate
# ~2 trading weeks per timeframe: long enough that the trail almost always fires
# first, short enough that an unresolved signal doesn't stay open indefinitely.
_FALLBACK_HOLD_BARS = {
    ("rsi2", "1h"): 48, ("rsi2", "4h"): 20, ("rsi2", "1d"): 10,
    ("mr", "1h"): 48, ("mr", "4h"): 20, ("mr", "1d"): 60,
    ("breakout", "1d"): 20,
    ("confluence", "1h"): 70, ("confluence", "4h"): 20, ("confluence", "1d"): 10,
}


def _strategy_key(row: pd.Series | dict) -> str:
    """Normalize a ledger strategy name (incl. shadow suffixes) to its family."""
    name = str(row.get("strategy", "")).lower()
    if "rsi2" in name:
        return "rsi2"
    if "breakout" in name:
        return "breakout"
    # Prefix match only: "MRVL_WideExit" contains "mr" but is Confluence-based.
    if name == "mr" or name.startswith("mr_"):
        return "mr"
    return "confluence"


def hold_bars(row: pd.Series | dict, tf: str | None = None) -> int:
    """Resolve how many bars a signal may be held, in that signal's own timeframe.

    Priority: the parameter snapshot taken when the alert fired, then the
    owning strategy's backtest default.  A single shared constant cannot work
    here -- RSI2 1h holds 48 bars while its 1d variant holds 10, and grid-tuned
    symbols carry their own values -- so reading the snapshot is what keeps the
    replay aligned with what the strategy would actually have done.
    """
    tf = tf or str(row.get("tf", "")) or "1d"
    snapshot = _num(signal_params(row).get("max_hold_bars"), 0)
    if snapshot > 0:
        return int(snapshot)
    return _FALLBACK_HOLD_BARS.get((_strategy_key(row), tf), 20)


def hold_description(row: pd.Series | dict, tf: str | None = None) -> str:
    """Human-readable holding cap: bar count plus its trading-day equivalent."""
    tf = tf or str(row.get("tf", "")) or "1d"
    bars = hold_bars(row, tf)
    per_day = BARS_PER_DAY.get(tf)
    if not per_day:
        return f"最长 {bars} 根 {tf} bar"
    days = bars / per_day
    days_text = f"{days:.0f}" if abs(days - round(days)) < 0.05 else f"{days:.1f}"
    return f"最长 {bars} 根 {tf} bar（约 {days_text} 交易日）"


def _future_bars(row: pd.Series | dict, price: pd.DataFrame, max_bars: int) -> pd.DataFrame:
    timestamp = pd.to_datetime(row.get("bar_date") or row.get("timestamp"))
    index = pd.to_datetime(price.index).tz_localize(None)
    data = price.copy()
    data.index = index
    return data[data.index > timestamp].head(max_bars)


def _r(entry: float, exit_price: float, atr: float, direction: str) -> float:
    if atr <= 0:
        return 0.0
    return ((exit_price - entry) / atr) * (1 if direction == "做多" else -1)


def _atr(price: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = price["High"], price["Low"], price["Close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(length).mean()


def _rsi2(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(2).mean()
    loss = (-delta.clip(upper=0)).rolling(2).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def intrabar_bounds(entry: float, sl: float, tp: float, bar: pd.Series, direction: str) -> tuple[str, float, float] | None:
    """Return explicit lower/upper R bounds when a bar touches both levels.

    Open gaps establish a known first event.  For the remaining intrabar path
    OHLC cannot establish order, so the result stays an honest range.
    """
    open_, high, low = map(float, (bar["Open"], bar["High"], bar["Low"]))
    if direction == "做多":
        hit_sl, hit_tp = low <= sl, high >= tp
        if not (hit_sl and hit_tp):
            return None
        if open_ <= sl:
            value = _r(entry, sl, abs(entry - sl), direction)
            return "开盘跳空止损", value, value
        if open_ >= tp:
            value = _r(entry, tp, abs(entry - sl), direction)
            return "开盘跳空止盈", value, value
    else:
        hit_sl, hit_tp = high >= sl, low <= tp
        if not (hit_sl and hit_tp):
            return None
        if open_ >= sl:
            value = _r(entry, sl, abs(entry - sl), direction)
            return "开盘跳空止损", value, value
        if open_ <= tp:
            value = _r(entry, tp, abs(entry - sl), direction)
            return "开盘跳空止盈", value, value
    # Range is reported separately; live strategies are close-driven.
    risk = abs(entry - sl)
    return "同bar双触达（OHLC无法判序）", _r(entry, sl, risk, direction), _r(entry, tp, risk, direction)


def eval_confluence(row: pd.Series | dict, price: pd.DataFrame, max_bars: int) -> dict:
    """Replay staged exits using the same close-driven state transitions as strategy.py."""
    entry, atr = _num(row.get("entry_price")), _num(row.get("atr"))
    direction = str(row.get("direction", "做多"))
    if entry <= 0 or atr <= 0:
        return {"outcome": "数据失败", "r_mult": None, "bars": 0}
    params = signal_params(row)
    tp1 = _num(row.get("tp1"), entry + atr)
    tp2 = _num(row.get("tp2"), entry + 3 * atr)
    fixed_sl = _num(row.get("sl"), entry - atr)
    use_fixed = bool(params.get("use_fixed_initial_sl", True))
    breakeven = bool(params.get("use_breakeven_after_tp1", False))
    ssl_only = params.get("exit_variant") == "ssl_exit"
    future = _future_bars(row, price, max_bars)
    if future.empty:
        return {"outcome": "未决", "r_mult": None, "bars": 0, "exit_model": "close"}

    # Historical logs lack utTS/sslExit.  Recompute when enough raw data exists.
    data = price.copy()
    # Historical backfill may supply a precomputed indicator frame.  Reusing it
    # keeps replay deterministic and avoids recomputing years of indicators per
    # historical event.
    if not {"utTS", "sslExit"}.issubset(data.columns):
        try:
            from indicators import compute_signals
            data = compute_signals(data, params) if params else data
        except Exception:
            pass
    data.index = pd.to_datetime(data.index).tz_localize(None)
    future = data[data.index > pd.to_datetime(row.get("bar_date") or row.get("timestamp"))].head(max_bars)
    stage, realized, ambiguity = 1, 0.0, None
    prev_close = None
    for n, (_, bar) in enumerate(future.iterrows(), 1):
        close = float(bar["Close"])
        utts = _num(bar.get("utTS"), fixed_sl)
        ssl = _num(bar.get("sslExit"), close)
        stop = fixed_sl if use_fixed and stage == 1 else utts
        if stage >= 2 and breakeven:
            stop = max(stop, entry) if direction == "做多" else min(stop, entry)
        bound = intrabar_bounds(entry, stop, tp1 if stage == 1 else tp2, bar, direction)
        if bound and ambiguity is None:
            ambiguity = bound[0]

        hit_stop = (direction == "做多" and close < stop) or (direction == "做空" and close > stop)
        if hit_stop:
            remaining = 1 - sum(STAGED_PORTIONS[:stage - 1])
            realized += remaining * _r(entry, stop, atr, direction)
            return {"outcome": "止损", "r_mult": round(realized, 3), "bars": n, "exit_model": "close", "ambiguity": ambiguity}
        if ssl_only and prev_close is not None:
            crossed = (direction == "做多" and prev_close > ssl and close <= ssl) or (direction == "做空" and prev_close < ssl and close >= ssl)
            if crossed:
                return {"outcome": "SSL追踪出场", "r_mult": round(_r(entry, close, atr, direction), 3), "bars": n, "exit_model": "close", "ambiguity": ambiguity}
            prev_close = close
            continue
        if stage == 1 and ((direction == "做多" and close >= tp1) or (direction == "做空" and close <= tp1)):
            realized += STAGED_PORTIONS[0] * _r(entry, tp1, atr, direction)
            stage = 2
        elif stage == 2 and ((direction == "做多" and close >= tp2) or (direction == "做空" and close <= tp2)):
            realized += STAGED_PORTIONS[1] * _r(entry, tp2, atr, direction)
            stage = 3
        if stage == 3 and prev_close is not None:
            crossed = (direction == "做多" and prev_close > ssl and close <= ssl) or (direction == "做空" and prev_close < ssl and close >= ssl)
            if crossed:
                realized += STAGED_PORTIONS[2] * _r(entry, close, atr, direction)
                return {"outcome": "SSL追踪出场", "r_mult": round(realized, 3), "bars": n, "exit_model": "close", "ambiguity": ambiguity}
        prev_close = close
    remaining = 1 - sum(STAGED_PORTIONS[:stage - 1])
    realized += remaining * _r(entry, float(future["Close"].iloc[-1]), atr, direction)
    # 数据没走完 ≠ 到了持仓上限。走到 future 末尾却还没满 max_bars，说明只是
    # 「行情数据就到这儿了」，仓位其实还开着——这两种情况的语义完全相反。
    # 2026-09-03 之前这里一律返回「时间止损」，后果是 paper_portfolio.update()
    # 把每个刚开的仓在下一轮扫描就判为已平仓：484 笔里 459 笔是「时间止损」、
    # 平均持仓 1.87 根 bar、68% 只持有 1 根 bar，于是权益曲线量的根本不是策略，
    # 而是「每笔交易一根 bar 就砍掉」。options_paper 的平仓判定同样中招。
    if len(future) < max_bars:
        # 返回结构随出场与否而变会坑到调用方（测试就是靠 "ambiguity" 这个键
        # 判断走的是哪条评估路径），故未决也保持本路径的完整结构。
        return {"outcome": "未决", "r_mult": None, "bars": len(future),
                "exit_model": "close", "ambiguity": ambiguity}
    return {"outcome": "时间止损", "r_mult": round(realized, 3), "bars": len(future), "exit_model": "close", "ambiguity": ambiguity}


def eval_rsi2(row: pd.Series | dict, price: pd.DataFrame, max_bars: int) -> dict:
    """Replay RSI2 model C: ATR trail, RSI half exit, then time exit."""
    entry, atr = _num(row.get("entry_price")), _num(row.get("atr"))
    if entry <= 0 or atr <= 0:
        return {"outcome": "数据失败", "r_mult": None, "bars": 0}
    p = signal_params(row)
    trail_mult = _num(p.get("atr_trail_mult"), 2.5)
    sl_mult = _num(p.get("atr_sl_mult"), 1.5)
    half_exit = _num(p.get("rsi2_half_exit"), 80.0)
    split = bool(p.get("use_split_exit", True))
    data = price.copy()
    data["_atr"] = _atr(data)
    data["_rsi2"] = _rsi2(data["Close"])
    future = _future_bars(row, data, max_bars)
    if future.empty:
        return {"outcome": "未决", "r_mult": None, "bars": 0, "exit_model": "close"}
    trail, half_closed, realized = entry - sl_mult * atr, False, 0.0
    for n, (_, bar) in enumerate(future.iterrows(), 1):
        close, current_atr = float(bar["Close"]), _num(bar.get("_atr"), atr)
        trail = max(trail, close - trail_mult * current_atr)
        rsi = _num(bar.get("_rsi2"), 0)
        if split and not half_closed and rsi > half_exit:
            realized += 0.5 * _r(entry, close, atr, "做多")
            half_closed = True
        hit_trail = close < trail
        hit_rsi = not split and rsi > _num(p.get("rsi2_exit"), 80.0)
        if hit_trail or hit_rsi:
            realized += (0.5 if half_closed else 1.0) * _r(entry, close, atr, "做多")
            return {"outcome": "ATR追踪出场" if hit_trail else "RSI出场", "r_mult": round(realized, 3), "bars": n, "exit_model": "close"}
    realized += (0.5 if half_closed else 1.0) * _r(entry, float(future["Close"].iloc[-1]), atr, "做多")
    # 数据没走完 ≠ 到了持仓上限。走到 future 末尾却还没满 max_bars，说明只是
    # 「行情数据就到这儿了」，仓位其实还开着——这两种情况的语义完全相反。
    # 2026-09-03 之前这里一律返回「时间止损」，后果是 paper_portfolio.update()
    # 把每个刚开的仓在下一轮扫描就判为已平仓：484 笔里 459 笔是「时间止损」、
    # 平均持仓 1.87 根 bar、68% 只持有 1 根 bar，于是权益曲线量的根本不是策略，
    # 而是「每笔交易一根 bar 就砍掉」。options_paper 的平仓判定同样中招。
    if len(future) < max_bars:
        return {"outcome": "未决", "r_mult": None, "bars": len(future), "exit_model": "close"}
    return {"outcome": "时间止损", "r_mult": round(realized, 3), "bars": len(future), "exit_model": "close"}


def eval_mr(row: pd.Series | dict, price: pd.DataFrame, max_bars: int) -> dict:
    """Replay MR model: pure ATR trailing stop (ratchets favorably only) + time exit.

    No partial exits and no RSI-based trigger -- unlike RSI2, MR never takes profit
    on an oscillator crossing a level; mr_strategy.py only exits via the trailing
    stop or the hold-bar limit.
    """
    entry, atr = _num(row.get("entry_price")), _num(row.get("atr"))
    if entry <= 0 or atr <= 0:
        return {"outcome": "数据失败", "r_mult": None, "bars": 0}
    p = signal_params(row)
    trail_mult = _num(p.get("atr_trail_mult"), 2.5)
    sl_mult = _num(p.get("atr_sl_mult"), 2.0)
    data = price.copy()
    data["_atr"] = _atr(data)
    future = _future_bars(row, data, max_bars)
    if future.empty:
        return {"outcome": "未决", "r_mult": None, "bars": 0, "exit_model": "close"}
    trail = entry - sl_mult * atr
    for n, (_, bar) in enumerate(future.iterrows(), 1):
        close, current_atr = float(bar["Close"]), _num(bar.get("_atr"), atr)
        trail = max(trail, close - trail_mult * current_atr)
        if close < trail:
            return {"outcome": "ATR追踪出场", "r_mult": round(_r(entry, close, atr, "做多"), 3), "bars": n, "exit_model": "close"}
    # 数据没走完 ≠ 到了持仓上限。走到 future 末尾却还没满 max_bars，说明只是
    # 「行情数据就到这儿了」，仓位其实还开着——这两种情况的语义完全相反。
    # 2026-09-03 之前这里一律返回「时间止损」，后果是 paper_portfolio.update()
    # 把每个刚开的仓在下一轮扫描就判为已平仓：484 笔里 459 笔是「时间止损」、
    # 平均持仓 1.87 根 bar、68% 只持有 1 根 bar，于是权益曲线量的根本不是策略，
    # 而是「每笔交易一根 bar 就砍掉」。options_paper 的平仓判定同样中招。
    if len(future) < max_bars:
        return {"outcome": "未决", "r_mult": None, "bars": len(future), "exit_model": "close"}
    return {"outcome": "时间止损", "r_mult": round(_r(entry, float(future["Close"].iloc[-1]), atr, "做多"), 3),
            "bars": len(future), "exit_model": "close"}


def evaluate(row: pd.Series | dict, price: pd.DataFrame | None, max_bars: int | None = None) -> dict:
    """Replay one signal.  max_bars defaults to the signal's own holding cap.

    Callers should normally omit max_bars so each signal is replayed under the
    parameters it was actually issued with; passing a value stays supported for
    tests and for deliberate what-if runs.
    """
    if price is None or price.empty:
        return {"outcome": "数据失败", "r_mult": None, "bars": 0}
    if max_bars is None:
        max_bars = hold_bars(row)
    family = _strategy_key(row)
    if family == "rsi2":
        return eval_rsi2(row, price, max_bars)
    if family == "mr":
        return eval_mr(row, price, max_bars)
    return eval_confluence(row, price, max_bars)

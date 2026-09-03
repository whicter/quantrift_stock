"""Create isolated historical signal and paper-equity ledgers from local OHLCV.

The output is simulation data only.  It never sends Telegram messages, connects
to IB, changes data CSVs, or appends to the live signal ledger.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from alert_engine import (
    BENCHMARK_SYMBOLS, BREAKOUT_PARAMS, RSI2_PARAMS, SECTOR_ETF_SYMBOLS,
    STRATEGY_MAP, _atr,
)
from breakout_backtest import compute_breakout_signals
from indicators import compute_signals as compute_confluence_signals
from param_loader import get_params
from review_core import evaluate
from rsi2_backtest import DEFAULT_PARAMS as RSI2_DEFAULTS
from rsi2_backtest import compute_signals as compute_rsi2_signals


DATA_DIR = Path("data")
LOG_DIR = Path("logs")
SIGNALS_PATH = LOG_DIR / "backfill_signal_log.csv"
EQUITY_PATH = LOG_DIR / "backfill_paper_equity.csv"
# Holding caps come from each event's own parameters (review_core.hold_bars);
# CONTEXT_PAD only bounds how many bars of look-ahead the replay slice needs.
CONTEXT_PAD = 96  # > any fallback cap (max 70) plus headroom for grid-tuned snapshots
RISK_PCT = 0.0075
POSITION_WEIGHT = 0.10
SEMIS = {"MU", "MRVL", "STX", "SNDK", "NVDA", "INTC", "AMD", "AMAT", "KLAC", "SOXX", "SMH"}
INDICATOR_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def load_data(symbol: str, tf: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    if not path.exists():
        return None
    data = pd.read_csv(path, index_col=0, parse_dates=True)
    data.index = pd.to_datetime(data.index).tz_localize(None)
    data.columns = [column.capitalize() for column in data.columns]
    if not {"Open", "High", "Low", "Close"}.issubset(data.columns):
        return None
    if "Volume" not in data:
        data["Volume"] = 0
    return data.sort_index()


def _quality_confluence(row: pd.Series, direction: str, adx_threshold: float) -> int:
    active = float(row["bullScore"] if direction == "做多" else row["bearScore"])
    signal = active / 6 * 5
    adx = float(row["adx"])
    adx_pts = min(2.5, max(0.0, (adx / adx_threshold - 1) * 2.5)) if adx_threshold else 0.0
    regime = min(2.5, max(0.0, float(row.get("market_score", 4)) / 4 * 2.5))
    return round(min(10, max(0, signal + adx_pts + regime)))


def confluence_candidates(symbol: str, tf: str, raw: pd.DataFrame, qqq: pd.DataFrame | None,
                          params: dict, strategy: str = "Confluence") -> list[dict]:
    sig = compute_confluence_signals(raw, params, qqq)
    INDICATOR_CACHE[(symbol, tf)] = sig
    min_score = int(params.get("min_score", 5))
    conflict = int(params.get("conflict_threshold", 2))
    use_adx, use_vol = bool(params.get("use_adx", True)), bool(params.get("use_vol", True))
    threshold = float(params.get("adx_threshold", 25))
    not_choppy = ~sig["isChoppy"].fillna(True).astype(bool)
    long = ((sig["bullScore"] >= min_score) & (sig["bearScore"] <= conflict) & not_choppy)
    short = ((sig["bearScore"] >= min_score) & (sig["bullScore"] <= conflict) & not_choppy)
    if use_adx:
        long &= sig["adx"] >= threshold
        short &= sig["adx"] >= threshold
    if use_vol:
        long &= sig["isHighVol"].fillna(False).astype(bool)
        short &= sig["isHighVol"].fillna(False).astype(bool)
    if bool(params.get("use_regime_filter", False)):
        long &= sig["market_score"] >= int(params.get("min_market_score", 2))
    if not bool(params.get("allow_short", True)):
        short &= False
    # A continuous setup is one historical opportunity, not a new independent
    # paper position on every bar it remains true.
    long &= ~long.shift(1, fill_value=False)
    short &= ~short.shift(1, fill_value=False)
    events = []
    for timestamp, row in sig[long | short].iterrows():
        direction = "做多" if bool(long.loc[timestamp]) else "做空"
        atr, close = float(row["atrVal"]), float(row["Close"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        sign = 1 if direction == "做多" else -1
        events.append({
            "timestamp": timestamp, "bar_date": timestamp.strftime("%Y-%m-%d"), "symbol": symbol, "tf": tf,
            "strategy": strategy, "source": "historical_backfill", "is_shadow": strategy.endswith("_shadow"),
            "direction": direction, "entry_price": close, "atr": atr,
            "tp1": close + sign * float(params.get("atr_tp1_mult", 1)) * atr,
            "tp2": close + sign * float(params.get("atr_tp2_mult", 2)) * atr,
            "sl": float(row["utTS"]), "market_score": float(row.get("market_score", 4)), "vix": "",
            "quality": _quality_confluence(row, direction, threshold), "params_json": json.dumps(params, sort_keys=True),
        })
    return events


def rsi2_candidates(symbol: str, tf: str, raw: pd.DataFrame, qqq: pd.DataFrame | None,
                    params: dict, strategy: str = "RSI2", ibs_only: bool = False) -> list[dict]:
    benchmark, sector = symbol in BENCHMARK_SYMBOLS, symbol in SECTOR_ETF_SYMBOLS
    sig = compute_rsi2_signals(raw, params, qqq, is_benchmark=benchmark, is_sector_etf=sector)
    mask = (sig["Close"] > sig["sma200"]) & (sig["rsi2"] < float(params["rsi2_entry"]))
    mask &= sig["market_score"] >= int(params["min_market_score"])
    if bool(params.get("use_pullback_filter", False)):
        mask &= sig["pullback_ok"].astype(bool)
    if bool(params.get("use_rs_filter", True)) and not benchmark:
        mask &= sig["rs_positive"].astype(bool)
    if ibs_only:
        width = sig["High"] - sig["Low"]
        mask &= ((sig["Close"] - sig["Low"]) / width.replace(0, float("nan"))) < 0.2
    mask &= ~mask.shift(1, fill_value=False)
    events = []
    for timestamp, row in sig[mask].iterrows():
        atr, close = float(row["atrVal"]), float(row["Close"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        rsi_points = max(0.0, 4 * (1 - float(row["rsi2"]) / float(params["rsi2_entry"])))
        quality = round(min(10, max(0, rsi_points + min(4, float(row["market_score"])))))
        events.append({
            "timestamp": timestamp, "bar_date": timestamp.strftime("%Y-%m-%d"), "symbol": symbol, "tf": tf,
            "strategy": strategy, "source": "historical_backfill", "is_shadow": strategy.endswith("_shadow"),
            "direction": "做多", "entry_price": close, "atr": atr, "tp1": 0.0, "tp2": 0.0,
            "sl": close - float(params["atr_trail_mult"]) * atr, "market_score": float(row["market_score"]),
            "vix": "", "quality": quality, "params_json": json.dumps(params, sort_keys=True),
        })
    return events


def breakout_candidates(symbol: str, raw: pd.DataFrame, params: dict, strategy: str = "Breakout52W") -> list[dict]:
    sig = compute_breakout_signals(raw, params)
    mask = (sig["Close"] > sig["sma200"]) & sig["breakout"].astype(bool)
    if bool(params.get("use_vol_filter", False)):
        mask &= sig["vol_surge"].astype(bool)
    mask &= ~mask.shift(1, fill_value=False)
    events = []
    for timestamp, row in sig[mask].iterrows():
        atr, close = float(row["atrVal"]), float(row["Close"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        events.append({
            "timestamp": timestamp, "bar_date": timestamp.strftime("%Y-%m-%d"), "symbol": symbol, "tf": "1d",
            "strategy": strategy, "source": "historical_backfill", "is_shadow": strategy.endswith("_shadow"),
            "direction": "做多", "entry_price": close, "atr": atr,
            "tp1": close + 2 * atr, "tp2": close + float(params["atr_trail_mult"]) * atr,
            "sl": close - float(params["atr_sl_mult"]) * atr, "market_score": 4.0, "vix": "", "quality": 7,
            "params_json": json.dumps(params, sort_keys=True),
        })
    return events


def _eval_breakout(row: dict, price: pd.DataFrame) -> dict:
    params = json.loads(row["params_json"])
    future = price[price.index > pd.Timestamp(row["timestamp"])].head(int(params["max_hold_bars"]))
    if future.empty:
        return {"outcome": "未决", "r_mult": None, "bars": 0, "exit_date": ""}
    trail = float(row["sl"])
    for bars, (timestamp, bar) in enumerate(future.iterrows(), 1):
        close = float(bar["Close"])
        history = price.loc[:timestamp]
        atr = float(_atr(history["High"], history["Low"], history["Close"], 14).iloc[-1])
        if math.isfinite(atr):
            trail = max(trail, close - float(params["atr_trail_mult"]) * atr)
        if close < trail:
            return {"outcome": "ATR追踪出场", "r_mult": round((close - float(row["entry_price"])) / float(row["atr"]), 3), "bars": bars, "exit_date": timestamp.isoformat()}
    close = float(future["Close"].iloc[-1])
    return {"outcome": "时间止损", "r_mult": round((close - float(row["entry_price"])) / float(row["atr"]), 3), "bars": len(future), "exit_date": future.index[-1].isoformat()}


def event_context(price: pd.DataFrame, timestamp: pd.Timestamp, tf: str) -> pd.DataFrame:
    """Give replay enough indicator warm-up without recomputing years of history per event."""
    position = price.index.get_indexer([timestamp], method="nearest")[0]
    before = max(0, position - 260)
    after = min(len(price), position + CONTEXT_PAD + 2)
    return price.iloc[before:after]


def run_backfill() -> pd.DataFrame:
    events: list[dict] = []
    # Explicit live routes only; do not backfill known-default fall-through routes.
    for (symbol, tf), strategy in STRATEGY_MAP.items():
        if ":" in tf or strategy == "breakout":
            continue
        raw, qqq = load_data(symbol, tf), load_data("QQQ", tf)
        if raw is None:
            continue
        if strategy == "confluence":
            events += confluence_candidates(symbol, tf, raw, qqq, get_params(symbol, tf))
        elif strategy == "rsi2":
            # 必须用 .get：STRATEGY_MAP 里新增的 rsi2 路由不一定在 RSI2_PARAMS 里
            # 有专属参数（走 DEFAULTS 即可）。直接下标会 KeyError——2026-07-26 把
            # MU/STX 1h 从 confluence 升级成 rsi2 后，本脚本就是这样静默崩掉的，
            # 到 9/3 才发现回填账本停在 7/24 整整六周没更新。alert_engine 一直用
            # 的就是 .get，这里与它对齐。
            params = {**RSI2_DEFAULTS[tf], **RSI2_PARAMS.get((symbol, tf), {})}
            events += rsi2_candidates(symbol, tf, raw, qqq, params)
            events += rsi2_candidates(symbol, tf, raw, qqq, params, strategy="RSI2_IBS_shadow", ibs_only=True)
    # Shadow exit variants, independent of whether they are primary live routes.
    for symbol, tf, name, changes in (
        ("TSLA", "4h", "TSLA_SSLTrail_shadow", {"exit_variant": "ssl_exit"}),
        ("MRVL", "1h", "MRVL_WideExit_shadow", {"atr_tp2_mult": 4.0}),
    ):
        raw, qqq = load_data(symbol, tf), load_data("QQQ", tf)
        if raw is not None:
            events += confluence_candidates(symbol, tf, raw, qqq, {**get_params(symbol, tf), **changes}, name)
    for symbol, params in BREAKOUT_PARAMS.items():
        raw = load_data(symbol, "1d")
        if raw is not None:
            events += breakout_candidates(symbol, raw, params)
    rklb = load_data("RKLB", "1d")
    if rklb is not None:
        events += breakout_candidates("RKLB", rklb, {"confirm_days": 1, "atr_trail_mult": 3.0, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False}, "RKLB_Breakout_shadow")
    print(f"候选信号: {len(events)}", flush=True)
    rows = []
    for index, event in enumerate(events, 1):
        price = INDICATOR_CACHE.get((event["symbol"], event["tf"]), load_data(event["symbol"], event["tf"]))
        context = event_context(price, pd.Timestamp(event["timestamp"]), event["tf"])
        result = _eval_breakout(event, context) if "breakout" in event["strategy"].lower() else evaluate(event, context)
        if "exit_date" not in result and result["bars"]:
            future = context[context.index > pd.Timestamp(event["timestamp"])].head(result["bars"])
            result["exit_date"] = future.index[-1].isoformat() if not future.empty else ""
        rows.append({**event, **result})
        if index % 500 == 0:
            print(f"已复盘 {index}/{len(events)}", flush=True)
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol", "strategy"]).reset_index(drop=True)


def build_equity(events: pd.DataFrame) -> pd.DataFrame:
    """Create a chronological, non-overlapping paper-position ledger.

    Each position fixes its dollar risk when it opens.  Therefore a trade that
    closes later cannot be sized with capital earned by another, overlapping
    trade.  This is deliberately a baseline portfolio simulation: it records
    exposure warnings but does not model the unfinished Pyramiding state machine.
    """
    columns = [
        "event_time", "event_type", "decision", "signal_time", "exit_date", "symbol", "tf", "strategy",
        "r_mult", "risk_pct", "risk_dollars", "equity_before", "equity_after", "open_positions",
        "symbol_weight", "semi_weight", "semi_exposure", "max_equity", "drawdown_pct",
    ]
    decided = events.copy()
    decided["r_mult"] = pd.to_numeric(decided["r_mult"], errors="coerce")
    decided["entry_time"] = pd.to_datetime(decided["timestamp"], errors="coerce")
    decided["exit_time"] = pd.to_datetime(decided["exit_date"], errors="coerce")
    decided = decided.dropna(subset=["r_mult", "entry_time", "exit_time"])
    decided = decided[decided["exit_time"] > decided["entry_time"]].sort_values(
        ["entry_time", "symbol", "strategy"]
    )

    equity = max_equity = 100000.0
    active: list[dict] = []
    rows: list[dict] = []

    def exposure(symbol: str) -> tuple[float, float]:
        return (
            sum(position["weight"] for position in active if position["symbol"] == symbol),
            sum(position["weight"] for position in active if position["symbol"] in SEMIS),
        )

    def close_due(until: pd.Timestamp) -> None:
        nonlocal equity, max_equity, active
        due = sorted((position for position in active if position["exit_time"] <= until), key=lambda position: position["exit_time"])
        active = [position for position in active if position["exit_time"] > until]
        for position in due:
            before = equity
            equity = round(equity + position["risk_dollars"] * position["r_mult"], 2)
            max_equity = max(max_equity, equity)
            symbol_weight, semi_exposure = exposure(position["symbol"])
            rows.append({
                "event_time": position["exit_time"], "event_type": "exit", "decision": position["outcome"],
                "signal_time": position["entry_time"], "exit_date": position["exit_time"],
                "symbol": position["symbol"], "tf": position["tf"], "strategy": position["strategy"],
                "r_mult": position["r_mult"], "risk_pct": RISK_PCT, "risk_dollars": position["risk_dollars"],
                "equity_before": before, "equity_after": equity, "open_positions": len(active),
                "symbol_weight": symbol_weight, "semi_weight": POSITION_WEIGHT if position["symbol"] in SEMIS else 0.0,
                "semi_exposure": semi_exposure, "max_equity": max_equity,
                "drawdown_pct": round((equity / max_equity - 1) * 100, 3),
            })

    for _, event in decided.iterrows():
        entry_time = event["entry_time"]
        close_due(entry_time)
        identity = (event["symbol"], event["tf"], event["strategy"])
        duplicate = any(position["identity"] == identity for position in active)
        symbol_weight, semi_exposure = exposure(event["symbol"])
        if duplicate:
            decision = "skip_duplicate_active"
        elif len(active) >= 10:
            decision = "skip_max_open_positions"
        else:
            decision = "open_semi_exposure_warning" if event["symbol"] in SEMIS and semi_exposure + POSITION_WEIGHT > 0.45 else "open"
        if decision.startswith("skip"):
            rows.append({
                "event_time": entry_time, "event_type": "entry", "decision": decision,
                "signal_time": entry_time, "exit_date": event["exit_time"], "symbol": event["symbol"], "tf": event["tf"],
                "strategy": event["strategy"], "r_mult": event["r_mult"], "risk_pct": RISK_PCT, "risk_dollars": 0.0,
                "equity_before": equity, "equity_after": equity, "open_positions": len(active),
                "symbol_weight": symbol_weight, "semi_weight": POSITION_WEIGHT if event["symbol"] in SEMIS else 0.0,
                "semi_exposure": semi_exposure, "max_equity": max_equity,
                "drawdown_pct": round((equity / max_equity - 1) * 100, 3),
            })
            continue
        risk_dollars = round(equity * RISK_PCT, 2)
        active.append({
            "identity": identity, "entry_time": entry_time, "exit_time": event["exit_time"], "risk_dollars": risk_dollars,
            "r_mult": float(event["r_mult"]), "outcome": event["outcome"], "symbol": event["symbol"], "tf": event["tf"],
            "strategy": event["strategy"], "weight": POSITION_WEIGHT,
        })
        symbol_weight, semi_exposure = exposure(event["symbol"])
        rows.append({
            "event_time": entry_time, "event_type": "entry", "decision": decision,
            "signal_time": entry_time, "exit_date": event["exit_time"], "symbol": event["symbol"], "tf": event["tf"],
            "strategy": event["strategy"], "r_mult": event["r_mult"], "risk_pct": RISK_PCT, "risk_dollars": risk_dollars,
            "equity_before": equity, "equity_after": equity, "open_positions": len(active),
            "symbol_weight": symbol_weight, "semi_weight": POSITION_WEIGHT if event["symbol"] in SEMIS else 0.0,
            "semi_exposure": semi_exposure, "max_equity": max_equity,
            "drawdown_pct": round((equity / max_equity - 1) * 100, 3),
        })
    close_due(pd.Timestamp.max)
    return pd.DataFrame(rows, columns=columns).sort_values(["event_time", "event_type"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="历史信号与纸面组合回填（仅本地 CSV）")
    parser.add_argument("--write", action="store_true", help="写入独立 backfill CSV 文件")
    args = parser.parse_args()
    events = run_backfill()
    equity = build_equity(events)
    print(f"回填信号: {len(events)}；已决: {len(equity)}；影子: {int(events['is_shadow'].sum())}")
    if args.write:
        LOG_DIR.mkdir(exist_ok=True)
        events.to_csv(SIGNALS_PATH, index=False)
        equity.to_csv(EQUITY_PATH, index=False)
        print(f"已写入 {SIGNALS_PATH} 和 {EQUITY_PATH}")


if __name__ == "__main__":
    main()

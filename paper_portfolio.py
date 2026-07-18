"""Persistent paper-only portfolio for signal risk context.

Entries are virtual records created from alerts.  No broker API is imported.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from review_core import evaluate

POSITIONS_PATH = Path("data/.paper_positions.json")
EQUITY_PATH = Path("logs/paper_equity.csv")
SEMIS = {"MU", "MRVL", "STX", "SNDK", "NVDA", "INTC", "AMD", "AMAT", "KLAC", "SOXX", "SMH"}
RISK_PCT = 0.0075
POSITION_WEIGHT = 0.10
SECTOR_LIMIT = 0.45


def load() -> dict:
    if not POSITIONS_PATH.exists():
        return {"equity": 100000.0, "positions": [], "events": []}
    try:
        return json.loads(POSITIONS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"equity": 100000.0, "positions": [], "events": []}


def save(book: dict) -> None:
    POSITIONS_PATH.parent.mkdir(exist_ok=True)
    POSITIONS_PATH.write_text(json.dumps(book, ensure_ascii=False, indent=2))


def _open_positions(book: dict) -> list[dict]:
    return [p for p in book["positions"] if p.get("status") == "open"]


def risk_warnings(symbol: str, book: dict | None = None) -> list[str]:
    book = book or load()
    open_positions = _open_positions(book)
    same_symbol = sum(1 for p in open_positions if p["symbol"] == symbol)
    semis = sum(POSITION_WEIGHT for p in open_positions if p["symbol"] in SEMIS)
    warnings = []
    if same_symbol >= 1:
        warnings.append("⚠️ 虚拟账本：该标的已有仓位；单标的新增风险将超过 0.75% equity")
    if symbol in SEMIS and semis + POSITION_WEIGHT > SECTOR_LIMIT:
        warnings.append("⚠️ 虚拟账本：半导体总暴露将超过 45%")
    return warnings


def open_position(row: dict, book: dict | None = None) -> list[str]:
    book = book or load()
    signal_id = row.get("signal_id") or f"{row['symbol']}|{row['tf']}|{row['strategy']}|{row['bar_date']}"
    if any(p.get("signal_id") == signal_id for p in book["positions"]):
        return []
    warnings = risk_warnings(str(row["symbol"]), book)
    book["positions"].append({
        **row, "signal_id": signal_id, "opened_at": datetime.now().isoformat(timespec="seconds"),
        "status": "open", "risk_pct": RISK_PCT, "weight": POSITION_WEIGHT,
        "tp1_seen": False, "pyramiding_notified": False,
    })
    save(book)
    return warnings


def update(price_by_key: dict[tuple[str, str], pd.DataFrame], max_bars: dict[str, int]) -> list[dict]:
    """Close virtual positions using the shared replay; return new status events."""
    book, events = load(), []
    for position in _open_positions(book):
        price = price_by_key.get((position["symbol"], position["tf"]))
        if price is not None and not price.empty and position.get("tp1"):
            after = price[pd.to_datetime(price.index).tz_localize(None) > pd.to_datetime(position.get("bar_date") or position["timestamp"])]
            tp1 = float(position["tp1"])
            direction = position.get("direction", "做多")
            reached = (after["High"] >= tp1).any() if direction == "做多" else (after["Low"] <= tp1).any()
            if reached and not position.get("tp1_seen"):
                position["tp1_seen"] = True
                position["tp1_seen_at"] = datetime.now().isoformat(timespec="seconds")
            if position.get("tp1_seen") and not position.get("pyramiding_notified") and len(after) >= 2:
                latest, prior = float(after["High"].iloc[-1]), float(after["High"].iloc[:-1].max())
                continuing = latest > prior if direction == "做多" else float(after["Low"].iloc[-1]) < float(after["Low"].iloc[:-1].min())
                if continuing:
                    position["pyramiding_notified"] = True
                    events.append({"type": "pyramid", "symbol": position["symbol"], "outcome": "TP1后创新高", "r_mult": 0.0})
        outcome = evaluate(position, price, max_bars.get(position["tf"], 10))
        if outcome["outcome"] == "未决":
            continue
        position.update(outcome)
        position["status"] = "closed"
        position["closed_at"] = datetime.now().isoformat(timespec="seconds")
        r_mult = float(outcome.get("r_mult") or 0)
        book["equity"] = round(float(book["equity"]) * (1 + RISK_PCT * r_mult), 2)
        events.append({"type": "closed", "symbol": position["symbol"], "outcome": outcome["outcome"], "r_mult": r_mult})
    if events:
        EQUITY_PATH.parent.mkdir(exist_ok=True)
        new = not EQUITY_PATH.exists()
        with open(EQUITY_PATH, "a") as fh:
            if new:
                fh.write("timestamp,equity,event,symbol,r_mult\n")
            for event in events:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')},{book['equity']},{event['type']},{event['symbol']},{event['r_mult']}\n")
        book["events"].extend(events)
        book["events"] = book["events"][-200:]
        save(book)
    return events

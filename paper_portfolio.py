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
SEMIS = {"MU", "MRVL", "STX", "SNDK", "NVDA", "INTC", "AMD", "AMAT", "KLAC", "SOXX", "SMH", "TSM"}
RISK_PCT = 0.0075
POSITION_WEIGHT = 0.10
SECTOR_LIMIT = 0.45

# 同板块并发持仓上限（2026-09-04 起）。
#
# 此前只有 risk_warnings() 发一句警告、open_position() 照开不误，而且只认上面
# 那个写死的 12 个半导体标的。实测 45 天里同日同板块 ≥4 条信号出现了 21 天，
# 单日单板块最多 9 条（7/28 半导体）——每仓 0.75% 风险 × 9 个同向标的 = 6.75%
# 权益同涨同跌，这就是 -33% 回撤的来源。
#
# 用 264 笔已决交易回放不同上限（收益 / 最大回撤 / 比值）：
#   不限 +7.99% / -33.13% / 0.24      5 → +9.17% / -28.26% / 0.32
#   4    +16.33% / -24.27% / 0.67     3 → +15.35% / -20.14% / 0.76
#   2    +11.04% / -16.43% / 0.67
# 2-5 全都改善回撤，方向是稳的；但精确最优值属样本内拟合，别把 4 当成调出来的
# 参数——它只是"限制同板块并发"这个结构性约束的一个合理取值。
#
# **只约束纸面组合的建仓，不过滤信号推送**——用户明确要求信号全发。
SECTOR_MAX_CONCURRENT = 4


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


_sector_cache: dict[str, str] = {}


def _sector(symbol: str) -> str:
    """真实板块归类。原来用写死的 12 个半导体标的，覆盖不到其余 96 个已路由标的。"""
    if not symbol:
        return ""
    if symbol not in _sector_cache:
        try:
            from sector_map import sector_of
            _sector_cache[symbol] = sector_of(symbol) or ""
        except Exception:
            _sector_cache[symbol] = "半导体" if symbol in SEMIS else ""
    return _sector_cache[symbol]


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

    # 同板块并发上限：超了就不建仓（信号照发，只是纸面组合不吃这一笔）
    sector = _sector(str(row["symbol"]))
    if sector:
        same = sum(1 for p in _open_positions(book) if _sector(p.get("symbol", "")) == sector)
        if same >= SECTOR_MAX_CONCURRENT:
            warnings.append(f"⚠️ 虚拟账本：{sector} 已有 {same} 个并发仓位"
                            f"（上限 {SECTOR_MAX_CONCURRENT}），本笔不建仓")
            return warnings

    book["positions"].append({
        **row, "signal_id": signal_id, "opened_at": datetime.now().isoformat(timespec="seconds"),
        "status": "open", "risk_pct": RISK_PCT, "weight": POSITION_WEIGHT,
        "sector": sector, "tp1_seen": False, "pyramiding_notified": False,
    })
    save(book)
    return warnings


def update(price_by_key: dict[tuple[str, str], pd.DataFrame],
           max_bars: dict[str, int] | None = None) -> list[dict]:
    """Close virtual positions using the shared replay; return new status events.

    max_bars is accepted for backward compatibility but ignored: each position
    is replayed under its own recorded holding cap, so the virtual equity curve
    matches what the issuing strategy would actually have done.
    """
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
        outcome = evaluate(position, price)
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

"""
execution_ledger.py — 记录"你实际执行了什么"（Telegram 长轮询，绝不下单）

背景（2026-08-15）：系统此前只知道自己发了什么信号，完全不知道用户实际接了哪些、
什么价成交、什么时候出的。所有 R 值都是"下一根 bar 开盘成交 + 严格按 SL 出场"的
理论值。没有这份账本，"这套系统到底赚不赚钱"永远只能靠推测——这是从信号系统
走向盈利系统的关键缺口。

用法（在 Telegram 里直接发，不必回复某条消息）：
  接 NVDA 176.5        记录入场成交价（可选 @数量：接 NVDA 176.5 @100）
  平 NVDA 182.3        记录出场成交价
  跳过 NVDA            明确记录"看到了但没接"（区别于"没看到"，对复盘同样有价值）
  账本                 查看当前未平仓记录与近期统计

匹配规则：命令里的标的会去 `logs/signal_log.csv` 找该标的**最近一条**未平仓信号
并挂钩；找不到就作为独立记录存下（用户可能接的是系统没发过的票，照记不误）。

安全边界：
  - 本模块只读 signal_log、只写 execution_log，**不连 IB、不下任何单**
  - 与期货项目的 `ib-bot-tg-control` 用的是不同 bot token（已核对：
    stock 8864211814 vs future 8882740685），不冲突；同一 token 全局只能有
    一个 getUpdates 消费者，新增轮询前必须确认这一点
"""

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TG_TOKEN", "")
CHAT_ID = os.getenv("TG_CHAT_ID", "")
LEDGER_PATH = Path("logs/execution_log.csv")
STATE_PATH = Path("data/.exec_ledger_state.json")
SIGNAL_LOG = Path("logs/signal_log.csv")

FIELDS = ["timestamp", "action", "symbol", "price", "qty", "signal_id",
          "signal_time", "signal_strategy", "signal_tf", "signal_direction",
          "signal_entry", "signal_sl", "note"]

# 中英文都接受，容错常见变体
_ACTION_WORDS = {
    "接": "entry", "接了": "entry", "买": "entry", "buy": "entry", "开": "entry",
    "平": "exit", "平了": "exit", "卖": "exit", "sell": "exit", "出": "exit",
    "跳过": "skip", "不接": "skip", "skip": "skip", "pass": "skip",
}
_CMD_RE = re.compile(
    r"^\s*(?P<action>[一-龥]+|[A-Za-z]+)\s+(?P<symbol>[A-Za-z][A-Za-z.\-]{0,9})"
    r"(?:\s+(?P<price>\d+(?:\.\d+)?))?(?:\s*@\s*(?P<qty>\d+))?\s*$")


def tg_send(text: str) -> None:
    if not TOKEN or not CHAT_ID:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                               data=data, timeout=15)
    except Exception:
        pass


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"offset": None}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def _read_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    try:
        with open(LEDGER_PATH, newline="") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def _append_ledger(row: dict) -> None:
    LEDGER_PATH.parent.mkdir(exist_ok=True)
    exists = LEDGER_PATH.exists()
    if exists:
        # 与 screener_results / review_history 同类事故的预防：追加前校验表头
        with open(LEDGER_PATH) as fh:
            if fh.readline().strip().split(",") != FIELDS:
                LEDGER_PATH.rename(LEDGER_PATH.with_suffix(
                    f".schema-{datetime.now():%Y%m%d}.bak"))
                exists = False
    with open(LEDGER_PATH, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def find_recent_signal(symbol: str) -> dict | None:
    """找该标的最近一条实盘（非影子）信号。"""
    if not SIGNAL_LOG.exists():
        return None
    try:
        with open(SIGNAL_LOG, newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if r.get("symbol", "").upper() == symbol.upper()
                    and str(r.get("is_shadow", "0")) != "1"]
        return rows[-1] if rows else None
    except Exception:
        return None


def open_positions() -> list[dict]:
    """账本里已入场但还没记录出场的标的。"""
    ledger = _read_ledger()
    state: dict[str, dict] = {}
    for row in ledger:
        sym = row.get("symbol", "").upper()
        if row.get("action") == "entry":
            state[sym] = row
        elif row.get("action") == "exit":
            state.pop(sym, None)
    return list(state.values())


def handle_command(text: str) -> str | None:
    """解析一条消息；不是账本命令则返回 None（静默忽略普通聊天）。"""
    stripped = text.strip()
    if stripped in ("账本", "ledger", "/ledger"):
        return _ledger_summary()

    m = _CMD_RE.match(stripped)
    if not m:
        return None
    action = _ACTION_WORDS.get(m.group("action").lower())
    if not action:
        return None

    symbol = m.group("symbol").upper()
    price = m.group("price")
    qty = m.group("qty") or ""

    if action in ("entry", "exit") and not price:
        return f"⚠️ {symbol} 缺成交价。格式：接 {symbol} 176.5"

    sig = find_recent_signal(symbol)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action, "symbol": symbol, "price": price or "", "qty": qty,
        "signal_id": (sig or {}).get("signal_id", ""),
        "signal_time": (sig or {}).get("timestamp", ""),
        "signal_strategy": (sig or {}).get("strategy", ""),
        "signal_tf": (sig or {}).get("tf", ""),
        "signal_direction": (sig or {}).get("direction", ""),
        "signal_entry": (sig or {}).get("entry_price", ""),
        "signal_sl": (sig or {}).get("sl", ""),
        "note": "" if sig else "无匹配信号（可能是系统未覆盖的标的）",
    }
    _append_ledger(row)

    if action == "skip":
        return f"✅ 已记录：{symbol} 跳过未接"
    if action == "entry":
        slip = ""
        if sig and price:
            try:
                ref = float(sig["entry_price"])
                d = (float(price) - ref) / ref * 100
                slip = f"　信号价 ${ref:.2f}，滑点 {d:+.2f}%"
            except Exception:
                pass
        sl = (sig or {}).get("sl", "")
        return (f"✅ 已记录入场：{symbol} ${price}{f' × {qty}' if qty else ''}\n"
                f"{slip}\n参考止损 ${sl}" if sig else
                f"✅ 已记录入场：{symbol} ${price}（无匹配信号）")
    # exit
    entry_row = next((r for r in reversed(_read_ledger())
                      if r.get("symbol") == symbol and r.get("action") == "entry"), None)
    pnl = ""
    if entry_row and entry_row.get("price"):
        try:
            e, x = float(entry_row["price"]), float(price)
            short = (entry_row.get("signal_direction") == "做空")
            ret = (e - x) / e * 100 if short else (x - e) / e * 100
            pnl = f"　实际收益 {ret:+.2f}%"
        except Exception:
            pass
    return f"✅ 已记录出场：{symbol} ${price}\n{pnl}"


def _ledger_summary() -> str:
    ledger = _read_ledger()
    if not ledger:
        return "📒 执行账本为空。用「接 NVDA 176.5」开始记录。"
    entries = [r for r in ledger if r["action"] == "entry"]
    exits = [r for r in ledger if r["action"] == "exit"]
    skips = [r for r in ledger if r["action"] == "skip"]
    lines = [f"📒 执行账本：入场 {len(entries)}　出场 {len(exits)}　跳过 {len(skips)}"]

    opens = open_positions()
    if opens:
        lines.append("\n持仓中：")
        for r in opens:
            tag = f"　{r['signal_strategy']} {r['signal_tf']}" if r.get("signal_strategy") else ""
            lines.append(f"· {r['symbol']} ${r['price']}{tag}")

    # 已配对的真实收益：这是系统唯一能看到的"真金白银"口径
    paired, total = [], 0.0
    for ex in exits:
        en = next((r for r in entries
                   if r["symbol"] == ex["symbol"] and r["timestamp"] <= ex["timestamp"]), None)
        if en and en.get("price") and ex.get("price"):
            try:
                e, x = float(en["price"]), float(ex["price"])
                ret = (e - x) / e * 100 if en.get("signal_direction") == "做空" else (x - e) / e * 100
                paired.append(ret)
                total += ret
            except Exception:
                pass
    if paired:
        wins = sum(1 for r in paired if r > 0)
        lines.append(f"\n已平仓 {len(paired)} 笔　胜率 {wins/len(paired)*100:.0f}%　"
                     f"累计 {total:+.1f}%　单笔均值 {total/len(paired):+.2f}%")
    return "\n".join(lines)


def main() -> None:
    if not TOKEN or not CHAT_ID:
        print("未配置 TG_TOKEN/TG_CHAT_ID，退出")
        return
    state = _load_state()
    offset = state.get("offset")
    print(f"执行账本轮询启动（offset={offset}）")

    while True:
        try:
            url = (f"https://api.telegram.org/bot{TOKEN}/getUpdates?timeout=25"
                   + (f"&offset={offset}" if offset is not None else ""))
            with urllib.request.urlopen(url, timeout=35) as resp:
                payload = json.loads(resp.read().decode())
            if not payload.get("ok"):
                time.sleep(5)
                continue
            for upd in payload.get("result", []):
                offset = int(upd["update_id"]) + 1
                msg = upd.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
                    continue
                text = msg.get("text", "")
                if not text:
                    continue
                try:
                    reply = handle_command(text)
                except Exception as exc:
                    reply = f"⚠️ 记录失败：{exc}"
                if reply:
                    print(f"[{datetime.now():%H:%M:%S}] {text!r} → 已回复")
                    tg_send(reply)
            _save_state({"offset": offset})
        except Exception as exc:
            print(f"轮询异常（10秒后重试）: {exc}")
            time.sleep(10)


if __name__ == "__main__":
    main()

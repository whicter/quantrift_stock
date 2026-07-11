"""
signal_review.py — 信号复盘脚本

从 logs/signal_log.csv 读取历史信号，拉取后续价格，逐条评估结果。

结果说明：
  - Confluence 信号（有 TP1/TP2/SL）：判断哪个先被触及
  - RSI2 信号（只有 SL）：判断是否止损，否则显示当前浮盈 R 值
  - SL 使用信号时刻固定值（RSI2 实盘为追踪止损，复盘偏保守）

用法：
  python signal_review.py              # 复盘所有信号
  python signal_review.py --days 30    # 只看最近 30 天
  python signal_review.py --symbol MU  # 只看某标的
  python signal_review.py --tf 1d      # 只看某周期（1h/4h/1d）
  python signal_review.py --add        # 手动补录一条历史信号
"""

import argparse
import csv
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

SIGNAL_LOG = Path("logs/signal_log.csv")
LOG_FIELDS = [
    "timestamp", "bar_date", "symbol", "tf", "strategy", "direction",
    "entry_price", "atr", "tp1", "tp2", "sl",
    "market_score", "vix", "quality",
]


# ── 价格数据获取 ────────────────────────────────────────────────────────────

DATA_DIR = Path("data")

def _load_local_csv(symbol: str, interval: str) -> pd.DataFrame | None:
    """尝试从本地 data/ 目录读取已有 CSV（IB 抓取的历史数据）。"""
    tf_map = {"1h": "1h", "1d": "1d"}
    tf = tf_map.get(interval)
    if tf is None:
        return None
    path = DATA_DIR / f"{symbol}_{tf}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        # 统一列名
        col_map = {c: c.capitalize() for c in df.columns}
        df = df.rename(columns=col_map)
        for col in ["Open", "High", "Low", "Close"]:
            if col not in df.columns:
                return None
        return df
    except Exception:
        return None


def _fetch(symbol: str, start: str, interval: str = "1d") -> pd.DataFrame | None:
    """先查本地 CSV，缺失再用 yfinance 拉取（自动限速）。"""
    # 1. 先试本地 CSV
    local = _load_local_csv(symbol, interval)
    if local is not None and not local.empty:
        cutoff = pd.to_datetime(start).tz_localize(None)
        filtered = local[local.index >= cutoff]
        if not filtered.empty:
            return filtered

    # 2. 回退 yfinance（限速：每次请求前等 2 秒）
    time.sleep(2)
    try:
        df = yf.download(symbol, start=start, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:
        print(f"  ⚠ 获取 {symbol} ({interval}) 数据失败: {e}")
        return None


# ── 信号评估 ────────────────────────────────────────────────────────────────

# 各周期最大持仓 bar 数（与实际策略 hold 参数对齐）
MAX_BARS = {"1h": 10, "4h": 10, "1d": 15}


def _eval_confluence(row: pd.Series, price: pd.DataFrame, tf: str) -> dict:
    """
    Confluence 信号评估（有 TP1/TP2/SL）。
    逐 bar 检查：同一根 bar 内 SL 优先（保守假设）。
    超过 MAX_BARS 未触及 SL/TP 则按收盘价时间止损。
    """
    entry     = float(row["entry_price"])
    tp1       = float(row["tp1"])
    tp2       = float(row["tp2"])
    sl        = float(row["sl"])
    atr       = float(row["atr"])
    direction = str(row["direction"])
    sig_dt    = pd.to_datetime(row["timestamp"])
    max_bars  = MAX_BARS.get(tf, 10)

    future = price[price.index > sig_dt].head(max_bars)
    if future.empty:
        return {"outcome": "未决", "r_mult": _current_r(price, entry, atr, direction), "bars": 0}

    for i, (_, bar) in enumerate(future.iterrows()):
        hi = float(bar["High"])
        lo = float(bar["Low"])

        if direction == "做多":
            if lo <= sl:
                return {"outcome": "止损",   "r_mult": round((sl - entry) / atr, 2), "bars": i + 1}
            if hi >= tp2:
                return {"outcome": "TP2命中", "r_mult": round((tp2 - entry) / atr, 2), "bars": i + 1}
            if hi >= tp1:
                return {"outcome": "TP1命中", "r_mult": round((tp1 - entry) / atr, 2), "bars": i + 1}
        else:  # 做空
            if hi >= sl:
                return {"outcome": "止损",   "r_mult": round((entry - sl) / atr, 2), "bars": i + 1}
            if lo <= tp2:
                return {"outcome": "TP2命中", "r_mult": round((entry - tp2) / atr, 2), "bars": i + 1}
            if lo <= tp1:
                return {"outcome": "TP1命中", "r_mult": round((entry - tp1) / atr, 2), "bars": i + 1}

    # 时间止损：按最后一根 bar 收盘价平仓
    last_close = float(future["Close"].iloc[-1])
    r = _current_r(future, entry, atr, direction)
    return {"outcome": "时间止损", "r_mult": r, "bars": len(future)}


def _eval_rsi2(row: pd.Series, price: pd.DataFrame, tf: str) -> dict:
    """
    RSI2 信号评估（只有 SL，无固定 TP）。
    超过 MAX_BARS 未触及 SL 则按收盘价时间止损。
    """
    entry    = float(row["entry_price"])
    sl       = float(row["sl"])
    atr      = float(row["atr"])
    sig_dt   = pd.to_datetime(row["timestamp"])
    max_bars = MAX_BARS.get(tf, 15)

    future = price[price.index > sig_dt].head(max_bars)
    if future.empty:
        return {"outcome": "未决", "r_mult": _current_r(price, entry, atr, "做多"), "bars": 0}

    for i, (_, bar) in enumerate(future.iterrows()):
        if float(bar["Low"]) <= sl:
            return {"outcome": "止损", "r_mult": round((sl - entry) / atr, 2), "bars": i + 1}

    # 时间止损：按最后一根 bar 收盘价平仓
    r = _current_r(future, entry, atr, "做多")
    return {"outcome": "时间止损", "r_mult": r, "bars": len(future)}


def _current_r(price: pd.DataFrame, entry: float, atr: float, direction: str) -> float | None:
    """当前浮盈/浮亏换算为 R 倍数。"""
    if price.empty or atr <= 0:
        return None
    last = float(price["Close"].iloc[-1])
    if direction == "做多":
        return round((last - entry) / atr, 2)
    else:
        return round((entry - last) / atr, 2)


# ── 手动补录 ────────────────────────────────────────────────────────────────

def add_signal_manually():
    """交互式补录一条历史信号到 signal_log.csv。"""
    print("\n── 手动补录信号 ──")
    print("（时间格式：YYYY-MM-DD HH:MM，价格输入 0 表示不适用）\n")

    row = {}
    row["timestamp"]    = input("信号时间 (如 2026-06-21 20:03): ").strip()
    row["bar_date"]     = input("触发 bar 日期 (如 2026-06-21, 空=同上): ").strip() or row["timestamp"][:10]
    row["symbol"]       = input("标的 (如 STX): ").strip().upper()
    row["tf"]           = input("周期 (1h/4h/1d): ").strip()
    row["strategy"]     = input("策略 (Confluence/RSI2): ").strip()
    row["direction"]    = input("方向 (做多/做空, 默认做多): ").strip() or "做多"
    row["entry_price"]  = input("入场价: ").strip()
    row["atr"]          = input("ATR: ").strip()
    row["tp1"]          = input("TP1 (RSI2 输入 0): ").strip() or "0"
    row["tp2"]          = input("TP2 (RSI2 输入 0): ").strip() or "0"
    row["sl"]           = input("SL: ").strip()
    row["market_score"] = input("Regime 评分 (可空): ").strip()
    row["vix"]          = input("VIX 值 (可空): ").strip()
    row["quality"]      = input("信号质量 0-10 (可空): ").strip() or "0"

    SIGNAL_LOG.parent.mkdir(exist_ok=True)
    write_header = not SIGNAL_LOG.exists()
    with open(SIGNAL_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"\n✅ 已追加到 {SIGNAL_LOG}")


# ── 主逻辑 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="信号复盘")
    parser.add_argument("--days",   type=int, default=0,  help="只看最近 N 天（0=全部）")
    parser.add_argument("--symbol", type=str, default="", help="只看某标的")
    parser.add_argument("--tf",     type=str, default="", help="只看某周期 1h/4h/1d")
    parser.add_argument("--add",    action="store_true",  help="手动补录一条历史信号")
    args = parser.parse_args()

    if args.add:
        add_signal_manually()
        return

    if not SIGNAL_LOG.exists():
        print("❌ logs/signal_log.csv 不存在，尚无信号记录。")
        print("   信号会在 alert_engine 发出 Telegram 告警时自动写入。")
        print("   也可用 --add 手动补录历史信号。")
        return

    df = pd.read_csv(SIGNAL_LOG)
    if df.empty:
        print("信号日志为空。")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["tp1"] = pd.to_numeric(df["tp1"], errors="coerce").fillna(0)
    df["tp2"] = pd.to_numeric(df["tp2"], errors="coerce").fillna(0)

    # 过滤
    if args.days > 0:
        cutoff = datetime.now() - timedelta(days=args.days)
        df = df[df["timestamp"] >= cutoff]
    if args.symbol:
        df = df[df["symbol"].str.upper() == args.symbol.upper()]
    if args.tf:
        df = df[df["tf"] == args.tf]

    if df.empty:
        print("过滤后无信号。")
        return

    print(f"\n共 {len(df)} 条信号，正在拉取价格数据...\n")

    # 预算各标的最早信号时间
    earliest_by_sym = df.groupby("symbol")["timestamp"].min().to_dict()
    global_start = (df["timestamp"].min() - timedelta(days=2)).strftime("%Y-%m-%d")

    # 批量下载：一次请求所有标的（避免逐个限速）
    all_symbols = df["symbol"].unique().tolist()
    syms_1h = [s for s in all_symbols if df[df["symbol"] == s]["tf"].isin(["1h", "4h"]).any()]
    syms_1d = [s for s in all_symbols if df[df["symbol"] == s]["tf"].eq("1d").any()]

    price_cache: dict[tuple[str, str], pd.DataFrame | None] = {}

    def _batch_download(symbols: list[str], interval: str, start: str):
        """批量下载多标的，结果拆分存入 price_cache。"""
        if not symbols:
            return
        # 先从本地 CSV 读取
        missing = []
        for sym in symbols:
            local = _load_local_csv(sym, interval)
            if local is not None and not local.empty:
                cutoff = pd.to_datetime(start).tz_localize(None)
                filtered = local[local.index >= cutoff]
                if not filtered.empty:
                    price_cache[(sym, interval)] = filtered
                    continue
            missing.append(sym)

        if not missing:
            return

        # 批量 yfinance（多 ticker 一次请求）
        print(f"  yfinance 批量下载 {len(missing)} 个标的 [{interval}]...")
        try:
            raw = yf.download(missing, start=start, interval=interval,
                              progress=False, auto_adjust=True, group_by="ticker")
            if raw.empty:
                return
            for sym in missing:
                try:
                    if len(missing) == 1:
                        sub = raw.copy()
                    else:
                        sub = raw[sym].copy()
                    if isinstance(sub.columns, pd.MultiIndex):
                        sub.columns = sub.columns.get_level_values(0)
                    sub.index = pd.to_datetime(sub.index).tz_localize(None)
                    sub = sub.dropna(how="all")
                    price_cache[(sym, interval)] = sub if not sub.empty else None
                except Exception:
                    price_cache[(sym, interval)] = None
        except Exception as e:
            print(f"  ⚠ 批量下载失败: {e}")

    _batch_download(syms_1h, "1h", global_start)
    _batch_download(syms_1d, "1d", global_start)

    def get_price(symbol: str, tf: str, earliest_dt: datetime) -> pd.DataFrame | None:
        interval = "1h" if tf in ("1h", "4h") else "1d"
        return price_cache.get((symbol, interval))

    results = []
    for _, row in df.iterrows():
        sym   = row["symbol"]
        tf    = row["tf"]
        strat = str(row.get("strategy", "")).lower()

        price = get_price(sym, tf, earliest_by_sym[sym])

        if price is None:
            ev = {"outcome": "数据失败", "r_mult": None, "bars": 0}
        elif "confluence" in strat or float(row.get("tp1", 0) or 0) != 0:
            ev = _eval_confluence(row, price, tf)
        else:
            ev = _eval_rsi2(row, price, tf)

        results.append({**row.to_dict(), **ev})

    rdf = pd.DataFrame(results)

    # ── 明细表 ──────────────────────────────────────────────────────────────
    OUTCOME_ICON = {
        "TP2命中": "✅✅",
        "TP1命中": "✅ ",
        "止损":    "❌ ",
        "时间止损": "⏱ ",
        "未决":    "⏳ ",
        "数据失败": "⚠  ",
    }

    print("=" * 90)
    print(f"{'时间':16} {'标的':6} {'TF':4} {'策略':12} {'方向':4} "
          f"{'入场':8} {'SL':8} {'TP1':8} {'结果':8} {'R值':6} {'质量':4}")
    print("-" * 90)

    for _, r in rdf.iterrows():
        ts      = str(r["timestamp"])[:16]
        outcome = str(r["outcome"])
        icon    = OUTCOME_ICON.get(outcome, "? ")
        r_mult  = r["r_mult"]
        r_str   = f"{r_mult:+.1f}R" if r_mult is not None and not (isinstance(r_mult, float) and math.isnan(r_mult)) else "  — "
        tp1_str = f"${float(r['tp1']):.2f}" if float(r.get('tp1', 0) or 0) != 0 else "  N/A"
        print(f"{ts:16} {r['symbol']:6} {r['tf']:4} {r['strategy']:12} "
              f"{r.get('direction','做多'):4} "
              f"${float(r['entry_price']):7.2f} "
              f"${float(r['sl']):7.2f} "
              f"{tp1_str:8} "
              f"{icon}{outcome:5} "
              f"{r_str:6}  "
              f"{int(r.get('quality', 0))}/10")

    print("=" * 90)

    # ── 汇总统计 ─────────────────────────────────────────────────────────────
    print(f"\n📊 汇总统计（共 {len(rdf)} 条）\n")

    decided = rdf[rdf["outcome"].isin(["TP1命中", "TP2命中", "止损", "时间止损"])]
    pending = rdf[rdf["outcome"] == "未决"]

    tp2_n  = len(rdf[rdf["outcome"] == "TP2命中"])
    tp1_n  = len(rdf[rdf["outcome"] == "TP1命中"])
    sl_n   = len(rdf[rdf["outcome"] == "止损"])
    tsl_n  = len(rdf[rdf["outcome"] == "时间止损"])
    pen_n  = len(pending)

    print(f"  TP2命中: {tp2_n}  TP1命中: {tp1_n}  止损: {sl_n}  时间止损: {tsl_n}  未决: {pen_n}")

    if len(decided) > 0:
        win_rate = (tp1_n + tp2_n) / len(decided) * 100
        avg_r    = decided["r_mult"].dropna().mean()
        print(f"  已决胜率: {win_rate:.1f}%  平均 R（已决）: {avg_r:+.2f}R")

    if pen_n > 0:
        pend_r = pending["r_mult"].dropna()
        if len(pend_r) > 0:
            print(f"  未决浮盈均值: {pend_r.mean():+.2f}R  (最新收盘 vs 入场)")

    # 按策略分组
    print()
    for strat in rdf["strategy"].unique():
        sub = rdf[rdf["strategy"] == strat]
        dec = sub[sub["outcome"].isin(["TP1命中", "TP2命中", "止损", "时间止损"])]
        pen = sub[sub["outcome"] == "未决"]
        line = f"  [{strat}] 共{len(sub)}条"
        if len(dec) > 0:
            wins = len(dec[dec["outcome"].isin(["TP1命中", "TP2命中"])])
            wr   = wins / len(dec) * 100
            ar   = dec["r_mult"].dropna().mean()
            line += f"  已决{len(dec)}条 胜率{wr:.0f}% 均R{ar:+.2f}R"
        if len(pen) > 0:
            pr = pen["r_mult"].dropna()
            if len(pr) > 0:
                line += f"  未决{len(pen)}条(浮盈{pr.mean():+.2f}R)"
        print(line)

    print()


if __name__ == "__main__":
    main()

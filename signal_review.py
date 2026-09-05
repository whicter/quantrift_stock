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
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from meta_label import train as train_meta_model
from review_core import _strategy_key as review_family, evaluate, hold_bars

SIGNAL_LOG = Path("logs/signal_log.csv")
LOG_FIELDS = [
    "timestamp", "bar_date", "symbol", "tf", "strategy", "direction",
    "entry_price", "atr", "tp1", "tp2", "sl",
    "market_score", "vix", "quality", "signal_id", "source", "is_shadow", "source_strategy",
    "params_json", "sector_aligned", "screener_rank", "market_regime",
]


# ── 价格数据获取 ────────────────────────────────────────────────────────────

DATA_DIR = Path("data")

def _load_local_csv(symbol: str, interval: str) -> pd.DataFrame | None:
    """尝试从本地 data/ 目录读取已有 CSV（IB 抓取的历史数据）。

    4h must map to the 4h file: replaying a 4h signal against 1h bars would
    count each holding bar as one hour, cutting the effective holding window
    to a quarter of what the strategy allows.
    """
    tf_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
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
        # A stale local IB snapshot cannot resolve a newer signal.  Returning it
        # would silently mark the signal as pending and suppress the network
        # fallback, which is worse than an explicit download failure.
        latest_expected = pd.Timestamp.now().tz_localize(None).normalize() - pd.Timedelta(days=3)
        if df.index.max() < latest_expected:
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
    # yfinance has no native 4h interval, so 4h is resampled from 1h the same
    # way alert_engine builds its live 4h bars.
    time.sleep(2)
    download_interval = "1h" if interval == "4h" else interval
    try:
        df = yf.download(symbol, start=start, interval=download_interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        if interval == "4h":
            df = _resample_4h(df)
        return df
    except Exception as e:
        print(f"  ⚠ 获取 {symbol} ({interval}) 数据失败: {e}")
        return None


def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h bars into 4h using alert_engine's live convention."""
    return (df_1h.resample("4h", label="right", closed="right")
            .agg({"Open": "first", "High": "max", "Low": "min",
                  "Close": "last", "Volume": "sum"})
            .dropna(subset=["Close"]))


# ── 信号评估 ────────────────────────────────────────────────────────────────
# 持仓上限不再用统一常量：每条信号按自身 params_json 里的 max_hold_bars 回放，
# 缺失时回退到该策略的回测默认值（见 review_core.hold_bars）。旧的
# MAX_BARS = {1h:10, 4h:10, 1d:15} 会把 RSI2（默认 48 根）提前 5 倍平仓，
# 是复盘胜率远低于回测胜率的直接原因。


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
    row["source"]       = "live"

    SIGNAL_LOG.parent.mkdir(exist_ok=True)
    write_header = not SIGNAL_LOG.exists()
    with open(SIGNAL_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"\n✅ 已追加到 {SIGNAL_LOG}")


def _quality_report(rdf: pd.DataFrame) -> None:
    """Show whether the published quality score predicts realized R."""
    decided = rdf[pd.to_numeric(rdf["r_mult"], errors="coerce").notna()].copy()
    if decided.empty:
        return
    decided["quality"] = pd.to_numeric(decided["quality"], errors="coerce").fillna(0)
    print("\n📏 Quality 校准")
    for label, low, high in (("0-4", 0, 4), ("5-7", 5, 7), ("8-10", 8, 10)):
        group = decided[decided["quality"].between(low, high)]
        if not group.empty:
            print(f"  {label}: N={len(group)} 胜率={(group['r_mult'] > 0).mean() * 100:.1f}% 平均R={group['r_mult'].mean():+.2f}")


MIN_MONITOR_SAMPLES = 5
EXPECTATIONS_PATH = Path("strategy_expectations.json")


def _load_expectations() -> dict:
    """Historical replay expectations; absent file degrades to the 0R baseline."""
    if not EXPECTATIONS_PATH.exists():
        return {}
    try:
        return json.loads(EXPECTATIONS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _same_period_baseline(days: int) -> dict:
    """同期回测基准：同一策略/周期在**同一段行情**里回测能拿到多少 R。

    2026-09-03 发现的方法论缺陷：`expectations.json` 里的 mean_r 是十年样本的
    长期均值（Confluence +0.285 / RSI2 +0.388），拿它当基准去判定最近 90 天的
    实盘，等于把"这一季行情本来就不好"误读成"策略衰减"。实测同期回测（只算
    真正开仓的行）最近 90 天 Confluence -0.163、RSI2 -0.060——也就是说回测
    自己在这段行情里同样是亏的，而实盘 Confluence +0.289 其实是**跑赢**同期
    回测的。用长期均值当基准，衰减监控会在每一段低于平均的行情里批量误报红灯，
    进而触发自动降级——正好把策略在最不该关的时候关掉。

    因此基准优先取同期回测；同期样本不足（<10 笔）才退回长期均值。
    """
    path = Path("logs/backfill_paper_equity.csv")
    if not path.exists():
        return {}
    try:
        b = pd.read_csv(path)
        b["event_time"] = pd.to_datetime(b["event_time"], errors="coerce")
        # 只算真正开过仓的：skip_max_open_positions / skip_duplicate_active
        # 这些行也带 r_mult，但它们代表"没开成的仓"，混进来会稀释基准。
        b = b[~b["decision"].astype(str).str.startswith("skip")]
        b = b[b["event_time"] >= b["event_time"].max() - pd.Timedelta(days=days)]
        b["r_mult"] = pd.to_numeric(b["r_mult"], errors="coerce")
        b = b[b["r_mult"].notna()]
    except Exception:
        return {}
    out = {}
    for (strategy, tf), g in b.groupby(["strategy", "tf"]):
        if len(g) >= 10:
            out[(str(strategy), str(tf))] = float(g["r_mult"].mean())
    return out


def _expected_r(expectations: dict, strategy: str, symbol: str, tf: str,
                same_period: dict | None = None) -> tuple[float, str]:
    """Baseline mean R for one combination, plus where it came from.

    Shadow variants fall back to their strategy family (RSI2_IBS_shadow ->
    RSI2), since they differ only in exit or filter handling and have no
    expectation rows of their own.
    """
    # 同期回测基准优先（见 _same_period_baseline 的说明）
    if same_period:
        family = strategy[:-7] if strategy.endswith("_shadow") else strategy
        for name in (strategy, family):
            if (name, tf) in same_period:
                return same_period[(name, tf)], "same_period"

    table = expectations.get("expectations", {})
    candidates = [strategy]
    if strategy.endswith("_shadow"):
        family = review_family({"strategy": strategy})
        candidates.append({"rsi2": "RSI2", "mr": "MR",
                           "breakout": "Breakout52W"}.get(family, "Confluence"))
    for name in candidates:
        entry = table.get(name, {}).get(symbol, {}).get(tf)
        if entry:
            return float(entry["mean_r"]), "backtest"
    return 0.0, "placeholder"


def _append_with_schema_check(df: pd.DataFrame, path: Path) -> None:
    """追加前校验列结构；不一致则归档旧文件重建。

    2026-08-15 发现：`review_history.csv` 的表头停留在旧的 8 字段 schema（无 tf、
    无 baseline_r/baseline_kind），而后续 544 行是 11 字段——因为原来用
    `header=not path.exists()` 盲目追加，schema 演进时表头从未更新，导致
    `pd.read_csv` 直接解析失败，整个文件对下游不可用。与 screener_results.csv
    是同一类事故（见 LEARNING.md），此处用同样的写入方检查修复。
    """
    if path.exists():
        with open(path) as fh:
            existing_header = fh.readline().strip().split(",")
        if existing_header != list(df.columns):
            archive = path.with_suffix(f".schema-{datetime.now():%Y%m%d}.bak")
            path.rename(archive)
            df.to_csv(path, index=False)
            print(f"⚠️ review_history.csv 列结构不同，已归档为 {archive.name} 并重建")
            return
        df.to_csv(path, mode="a", index=False, header=False)
    else:
        df.to_csv(path, index=False)


def _monitor(rdf: pd.DataFrame) -> None:
    same_period = _same_period_baseline(90)
    """Write rolling live performance history and flag statistical degradation."""
    decided = rdf[pd.to_numeric(rdf["r_mult"], errors="coerce").notna()].copy()
    if decided.empty:
        print("\n🚦 衰减监控：暂无已决信号")
        return
    expectations = _load_expectations()
    path = Path("logs/review_history.csv")
    rows = []
    # Grouped per timeframe as well: the same symbol can behave very differently
    # on 1h vs 1d, and the expectation table is keyed that way.
    for (strategy, symbol, tf), group in decided.groupby(["strategy", "symbol", "tf"]):
        recent = group.sort_values("timestamp").tail(20)
        mean = float(recent["r_mult"].mean())
        sigma = float(recent["r_mult"].std(ddof=0) / max(len(recent) ** 0.5, 1))
        baseline, baseline_kind = _expected_r(expectations, strategy, symbol, tf, same_period)
        # Measuring against this combination's own historical replay answers
        # "is it behaving worse than it ever did", rather than the far weaker
        # "did it lose money recently" that a 0R baseline tests.
        z = (mean - baseline) / sigma if sigma > 0 else 0.0
        # A handful of trades cannot support a degradation verdict; flagging
        # N=1 as "red" is noise that invites acting on nothing.
        if len(recent) < MIN_MONITOR_SAMPLES:
            level = "样本不足"
        else:
            level = "红" if z < -2 else "黄" if z < -1 else "绿"
        rows.append({"timestamp": datetime.now().isoformat(timespec="seconds"), "strategy": strategy,
                     "symbol": symbol, "tf": tf, "n": len(recent), "mean_r": round(mean, 4),
                     "se": round(sigma, 4), "baseline_r": round(baseline, 4),
                     "baseline_kind": baseline_kind, "z_vs_baseline": round(z, 3), "status": level})
    hist = pd.DataFrame(rows)
    path.parent.mkdir(exist_ok=True)
    _append_with_schema_check(hist, path)
    graded = [r for r in rows if r["status"] != "样本不足"]
    pending = [r for r in rows if r["status"] == "样本不足"]
    meta = expectations.get("_meta", {})
    if meta:
        src = f"回测期望表（{meta.get('combinations', '?')} 组合，{meta.get('generated_at', '?')} 生成）"
    else:
        src = "0R 占位（strategy_expectations.json 缺失，运行 build_expectations.py 生成）"
    print(f"\n🚦 衰减监控（最近20笔；基准={src}；N<{MIN_MONITOR_SAMPLES} 不判级）")
    for row in sorted(graded, key=lambda r: r["z_vs_baseline"]):
        print(f"  {row['status']} {row['strategy']} {row['symbol']} {row['tf']}: "
              f"N={row['n']} 均R={row['mean_r']:+.2f} 期望={row['baseline_r']:+.2f}"
              f"{ {'backtest': '', 'same_period': '(同期回测)'}.get(row['baseline_kind'], '(占位)') }"
              f" z={row['z_vs_baseline']:+.2f}")
    if pending:
        names = ", ".join(f"{r['strategy']}/{r['symbol']}/{r['tf']}(N={r['n']})" for r in pending)
        print(f"  样本不足未判级：{names}")


def _telegram_summary(rdf: pd.DataFrame) -> None:
    """A weekly status notification; failures must never affect the ledger."""
    import os
    import requests
    token, chat_id = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        return
    decided = rdf[pd.to_numeric(rdf["r_mult"], errors="coerce").notna()].copy()
    avg_r = decided["r_mult"].mean() if not decided.empty else 0
    lines = [f"📋 周度信号复盘",
             f"信号 {len(rdf)} 条，已决 {len(decided)} 条，均R {avg_r:+.2f}"]

    # Per-strategy breakdown: a single blended average hides which family is
    # actually degrading.
    if not decided.empty:
        lines.append("")
        for strategy, group in decided.groupby("strategy"):
            wins = (group["r_mult"] > 0).mean() * 100
            lines.append(f"· {strategy}: N={len(group)} 胜率{wins:.0f}% 均R{group['r_mult'].mean():+.2f}")

        expectations = _load_expectations()
        same_period = _same_period_baseline(90)
        red = []
        for (strategy, symbol, tf), group in decided.groupby(["strategy", "symbol", "tf"]):
            recent = group.sort_values("timestamp").tail(20)
            if len(recent) < MIN_MONITOR_SAMPLES:
                continue
            mean = float(recent["r_mult"].mean())
            sigma = float(recent["r_mult"].std(ddof=0) / max(len(recent) ** 0.5, 1))
            baseline, _ = _expected_r(expectations, strategy, symbol, tf, same_period)
            if sigma > 0 and (mean - baseline) / sigma < -2:
                red.append(f"{strategy}/{symbol}/{tf}(均R{mean:+.2f} vs 期望{baseline:+.2f}, N={len(recent)})")
        if red:
            lines.append("")
            lines.append(f"🔴 红灯 {len(red)} 项：" + ", ".join(red))

    lines.append("")
    meta = _load_expectations().get("_meta", {})
    sp = _same_period_baseline(90)
    baseline_note = (f"基准=同期回测（近90天，{len(sp)} 个策略/周期）" if sp
                     else f"基准=回测期望表（{meta['combinations']} 组合）" if meta
                     else "基准=0R 占位（期望表缺失）")
    lines.append(f"{baseline_note}；N<{MIN_MONITOR_SAMPLES} 不判级")
    lines.append("详情：logs/review_history.csv")
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": "\n".join(lines)}, timeout=10)
    except requests.RequestException:
        pass


# ── 主逻辑 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="信号复盘")
    parser.add_argument("--days",   type=int, default=0,  help="只看最近 N 天（0=全部）")
    parser.add_argument("--symbol", type=str, default="", help="只看某标的")
    parser.add_argument("--tf",     type=str, default="", help="只看某周期 1h/4h/1d")
    parser.add_argument("--add",    action="store_true",  help="手动补录一条历史信号")
    parser.add_argument("--monitor", action="store_true", help="写入最近20笔策略衰减监控")
    parser.add_argument("--train-meta", action="store_true", help="样本>=150时训练逻辑回归元标签模型")
    parser.add_argument("--telegram", action="store_true", help="发送复盘摘要到 Telegram")
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

    # Entries written before source separation were all live alert records.
    if "source" not in df:
        df["source"] = "live"
    else:
        df["source"] = df["source"].fillna("live").replace("", "live")

    # 重播不计入复盘。引擎在同一个交易想法尚未出场时会每根 bar 重新播报一次，
    # 而回测里一个想法只开一次仓。把重播当成独立交易统计，等于把同一波行情里
    # 越来越晚的入场点全部计入，均 R 被系统性拉低——实测 Confluence 含重播
    # +0.224R、去重后 +0.289R，而回测期望 +0.285R。所谓的「Confluence 衰减」
    # 完全是这个口径造出来的假象。重播仍然写进 signal_log（账本记全），只是
    # 不参与绩效统计。
    if "is_repeat" in df:
        df = df[pd.to_numeric(df["is_repeat"], errors="coerce").fillna(0) != 1]

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
    syms_1h = [s for s in all_symbols if df[df["symbol"] == s]["tf"].eq("1h").any()]
    syms_4h = [s for s in all_symbols if df[df["symbol"] == s]["tf"].eq("4h").any()]
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

        # 批量 yfinance（多 ticker 一次请求）；4h 无原生 interval，拉 1h 再聚合
        print(f"  yfinance 批量下载 {len(missing)} 个标的 [{interval}]...")
        download_interval = "1h" if interval == "4h" else interval
        try:
            raw = yf.download(missing, start=start, interval=download_interval,
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
                    if interval == "4h" and not sub.empty:
                        sub = _resample_4h(sub)
                    price_cache[(sym, interval)] = sub if not sub.empty else None
                except Exception:
                    price_cache[(sym, interval)] = None
        except Exception as e:
            print(f"  ⚠ 批量下载失败: {e}")

    _batch_download(syms_1h, "1h", global_start)
    _batch_download(syms_4h, "4h", global_start)
    _batch_download(syms_1d, "1d", global_start)

    def get_price(symbol: str, tf: str, earliest_dt: datetime) -> pd.DataFrame | None:
        # Each timeframe replays against its own bars; a 4h signal measured in
        # 1h bars would be force-closed four times too early.
        interval = tf if tf in ("1h", "4h", "1d") else "1d"
        return price_cache.get((symbol, interval))

    results = []
    for _, row in df.iterrows():
        sym   = row["symbol"]
        tf    = row["tf"]

        price = get_price(sym, tf, earliest_by_sym[sym])

        if price is None:
            ev = {"outcome": "数据失败", "r_mult": None, "bars": 0}
        else:
            # Strategy routing and the holding cap both come from the signal
            # itself (strategy name + params_json snapshot).
            ev = evaluate(row, price)

        results.append({**row.to_dict(), **ev, "hold_cap": hold_bars(row, tf)})

    rdf = pd.DataFrame(results)

    # ── 明细表 ──────────────────────────────────────────────────────────────
    OUTCOME_ICON = {
        "TP2命中": "✅✅",
        "TP1命中": "✅ ",
        "SSL追踪出场": "✅ ",
        "ATR追踪出场": "✅ ",
        "RSI出场": "✅ ",
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

    # 「已决」= 复盘算得出 R 的，而不是一份写死的出场名单。旧写法只认
    # TP1/TP2/止损/时间止损，把 ATR追踪出场 / RSI出场 / SSL追踪出场 全漏了——
    # 而 ATR 追踪正是 RSI2 与 MR 的**主要**出场方式（RSI2 根本没有固定 TP）。
    # 后果：RSI2 的 84 笔 ATR 出场从未进入任何汇总，只剩 47 笔"跑满时间没被
    # 止损"的幸存者，于是显示 85% 胜率 / +1.25R。典型的生存者偏差。
    # 衰减监控用的一直是 r_mult 口径，所以只有这份给人看的汇总在骗人。
    _r = pd.to_numeric(rdf["r_mult"], errors="coerce")
    decided = rdf[_r.notna()]
    pending = rdf[rdf["outcome"] == "未决"]

    tp2_n  = len(rdf[rdf["outcome"] == "TP2命中"])
    tp1_n  = len(rdf[rdf["outcome"] == "TP1命中"])
    sl_n   = len(rdf[rdf["outcome"] == "止损"])
    tsl_n  = len(rdf[rdf["outcome"] == "时间止损"])
    pen_n  = len(pending)

    other = {k: int(v) for k, v in rdf["outcome"].value_counts().items()
             if k not in ("TP2命中", "TP1命中", "止损", "时间止损", "未决")}
    print(f"  TP2命中: {tp2_n}  TP1命中: {tp1_n}  止损: {sl_n}  时间止损: {tsl_n}  未决: {pen_n}"
          + ("  " + "  ".join(f"{k}: {v}" for k, v in other.items()) if other else ""))

    if len(decided) > 0:
        win_rate = (pd.to_numeric(decided["r_mult"], errors="coerce") > 0).mean() * 100
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
        dec = sub[pd.to_numeric(sub["r_mult"], errors="coerce").notna()]
        pen = sub[sub["outcome"] == "未决"]
        line = f"  [{strat}] 共{len(sub)}条"
        if len(dec) > 0:
            wins = int((pd.to_numeric(dec["r_mult"], errors="coerce") > 0).sum())
            wr   = wins / len(dec) * 100
            ar   = dec["r_mult"].dropna().mean()
            line += f"  已决{len(dec)}条 胜率{wr:.0f}% 均R{ar:+.2f}R"
        if len(pen) > 0:
            pr = pen["r_mult"].dropna()
            if len(pr) > 0:
                line += f"  未决{len(pen)}条(浮盈{pr.mean():+.2f}R)"
        print(line)

    _quality_report(rdf)
    if args.monitor:
        _monitor(rdf)
    if args.train_meta:
        live = rdf[rdf["source"] == "live"]
        result = train_meta_model(live)
        print(f"\n🤖 Meta-label（仅 live 样本）: {result.get('reason') or '模型已训练'}")
    if args.telegram:
        _telegram_summary(rdf)

    print()


if __name__ == "__main__":
    main()

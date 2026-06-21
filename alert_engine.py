"""
alert_engine.py — 股票信号监控引擎（仅告警，不下单）

功能：
  - 每小时整点检查所有标的 × 所有周期的信号
  - 满足入场条件时发 Telegram 告警
  - 连接 IB Gateway 拉取实时 bar 数据（clientId=2，不与期货引擎冲突）

用法：
  python alert_engine.py --port 4002
  python alert_engine.py --port 4001   # 实盘

**绝对不下单，不调用任何 placeOrder / reqOrder 接口**
"""

import argparse
import os
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

try:
    from ib_insync import IB, Stock, util
except ImportError:
    sys.exit("请安装 ib_insync：pip install ib_insync")

from indicators import compute_signals
from param_loader import get_params

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

TG_TOKEN   = os.environ.get("TG_TOKEN",   cfg["telegram"].get("token", ""))
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", cfg["telegram"].get("chat_id", ""))

ALL_SYMBOLS = (
    cfg["symbols"]["mag7"]
    + cfg["symbols"]["semis"]
    + cfg["symbols"]["etfs"]
)
TIMEFRAMES = ["1h", "4h", "1d"]

# IB bar size 映射
IB_BAR_SIZE = {"1h": "1 hour", "4h": "4 hours", "1d": "1 day"}
IB_DURATION = {"1h": "30 D",   "4h": "60 D",    "1d": "3 Y"}


# ── Telegram ────────────────────────────────────────────────────────────

def tg_alert(msg: str):
    """非阻塞线程发送 Telegram，静默失败。"""
    if not TG_TOKEN or not TG_CHAT_ID:
        return

    def _send():
        try:
            import urllib.request, urllib.parse
            url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": msg}).encode()
            urllib.request.urlopen(url, data=data, timeout=10)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


# ── IB 数据获取 ──────────────────────────────────────────────────────────

def fetch_bars(ib: IB, symbol: str, tf: str) -> pd.DataFrame | None:
    """拉取历史 bar，返回标准 OHLCV DataFrame。"""
    contract = Stock(symbol, "SMART", "USD")
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=IB_DURATION[tf],
        barSizeSetting=IB_BAR_SIZE[tf],
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        return None
    df = util.df(bars)[["date", "open", "high", "low", "close", "volume"]].copy()
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    return df


# ── 信号检查 ─────────────────────────────────────────────────────────────

def check_signal(df_raw: pd.DataFrame, params: dict) -> dict | None:
    """
    计算指标，检查最后一根 bar 是否满足入场条件。
    返回信号字典，或 None（无信号）。
    """
    if len(df_raw) < 50:
        return None

    df = compute_signals(df_raw, params)
    last = df.iloc[-1]

    close      = float(last["Close"])
    bull_score = int(last["bullScore"])
    bear_score = int(last["bearScore"])
    adx        = float(last["adx"])
    is_choppy  = bool(last["isChoppy"])
    is_high_vol= bool(last["isHighVol"])
    atr_val    = float(last["atrVal"])
    ut_ts      = float(last["utTS"])

    min_score       = int(params.get("min_score", 5))
    adx_threshold   = float(params.get("adx_threshold", 25.0))
    use_adx         = bool(params.get("use_adx", True))
    use_vol         = bool(params.get("use_vol", True))
    allow_short     = bool(params.get("allow_short", True))
    conflict_thresh = int(params.get("conflict_threshold", 2))
    tp1_mult        = float(params.get("atr_tp1_mult", 1.0))
    tp2_mult        = float(params.get("atr_tp2_mult", 2.0))

    ok_trend = (not use_adx) or (adx >= adx_threshold)
    ok_vol   = (not use_vol)  or is_high_vol

    long_signal  = (bull_score >= min_score
                    and bear_score <= conflict_thresh
                    and ok_trend and ok_vol
                    and not is_choppy)
    short_signal = (allow_short
                    and bear_score >= min_score
                    and bull_score <= conflict_thresh
                    and ok_trend and ok_vol
                    and not is_choppy)

    if long_signal:
        direction = "做多"
        tp1 = close + tp1_mult * atr_val
        tp2 = close + tp2_mult * atr_val
        sl  = ut_ts
    elif short_signal:
        direction = "做空"
        tp1 = close - tp1_mult * atr_val
        tp2 = close - tp2_mult * atr_val
        sl  = ut_ts
    else:
        return None

    return {
        "direction":  direction,
        "close":      close,
        "atr":        atr_val,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "adx":        adx,
        "tp1":        tp1,
        "tp2":        tp2,
        "sl":         sl,
    }


def build_alert_msg(symbol: str, tf: str, sig: dict) -> str:
    d = sig["direction"]
    emoji = "📈" if d == "做多" else "📉"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"{emoji} {symbol} {tf} {d}信号\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  Bull: {sig['bull_score']}/6  Bear: {sig['bear_score']}/6  ADX: {sig['adx']:.1f}\n"
        f"  TP1: ${sig['tp1']:.2f}  TP2: ${sig['tp2']:.2f}\n"
        f"  SL(utTS): ${sig['sl']:.2f}\n"
        f"  时间: {ts} ET"
    )


# ── 主循环 ───────────────────────────────────────────────────────────────

def run_scan(ib: IB):
    """扫描所有标的 × 所有周期，发告警。"""
    print(f"\n[{datetime.now().strftime('%H:%M')}] 开始扫描 {len(ALL_SYMBOLS)} 个标的...")
    found = 0

    for symbol in ALL_SYMBOLS:
        for tf in TIMEFRAMES:
            params = get_params(symbol, tf)
            df_raw = fetch_bars(ib, symbol, tf)
            if df_raw is None:
                print(f"  {symbol} {tf}: 无数据")
                continue

            sig = check_signal(df_raw, params)
            if sig:
                msg = build_alert_msg(symbol, tf, sig)
                print(f"\n  ⚡ 信号：{symbol} {tf} {sig['direction']}")
                print(msg)
                tg_alert(msg)
                found += 1
            else:
                score = "?"
                try:
                    df = compute_signals(df_raw, params)
                    score = f"bull={int(df.iloc[-1]['bullScore'])} bear={int(df.iloc[-1]['bearScore'])}"
                except Exception:
                    pass
                print(f"  {symbol} {tf}: 无信号 ({score})")

    print(f"\n扫描完成，发现 {found} 个信号")
    if found == 0:
        print("  (无信号)")


def wait_until_next_hour():
    """等到下一个整点。"""
    now = datetime.now()
    seconds_to_next = 3600 - (now.minute * 60 + now.second)
    print(f"\n下次扫描：{seconds_to_next // 60}分{seconds_to_next % 60}秒后")
    time.sleep(seconds_to_next)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--once", action="store_true", help="只扫描一次后退出")
    args = parser.parse_args()

    ib = IB()
    host = cfg["ib"]["host"]
    cid  = cfg["ib"]["client_id"]

    print(f"连接 IB Gateway {host}:{args.port} clientId={cid} ...")
    ib.connect(host, args.port, clientId=cid)
    print("✅ 已连接")
    tg_alert(f"✅ quantrift_stock 告警引擎已连接（port={args.port}）")

    try:
        if args.once:
            run_scan(ib)
        else:
            while True:
                run_scan(ib)
                wait_until_next_hour()
    except KeyboardInterrupt:
        print("\n⛔ 用户中断")
    finally:
        ib.disconnect()
        print("已断开 IB 连接")


if __name__ == "__main__":
    main()

"""
alert_engine.py — 股票信号监控引擎（仅告警，不下单）

功能：
  - 每小时整点检查所有标的 × 所有周期的信号
  - 满足入场条件时发 Telegram 告警
  - 连接 IB Gateway 拉取实时 bar 数据（clientId=2，不与期货引擎冲突）
  - 支持 ConfluenceStrategy 和 RSI2 v2 双策略路由

用法：
  python alert_engine.py --port 4002
  python alert_engine.py --port 4001   # 实盘

**绝对不下单，不调用任何 placeOrder / reqOrder 接口**
"""

import argparse
import math
import os
import sys

# 加载 .env（脚本自持，无需 pm2 注入环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import time
import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

try:
    from ib_insync import IB, Stock, util
except ImportError:
    sys.exit("请安装 ib_insync：pip install ib_insync")

from indicators import compute_signals, _sma, _atr
from param_loader import get_params
from data_providers import get_provider

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

TG_TOKEN   = os.environ.get("TG_TOKEN",   cfg["telegram"].get("token", ""))
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", cfg["telegram"].get("chat_id", ""))

ALL_SYMBOLS = (
    cfg["symbols"].get("momentum",   [])
    + cfg["symbols"].get("high_vol", [])
    + cfg["symbols"].get("storage",  [])
    + cfg["symbols"].get("mega_cap", [])
    + cfg["symbols"].get("watch",    [])
    + cfg["symbols"].get("pending",  [])
    + cfg["symbols"].get("sector_etf", [])
    + cfg["symbols"].get("broad_etf",  [])
)
TIMEFRAMES = ["1h", "4h", "1d"]

# IB bar size 映射
IB_BAR_SIZE = {"1h": "1 hour", "4h": "4 hours", "1d": "1 day"}
IB_DURATION = {"1h": "30 D",   "4h": "60 D",    "1d": "3 Y"}

# ── 策略路由 ──────────────────────────────────────────────────────────────
# 值: "confluence" | "rsi2"
# 未列出的 (symbol, tf) 默认使用 "confluence"
STRATEGY_MAP: dict[tuple[str, str], str] = {
    # ConfluenceStrategy 主力池
    ("MU",   "1h"): "confluence",
    ("MU",   "4h"): "confluence",
    ("MRVL", "1h"): "confluence",
    ("MRVL", "4h"): "confluence",
    ("NVDA", "4h"): "confluence",
    ("SNDK", "1h"): "confluence",
    ("STX",  "1h"): "confluence",
    ("STX",  "4h"): "confluence",
    ("STX",  "1d"): "confluence",
    ("TSLA", "1d"): "confluence",
    # RSI2 v2 主力池
    ("NVDA", "1d"): "rsi2",
    ("MRVL", "1d"): "rsi2",
    ("MU",   "1d"): "rsi2",
    ("MSFT", "1d"): "rsi2",
    ("MSFT", "4h"): "rsi2",
    ("GOOGL","1h"): "rsi2",
    ("GOOGL","4h"): "rsi2",
    ("GOOGL","1d"): "rsi2",
    ("META", "1h"): "rsi2",
    ("META", "1d"): "rsi2",
    ("SOXX", "1h"): "rsi2",
    ("SOXX", "4h"): "rsi2",
    ("SOXX", "1d"): "rsi2",
    ("SMH",  "4h"): "rsi2",
    ("SMH",  "1d"): "rsi2",
    ("QQQ",  "1d"): "rsi2",
    ("SPY",  "4h"): "rsi2",
    ("SPY",  "1d"): "rsi2",
    ("AAPL", "1d"): "rsi2",
}

# RSI2 最优参数（来自 LEARNING.md 网格优化结果）
# use_rs_filter=False → 行业/宽基 ETF 不做 RS vs QQQ 过滤
RSI2_PARAMS: dict[tuple[str, str], dict] = {
    ("SOXX", "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 3.0, "min_market_score": 1, "use_rs_filter": False},
    ("SOXX", "1h"): {"rsi2_entry": 5,  "atr_trail_mult": 3.0, "min_market_score": 3, "use_rs_filter": False},
    ("SOXX", "4h"): {"rsi2_entry": 5,  "atr_trail_mult": 2.0, "min_market_score": 1, "use_rs_filter": False, "use_pullback_filter": True},
    ("SMH",  "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 2.5, "min_market_score": 2, "use_rs_filter": False},
    ("SMH",  "4h"): {"rsi2_entry": 5,  "atr_trail_mult": 2.5, "min_market_score": 2, "use_rs_filter": False, "use_pullback_filter": True},
    ("GOOGL","1h"): {"rsi2_entry": 5,  "atr_trail_mult": 2.5, "min_market_score": 1},
    ("GOOGL","4h"): {"rsi2_entry": 5,  "atr_trail_mult": 3.0, "min_market_score": 3},
    ("GOOGL","1d"): {"rsi2_entry": 15, "atr_trail_mult": 2.0, "min_market_score": 2, "use_vol_score": True},
    ("META", "1h"): {"rsi2_entry": 5,  "atr_trail_mult": 2.0, "min_market_score": 3, "use_pullback_filter": True},
    ("META", "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 2.5, "min_market_score": 2, "use_vol_score": True},
    ("MSFT", "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 2.5, "min_market_score": 1, "use_vol_score": True, "use_vix_spike": True},
    ("MSFT", "4h"): {"rsi2_entry": 15, "atr_trail_mult": 2.0, "min_market_score": 1},
    ("NVDA", "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 2.0, "min_market_score": 1, "use_vix_spike": True},
    ("MU",   "1d"): {"rsi2_entry": 5,  "atr_trail_mult": 3.0, "min_market_score": 3, "use_vol_score": True, "use_vix_spike": True},
    ("MRVL", "1d"): {"rsi2_entry": 15, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("QQQ",  "1d"): {"rsi2_entry": 10, "atr_trail_mult": 3.0, "min_market_score": 1, "use_rs_filter": False},
    ("SPY",  "1d"): {"rsi2_entry": 15, "atr_trail_mult": 3.0, "min_market_score": 1, "use_rs_filter": False},
    ("SPY",  "4h"): {"rsi2_entry": 15, "atr_trail_mult": 2.5, "min_market_score": 1, "use_rs_filter": False},
    ("AAPL", "1d"): {"rsi2_entry": 15, "atr_trail_mult": 3.0, "min_market_score": 2},
}

BENCHMARK_SYMBOLS  = {"QQQ", "SPY"}
SECTOR_ETF_SYMBOLS = {"SOXX", "SMH"}


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


# ── Confluence 信号检查 ──────────────────────────────────────────────────

def check_confluence_signal(df_raw: pd.DataFrame, params: dict,
                             df_qqq: pd.DataFrame | None = None,
                             vix_value: float | None = None) -> dict | None:
    """
    计算 ConfluenceStrategy 指标，检查最后一根 bar 是否满足入场条件。
    返回信号字典，或 None（无信号）。
    """
    if len(df_raw) < 50:
        return None

    df = compute_signals(df_raw, params, df_qqq)
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
    use_regime      = bool(params.get("use_regime_filter", False))
    min_mkt_score   = int(params.get("min_market_score", 2))

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

    # Market Regime Score（始终计算，用于告警展示；use_regime=True 时才过滤）
    market_score = float(last.get("market_score", 4))
    if math.isnan(market_score):
        market_score = 4.0
    if vix_value is not None and not math.isnan(vix_value) and vix_value > 20:
        market_score -= 1.0

    if use_regime and long_signal:
        if market_score < min_mkt_score:
            long_signal = False

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

    # Confluence 信号质量评分（0-10）
    active_score  = bull_score if direction == "做多" else bear_score
    signal_pts    = active_score / 6.0 * 5.0
    adx_pts       = min(2.5, max(0.0, (adx / adx_threshold - 1.0) * 2.5)) if adx_threshold > 0 else 0.0
    regime_pts    = min(2.5, max(0.0, market_score / 4.0 * 2.5))
    quality       = round(min(10, max(0, signal_pts + adx_pts + regime_pts)))

    return {
        "strategy":     "Confluence",
        "direction":    direction,
        "close":        close,
        "atr":          atr_val,
        "bull_score":   bull_score,
        "bear_score":   bear_score,
        "adx":          adx,
        "tp1":          tp1,
        "tp2":          tp2,
        "sl":           sl,
        "market_score": market_score,
        "vix":          vix_value,
        "quality":      quality,
    }


# ── RSI2 v2 信号检查 ──────────────────────────────────────────────────────

def _rsi2_series(close: pd.Series) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(2).mean()
    loss  = (-delta.clip(upper=0)).rolling(2).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


def check_rsi2_signal(df_raw: pd.DataFrame, symbol: str, tf: str,
                      df_qqq: pd.DataFrame | None = None,
                      vix_value: float | None = None) -> dict | None:
    """
    RSI2 v2 信号检查（只做多）。
    入场条件：close > SMA200 + RSI2 < entry + Market Regime Score + RS 过滤
    """
    if len(df_raw) < 210:
        return None

    close = df_raw["Close"]
    high  = df_raw["High"]
    low   = df_raw["Low"]

    p = RSI2_PARAMS.get((symbol, tf), {})
    entry_thresh   = float(p.get("rsi2_entry",        10.0))
    min_mkt_score  = int(p.get("min_market_score",    2))
    use_rs_filter  = bool(p.get("use_rs_filter",      True))
    use_pullback   = bool(p.get("use_pullback_filter", False))
    use_vol_score  = bool(p.get("use_vol_score",      False))
    use_vix_spike  = bool(p.get("use_vix_spike",      False))
    atr_trail_mult = float(p.get("atr_trail_mult",    2.5))

    sma200  = _sma(close, 200)
    sma100  = _sma(close, 100)
    sma20   = _sma(close, 20)
    rsi2    = _rsi2_series(close)
    atr_val = _atr(high, low, close, 14)

    volume = df_raw["Volume"].replace(0, np.nan) if "Volume" in df_raw.columns else None

    last_close  = float(close.iloc[-1])
    last_rsi2   = float(rsi2.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])
    last_sma100 = float(sma100.iloc[-1])
    last_sma20  = float(sma20.iloc[-1])
    last_atr    = float(atr_val.iloc[-1])

    if any(math.isnan(v) for v in [last_sma200, last_rsi2, last_atr]):
        return None

    # 1. 大趋势向上
    if last_close <= last_sma200:
        return None

    # 2. Pullback 位置（可选）
    if use_pullback:
        if not (last_close > last_sma100 and last_close < last_sma20):
            return None

    # 3. RSI2 超卖
    if last_rsi2 >= entry_thresh:
        return None

    is_benchmark  = symbol in BENCHMARK_SYMBOLS
    is_sector_etf = symbol in SECTOR_ETF_SYMBOLS
    market_score  = 4.0

    # 4. Market Regime Score
    if df_qqq is not None and not is_benchmark:
        qqq_c   = df_qqq["Close"].reindex(df_raw.index, method="ffill")
        q_s20   = _sma(qqq_c, 20)
        q_s50   = _sma(qqq_c, 50)
        q_s100  = _sma(qqq_c, 100)
        q_s200  = _sma(qqq_c, 200)
        q_ret5  = qqq_c.pct_change(5)

        q = qqq_c.iloc[-1]
        market_score = (
            float(q > q_s100.iloc[-1]) +
            float(q > q_s200.iloc[-1]) +
            float(q_s20.iloc[-1] > q_s50.iloc[-1]) +
            float(q_ret5.iloc[-1] > 0)
        )
        # VIX 分量（有数据时加入，最高分 4→5，阈值含义不变）
        if vix_value is not None and not math.isnan(vix_value):
            market_score -= float(vix_value > 20)
        # 成交量放量加分（Mega-cap / MU 专用）
        if use_vol_score and volume is not None:
            vol_avg = volume.rolling(20).mean()
            vol_surge = float(volume.iloc[-1]) > float(vol_avg.iloc[-1]) * 1.5
            if vol_surge and not math.isnan(float(vol_avg.iloc[-1])):
                market_score += 1.0
        # VIX 急升回落加分（MSFT/NVDA/MU 专用）
        if use_vix_spike and vix_value is not None and not math.isnan(vix_value):
            try:
                from datetime import timedelta
                start_dt = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
                _provider = get_provider()
                vix_hist = _provider.fetch_ohlcv("^VIX", "1d", start=start_dt)
                if vix_hist is not None and len(vix_hist) >= 4:
                    vix_close_hist = vix_hist["Close"]
                    vix_max10 = float(vix_close_hist.rolling(min(10, len(vix_close_hist))).max().iloc[-1])
                    vix_spiked = vix_max10 > 25.0
                    vix_declining = vix_value < float(vix_close_hist.iloc[-4])
                    if vix_spiked and vix_declining:
                        market_score += 1.0
            except Exception:
                pass
        if math.isnan(market_score):
            market_score = 0.0

    if market_score < min_mkt_score:
        return None

    # 5. 相对强度过滤
    if use_rs_filter and df_qqq is not None and not is_benchmark:
        qqq_c = df_qqq["Close"].reindex(df_raw.index, method="ffill")
        if is_sector_etf:
            if last_close <= last_sma100:
                return None
        else:
            rs_20    = float(close.pct_change(20).iloc[-1]) - float(qqq_c.pct_change(20).iloc[-1])
            rs_60    = float(close.pct_change(60).iloc[-1]) - float(qqq_c.pct_change(60).iloc[-1])
            rs_score = 0.4 * rs_20 + 0.6 * rs_60
            if math.isnan(rs_score) or rs_score <= 0:
                return None

    sl = last_close - atr_trail_mult * last_atr

    # RSI2 信号质量评分（0-10）
    rsi2_pts   = max(0.0, 4.0 * (1.0 - last_rsi2 / entry_thresh)) if entry_thresh > 0 else 2.0
    regime_pts = min(4.0, max(0.0, market_score))
    vol_pts    = 1.0 if (use_vol_score and volume is not None
                         and not math.isnan(float(volume.iloc[-1]))
                         and not math.isnan(float(volume.rolling(20).mean().iloc[-1]))
                         and float(volume.iloc[-1]) > float(volume.rolling(20).mean().iloc[-1]) * 1.5) else 0.0
    vix_pts    = 0.0  # vix_spike 在上方已计算并加入 market_score，此处不重复加
    quality    = round(min(10, max(0, rsi2_pts + regime_pts + vol_pts + vix_pts)))

    return {
        "strategy":     "RSI2",
        "direction":    "做多",
        "close":        last_close,
        "atr":          last_atr,
        "rsi2":         last_rsi2,
        "market_score": market_score,
        "sma200":       last_sma200,
        "sl":           sl,
        "vix":          vix_value,
        "quality":      quality,
    }


# ── 告警消息格式 ──────────────────────────────────────────────────────────

def _regime_line(market_score: float, vix: float | None) -> str:
    score_str = f"{market_score:.0f}/4"
    if vix is not None:
        vix_tag = f"  VIX {vix:.1f} ⚠" if vix > 20 else f"  VIX {vix:.1f}"
        return f"  Regime: {score_str}{vix_tag}"
    return f"  Regime: {score_str}"


def build_confluence_alert(symbol: str, tf: str, sig: dict) -> str:
    d = sig["direction"]
    emoji = "📈" if d == "做多" else "📉"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    quality = sig.get("quality", 0)
    return (
        f"{emoji} {symbol} {tf} {d}信号 [Confluence]  ⭐ {quality}/10\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  Bull: {sig['bull_score']}/6  Bear: {sig['bear_score']}/6  ADX: {sig['adx']:.1f}\n"
        f"  TP1: ${sig['tp1']:.2f}  TP2: ${sig['tp2']:.2f}\n"
        f"  SL(utTS): ${sig['sl']:.2f}\n"
        + _regime_line(sig["market_score"], sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )


def build_rsi2_alert(symbol: str, tf: str, sig: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    p = RSI2_PARAMS.get((symbol, tf), {})
    quality = sig.get("quality", 0)
    return (
        f"📊 {symbol} {tf} 做多信号 [RSI2 v2]  ⭐ {quality}/10\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  RSI2: {sig['rsi2']:.1f}  SMA200: ${sig['sma200']:.2f}\n"
        f"  SL(ATR trail ×{p.get('atr_trail_mult', 2.5)}): ${sig['sl']:.2f}\n"
        + _regime_line(sig["market_score"], sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )


# ── 主循环 ───────────────────────────────────────────────────────────────

def run_scan(ib: IB):
    """扫描所有标的 × 所有周期，发告警。"""
    print(f"\n[{datetime.now().strftime('%H:%M')}] 开始扫描 {len(ALL_SYMBOLS)} 个标的...")
    found = 0

    # 每次扫描前拉一次 VIX（数据源由 config.yaml data.provider 决定）
    try:
        _provider = get_provider()
        vix_value = _provider.fetch_vix()
        if vix_value is not None:
            print(f"  VIX: {vix_value:.2f}  ({'高波动 -1分' if vix_value > 20 else '正常'})")
        else:
            print("  VIX: 获取失败，跳过该分量")
    except Exception as e:
        print(f"  VIX: 获取异常 ({e})，跳过该分量")
        vix_value = None

    for tf in TIMEFRAMES:
        # 每个周期拉一次 QQQ（用于 Market Regime Score + RS 过滤）
        df_qqq = None
        needs_qqq = any(
            STRATEGY_MAP.get((sym, tf), "confluence") == "rsi2"
            or cfg["timeframes"][tf].get("use_regime_filter", False)
            for sym in ALL_SYMBOLS
        )
        if needs_qqq:
            df_qqq = fetch_bars(ib, "QQQ", tf)
            if df_qqq is None:
                print(f"  [QQQ {tf}] ⚠ 无法获取 QQQ 数据，Market Regime 过滤将跳过")

        for symbol in ALL_SYMBOLS:
            params  = get_params(symbol, tf)
            df_raw  = fetch_bars(ib, symbol, tf)
            if df_raw is None:
                print(f"  {symbol} {tf}: 无数据")
                continue

            strategy = STRATEGY_MAP.get((symbol, tf), "confluence")

            if strategy == "confluence":
                sig = check_confluence_signal(df_raw, params, df_qqq, vix_value)
                if sig:
                    msg = build_confluence_alert(symbol, tf, sig)
                    print(f"\n  ⚡ 信号：{symbol} {tf} {sig['direction']} [Confluence]")
                    print(msg)
                    tg_alert(msg)
                    found += 1
                else:
                    print(f"  {symbol} {tf}: 无信号 [Confluence]")

            elif strategy == "rsi2":
                sig = check_rsi2_signal(df_raw, symbol, tf, df_qqq, vix_value)
                if sig:
                    msg = build_rsi2_alert(symbol, tf, sig)
                    print(f"\n  ⚡ 信号：{symbol} {tf} 做多 [RSI2 v2]")
                    print(msg)
                    tg_alert(msg)
                    found += 1
                else:
                    p = RSI2_PARAMS.get((symbol, tf), {})
                    print(f"  {symbol} {tf}: 无信号 [RSI2 v2 entry<{p.get('rsi2_entry', 10)}]")

            else:
                print(f"  {symbol} {tf}: 未知策略路由 '{strategy}'")

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
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("ALERT_PORT", 4002)))
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

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
import csv
import json
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
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

try:
    from ib_insync import IB, Stock, util
except ImportError:
    # The live scanner is yfinance/provider based; IB remains an optional type hint.
    IB = Stock = util = None

try:
    import yfinance as yf
except ImportError:
    sys.exit("请安装 yfinance：pip install yfinance")

from indicators import compute_signals, _sma, _atr, _rsi, _adx
from param_loader import get_params
from data_providers import get_provider
from mag7_rotation import run_rotation
from meta_label import suggest as meta_label_suggest
from paper_portfolio import open_position as paper_open_position, risk_warnings as paper_risk_warnings, update as paper_update

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
    + cfg["symbols"].get("watchlist_2026_07", [])
)
TIMEFRAMES = ["1h", "4h", "1d"]


# ── 策略路由 ──────────────────────────────────────────────────────────────
# 值: "confluence" | "rsi2" | "breakout"
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
    # PLTR — RSI2 全周期（Confluence 全周期为负）
    ("PLTR", "1h"): "rsi2",
    ("PLTR", "4h"): "rsi2",
    ("PLTR", "1d"): "rsi2",
    # 52周高点突破 — 仅日线，与 RSI2/Confluence 互补（突破动量 vs 回调入场）
    ("NVDA", "1d:bo"): "breakout",
    ("MU",   "1d:bo"): "breakout",
    ("MSFT", "1d:bo"): "breakout",
    ("PLTR", "1d:bo"): "breakout",
    ("TSLA", "1d:bo"): "breakout",

    # ── 2026-07-25 watchlist 批量回测新增（见 config.yaml watchlist_2026_07 注释）──
    ("AIS", "1d"): "confluence",  # Sharpe 0.64 N=30 WR=70.0%
    ("BB", "4h"): "confluence",  # Sharpe 1.36 N=44 WR=61.4%
    ("DJT", "1h"): "confluence",  # Sharpe 1.31 N=125 WR=66.4%
    ("GME", "1h"): "confluence",  # Sharpe 0.69 N=129 WR=56.6%
    ("IBM", "4h"): "confluence",  # Sharpe 0.76 N=53 WR=67.9%
    ("INTU", "4h"): "confluence",  # Sharpe 0.60 N=34 WR=64.7%
    ("LUNR", "4h"): "confluence",  # Sharpe 1.08 N=50 WR=68.0%
    ("LWLG", "1h"): "confluence",  # Sharpe 0.70 N=133 WR=58.6%
    ("MORN", "4h"): "confluence",  # Sharpe 0.71 N=37 WR=67.6%
    ("MSOS", "1d"): "confluence",  # Sharpe 0.87 N=50 WR=76.0%
    ("PYPL", "1d"): "confluence",  # Sharpe 0.65 N=53 WR=66.0%
    ("RBLX", "1d"): "confluence",  # Sharpe 1.06 N=38 WR=78.9%
    ("SOFI", "1d"): "confluence",  # Sharpe 0.71 N=42 WR=73.8%
    ("USAR", "1h"): "confluence",  # Sharpe 0.75 N=74 WR=59.5%
    ("AIS", "1h"): "rsi2",  # Sharpe 0.784 N=77 WR=57.1%
    ("BABA", "4h"): "rsi2",  # Sharpe 0.621 N=30 WR=53.3%
    ("BB", "1h"): "rsi2",  # Sharpe 0.727 N=93 WR=55.9%
    ("CEG", "1h"): "rsi2",  # Sharpe 0.603 N=109 WR=51.4%
    ("CRWD", "1h"): "rsi2",  # Sharpe 0.765 N=124 WR=58.9%
    ("CRWD", "4h"): "rsi2",  # Sharpe 0.69 N=42 WR=64.3%
    ("JPM", "1h"): "rsi2",  # Sharpe 0.622 N=107 WR=55.1%
    ("JPM", "4h"): "rsi2",  # Sharpe 0.604 N=47 WR=70.2%
    ("LVHI", "4h"): "rsi2",  # Sharpe 1.195 N=30 WR=63.3%
    ("NTRS", "1h"): "rsi2",  # Sharpe 1.017 N=107 WR=59.8%
    ("OKLO", "4h"): "rsi2",  # Sharpe 0.766 N=33 WR=72.7%
    ("ORCL", "1h"): "rsi2",  # Sharpe 0.842 N=113 WR=54.9%
    ("PKW", "4h"): "rsi2",  # Sharpe 0.614 N=40 WR=57.5%
    ("RBLX", "4h"): "rsi2",  # Sharpe 0.91 N=38 WR=57.9%
    ("REMX", "4h"): "rsi2",  # Sharpe 0.845 N=32 WR=71.9%
    ("SLV", "4h"): "rsi2",  # Sharpe 0.744 N=40 WR=65.0%
    ("SPMO", "1h"): "rsi2",  # Sharpe 1.074 N=134 WR=56.7%

    # 2026-07-25 补跑（用户追问 HOOD/EU/XYZ/COIN/DELL，仅 HOOD/DELL 达标）
    ("DELL", "1h"): "confluence",  # Sharpe 0.83 N=70 WR=61.4%
    ("DELL", "4h"): "rsi2",  # Sharpe 0.853 N=38 WR=68.4%
    ("HOOD", "1h"): "rsi2",  # Sharpe 1.108 N=142 WR=62.7%
    ("HOOD", "4h"): "rsi2",  # Sharpe 0.644 N=51 WR=54.9%

    # 2026-07-25 MR（均值回归）首次接入实时扫描，见 MR_PARAMS 注释
    ("TSM",  "1h"): "mr",  # Sharpe 1.281 N=31 WR=61.3%
    ("FDVV", "1h"): "mr",  # Sharpe 0.619 N=38 WR=42.1%

    # 2026-07-25 第四版watchlist批量回测新增（89个新标的 -> 21个通过筛选，含1个MR、8个Confluence、15个RSI2；
    # SMR 1h RSI2 Sharpe 0.686 但最大回撤-95.12%，判定风险过高已排除，不接入）
    ("CBUS", "1h"): "confluence",  # Sharpe 0.79 N=110 WR=59.1%
    ("CRCL", "1h"): "confluence",  # Sharpe 0.92 N=40 WR=60.0%
    ("CRWV", "1h"): "confluence",  # Sharpe 1.21 N=73 WR=64.4%
    ("LMT", "1h"): "confluence",  # Sharpe 0.77 N=116 WR=65.5%
    ("OC", "4h"): "confluence",  # Sharpe 0.83 N=40 WR=62.5%
    ("ONDS", "1d"): "confluence",  # Sharpe 0.94 N=53 WR=79.2%
    ("ONDS", "1h"): "confluence",  # Sharpe 0.88 N=131 WR=65.6%
    ("OUST", "1d"): "confluence",  # Sharpe 0.62 N=46 WR=73.9%
    ("AGI", "4h"): "rsi2",  # Sharpe 0.856 N=37 WR=70.3%
    ("BAC", "1h"): "rsi2",  # Sharpe 0.782 N=116 WR=61.2%
    ("BE", "4h"): "rsi2",  # Sharpe 0.698 N=41 WR=68.3%
    ("CCB", "4h"): "rsi2",  # Sharpe 0.622 N=38 WR=71.1%
    ("FOX", "4h"): "rsi2",  # Sharpe 0.91 N=40 WR=55.0%
    ("GE", "4h"): "rsi2",  # Sharpe 0.837 N=45 WR=62.2%
    ("GOOG", "4h"): "rsi2",  # Sharpe 0.875 N=46 WR=63.0% -- GOOGL已在mega_cap组，GOOG是无投票权股，走势高度相关，属重复板块敞口
    ("LTL", "1h"): "rsi2",  # Sharpe 0.982 N=73 WR=56.2%
    ("MS", "4h"): "rsi2",  # Sharpe 0.601 N=51 WR=62.7%
    ("OSCR", "4h"): "rsi2",  # Sharpe 0.623 N=42 WR=61.9%
    ("WBD", "1h"): "rsi2",  # Sharpe 0.969 N=81 WR=53.1%
    ("WBD", "4h"): "rsi2",  # Sharpe 0.796 N=32 WR=62.5%
    ("WDC", "1h"): "rsi2",  # Sharpe 1.276 N=141 WR=59.6%
    ("WDC", "4h"): "rsi2",  # Sharpe 1.01 N=47 WR=70.2%
    ("WMT", "4h"): "rsi2",  # Sharpe 0.677 N=42 WR=61.9%
    ("MKSI", "1h"): "mr",  # Sharpe 0.623 N=31 WR=38.7%
}

# 52周突破最优参数（来自 breakout_backtest.py --optimize）
BREAKOUT_PARAMS: dict[str, dict] = {
    "NVDA": {"confirm_days": 1, "atr_trail_mult": 3.0, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},
    "MU":   {"confirm_days": 1, "atr_trail_mult": 3.0, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": True},
    "MSFT": {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},
    "PLTR": {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},
    "TSLA": {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 10, "use_vol_filter": False},
    # AAPL: Sharpe 1.161（9笔，样本偏少），confirm=2 过滤假突破，vol 放量确认
    "AAPL": {"confirm_days": 2, "atr_trail_mult": 2.0, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": True},

    # 2026-07-25 watchlist 批量回测新增（默认参数，未逐个网格优化）
    "DGRO": {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},  # Sharpe 0.662 N=50
    "SPYM": {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},  # Sharpe 0.635 N=51
    "VOO":  {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},  # Sharpe 0.611 N=52
    "VTI":  {"confirm_days": 1, "atr_trail_mult": 2.5, "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False},  # Sharpe 0.627 N=54
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
    # PLTR — 网格最优参数（2026-06，N=25/109/36）
    ("PLTR", "1d"): {"rsi2_entry": 10, "atr_trail_mult": 2.0, "min_market_score": 1, "use_vol_score": True},
    ("PLTR", "1h"): {"rsi2_entry": 5,  "atr_trail_mult": 3.0, "min_market_score": 3},
    ("PLTR", "4h"): {"rsi2_entry": 10, "atr_trail_mult": 3.0, "min_market_score": 1},

    # 2026-07-25 watchlist 批量回测新增（rsi2_backtest.py DEFAULT_PARAMS，未逐个网格优化）
    ("AIS",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("BABA", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("BB",   "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("CEG",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("CRWD", "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("CRWD", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("JPM",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("JPM",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("LVHI", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("NTRS", "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("OKLO", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("ORCL", "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("PKW",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("RBLX", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("REMX", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("SLV",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("SPMO", "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},

    # 2026-07-25 补跑
    ("DELL", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("HOOD", "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("HOOD", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},

    # 2026-07-25 第四版watchlist批量回测新增
    ("AGI",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("BAC",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("BE",   "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("CCB",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("FOX",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("GE",   "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("GOOG", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("LTL",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("MS",   "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("OSCR", "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("WBD",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("WBD",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("WDC",  "1h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.0, "min_market_score": 2},
    ("WDC",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
    ("WMT",  "4h"): {"rsi2_entry": 10.0, "atr_trail_mult": 2.5, "min_market_score": 2},
}

# MR（均值回归）参数：来自 mr_backtest.py DEFAULT_PARAMS，2026-07-25 首次接入实时扫描
# 只做多，z-score<=-0.9 + RSI超卖 + ADX<上限 + close>trendSMA；ATR追踪出场+时间止损
MR_PARAMS: dict[tuple[str, str], dict] = {
    ("TSM",  "1h"): {"bb_len": 20, "bb_mult": 2.0, "rsi_len": 14, "rsi_os": 40.0,
                      "adx_len": 14, "adx_max": 25.0, "trend_filter_len": 200,
                      "use_trend_filter": True, "atr_sl_mult": 2.0, "atr_trail_mult": 2.5,
                      "max_hold_bars": 48},  # Sharpe 1.281 N=31
    ("FDVV", "1h"): {"bb_len": 20, "bb_mult": 2.0, "rsi_len": 14, "rsi_os": 40.0,
                      "adx_len": 14, "adx_max": 25.0, "trend_filter_len": 200,
                      "use_trend_filter": True, "atr_sl_mult": 2.0, "atr_trail_mult": 2.5,
                      "max_hold_bars": 48},  # Sharpe 0.619 N=38
    ("MKSI", "1h"): {"bb_len": 20, "bb_mult": 2.0, "rsi_len": 14, "rsi_os": 40.0,
                      "adx_len": 14, "adx_max": 25.0, "trend_filter_len": 200,
                      "use_trend_filter": True, "atr_sl_mult": 2.0, "atr_trail_mult": 2.5,
                      "max_hold_bars": 48},  # Sharpe 0.623 N=31
}

BENCHMARK_SYMBOLS  = {"QQQ", "SPY"}
SECTOR_ETF_SYMBOLS = {"SOXX", "SMH"}
# 半导体个股：SOXX 弱势时追加板块逆风警告
SEMI_SYMBOLS = {"MU", "MRVL", "STX", "SNDK", "NVDA", "INTC", "AMD", "AMAT", "KLAC", "TSM"}

# ── 信号去重：同一根 bar 的信号只发一次（持久化到磁盘，重启不丢失）────────────
# key: "symbol|tf|strategy|direction"  value: bar 日期字符串 (YYYY-MM-DD)
_SENT_SIGNALS_PATH = Path("data/.sent_signals.json")

def _load_sent_signals() -> dict[str, str]:
    """从磁盘加载已发信号记录，忽略读取错误。"""
    import json
    try:
        if _SENT_SIGNALS_PATH.exists():
            data = json.loads(_SENT_SIGNALS_PATH.read_text())
            # 保留最近 7 天的 bar_date 记录（覆盖周末重启场景）
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            return {k: v for k, v in data.items() if v >= cutoff}
    except Exception:
        pass
    return {}

def _save_sent_signals(signals: dict[str, str]):
    """持久化已发信号记录到磁盘。"""
    import json
    try:
        _SENT_SIGNALS_PATH.parent.mkdir(exist_ok=True)
        _SENT_SIGNALS_PATH.write_text(json.dumps(signals))
    except Exception:
        pass

_sent_signals: dict[str, str] = _load_sent_signals()


# ── 信号日志（永久保留，用于复盘） ────────────────────────────────────────
_SIGNAL_LOG_PATH = Path("logs/signal_log.csv")

_LOG_FIELDS = [
    "timestamp", "bar_date", "symbol", "tf", "strategy", "direction", "entry_price", "atr", "tp1", "tp2", "sl",
    "market_score", "vix", "quality", "signal_id", "source", "is_shadow", "source_strategy", "params_json",
    "sector_aligned", "screener_rank", "market_regime",
]

def _ensure_log_schema():
    """Upgrade the append-only ledger without losing older signal rows."""
    if not _SIGNAL_LOG_PATH.exists():
        return
    with open(_SIGNAL_LOG_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
        existing = list(rows[0].keys()) if rows else []
    if set(_LOG_FIELDS).issubset(existing):
        return
    with open(_SIGNAL_LOG_PATH, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LOG_FIELDS)
        writer.writeheader()
        for old in rows:
            writer.writerow({field: old.get(field, "live" if field == "source" else "") for field in _LOG_FIELDS})

def _log_signal(symbol: str, tf: str, bar_date: str, sig: dict, *, params: dict | None = None,
                is_shadow: bool = False, source_strategy: str = "", sector_aligned: bool | None = None,
                screener_rank: int | None = None, market_regime: str = "") -> dict:
    """将信号追加写入 logs/signal_log.csv（永久保留，不自动清理）。"""
    _SIGNAL_LOG_PATH.parent.mkdir(exist_ok=True)
    _ensure_log_schema()
    strategy = str(sig.get("strategy", "")) + ("_shadow" if is_shadow else "")
    row = {
        "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "bar_date":     bar_date,
        "symbol":       symbol,
        "tf":           tf,
        "strategy":     strategy,
        "direction":    sig.get("direction", ""),
        "entry_price":  round(float(sig.get("close", 0)), 4),
        "atr":          round(float(sig.get("atr", 0)), 4),
        "tp1":          round(float(sig.get("tp1", 0)), 4),
        "tp2":          round(float(sig.get("tp2", 0)), 4),
        "sl":           round(float(sig.get("sl", 0)), 4),
        "market_score": sig.get("market_score", ""),
        "vix":          round(float(sig["vix"]), 2) if sig.get("vix") is not None else "",
        "quality":      sig.get("quality", 0),
        "signal_id":    f"{symbol}|{tf}|{strategy}|{bar_date}|{sig.get('direction','')}",
        "source":       "shadow" if is_shadow else "live",
        "is_shadow":    int(is_shadow),
        "source_strategy": source_strategy,
        "params_json":  json.dumps(params or {}, sort_keys=True),
        "sector_aligned": sector_aligned if sector_aligned is not None else "",
        "screener_rank": screener_rank if screener_rank is not None else "",
        "market_regime": market_regime,
    }
    write_header = not _SIGNAL_LOG_PATH.exists()
    with open(_SIGNAL_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return row


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

_YF_PERIOD = {"1h": "60d", "4h": "60d", "1d": "3y"}
_YF_INTERVAL = {"1h": "1h", "4h": "1h", "1d": "1d"}   # yfinance 无 4h，用 1h 重采样


def fetch_bars(ib, symbol: str, tf: str) -> pd.DataFrame | None:
    """拉取历史 bar（yfinance，无 IB pacing 限制）。

    ib 参数保留签名兼容性，实际不使用。
    """
    try:
        interval = _YF_INTERVAL[tf]
        period   = _YF_PERIOD[tf]
        ticker   = yf.Ticker(symbol)
        raw = ticker.history(period=period, interval=interval, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        # 标准化列名
        raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        raw.index.name = "Date"
        raw.index = pd.to_datetime(raw.index)
        # 4h 重采样：把 1h bar 合并成 4h
        if tf == "4h":
            raw = (raw.resample("4h", label="right", closed="right")
                   .agg({"Open": "first", "High": "max", "Low": "min",
                         "Close": "last", "Volume": "sum"})
                   .dropna(subset=["Close"]))
        # 去除时区（backtesting 库不接受 tz-aware index）
        if raw.index.tz is not None:
            raw.index = raw.index.tz_convert("America/New_York").tz_localize(None)
        return raw if not raw.empty else None
    except Exception as e:
        print(f"  fetch_bars({symbol} {tf}) yfinance 异常: {e}")
        return None


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


# ── MR（均值回归）信号检查 ─────────────────────────────────────────────────
# 2026-07-25 首次接入实时扫描，逻辑对齐 mr_strategy.py 回测（只做多）：
#   入场：z-score <= -0.9（布林下轨附近）+ RSI < rsi_os + ADX < adx_max + close > trendSMA
#   出场（仅供告警展示，不做状态跟踪）：初始 SL = entry - atr_sl_mult × ATR，
#   之后转为 ATR 追踪止损（只升不降）+ 超过 max_hold_bars 时间止损

def check_mr_signal(df_raw: pd.DataFrame, symbol: str, tf: str,
                     vix_value: float | None = None) -> dict | None:
    if len(df_raw) < 210:
        return None

    p = MR_PARAMS.get((symbol, tf))
    if p is None:
        return None

    bb_len      = int(p.get("bb_len", 20))
    bb_mult     = float(p.get("bb_mult", 2.0))
    rsi_len     = int(p.get("rsi_len", 14))
    rsi_os      = float(p.get("rsi_os", 40.0))
    adx_len     = int(p.get("adx_len", 14))
    adx_max     = float(p.get("adx_max", 25.0))
    trend_len   = int(p.get("trend_filter_len", 200))
    use_trend   = bool(p.get("use_trend_filter", True))
    atr_sl_mult = float(p.get("atr_sl_mult", 2.0))

    close = df_raw["Close"]
    high  = df_raw["High"]
    low   = df_raw["Low"]

    bb_mid     = _sma(close, bb_len)
    bb_std     = close.rolling(bb_len, min_periods=bb_len).std(ddof=1)
    bb_upper   = bb_mid + bb_mult * bb_std
    bb_lower   = bb_mid - bb_mult * bb_std
    band_width = bb_upper - bb_lower
    z_score    = (2 * (close - bb_mid) / band_width.replace(0, np.nan)).clip(-2, 2)

    rsi_val   = _rsi(close, rsi_len)
    adx_val   = _adx(high, low, close, adx_len)
    atr_val   = _atr(high, low, close, 14)
    trend_sma = _sma(close, trend_len)

    last_close = float(close.iloc[-1])
    last_z     = float(z_score.iloc[-1])
    last_rsi   = float(rsi_val.iloc[-1])
    last_adx   = float(adx_val.iloc[-1])
    last_atr   = float(atr_val.iloc[-1])
    last_trend = float(trend_sma.iloc[-1])

    if any(math.isnan(v) for v in [last_z, last_rsi, last_adx, last_atr, last_trend]):
        return None

    ok_trend = (not use_trend) or (last_close > last_trend)
    ok_adx   = last_adx < adx_max
    touch_lower = last_z <= -0.9

    if not (touch_lower and last_rsi < rsi_os and ok_adx and ok_trend):
        return None

    sl = last_close - atr_sl_mult * last_atr

    z_pts   = min(5.0, max(0.0, (-0.9 - last_z) * 5.0))
    rsi_pts = min(5.0, max(0.0, (rsi_os - last_rsi) / rsi_os * 5.0)) if rsi_os > 0 else 0.0
    quality = round(min(10, max(0, z_pts + rsi_pts)))

    return {
        "strategy":  "MR",
        "direction": "做多",
        "close":     last_close,
        "atr":       last_atr,
        "z_score":   last_z,
        "rsi":       last_rsi,
        "adx":       last_adx,
        "sl":        sl,
        "vix":       vix_value,
        "quality":   quality,
    }


# ── 告警消息格式 ──────────────────────────────────────────────────────────

def _regime_line(market_score: float, vix: float | None) -> str:
    score_str = f"{market_score:.0f}/4"
    if vix is not None:
        vix_tag = f"  VIX {vix:.1f} ⚠" if vix > 20 else f"  VIX {vix:.1f}"
        return f"  Regime: {score_str}{vix_tag}"
    return f"  Regime: {score_str}"


_HOLD_DESC = {"1h": "最长 10 小时", "4h": "最长 2 交易日", "1d": "最长 3 周"}


def build_confluence_alert(symbol: str, tf: str, sig: dict) -> str:
    d = sig["direction"]
    emoji = "📈" if d == "做多" else "📉"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    quality = sig.get("quality", 0)
    hold = _HOLD_DESC.get(tf, "—")
    return (
        f"{emoji} {symbol} {tf} {d}信号 [Confluence]  ⭐ {quality}/10\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  Bull: {sig['bull_score']}/6  Bear: {sig['bear_score']}/6  ADX: {sig['adx']:.1f}\n"
        f"  TP1: ${sig['tp1']:.2f}  TP2: ${sig['tp2']:.2f}\n"
        f"  SL(utTS): ${sig['sl']:.2f}  持仓: {hold}\n"
        + _regime_line(sig["market_score"], sig.get("vix")) + "\n"
        + _vix_position_hint(sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )


def build_rsi2_alert(symbol: str, tf: str, sig: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    p = RSI2_PARAMS.get((symbol, tf), {})
    quality = sig.get("quality", 0)
    hold = _HOLD_DESC.get(tf, "—")
    return (
        f"📊 {symbol} {tf} 做多信号 [RSI2 v2]  ⭐ {quality}/10\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  RSI2: {sig['rsi2']:.1f}  SMA200: ${sig['sma200']:.2f}\n"
        f"  SL(ATR trail ×{p.get('atr_trail_mult', 2.5)}): ${sig['sl']:.2f}  持仓: {hold}\n"
        + _regime_line(sig["market_score"], sig.get("vix")) + "\n"
        + _vix_position_hint(sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )


def build_mr_alert(symbol: str, tf: str, sig: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    p = MR_PARAMS.get((symbol, tf), {})
    quality = sig.get("quality", 0)
    hold = _HOLD_DESC.get(tf, "—")
    return (
        f"🔄 {symbol} {tf} 做多信号 [MR 均值回归]  ⭐ {quality}/10\n"
        f"  价格: ${sig['close']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  z-score: {sig['z_score']:.2f}  RSI: {sig['rsi']:.1f}  ADX: {sig['adx']:.1f}\n"
        f"  SL(初始 ATR×{p.get('atr_sl_mult', 2.0)}，之后转追踪): ${sig['sl']:.2f}  持仓: {hold}\n"
        + _vix_position_hint(sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )




# ── 52周高点突破信号 ───────────────────────────────────────────────────────

def check_breakout_signal(df_raw: pd.DataFrame, symbol: str,
                          vix_value: float | None = None) -> dict | None:
    """
    52周高点突破信号（仅日线）。
    入场：close > rolling_max(High, 252).shift(1)（连续 confirm_days 日）
          且 close > SMA200（大趋势过滤）
    """
    if len(df_raw) < 260:
        return None

    p = BREAKOUT_PARAMS.get(symbol, {
        "confirm_days": 1, "atr_trail_mult": 2.5,
        "atr_sl_mult": 1.5, "max_hold_bars": 20, "use_vol_filter": False,
    })
    confirm       = int(p.get("confirm_days",   1))
    trail_mult    = float(p.get("atr_trail_mult", 2.5))
    sl_mult       = float(p.get("atr_sl_mult",    1.5))
    use_vol       = bool(p.get("use_vol_filter",  False))

    close  = df_raw["Close"]
    high   = df_raw["High"]
    low    = df_raw["Low"]
    volume = df_raw["Volume"].replace(0, np.nan)

    high_252 = high.rolling(252, min_periods=200).max().shift(1)
    sma200   = close.rolling(200).mean()
    atr14    = _atr(high, low, close, 14)

    last_close  = float(close.iloc[-1])
    last_h252   = float(high_252.iloc[-1])
    last_sma200 = float(sma200.iloc[-1])
    last_atr    = float(atr14.iloc[-1])

    if any(math.isnan(v) for v in [last_close, last_h252, last_sma200, last_atr]):
        return None

    # 大趋势过滤
    if last_close <= last_sma200:
        return None

    # 突破检测（N 日确认）
    bo = (close > high_252).astype(int)
    if confirm >= 2:
        confirmed = bool(bo.rolling(confirm).min().iloc[-1])
    else:
        confirmed = bool(bo.iloc[-1])
    if not confirmed:
        return None

    # 成交量过滤
    if use_vol:
        vol_avg = volume.rolling(20).mean()
        if pd.isna(vol_avg.iloc[-1]) or float(volume.iloc[-1]) <= float(vol_avg.iloc[-1]) * 1.5:
            return None

    sl  = last_close - sl_mult    * last_atr
    tp1 = last_close + 2.0        * last_atr
    tp2 = last_close + trail_mult * last_atr

    return {
        "strategy":   "Breakout52W",
        "direction":  "做多",
        "close":      last_close,
        "atr":        last_atr,
        "high_252":   last_h252,
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "confirm":    confirm,
        "vix":        vix_value,
    }


def build_breakout_alert(symbol: str, sig: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    p  = BREAKOUT_PARAMS.get(symbol, {})
    confirm_tag = f"（{sig['confirm']}日确认）" if sig["confirm"] >= 2 else ""
    return (
        f"🚀 {symbol} 1d 突破52周高点{confirm_tag} [Breakout]\n"
        f"  价格: ${sig['close']:.2f}  52W高: ${sig['high_252']:.2f}  ATR: ${sig['atr']:.2f}\n"
        f"  TP1: ${sig['tp1']:.2f}  TP2: ${sig['tp2']:.2f}\n"
        f"  SL(初始 ×{p.get('atr_sl_mult',1.5)}): ${sig['sl']:.2f}"
        f"  持仓: 最长 {p.get('max_hold_bars',20)} 交易日\n"
        + _regime_line(4.0, sig.get("vix")) + "\n"
        + _vix_position_hint(sig.get("vix")) + "\n"
        + f"  时间: {ts} ET"
    )


# ── 财报预警 ─────────────────────────────────────────────────────────────

def _fetch_all_earnings(symbols: list[str], max_calendar_days: int = 7) -> dict[str, int]:
    """
    批量查询即将到来的财报。
    返回 {symbol: approx_trading_days}，仅包含 max_calendar_days 内有财报的标的。
    trading_days 为从当前到财报的大约交易日数（calendar_days × 5/7）。
    """
    import yfinance as yf
    from datetime import date as date_type
    result = {}
    cutoff = datetime.now() + timedelta(days=max_calendar_days)
    for sym in symbols:
        try:
            cal = yf.Ticker(sym).calendar
            if cal is None:
                continue
            d = cal.get("Earnings Date")
            if d is None:
                continue
            if isinstance(d, list):
                d = d[0]
            if hasattr(d, "date"):
                d = d.date()
            dt = (datetime(d.year, d.month, d.day)
                  if isinstance(d, date_type)
                  else datetime.strptime(str(d)[:10], "%Y-%m-%d"))
            delta = (dt - datetime.now()).days
            if 0 <= delta <= max_calendar_days:
                result[sym] = max(1, round(delta * 5 / 7))
        except Exception:
            pass
    return result


def _load_screener_ranks(top_n: int = 10) -> dict[str, int]:
    """
    读取最近一次选股结果，返回 {symbol: rank} for Top-N。
    文件不存在或读取失败时返回空 dict。
    """
    path = Path("data/screener_results.csv")
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
        latest = df["run_date"].max()
        top = (df[df["run_date"] == latest]
               .drop_duplicates(subset=["symbol"])
               .sort_values("rank_in_run")
               .head(top_n))
        return {row["symbol"]: int(row["rank_in_run"]) for _, row in top.iterrows()}
    except Exception:
        return {}


def _extra_warnings(symbol: str, earnings_days: dict[str, int],
                    soxx_below_ma50: bool,
                    screener_ranks: dict[str, int]) -> str:
    """返回信号附加注释行（可能为空字符串）。"""
    lines = []
    rank = screener_ranks.get(symbol)
    if rank is not None:
        lines.append(f"  📊 本周因子选股 #{rank}")
    if symbol in SEMI_SYMBOLS and soxx_below_ma50:
        lines.append("  ⚠️ SOXX 弱势（< MA50），半导体板块逆风")
    days = earnings_days.get(symbol)
    if days is not None:
        lines.append(f"  ⚠️ 财报约 {days} 交易日后，谨慎开新仓")
    return "\n".join(lines)


def _portfolio_context(sig: dict, symbol: str) -> str:
    lines = paper_risk_warnings(symbol)
    probability = meta_label_suggest(sig)
    if probability is not None:
        size = "正常" if probability >= .60 else ("减半" if probability >= .45 else "观察")
        lines.append(f"🤖 Meta-label 胜率估计 {probability:.0%}，建议{size}仓位")
    return "\n".join(f"  {line}" if not line.startswith("  ") else line for line in lines)


def _log_shadow(symbol: str, tf: str, bar_date: str, sig: dict, params: dict, name: str,
                *, sector_aligned: bool | None, screener_rank: int | None, market_regime: str) -> None:
    """Record a candidate without Telegram delivery or any execution action."""
    shadow = dict(sig)
    shadow["strategy"] = name
    key = f"{symbol}|{tf}|{name}_shadow|{shadow.get('direction','做多')}"
    if _sent_signals.get(key) == bar_date:
        return
    _log_signal(symbol, tf, bar_date, shadow, params=params, is_shadow=True,
                source_strategy=sig.get("strategy", ""), sector_aligned=sector_aligned,
                screener_rank=screener_rank, market_regime=market_regime)
    _sent_signals[key] = bar_date
    _save_sent_signals(_sent_signals)
    print(f"  {symbol} {tf}: 记录影子信号 [{name}]")


def _ibs(df_raw: pd.DataFrame) -> float:
    last = df_raw.iloc[-1]
    width = float(last["High"] - last["Low"])
    return (float(last["Close"] - last["Low"]) / width) if width > 0 else 1.0


# ── MAG7 轮动 ───────────────────────────────────────────────────────────

def _fetch_earnings_dates(symbols: list[str], within_days: int = 21) -> dict[str, str]:
    """返回 {symbol: "MM-DD"} 若在 within_days 内有财报，否则不含该 key。"""
    import yfinance as yf
    from datetime import date as date_type
    result = {}
    cutoff = datetime.now() + timedelta(days=within_days)
    for sym in symbols:
        try:
            cal = yf.Ticker(sym).calendar
            if cal is None:
                continue
            d = cal.get("Earnings Date")
            if d is None:
                continue
            if isinstance(d, list):
                d = d[0]
            if hasattr(d, "date"):
                d = d.date()
            dt = datetime(d.year, d.month, d.day) if isinstance(d, date_type) else datetime.strptime(str(d)[:10], "%Y-%m-%d")
            if datetime.now() <= dt <= cutoff:
                result[sym] = dt.strftime("%m-%d")
        except Exception:
            pass
    return result


def _vix_put_spread_hint(vix: float | None) -> str:
    if vix is None:
        return ""
    if vix < 20:
        return f"  VIX {vix:.1f} ✅ 正常开仓（5-6% OTM）"
    elif vix < 25:
        return f"  VIX {vix:.1f} ⚠️ 缩小仓位，行权价下移至 7-8% OTM"
    elif vix < 30:
        return f"  VIX {vix:.1f} 🔴 规模减半，价差收窄至 $5 内"
    else:
        return f"  VIX {vix:.1f} ❌ 不开新仓，平现有仓位"


def _vix_position_hint(vix: float | None) -> str:
    if vix is None:
        return ""
    if vix < 20:
        return f"  仓位建议: 正常（VIX {vix:.1f}）"
    if vix < 25:
        return f"  仓位建议: 缩小（VIX {vix:.1f}）"
    if vix < 30:
        return f"  仓位建议: 减半（VIX {vix:.1f}）"
    return f"  仓位建议: 不开新仓（VIX {vix:.1f}）"


def _scan_market_regime(ib, vix_value: float | None) -> tuple[str, bool]:
    """Use the ETF scanner's definitions; the bool denotes risk-on chop."""
    try:
        spy = fetch_bars(ib, "SPY", "1d")
        qqq = fetch_bars(ib, "QQQ", "1d")
        if spy is None or qqq is None or len(spy) < 200:
            return "unknown", False
        close = spy["Close"]
        above_200 = float(close.iloc[-1]) > float(close.rolling(200).mean().iloc[-1])
        bull_ma = float(close.rolling(20).mean().iloc[-1]) > float(close.rolling(50).mean().iloc[-1])
        rs = qqq["Close"].reindex(close.index, method="ffill") / close
        rs_up = float(rs.iloc[-1]) > float(rs.rolling(20).mean().iloc[-1])
        calm = vix_value is None or vix_value < 25
        regime = "risk_on" if above_200 and bull_ma and rs_up and calm else ("neutral" if above_200 and calm else "risk_off")
        qqq_adx = compute_signals(qqq, get_params("QQQ", "1d")).iloc[-1].get("adx", 0)
        return regime, bool(regime == "risk_on" and float(qqq_adx) < 20)
    except Exception as exc:
        print(f"  市场状态: 获取失败 ({exc})")
        return "unknown", False


def check_mag7_rotation_signal(vix: float | None = None) -> dict | None:
    """每周触发一次（本周未发过则发），返回本周应持仓的 MAG7 标的。"""
    try:
        rec = run_rotation(top_n=2, rs_period=60, use_risk_off=True)
    except Exception as e:
        print(f"  MAG7 轮动: run_rotation 失败 ({e})")
        return None
    if rec.empty:
        return None
    latest   = rec.iloc[-1]
    holdings = latest["holdings"]
    date_str = str(latest.name.date())
    in_mkt   = latest["in_market"]
    prev_holdings = rec.iloc[-2]["holdings"] if len(rec) >= 2 else ""
    changed = (holdings != prev_holdings)
    # 财报日期（仅持仓标的，21天内）
    earnings = {}
    if in_mkt and holdings not in ("(空仓)",):
        syms = [s.strip() for s in holdings.split(",")]
        earnings = _fetch_earnings_dates(syms, within_days=21)
    return {
        "holdings":      holdings,
        "prev_holdings": prev_holdings,
        "date":          date_str,
        "in_market":     in_mkt,
        "changed":       changed,
        "earnings":      earnings,
        "vix":           vix,
    }


def build_mag7_alert(sig: dict) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    holdings = sig["holdings"]
    prev     = sig["prev_holdings"]
    earnings = sig.get("earnings", {})
    vix      = sig.get("vix")
    changed_tag = "  🔄 换仓" if sig["changed"] else "  （持仓不变）"
    if not sig["in_market"]:
        body = "  ⚠️ QQQ < 200SMA，本周空仓"
    elif holdings == "(空仓)":
        body = "  本周空仓（无强势标的）"
    else:
        syms = [s.strip() for s in holdings.split(",")]
        parts = []
        for s in syms:
            tag = f" ⚠️财报{earnings[s]}" if s in earnings else ""
            parts.append(f"${s}{tag}")
        body = "  本周持仓: " + " / ".join(parts)
    lines = [f"🔁 MAG7 周频轮动{changed_tag}", body]
    if prev:
        lines.append(f"  上周持仓: {prev}")
    for sym, d in earnings.items():
        lines.append(f"  ⚠️ {sym} 财报 {d}，该周避免卖 Put")
    hint = _vix_put_spread_hint(vix)
    if hint:
        lines.append(hint)
    lines += [
        "  策略: top-2 by 60d RS  (risk-off: QQQ>200SMA)",
        f"  时间: {ts} ET",
    ]
    return "\n".join(lines)

# ── 主循环 ───────────────────────────────────────────────────────────────

def run_scan(ib=None):
    """扫描所有标的 × 所有周期，发告警。"""
    print(f"\n[{datetime.now().strftime('%H:%M')}] 开始扫描 {len(ALL_SYMBOLS)} 个标的...")
    found = 0
    scan_signals: dict[str, list[str]] = {}
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}

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

    market_regime, risk_on_chop = _scan_market_regime(ib, vix_value)
    print(f"  市场状态: {market_regime}{'（趋势弱，追随策略降级）' if risk_on_chop else ''}")

    # ── MAG7 周频轮动────────────────────────────────────────────────────
    mag7_sig = check_mag7_rotation_signal(vix=vix_value)
    if mag7_sig is not None:
        print(f"  MAG7 轮动: {mag7_sig['holdings']}  in_market={mag7_sig['in_market']}")
        # 用本周周一日期作为 dedup key（不受 run_rotation 历史数据截止影响）
        this_monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
        dedup_key = f"mag7|weekly|{this_monday}"
        if _sent_signals.get(dedup_key) == this_monday:
            print(f"  MAG7 轮动: 本周已发送，跳过")
        else:
            msg = build_mag7_alert(mag7_sig)
            print(f"\n  ⚡ MAG7 轮动信号")
            print(msg)
            tg_alert(msg)
            _sent_signals[dedup_key] = this_monday
            _save_sent_signals(_sent_signals)
            found += 1
    else:
        print(f"  MAG7 轮动: 本周已发送，跳过")

    # ── 选股排名：读取最近一次选股结果 Top10 ──────────────────────────────────
    screener_ranks = _load_screener_ranks(top_n=10)
    if screener_ranks:
        top_syms = ", ".join(f"{s}#{r}" for s, r in sorted(screener_ranks.items(), key=lambda x: x[1]))
        print(f"  选股 Top10: {top_syms}")
    else:
        print("  选股 Top10: 无数据（screener_results.csv 不存在）")

    # ── 财报预警：批量查询所有非ETF标的近期财报（7个日历日 ≈ 5个交易日）──────────
    _etf_set = BENCHMARK_SYMBOLS | SECTOR_ETF_SYMBOLS
    _stock_symbols = [s for s in ALL_SYMBOLS if s not in _etf_set]
    print("  查询财报日期...", end="", flush=True)
    try:
        earnings_days = _fetch_all_earnings(_stock_symbols, max_calendar_days=7)
        if earnings_days:
            print(f" 近期财报: {earnings_days}")
        else:
            print(" 无近期财报")
    except Exception as e:
        print(f" 失败({e})")
        earnings_days = {}

    # ── SOXX 状态：判断半导体板块趋势（1d MA50），用于半导体个股信号辅助判断 ──
    soxx_below_ma50 = False
    try:
        df_soxx_1d = fetch_bars(ib, "SOXX", "1d")
        if df_soxx_1d is not None and len(df_soxx_1d) >= 50:
            soxx_ma50 = float(df_soxx_1d["Close"].rolling(50).mean().iloc[-1])
            soxx_last = float(df_soxx_1d["Close"].iloc[-1])
            soxx_below_ma50 = soxx_last < soxx_ma50
            _soxx_tag = "弱势 ⚠️" if soxx_below_ma50 else "强势 ✅"
            print(f"  SOXX 1d: ${soxx_last:.2f}  MA50: ${soxx_ma50:.2f}  {_soxx_tag}")
    except Exception as e:
        print(f"  SOXX MA50: 获取失败 ({e})")

    df_1d_cache: dict[str, pd.DataFrame] = {}  # 复用给 breakout 扫描，避免重复拉取

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
            price_cache[(symbol, tf)] = df_raw

            if tf == "1d":
                df_1d_cache[symbol] = df_raw  # 缓存日线数据供 breakout 扫描复用

            strategy = STRATEGY_MAP.get((symbol, tf), "confluence")
            bar_date = str(df_raw.index[-1].date())

            # Risk-off keeps this alert-only system focused on ETF pullbacks.
            if market_regime == "risk_off" and symbol not in (BENCHMARK_SYMBOLS | SECTOR_ETF_SYMBOLS):
                print(f"  {symbol} {tf}: Risk-Off，仅保留 ETF 深度回调候选")
                continue

            if strategy == "confluence":
                sig = check_confluence_signal(df_raw, params, df_qqq, vix_value)
                if sig and risk_on_chop:
                    sig["quality"] = max(0, int(sig.get("quality", 0)) - 1)
                if sig and sig["direction"] == "做空":
                    max_short = cfg["timeframes"][tf].get("max_market_score_short", 4)
                    score = sig.get("market_score") or 0
                    if score > max_short:
                        print(f"  {symbol} {tf}: 做空信号被 Regime 过滤（score={score} > {max_short}）")
                        sig = None
                if sig:
                    dedup_key = f"{symbol}|{tf}|confluence|{sig['direction']}"
                    if _sent_signals.get(dedup_key) == bar_date:
                        print(f"  {symbol} {tf}: 已发送（同 bar），跳过 [Confluence]")
                    else:
                        extra = _extra_warnings(symbol, earnings_days, soxx_below_ma50, screener_ranks)
                        resonance = scan_signals.setdefault(symbol, [])
                        if resonance:
                            sig["quality"] = min(10, int(sig.get("quality", 0)) + 1)
                            extra = "\n".join(filter(None, [extra, "  📈 多周期/多策略共振"] ))
                        resonance.append(f"{tf}:confluence")
                        portfolio = _portfolio_context(sig, symbol)
                        msg = build_confluence_alert(symbol, tf, sig)
                        if extra:
                            msg += "\n" + extra
                        if portfolio:
                            msg += "\n" + portfolio
                        print(f"\n  ⚡ 信号：{symbol} {tf} {sig['direction']} [Confluence]")
                        print(msg)
                        tg_alert(msg)
                        row = _log_signal(symbol, tf, bar_date, sig, params=params,
                                          sector_aligned=not soxx_below_ma50 if symbol in SEMI_SYMBOLS else None,
                                          screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        paper_open_position(row)
                        if (symbol, tf) == ("TSLA", "4h"):
                            shadow_p = {**params, "exit_variant": "ssl_exit"}
                            _log_shadow(symbol, tf, bar_date, sig, shadow_p, "TSLA_SSLTrail",
                                        sector_aligned=None, screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        if (symbol, tf) == ("MRVL", "1h"):
                            shadow_p = {**params, "atr_tp2_mult": float(params.get("atr_tp2_mult", 3)) + 1.0}
                            shadow_sig = {**sig, "tp2": sig["close"] + (1 if sig["direction"] == "做多" else -1) * shadow_p["atr_tp2_mult"] * sig["atr"]}
                            _log_shadow(symbol, tf, bar_date, shadow_sig, shadow_p, "MRVL_WideExit",
                                        sector_aligned=not soxx_below_ma50, screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        _sent_signals[dedup_key] = bar_date
                        _save_sent_signals(_sent_signals)
                        found += 1
                else:
                    print(f"  {symbol} {tf}: 无信号 [Confluence]")

            elif strategy == "rsi2":
                p = RSI2_PARAMS.get((symbol, tf), {})
                sig = check_rsi2_signal(df_raw, symbol, tf, df_qqq, vix_value)
                if sig:
                    dedup_key = f"{symbol}|{tf}|rsi2|做多"
                    if _sent_signals.get(dedup_key) == bar_date:
                        print(f"  {symbol} {tf}: 已发送（同 bar），跳过 [RSI2 v2]")
                    else:
                        extra = _extra_warnings(symbol, earnings_days, soxx_below_ma50, screener_ranks)
                        resonance = scan_signals.setdefault(symbol, [])
                        if resonance:
                            sig["quality"] = min(10, int(sig.get("quality", 0)) + 1)
                            extra = "\n".join(filter(None, [extra, "  📈 多周期/多策略共振"] ))
                        resonance.append(f"{tf}:rsi2")
                        portfolio = _portfolio_context(sig, symbol)
                        msg = build_rsi2_alert(symbol, tf, sig)
                        if extra:
                            msg += "\n" + extra
                        if portfolio:
                            msg += "\n" + portfolio
                        print(f"\n  ⚡ 信号：{symbol} {tf} 做多 [RSI2 v2]")
                        print(msg)
                        tg_alert(msg)
                        row = _log_signal(symbol, tf, bar_date, sig, params=p,
                                          sector_aligned=not soxx_below_ma50 if symbol in SEMI_SYMBOLS else None,
                                          screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        paper_open_position(row)
                        if _ibs(df_raw) < 0.2:
                            shadow_p = {**p, "use_ibs_filter": True}
                            _log_shadow(symbol, tf, bar_date, sig, shadow_p, "RSI2_IBS",
                                        sector_aligned=not soxx_below_ma50 if symbol in SEMI_SYMBOLS else None,
                                        screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        _sent_signals[dedup_key] = bar_date
                        _save_sent_signals(_sent_signals)
                        found += 1
                else:
                    p = RSI2_PARAMS.get((symbol, tf), {})
                    print(f"  {symbol} {tf}: 无信号 [RSI2 v2 entry<{p.get('rsi2_entry', 10)}]")

            elif strategy == "mr":
                p = MR_PARAMS.get((symbol, tf), {})
                sig = check_mr_signal(df_raw, symbol, tf, vix_value)
                if sig:
                    dedup_key = f"{symbol}|{tf}|mr|做多"
                    if _sent_signals.get(dedup_key) == bar_date:
                        print(f"  {symbol} {tf}: 已发送（同 bar），跳过 [MR]")
                    else:
                        extra = _extra_warnings(symbol, earnings_days, soxx_below_ma50, screener_ranks)
                        resonance = scan_signals.setdefault(symbol, [])
                        if resonance:
                            sig["quality"] = min(10, int(sig.get("quality", 0)) + 1)
                            extra = "\n".join(filter(None, [extra, "  📈 多周期/多策略共振"] ))
                        resonance.append(f"{tf}:mr")
                        portfolio = _portfolio_context(sig, symbol)
                        msg = build_mr_alert(symbol, tf, sig)
                        if extra:
                            msg += "\n" + extra
                        if portfolio:
                            msg += "\n" + portfolio
                        print(f"\n  ⚡ 信号：{symbol} {tf} 做多 [MR]")
                        print(msg)
                        tg_alert(msg)
                        row = _log_signal(symbol, tf, bar_date, sig, params=p,
                                          sector_aligned=not soxx_below_ma50 if symbol in SEMI_SYMBOLS else None,
                                          screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                        paper_open_position(row)
                        _sent_signals[dedup_key] = bar_date
                        _save_sent_signals(_sent_signals)
                        found += 1
                else:
                    print(f"  {symbol} {tf}: 无信号 [MR]")

            else:
                print(f"  {symbol} {tf}: 未知策略路由 '{strategy}'")

    # ── 52周高点突破扫描（仅日线，独立于主循环，复用 df_1d_cache 避免重复拉取）─────
    for symbol in BREAKOUT_PARAMS:
        _cached = df_1d_cache.get(symbol)
        df_raw = _cached if _cached is not None else fetch_bars(ib, symbol, "1d")
        if df_raw is not None:
            df_1d_cache[symbol] = df_raw
        sig = check_breakout_signal(df_raw, symbol, vix_value) if df_raw is not None else None
        if sig:
            bar_date  = str(df_raw.index[-1].date())
            dedup_key = f"{symbol}|1d|breakout|做多"
            if _sent_signals.get(dedup_key) == bar_date:
                print(f"  {symbol} 1d: 已发送（同 bar），跳过 [Breakout]")
            else:
                resonance = scan_signals.setdefault(symbol, [])
                if resonance:
                    sig["quality"] = min(10, int(sig.get("quality", 7)) + 1)
                else:
                    sig.setdefault("quality", 7)
                resonance.append("1d:breakout")
                msg   = build_breakout_alert(symbol, sig)
                extra = _extra_warnings(symbol, earnings_days, soxx_below_ma50, screener_ranks)
                if len(resonance) > 1:
                    extra = "\n".join(filter(None, [extra, "  📈 多周期/多策略共振"]))
                portfolio = _portfolio_context(sig, symbol)
                if extra:
                    msg += "\n" + extra
                if portfolio:
                    msg += "\n" + portfolio
                print(f"\n  🚀 突破信号：{symbol} 1d [Breakout52W]")
                print(msg)
                tg_alert(msg)
                row = _log_signal(symbol, "1d", bar_date, sig, params=BREAKOUT_PARAMS.get(symbol, {}),
                                  sector_aligned=not soxx_below_ma50 if symbol in SEMI_SYMBOLS else None,
                                  screener_rank=screener_ranks.get(symbol), market_regime=market_regime)
                paper_open_position(row)
                _sent_signals[dedup_key] = bar_date
                _save_sent_signals(_sent_signals)
                found += 1
        else:
            print(f"  {symbol} 1d: 无突破信号 [Breakout52W]")

    # RKLB remains a shadow-only breakout candidate until its sample is adequate.
    rklb = fetch_bars(ib, "RKLB", "1d")
    if rklb is not None:
        rklb_sig = check_breakout_signal(rklb, "RKLB", vix_value)
        if rklb_sig:
            rklb_sig["quality"] = 7
            _log_shadow("RKLB", "1d", str(rklb.index[-1].date()), rklb_sig,
                        {"atr_trail_mult": 3.0, "atr_sl_mult": 1.5, "max_hold_bars": 20},
                        "RKLB_Breakout", sector_aligned=None, screener_rank=screener_ranks.get("RKLB"),
                        market_regime=market_regime)

    for event in paper_update(price_cache, {"1h": 10, "4h": 10, "1d": 15}):
        print(f"  虚拟持仓平仓: {event['symbol']} {event['outcome']} {event['r_mult']:+.2f}R")
        if event["type"] == "pyramid":
            tg_alert(f"➕ {event['symbol']} 虚拟持仓 TP1 后继续创新高\n  纸面策略提示：可考虑补回已减半仓位，保护止损上移至 TP1。\n  仅提示，不执行任何下单。")

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

    tg_alert("✅ quantrift_stock 告警引擎已启动（yfinance 数据源）")

    try:
        if args.once:
            run_scan(None)
        else:
            while True:
                run_scan(None)
                wait_until_next_hour()
    except KeyboardInterrupt:
        print("\n⛔ 用户中断")


if __name__ == "__main__":
    main()

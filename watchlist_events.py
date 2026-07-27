"""
watchlist_events.py — watchlist 全池每日事件扫描（发现型提醒，非交易信号）

背景（2026-07-26）：
  watchlist 中大量个股四策略均不达标，没有常驻信号路由；周频因子选股又太慢。
  本脚本每个交易日收盘后对全部 watchlist 标的做一次事件检测，把"今天发生了
  值得看一眼的事"推送 Telegram——它只做发现，不给 TP/SL，不宣称任何胜率。

事件类型：
  🚀 52周新高突破：close > 前252日最高价（动量事件，Breakout 策略的原始触发）
  📈 20日新高 + 放量：close > 前20日最高 且 成交量 >= 2× 20日均量
  ⚡ 异动：单日涨跌幅 >= ±5% 且 成交量 >= 2× 20日均量

数据：yfinance 批量下载（1年日线），不依赖 IB。
用法：
  python watchlist_events.py             # 控制台输出
  python watchlist_events.py --telegram  # 同时推送 Telegram
"""

import argparse
import os
import warnings

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from universes import get_universe

warnings.filterwarnings("ignore")
load_dotenv()

VOL_SURGE = 2.0
MOVE_PCT = 5.0
CHUNK = 50


def tg_send(msg: str) -> None:
    token, chat = os.getenv("TG_TOKEN", ""), os.getenv("TG_CHAT_ID", "")
    if not token or not chat:
        print("[Telegram] 未配置，跳过推送")
        return
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                               data=data, timeout=15)
        print("[Telegram] 推送成功")
    except Exception as exc:
        print(f"[Telegram] 推送失败: {exc}")


def scan() -> list[str]:
    tickers, _, _ = get_universe("watchlist")
    events: list[tuple[float, str]] = []

    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        try:
            raw = yf.download(chunk, period="1y", interval="1d", auto_adjust=True,
                              progress=False, group_by="ticker", threads=True)
        except Exception:
            continue
        for sym in chunk:
            try:
                df = raw[sym].copy() if len(chunk) > 1 else raw.copy()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                if len(df) < 60:
                    continue
                close, high, vol = df["Close"], df["High"], df["Volume"]
                last, prev = float(close.iloc[-1]), float(close.iloc[-2])
                move = (last / prev - 1) * 100
                vol_avg = float(vol.iloc[-21:-1].mean())
                vol_ratio = float(vol.iloc[-1]) / vol_avg if vol_avg > 0 else 0

                hi252 = float(high.iloc[:-1].tail(252).max())
                hi20 = float(high.iloc[:-1].tail(20).max())

                if last > hi252 and len(df) >= 200:
                    events.append((abs(move) + 10,  # 52W突破排最前
                                   f"🚀 {sym} 突破52周新高  ${last:.2f} ({move:+.1f}%)  量比{vol_ratio:.1f}x"))
                elif last > hi20 and vol_ratio >= VOL_SURGE:
                    events.append((abs(move) + 5,
                                   f"📈 {sym} 20日新高+放量  ${last:.2f} ({move:+.1f}%)  量比{vol_ratio:.1f}x"))
                elif abs(move) >= MOVE_PCT and vol_ratio >= VOL_SURGE:
                    events.append((abs(move),
                                   f"⚡ {sym} 异动  ${last:.2f} ({move:+.1f}%)  量比{vol_ratio:.1f}x"))
            except Exception:
                continue

    events.sort(key=lambda x: -x[0])
    return [text for _, text in events]


def main() -> None:
    parser = argparse.ArgumentParser(description="watchlist 每日事件扫描")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--max", type=int, default=20, help="最多显示条数")
    args = parser.parse_args()

    lines = scan()
    if not lines:
        print("今日无事件")
        return
    shown = lines[:args.max]
    body = "\n".join(shown)
    extra = f"\n（另有 {len(lines) - len(shown)} 条未显示）" if len(lines) > len(shown) else ""
    msg = (f"👀 Watchlist 事件雷达（{len(lines)} 条）\n{body}{extra}\n"
           f"—— 发现型提醒：未经过策略验证，无 TP/SL，仅提示值得研究")
    print(msg)
    if args.telegram:
        tg_send(msg)


if __name__ == "__main__":
    main()

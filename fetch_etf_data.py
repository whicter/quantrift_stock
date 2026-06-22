"""
fetch_etf_data.py — 通过 IB Gateway 拉取 ETF 日线数据

必须在 Mac Studio 上运行（IB Gateway 只在本机可访问）：
  /opt/homebrew/bin/python3.11 fetch_etf_data.py
  /opt/homebrew/bin/python3.11 fetch_etf_data.py --symbol XLK
  /opt/homebrew/bin/python3.11 fetch_etf_data.py --port 4002   # 模拟盘测试

IB pacing 限制：每次请求后等 6 秒，安全起见。
数据保存到 data/{SYMBOL}_1d.csv（ADJUSTED_LAST，已还权）。

ETF 列表与 etf_scanner.py 中的 ETF_GROUPS 保持一致。
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

try:
    from ib_insync import IB, Index, Stock, util
except ImportError:
    sys.exit("请安装 ib_insync：pip install ib_insync")

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
DATA_DIR.mkdir(exist_ok=True)

# ── ETF 列表（与 etf_scanner.py 保持一致）───────────────────────────────────

ETF_GROUPS = {
    "大板块":    ["XLK", "XLC", "XLY", "XLP", "XLV", "XLF", "XLI", "XLE", "XLB", "XLU", "XLRE"],
    "科技/AI":   ["IGV", "CIBR", "HACK", "SKYY", "CLOU", "BOTZ", "ARTY", "AIQ"],
    "半导体":    ["SMH", "SOXX", "XSD"],
    "金融细分":  ["KBE", "KRE", "KIE"],
    "医疗/生技": ["XBI", "IBB", "IHI"],
    "国防/运输": ["ITA", "XAR", "IYT"],
    "消费/住宅": ["XHB", "ITB", "XRT"],
    "能源/资源": ["XOP", "ICLN", "TAN", "GDX", "GDXJ"],
    "房地产":    ["VNQ", "IYR", "SRVR", "DTCR"],
}

ALL_ETFS    = [sym for syms in ETF_GROUPS.values() for sym in syms]
BENCHMARKS  = ["SPY", "QQQ"]   # 基准（扫描器计算 RS 用）
ALL_SYMBOLS = list(dict.fromkeys(ALL_ETFS + BENCHMARKS))  # 去重保序

PACING_SLEEP = 6   # 每次 IB 请求后等待秒数


# ── IB 数据拉取 ──────────────────────────────────────────────────────────────

def fetch_vix(ib: IB) -> pd.DataFrame | None:
    """拉取 VIX 日线数据（IB Index 合约），保存到 data/VIX_1d.csv。"""
    contract = Index("VIX", "CBOE", "USD")
    try:
        ib.qualifyContracts(contract)
    except Exception as e:
        print(f" ❌ VIX qualifyContracts 失败: {e}")
        return None

    print("  [VIX] 请求中...", end="", flush=True)
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="2 Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
        )
    except Exception as e:
        print(f" ❌ {e}")
        return None
    finally:
        time.sleep(PACING_SLEEP)

    if not bars:
        print(" ❌ 无数据")
        return None

    df = util.df(bars)[["date", "open", "high", "low", "close", "volume"]].copy()
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_bars(ib: IB, symbol: str) -> pd.DataFrame | None:
    contract = Stock(symbol, "SMART", "USD")
    try:
        ib.qualifyContracts(contract)
    except Exception as e:
        print(f" ❌ qualifyContracts 失败: {e}")
        return None

    print(f"  [1d] 请求中...", end="", flush=True)
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="2 Y",          # 2 年日线，足够 200MA
            barSizeSetting="1 day",
            whatToShow="ADJUSTED_LAST",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
        )
    except Exception as e:
        print(f" ❌ reqHistoricalData: {e}")
        return None
    finally:
        time.sleep(PACING_SLEEP)

    if not bars:
        print(" ❌ 无数据")
        return None

    df = util.df(bars)[["date", "open", "high", "low", "close", "volume"]].copy()
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_symbol(ib: IB, symbol: str):
    out_path = DATA_DIR / f"{symbol}_1d.csv"
    print(f"\n{symbol}", end=" ")
    df = fetch_bars(ib, symbol)
    if df is None or df.empty:
        return
    df.to_csv(out_path)
    print(f" ✅ {len(df)} 行 → {out_path}")


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="从 IB 拉取 ETF 日线数据")
    parser.add_argument("--port",   type=int, default=4001,
                        help="IB Gateway 端口（默认 4001 实盘）")
    parser.add_argument("--symbol", help="只下载单个 ETF，如 XLK")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else ALL_SYMBOLS

    ib = IB()
    print(f"连接 IB Gateway 127.0.0.1:{args.port} clientId=3 ...")
    ib.connect("127.0.0.1", args.port, clientId=3)
    print(f"✅ 已连接\n")
    print(f"下载 {len(symbols)} 个 ETF 日线数据（每次间隔 {PACING_SLEEP}s，约 {len(symbols)*PACING_SLEEP//60+1} 分钟）")

    try:
        # VIX（单独处理，Index 合约）
        if not args.symbol or args.symbol.upper() == "VIX":
            print("\nVIX", end=" ")
            vix_df = fetch_vix(ib)
            if vix_df is not None and not vix_df.empty:
                out = DATA_DIR / "VIX_1d.csv"
                vix_df.to_csv(out)
                print(f" ✅ {len(vix_df)} 行 → {out}")

        # 只请求 VIX 时跳过 ETF 列表
        if args.symbol and args.symbol.upper() == "VIX":
            symbols = []

        for sym in symbols:
            fetch_symbol(ib, sym)
    except KeyboardInterrupt:
        print("\n⛔ 用户中断")
    finally:
        ib.disconnect()
        print(f"\n✅ 完成，数据保存在 {DATA_DIR}/")


if __name__ == "__main__":
    main()

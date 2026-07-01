"""
fetch_ib_data.py — 通过 IB Gateway 拉取历史 bar 数据

必须在 Mac Studio 上运行（IB Gateway 只在本机可访问）：
  /opt/homebrew/bin/python3.11 fetch_ib_data.py
  /opt/homebrew/bin/python3.11 fetch_ib_data.py --symbol NVDA
  /opt/homebrew/bin/python3.11 fetch_ib_data.py --tf 1d

IB pacing 限制：
  - 同一合约同参数请求：间隔 ≥ 15s
  - 所有请求：每 10 分钟不超过 60 次
  - 脚本在每次请求后固定等 6s，安全起见

数据保存到 data/{SYMBOL}_{TF}.csv（ADJUSTED_LAST，已还权）
4h 由 1h 重采样生成。
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

try:
    from ib_insync import IB, Stock, util
except ImportError:
    sys.exit("请安装 ib_insync：pip install ib_insync")

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
DATA_DIR.mkdir(exist_ok=True)

ALL_SYMBOLS = (
    cfg["symbols"].get("momentum",  [])
    + cfg["symbols"].get("high_vol", [])
    + cfg["symbols"].get("storage",  [])
    + cfg["symbols"].get("mega_cap", [])
    + cfg["symbols"].get("watch",    [])
    + cfg["symbols"].get("pending",  [])
    + cfg["symbols"].get("sector_etf", [])
    + cfg["symbols"].get("broad_etf",  [])
)

from universes import get_universe  # noqa: E402

# IB 参数
IB_BAR_SIZE = {"1h": "1 hour", "1d": "1 day"}
IB_DURATION  = {"1h": "2 Y",   "1d": "10 Y"}
PACING_SLEEP = 6  # 每次请求后等待秒数


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    df = df_1h.copy()
    df.index = pd.to_datetime(df.index)
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    return df.resample("4h", closed="left", label="left").agg(agg).dropna()


def fetch_bars(ib: IB, symbol: str, tf: str) -> pd.DataFrame | None:
    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)

    print(f"  [{tf}] 请求中...", end="", flush=True)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr=IB_DURATION[tf],
        barSizeSetting=IB_BAR_SIZE[tf],
        whatToShow="ADJUSTED_LAST",
        useRTH=True,
        formatDate=1,
        keepUpToDate=False,
    )
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


def fetch_symbol(ib: IB, symbol: str, tfs: list[str]):
    print(f"\n{'─'*40}")
    print(f"  {symbol}")
    print(f"{'─'*40}")

    df_1h = None

    for tf in tfs:
        out_path = DATA_DIR / f"{symbol}_{tf}.csv"

        if tf == "4h":
            # 4h 由 1h 重采样，1h 数据可能已经 fetch 过
            if df_1h is None:
                df_1h = fetch_bars(ib, symbol, "1h")
            if df_1h is None or df_1h.empty:
                print(f"  [4h] ❌ 无 1h 数据，跳过")
                continue
            df = resample_4h(df_1h)
            print(f"  [4h] ✅ {len(df)} 行（由 1h 重采样）→ {out_path}")
            df.to_csv(out_path)
            continue

        df = fetch_bars(ib, symbol, tf)
        if df is None or df.empty:
            continue

        if tf == "1h":
            df_1h = df  # 保留供 4h 重采样用

        df.to_csv(out_path)
        print(f" ✅ {len(df)} 行  →  {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",     type=int, default=4001)
    parser.add_argument("--symbol",   help="单标的，如 NVDA")
    parser.add_argument("--tf",       help="单周期：1h / 4h / 1d")
    parser.add_argument("--universe", choices=["dow30", "ndx100", "sp500", "all"],
                        help="指数成分股批量下载（仅 1d，用于 screener）")
    args = parser.parse_args()

    if args.universe:
        # screener 用途：仅下载日线，不需要 1h/4h
        tickers, benchmark, label = get_universe(args.universe)
        # 加入基准 ETF（screener 需要）
        symbols = sorted(set(tickers + [benchmark]))
        tfs     = ["1d"]
        print(f"[universe={args.universe}] {label}：{len(symbols)} 个标的（含基准 {benchmark}）")
        print(f"预计耗时约 {len(symbols) * PACING_SLEEP // 60} 分钟（IB pacing {PACING_SLEEP}s/请求）")
    elif args.symbol:
        symbols = [args.symbol.upper()]
        tfs     = [args.tf] if args.tf else ["1d", "1h", "4h"]
    else:
        symbols = ALL_SYMBOLS
        tfs     = [args.tf] if args.tf else ["1d", "1h", "4h"]

    ib = IB()
    print(f"连接 IB Gateway 127.0.0.1:{args.port} clientId=3 ...")
    ib.connect("127.0.0.1", args.port, clientId=3)
    print("✅ 已连接\n")
    print(f"下载 {len(symbols)} 个标的 × {tfs}（每次请求间隔 {PACING_SLEEP}s）")

    try:
        for sym in symbols:
            fetch_symbol(ib, sym, tfs)
    except KeyboardInterrupt:
        print("\n⛔ 用户中断")
    finally:
        ib.disconnect()
        print("\n已断开 IB 连接")
        print(f"数据保存在 {DATA_DIR}/")


if __name__ == "__main__":
    main()

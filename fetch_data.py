"""
fetch_data.py — 下载所有标的历史数据（via yfinance）

用法：
  python fetch_data.py                    # 下载全部
  python fetch_data.py --symbol NVDA      # 单标的
  python fetch_data.py --tf 1h            # 单周期

4h 数据由 1h 重采样生成（yfinance 不直接提供 4h）。
数据保存到 data/{SYMBOL}_{TF}.csv
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

try:
    import yfinance as yf
except ImportError:
    sys.exit("请安装 yfinance：pip install yfinance")

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
DATA_DIR.mkdir(exist_ok=True)
SOURCE_MANIFEST = DATA_DIR / ".data_sources.json"
REQUEST_TIMEOUT = 20

ALL_SYMBOLS = (
    cfg["symbols"].get("momentum", [])
    + cfg["symbols"].get("high_vol", [])
    + cfg["symbols"].get("storage", [])
    + cfg["symbols"].get("mega_cap", [])
    + cfg["symbols"].get("watch", [])
    + cfg["symbols"].get("watch_candidates", [])
    + cfg["symbols"].get("pending", [])
    + cfg["symbols"].get("pending_high_vol", [])
    + cfg["symbols"].get("sector_etf", [])
    + cfg["symbols"].get("broad_etf", [])
)


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """将 1h OHLCV 重采样为 4h。"""
    df = df_1h.copy()
    df.index = pd.to_datetime(df.index)
    agg = {
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }
    df4 = df.resample("4h", closed="left", label="left").agg(agg).dropna()
    return df4


def download_1d(symbol: str, start: str) -> pd.DataFrame:
    try:
        df = yf.download(symbol, start=start, interval="1d", auto_adjust=True,
                         progress=False, timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        print(f"  [1d] ❌ yfinance 请求失败：{exc}")
        return pd.DataFrame()
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    df.index.name = "Date"
    return df


def download_1h(symbol: str, start: str) -> pd.DataFrame:
    # yfinance 1h 最多 730 天
    try:
        df = yf.download(symbol, period="729d", interval="1h", auto_adjust=True,
                         progress=False, timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        print(f"  [1h] ❌ yfinance 请求失败：{exc}")
        return pd.DataFrame()
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    df.index.name = "Date"
    # 去掉时区信息（backtesting.py 兼容）
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def merge_bars(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return incoming.sort_index()
    merged = pd.concat([existing, incoming])
    merged.index = pd.to_datetime(merged.index)
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def save_bars(path: Path, frame: pd.DataFrame, symbol: str, tf: str, merge: bool) -> pd.DataFrame:
    existing = None
    if merge and path.exists():
        existing = pd.read_csv(path, index_col=0, parse_dates=True)
        existing.columns = [column.capitalize() for column in existing.columns]
    output = merge_bars(existing, frame) if merge else frame
    temporary = path.with_suffix(".tmp")
    output.to_csv(temporary)
    os.replace(temporary, path)
    try:
        manifest = json.loads(SOURCE_MANIFEST.read_text()) if SOURCE_MANIFEST.exists() else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    manifest[f"{symbol}|{tf}"] = {
        "source": "yfinance",
        "fetched_at": pd.Timestamp.now(tz="America/Los_Angeles").isoformat(),
        "bars": len(output),
        "path": str(path),
    }
    temporary_manifest = SOURCE_MANIFEST.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(temporary_manifest, SOURCE_MANIFEST)
    return output


def fetch_symbol(symbol: str, tfs: list[str], merge: bool = False):
    print(f"\n{'─'*40}")
    print(f"  {symbol}")
    print(f"{'─'*40}")

    df_1h = None

    for tf in tfs:
        out_path = DATA_DIR / f"{symbol}_{tf}.csv"

        if tf == "1d":
            df = download_1d(symbol, cfg["data"]["start_1d"])
        elif tf == "1h":
            df = download_1h(symbol, cfg["data"]["start_1h"])
            df_1h = df  # 保留供 4h 重采样用
        elif tf == "4h":
            if df_1h is None:
                df_1h = download_1h(symbol, cfg["data"]["start_4h"])
            df = resample_4h(df_1h) if not df_1h.empty else pd.DataFrame()
        else:
            print(f"  [{tf}] 未知周期，跳过")
            continue

        if df.empty:
            print(f"  [{tf}] ❌ 无数据（可能上市时间不足）")
            time.sleep(2)
            continue

        saved = save_bars(out_path, df, symbol, tf, merge)
        print(f"  [{tf}] ✅ {len(saved)} 行  →  {out_path}")
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="单标的，如 NVDA")
    parser.add_argument("--tf", help="单周期，如 1h / 4h / 1d")
    parser.add_argument("--merge", action="store_true", help="与已有 CSV 合并，保留旧历史并覆盖重复时间戳")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else list(dict.fromkeys(ALL_SYMBOLS))
    tfs = [args.tf] if args.tf else ["1d", "1h", "4h"]

    print(f"下载 {len(symbols)} 个标的 × {tfs} 周期")
    for sym in symbols:
        fetch_symbol(sym, tfs, merge=args.merge)

    print("\n✅ 全部完成")


if __name__ == "__main__":
    main()

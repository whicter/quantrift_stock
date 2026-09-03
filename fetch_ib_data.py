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
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

try:
    from ib_insync import IB, Stock, util
except ImportError:
    IB = Stock = util = None

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])
DATA_DIR.mkdir(exist_ok=True)
SOURCE_MANIFEST = DATA_DIR / ".data_sources.json"

ALL_SYMBOLS = (
    cfg["symbols"].get("momentum",         [])
    + cfg["symbols"].get("high_vol",       [])
    + cfg["symbols"].get("storage",        [])
    + cfg["symbols"].get("mega_cap",       [])
    + cfg["symbols"].get("watch",          [])
    + cfg["symbols"].get("watch_candidates", [])
    + cfg["symbols"].get("pending",        [])
    + cfg["symbols"].get("pending_high_vol", [])
    + cfg["symbols"].get("sector_etf",     [])
    + cfg["symbols"].get("broad_etf",      [])
    # 2026-07-27 补：watchlist 批次接入的标的此前不在补拉范围内，
    # 夜间 IB 刷新（stock-nightly-ib-refresh）必须覆盖全部实盘标的
    + cfg["symbols"].get("watchlist_2026_07", [])
)

from universes import get_universe  # noqa: E402

# IB 参数
IB_BAR_SIZE = {"1h": "1 hour", "1d": "1 day"}
IB_DURATION  = {"1h": "2 Y",   "1d": "10 Y"}
PACING_SLEEP = 6  # 每次请求后等待秒数
REQUEST_TIMEOUT = 45  # Gateway 无响应时跳过，不能阻塞整个补拉批次


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    df = df_1h.copy()
    df.index = pd.to_datetime(df.index)
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    return df.resample("4h", closed="left", label="left").agg(agg).dropna()


def merge_bars(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Keep prior history and prefer newly fetched bars at duplicate timestamps."""
    if existing is None or existing.empty:
        return incoming.sort_index()
    merged = pd.concat([existing, incoming])
    merged.index = pd.to_datetime(merged.index)
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def _load_existing(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.columns = [column.capitalize() for column in frame.columns]
        return frame
    except Exception:
        return None


def _record_source(path: Path, symbol: str, tf: str, bars: int):
    try:
        manifest = json.loads(SOURCE_MANIFEST.read_text()) if SOURCE_MANIFEST.exists() else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    manifest[f"{symbol}|{tf}"] = {
        "source": "ib",
        "fetched_at": pd.Timestamp.now(tz="America/Los_Angeles").isoformat(),
        "bars": bars,
        "path": str(path),
    }
    temp = SOURCE_MANIFEST.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    os.replace(temp, SOURCE_MANIFEST)


def save_bars(path: Path, df: pd.DataFrame, symbol: str, tf: str, merge: bool):
    output = merge_bars(_load_existing(path), df) if merge else df
    temp = path.with_suffix(".tmp")
    output.to_csv(temp)
    os.replace(temp, path)
    _record_source(path, symbol, tf, len(output))
    return output


def fetch_bars(ib: IB, symbol: str, tf: str) -> pd.DataFrame | None:
    print(f"  [{tf}] 请求中...", end="", flush=True)
    try:
        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=IB_DURATION[tf],
            barSizeSetting=IB_BAR_SIZE[tf],
            whatToShow="ADJUSTED_LAST",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        print(f" ❌ 请求失败：{exc}")
        return None
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


def fetch_symbol(ib: IB, symbol: str, tfs: list[str], merge: bool = False):
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
            saved = save_bars(out_path, df, symbol, tf, merge)
            print(f"  [4h] ✅ {len(saved)} 行（由 1h 重采样）→ {out_path}")
            continue

        df = fetch_bars(ib, symbol, tf)
        if df is None or df.empty:
            continue

        if tf == "1h":
            df_1h = df  # 保留供 4h 重采样用

        saved = save_bars(out_path, df, symbol, tf, merge)
        print(f" ✅ {len(saved)} 行  →  {out_path}")


def _alert_failure(failed: list[str], total: int) -> None:
    """拉取失败率过高时推 Telegram。只读环境变量，失败静默，绝不影响数据流程。"""
    import os
    import urllib.parse
    import urllib.request
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    token, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT_ID")
    if not token or not chat:
        return
    msg = (f"⚠️ IB 数据保鲜异常：{len(failed)}/{total} 个标的未更新\n"
           f"（常见原因：Gateway 中途掉线，日志里成片的「Not connected」）\n"
           f"受影响：{', '.join(failed[:20])}{' ...' if len(failed) > 20 else ''}\n"
           f"本地数据是引擎补缺兜底与复盘的价格来源，陈旧会同时污染信号和复盘。")
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode(),
            timeout=15)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",     type=int, default=4001)
    parser.add_argument("--clientId", type=int, default=2)
    parser.add_argument("--symbol",   help="单标的，如 NVDA")
    parser.add_argument("--tf",       help="单周期：1h / 4h / 1d")
    parser.add_argument("--universe", choices=["dow30", "ndx100", "sp500", "russell2000", "all"],
                        help="指数成分股批量下载（仅 1d，用于 screener）")
    parser.add_argument("--merge", action="store_true",
                        help="与已有 CSV 合并，保留旧历史且以新 IB bar 覆盖重复时间戳")
    args = parser.parse_args()

    if IB is None:
        raise SystemExit("请安装 ib_insync：pip install ib_insync")

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
    # qualifyContracts() also performs a Gateway request; apply the same bound
    # as historical bars so an unavailable API cannot stall the entire batch.
    ib.RequestTimeout = REQUEST_TIMEOUT
    print(f"连接 IB Gateway 127.0.0.1:{args.port} clientId={args.clientId} ...")
    ib.connect("127.0.0.1", args.port, clientId=args.clientId)
    print("✅ 已连接\n")
    print(f"下载 {len(symbols)} 个标的 × {tfs}（每次请求间隔 {PACING_SLEEP}s）")

    # 断连自查。2026-09-03 发现：IB 连接会在批量拉取中途掉线，之后每个标的都
    # 打印「请求失败：Not connected」但脚本照常跑完、照常退出 0，pm2 也认为
    # 成功——结果 108 个已路由标的里有 24 个的本地日线停在 8/21，整整 13 天
    # 没人发现。本地数据是 alert_engine 的补缺与兜底数据源，也是 review_core
    # 复盘的唯一价格来源，陈旧了会同时污染信号和复盘。静默失败必须变成告警。
    failed: list[str] = []
    try:
        for sym in symbols:
            before = {tf: (DATA_DIR / f"{sym}_{tf}.csv").stat().st_mtime
                      if (DATA_DIR / f"{sym}_{tf}.csv").exists() else 0 for tf in tfs}
            fetch_symbol(ib, sym, tfs, merge=args.merge)
            after = {tf: (DATA_DIR / f"{sym}_{tf}.csv").stat().st_mtime
                     if (DATA_DIR / f"{sym}_{tf}.csv").exists() else 0 for tf in tfs}
            if all(after[tf] <= before[tf] for tf in tfs):
                failed.append(sym)
    except KeyboardInterrupt:
        print("\n⛔ 用户中断")
    finally:
        ib.disconnect()
        print("\n已断开 IB 连接")
        print(f"数据保存在 {DATA_DIR}/")
        if symbols:
            rate = len(failed) / len(symbols)
            print(f"\n本轮 {len(symbols) - len(failed)}/{len(symbols)} 个标的已更新"
                  + (f"，失败 {len(failed)}：{', '.join(failed[:15])}"
                     f"{' ...' if len(failed) > 15 else ''}" if failed else ""))
            if rate > 0.1:
                _alert_failure(failed, len(symbols))


if __name__ == "__main__":
    main()

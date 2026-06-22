"""
pead_backtest.py — Post-Earnings Announcement Drift (PEAD) 回测

策略逻辑：
  - 财报公布后（下一个交易日开盘），若 EPS 超预期（beat）→ 买入持有 N 天
  - 若 EPS 不及预期（miss）→ 可做空持有 N 天（可选）
  - 仅在 Market Regime Score ≥ 阈值时开多（空头不限制）

数据需求：
  - earnings_df: 包含 [symbol, date, eps_actual, eps_estimate] 的 DataFrame
    date = 财报公布日（非交易日往后推到下一个交易日）
  - 价格数据：各标的日线 OHLCV（已存在 data/）

数据获取方法（按优先级）：
  1. yfinance ticker.earnings_history → 免费，有 EPS actual/estimate，限速较严
  2. EODHD API（eodhd.com）→ 付费，$20/月，财报数据质量更高
  3. 手动 CSV 导入（从 Zacks/Seeking Alpha 下载）

用法：
  python pead_backtest.py --fetch-earnings      # 从 yfinance 抓取财报数据
  python pead_backtest.py                       # 用已有 data/earnings.csv 回测
  python pead_backtest.py --hold 5              # 持有 5 个交易日（默认 3）
  python pead_backtest.py --no-short            # 只做多（默认允许做空 miss 标的）
"""

import argparse
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR     = Path(cfg["data"]["dir"])
EARNINGS_CSV = DATA_DIR / "earnings.csv"

# 目标标的（不含 AMZN/TSLA，这两个个股逻辑太特殊）
PEAD_SYMBOLS = ["NVDA", "MU", "MRVL", "SNDK", "STX",
                "MSFT", "GOOGL", "META", "AAPL"]

INITIAL_CASH = 100_000.0
COMMISSION   = 0.001


# ── 数据获取 ────────────────────────────────────────────────────────────────

def fetch_earnings_alphavantage(symbols: list[str], api_key: str,
                                sleep_sec: float = 13.0) -> pd.DataFrame:
    """
    从 Alpha Vantage EARNINGS 端点抓取历史财报数据（免费 tier）。
    免费限额：25 次/天，5 次/分钟 → 每次请求间隔 13 秒
    返回列：symbol, date(报告日), eps_actual, eps_estimate, surprise_pct(小数格式)
    注：surprise_pct 以小数存储（0.05 = 5%），与 yfinance 版本一致
    """
    import json
    import urllib.request

    rows = []
    for sym in symbols:
        url = (f"https://www.alphavantage.co/query"
               f"?function=EARNINGS&symbol={sym}&apikey={api_key}")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())

            if "quarterlyEarnings" not in data:
                note = data.get("Note", data.get("Information", "未知原因"))
                print(f"  {sym}: 无数据（{note}）")
                continue

            count_before = len(rows)
            for q in data["quarterlyEarnings"]:
                try:
                    eps_a = float(q["reportedEPS"])
                    eps_e = float(q["estimatedEPS"])
                    surp  = float(q["surprisePercentage"]) / 100.0  # 转小数格式
                    date  = pd.Timestamp(q["reportedDate"]).normalize()
                    rows.append({
                        "symbol":       sym,
                        "date":         date,
                        "eps_actual":   eps_a,
                        "eps_estimate": eps_e,
                        "surprise_pct": surp,
                    })
                except (ValueError, KeyError):
                    continue

            print(f"  {sym}: {len(rows) - count_before} 条")
        except Exception as e:
            print(f"  {sym}: 获取失败 ({e})")

        if sym != symbols[-1]:
            time.sleep(sleep_sec)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["symbol", "date"])


def fetch_earnings_yfinance(symbols: list[str], sleep_sec: float = 2.0) -> pd.DataFrame:
    """
    从 yfinance 抓取历史财报数据。
    返回列：symbol, date(UTC), eps_actual, eps_estimate, surprise_pct
    注意：yfinance 有频率限制，需要间隔 sleep_sec 秒
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("请安装 yfinance：pip install yfinance")

    rows = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            hist = t.earnings_history
            if hist is None or hist.empty:
                print(f"  {sym}: 无财报数据")
                continue
            # earnings_history 列名：epsActual, epsEstimate, epsDifference, surprisePercent
            for idx, row in hist.iterrows():
                eps_a = float(row.get("epsActual",   np.nan))
                eps_e = float(row.get("epsEstimate", np.nan))
                if np.isnan(eps_a) or np.isnan(eps_e):
                    continue
                rows.append({
                    "symbol":       sym,
                    "date":         pd.Timestamp(idx).normalize(),
                    "eps_actual":   eps_a,
                    "eps_estimate": eps_e,
                    "surprise_pct": float(row.get("surprisePercent", (eps_a - eps_e) / abs(eps_e) * 100
                                                  if eps_e != 0 else 0)),
                })
            print(f"  {sym}: {len(rows)} 条（截至当前）")
        except Exception as e:
            print(f"  {sym}: 获取失败 ({e})")
        time.sleep(sleep_sec)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["symbol", "date"])


# ── 核心回测 ────────────────────────────────────────────────────────────────

def load_daily(symbol: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_1d.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    df.columns = [c.capitalize() for c in df.columns]
    return df


def next_trading_day(date: pd.Timestamp, calendar: pd.DatetimeIndex) -> pd.Timestamp | None:
    """返回 date 当天或其后的第一个交易日。"""
    future = calendar[calendar > date]
    return future[0] if len(future) > 0 else None


def run_pead(earnings_df: pd.DataFrame,
             hold_days: int = 3,
             allow_short: bool = True,
             beat_thresh: float = 0.0,    # EPS 超预期 % 阈值（正数=必须 beat 多少才进）
             miss_thresh: float = 0.0,    # EPS 不及预期 % 阈值（负数）
             ) -> pd.DataFrame:
    """
    PEAD 回测主函数。
    每次财报：
      - EPS beat (surprise_pct > beat_thresh)  → 下一交易日开盘买入，持有 hold_days 天
      - EPS miss (surprise_pct < miss_thresh)  → 下一交易日开盘卖空（可选）
    返回每笔交易记录。
    """
    if earnings_df.empty:
        print("⚠ 无财报数据，跳过回测")
        return pd.DataFrame()

    all_trades = []

    for sym in earnings_df["symbol"].unique():
        df_price = load_daily(sym)
        if df_price is None or len(df_price) < 10:
            continue

        calendar = df_price.index
        sym_earn = earnings_df[earnings_df["symbol"] == sym].copy()

        for _, earn_row in sym_earn.iterrows():
            earn_date = earn_row["date"]
            surp      = earn_row["surprise_pct"]

            # 确定方向
            if surp > beat_thresh:
                direction = 1     # 做多
            elif allow_short and surp < miss_thresh:
                direction = -1    # 做空
            else:
                continue

            # 入场：财报日后第一个交易日开盘
            entry_date = next_trading_day(earn_date, calendar)
            if entry_date is None:
                continue

            # 出场：持有 hold_days 个交易日后
            entry_idx = calendar.get_loc(entry_date)
            exit_idx  = entry_idx + hold_days
            if exit_idx >= len(calendar):
                continue

            exit_date  = calendar[exit_idx]
            entry_price = float(df_price.loc[entry_date, "Open"])
            exit_price  = float(df_price.loc[exit_date, "Close"])

            if entry_price <= 0:
                continue

            raw_ret = (exit_price - entry_price) / entry_price * direction
            net_ret = raw_ret - 2 * COMMISSION  # 双向成本

            all_trades.append({
                "symbol":    sym,
                "earn_date": earn_date,
                "direction": "多" if direction == 1 else "空",
                "surprise":  round(surp, 2),
                "entry":     entry_date,
                "exit":      exit_date,
                "entry_px":  round(entry_price, 2),
                "exit_px":   round(exit_price, 2),
                "ret_pct":   round(net_ret * 100, 2),
                "win":       net_ret > 0,
            })

    return pd.DataFrame(all_trades)


def calc_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    n       = len(trades)
    wr      = trades["win"].mean() * 100
    avg_ret = trades["ret_pct"].mean()
    wins    = trades[trades["win"]]["ret_pct"]
    losses  = trades[~trades["win"]]["ret_pct"]
    avg_w   = wins.mean()   if len(wins)   else 0
    avg_l   = losses.mean() if len(losses) else 0
    rr      = abs(avg_w / avg_l) if avg_l != 0 else float("inf")
    total   = trades["ret_pct"].sum()
    return {
        "n":      n,
        "wr":     round(wr, 1),
        "avg_ret":round(avg_ret, 2),
        "avg_w":  round(avg_w, 2),
        "avg_l":  round(avg_l, 2),
        "rr":     round(rr, 2),
        "total":  round(total, 1),
    }


# ── 入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-earnings", action="store_true", dest="fetch",
                        help="从 yfinance 抓取财报数据")
    parser.add_argument("--av-key", dest="av_key", default="",
                        help="Alpha Vantage API Key，提供后自动用 AV 抓取（5年历史，优先于 yfinance）")
    parser.add_argument("--hold",     type=int,   default=3)
    parser.add_argument("--beat",     type=float, default=0.02,
                        help="EPS beat 阈值，小数格式（默认 0.02 = 2%%）")
    parser.add_argument("--miss",     type=float, default=-0.02,
                        help="EPS miss 阈值，小数格式（默认 -0.02 = -2%%）")
    parser.add_argument("--no-short", action="store_true", dest="no_short")
    parser.add_argument("--symbol",   help="只测试单只标的")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else PEAD_SYMBOLS

    if args.fetch or args.av_key:
        if args.av_key:
            print(f"Alpha Vantage 抓取 {len(symbols)} 只标的（每只间隔 13s，约 {len(symbols)*13//60+1} 分钟）...")
            df = fetch_earnings_alphavantage(symbols, args.av_key)
        else:
            print(f"yfinance 抓取 {len(symbols)} 只标的（每只间隔 2s）...")
            df = fetch_earnings_yfinance(symbols)
        if df.empty:
            print("⚠ 未获取到任何数据")
            return
        df.to_csv(EARNINGS_CSV, index=False)
        print(f"✅ 已保存 {len(df)} 条到 {EARNINGS_CSV}")
        return

    if not EARNINGS_CSV.exists():
        print("⚠ 无财报数据，请先运行：")
        print("  python pead_backtest.py --av-key YOUR_KEY   # 推荐，5年历史")
        print("  python pead_backtest.py --fetch-earnings    # yfinance，仅4季度")
        return

    earnings_df = pd.read_csv(EARNINGS_CSV, parse_dates=["date"])
    if args.symbol:
        earnings_df = earnings_df[earnings_df["symbol"] == args.symbol.upper()]
    else:
        earnings_df = earnings_df[earnings_df["symbol"].isin(symbols)]

    print(f"财报数据：{len(earnings_df)} 条  标的：{earnings_df['symbol'].nunique()} 只")

    trades = run_pead(earnings_df,
                      hold_days=args.hold,
                      allow_short=not args.no_short,
                      beat_thresh=args.beat,
                      miss_thresh=-abs(args.miss))

    if trades.empty:
        print("无有效交易")
        return

    print(f"\n{'═'*65}")
    print(f"  PEAD 回测  hold={args.hold}d  beat>{args.beat}%  miss<{-abs(args.miss)}%")
    print(f"  {'方向':<4} {'仅多' if args.no_short else '多空'}")
    print(f"{'═'*65}")

    # 按标的汇总
    for sym in trades["symbol"].unique():
        sub = trades[trades["symbol"] == sym]
        s   = calc_stats(sub)
        if s:
            print(f"  {sym:<6}: N={s['n']:>3}  WR={s['wr']:.1f}%  "
                  f"avgRet={s['avg_ret']:.2f}%  RR={s['rr']:.2f}  total={s['total']:.1f}%")

    # 全体汇总
    s = calc_stats(trades)
    print(f"\n  全体合计：N={s['n']}  WR={s['wr']:.1f}%  "
          f"avgRet={s['avg_ret']:.2f}%  RR={s['rr']:.2f}  total={s['total']:.1f}%")

    out = Path("logs/pead_trades.csv")
    out.parent.mkdir(exist_ok=True)
    trades.to_csv(out, index=False)
    print(f"\n  交易记录已保存至 {out}")

    # 参数扫描（hold 天数）
    print(f"\n{'═'*50}")
    print("  持有天数敏感性（full sample）")
    print(f"{'═'*50}")
    print(f"  {'hold':>5} {'N':>5} {'WR%':>6} {'avgRet%':>8} {'RR':>5}")
    for h in [1, 2, 3, 5, 10]:
        t = run_pead(earnings_df, hold_days=h,
                     allow_short=not args.no_short,
                     beat_thresh=args.beat, miss_thresh=-abs(args.miss))
        if not t.empty:
            s = calc_stats(t)
            print(f"  {h:>5} {s['n']:>5} {s['wr']:>6.1f} {s['avg_ret']:>8.2f} {s['rr']:>5.2f}")


if __name__ == "__main__":
    main()

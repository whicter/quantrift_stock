"""
screener.py — NDX 100 周频因子选股初筛

5 个 WQ-style 因子（仅用 OHLCV）：
  F1  跳期动量      close[-6]/close[-66]-1  （60日收益，跳过最近5日避免反转）
  F2  相对强度      0.4×RS20 + 0.6×RS60 vs QQQ
  F3  量价背离      sign(Δvol)×(-Δclose) 20日滚动均值（Alpha#12 变体）
  F4  风险调整动量  ret_20 / std(daily_ret, 20)
  F5  52W高点接近度 close / rolling_max(252)

综合得分 = 5 因子各自 z-score 等权相加，全域排名取 Top N。

用法：
  python3.11 screener.py                  # 终端输出 Top 20
  python3.11 screener.py --top 30         # Top 30
  python3.11 screener.py --telegram       # 同时推送 Telegram
  python3.11 screener.py --top 20 --telegram
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────

TG_TOKEN   = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")


def tg_send(msg: str):
    """同步发送 Telegram（screener 单次运行，不需要非阻塞）。"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("[Telegram] 未配置 TG_TOKEN / TG_CHAT_ID，跳过推送")
        return
    try:
        import urllib.request, urllib.parse
        url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": msg}).encode()
        urllib.request.urlopen(url, data=data, timeout=15)
        print("[Telegram] 推送成功")
    except Exception as e:
        print(f"[Telegram] 推送失败: {e}")


# ── NDX 100 成分股（2025 Q4 QQQ 持仓，约 100 只）────────────────────────────

NDX100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO",
    "COST", "NFLX", "AMD", "ASML", "CSCO", "ADBE", "PEP", "QCOM", "INTC",
    "INTU", "CMCSA", "AMAT", "TXN", "HON", "AMGN", "SBUX", "ISRG", "BKNG",
    "VRTX", "MU", "LRCX", "KLAC", "SNPS", "CDNS", "ADI", "REGN", "PANW",
    "CRWD", "MELI", "MDLZ", "CTAS", "AEP", "ORLY", "FTNT", "KHC", "DXCM",
    "MNST", "CHTR", "LULU", "MRVL", "IDXX", "ROST", "PAYX", "CEG", "ODFL",
    "EXC", "BIIB", "PCAR", "FANG", "GEHC", "FAST", "CTSH", "VRSK", "KDP",
    "CSGP", "ON", "MCHP", "DLTR", "ANSS", "XEL", "GFS", "CCEP", "CDW",
    "TEAM", "DDOG", "ZS", "SPLK", "WBD", "SIRI", "ILMN", "ENPH", "ZM",
    "ALGN", "NXPI", "WBA", "CPRT", "LCID", "TTWO", "NTES", "JD", "PDD",
    "PLTR", "SNOW", "RIVN", "ABNB", "DASH", "UBER", "COIN",
]

# 去重并过滤
NDX100 = sorted(set(NDX100))
BENCHMARK = "QQQ"


# ── 数据下载 ──────────────────────────────────────────────────────────────────

def _download_one(sym: str, period: str) -> pd.DataFrame | None:
    """单个标的下载，返回标准化 OHLCV DataFrame 或 None。"""
    try:
        df = yf.Ticker(sym).history(period=period, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        # 列名统一为首字母大写
        df.columns = [c.capitalize() for c in df.columns]
        # 保留必要列
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        # 去掉时区信息（使 index 统一为 date）
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df if len(df) >= 60 else None
    except Exception:
        return None


def download_data(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    逐个下载日线 OHLCV，返回 {symbol: DataFrame}。
    顺序下载避免多线程 DNS 并发错误。
    """
    all_syms = symbols + ([BENCHMARK] if BENCHMARK not in symbols else [])
    print(f"下载 {len(all_syms)} 个标的 ({period} 日线)...")

    data: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(all_syms, 1):
        df = _download_one(sym, period)
        if df is not None:
            data[sym] = df
        if i % 20 == 0:
            print(f"  进度: {i}/{len(all_syms)}, 成功 {len(data)} 个")

    print(f"成功加载 {len(data)} 个标的（过滤掉数据不足或下载失败的）")
    return data


# ── 因子计算 ──────────────────────────────────────────────────────────────────

def zscore(s: pd.Series) -> pd.Series:
    """截面 z-score 标准化。"""
    mu, sigma = s.mean(), s.std()
    if sigma == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sigma


def compute_factors(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    对所有标的计算 F1-F5，返回 DataFrame（index=symbol，columns=F1..F5+composite）。
    """
    qqq = data.get(BENCHMARK)
    rows = []

    for sym, df in data.items():
        if sym == BENCHMARK:
            continue
        close  = df["Close"]
        volume = df["Volume"]
        n = len(close)

        try:
            # F1: 跳期动量（60d 收益，跳过最近 5 日）
            f1 = (close.iloc[-6] / close.iloc[-66] - 1) if n >= 66 else np.nan

            # F2: 相对强度 vs QQQ（0.4×RS20 + 0.6×RS60）
            if qqq is not None and len(qqq) >= 60:
                ret20_sym  = close.iloc[-1] / close.iloc[-21] - 1
                ret60_sym  = close.iloc[-1] / close.iloc[-61] - 1
                ret20_qqq  = qqq["Close"].iloc[-1] / qqq["Close"].iloc[-21] - 1
                ret60_qqq  = qqq["Close"].iloc[-1] / qqq["Close"].iloc[-61] - 1
                f2 = 0.4 * (ret20_sym - ret20_qqq) + 0.6 * (ret60_sym - ret60_qqq)
            else:
                f2 = np.nan

            # F3: 量价背离（Alpha#12 变体）—— sign(Δvol) × (-Δclose) 20日均值
            if n >= 21:
                delta_vol   = volume.diff()
                delta_close = close.diff()
                pv = (np.sign(delta_vol) * (-delta_close)).rolling(20).mean()
                f3 = pv.iloc[-1]
            else:
                f3 = np.nan

            # F4: 风险调整动量（ret_20 / std_20）
            if n >= 21:
                daily_ret = close.pct_change()
                ret_20    = close.iloc[-1] / close.iloc[-21] - 1
                std_20    = daily_ret.iloc[-20:].std()
                f4 = ret_20 / std_20 if std_20 > 0 else np.nan
            else:
                f4 = np.nan

            # F5: 接近 52 周高点（close / max_252）
            window = min(252, n)
            f5 = close.iloc[-1] / close.iloc[-window:].max() if window >= 20 else np.nan

            rows.append({
                "symbol": sym,
                "close":  round(close.iloc[-1], 2),
                "F1_mom":     f1,
                "F2_rs":      f2,
                "F3_pv_div":  f3,
                "F4_risk_adj": f4,
                "F5_hi52":    f5,
            })
        except Exception as e:
            print(f"  [跳过] {sym}: {e}")

    df_factors = pd.DataFrame(rows).set_index("symbol")

    # z-score 标准化 + 等权合成
    factor_cols = ["F1_mom", "F2_rs", "F3_pv_div", "F4_risk_adj", "F5_hi52"]
    for col in factor_cols:
        df_factors[f"z_{col}"] = zscore(df_factors[col].dropna().reindex(df_factors.index))

    z_cols = [f"z_{c}" for c in factor_cols]
    df_factors["composite"] = df_factors[z_cols].mean(axis=1)
    df_factors["rank"]      = df_factors["composite"].rank(ascending=False).astype(int)

    return df_factors.sort_values("composite", ascending=False)


# ── 输出 ──────────────────────────────────────────────────────────────────────

def format_terminal(df: pd.DataFrame, top_n: int, run_date: str) -> None:
    """终端打印 Top N 结果。"""
    print(f"\n{'─'*60}")
    print(f"  ⭐ NDX 100 周频因子选股 Top {top_n}   {run_date}")
    print(f"{'─'*60}")
    print(f"  {'#':>3}  {'标的':<6}  {'收盘':>7}  {'综合':>7}  {'动量F1':>7}  {'RS F2':>7}  {'量价F3':>7}  {'风调F4':>7}  {'52WF5':>6}")
    print(f"  {'─'*3}  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*6}")
    for i, (sym, row) in enumerate(df.head(top_n).iterrows(), 1):
        def fmt(v):
            return f"{v:+.3f}" if pd.notna(v) else "   n/a"
        print(f"  {i:>3}. {sym:<6}  ${row['close']:>6.2f}  {fmt(row['composite'])}  "
              f"{fmt(row['F1_mom'])}  {fmt(row['F2_rs'])}  {fmt(row['F3_pv_div'])}  "
              f"{fmt(row['F4_risk_adj'])}  {fmt(row['F5_hi52'])}")
    print(f"{'─'*60}\n")


def format_telegram(df: pd.DataFrame, top_n: int, run_date: str) -> str:
    """生成 Telegram 消息（最多 Top 20，避免太长）。"""
    n = min(top_n, 20)
    lines = [
        f"⭐ NDX 100 周频因子选股 Top {n}",
        f"📅 {run_date}",
        "",
    ]
    for i, (sym, row) in enumerate(df.head(n).iterrows(), 1):
        score_str = f"{row['composite']:+.2f}" if pd.notna(row["composite"]) else "n/a"
        # 简短标签
        tags = []
        if pd.notna(row["F1_mom"]) and row["F1_mom"] > 0.05:
            tags.append("动量↑")
        if pd.notna(row["F2_rs"]) and row["F2_rs"] > 0.02:
            tags.append("RS强")
        if pd.notna(row["F5_hi52"]) and row["F5_hi52"] > 0.95:
            tags.append("近高点")
        tag_str = " " + "/".join(tags) if tags else ""
        lines.append(f"  {i:>2}. {sym:<5} {score_str}{tag_str}")

    lines += [
        "",
        "因子: 60d动量 · RS/QQQ · 量价背离 · 风险调整动量 · 52W高点",
        f"数据: yfinance 1Y 日线  |  仅供参考，非交易建议",
    ]
    return "\n".join(lines)


def save_csv(df: pd.DataFrame, top_n: int, run_date: str) -> None:
    """Append Top N 结果到 data/screener_results.csv。"""
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "screener_results.csv"

    top = df.head(top_n).copy().reset_index()
    top.insert(0, "run_date", run_date)
    top.insert(1, "rank_in_run", range(1, len(top) + 1))

    if out_path.exists():
        top.to_csv(out_path, mode="a", header=False, index=False)
    else:
        top.to_csv(out_path, index=False)

    print(f"结果已追加到 {out_path}（共 {len(top)} 行）")


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NDX 100 周频因子选股初筛")
    parser.add_argument("--top",      type=int, default=20, help="输出 Top N（默认 20）")
    parser.add_argument("--telegram", action="store_true",  help="推送 Telegram")
    parser.add_argument("--no-save",  action="store_true",  help="不写 CSV")
    args = parser.parse_args()

    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n=== NDX 100 因子选股  {run_date} ===")

    data       = download_data(NDX100)
    df_factors = compute_factors(data)

    format_terminal(df_factors, args.top, run_date)

    if not args.no_save:
        save_csv(df_factors, args.top, run_date)

    if args.telegram:
        msg = format_telegram(df_factors, args.top, run_date)
        tg_send(msg)


if __name__ == "__main__":
    main()

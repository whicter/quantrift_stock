"""
screener.py — 多指数周频因子选股初筛

5 个 WQ-style 因子（仅用 OHLCV）：
  F1  跳期动量      close[-6]/close[-66]-1  （60日收益，跳过最近5日避免反转）
  F2  相对强度      0.4×RS20 + 0.6×RS60 vs 基准ETF
  F3  量价背离      sign(Δvol)×(-Δclose) 20日滚动均值（Alpha#12 变体）
  F4  风险调整动量  ret_20 / std(daily_ret, 20)
  F5  52W高点接近度 close / rolling_max(252)

数据优先级：
  1. data/{SYM}_1d.csv（IB Gateway 拉取，最准确）
  2. yfinance fallback（IB 数据缺失时使用）

综合得分 = 5 因子各自 z-score 等权相加，全域排名取 Top N。

用法：
  python3.11 screener.py                          # NDX100，Top 20
  python3.11 screener.py --universe sp500         # S&P 500
  python3.11 screener.py --universe dow30         # Dow 30
  python3.11 screener.py --universe all           # 三个指数合并
  python3.11 screener.py --top 30 --telegram      # Top 30 + Telegram

前置：先用 IB 拉数据（每周更新一次）：
  python3.11 fetch_ib_data.py --universe ndx100
  python3.11 fetch_ib_data.py --universe sp500    # ~50 分钟
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

from universes import get_universe

load_dotenv()

DATA_DIR = Path("data")

# ── Telegram ──────────────────────────────────────────────────────────────────

TG_TOKEN   = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")


def tg_send(msg: str):
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


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def _load_csv(sym: str) -> pd.DataFrame | None:
    """读取本地 IB CSV（data/{sym}_1d.csv），返回标准化 DataFrame 或 None。

    陈旧文件视为缺失：每日自动运行时，静默使用一个停更的本地快照会让
    动量/RS 因子整体失真，比走 yfinance 兜底更糟。
    """
    path = DATA_DIR / f"{sym}_1d.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        # 统一列名为首字母大写
        df.columns = [c.strip().capitalize() for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        if len(df) < 60:
            return None
        stale_cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=4)
        if df.index.max() < stale_cutoff:
            return None
        return df
    except Exception:
        return None


def _download_yf(sym: str) -> pd.DataFrame | None:
    """yfinance fallback：当本地 CSV 不存在时使用。"""
    try:
        df = yf.Ticker(sym).history(period="1y", auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        df.columns = [c.capitalize() for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        if hasattr(df.index, "tz") and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df if len(df) >= 60 else None
    except Exception:
        return None


def load_data(symbols: list[str], benchmark: str) -> dict[str, pd.DataFrame]:
    """
    加载所有标的数据。优先读本地 CSV（IB），缺失时 fallback yfinance。
    """
    all_syms = symbols + ([benchmark] if benchmark not in symbols else [])
    data: dict[str, pd.DataFrame] = {}

    missing = []
    for sym in all_syms:
        df = _load_csv(sym)
        if df is not None:
            data[sym] = df
        else:
            missing.append(sym)

    # Batch the yfinance fallback: one-by-one requests get rate-limited long
    # before a 285-symbol universe finishes, which matters now that the
    # watchlist screener runs unattended every day.
    yf_fallback = 0
    if missing:
        for i in range(0, len(missing), 50):
            chunk = missing[i:i + 50]
            try:
                raw = yf.download(chunk, period="1y", interval="1d", auto_adjust=True,
                                  progress=False, group_by="ticker", threads=True)
            except Exception:
                continue
            for sym in chunk:
                try:
                    sub = raw[sym].copy() if len(chunk) > 1 else raw.copy()
                    if isinstance(sub.columns, pd.MultiIndex):
                        sub.columns = sub.columns.get_level_values(0)
                    sub = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    if hasattr(sub.index, "tz") and sub.index.tz is not None:
                        sub.index = sub.index.tz_localize(None)
                    if len(sub) >= 60:
                        data[sym] = sub
                        yf_fallback += 1
                except Exception:
                    continue

    ib_count = len(data) - yf_fallback
    print(f"数据加载完成: {len(data)} 只  "
          f"(IB本地 {ib_count} + yfinance补充 {yf_fallback}, "
          f"缺失 {len(all_syms) - len(data)})")
    if yf_fallback > 0:
        print(f"  提示：{yf_fallback} 只标的使用了 yfinance，"
              f"建议先运行 fetch_ib_data.py --universe <name> 更新本地数据")
    return data


# ── 因子计算 ──────────────────────────────────────────────────────────────────

def zscore(s: pd.Series) -> pd.Series:
    mu, sigma = s.mean(), s.std()
    if sigma == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sigma


def compute_factors(data: dict[str, pd.DataFrame], benchmark: str) -> pd.DataFrame:
    bench_df = data.get(benchmark)
    rows = []

    for sym, df in data.items():
        if sym == benchmark:
            continue
        close  = df["Close"]
        volume = df["Volume"]
        n = len(close)

        try:
            # F1: 跳期动量（60d，跳过最近 5 日避免短期反转）
            f1 = (close.iloc[-6] / close.iloc[-66] - 1) if n >= 66 else np.nan

            # F2: 相对强度 vs 基准（0.4×RS20 + 0.6×RS60）
            if bench_df is not None and len(bench_df) >= 61:
                f2 = (0.4 * ((close.iloc[-1] / close.iloc[-21] - 1) -
                              (bench_df["Close"].iloc[-1] / bench_df["Close"].iloc[-21] - 1)) +
                      0.6 * ((close.iloc[-1] / close.iloc[-61] - 1) -
                              (bench_df["Close"].iloc[-1] / bench_df["Close"].iloc[-61] - 1)))
            else:
                f2 = np.nan

            # F3: 量价背离（Alpha#12 变体）— sign(Δvol) × (-Δclose) 20日均值
            if n >= 21:
                pv = (np.sign(volume.diff()) * (-close.diff())).rolling(20).mean()
                f3 = pv.iloc[-1]
            else:
                f3 = np.nan

            # F4: 风险调整动量（ret_20 / std_20，类 Sharpe）
            if n >= 21:
                daily_ret = close.pct_change()
                std_20 = daily_ret.iloc[-20:].std()
                f4 = (close.iloc[-1] / close.iloc[-21] - 1) / std_20 if std_20 > 0 else np.nan
            else:
                f4 = np.nan

            # F5: 接近 52 周高点（close / rolling_max(252)）
            window = min(252, n)
            f5 = close.iloc[-1] / close.iloc[-window:].max() if window >= 20 else np.nan

            # ── ATR14 ────────────────────────────────────────────────────
            high, low = df["High"], df["Low"]
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low  - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr14   = tr.rolling(14).mean().iloc[-1]
            px      = close.iloc[-1]
            atr_pct = round(atr14 / px * 100, 1)

            # ── 支撑位（大级别 → 小级别）────────────────────────────────
            ma200 = round(close.rolling(200).mean().iloc[-1], 2) if n >= 200 else np.nan
            ma50  = round(close.rolling(50).mean().iloc[-1],  2) if n >= 50  else np.nan
            ma20  = round(close.rolling(20).mean().iloc[-1],  2) if n >= 20  else np.nan
            ma10  = round(close.rolling(10).mean().iloc[-1],  2) if n >= 10  else np.nan
            # 近期摆动低点（用 Low 列）
            low_qtr  = round(low.iloc[-60:].min(), 2)  if n >= 60  else np.nan  # 季度低
            low_1m   = round(low.iloc[-20:].min(), 2)  if n >= 20  else np.nan  # 1月低
            low_2w   = round(low.iloc[-10:].min(), 2)  if n >= 10  else np.nan  # 2周低

            # TP1/TP2/SL 基于当前价 + ATR
            tp1 = round(px + 2.0 * atr14, 2)
            tp2 = round(px + 3.5 * atr14, 2)
            sl  = round(px - 1.5 * atr14, 2)

            rows.append({
                "symbol":   sym,
                "close":    round(px, 2),
                "F1_mom": f1, "F2_rs": f2, "F3_pv_div": f3,
                "F4_risk_adj": f4, "F5_hi52": f5,
                # 支撑位
                "ma200": ma200, "ma50": ma50, "ma20": ma20, "ma10": ma10,
                "low_qtr": low_qtr, "low_1m": low_1m, "low_2w": low_2w,
                # 交易参考
                "atr_pct": atr_pct, "tp1": tp1, "tp2": tp2, "sl": sl,
            })
        except Exception as e:
            print(f"  [跳过] {sym}: {e}")

    df_f = pd.DataFrame(rows).set_index("symbol")

    factor_cols = ["F1_mom", "F2_rs", "F3_pv_div", "F4_risk_adj", "F5_hi52"]
    for col in factor_cols:
        df_f[f"z_{col}"] = zscore(df_f[col].dropna().reindex(df_f.index))

    z_cols = [f"z_{c}" for c in factor_cols]
    df_f["composite"] = df_f[z_cols].mean(axis=1)
    df_f["rank"]      = df_f["composite"].rank(ascending=False).astype(int)

    return df_f.sort_values("composite", ascending=False)


# ── 输出 ──────────────────────────────────────────────────────────────────────

def _support_str(row: pd.Series) -> str:
    """把支撑位格式化为可读字符串，只显示低于当前价的支撑。"""
    px = row["close"]
    def fp(v, label):
        if pd.isna(v) or v >= px:
            return None
        return f"{label}${v:.2f}"
    parts = []
    # 大级别
    s = fp(row.get("ma200"), "MA200 ")
    if s: parts.append(("大", s))
    s = fp(row.get("low_qtr"), "季低 ")
    if s: parts.append(("大", s))
    # 中级别
    s = fp(row.get("ma50"), "MA50 ")
    if s: parts.append(("中", s))
    # 小级别
    s = fp(row.get("ma20"), "MA20 ")
    if s: parts.append(("小", s))
    s = fp(row.get("low_1m"), "1M低 ")
    if s: parts.append(("小", s))
    s = fp(row.get("ma10"), "MA10 ")
    if s: parts.append(("小", s))
    s = fp(row.get("low_2w"), "2W低 ")
    if s: parts.append(("小", s))
    if not parts:
        return "  支撑: 各均线均在当前价上方（价格正在突破）"
    big = " | ".join(v for k, v in parts if k == "大")
    mid = " | ".join(v for k, v in parts if k == "中")
    sml = " | ".join(v for k, v in parts if k == "小")
    line = "  支撑: "
    segments = []
    if big: segments.append(f"[大] {big}")
    if mid: segments.append(f"[中] {mid}")
    if sml: segments.append(f"[小] {sml}")
    return line + "  ".join(segments)


def format_terminal(df: pd.DataFrame, top_n: int, label: str, benchmark: str, run_date: str) -> None:
    w = 88
    print(f"\n{'─'*w}")
    print(f"  ⭐ {label} 周频因子选股 Top {top_n}   基准:{benchmark}   {run_date}")
    print(f"{'─'*w}")
    for i, (sym, row) in enumerate(df.head(top_n).iterrows(), 1):
        score = f"{row['composite']:+.2f}" if pd.notna(row["composite"]) else "n/a"
        tags = []
        if pd.notna(row["F1_mom"]) and row["F1_mom"] > 0.05:   tags.append("动量↑")
        if pd.notna(row["F2_rs"]) and row["F2_rs"] > 0.02:     tags.append("RS强")
        if pd.notna(row["F5_hi52"]) and row["F5_hi52"] > 0.95: tags.append("近高点")
        tag_str = " [" + "/".join(tags) + "]" if tags else ""
        atr_str = f"ATR {row['atr_pct']:.1f}%" if pd.notna(row.get("atr_pct")) else ""
        def p(v): return f"${v:.2f}" if pd.notna(v) else "n/a"
        print(f"\n  {i:>2}. {sym:<5}  综合 {score}{tag_str}   收盘 {p(row['close'])}  {atr_str}")
        print(f"  {'':>4}入场: {p(row['close'])}(立即追) / 等回踩见下方支撑")
        print(f"  {'':>4}目标: TP1 {p(row.get('tp1'))}  TP2 {p(row.get('tp2'))}  SL {p(row.get('sl'))}")
        print(_support_str(row))
    print(f"\n{'─'*w}")
    print(f"  支撑级别: [大]=MA200/季低  [中]=MA50  [小]=MA20/1M低/MA10/2W低")
    print(f"  TP1=+2ATR  TP2=+3.5ATR  SL=-1.5ATR（日线ATR14，仅供参考）")
    print(f"{'─'*w}\n")


def format_telegram(df: pd.DataFrame, top_n: int, label: str, benchmark: str, run_date: str) -> str:
    n = min(top_n, 20)
    lines = [f"⭐ {label} 因子选股 Top {n}", f"📅 {run_date}  基准:{benchmark}", ""]
    for i, (sym, row) in enumerate(df.head(n).iterrows(), 1):
        px   = row["close"]
        score = f"{row['composite']:+.2f}" if pd.notna(row["composite"]) else "n/a"
        tags = []
        if pd.notna(row["F1_mom"]) and row["F1_mom"] > 0.05:   tags.append("动量↑")
        if pd.notna(row["F2_rs"]) and row["F2_rs"] > 0.02:     tags.append("RS强")
        if pd.notna(row["F5_hi52"]) and row["F5_hi52"] > 0.95: tags.append("近高点")
        tag_str = " " + "/".join(tags) if tags else ""
        def fp(v): return f"${v:.2f}" if pd.notna(v) else "n/a"

        # 支撑位（只取低于当前价的，各级别最近的一个）
        sup_big, sup_mid, sup_sml = None, None, None
        for v, lbl in [(row.get("ma200"), "MA200"), (row.get("low_qtr"), "季低")]:
            if pd.notna(v) and v < px and sup_big is None:
                sup_big = f"{lbl} {fp(v)}"
        if pd.notna(row.get("ma50")) and row["ma50"] < px:
            sup_mid = f"MA50 {fp(row['ma50'])}"
        for v, lbl in [(row.get("ma20"), "MA20"), (row.get("low_1m"), "1M低"),
                       (row.get("ma10"), "MA10"), (row.get("low_2w"), "2W低")]:
            if pd.notna(v) and v < px and sup_sml is None:
                sup_sml = f"{lbl} {fp(v)}"

        sup_parts = [s for s in [sup_big, sup_mid, sup_sml] if s]
        sup_line = "支撑: " + " | ".join(sup_parts) if sup_parts else "支撑: 各MA均在价格上方(突破中)"

        atr_str = f"ATR {row['atr_pct']:.1f}%" if pd.notna(row.get("atr_pct")) else ""
        lines += [
            f"{i:>2}. {sym:<5} {score}{tag_str}  {fp(px)}  {atr_str}",
            f"    TP1 {fp(row.get('tp1'))}  TP2 {fp(row.get('tp2'))}  SL {fp(row.get('sl'))}",
            f"    {sup_line}",
            "",
        ]
    lines += ["大=MA200/季低  中=MA50  小=MA20/1M低", "仅供参考，非交易建议"]
    return "\n".join(lines)


def save_csv(df: pd.DataFrame, top_n: int, universe: str, run_date: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / "screener_results.csv"

    top = df.head(top_n).copy().reset_index()
    top.insert(0, "run_date", run_date)
    top.insert(1, "universe", universe)
    top.insert(2, "rank_in_run", range(1, len(top) + 1))

    if out_path.exists():
        top.to_csv(out_path, mode="a", header=False, index=False)
    else:
        top.to_csv(out_path, index=False)
    print(f"结果已追加到 {out_path}（{len(top)} 行）")


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="多指数周频因子选股初筛")
    parser.add_argument("--universe", default="ndx100",
                        choices=["ndx100", "sp500", "dow30", "russell2000", "all", "watchlist"],
                        help="股票池：ndx100 / sp500 / dow30 / russell2000 / all / watchlist（默认 ndx100）")
    parser.add_argument("--top",      type=int, default=20, help="输出 Top N（默认 20）")
    parser.add_argument("--telegram", action="store_true",  help="推送 Telegram")
    parser.add_argument("--no-save",  action="store_true",  help="不写 CSV")
    args = parser.parse_args()

    tickers, benchmark, label = get_universe(args.universe)
    run_date = datetime.now().strftime("%Y-%m-%d")
    print(f"\n=== {label} 因子选股  {run_date}  ({len(tickers)} 只标的) ===")

    data       = load_data(tickers, benchmark)
    df_factors = compute_factors(data, benchmark)

    format_terminal(df_factors, args.top, label, benchmark, run_date)

    if not args.no_save:
        save_csv(df_factors, args.top, args.universe, run_date)

    if args.telegram:
        msg = format_telegram(df_factors, args.top, label, benchmark, run_date)
        tg_send(msg)


if __name__ == "__main__":
    main()

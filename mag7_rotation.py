"""
mag7_rotation.py — MAG7 周频相对强弱轮动回测

策略逻辑：
  - 每周一（或下一个交易日）按 60 日收益排名
  - 持仓 top-N 只（默认 N=2），等权分配
  - 无信号过滤：只要市场开放就持仓（本策略是相对强弱轮动，不做 Regime 过滤）
  - 可选：加入 QQQ > 200SMA 门槛（Risk-off 时全部空仓）

用法：
  python mag7_rotation.py
  python mag7_rotation.py --top 3
  python mag7_rotation.py --top 2 --risk-off    # 加入风控：QQQ < 200SMA 时空仓
  python mag7_rotation.py --rs-period 20         # 用 20 日收益替代 60 日
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

DATA_DIR = Path(cfg["data"]["dir"])

MAG7 = ["MSFT", "GOOGL", "META", "AAPL", "NVDA", "AMZN", "TSLA"]
INITIAL_CASH = 100_000.0
COMMISSION   = 0.001   # 0.1%


def load_daily(symbol: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}_1d.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    df.columns = [c.capitalize() for c in df.columns]
    return df[["Open", "High", "Low", "Close", "Volume"]]


def run_rotation(top_n: int = 2, rs_period: int = 60,
                 use_risk_off: bool = False,
                 qqq_sma: int = 200) -> pd.DataFrame:
    """
    运行 MAG7 周频轮动回测。
    返回每周调仓记录 DataFrame。
    """
    # 加载所有数据
    prices = {}
    for sym in MAG7:
        df = load_daily(sym)
        if df is not None:
            prices[sym] = df["Close"]
    if len(prices) < 2:
        raise ValueError("MAG7 数据不足")

    # 对齐到公共交易日
    close_df = pd.DataFrame(prices).dropna(how="all")
    close_df = close_df.ffill()

    # QQQ（risk-off 用）
    qqq_close = None
    if use_risk_off:
        df_qqq = load_daily("QQQ")
        if df_qqq is not None:
            qqq_close = df_qqq["Close"].reindex(close_df.index, method="ffill")

    # 计算 RS 收益
    rs = close_df.pct_change(rs_period)

    # 每周一重采样：取周一收盘价 + RS 排名
    weekly_mondays = close_df.resample("W-MON").first().index
    # 只取 rs_period 个交易日之后才开始
    start_idx = rs_period + 5
    weekly_mondays = weekly_mondays[weekly_mondays >= close_df.index[start_idx]]

    # 回测变量
    portfolio_value = INITIAL_CASH
    cash = INITIAL_CASH
    holdings: dict[str, float] = {}   # symbol → shares
    prev_prices: dict[str, float] = {}
    records = []

    for i, rebal_date in enumerate(weekly_mondays):
        # 找到最近的实际交易日
        date_idx = close_df.index.searchsorted(rebal_date)
        if date_idx >= len(close_df):
            break
        actual_date = close_df.index[date_idx]

        current_prices = close_df.loc[actual_date]
        rs_today       = rs.loc[actual_date] if actual_date in rs.index else pd.Series()

        # 平掉旧仓位（按当前价格）
        for sym, shares in holdings.items():
            if sym in current_prices and not pd.isna(current_prices[sym]):
                sell_value = shares * current_prices[sym]
                commission = sell_value * COMMISSION
                cash += sell_value - commission

        holdings.clear()

        # Risk-off 检查
        in_market = True
        if use_risk_off and qqq_close is not None:
            qqq_sma_val = qqq_close.rolling(qqq_sma).mean().loc[actual_date]
            if pd.isna(qqq_sma_val) or qqq_close.loc[actual_date] < qqq_sma_val:
                in_market = False

        selected = []
        if in_market and len(rs_today) > 0:
            # 按 RS 排名选 top-N
            valid_rs = rs_today.dropna()
            ranked   = valid_rs.sort_values(ascending=False)
            selected = list(ranked.index[:top_n])

        # 买入 top-N（等权）
        if selected:
            alloc_each = cash / len(selected)
            for sym in selected:
                price = current_prices.get(sym, np.nan)
                if pd.isna(price) or price <= 0:
                    continue
                shares = int((alloc_each * (1 - COMMISSION)) / price)
                if shares <= 0:
                    continue
                cost = shares * price * (1 + COMMISSION)
                if cost > cash:
                    shares = int(cash / (price * (1 + COMMISSION)))
                    cost   = shares * price * (1 + COMMISSION)
                if shares <= 0:
                    continue
                holdings[sym] = shares
                cash -= cost

        # 计算当前净值
        portfolio_value = cash + sum(
            holdings.get(sym, 0) * current_prices.get(sym, 0)
            for sym in holdings
        )

        records.append({
            "date":      actual_date,
            "portfolio": portfolio_value,
            "cash":      cash,
            "holdings":  ",".join(selected) if selected else "(空仓)",
            "in_market": in_market,
        })

    return pd.DataFrame(records).set_index("date")


def calc_metrics(rec: pd.DataFrame) -> dict:
    pv = rec["portfolio"]
    rets = pv.pct_change().dropna()
    n_weeks = len(rec)
    n_years = n_weeks / 52

    total_ret = (pv.iloc[-1] / INITIAL_CASH - 1) * 100
    ann_ret   = ((pv.iloc[-1] / INITIAL_CASH) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    ann_vol   = rets.std() * (52 ** 0.5) * 100
    sharpe    = (ann_ret / ann_vol) if ann_vol > 0 else 0
    drawdowns = (pv / pv.cummax() - 1) * 100
    max_dd    = drawdowns.min()
    win_weeks = (rets > 0).sum()
    wr        = win_weeks / len(rets) * 100 if len(rets) else 0
    return {
        "total_ret": round(total_ret, 1),
        "ann_ret":   round(ann_ret, 1),
        "ann_vol":   round(ann_vol, 1),
        "sharpe":    round(sharpe, 3),
        "max_dd":    round(max_dd, 1),
        "wr":        round(wr, 1),
        "n_weeks":   n_weeks,
    }


def run_sensitivity(top_ns, rs_periods, use_risk_off):
    """参数敏感性扫描"""
    print(f"\n{'═'*70}")
    print(f"  MAG7 轮动 参数扫描  risk_off={use_risk_off}")
    print(f"{'═'*70}")
    hdr = (f"{'top_n':>6} {'rs_d':>5} {'总收益%':>8} {'年化%':>7} "
           f"{'Sharpe':>7} {'MaxDD%':>8} {'胜率%':>6} {'周数':>6}")
    print(hdr); print("─"*70)
    results = []
    for top_n in top_ns:
        for rs_p in rs_periods:
            try:
                rec = run_rotation(top_n=top_n, rs_period=rs_p, use_risk_off=use_risk_off)
                m = calc_metrics(rec)
                print(f"{top_n:>6} {rs_p:>5} {m['total_ret']:>8.1f} {m['ann_ret']:>7.1f} "
                      f"{m['sharpe']:>7.3f} {m['max_dd']:>8.1f} {m['wr']:>6.1f} {m['n_weeks']:>6}")
                results.append({"top_n": top_n, "rs_period": rs_p, **m})
            except Exception as e:
                print(f"{top_n:>6} {rs_p:>5}  错误: {e}")
    return results


def print_holding_dist(rec: pd.DataFrame):
    """打印各标的持仓频率"""
    from collections import Counter
    cnt = Counter()
    for h in rec["holdings"]:
        if h != "(空仓)":
            for sym in h.split(","):
                cnt[sym.strip()] += 1
    total = len(rec)
    print("\n  持仓频率（占调仓次数 %）：")
    for sym, n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"    {sym:<6}: {n}/{total} = {n/total*100:.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top",      type=int, default=2, help="持仓只数（默认 2）")
    parser.add_argument("--rs-period",type=int, default=60,help="RS 计算周期（交易日，默认 60）")
    parser.add_argument("--risk-off", action="store_true", help="QQQ < 200SMA 时空仓")
    parser.add_argument("--scan",     action="store_true", help="参数敏感性扫描")
    args = parser.parse_args()

    if args.scan:
        results = run_sensitivity(
            top_ns    = [1, 2, 3],
            rs_periods = [20, 40, 60, 90],
            use_risk_off = args.risk_off,
        )
        # 找最优
        if results:
            best = max(results, key=lambda x: x["sharpe"])
            print(f"\n  最优: top_n={best['top_n']}  rs={best['rs_period']}d"
                  f"  Sharpe={best['sharpe']:.3f}  MaxDD={best['max_dd']:.1f}%")
        # 基准对比：等权持有 MAG7
        print("\n  基准：等权持有 MAG7（每周再平衡）")
        rec_bm = run_rotation(top_n=7, rs_period=60, use_risk_off=False)
        m_bm   = calc_metrics(rec_bm)
        print(f"  Sharpe={m_bm['sharpe']:.3f}  年化={m_bm['ann_ret']:.1f}%"
              f"  MaxDD={m_bm['max_dd']:.1f}%")
    else:
        rec = run_rotation(top_n=args.top, rs_period=args.rs_period,
                           use_risk_off=args.risk_off)
        m   = calc_metrics(rec)
        print(f"\n{'═'*55}")
        print(f"  MAG7 轮动  top={args.top}  rs={args.rs_period}d"
              f"  risk_off={args.risk_off}")
        print(f"{'═'*55}")
        print(f"  总收益:   {m['total_ret']:.1f}%")
        print(f"  年化收益: {m['ann_ret']:.1f}%  年化波动: {m['ann_vol']:.1f}%")
        print(f"  Sharpe:   {m['sharpe']:.3f}")
        print(f"  最大回撤: {m['max_dd']:.1f}%")
        print(f"  周胜率:   {m['wr']:.1f}%  （{m['n_weeks']} 周）")
        print_holding_dist(rec)

        # 对比基准
        print(f"\n  基准：等权持有 MAG7")
        rec_bm = run_rotation(top_n=7, rs_period=60, use_risk_off=False)
        m_bm   = calc_metrics(rec_bm)
        print(f"  Sharpe={m_bm['sharpe']:.3f}  年化={m_bm['ann_ret']:.1f}%"
              f"  MaxDD={m_bm['max_dd']:.1f}%")

        out = Path("logs/mag7_rotation.csv")
        out.parent.mkdir(exist_ok=True)
        rec.to_csv(out)
        print(f"\n  结果已保存至 {out}")


if __name__ == "__main__":
    main()

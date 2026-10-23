"""ETF 动量轮动（34 日「年化收益 × R²」+ 月度调仓 + 前 3 + 弱市空仓）—— 预注册实验。

参数**全部照抄** `research/DESIGN_etf_momentum_rotation.md`（预注册于 2026-10-18，
§10 修订于 2026-10-23，均在任何结果产生之前）。本文件只执行，不新增任何旋钮。

判据（G1–G6）与对照（§5）见设计文档；这里只实现，不重述理由。
一次跑完即定稿：**p/指标不过就是不过，不许改参数、改窗口、改出场再跑。**
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ── 冻结参数（来自 DESIGN §2/§3）────────────────────────────────────────────
PRIMARY = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
CROSS = ["GLD", "TLT"]
BENCH = "SPY"
BENCH2 = "QQQ"
START = pd.Timestamp("2011-01-01")
END = pd.Timestamp("2026-06-30")
MOM_W = 34           # 打分窗口（交易日）
TOP_N = 3
MIN_HIST = 250       # 当月参与打分所需的最少历史日线
COST_SIDE = 0.0010   # 单边 10bps
COST_STRESS = 0.0030
SHRINK = 0.20        # 次口径权重：相关阵向单位阵收缩
COV_W = 1200
BOOT = 1000
SEED = 20261018
Z80 = 1.959964 + 0.841621
SPLIT = pd.Timestamp("2019-01-01")   # G5 前后段分界
W_GRID = [20, 25, 34, 50, 60]
N_GRID = [1, 2, 3, 5]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(sym: str) -> pd.Series:
    """ETF 读本地 IB 日线；两个基准读 research/data_external 的 yfinance 序列。

    本地 data/SPY_1d.csv 只回溯到 2016-07（IB 默认 10 年），而本实验注册区间自
    2011 起。补基准时夜间保鲜（14:40）正占着 clientId=2，不与生产任务抢连接，
    改用 yfinance 单独取并落在 research 目录——不改动任何生产数据文件。
    两源在 2016-07 之后的重叠段中位差 SPY 0.0003% / QQQ 0.0001%，可以互换。
    """
    base = os.path.join(ROOT, "research", "data_external", f"{sym}_bench_1d.csv")
    path = base if os.path.exists(base) else os.path.join(ROOT, "data", f"{sym}_1d.csv")
    d = pd.read_csv(path)
    c = d.columns[0]
    d[c] = pd.to_datetime(d[c])
    d = d.set_index(c).sort_index()
    d.columns = [x.capitalize() for x in d.columns]
    return d["Close"].loc[:END]


def score_table(px: pd.DataFrame, w: int) -> pd.DataFrame:
    """score = 年化收益 × R²，对最近 w 个交易日的对数收盘价做 OLS。"""
    lp = np.log(px)
    x = np.arange(w, dtype=float)
    xc = x - x.mean()
    sxx = (xc ** 2).sum()
    out = pd.DataFrame(index=px.index, columns=px.columns, dtype=float)
    for col in px.columns:
        v = lp[col].values
        res = np.full(len(v), np.nan)
        for i in range(w - 1, len(v)):
            yv = v[i - w + 1:i + 1]
            if np.isnan(yv).any():
                continue
            slope = (xc * (yv - yv.mean())).sum() / sxx
            pred = yv.mean() + slope * xc
            ss_res = ((yv - pred) ** 2).sum()
            ss_tot = ((yv - yv.mean()) ** 2).sum()
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            res[i] = (np.exp(slope * 252) - 1) * r2
        out[col] = res
    return out


def rebalance_dates(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(idx, index=idx)
    return [g.iloc[0] for _, g in s.groupby([idx.year, idx.month])]


def shrink_weights(rets: pd.DataFrame) -> np.ndarray:
    """相关阵向单位阵收缩 20% 后的最小方差权重（EPO 的近似，见 DESIGN §3）。"""
    if rets.shape[0] < 60 or rets.shape[1] == 1:
        return np.ones(rets.shape[1]) / rets.shape[1]
    sd = rets.std().values
    corr = rets.corr().values
    corr = (1 - SHRINK) * corr + SHRINK * np.eye(len(corr))
    cov = corr * np.outer(sd, sd)
    try:
        inv = np.linalg.pinv(cov)
        w = inv @ np.ones(len(cov))
        if w.sum() <= 0:
            raise np.linalg.LinAlgError
        w = np.clip(w / w.sum(), 0, None)
        return w / w.sum()
    except np.linalg.LinAlgError:
        return np.ones(rets.shape[1]) / rets.shape[1]


def run(px: pd.DataFrame, w: int = MOM_W, top_n: int = TOP_N,
        cost: float = COST_SIDE, weighting: str = "equal",
        picker=None, seed: int = SEED) -> pd.Series:
    """返回日度净值序列。picker 可替换为随机选择（对照 2）。"""
    sc = score_table(px, w)
    rb = [d for d in rebalance_dates(px.index) if d >= START]
    rets = px.pct_change()
    hold: dict[str, float] = {}
    nav, navs = 1.0, []
    rng = np.random.default_rng(seed)
    rb_set = set(rb)
    for i, dt in enumerate(px.index):
        if dt < START:
            continue
        if hold:
            r = sum(wt * rets.at[dt, s] for s, wt in hold.items()
                    if not np.isnan(rets.at[dt, s]))
            nav *= (1 + r)
        if dt in rb_set:
            elig = [s for s in px.columns
                    if px[s].loc[:dt].notna().sum() >= MIN_HIST and not np.isnan(sc.at[dt, s])]
            if picker is None:
                ranked = sorted(elig, key=lambda s: sc.at[dt, s], reverse=True)
                pick = [s for s in ranked[:top_n] if sc.at[dt, s] > 0]
            else:
                pick = picker(elig, top_n, rng)
            if not pick:
                new: dict[str, float] = {}
            elif weighting == "shrink":
                sub = rets[pick].loc[:dt].tail(COV_W).dropna()
                wts = shrink_weights(sub)
                new = dict(zip(pick, wts))
            else:
                new = {s: 1.0 / len(pick) for s in pick}
            turnover = sum(abs(new.get(s, 0) - hold.get(s, 0))
                           for s in set(new) | set(hold))
            nav *= (1 - cost * turnover)
            hold = new
        navs.append((dt, nav))
    return pd.Series(dict(navs))


def stats(nav: pd.Series) -> dict:
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    dd = (nav / nav.cummax() - 1).min()
    m = nav.resample("ME").last().pct_change().dropna()
    sharpe = m.mean() / m.std() * np.sqrt(12) if m.std() > 0 else 0.0
    return dict(cagr=cagr, mdd=dd, sharpe=sharpe, calmar=cagr / abs(dd) if dd else np.nan,
                months=len(m), total=nav.iloc[-1] - 1)


def monthly(nav: pd.Series) -> pd.Series:
    return nav.resample("ME").last().pct_change().dropna()


def block_bootstrap_diff(a: pd.Series, b: pd.Series, rounds: int = BOOT) -> tuple:
    """按月重采样（有效单位是调仓期），返回年化差的 90% 区间。"""
    j = pd.concat([a, b], axis=1).dropna()
    d = (j.iloc[:, 0] - j.iloc[:, 1]).values
    rng = np.random.default_rng(SEED)
    out = []
    for _ in range(rounds):
        s = d[rng.integers(0, len(d), len(d))]
        out.append((1 + s.mean()) ** 12 - 1)
    return float(np.percentile(out, 5)), float(np.percentile(out, 95))


def main() -> int:
    t0 = datetime.now()
    px_all = pd.DataFrame({s: load(s) for s in PRIMARY + CROSS + [BENCH, BENCH2]}).sort_index()
    px_all = px_all.loc[:END]
    prim = px_all[PRIMARY].dropna(how="all")
    second = px_all[PRIMARY + CROSS].dropna(how="all")
    bench_nav = (px_all[BENCH] / px_all[BENCH].loc[px_all.index >= START].iloc[0]).loc[START:]
    bench2_nav = (px_all[BENCH2] / px_all[BENCH2].loc[px_all.index >= START].iloc[0]).loc[START:]

    print("=" * 92)
    print("ETF 动量轮动（34 日 年化收益×R² · 月度 · 前3 · 弱市空仓）—— 预注册实验")
    print(f"跑于 {t0:%Y-%m-%d %H:%M:%S}  seed={SEED}  自助 {BOOT} 次")
    print("预注册：research/DESIGN_etf_momentum_rotation.md（2026-10-18，§10 修订 2026-10-23）")
    print(f"数据源：data/*_1d.csv（IB ADJUSTED_LAST，13/13 过验收）")
    print(f"主口径 universe：{' '.join(PRIMARY)}（SPDR 行业全集，外部给定）")
    print(f"次口径：+ {' '.join(CROSS)}（TLT 数据自 2016-01 起，按「可用即纳入」）")
    print(f"区间：{START:%Y-%m-%d} → {END:%Y-%m-%d}   成本：单边 {COST_SIDE:.2%}")
    print("=" * 92)

    res = {}
    for name, px, wtg in (("主口径·等权", prim, "equal"),
                          ("次口径·等权(+GLD/TLT)", second, "equal"),
                          ("主口径·收缩最小方差", prim, "shrink")):
        res[name] = run(px, weighting=wtg)
    res["对照1 等权持有全池"] = run(prim, picker=lambda e, n, r: e)

    print(f"\n{'策略':<24}{'累计':>9}{'年化':>8}{'最大回撤':>10}{'夏普':>7}{'卡玛':>7}{'月数':>6}")
    rows = {}
    for k, nav in list(res.items()) + [("基准 SPY", bench_nav), ("基准 QQQ", bench2_nav)]:
        s = stats(nav); rows[k] = s
        print(f"{k:<24}{s['total']:>+9.1%}{s['cagr']:>+8.2%}{s['mdd']:>10.1%}"
              f"{s['sharpe']:>7.2f}{s['calmar']:>7.2f}{s['months']:>6}")

    main_nav = res["主口径·等权"]
    bs = rows["主口径·等权"]; bb = rows["基准 SPY"]
    print("\n" + "─" * 92)
    print("判据（全部须通过）")
    g1 = bs["cagr"] - bb["cagr"]
    print(f"  G1 年化 > SPY：{bs['cagr']:+.2%} vs {bb['cagr']:+.2%}  差 {g1:+.2%}  "
          f"{'✅' if g1 > 0 else '❌'}")
    lo, hi = block_bootstrap_diff(monthly(main_nav), monthly(bench_nav))
    print(f"  G2 月度块自助 90% 区间整体 >0：[{lo:+.2%}, {hi:+.2%}]  {'✅' if lo > 0 else '❌'}")

    yr = monthly(main_nav).groupby(monthly(main_nav).index.year).apply(lambda s: (1 + s).prod() - 1)
    yb = monthly(bench_nav).groupby(monthly(bench_nav).index.year).apply(lambda s: (1 + s).prod() - 1)
    worst = (yr - yb).idxmax()
    m2 = monthly(main_nav)[monthly(main_nav).index.year != worst]
    b2 = monthly(bench_nav)[monthly(bench_nav).index.year != worst]
    c2 = (1 + m2).prod() ** (12 / len(m2)) - 1
    cb2 = (1 + b2).prod() ** (12 / len(b2)) - 1
    print(f"  G3 剔除贡献最大年份（{worst}）后年化 > SPY：{c2:+.2%} vs {cb2:+.2%}  "
          f"{'✅' if c2 > cb2 else '❌'}")

    nav30 = run(prim, cost=COST_STRESS)
    s30 = stats(nav30)
    print(f"  G4 30bps 下年化 > SPY：{s30['cagr']:+.2%} vs {bb['cagr']:+.2%}  "
          f"{'✅' if s30['cagr'] > bb['cagr'] else '❌'}")

    post = main_nav.loc[SPLIT:] / main_nav.loc[SPLIT:].iloc[0]
    postb = bench_nav.loc[SPLIT:] / bench_nav.loc[SPLIT:].iloc[0]
    sp, sb = stats(post), stats(postb)
    g5 = sp["cagr"] > sb["cagr"] and sp["sharpe"] > 0.5
    print(f"  G5 后段({SPLIT:%Y}–)单独成立：年化 {sp['cagr']:+.2%} vs SPY {sb['cagr']:+.2%}，"
          f"夏普 {sp['sharpe']:.2f}  {'✅' if g5 else '❌'}")

    rnd = []
    for k in range(200):
        nv = run(prim, picker=lambda e, n, r: list(r.choice(e, size=min(n, len(e)), replace=False)),
                 seed=SEED + k)
        rnd.append(stats(nv)["cagr"])
    rnd = np.array(rnd)
    pval = float((rnd >= bs["cagr"]).mean())
    print(f"  G6 跑赢「随机选3」分布：随机年化中位 {np.median(rnd):+.2%}，"
          f"策略 {bs['cagr']:+.2%}，p={pval:.4f}  {'✅' if pval < 0.05 else '❌'}")

    md = monthly(main_nav) - monthly(bench_nav)
    # 配对差分用 sqrt(1/n)，不是双样本的 sqrt(2/n)——2026-10-23 首跑时写错了，
    # 把可检出下限高估了 √2 倍（12.03%/年 → 8.4%/年）。判据 G2 用的是配对自助，
    # 不受影响；这里只是功效参考值。
    floor = Z80 * md.std() / np.sqrt(len(md))
    print(f"\n  80% 功效可检出的月度超额下限 {floor:+.3%}（年化 ≈ {((1+floor)**12-1):+.2%}），"
          f"实测月度超额 {md.mean():+.3%}"
          + ("  ⚠️ 低于下限：看不见，不等于无效应" if abs(md.mean()) < floor else ""))

    print("\n── 窗口稳健性（不进判据）──")
    for w in W_GRID:
        s = stats(run(prim, w=w))
        print(f"  W={w:<3} 年化 {s['cagr']:+7.2%}  夏普 {s['sharpe']:5.2f}  回撤 {s['mdd']:6.1%}"
              + ("   ← 原策略" if w == MOM_W else ""))
    print("── 持仓数稳健性（不进判据）──")
    for n in N_GRID:
        s = stats(run(prim, top_n=n))
        print(f"  N={n:<3} 年化 {s['cagr']:+7.2%}  夏普 {s['sharpe']:5.2f}  回撤 {s['mdd']:6.1%}"
              + ("   ← 原策略" if n == TOP_N else ""))

    print("\n── 逐年（主口径 vs SPY）──")
    for y in sorted(set(yr.index) & set(yb.index)):
        print(f"  {y}  策略 {yr[y]:+7.2%}   SPY {yb[y]:+7.2%}   差 {yr[y]-yb[y]:+7.2%}")
    print(f"  跑赢年份：{int((yr > yb).sum())}/{len(yr)}")

    passed = [g1 > 0, lo > 0, c2 > cb2, s30["cagr"] > bb["cagr"], g5, pval < 0.05]
    print("\n" + "=" * 92)
    print(f"裁决：G1–G6 通过 {sum(passed)}/6 → "
          + ("全部通过，可进入下一步（样本外跟踪）" if all(passed) else "**判负归档**"))
    print(f"完成，耗时 {(datetime.now()-t0).total_seconds():.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())

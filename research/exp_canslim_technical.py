"""CAN SLIM 的技术半套（L / S / M / 基底）叠在既有 252 日突破上 —— 预注册实验。

═══ 来源与范围 ═══
小红书「他一年赚9倍，就靠这7个字母」（厘厘研究室，2026-10-17）讲欧奈尔 CAN SLIM。
**基本面四条（C 季度 EPS+25% / A 三年+25% / N 新产品 / I 机构家数递增）本仓库没有
数据源，本轮不测**，不要把本轮结果当成对 CAN SLIM 整体的检验——它只检验价格与
成交量能定义的那半套。

═══ 为什么叠在既有突破上，而不另写一套 ═══
`breakout_backtest.compute_breakout_signals` 已有 252 日新高突破（`close >
high.rolling(252, min_periods=200).max().shift(1)`），且 `use_vol_filter` 已有
「突破日量 > 20 日均量 ×1.5」（默认关）。本实验**直接 import 它算突破**，只在上面
叠层，这样「叠加是否有增量」才问得干净；另写一套突破会把突破定义的差异混进结论。

═══ 预注册假设（施工前冻结，跑完不许改参数/窗口/出场再跑）═══
逐层嵌套，**每层对上一层的增量是主判据**：

    L0  裸突破                       （对照基线）
    L1  + L 相对强度：突破日该股过去 252 日收益在**全 universe 横截面**百分位 ≥ 80
    L2  + S 放量：突破日成交量 ≥ 20 日均量 × 1.4
    L3  + M 大盘：QQQ 当日收盘 > 其 SMA200
    L4  + 基底：突破前 15 个交易日内未创过 252 日新高（「横盘几周后突破」）

H1–H4：每加一层，**单笔净收益均值高于上一层**。m = 4，Holm 校正。
判据 p < 0.05（Holm 后）。p 不过就是不过。

注：L 这一条与 `screener.py` 的 F2 不同口径——F2 是 0.4×RS20+0.6×RS60 对基准 ETF
的**相对涨幅**，本轮是 252 日收益在全 universe 的**横截面百分位**（欧奈尔 RS Rating
的口径）。两者没测过彼此的替代关系，本轮也不测。

═══ 出场结构（真实组与所有对照组完全相同）═══
- 入场：突破日**收盘**（与本仓库「完整 bar 收盘决策」惯例一致）
- 固定止损 −7.5%（欧奈尔口径）：盘中 Low ≤ 入场×0.925 即出；当日 Open 已跳空
  在止损价下方时按 **Open** 成交（不假装能在止损价拿到成交）
- 未触止损则持有 **20 个交易日**按收盘出
- 稳健性另跑持有 **60 个交易日**，**不进判据**
- 成本：单边 10bps、双边共 20bps（`config.yaml` 的 `commission: 0.001` 在
  Backtesting.py 里是按边收取，这里照同一口径），从净收益里直接扣

═══ 统计（这是本实验最容易做错的地方）═══
同一天几十个标的一起触发、共用同一个大盘状态，**有效样本是不同日期数，不是信号数**
（上游 `quantrift_index_future/research/exp_breadth_stock_signals.py` 的教训，只读参考）。

本轮的条件变量分两类，置换方式必须分开：
- **标的层条件**（L1 相对强度 / L2 放量 / L4 基底）：**日内置换**——在每个日期内部，
  把「是否入选」的标签在当日的上层事件之间打乱。这样当日的市场效应被整个条件掉，
  问的正是「同一天里，这个条件挑出来的股票是否更好」。
- **日期层条件**（L3 大盘）：**整日块置换**——把日期的 regime 标签在日期之间打乱。
  这一层的差异本质上是「哪些日子入场」，不能在日内置换（同一天标签相同）。

功效：80% 功效可检出下限 = Z80 × sd × sqrt(1/d_a + 1/d_b)，**d 用不同日期数**。
效应低于下限时标注「看不见」，**不得当成「无效应」**。

═══ 对照 ═══
① 每层对上一层的增量（主判据，见上）
② 同波动率随机入场：对每个事件，在**同一日期**、ATR%/收盘同一十分位的标的里随机
   取一个入场，用完全相同的出场规则。同日期是为了把大盘状态条件掉。

═══ 数据源与 universe（写进输出头部）═══
- 价格：`data/{SYMBOL}_1d.csv`（本仓库本地日线，IB ADJUSTED_LAST + useRTH 为主，
  缺口由 yfinance auto_adjust 回补；两者 2026-07-25 抽查收盘价差异 0.000%）
- universe：本地所有 ≥300 根日线的标的（含 Russell2000 快照池），**非时点化**
- ⚠️ **幸存者/选择偏差无法消除**：这个池子是「今天还在本地有数据」的标的，
  TASK.md「长多头横截面动量轮动」正因此判负。本轮的主判据是**同一事件集内部的
  条件比较**（且 L1/L2/L4 用日内置换），比「按表现选池子」暴露小，但 L1 的横截面
  百分位仍然是在一个偏差池子里算的——**结论只在这个口径下成立**。
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ── 冻结参数 ────────────────────────────────────────────────────────────────
RS_PCTL      = 0.80      # L1：252 日收益横截面百分位下限
VOL_MULT     = 1.40      # L2：突破日量 / 20 日均量
BASE_LOOKBACK = 15       # L4：突破前多少个交易日内不得创 252 日新高
STOP_PCT     = 0.075     # 固定止损 7.5%
HOLD_BARS    = 20        # 主出场
HOLD_BARS_ALT = 60       # 稳健性，不进判据
COST_RT      = 0.0020    # 双边成本 20bps
MIN_BARS     = 300       # universe 门槛
MIN_XSEC     = 100       # 某日横截面不足此数则丢弃当日事件
ROUNDS       = 5000
SEED         = 20261018
Z80          = 1.959964 + 0.841621
P_THRESHOLD  = 0.05
EXCLUDE_YEARS = (2020, 2021)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from breakout_backtest import compute_breakout_signals  # noqa: E402  只读复用突破定义

LAYERS = ["L0 裸突破", "L1 +相对强度", "L2 +放量", "L3 +大盘", "L4 +基底"]
LAYER_KIND = {1: "symbol", 2: "symbol", 3: "date", 4: "symbol"}


def load_universe() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "*_1d.csv"))):
        sym = os.path.basename(f)[:-7]
        try:
            d = pd.read_csv(f)
        except Exception:
            continue
        if d.empty or d.columns[0] not in ("Date", "date"):
            continue
        d.columns = [c.capitalize() for c in d.columns]
        if not {"Open", "High", "Low", "Close", "Volume"}.issubset(d.columns):
            continue
        d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
        d = d.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
        d = d[~d.index.duplicated(keep="last")]
        if len(d) < MIN_BARS:
            continue
        out[sym] = d[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    return out


def exit_return(d: pd.DataFrame, i: int, hold: int) -> float | None:
    """固定止损 + 到期收盘出。返回净收益；数据不足到期则 None（未决，丢弃并计数）。"""
    entry = float(d["Close"].iloc[i])
    stop = entry * (1 - STOP_PCT)
    n = len(d)
    if i + hold >= n:
        return None
    lo = d["Low"].values
    op = d["Open"].values
    for h in range(1, hold + 1):
        j = i + h
        if lo[j] <= stop:
            px = min(op[j], stop)        # 跳空低开则按开盘价，不假装能在止损价成交
            return px / entry - 1 - COST_RT
    return float(d["Close"].iloc[i + hold]) / entry - 1 - COST_RT


def build_events(uni: dict[str, pd.DataFrame]) -> pd.DataFrame:
    # 横截面 252 日收益矩阵（date × symbol）
    r252 = pd.concat({s: d["Close"] / d["Close"].shift(252) - 1 for s, d in uni.items()}, axis=1)
    pctl = r252.rank(axis=1, pct=True)
    xsec_n = r252.notna().sum(axis=1)
    atrp = pd.concat({s: ((d["High"] - d["Low"]).rolling(20).mean() / d["Close"])
                      for s, d in uni.items()}, axis=1)
    atr_dec = atrp.rank(axis=1, pct=True)

    qqq = uni.get("QQQ")
    if qqq is None:
        raise SystemExit("缺 data/QQQ_1d.csv，L3 无法判定")
    regime = (qqq["Close"] > qqq["Close"].rolling(200).mean())

    rows = []
    for sym, d in uni.items():
        sig = compute_breakout_signals(d, {"confirm_days": 1})
        bo = sig["breakout"].astype(float)
        if bo.sum() == 0:
            continue
        volavg = d["Volume"].replace(0, np.nan).rolling(20).mean()
        volr = d["Volume"] / volavg
        prior_high = bo.rolling(BASE_LOOKBACK).max().shift(1)   # 前 15 日内是否创过新高
        idx = np.where(bo.values == 1)[0]
        for i in idx:
            dt = d.index[i]
            if xsec_n.get(dt, 0) < MIN_XSEC:
                continue
            p = pctl.at[dt, sym] if dt in pctl.index else np.nan
            if not np.isfinite(p):
                continue
            r20 = exit_return(d, i, HOLD_BARS)
            r60 = exit_return(d, i, HOLD_BARS_ALT)
            rows.append(dict(
                sym=sym, date=dt, rs_pctl=float(p),
                volr=float(volr.iloc[i]) if np.isfinite(volr.iloc[i]) else np.nan,
                base_ok=bool(prior_high.iloc[i] == 0) if np.isfinite(prior_high.iloc[i]) else False,
                regime=bool(regime.get(dt, False)),
                atr_dec=float(atr_dec.at[dt, sym]) if dt in atr_dec.index else np.nan,
                ret20=r20, ret60=r60))
    ev = pd.DataFrame(rows)
    ev.attrs["atr_dec"] = atr_dec
    return ev


def layer_mask(ev: pd.DataFrame, k: int) -> pd.Series:
    m = pd.Series(True, index=ev.index)
    if k >= 1:
        m &= ev.rs_pctl >= RS_PCTL
    if k >= 2:
        m &= ev.volr >= VOL_MULT
    if k >= 3:
        m &= ev.regime
    if k >= 4:
        m &= ev.base_ok
    return m


def perm_p_within_date(sub: pd.DataFrame, label: np.ndarray, vals: np.ndarray,
                       observed: float) -> float:
    """日内置换：每个日期内部打乱标签，当日市场效应被条件掉。"""
    rng = np.random.default_rng(SEED)
    days = sub.date.values
    order = np.argsort(days, kind="stable")
    d_sorted = days[order]
    starts = np.searchsorted(d_sorted, np.unique(d_sorted), side="left")
    ends = np.searchsorted(d_sorted, np.unique(d_sorted), side="right")
    lab = label[order].copy()
    val = vals[order]
    # 只有同时含两类的日期才提供信息
    seg = [(a, b) for a, b in zip(starts, ends) if 0 < lab[a:b].sum() < (b - a)]
    if not seg:
        return float("nan")
    hits = 0
    for _ in range(ROUNDS):
        sh = lab.copy()
        for a, b in seg:
            sh[a:b] = rng.permutation(sh[a:b])
        A, B = val[sh == 1], val[sh == 0]
        if len(A) < 10 or len(B) < 10:
            continue
        if abs(A.mean() - B.mean()) >= abs(observed):
            hits += 1
    return hits / ROUNDS


def perm_p_date_block(sub: pd.DataFrame, label: np.ndarray, vals: np.ndarray,
                      observed: float) -> float:
    """整日块置换：日期层条件（大盘）用这个，把整天的事件一起换组。"""
    rng = np.random.default_rng(SEED)
    grp = sub.groupby("date")["_lab"]
    day_lab = grp.first().values            # 日期层条件：同一天的标签必然相同
    days = sub.date.values
    uniq = grp.first().index.values
    pos = {d: i for i, d in enumerate(uniq)}
    idx = np.array([pos[d] for d in days])
    hits = 0
    for _ in range(ROUNDS):
        sh = day_lab[rng.permutation(len(day_lab))][idx]
        A, B = vals[sh == 1], vals[sh == 0]
        if len(A) < 10 or len(B) < 10:
            continue
        if abs(A.mean() - B.mean()) >= abs(observed):
            hits += 1
    return hits / ROUNDS


def holm(ps: list[float]) -> list[float]:
    fin = [i for i, p in enumerate(ps) if np.isfinite(p)]
    order = sorted(fin, key=lambda i: ps[i])
    m, out, run = len(fin), [float("nan")] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        out[i] = run
    return out


def layer_stats(ev: pd.DataFrame, col: str = "ret20") -> list[dict]:
    rows = []
    for k in range(1, 5):
        prev = ev[layer_mask(ev, k - 1) & ev[col].notna()].copy()
        inn = layer_mask(prev, k).values
        if inn.sum() < 20 or (~inn).sum() < 20:
            rows.append(dict(layer=LAYERS[k], n_in=int(inn.sum()), skip="样本不足"))
            continue
        vals = prev[col].values
        diff = float(vals[inn].mean() - vals[~inn].mean())
        prev["_lab"] = inn.astype(int)
        prev = prev.sort_values("date", kind="stable")
        if LAYER_KIND[k] == "symbol":
            p = perm_p_within_date(prev, prev._lab.values, prev[col].values, diff)
            how = "日内置换"
        else:
            p = perm_p_date_block(prev, prev._lab.values, prev[col].values, diff)
            how = "整日块置换"
        d_in = prev.loc[prev._lab == 1, "date"].nunique()
        d_out = prev.loc[prev._lab == 0, "date"].nunique()
        sd = float(prev[col].std(ddof=1))
        floor = Z80 * sd * np.sqrt(1 / max(d_in, 1) + 1 / max(d_out, 1))
        rows.append(dict(layer=LAYERS[k], how=how,
                         n_in=int(inn.sum()), n_out=int((~inn).sum()),
                         d_in=int(d_in), d_out=int(d_out),
                         mean_in=float(vals[inn].mean()), mean_out=float(vals[~inn].mean()),
                         diff=diff, p=p, floor=float(floor)))
    for r, ph in zip(rows, holm([r.get("p", float("nan")) for r in rows])):
        r["p_holm"] = ph
    return rows


def random_control(ev: pd.DataFrame, uni: dict[str, pd.DataFrame]) -> pd.Series:
    """对照②：同日期、同 ATR% 十分位的随机入场，出场规则完全相同。

    返回**逐事件配对**的随机对照收益（index 与 ev 对齐）。配对而不是只给均值，是为了
    能算「突破相对随机入场的超额」——这一项是本实验的照妖镜：如果某一层的增量在
    随机对照上同样出现，那层量到的就是**大盘 beta**，不是突破的边际。
    """
    rng = np.random.default_rng(SEED)
    atr_dec = ev.attrs["atr_dec"]
    cache: dict[tuple, list[str]] = {}
    out = pd.Series(np.nan, index=ev.index, dtype=float)
    for r in ev.itertuples():
        if not np.isfinite(r.atr_dec):
            continue
        dec = int(min(9, max(0, int(r.atr_dec * 10))))
        key = (r.date, dec)
        if key not in cache:
            if r.date in atr_dec.index:
                row = atr_dec.loc[r.date]
                lo, hi = dec / 10, (dec + 1) / 10
                cache[key] = [sy for sy, v in row.items()
                              if np.isfinite(v) and lo <= v < hi and sy in uni]
            else:
                cache[key] = []
        pool = cache[key]
        if not pool:
            continue
        d = uni[pool[rng.integers(len(pool))]]
        if r.date not in d.index:
            continue
        rr = exit_return(d, int(d.index.get_loc(r.date)), HOLD_BARS)
        if rr is not None:
            out.at[r.Index] = rr
    return out


def spread_stats(ev: pd.DataFrame) -> list[dict]:
    """逐层「突破 − 同日同波动率随机入场」的超额，以及它的逐层增量。

    主判据看的是各层净收益的增量；这里看的是**超额**的增量。两者结论不一致时，
    以超额为准——净收益的增量可能只是入场日期分布变了（大盘好的日子里什么都涨）。
    """
    rows = []
    for k in range(1, 5):
        prev = ev[layer_mask(ev, k - 1) & ev.spread.notna()].copy()
        inn = layer_mask(prev, k).values
        if inn.sum() < 20 or (~inn).sum() < 20:
            rows.append(dict(layer=LAYERS[k], skip="样本不足")); continue
        vals = prev.spread.values
        diff = float(vals[inn].mean() - vals[~inn].mean())
        prev["_lab"] = inn.astype(int)
        prev = prev.sort_values("date", kind="stable")
        if LAYER_KIND[k] == "symbol":
            pv = perm_p_within_date(prev, prev._lab.values, prev.spread.values, diff)
        else:
            pv = perm_p_date_block(prev, prev._lab.values, prev.spread.values, diff)
        rows.append(dict(layer=LAYERS[k], n_in=int(inn.sum()),
                         mean_in=float(vals[inn].mean()), mean_out=float(vals[~inn].mean()),
                         diff=diff, p=pv))
    for r, ph in zip(rows, holm([r.get("p", float("nan")) for r in rows])):
        r["p_holm"] = ph
    return rows


def main() -> int:
    t0 = datetime.now()
    uni = load_universe()
    ev = build_events(uni)
    if ev.empty:
        print("无事件"); return 1
    att = ev.attrs
    ev_full = ev.copy()
    span = f"{ev.date.min():%Y-%m-%d} → {ev.date.max():%Y-%m-%d}"
    dates_all = sorted({d for s in uni.values() for d in (s.index.min(), s.index.max())})

    print("=" * 94)
    print("CAN SLIM 技术半套（L/S/M/基底）叠在 252 日突破上 —— 预注册实验")
    print(f"跑于 {t0:%Y-%m-%d %H:%M:%S}  seed={SEED}  置换 {ROUNDS} 轮")
    print(f"数据源：data/*_1d.csv（本地日线，IB ADJUSTED_LAST 为主）")
    print(f"universe：{len(uni)} 个标的（≥{MIN_BARS} 根日线，**非时点化，有幸存者偏差**）")
    print(f"价格区间：{min(dates_all):%Y-%m-%d} → {max(dates_all):%Y-%m-%d}；事件区间：{span}")
    print(f"冻结参数：RS≥{RS_PCTL:.0%}  量≥{VOL_MULT}×20日均量  QQQ>SMA200  "
          f"基底{BASE_LOOKBACK}日  止损−{STOP_PCT:.1%}  持有{HOLD_BARS}日  成本{COST_RT:.2%}双边")
    print("=" * 94)

    und = int(ev.ret20.isna().sum())
    print(f"\n突破事件：{len(ev)} 条 / {ev.date.nunique()} 个日期 / {ev.sym.nunique()} 个标的"
          f"（其中 {und} 条因数据不足 {HOLD_BARS} 日未决，已剔除）")

    print("\n── 逐层规模与单笔净收益（持有 20 日）──")
    print(f"{'层':<14}{'事件数':>8}{'日期数':>8}{'均值':>9}{'中位':>9}{'胜率':>7}"
          f"{'随机对照':>10}{'超额':>10}")
    ev["spread"] = ev.ret20 - random_control(ev_full, uni)
    for k in range(5):
        s = ev[layer_mask(ev, k) & ev.ret20.notna()]
        if s.empty:
            continue
        rnd = (s.ret20 - s.spread).mean()
        print(f"{LAYERS[k]:<14}{len(s):>8}{s.date.nunique():>8}{s.ret20.mean():>+9.4f}"
              f"{s.ret20.median():>+9.4f}{(s.ret20 > 0).mean():>7.0%}{rnd:>+10.4f}"
              f"{s.spread.mean():>+10.4f}")

    print("\n── 主判据：每层对上一层的增量（Holm m=4）──")
    rows = layer_stats(ev, "ret20")
    print(f"{'层':<14}{'置换法':<10}{'入选':>7}{'落选':>7}{'入选日':>7}{'落选日':>7}"
          f"{'均值差':>9}{'下限':>8}{'p':>8}{'Holm':>8}")
    for r in rows:
        if r.get("skip"):
            print(f"{r['layer']:<14}{r['skip']}")
            continue
        print(f"{r['layer']:<14}{r['how']:<10}{r['n_in']:>7}{r['n_out']:>7}"
              f"{r['d_in']:>7}{r['d_out']:>7}{r['diff']:>+9.4f}{r['floor']:>8.4f}"
              f"{r['p']:>8.4f}{r['p_holm']:>8.4f}")
    verdict = [r for r in rows if not r.get("skip")]
    passed = [r for r in verdict if np.isfinite(r["p_holm"]) and r["p_holm"] < P_THRESHOLD
              and r["diff"] > 0]
    print(f"\n  Holm 后 p<{P_THRESHOLD} 且方向为正的层：{len(passed)}/{len(verdict)}"
          + ("  → " + ", ".join(r["layer"] for r in passed) if passed else ""))
    invisible = [r for r in verdict if abs(r["diff"]) < r["floor"]]
    if invisible:
        print(f"  ⚠ 效应小于 80% 功效可检出下限（「看不见」，不等于「无效应」）："
              + ", ".join(f"{r['layer']}(|{r['diff']:+.4f}|<{r['floor']:.4f})" for r in invisible))

    print("\n── 对照②：超额（突破 − 同日同波动率随机入场）的逐层增量 ──")
    print(f"{'层':<14}{'入选超额':>10}{'落选超额':>10}{'增量':>10}{'p':>8}{'Holm':>8}")
    for r in spread_stats(ev):
        if r.get("skip"):
            print(f"{r['layer']:<14}{r['skip']}"); continue
        print(f"{r['layer']:<14}{r['mean_in']:>+10.4f}{r['mean_out']:>+10.4f}"
              f"{r['diff']:>+10.4f}{r['p']:>8.4f}{r['p_holm']:>8.4f}")

    print("\n── 稳健性①：持有 60 日（不进判据）──")
    for r in layer_stats(ev, "ret60"):
        if r.get("skip"):
            print(f"{r['layer']:<14}{r['skip']}"); continue
        print(f"{r['layer']:<14}均值差{r['diff']:>+9.4f}  p={r['p']:.4f}  Holm={r['p_holm']:.4f}")

    print(f"\n── 稳健性②：剔除 {EXCLUDE_YEARS} 后 ──")
    ev2 = ev[~ev.date.dt.year.isin(EXCLUDE_YEARS)].copy()
    ev2.attrs["atr_dec"] = att["atr_dec"]
    print(f"剩 {len(ev2)} 条 / {ev2.date.nunique()} 个日期")
    for r in layer_stats(ev2, "ret20"):
        if r.get("skip"):
            print(f"{r['layer']:<14}{r['skip']}"); continue
        print(f"{r['layer']:<14}均值差{r['diff']:>+9.4f}  p={r['p']:.4f}  Holm={r['p_holm']:.4f}")

    print("\n── 稳健性③：逐年同向比例（每层增量的年度符号）──")
    yrs = sorted(ev.date.dt.year.unique())
    print(f"{'层':<14}" + "".join(f"{y:>7}" for y in yrs) + f"{'同向':>8}")
    for k in range(1, 5):
        cells, pos, tot = [], 0, 0
        for y in yrs:
            e = ev[(ev.date.dt.year == y) & ev.ret20.notna()]
            prev = e[layer_mask(e, k - 1)]
            inn = layer_mask(prev, k).values
            if inn.sum() < 5 or (~inn).sum() < 5:
                cells.append("     ·"); continue
            dd = prev.ret20.values[inn].mean() - prev.ret20.values[~inn].mean()
            cells.append(f"{dd:>+7.3f}"); tot += 1; pos += dd > 0
        print(f"{LAYERS[k]:<14}" + "".join(cells) + f"{f'{pos}/{tot}':>8}")

    print(f"\n完成，耗时 {(datetime.now() - t0).total_seconds():.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())

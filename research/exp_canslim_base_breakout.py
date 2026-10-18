"""CAN SLIM 第二轮：把买点换成原文的「整理区最高价」，重问同样的三层 —— 预注册。

═══ 为什么要有这一轮 ═══
第一轮（`exp_canslim_technical.py`，2026-10-18）把 L/S/M/基底叠在本仓库既有的
**252 日新高**突破上，结论是 L/S/基底 无证据、M 通过但生产早有。读完原视频后发现
一处定义偏差，它足以限定上一轮结论的适用范围：

> 画面原文：买点是「**冲过整理区最高价**」，整理区标注「横盘整理几周」，
> 那条红虚线**明显低于全图最高点**——它是几周的局部高点，不是 252 日新高。

252 日新高是个**严格得多**的门槛。所以上一轮测的是「252 日新高 + 四个条件」，
**不是欧奈尔原版的 base breakout**。本轮换买点定义重做，看结论是否翻转。

═══ 预注册（施工前冻结，跑完不许改参数/窗口/出场再跑）═══
**整理区（base）定义**，全部取自原文可量化的部分 + 欧奈尔的常规约定：
    BASE_W      = 15 个交易日（原文「横盘整理几周」≈3 周）
    MAX_DEPTH   = 25%   基底区间 (最高-最低)/最高 ≤ 25%（欧奈尔杯柄常见 15–33%，取中）
    PRIOR_RUNUP = +20%  基底形成前 60 个交易日涨幅（欧奈尔要求 base 之前有上涨段）
    买点        = 收盘 > 基底区间最高 High（pivot）
    去重        = 前 15 个交易日内已触发过则不再计（同一个基底只买一次）

**三层叠加**（基底已进入买点定义本身，故不再有第四层，m = 3）：
    L0  裸基底突破
    L1  + L 相对强度：252 日收益全 universe 横截面百分位 ≥ 80
    L2  + S 放量：突破日成交量 ≥ 20 日均量 × 1.4（画面原文「成交量 +40% 以上」）
    L3  + M 大盘：QQQ 收盘 > 其 SMA200

H1–H3：每加一层，单笔净收益均值高于上一层。Holm m=3，判据 p<0.05。

**另报（不进 Holm 家族，口径不同，标为描述性）**：新买点的裸信号 vs 上一轮
252 日新高的裸信号——这是「换买点定义会不会改变结论」的直接回答。

═══ 与第一轮完全相同的部分（不许动）═══
出场：入场=突破日收盘；固定 −7.5% 止损（跳空低开按 Open 成交）；未触发则持有
20 交易日收盘出；60 日作稳健性不进判据；双边成本 20bps。
统计：标的层条件用**日内置换**、日期层条件用**整日块置换**；功效下限按**不同日期数**
算；剔除 2020–2021；逐年同向比例。universe、数据源、幸存者偏差声明同第一轮。

═══ 仍未测、本轮也不测 ═══
- C/A/N/I 四条基本面：无数据源。
- **「领头羊」（每个行业只挑最强的一两只）**：原文 L 的一半。本仓库 `sector_map.py`
  只覆盖已路由标的，盖不住 2,409 个池子；逐个拉行业分类需要 2,409 次外部请求，
  本轮不做。**所以本轮的 L 仍然是「全市场 RS≥80」，比原文宽松。**
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ── 冻结参数 ────────────────────────────────────────────────────────────────
BASE_W       = 15        # 整理区长度（交易日）
MAX_DEPTH    = 0.25      # 整理区深度上限
PRIOR_RUNUP  = 0.20      # 基底前 60 日涨幅下限
RUNUP_LOOKBACK = 60
RS_PCTL      = 0.80
VOL_MULT     = 1.40
STOP_PCT     = 0.075
HOLD_BARS    = 20
HOLD_BARS_ALT = 60
COST_RT      = 0.0020
MIN_BARS     = 300
MIN_XSEC     = 100
ROUNDS       = 5000
SEED         = 20261018
Z80          = 1.959964 + 0.841621
P_THRESHOLD  = 0.05
EXCLUDE_YEARS = (2020, 2021)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from breakout_backtest import compute_breakout_signals          # noqa: E402  仅用于对照旧买点
from exp_canslim_technical import (                              # noqa: E402  复用第一轮的口径
    exit_return, holm, load_universe, perm_p_date_block, perm_p_within_date)

LAYERS = ["L0 裸基底突破", "L1 +相对强度", "L2 +放量", "L3 +大盘"]
LAYER_KIND = {1: "symbol", 2: "symbol", 3: "date"}


def base_breakout_flags(d: pd.DataFrame) -> pd.Series:
    """整理区突破：收盘 > 前 BASE_W 日最高 High，且该区间够窄、之前有上涨段。"""
    base_high = d["High"].rolling(BASE_W).max().shift(1)
    base_low = d["Low"].rolling(BASE_W).min().shift(1)
    depth = (base_high - base_low) / base_high
    runup = d["Close"].shift(BASE_W + 1) / d["Close"].shift(BASE_W + 1 + RUNUP_LOOKBACK) - 1
    raw = (d["Close"] > base_high) & (depth <= MAX_DEPTH) & (runup >= PRIOR_RUNUP)
    raw = raw.fillna(False)
    # 同一个基底只买一次：前 BASE_W 日内已触发过就跳过
    out = np.zeros(len(raw), dtype=bool)
    last = -10 ** 9
    vals = raw.values
    for i in range(len(vals)):
        if vals[i] and i - last >= BASE_W:
            out[i] = True
            last = i
    return pd.Series(out, index=d.index)


def build_events(uni: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    r252 = pd.concat({s: d["Close"] / d["Close"].shift(252) - 1 for s, d in uni.items()}, axis=1)
    pctl = r252.rank(axis=1, pct=True)
    xsec_n = r252.notna().sum(axis=1)
    atrp = pd.concat({s: ((d["High"] - d["Low"]).rolling(20).mean() / d["Close"])
                      for s, d in uni.items()}, axis=1)
    atr_dec = atrp.rank(axis=1, pct=True)
    qqq = uni["QQQ"]
    regime = (qqq["Close"] > qqq["Close"].rolling(200).mean())

    rows, old_rows = [], []
    for sym, d in uni.items():
        volavg = d["Volume"].replace(0, np.nan).rolling(20).mean()
        volr = d["Volume"] / volavg
        new_bo = base_breakout_flags(d)
        old_bo = compute_breakout_signals(d, {"confirm_days": 1})["breakout"].astype(bool)
        for tag, flags, sink in (("new", new_bo, rows), ("old", old_bo, old_rows)):
            for i in np.where(flags.values)[0]:
                dt = d.index[i]
                if xsec_n.get(dt, 0) < MIN_XSEC or dt not in pctl.index:
                    continue
                p = pctl.at[dt, sym]
                if not np.isfinite(p):
                    continue
                sink.append(dict(
                    sym=sym, date=dt, rs_pctl=float(p),
                    volr=float(volr.iloc[i]) if np.isfinite(volr.iloc[i]) else np.nan,
                    regime=bool(regime.get(dt, False)),
                    atr_dec=float(atr_dec.at[dt, sym]) if dt in atr_dec.index else np.nan,
                    ret20=exit_return(d, int(i), HOLD_BARS),
                    ret60=exit_return(d, int(i), HOLD_BARS_ALT)))
    ev = pd.DataFrame(rows)
    ev.attrs["atr_dec"] = atr_dec
    return ev, pd.DataFrame(old_rows)


def layer_mask(ev: pd.DataFrame, k: int) -> pd.Series:
    m = pd.Series(True, index=ev.index)
    if k >= 1:
        m &= ev.rs_pctl >= RS_PCTL
    if k >= 2:
        m &= ev.volr >= VOL_MULT
    if k >= 3:
        m &= ev.regime
    return m


def layer_stats(ev: pd.DataFrame, col: str = "ret20") -> list[dict]:
    rows = []
    for k in range(1, 4):
        prev = ev[layer_mask(ev, k - 1) & ev[col].notna()].copy()
        inn = layer_mask(prev, k).values
        if inn.sum() < 20 or (~inn).sum() < 20:
            rows.append(dict(layer=LAYERS[k], skip="样本不足")); continue
        vals = prev[col].values
        diff = float(vals[inn].mean() - vals[~inn].mean())
        prev["_lab"] = inn.astype(int)
        prev = prev.sort_values("date", kind="stable")
        fn = perm_p_within_date if LAYER_KIND[k] == "symbol" else perm_p_date_block
        p = fn(prev, prev._lab.values, prev[col].values, diff)
        d_in = prev.loc[prev._lab == 1, "date"].nunique()
        d_out = prev.loc[prev._lab == 0, "date"].nunique()
        sd = float(prev[col].std(ddof=1))
        rows.append(dict(layer=LAYERS[k],
                         how="日内置换" if LAYER_KIND[k] == "symbol" else "整日块置换",
                         n_in=int(inn.sum()), n_out=int((~inn).sum()),
                         d_in=int(d_in), d_out=int(d_out),
                         mean_in=float(vals[inn].mean()), mean_out=float(vals[~inn].mean()),
                         diff=diff, p=p,
                         floor=float(Z80 * sd * np.sqrt(1 / max(d_in, 1) + 1 / max(d_out, 1)))))
    for r, ph in zip(rows, holm([r.get("p", float("nan")) for r in rows])):
        r["p_holm"] = ph
    return rows


def main() -> int:
    t0 = datetime.now()
    uni = load_universe()
    ev, old = build_events(uni)
    if ev.empty:
        print("无事件"); return 1

    print("=" * 94)
    print("CAN SLIM 第二轮：买点换成「整理区最高价」 —— 预注册实验")
    print(f"跑于 {t0:%Y-%m-%d %H:%M:%S}  seed={SEED}  置换 {ROUNDS} 轮")
    print("数据源：data/*_1d.csv（本地日线，IB ADJUSTED_LAST 为主）")
    print(f"universe：{len(uni)} 个标的（≥{MIN_BARS} 根日线，**非时点化，有幸存者偏差**）")
    print(f"事件区间：{ev.date.min():%Y-%m-%d} → {ev.date.max():%Y-%m-%d}")
    print(f"冻结参数：基底{BASE_W}日 深度≤{MAX_DEPTH:.0%} 前涨≥{PRIOR_RUNUP:.0%}/{RUNUP_LOOKBACK}日"
          f"  RS≥{RS_PCTL:.0%}  量≥{VOL_MULT}×  QQQ>SMA200"
          f"  止损−{STOP_PCT:.1%}  持有{HOLD_BARS}日  成本{COST_RT:.2%}双边")
    print("未测：C/A/N/I（无数据源）、「领头羊」行业内排名（无行业分类）")
    print("=" * 94)

    print(f"\n── 描述性：新买点 vs 旧买点（裸信号，出场完全相同，不进 Holm 家族）──")
    a = ev[ev.ret20.notna()]; b = old[old.ret20.notna()]
    print(f"{'买点定义':<22}{'事件数':>9}{'日期数':>8}{'标的数':>8}{'均值':>9}{'中位':>9}{'胜率':>7}")
    print(f"{'整理区最高价（本轮）':<22}{len(a):>9}{a.date.nunique():>8}{a.sym.nunique():>8}"
          f"{a.ret20.mean():>+9.4f}{a.ret20.median():>+9.4f}{(a.ret20 > 0).mean():>7.0%}")
    print(f"{'252 日新高（上一轮）':<22}{len(b):>9}{b.date.nunique():>8}{b.sym.nunique():>8}"
          f"{b.ret20.mean():>+9.4f}{b.ret20.median():>+9.4f}{(b.ret20 > 0).mean():>7.0%}")

    print("\n── 逐层规模与单笔净收益（持有 20 日）──")
    print(f"{'层':<16}{'事件数':>9}{'日期数':>8}{'均值':>9}{'中位':>9}{'胜率':>7}")
    for k in range(4):
        s = ev[layer_mask(ev, k) & ev.ret20.notna()]
        if s.empty:
            continue
        print(f"{LAYERS[k]:<16}{len(s):>9}{s.date.nunique():>8}{s.ret20.mean():>+9.4f}"
              f"{s.ret20.median():>+9.4f}{(s.ret20 > 0).mean():>7.0%}")

    print("\n── 主判据：每层对上一层的增量（Holm m=3）──")
    rows = layer_stats(ev, "ret20")
    print(f"{'层':<16}{'置换法':<10}{'入选':>8}{'落选':>8}{'入选日':>7}{'落选日':>7}"
          f"{'均值差':>9}{'下限':>8}{'p':>8}{'Holm':>8}")
    for r in rows:
        if r.get("skip"):
            print(f"{r['layer']:<16}{r['skip']}"); continue
        print(f"{r['layer']:<16}{r['how']:<10}{r['n_in']:>8}{r['n_out']:>8}"
              f"{r['d_in']:>7}{r['d_out']:>7}{r['diff']:>+9.4f}{r['floor']:>8.4f}"
              f"{r['p']:>8.4f}{r['p_holm']:>8.4f}")
    done = [r for r in rows if not r.get("skip")]
    ok = [r for r in done if np.isfinite(r["p_holm"]) and r["p_holm"] < P_THRESHOLD and r["diff"] > 0]
    print(f"\n  Holm 后 p<{P_THRESHOLD} 且方向为正：{len(ok)}/{len(done)}"
          + ("  → " + ", ".join(r["layer"] for r in ok) if ok else ""))
    inv = [r for r in done if abs(r["diff"]) < r["floor"]]
    if inv:
        print("  ⚠ 效应小于 80% 功效可检出下限（「看不见」≠「无效应」）："
              + ", ".join(f"{r['layer']}(|{r['diff']:+.4f}|<{r['floor']:.4f})" for r in inv))

    print("\n── 稳健性①：持有 60 日（不进判据）──")
    for r in layer_stats(ev, "ret60"):
        if r.get("skip"):
            print(f"{r['layer']:<16}{r['skip']}"); continue
        print(f"{r['layer']:<16}均值差{r['diff']:>+9.4f}  p={r['p']:.4f}  Holm={r['p_holm']:.4f}")

    print(f"\n── 稳健性②：剔除 {EXCLUDE_YEARS} 后 ──")
    ev2 = ev[~ev.date.dt.year.isin(EXCLUDE_YEARS)].copy()
    print(f"剩 {len(ev2)} 条 / {ev2.date.nunique()} 个日期")
    for r in layer_stats(ev2, "ret20"):
        if r.get("skip"):
            print(f"{r['layer']:<16}{r['skip']}"); continue
        print(f"{r['layer']:<16}均值差{r['diff']:>+9.4f}  p={r['p']:.4f}  Holm={r['p_holm']:.4f}")

    print("\n── 稳健性③：逐年同向比例 ──")
    yrs = sorted(ev.date.dt.year.unique())
    print(f"{'层':<16}" + "".join(f"{y:>7}" for y in yrs) + f"{'同向':>8}")
    for k in range(1, 4):
        cells, pos, tot = [], 0, 0
        for y in yrs:
            e = ev[(ev.date.dt.year == y) & ev.ret20.notna()]
            prev = e[layer_mask(e, k - 1)]
            inn = layer_mask(prev, k).values
            if inn.sum() < 5 or (~inn).sum() < 5:
                cells.append("     ·"); continue
            dd = prev.ret20.values[inn].mean() - prev.ret20.values[~inn].mean()
            cells.append(f"{dd:>+7.3f}"); tot += 1; pos += dd > 0
        print(f"{LAYERS[k]:<16}" + "".join(cells) + f"{f'{pos}/{tot}':>8}")

    print(f"\n完成，耗时 {(datetime.now() - t0).total_seconds():.0f} 秒")
    return 0


if __name__ == "__main__":
    sys.exit(main())

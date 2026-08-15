"""广度 × **股票信号台账** —— 换靶子重问（2026-08-14）。

═══ 为什么之前问错了 ═══
前几轮我一直把广度拿去预测 **NQ/ES 指数的前向收益**。那个问法的观测单位是
「一次回调」：8 年样本里 osc≤−70 只有 **97 天 / 45 段 / 约 22 次独立事件**，
在 22 次事件上分辨 3pp 的效应本来就做不到（见 `LEARNING.md` 2026-08-14 再更正）。

**广度是股票市场内部结构指标，它的自然靶子是股票系统，不是指数期货。**
`quantrift_stock` 有 `logs/backfill_signal_log.csv`——**22,851 条带实现结果的信号台账**
（`outcome` / `r_mult` / `bars` / `exit_date`），101 个标的、2016-09 → 2026-07。
与广度数据重叠 **22,202 条**。观测单位从「回调」换成「信号」，样本量差两个数量级。

═══ ⚠️ 但信号数 ≠ 有效样本（这是我前面栽过的同一个坑）═══
同一天几十个标的一起触发，共用同一个广度值，且当日结果高度相关（市场同涨同跌）。
**有效样本是不同日期数，不是信号数**：

    Confluence  7,376 信号 / **1,153 天**（每日均 6.4 条）
    RSI2        8,716 信号 / **1,056 天**（每日均 8.3 条）
    RSI2_IBS    4,860 信号 /   850 天
    Breakout52W   762 信号 /   383 天
    MRVL_shadow   424 信号 /   329 天

⇒ 统计一律用**按日期分块的置换检验**（整天的信号一起换组），
不用逐信号置换——后者会把有效样本虚报 6-8 倍。

═══ 命题：两类策略对广度的反应**方向必须相反** ═══
这是有机制的可证伪预测，不是扫参数：

  **均值回归类**（RSI2 / RSI2_IBS / MRVL_WideExit）
      低广度 = 市场洗盘 ⇒ 买进去的是超卖 ⇒ **前向 R 应更高**
  **突破/动量类**（Breakout52W / RKLB_Breakout）
      低广度 = 参与度稀薄 ⇒ 突破缺乏跟随 ⇒ **前向 R 应更低**
  **Confluence**（多指标共振，两种成分都有）
      **不做方向预测**，只报数，不进核心判据。

**如果两类是同号的，命题就错了** —— 那说明量到的是「广度低之后市场整体涨/跌」
这个 beta，不是「广度改变了这类策略的成败」。**这一条是本轮的照妖镜。**

═══ 防前视 ═══
广度收盘后才可得 ⇒ 一律用 `osc[t−1]`（信号 bar 的**前一交易日**）。
1h/4h 信号在盘中触发，当日广度当时根本不存在，用 t−1 是唯一正确的。

═══ 判据（施工前冻结）═══
    G1 **方向相反**：MR 类端点差（Q1−Q5，低广度减高广度）> 0
                     且 突破类 < 0                       ← 核心
    G2 显著：**日期块置换** p < 0.05（Holm 跨全部被检验的策略）
    G3 一致：MR 三条腿 ≥2 条同向；突破类两条腿同向
    G4 量级：端点差 ≥ **0.10 R**（低于此即使显著也没有操作价值）
任一不过即判负；G1 不过则命题直接被证伪，不必看其余。

**功效一并报告**：按有效样本（不同日期数）算可检出下限，
低于下限的效应一律标注「看不见」，不得当作「无效应」——
这是 08-14 补算 NYMO 下限时学到的，本轮**在跑之前**就装上。

═══ 数据源 ═══
广度：`breadth_common_nyse_daily.csv`（**经典 NYMO 口径**，NYSE 普通股，
      用 Nasdaq 官方证券目录剔除 ETF，日均 1,894 只）为主口径；
      `breadth_common_all_daily.csv`（全市场普通股）作并列对照。
信号：`~/Documents/quantrift_stock/logs/backfill_signal_log.csv`（只读）。

═══ 结果（2026-08-14）═══
**预注册命题被证伪**：MR 类端点差 −0.003 / +0.061 / −0.578 R（方向不一致），
突破类 −0.336 R ⇒ **两类不相反，G1 不过**。
⇒ 「广度可作 MR 的择时过滤」在股票系统上同样不成立，**这条判负站得住**。

**但预注册为「中性、不进判据」的 Confluence 显出东西**：

    逐档均值 R  Q1(广度最低) +0.169 | +0.489 | +0.391 | +0.414 | Q5 +0.571
    端点差 −0.402 R，n=7,374 信号 / **1,152 天**，日期块置换 p=0.0000，Holm <0.01
    两个广度 universe 都复现（common_all −0.323，p=0.0014）

稳健性：剔除 2020 → −0.412；再剔 2022 → −0.450（**非危机年驱动**）。
逐年 **5/6 同向**（2022 熊市是唯一反号年 +0.908）。

⭐ **关键控制——它不是「前一日大盘跌」的马甲**：ρ(广度, 前一日大盘收益)=0.394；
在前一日大盘收益的每个五分位内部再切广度，组内端点差
−0.227 / −0.243 / −0.389 / −0.065 / −0.123，**5/5 同向，均值 −0.209 R**
⇒ 约一半由前一日大盘收益解释，**另一半是广度的增量信息**。
**本项目「压力指标先做基准匹配」纪律下第一个挺过匹配的广度结果。**

⚠️ **但它是 post-hoc**（本轮明确预注册为不进判据），按纪律只能算
**待独立检验的假设**，不得据此改任何东西。方向是「广度高时更好」=
**参与度确认**，属广度惯例用法，恰恰不是一直在测的「超卖反转」。
口径就此冻结为 `Confluence × osc[t−1] 五分位 × 日期块置换`，**不许再扫**。

纯离线，不连 IB，不改任何项目的生产文件。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

LEDGER = Path.home() / "Documents/quantrift_stock/logs/backfill_signal_log.csv"
BREADTH = {
    "common_nyse": BASE / "research/data_external/breadth_common_nyse_daily.csv",
    "common_all": BASE / "research/data_external/breadth_common_all_daily.csv",
}
MR_STRATS = ("RSI2", "RSI2_IBS_shadow", "MRVL_WideExit_shadow")
BREAKOUT_STRATS = ("Breakout52W", "RKLB_Breakout_shadow")
NEUTRAL_STRATS = ("Confluence",)
N_BINS = 5
MIN_SIGNALS = 200
MIN_DATES = 100
EFFECT_GATE = 0.10          # R
P_THRESHOLD = 0.05
ROUNDS = 5000
SEED = 20260814
Z80 = 1.959964 + 0.841621


def load_breadth(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    d = d[d[["adv", "dec"]].sum(axis=1) > 0].reset_index(drop=True)
    # 防前视：t 日信号只能用 t−1 收盘后可得的广度
    d["osc_prev"] = d["osc"].shift(1)
    return d.dropna(subset=["osc_prev"])[["date", "osc_prev"]]


def load_signals() -> pd.DataFrame:
    d = pd.read_csv(LEDGER)
    d["bar_date"] = pd.to_datetime(d["bar_date"], errors="coerce", utc=True).dt.tz_localize(None)
    d = d[d["bar_date"].notna() & d["r_mult"].notna()].copy()
    d["day"] = d["bar_date"].dt.normalize()
    return d


def date_block_permutation_p(day_bin: pd.Series, values: pd.Series, days: pd.Series,
                             observed: float, rounds: int = ROUNDS,
                             seed: int = SEED) -> float:
    """把**整天**的信号一起换组，保留同日相关性。

    逐信号置换会假装同一天的 8 条信号是 8 个独立观测，
    从而把有效样本虚报 6-8 倍、p 值严重偏小。
    """
    uniq = day_bin.index.to_numpy()
    bins = day_bin.to_numpy()
    rng = np.random.default_rng(seed)
    day_arr = days.to_numpy()
    val = values.to_numpy()
    pos = {d: i for i, d in enumerate(uniq)}
    idx = np.array([pos[d] for d in day_arr])
    hits = 0
    for _ in range(rounds):
        shuffled = bins[rng.permutation(len(bins))]
        b = shuffled[idx]
        lo, hi = val[b == 1], val[b == N_BINS]
        if len(lo) < 10 or len(hi) < 10:
            continue
        if abs(lo.mean() - hi.mean()) >= abs(observed):
            hits += 1
    return hits / rounds


def analyse(sig: pd.DataFrame, br: pd.DataFrame, strat: str) -> dict | None:
    s = sig[sig["strategy"] == strat].merge(
        br.rename(columns={"date": "day"}), on="day", how="inner")
    if len(s) < MIN_SIGNALS or s["day"].nunique() < MIN_DATES:
        return None
    # 分档按**日期**切，不按信号切——否则信号多的日子会主导分档边界
    per_day = s.groupby("day")["osc_prev"].first()
    day_bin = pd.Series(
        pd.qcut(per_day, N_BINS, labels=range(1, N_BINS + 1), duplicates="drop"),
        index=per_day.index).astype(int)
    s["bin"] = s["day"].map(day_bin)

    lo = s.loc[s["bin"] == 1, "r_mult"]
    hi = s.loc[s["bin"] == N_BINS, "r_mult"]
    diff = float(lo.mean() - hi.mean())
    p = date_block_permutation_p(day_bin, s["r_mult"], s["day"], diff)

    # 可检出下限按**有效样本 = 不同日期数**算，不按信号数
    n_lo_d = s.loc[s["bin"] == 1, "day"].nunique()
    n_hi_d = s.loc[s["bin"] == N_BINS, "day"].nunique()
    sd = float(s["r_mult"].std(ddof=1))
    floor = Z80 * sd * np.sqrt(1 / max(n_lo_d, 1) + 1 / max(n_hi_d, 1))

    means = [float(s.loc[s["bin"] == b, "r_mult"].mean()) for b in range(1, N_BINS + 1)]
    return dict(strategy=strat, n=len(s), days=int(s["day"].nunique()),
                bin_means=means, diff=diff, p=p, floor=float(floor),
                win_lo=float((lo > 0).mean()), win_hi=float((hi > 0).mean()),
                n_lo=len(lo), n_hi=len(hi), days_lo=n_lo_d, days_hi=n_hi_d)


def holm(ps: list[float]) -> list[float]:
    fin = [i for i, p in enumerate(ps) if np.isfinite(p)]
    order = sorted(fin, key=lambda i: ps[i])
    m, out, run = len(fin), [float("nan")] * len(ps), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        out[i] = run
    return out


def main() -> int:
    if not LEDGER.exists():
        print(f"❌ 找不到股票信号台账：{LEDGER}")
        return 1
    sig = load_signals()
    print("═" * 92)
    print("广度 × 股票信号台账 —— 均值回归 vs 突破，方向必须相反")
    print("═" * 92)
    print(f"台账 {len(sig):,} 条（有 r_mult），{sig.symbol.nunique()} 个标的，"
          f"{sig.bar_date.min().date()} → {sig.bar_date.max().date()}")
    print("防前视：一律用 osc[t−1]；统计用**按日期分块**的置换检验\n")

    for src, path in BREADTH.items():
        if not path.exists():
            print(f"⚠️ 跳过 {src}：{path.name} 不存在")
            continue
        br = load_breadth(path)
        print("─" * 92)
        print(f"【广度口径 {src}】{'（经典 NYMO：NYSE 普通股）' if 'nyse' in src else '（全市场普通股）'}")
        print("─" * 92)
        rows = []
        for group, strats in (("均值回归", MR_STRATS), ("突破/动量", BREAKOUT_STRATS),
                              ("中性(不进判据)", NEUTRAL_STRATS)):
            for st in strats:
                r = analyse(sig, br, st)
                if r:
                    r["group"] = group
                    rows.append(r)
        if not rows:
            print("  样本不足，无可分析策略")
            continue
        for r, ph in zip(rows, holm([x["p"] for x in rows])):
            r["p_holm"] = ph

        print(f"{'组':<14}{'策略':<22}{'信号':>7}{'天数':>6}"
              f"{'Q1均值R':>9}{'Q5均值R':>9}{'端点差':>9}{'下限':>8}{'块置换p':>9}{'Holm':>8}")
        for r in rows:
            vis = "✅" if abs(r["diff"]) > r["floor"] else "看不见"
            print(f"{r['group']:<14}{r['strategy']:<22}{r['n']:>7,}{r['days']:>6}"
                  f"{r['bin_means'][0]:>+9.3f}{r['bin_means'][-1]:>+9.3f}"
                  f"{r['diff']:>+9.3f}{r['floor']:>8.3f}{r['p']:>9.4f}{r['p_holm']:>8.4f}"
                  f"  {vis}")

        print("\n  逐档均值 R（Q1=广度最低 … Q5=最高）：")
        for r in rows:
            print(f"    {r['strategy']:<22}" + "  ".join(f"{m:+.3f}" for m in r["bin_means"]))

        mr = [r for r in rows if r["group"] == "均值回归"]
        bo = [r for r in rows if r["group"] == "突破/动量"]
        print("\n  【G1 核心：方向是否相反】")
        mr_pos = sum(1 for r in mr if r["diff"] > 0)
        bo_neg = sum(1 for r in bo if r["diff"] < 0)
        print(f"    均值回归类端点差 > 0（低广度更好）：{mr_pos}/{len(mr)}")
        print(f"    突破类端点差 < 0（低广度更差）：    {bo_neg}/{len(bo)}")
        g1 = mr_pos >= max(2, (len(mr) + 1) // 2) and bo_neg >= max(1, (len(bo) + 1) // 2)
        print(f"    G1 {'✅ 方向相反，命题未被证伪' if g1 else '❌ 方向不相反 ⇒ 命题被证伪'}")
        if not g1:
            print("       ⇒ 若两类同号，量到的是「广度低之后市场整体怎么走」这个 beta，")
            print("          不是「广度改变了这类策略的成败」。**这就是照妖镜的作用。**")
            continue
        sig_ok = sum(1 for r in mr + bo
                     if np.isfinite(r["p_holm"]) and r["p_holm"] < P_THRESHOLD)
        big = sum(1 for r in mr + bo if abs(r["diff"]) >= EFFECT_GATE)
        vis = sum(1 for r in mr + bo if abs(r["diff"]) > r["floor"])
        print(f"  【G2 显著】Holm p<{P_THRESHOLD} 的：{sig_ok}/{len(mr)+len(bo)}")
        print(f"  【G4 量级】端点差 ≥{EFFECT_GATE} R 的：{big}/{len(mr)+len(bo)}"
              f"　（超过可检出下限的：{vis}）")
        print(f"  ⇒ {'✅ 全过，值得进入下一步' if (sig_ok and big) else '❌ 未全过'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

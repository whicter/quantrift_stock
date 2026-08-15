"""重建广度 —— 用**证券主数据**切出干净 universe（含真 NYMO 口径）。

═══ 为什么（2026-08-14，用户质疑「NYMO 机构广泛应用，怎么在你这里全败」）═══
复查查出两个**数据层面**的事实错误（与判据松紧无关）：

**① `XNAS.ITCH` 是「交易场所」不是「上市地」。** 它是 Nasdaq 的**场内成交**数据，
全美上市证券只要在 Nasdaq 成交都在里面，含 NYSE / ARCA 上市标的。
⇒ `build_nasdaq_breadth.py` 里「纳斯达克广度」这个名字**从一开始就是错的**。

**② universe 里近四成是 ETF。** 用 Nasdaq 官方证券目录比对实测：
    2026-08-07：11,254 标的 → 可分类 96%，**其中 ETF 4,398 个 = 全部的 39%**
    2018-05-01： 7,153 标的 → 可分类 58%，其中 ETF 1,149 个 = 全部的 16%
经典 NYMO 的 universe 是 **NYSE 普通股**，明确排除 ETF / 优先股 / 封闭式基金。
指数型 ETF 的日涨跌机械跟随指数 ⇒ 把四千多个这样的载体塞进涨跌家数，
等于把「指数自己」按上千票权重掺进「市场参与广度」，
**稀释掉广度本该测量的、指数之外的信息**。

**前一次修复尝试失败并被自己的验收拦下**（`build_breadth_common_only.py`）：
用「对市场因子 R² ≥ 0.75」判定指数型载体，15 个必剔 ETF 只认出 1 个
（SPY 0.689 / QQQ 0.518 / TLT 0.006 / GLD 0.023）——前提不成立，
因为市场因子取近万标的的横截面中位数 ≈ 等权小盘，而 SPY 是市值加权大盘。
**证券类型是事实，猜不出来，只能查表。**

═══ 数据源：Nasdaq 官方证券目录（免费、无需 key、已固化入库）═══
`research/data_external/nasdaq_symbol_directory_20260814.txt`
（源 `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt`，
13,143 行，管道分隔）。**固化快照，不做运行时抓取**——与 VVIX 同一纪律。
用到的列：`Symbol` / `ETF`（Y/N）/ `Listing Exchange`（N=NYSE, Q=Nasdaq,
P=ARCA, Z=BATS, A=NYSE American）/ `Test Issue`。

═══ 两个 universe（施工前冻结）═══
    common_all  ：ETF≠Y 且 Test Issue≠Y，**不限上市所** = 全市场普通股
    common_nyse ：再加 Listing Exchange=='N'  = **经典 NYMO 的原始 universe**

═══ ⚠️ 两条必须随结论一起报的限制 ═══
**① 目录是「当前快照」**，2018-2024 间退市的标的不在表里 ⇒ 越往前可分类率越低
（2018 年仅 58%）。脚本**逐年打印可分类率**，不许省略。

**② 无法分类的标的一律保留为普通股（进 `common_all`），但不进 `common_nyse`。**
这个不对称是刻意的：无法分类的绝大多数是**退市股**（多为经营性公司），
而 ETF 长寿、基本仍在表里。反过来「不认识就剔除」会把退市股一并剔掉，
**重新引入幸存者偏差**——那正是这份原始数据相对行业 ETF 代理的唯一优势。
代价是**早年 ETF 剔不干净**；因此 `common_nyse` 的早年样本偏保守，
且结论必须在覆盖率 >90% 的 2022+ 子段另行复核。

═══ 内置验收（不通过就不产出数据）═══
    必须判为 ETF：SPY QQQ IWM DIA VOO IVV XLF XLK TLT HYG GLD TQQQ SQQQ SOXL ARKK
    必须判为普通股：AAPL MSFT NVDA AMZN GOOGL JPM XOM PFE WMT KO
    NYSE 口径里必须含：JPM XOM KO（NYSE 上市）；必须不含：AAPL MSFT（Nasdaq 上市）
上一版就是靠这道验收当场拦下了一份分类全错的数据，这一版保留同样的门。

═══ 输出 ═══
    research/data_external/breadth_common_all_daily.csv
    research/data_external/breadth_common_nyse_daily.csv
列与 `nasdaq_breadth_daily.csv` 一致（date/n_total/adv/dec/unch/rana/adv_pct/
osc/…），另加 `classifiable_pct`（当日可分类标的占比）。

═══ 结果（2026-08-14）：**验收全过，两个 universe 已产出** ═══
15 个必剔 ETF 全部判对、10 只普通股全部保留、NYSE 口径含 JPM/XOM/KO 且不含 AAPL/MSFT。

    common_all   2,079 天  日均 7,072 标的  osc SD 33.3  [−128, +110]
    common_nyse  2,079 天  日均 1,894 标的  osc SD 40.2  [−143, +124]  ← 经典 NYMO 口径
    （原始含 ETF 版：日均 9,425，SD 35.5，[−129, +111]）

⭐ **NYSE 普通股版的量纲这才对上经典 NYMO**（±150 区间；COVID 中位 −75.0 / 最低 −140.2）。
含 ETF 版被压到 [−129,+111]，正是被几千个跟随指数的载体拉平的。

逐年可分类率 2018:59% → 2026:93%（目录是当前快照，早年退市标的查不到）。

**用 `common_nyse` 重跑 `exp_breadth_classic_usage.py` 的 8 个用法口径：
结果与含 ETF 版一模一样，0/8 通过，80 格最小 Holm p = 1.0000。**
⇒ universe 污染**不是**广度失效的原因；修好它只是让结论站得住。

纯离线（目录已固化），不连 IB，不改生产文件。约 2,079 个文件，需要几分钟。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
SRC = Path("/Users/congrenhan/Downloads/XNAS-20260810-JLNA94QEHN")
DIRECTORY = BASE / "research/data_external/nasdaq_symbol_directory_20260814.txt"
OUT = {
    "common_all": BASE / "research/data_external/breadth_common_all_daily.csv",
    "common_nyse": BASE / "research/data_external/breadth_common_nyse_daily.csv",
}
LIQ_MIN_VOLUME = 10_000

MUST_ETF = ("SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "XLF", "XLK",
            "TLT", "HYG", "GLD", "TQQQ", "SQQQ", "SOXL", "ARKK")
MUST_STOCK = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM", "XOM",
              "PFE", "WMT", "KO")
MUST_NYSE = ("JPM", "XOM", "KO")
MUST_NOT_NYSE = ("AAPL", "MSFT")


def load_directory() -> tuple[set[str], set[str], set[str]]:
    m = pd.read_csv(DIRECTORY, sep="|", dtype=str)
    m = m[m["Symbol"].notna()]
    m = m[~m["Symbol"].str.startswith("File Creation", na=False)]
    m["Symbol"] = m["Symbol"].str.strip()
    etf = set(m.loc[m["ETF"] == "Y", "Symbol"])
    test = set(m.loc[m["Test Issue"] == "Y", "Symbol"])
    common = set(m.loc[(m["ETF"] == "N") & (m["Test Issue"] != "Y"), "Symbol"])
    nyse = set(m.loc[(m["ETF"] == "N") & (m["Test Issue"] != "Y")
                     & (m["Listing Exchange"] == "N"), "Symbol"])
    known = set(m["Symbol"])
    print(f"证券目录：{len(m):,} 行　ETF {len(etf):,}　普通股 {len(common):,}"
          f"　其中 NYSE 上市 {len(nyse):,}　测试标的 {len(test)}")
    return known, common, nyse


def accept(known: set[str], common: set[str], nyse: set[str]) -> bool:
    print("\n【验收】")
    bad = []
    for s in MUST_ETF:
        ok = s in known and s not in common
        print(f"  应判 ETF    {s:<6} {'✅' if ok else '❌'}")
        if not ok:
            bad.append(f"{s} 未判为 ETF")
    for s in MUST_STOCK:
        ok = s in common
        print(f"  应判普通股  {s:<6} {'✅' if ok else '❌'}")
        if not ok:
            bad.append(f"{s} 未判为普通股")
    for s in MUST_NYSE:
        ok = s in nyse
        print(f"  NYSE 应含   {s:<6} {'✅' if ok else '❌'}")
        if not ok:
            bad.append(f"NYSE 缺 {s}")
    for s in MUST_NOT_NYSE:
        ok = s not in nyse
        print(f"  NYSE 应不含 {s:<6} {'✅' if ok else '❌'}")
        if not ok:
            bad.append(f"NYSE 误含 {s}")
    if bad:
        print(f"\n❌ 验收失败：{'; '.join(bad)}　⇒ 不产出数据")
        return False
    print("  ✅ 验收全部通过")
    return True


def main() -> int:
    if not DIRECTORY.exists():
        print(f"❌ 缺证券目录：{DIRECTORY}")
        return 1
    files = sorted(SRC.glob("xnas-itch-*.ohlcv-1d.dbn.zst"))
    if not files:
        print(f"❌ 找不到原始导出：{SRC}")
        return 1
    known, common, nyse = load_directory()
    if not accept(known, common, nyse):
        return 2

    import databento as db

    print(f"\n重建广度：{len(files)} 个交易日 × 2 个 universe")
    print("  common_all  = ETF≠Y 且非测试标的，不限上市所（无法分类者保留）")
    print("  common_nyse = 再限 Listing Exchange=='N'（经典 NYMO 口径，"
          "无法分类者**不**保留）\n")

    prev = {"common_all": {}, "common_nyse": {}}
    prev_liq = {"common_all": {}, "common_nyse": {}}
    rows = {"common_all": [], "common_nyse": []}
    for i, f in enumerate(files, 1):
        try:
            d = db.DBNStore.from_file(f).to_df()
        except Exception as e:                                  # noqa: BLE001
            print(f"  ⚠️ 跳过 {f.name}: {type(e).__name__}: {e}")
            continue
        if "symbol" not in d.columns or not len(d):
            continue
        day = pd.Timestamp(f.name.split("-")[2].split(".")[0])
        syms = d["symbol"].astype(str)
        classifiable = syms.isin(known).mean()
        keep = {
            # 无法分类 ⇒ 保留（多为退市的经营性公司，剔了就重新引入幸存者偏差）
            "common_all": syms.isin(common) | ~syms.isin(known),
            # NYSE 口径无法分类就不能算，因为不知道它在哪上市
            "common_nyse": syms.isin(nyse),
        }
        for uni, mask in keep.items():
            sub = d[mask.to_numpy()]
            if not len(sub):
                continue
            c = sub.groupby("symbol")["close"].last()
            v = sub.groupby("symbol")["volume"].sum()
            liq = c[v >= LIQ_MIN_VOLUME]
            row = dict(date=day, n_total=len(c), n_total_liq=len(liq),
                       classifiable_pct=float(classifiable))
            for tag, cur, pv in (("", c, prev[uni]), ("_liq", liq, prev_liq[uni])):
                inter = cur.index.intersection(list(pv))
                p = pd.Series({s: pv[s] for s in inter}) if len(inter) else pd.Series(dtype=float)
                a = int((cur[inter] > p).sum()) if len(inter) else 0
                dn = int((cur[inter] < p).sum()) if len(inter) else 0
                row[f"adv{tag}"] = a
                row[f"dec{tag}"] = dn
                row[f"unch{tag}"] = int((cur[inter] == p).sum()) if len(inter) else 0
                row[f"rana{tag}"] = (a - dn) / (a + dn) if (a + dn) else 0.0
                if tag == "":
                    row["adv_pct"] = a / (a + dn) if (a + dn) else 0.0
            rows[uni].append(row)
            prev[uni] = c.to_dict()
            prev_liq[uni] = liq.to_dict()
        if i % 400 == 0:
            print(f"    …{i} 天")

    for uni, rr in rows.items():
        out = pd.DataFrame(rr).sort_values("date").reset_index(drop=True)
        for tag in ("", "_liq"):
            out[f"osc{tag}"] = (out[f"rana{tag}"].ewm(span=19, adjust=False).mean()
                                - out[f"rana{tag}"].ewm(span=39, adjust=False).mean()) * 1000
        out.to_csv(OUT[uni], index=False)
        print(f"\n✅ {uni}: {len(out):,} 天 → {OUT[uni].name}")
        print(f"   {out.date.min():%Y-%m-%d} → {out.date.max():%Y-%m-%d}"
              f"　日均标的 {out.n_total.mean():,.0f}"
              f"　osc SD {out.osc.std():.1f} [{out.osc.min():.0f}, {out.osc.max():.0f}]")
        print("   逐年可分类率（目录是当前快照，越往前越低——这是必须随结论一起报的限制）：")
        yr = out.assign(y=out.date.dt.year).groupby("y").agg(
            n=("n_total", "mean"), cls=("classifiable_pct", "mean"))
        print("     " + "  ".join(f"{int(y)}:{r.cls:.0%}(n={r.n:,.0f})"
                                  for y, r in yr.iterrows()))
        print("   合理性自检（已知下跌段 osc 应显著为负）：")
        for lo, hi, nm in (("2018-10-01", "2018-12-31", "2018Q4"),
                           ("2020-02-20", "2020-03-31", "COVID"),
                           ("2022-01-01", "2022-06-30", "2022H1")):
            m2 = out[(out.date >= lo) & (out.date <= hi)]
            if len(m2):
                print(f"     {nm:<8} n={len(m2):>3}  中位 {m2.osc.median():>+7.1f}"
                      f"  最低 {m2.osc.min():>+7.1f}")
        print(f"     {'全样本':<8} n={len(out):>3}  中位 {out.osc.median():>+7.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

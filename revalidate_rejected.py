"""
revalidate_rejected.py — 每月对"回测不达标"标的自动复检

依据（2026-07-26）：本项目已有三个"rejected 不是永久判决"的实证——
  DELL  2026-07-02 被拒(0.26) → 07-25 达标(0.83) 接入
  IREN  旧评估 11 笔不稳     → 数据刷新后 230 笔 Sharpe 1.15 接入
  HOOD  第一批不在池         → 第二批达标接入
市场特征与数据都会变，固定周期重测能把"曾经不行、现在行了"的标的捞回来。

行为：
  1. 从 watchlist_history.csv 找出所有仅有 rejected 记录、且当前无策略路由的标的
  2. 重跑四策略 × 三周期回测（默认参数）
  3. 对通过 Sharpe>=0.6 / N>=30 / DD>-50% 初筛的组合，追加成本压力(10bps)与
     walk-forward(60/40) 验证
  4. 全部通过者推送 Telegram 报告为"待接入候选"——**不自动接入**，
     参数/标的变更仍需人工确认后走标准接入流程

⚠️ 统计提示：反复对同一批标的重测会抬高假阳性率（多重比较）。频率定为每月、
   且必须全套验证通过才报告，就是为了控制这一点；不要再加密到每周。

用法：
  python revalidate_rejected.py             # 控制台
  python revalidate_rejected.py --telegram  # 推送报告
"""

import argparse
import os
import warnings

import pandas as pd
import yaml
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

import backtest_runner as br
import breakout_backtest as bo
import mr_backtest as mrb
import rsi2_backtest as r2

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

PASS_SHARPE, MIN_N, DD_FLOOR, PASS_BPS = 0.6, 30, -50.0, 10
MIN_SEG = 15

# 结构性排除：数值门槛筛不住这两类——货币/短债基金的近零波动会让 ATR 框架
# 产生 Sharpe 极高的伪信号（SGOV 首轮复检就以 1.93 混进候选），杠杆/反向 ETF
# 的衰减特性从未被本系统的参数体系验证过。除非未来专项研究解禁，永不自动推荐。
STRUCTURAL_EXCLUDE = {
    "SGOV", "BND", "FBND", "HYMB", "TLT", "VTEB", "VBIL", "XHLF", "BSP", "JHS",
    "JEPI", "JEPQ", "QQQI", "SPYI", "FXAIX", "VTSAX",
    "SOXL", "SOXS", "SPXS", "SPXU", "SQQQ", "TQQQ", "BTCI", "OILU", "RAM",
}


def tg_send(msg: str) -> None:
    token, chat = os.getenv("TG_TOKEN", ""), os.getenv("TG_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                               data=data, timeout=15)
    except Exception:
        pass


def rejected_pool() -> list[str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("ae", "alert_engine.py")
    ae = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ae)
    routed = {s for (s, tf) in ae.STRATEGY_MAP if ":" not in tf} | set(ae.BREAKOUT_PARAMS)

    h = pd.read_csv("watchlist_history.csv")
    tested = h[h["status"].isin(["rejected", "rejected_high_risk_dd"])]["symbol"].unique()
    skip = set(h[h["status"].isin(["non_us_or_invalid", "no_data_unverified",
                                   "insufficient_data", "duplicate_format"])]["symbol"])
    return sorted(set(tested) - routed - skip - STRUCTURAL_EXCLUDE)


def backtest_all(sym: str, qqq: dict, vix) -> list[dict]:
    out = []
    for tf in ("1h", "4h", "1d"):
        try:
            c = br.run_backtest(sym, tf, cfg["timeframes"][tf], df_qqq=qqq[tf])
            if c:
                out.append({"tf": tf, "strategy": "confluence", **c})
        except Exception:
            pass
        try:
            df = r2.load_data(sym, tf)
            if df is not None and len(df) >= 210:
                r = r2.run_one(df, r2.DEFAULT_PARAMS[tf].copy(), qqq[tf], vix,
                               is_benchmark=False, is_sector_etf=False)
                if r:
                    out.append({"tf": tf, "strategy": "rsi2", **r})
        except Exception:
            pass
        try:
            dm = mrb.load_data(sym, tf)
            if dm is not None and len(dm) >= 210:
                r = mrb.run_one(dm, mrb.DEFAULT_PARAMS[tf].copy())
                if r:
                    out.append({"tf": tf, "strategy": "mr", **r})
        except Exception:
            pass
    try:
        db = bo.load_data(sym)
        if db is not None and len(db) >= 260:
            r = bo.run_one(db, bo.DEFAULT_PARAMS)
            if r:
                out.append({"tf": "1d", "strategy": "breakout", **r})
    except Exception:
        pass
    return out


def validate(sym: str, tf: str, strategy: str, qqq: dict, vix) -> dict | None:
    """Cost pressure + walk-forward on one candidate; None if it fails either."""
    def run(df_slice=None, commission=None):
        if strategy == "confluence":
            p = dict(cfg["timeframes"][tf])
            if commission is not None:
                p["commission"] = commission
            return br.run_backtest(sym, tf, p, df_qqq=qqq[tf], df_override=df_slice)
        if strategy == "rsi2":
            p = r2.DEFAULT_PARAMS[tf].copy()
            if commission is not None:
                p["commission"] = commission
            data = df_slice if df_slice is not None else r2.load_data(sym, tf)
            return r2.run_one(data, p, qqq[tf], vix, is_benchmark=False, is_sector_etf=False)
        if strategy == "mr":
            p = mrb.DEFAULT_PARAMS[tf].copy()
            if commission is not None:
                p["commission"] = commission
            data = df_slice if df_slice is not None else mrb.load_data(sym, tf)
            return mrb.run_one(data, p)
        p = dict(bo.DEFAULT_PARAMS)
        if commission is not None:
            p["commission"] = commission
        data = df_slice if df_slice is not None else bo.load_data(sym)
        return bo.run_one(data, p)

    at10 = run(commission=PASS_BPS / 10000)
    if not at10 or at10["sharpe"] < PASS_SHARPE:
        return None
    df = bo.load_data(sym) if strategy == "breakout" else r2.load_data(sym, tf)
    if df is None:
        return None
    split = int(len(df) * 0.6)
    tr, te = run(df_slice=df.iloc[:split]), run(df_slice=df.iloc[split:])
    if not tr or not te or tr["n"] < MIN_SEG or te["n"] < MIN_SEG or te["sharpe"] < 0:
        return None
    return {"s10": round(at10["sharpe"], 3),
            "train": round(tr["sharpe"], 3), "test": round(te["sharpe"], 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description="月度 rejected 池复检")
    parser.add_argument("--telegram", action="store_true")
    args = parser.parse_args()

    pool = rejected_pool()
    print(f"复检 rejected 池: {len(pool)} 个标的", flush=True)
    qqq = {tf: r2.load_data("QQQ", tf) for tf in ("1h", "4h", "1d")}
    vix = r2.load_vix()

    candidates = []
    for i, sym in enumerate(pool, 1):
        for res in backtest_all(sym, qqq, vix):
            if (res["sharpe"] >= PASS_SHARPE and res["n"] >= MIN_N
                    and res.get("dd", 0) > DD_FLOOR):
                v = validate(sym, res["tf"], res["strategy"], qqq, vix)
                if v:
                    candidates.append({"symbol": sym, "tf": res["tf"],
                                       "strategy": res["strategy"],
                                       "sharpe": round(res["sharpe"], 3),
                                       "n": res["n"], **v})
        if i % 25 == 0 or i == len(pool):
            print(f"  {i}/{len(pool)}", flush=True)

    if not candidates:
        msg = f"🔄 月度复检：{len(pool)} 个 rejected 标的重测，无新达标。"
    else:
        lines = [f"  {c['symbol']} {c['tf']} {c['strategy']}: Sharpe {c['sharpe']} "
                 f"(10bps {c['s10']}, wf {c['train']}→{c['test']}, N={c['n']})"
                 for c in candidates]
        msg = (f"🔄 月度复检：{len(pool)} 个 rejected 标的重测，"
               f"**{len(candidates)} 个组合通过全套验证**，待人工确认接入：\n"
               + "\n".join(lines))
    print(msg)
    if args.telegram:
        tg_send(msg)


if __name__ == "__main__":
    main()

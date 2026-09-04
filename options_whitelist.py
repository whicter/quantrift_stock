"""
options_whitelist.py — 用实时期权链重测已路由标的的可交易性（只读，不下单）

为什么需要它：现有白名单是从 quantrift_options-lab 的期权库筛出来的，而那个库
bid/ask 只有 7.6% 非空，曾把 SMH、CSCO 这类明明流动性充裕的标的判成"期权太少"
（实测 SMH 34DTE OI 4650、CSCO OI 2870）。用实时链直接测才作数。

两条必须遵守的纪律，都是 2026-09-03 踩过的坑：

1. **只在盘中测**。收盘后做市商撤单/放宽，同一张合约 22:51 测出来的价差是盘中
   的 3 倍（MU 2.3%→7.9%、PLTR 2.2%→7.6%），OI 也读不准。拿盘后数据筛白名单
   会把 CSCO/LLY/JPM/QCOM/IBM/WMT 这些最流动的票全部误杀。

2. **必须复用 `options_paper.pick_contract` 的选合约逻辑**。按"30-60DTE 里的
   第一个到期"去测，取到的可能是周度合约——实测 MU 周度 OI 只有 34，而同期
   月度 3,777。测的必须是我们真会买的那一张，否则这个数没有意义。

用法：
  python options_whitelist.py              # 盘中跑，输出建议
  python options_whitelist.py --force      # 明知盘后仍要跑（结果仅供参考）
"""

import argparse
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")

import pandas as pd

OUT = "logs/options_whitelist_live.csv"


def market_open_now() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return (now.hour, now.minute) >= (9, 30) and (now.hour, now.minute) <= (16, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="盘后也跑（结果不可用于筛选）")
    ap.add_argument("--max-spread", type=float, default=10.0, help="价差门槛%%（默认10）")
    args = ap.parse_args()

    ny = datetime.now(ZoneInfo("America/New_York"))
    if not market_open_now() and not args.force:
        raise SystemExit(
            f"现在是纽约时间 {ny:%H:%M %a}，非交易时段。\n"
            f"盘后价差是盘中的数倍、OI 也读不准，据此筛白名单会误杀最流动的标的。\n"
            f"请在美股盘中（09:30-16:00 ET）运行；确实要看盘后数据加 --force。")

    from alert_engine import BREAKOUT_PARAMS, STRATEGY_MAP
    import options_paper as op

    # 每条路由按自身持仓上限决定目标 DTE，与实盘开仓完全一致
    hold = {}
    for (symbol, tf), strat in STRATEGY_MAP.items():
        if ":" in tf:
            continue
        try:
            d = op._hold_days(pd.Series({"strategy": strat, "tf": tf, "params_json": "{}"}))
        except Exception:
            d = 10.0
        hold[symbol] = max(hold.get(symbol, 0), d)
    for symbol in BREAKOUT_PARAMS:
        hold.setdefault(symbol, 20.0)

    rows = []
    for i, (symbol, hd) in enumerate(sorted(hold.items())):
        # 直接调用实盘的选合约函数：测的就是真会买的那一张
        c = op.pick_contract(symbol, "做多", hd)
        if c is None:
            rows.append({"symbol": symbol, "note": "无有效双边报价"})
        else:
            rows.append({"symbol": symbol, "dte": c["dte"], "strike": c["strike"],
                         "mid": c["mid"], "spread_pct": c["spread_pct"],
                         "oi": c["oi"], "iv": round(c["iv"], 3), "note": "ok"})
        if i % 20 == 0:
            print(f"  ...{i}/{len(hold)}", flush=True)

    d = pd.DataFrame(rows)
    d.to_csv(OUT, index=False)
    ok = d[d.note == "ok"]
    print(f"\n采样时间 {ny:%Y-%m-%d %H:%M %Z}（盘中）")
    print(f"已路由 {len(d)} 个，取到实时双边报价 {len(ok)} 个")
    for lo, hi, lab in [(0, 5, "<5%"), (5, 10, "5-10%"), (10, 20, "10-20%"), (20, 1e4, ">=20%")]:
        n = len(ok[(ok.spread_pct >= lo) & (ok.spread_pct < hi)])
        print(f"  价差 {lab:8s} {n:3d}")

    good = set(ok[ok.spread_pct < args.max_spread].symbol)
    cur = op.WHITELIST
    print(f"\n当前白名单 {len(cur)}　按价差<{args.max_spread}% 应为 {len(good)}")
    print(f"  应加入: {sorted(good - cur) or '（无）'}")
    print(f"  应剔除: {sorted(cur - good) or '（无）'}")
    print(f"\n明细: {OUT}")


if __name__ == "__main__":
    main()

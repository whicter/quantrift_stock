"""
options_paper.py — 期权纸面模拟（绝不下单）

用户设想（2026-08-15）："每次给信号的时候马上模拟下单期权，到信号的止盈位置就
出掉，然后看盈利"。本模块实现该想法，但有三处基于实测数据的必要偏离，都记在这里：

1. **只覆盖流动性足够的标的**。`options_liquidity.py` 实测：108 个已路由标的中
   只有 75 个 ATM 未平仓量 ≥500，且能算出真实价差的里面中位价差 5.3%。价差
   >15% 的标的（ALL/BB/HOOD/MO/RGTI/WBD）做期权模拟毫无意义——价差就把利润吃光了。
   故白名单只取**实测价差 <5%** 的一批。

2. **"到止盈位出场"只对 Confluence/Breakout 成立**。RSI2 和 MR（占 130 条路由中的
   91 条）设计上就没有固定 TP，靠 ATR 追踪 + 时间止损离场。对这些路由，出场时点
   取自 `review_core` 对正股的逐 bar 复盘结果——即"正股策略什么时候出，期权就
   什么时候出"，与用户原意一致。

3. **报价取自 yfinance 实时期权链，不用 options-lab 数据库**。数据库的 bid/ask
   只有 7.6% 非空，且快照时点与我们的扫描不对齐；yfinance 在信号时刻能直接给出
   真实 bid/ask/OI/IV（实测 NVDA 价差 1.4%、AAPL 3.7%）。数据库更适合做历史分析。

成交假设（刻意保守，避免自欺）：
  买入按 **ask** 成交，卖出按 **bid** 成交。同时记录 mid 价便于对比"理想成交"与
  "实际可成交"的差距——这个差距正是期权相对正股的主要额外成本。

合约选择规则（固定，不做逐标的优化）：
  - 做多 → call；做空 → put
  - 到期：目标 DTE = max(30, 该路由持仓上限交易日 × 3.5)，**优先取月度到期
    （每月第三个周五）**。实测 CRWD 同一时点周度到期价差 16.0%/OI 99，月度
    8.4%/OI 233——月度流动性接近两倍，周度期权对模拟和实盘都不可用。
  - 行权价：最接近现价的 ATM（流动性最好、delta 最高）

用法：
  python options_paper.py            # 开新仓 + 检查平仓
  python options_paper.py --status   # 只看当前状态
"""

import argparse
import json
import warnings
from datetime import date, datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf

import review_core
from review_core import evaluate, hold_bars

SIGNAL_LOG = Path("logs/signal_log.csv")
LEDGER = Path("logs/options_paper_log.csv")
STATE = Path("data/.options_positions.json")

# 粗筛白名单：options_liquidity.py 2026-08-15 实测价差 <5% 的标的。
# 刻意保守：宁可覆盖少，也不要在价差大的标的上产生看似盈利的假结果。
# 入场实时价差闸门。白名单是基于 options-lab 数据库快照算的，但实测发现同一标的
# 的实时价差可能与快照差很多（CRWD 快照 <5%，实时周度到期却是 16%）。故白名单只
# 作粗筛，真正的把关是下单那一刻的实时价差。
MAX_ENTRY_SPREAD_PCT = 8.0

# 只接这个时间窗内发出的信号（分钟）。主扫描在整点触发、数分钟内完成，本任务
# 在 :10 运行，30 分钟窗口刚好覆盖当轮扫描且不会捞到上一小时的陈旧信号。
FRESH_MINUTES = 30

WHITELIST = {
    "AAPL", "BABA", "CRWD", "DELL", "GOOGL", "IBM", "INTC", "MRVL", "MS",
    "MSFT", "MU", "NFLX", "NVDA", "PLTR", "QCOM", "SLV", "SNDK", "TSLA",
}

FIELDS = [
    "opened_at", "closed_at", "symbol", "tf", "strategy", "direction", "signal_id",
    "contract", "expiry", "strike", "right", "dte_at_entry",
    "stock_entry", "stock_exit", "stock_r",
    "opt_entry_ask", "opt_entry_mid", "opt_exit_bid", "opt_exit_mid",
    "opt_return_pct", "opt_return_mid_pct", "iv_entry", "oi_entry", "exit_reason",
]


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {}


def _save_state(d: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1, ensure_ascii=False))


def _append(row: dict) -> None:
    LEDGER.parent.mkdir(exist_ok=True)
    exists = LEDGER.exists()
    if exists:
        with open(LEDGER) as fh:
            if fh.readline().strip().split(",") != FIELDS:
                LEDGER.rename(LEDGER.with_suffix(f".schema-{datetime.now():%Y%m%d}.bak"))
                exists = False
    import csv
    with open(LEDGER, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def pick_contract(symbol: str, direction: str, hold_days: float) -> dict | None:
    """按固定规则选一张 ATM 合约并取实时报价。"""
    target_dte = max(30, round(hold_days * 3.5))
    try:
        t = yf.Ticker(symbol)
        expiries = t.options
        if not expiries:
            return None
        today = date.today()

        def _is_monthly(e: str) -> bool:
            d = pd.Timestamp(e)
            return d.dayofweek == 4 and 15 <= d.day <= 21   # 第三个周五

        monthly = [e for e in expiries if _is_monthly(e)]
        # 月度到期若与目标 DTE 相差不超过 3 周，优先用月度；否则退回全集取最近的
        pool = monthly or list(expiries)
        exp = min(pool, key=lambda e: abs((pd.Timestamp(e).date() - today).days - target_dte))
        if abs((pd.Timestamp(exp).date() - today).days - target_dte) > 21:
            exp = min(expiries, key=lambda e: abs((pd.Timestamp(e).date() - today).days - target_dte))
        dte = (pd.Timestamp(exp).date() - today).days
        chain = t.option_chain(exp)
        df = chain.calls if direction == "做多" else chain.puts
        spot = float(t.fast_info.get("lastPrice") or 0)
        if not spot or df.empty:
            return None
        df = df.copy()
        df["dist"] = (df["strike"] - spot).abs()
        row = df.nsmallest(1, "dist").iloc[0]
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        if ask <= 0 or bid <= 0:
            return None      # 无有效双边报价，如实跳过而不是编一个价
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100
        if spread_pct > MAX_ENTRY_SPREAD_PCT:
            print(f"  ⊘ {symbol} {exp} 实时价差 {spread_pct:.1f}% > {MAX_ENTRY_SPREAD_PCT}%，跳过")
            return None
        return {
            "contract": str(row.get("contractSymbol", "")),
            "expiry": exp, "strike": float(row["strike"]),
            "right": "C" if direction == "做多" else "P",
            "dte": dte, "bid": bid, "ask": ask, "mid": round(mid, 4),
            "spread_pct": round(spread_pct, 1),
            "iv": round(float(row.get("impliedVolatility") or 0), 4),
            "oi": int(row.get("openInterest") or 0), "spot": spot,
        }
    except Exception as exc:
        print(f"  ⚠ {symbol} 期权链获取失败: {exc}")
        return None


def quote_contract(symbol: str, expiry: str, strike: float, right: str) -> dict | None:
    """取已持仓合约的当前报价。"""
    try:
        t = yf.Ticker(symbol)
        if expiry not in t.options:
            return None      # 已到期
        chain = t.option_chain(expiry)
        df = chain.calls if right == "C" else chain.puts
        m = df[df["strike"] == strike]
        if m.empty:
            return None
        row = m.iloc[0]
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        return {"bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 4)}
    except Exception:
        return None


def _hold_days(row: pd.Series) -> float:
    tf = str(row.get("tf", "1d"))
    return hold_bars(row, tf) / review_core.BARS_PER_DAY.get(tf, 1)


def r2_load(symbol: str, tf: str):
    import rsi2_backtest as r2
    return r2.load_data(symbol, tf)


def open_new(state: dict) -> int:
    """对白名单标的中**刚刚发出**的信号，按当下报价开纸面期权仓。"""
    if not SIGNAL_LOG.exists():
        return 0
    sig = pd.read_csv(SIGNAL_LOG)
    # is_shadow 在 CSV 里是浮点（1.0/0.0），用字符串比较会漏掉影子信号——
    # 2026-08-15 初版就因此把 MRVL_WideExit_shadow 当实盘信号开了仓。
    shadow = pd.to_numeric(sig.get("is_shadow", 0), errors="coerce").fillna(0)
    sig = sig[sig["symbol"].isin(WHITELIST) & (shadow != 1)
              & ~sig["strategy"].astype(str).str.endswith("_shadow")]
    # **只接刚刚这一轮扫描发出的信号**。期权必须在信号发出的当下按当时的报价买入，
    # 否则就是时点错配：拿几天后的期权报价去对应几天前发出的信号，两边不是同一段
    # 时间，算出来的盈亏毫无意义。本任务在主扫描（:00，数分钟内跑完）之后的 :10
    # 触发，故只取 FRESH_MINUTES 内的信号。
    cutoff = pd.Timestamp.now() - pd.Timedelta(minutes=FRESH_MINUTES)
    sig = sig[pd.to_datetime(sig["timestamp"]) >= cutoff]
    opened = 0
    for _, r in sig.iterrows():
        sid = str(r.get("signal_id", ""))
        if not sid or sid in state:
            continue
        # 同一 (标的,周期,策略,方向) 只开一仓：连续 bar 反复触发的是同一个交易想法，
        # 开成多仓会把单一判断的盈亏重复计数，夸大统计意义。
        idea = (str(r["symbol"]), str(r["tf"]), str(r["strategy"]), str(r["direction"]))
        if any((p["symbol"], p["tf"], p["strategy"], p["direction"]) == idea
               for p in state.values()):
            continue
        # 不再做"是否仍未出场"的二次判定：FRESH_MINUTES 窗口已保证信号是刚发出的，
        # 而 evaluate() 会因 bar 粒度（1h 信号的 bar_date 当天含 7 根 bar）把刚发出的
        # 信号误判成已出场，反而漏掉本该开的仓。
        c = pick_contract(str(r["symbol"]), str(r["direction"]), _hold_days(r))
        if not c:
            continue
        state[sid] = {
            "opened_at": datetime.now().isoformat(timespec="seconds"),
            "symbol": str(r["symbol"]), "tf": str(r["tf"]),
            "strategy": str(r["strategy"]), "direction": str(r["direction"]),
            "signal_row": {k: (None if pd.isna(v) else v) for k, v in r.items()},
            **{f"opt_{k}": v for k, v in c.items()},
        }
        print(f"  ＋ {r['symbol']} {r['tf']} {r['direction']} → "
              f"{c['right']} {c['strike']} @{c['expiry']} (DTE{c['dte']}) "
              f"买入ask ${c['ask']:.2f} 价差{(c['ask']-c['bid'])/c['mid']*100:.1f}%")
        opened += 1
    return opened


def close_finished(state: dict) -> int:
    """正股信号已出场的，按当前期权报价平掉纸面仓。"""
    import rsi2_backtest as r2
    closed = 0
    for sid in list(state):
        pos = state[sid]
        row = pd.Series(pos["signal_row"])
        price = r2.load_data(pos["symbol"], pos["tf"])
        if price is None:
            continue
        res = evaluate(row, price)
        if res.get("outcome") in ("未决", "数据失败"):
            continue          # 正股还没出场，期权继续持有
        q = quote_contract(pos["symbol"], pos["opt_expiry"],
                           pos["opt_strike"], pos["opt_right"])
        if not q:
            continue
        entry_ask, entry_mid = pos["opt_ask"], pos["opt_mid"]
        ret = (q["bid"] - entry_ask) / entry_ask * 100 if entry_ask else None
        ret_mid = (q["mid"] - entry_mid) / entry_mid * 100 if entry_mid else None
        _append({
            "opened_at": pos["opened_at"], "closed_at": datetime.now().isoformat(timespec="seconds"),
            "symbol": pos["symbol"], "tf": pos["tf"], "strategy": pos["strategy"],
            "direction": pos["direction"], "signal_id": sid,
            "contract": pos["opt_contract"], "expiry": pos["opt_expiry"],
            "strike": pos["opt_strike"], "right": pos["opt_right"],
            "dte_at_entry": pos["opt_dte"],
            "stock_entry": row.get("entry_price"), "stock_exit": "",
            "stock_r": res.get("r_mult"),
            "opt_entry_ask": entry_ask, "opt_entry_mid": entry_mid,
            "opt_exit_bid": q["bid"], "opt_exit_mid": q["mid"],
            "opt_return_pct": round(ret, 1) if ret is not None else "",
            "opt_return_mid_pct": round(ret_mid, 1) if ret_mid is not None else "",
            "iv_entry": pos["opt_iv"], "oi_entry": pos["opt_oi"],
            "exit_reason": res.get("outcome"),
        })
        print(f"  － {pos['symbol']} {pos['tf']} 平仓：正股 {res.get('r_mult'):+.2f}R "
              f"／期权 {ret:+.1f}%（{res.get('outcome')}）")
        del state[sid]
        closed += 1
    return closed


def summary() -> None:
    if not LEDGER.exists():
        print("期权纸面账本为空")
        return
    d = pd.read_csv(LEDGER)
    d = d[pd.to_numeric(d["opt_return_pct"], errors="coerce").notna()]
    if d.empty:
        print("暂无已平仓记录")
        return
    d["opt_return_pct"] = pd.to_numeric(d["opt_return_pct"])
    d["stock_r"] = pd.to_numeric(d["stock_r"], errors="coerce")
    print(f"\n=== 期权纸面结果（{len(d)} 笔已平仓）===")
    print(f"  期权胜率 {(d.opt_return_pct>0).mean()*100:.0f}%  平均 {d.opt_return_pct.mean():+.1f}%  "
          f"中位 {d.opt_return_pct.median():+.1f}%")
    print(f"  同期正股 平均 {d.stock_r.mean():+.2f}R  胜率 {(d.stock_r>0).mean()*100:.0f}%")
    both = d.dropna(subset=["stock_r"])
    if len(both) >= 5:
        agree = ((both.stock_r > 0) == (both.opt_return_pct > 0)).mean() * 100
        print(f"  方向一致率 {agree:.0f}%（正股赚时期权也赚的比例）")
    print("\n按策略:")
    print(d.groupby("strategy")["opt_return_pct"].agg(
        笔数="count", 胜率=lambda s: f"{(s>0).mean()*100:.0f}%", 平均=lambda s: f"{s.mean():+.1f}%").to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只看状态不动仓位")
    args = ap.parse_args()

    state = _load_state()
    if args.status:
        print(f"当前持有纸面期权仓 {len(state)} 个:")
        for sid, p in state.items():
            print(f"  {p['symbol']} {p['tf']} {p['opt_right']}{p['opt_strike']} "
                  f"@{p['opt_expiry']} 入场ask ${p['opt_ask']}")
        summary()
        return

    print(f"白名单 {len(WHITELIST)} 个标的｜当前持仓 {len(state)} 个")
    c = close_finished(state)
    o = open_new(state)
    _save_state(state)
    print(f"\n本轮：新开 {o}，平仓 {c}，当前持仓 {len(state)}")
    summary()


if __name__ == "__main__":
    main()

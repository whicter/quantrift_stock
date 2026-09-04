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

成交假设：
  **主口径按中间价（mid）成交**——用户要求不因价差宽而过滤，按 mid 下单。
  同时**仍记录保守口径**（买 ask / 卖 bid）作为对照列：两者之差就是价差成本，
  也是"限价单能否在 mid 成交"这一假设的敞口。宽价差标的上两个数会差很多，
  分析时以哪个为准由使用者判断，账本两个都留。

合约选择规则（固定，不做逐标的优化）：
  - 做多 → call；做空 → put
  - 到期：目标 DTE = clamp(持仓上限交易日 × 3.5, 30, 60)，**优先取月度到期
    （每月第三个周五）**。实测 CRWD 同一时点周度到期价差 16.0%/OI 99，月度
    8.4%/OI 233——月度流动性接近两倍，周度期权对模拟和实盘都不可用。
  - 行权价：最接近现价的 ATM（流动性最好、delta 最高）

用法：
  python options_paper.py            # 开新仓 + 检查平仓
  python options_paper.py --status   # 只看当前状态
"""

import argparse
import fcntl
import json
import warnings
from datetime import date, datetime
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

import review_core
from review_core import evaluate, hold_bars

load_dotenv()

SIGNAL_LOG = Path("logs/signal_log.csv")
LEDGER = Path("logs/options_paper_log.csv")
STATE = Path("data/.options_positions.json")
LOCK = Path("data/.options_paper.lock")

# 白名单：`options_liquidity.py` 实测 ATM 未平仓量 ≥500 的标的（2026-08-15）。
# 约束是"有没有真实的双边市场"，不是价差大小——用户明确要求按中间价成交、
# 不因价差宽而过滤，故价差不再作为准入条件，只作为记录字段供事后分析。
#
# SMH / CSCO 是**手工补入**：筛选脚本读的是 options-lab 数据库，而该库恰好没有
# 收这两个标的（连同 FOF 共 3 个未覆盖），于是被误判为"无到期覆盖"。yfinance
# 实测两者流动性其实很好——SMH 34DTE 价差7.2%/OI4650/量489，CSCO 34DTE
# 价差4.9%/OI2870/量2012，都优于名单里不少标的。这是数据采集缺口，不是市场事实。
# 封顶 60DTE 后对此前"无到期覆盖"的一批做了 yfinance 实测复核，准入线定为
# **目标到期处 OI≥50 且有有效双边报价**（用户要求不按价差过滤，价差只记录不拦截）：
#   补入：LLY(OI77) ISRG(64) NTRS(61) MAR(217) SPYM(291) VOO(95) VTI(550)
#   仍排除（几乎无市场）：AVDV(OI0) VYM(6) FDVV(11) MKSI(32) SPMO(38) DGRO(46)
# 注意 LLY/ISRG/NTRS 等价差 8-37% 不等，mid 成交假设在这些标的上偏乐观，
# 账本同时记保守口径（买ask/卖bid）供对照，分析时可按 spread 列自行筛。
WHITELIST = {
    "AAOI", "AAPL", "AGI", "AIRJ", "ALAB", "ALL", "AMC", "APLD", "APO", "APP",
    "BA", "BABA", "BAC", "BB", "BE", "CCJ", "CRCL", "CRSP", "CRWD", "CRWV", "CSCO",
    "DELL", "DJT", "GE", "GFS", "GOOG", "GOOGL", "HBM", "HOOD", "IBM", "INTC",
    "INTU", "IREN", "ISRG", "JPM", "KO", "LLY", "LMT", "LUNR", "LWLG", "MAR",
    "META", "MO", "MRVL", "NTRS",
    "MS", "MSFT", "MSOS", "MSTR", "MU", "NFLX", "NVDA", "OKLO", "ONDS", "ORCL",
    "OSCR", "PANW", "PLTR", "QCOM", "QQQ", "RBLX", "RGTI", "SAP", "SKM", "SLV",
    "SMCI", "SMH", "SNDK", "SOFI", "SOXX", "SPY", "SPYM", "STX", "TEAM", "TMC",
    "TSLA", "TSM", "TTD", "USAR", "VOO", "VTI", "WBD", "WDC", "WMT",
}

# 只接这个时间窗内发出的信号（分钟）。主扫描在整点触发、数分钟内完成，本任务
# 在 :10 运行，30 分钟窗口刚好覆盖当轮扫描且不会捞到上一小时的陈旧信号。
FRESH_MINUTES = 30

# 目标到期上限（天）。见 pick_contract 里的说明：超过约 60DTE 后，我们标的池里
# 多数合约的未平仓量断崖式下跌，宁可承担多一些 theta 也不要开在无人交易的合约上。
# 每笔期权分配的名义预算。正股纸面组合按 RISK_PCT=0.75% 的风险预算下单，
# 期权买方最大亏损就是权利金，故直接把「每笔投入的美元」定成同一量级，
# 两边的盈亏才有可比性。2026-09-03 之前账本只记百分比、不记数量，导致
# 「这套东西到底赚了多少钱」根本算不出来——复盘只能停在百分比上。
BUDGET_USD = 750.0

MIN_DTE = 30          # 到期硬下限：低于此天数的合约一律不选
MAX_TARGET_DTE = 60

FIELDS = [
    "opened_at", "closed_at", "symbol", "tf", "strategy", "direction", "signal_id",
    "contract", "expiry", "strike", "right", "dte_at_entry",
    "stock_entry", "stock_exit", "stock_r",
    "opt_entry_ask", "opt_entry_mid", "opt_exit_bid", "opt_exit_mid",
    "opt_return_pct", "opt_return_mid_pct", "iv_entry", "oi_entry", "exit_reason", "contracts", "cost_usd", "pnl_usd",
]


def tg_alert(msg: str) -> None:
    """推送到 Telegram；未配置或失败都静默跳过，绝不影响账本写入。"""
    import os
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


def _acquire_lock():
    """独占锁：同一时刻只允许一个实例改仓位。

    2026-09-03 复盘发现账本 149 行里有 23 行是同一仓位被写了两次，closed_at
    相差 1-3 秒、入场数据完全相同。日志里能看到两个进程的输出交错（同一分钟内
    两次 "白名单 84 个标的｜当前持仓 13 个"）。原因是 `main()` 只在最后才
    `_save_state()`，两个并发实例都读到同一份 state、都平掉同一批仓、都往账本
    追加一行。重复行会把单笔盈亏重复计入统计，直接污染复盘结论。

    返回文件句柄（须在进程存活期间持有）；拿不到锁返回 None。
    """
    LOCK.parent.mkdir(exist_ok=True)
    fh = open(LOCK, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


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
    # 3.5 倍持仓是为了让出场时点仍在 30DTE 的 theta 陡坡之外，但**必须封顶**：
    # 机械外推会把长持仓路由推到没人交易的远月——LLY 持仓30天×3.5=105DTE 处
    # OI 只有 39，而它 34DTE 处 OI 有 602。远月省下的 theta 远不抵流动性损失。
    target_dte = min(max(MIN_DTE, round(hold_days * 3.5)), MAX_TARGET_DTE)
    try:
        t = yf.Ticker(symbol)
        expiries = t.options
        if not expiries:
            return None
        today = date.today()

        def _dte(e: str) -> int:
            return (pd.Timestamp(e).date() - today).days

        def _is_monthly(e: str) -> bool:
            d = pd.Timestamp(e)
            return d.dayofweek == 4 and 15 <= d.day <= 21   # 第三个周五

        # MIN_DTE 是**硬下限**，不是软目标。2026-09-03 复盘发现旧实现里月度优先
        # 会把下限吃掉：目标 30DTE 时一张 16DTE 的月度合约因偏差 14 天（≤21）被
        # 接受，全账本 49% 的入场落在 30 天以内、最短 16 天——正好在本模块注释
        # 声明要避开的 theta 陡坡里面。先按下限过滤，再谈月度优先。
        usable = [e for e in expiries if _dte(e) >= MIN_DTE]
        if not usable:
            return None
        monthly = [e for e in usable if _is_monthly(e)]
        # 月度到期若与目标 DTE 相差不超过 3 周，优先用月度；否则退回可用全集取最近的
        pool = monthly or usable
        exp = min(pool, key=lambda e: abs(_dte(e) - target_dte))
        if abs(_dte(exp) - target_dte) > 21:
            exp = min(usable, key=lambda e: abs(_dte(e) - target_dte))
        dte = _dte(exp)
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
    msgs: list[str] = []
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
        # 一张合约 = 100 股。预算买不起一张就买一张（如实记录真实成本），
        # 不为了凑预算去编一个分数张数。
        contracts = max(1, int(BUDGET_USD // (c["mid"] * 100))) if c["mid"] > 0 else 1
        state[sid] = {
            "contracts": contracts,
            "cost_usd": round(c["mid"] * 100 * contracts, 2),
            "opened_at": datetime.now().isoformat(timespec="seconds"),
            "symbol": str(r["symbol"]), "tf": str(r["tf"]),
            "strategy": str(r["strategy"]), "direction": str(r["direction"]),
            "signal_row": {k: (None if pd.isna(v) else v) for k, v in r.items()},
            **{f"opt_{k}": v for k, v in c.items()},
        }
        line = (f"{c['right']} {c['strike']:g} @{c['expiry']} (DTE{c['dte']})\n"
                f"  {r['symbol']} {r['tf']} {r['direction']} [{r['strategy']}]\n"
                f"  买入 mid ${c['mid']:.2f}　(bid ${c['bid']:.2f} / ask ${c['ask']:.2f}，"
                f"价差 {c['spread_pct']}%)\n"
                f"  IV {c['iv']*100:.0f}%　OI {c['oi']:,}")
        print(f"  ＋ {r['symbol']} {r['tf']} {r['direction']} → {c['right']} {c['strike']:g} "
              f"@{c['expiry']} (DTE{c['dte']}) 按mid ${c['mid']:.2f} 价差{c['spread_pct']}%")
        msgs.append(line)
        opened += 1
    if msgs:
        tg_alert(f"🎲 期权纸面开仓 {len(msgs)} 笔（模拟，未下单）\n\n"
                 + "\n\n".join(msgs))
    return opened


def close_finished(state: dict) -> int:
    """正股信号已出场的，按当前期权报价平掉纸面仓。"""
    import rsi2_backtest as r2
    closed = 0
    msgs: list[str] = []
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
        # 主口径 mid→mid；对照口径 ask→bid（把价差成本吃满）
        ret_mid = (q["mid"] - entry_mid) / entry_mid * 100 if entry_mid else None
        ret = (q["bid"] - entry_ask) / entry_ask * 100 if entry_ask else None
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
            "contracts": pos.get("contracts", ""),
            "cost_usd": pos.get("cost_usd", ""),
            "pnl_usd": (round((q["mid"] - entry_mid) * 100 * pos["contracts"], 2)
                        if pos.get("contracts") else ""),
        })
        print(f"  － {pos['symbol']} {pos['tf']} 平仓：正股 {res.get('r_mult'):+.2f}R "
              f"／期权(mid) {ret_mid:+.1f}%　保守口径 {ret:+.1f}%（{res.get('outcome')}）")
        msgs.append(f"{pos['symbol']} {pos['tf']} {pos['opt_right']}{pos['opt_strike']:g}\n"
                    f"  正股 {res.get('r_mult'):+.2f}R　期权 {ret_mid:+.1f}% "
                    f"(保守 {ret:+.1f}%)\n"
                    f"  ${entry_mid:.2f} → ${q['mid']:.2f}　{res.get('outcome')}")
        del state[sid]
        closed += 1
    if msgs:
        tg_alert(f"🎲 期权纸面平仓 {len(msgs)} 笔（模拟）\n\n" + "\n\n".join(msgs))
    return closed


def summary() -> None:
    if not LEDGER.exists():
        print("期权纸面账本为空")
        return
    d = pd.read_csv(LEDGER)
    d = d[pd.to_numeric(d["opt_return_mid_pct"], errors="coerce").notna()]
    if d.empty:
        print("暂无已平仓记录")
        return
    d["opt_return_mid_pct"] = pd.to_numeric(d["opt_return_mid_pct"])
    d["opt_return_pct"] = pd.to_numeric(d["opt_return_pct"], errors="coerce")
    d["stock_r"] = pd.to_numeric(d["stock_r"], errors="coerce")
    print(f"\n=== 期权纸面结果（{len(d)} 笔已平仓）===")
    print(f"  期权(mid口径) 胜率 {(d.opt_return_mid_pct>0).mean()*100:.0f}%  "
          f"平均 {d.opt_return_mid_pct.mean():+.1f}%  中位 {d.opt_return_mid_pct.median():+.1f}%")
    print(f"  保守口径(吃满价差) 胜率 {(d.opt_return_pct>0).mean()*100:.0f}%  "
          f"平均 {d.opt_return_pct.mean():+.1f}%   ← 两者之差即价差成本")
    print(f"  同期正股 平均 {d.stock_r.mean():+.2f}R  胜率 {(d.stock_r>0).mean()*100:.0f}%")
    both = d.dropna(subset=["stock_r"])
    if len(both) >= 5:
        agree = ((both.stock_r > 0) == (both.opt_return_mid_pct > 0)).mean() * 100
        print(f"  方向一致率 {agree:.0f}%（正股赚时期权也赚的比例）")
    print("\n按策略:")
    print(d.groupby("strategy")["opt_return_mid_pct"].agg(
        笔数="count", 胜率=lambda s: f"{(s>0).mean()*100:.0f}%", 平均=lambda s: f"{s.mean():+.1f}%").to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只看状态不动仓位")
    args = ap.parse_args()

    if args.status:
        state = _load_state()
        print(f"当前持有纸面期权仓 {len(state)} 个:")
        for sid, p in state.items():
            print(f"  {p['symbol']} {p['tf']} {p['opt_right']}{p['opt_strike']} "
                  f"@{p['opt_expiry']} 入场ask ${p['opt_ask']}")
        summary()
        return

    # 先拿锁再读 state：反过来的话，等锁的实例手里已经是一份过期快照，
    # 拿到锁后就会基于旧仓位做决策，等于没锁。
    lock = _acquire_lock()
    if lock is None:
        print("已有实例在运行，本轮跳过（避免重复开平仓）")
        return
    state = _load_state()

    print(f"白名单 {len(WHITELIST)} 个标的｜当前持仓 {len(state)} 个")
    c = close_finished(state)
    o = open_new(state)
    _save_state(state)
    print(f"\n本轮：新开 {o}，平仓 {c}，当前持仓 {len(state)}")
    summary()


if __name__ == "__main__":
    main()

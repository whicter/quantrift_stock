"""
options_review.py — 期权纸面账本复盘（只读，绝不下单）

背景（2026-09-03）：期权纸面模拟从 8/15 起每小时开平仓，累计 149 条记录，但
`signal_review.py` 只复盘正股信号，**期权账本从上线起就没有任何复盘机制**。
开了单不看结果，模拟本身就没有意义。本模块补上这一环，挂在周日的 weekly
review 里自动出表。

本模块回答的问题只有一个：**同一个信号，做正股和做期权哪个更划算，差在哪里。**
所以每个口径都同时给出正股 R 与期权收益，而不是孤立地看期权盈亏。

两个必须一直盯的口径：
  - mid→mid：用户指定的成交假设（不因价差宽而过滤，按中间价成交）
  - ask→bid：吃满价差的保守口径；两者之差就是价差成本，也是"限价单能否在 mid
    成交"这一假设的敞口。宽价差标的上两个数会差几十个点。

用法：
  python options_review.py                 # 近 7 天 + 全样本
  python options_review.py --days 30
  python options_review.py --telegram      # 同时推 TG
"""

import argparse
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
from dotenv import load_dotenv

# pm2 的 stock-weekly-review 会经 env 注入 TG 凭证，但手动跑时不会——
# 补一次 .env 加载，让两条路径行为一致（否则手动复盘会静默不推送）。
load_dotenv()

LEDGER = Path("logs/options_paper_log.csv")
MIN_DTE = 30          # 与 options_paper.MIN_DTE 对齐，用于数据质量校验


def load_ledger() -> pd.DataFrame:
    """读账本并去重。

    去重不是可选的清理步骤：2026-09-03 发现 149 行里有 23 行是同一仓位被并发的
    两个实例各写了一次（closed_at 相差 1-3 秒、入场数据完全相同）。重复行会把
    单笔盈亏重复计入统计，直接改变结论。锁已在 options_paper 里加上，但历史行
    仍在，且并发一旦复发这里要能自己发现——所以去重同时统计删掉了多少。
    """
    if not LEDGER.exists():
        return pd.DataFrame()
    d = pd.read_csv(LEDGER)
    d["opened_at"] = pd.to_datetime(d["opened_at"], errors="coerce")
    d["closed_at"] = pd.to_datetime(d["closed_at"], errors="coerce")
    n_raw = len(d)
    d = d.drop_duplicates(subset=["signal_id", "opened_at"], keep="first")
    d.attrs["dupes_dropped"] = n_raw - len(d)

    for c in ("opt_return_mid_pct", "opt_return_pct", "stock_r",
              "opt_entry_mid", "opt_entry_ask", "dte_at_entry"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["opt_return_mid_pct"].notna() & d["closed_at"].notna()].copy()
    d["hold_d"] = (d["closed_at"] - d["opened_at"]).dt.total_seconds() / 86400
    # bid = 2*mid - ask，账本没直接存入场 bid
    d["entry_spread_pct"] = ((d["opt_entry_ask"] - (2 * d["opt_entry_mid"] - d["opt_entry_ask"]))
                             / d["opt_entry_mid"] * 100)
    d["dte_left_at_exit"] = d["dte_at_entry"] - d["hold_d"]
    return d


def capture_ratio(df: pd.DataFrame) -> tuple[float, float, float] | None:
    """每单位正股 R 的期权捕获率，分赢单/输单。

    这是整份复盘里最有信息量的一个数：孤立看期权收益无法区分"策略不行"和
    "期权这个载体不行"。捕获率把正股表现除掉，只剩载体本身的效率。
    赢单捕获 / 输单捕获 < 1 就意味着——同样一个 R，期权在亏的方向上放大得
    比赚的方向更多，这是买方 gamma 与价差共同作用的结果。
    """
    w, l = df[df.stock_r > 0], df[df.stock_r < 0]
    if len(w) < 3 or len(l) < 3 or w.stock_r.sum() == 0 or l.stock_r.sum() == 0:
        return None
    cw = w.opt_return_mid_pct.sum() / w.stock_r.sum()
    cl = l.opt_return_mid_pct.sum() / l.stock_r.sum()
    return cw, cl, (cw / cl if cl else float("nan"))


def bootstrap_ratio(df: pd.DataFrame, n: int = 1000, seed: int = 0) -> tuple[float, float, float] | None:
    """赢输比的自助法 90% 区间。

    点估计单独看会骗人：126 笔里 Confluence 的 1.20 看着像"期权对 Confluence
    划算"，但重抽后区间是 [0.23, 3.19]，完全不能下结论。只有区间整体落在 1
    的一侧才算有证据。
    """
    import numpy as np
    base = capture_ratio(df)
    if base is None:
        return None
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        r = capture_ratio(df.sample(len(df), replace=True,
                                    random_state=int(rng.integers(1 << 31))))
        if r:
            out.append(r[2])
    if len(out) < n // 10:
        return None
    lo, hi = float(np.percentile(out, 5)), float(np.percentile(out, 95))
    return base[2], lo, hi


def _block(df: pd.DataFrame, title: str) -> list[str]:
    if df.empty:
        return [f"── {title}：无记录 ──"]
    mid, cons = df.opt_return_mid_pct, df.opt_return_pct
    out = [f"── {title}（{len(df)} 笔平仓）──",
           f"  期权 mid口径   均值 {mid.mean():+.2f}%　中位 {mid.median():+.2f}%　"
           f"胜率 {(mid > 0).mean() * 100:.0f}%",
           f"  期权 保守口径  均值 {cons.mean():+.2f}%　"
           f"→ 价差成本 {mid.mean() - cons.mean():.1f} 个点/笔",
           f"  同期正股       均值 {df.stock_r.mean():+.2f}R　"
           f"胜率 {(df.stock_r > 0).mean() * 100:.0f}%"]
    both = df.dropna(subset=["stock_r"])
    if len(both) >= 5:
        agree = ((both.stock_r > 0) == (both.opt_return_mid_pct > 0)).mean() * 100
        out.append(f"  方向一致率     {agree:.0f}%")
    cr = capture_ratio(df)
    if cr:
        # 两个数都是"每 1R 对应多少 % 期权盈亏"的绝对幅度，故都取正号呈现，
        # 否则 输单 = 负收益/负R = 正数，看起来像在赚钱。
        out.append(f"  捕获率         正股每赚1R→期权 {abs(cr[0]):.1f}%　"
                   f"每亏1R→期权 -{abs(cr[1]):.1f}%　赢输比 {cr[2]:.2f}"
                   + ("　⚠️ <1：亏损被放大得比盈利更多" if cr[2] < 1 else ""))
        bs = bootstrap_ratio(df)
        if bs:
            verdict = ("显著<1（期权是更差的载体）" if bs[2] < 1 else
                       "显著>1" if bs[1] > 1 else "跨过1，样本不足以下结论")
            out.append(f"  赢输比90%区间   [{bs[1]:.2f}, {bs[2]:.2f}]　{verdict}")
    out.append(f"  持仓           中位 {df.hold_d.median() * 24:.1f} 小时　"
               f"最长 {df.hold_d.max():.1f} 天")
    return out


def _quality(df: pd.DataFrame) -> list[str]:
    """数据质量自检——复盘先要能信任自己的账本。"""
    out = ["── 账本质量 ──"]
    dupes = df.attrs.get("dupes_dropped", 0)
    out.append(f"  重复行 {dupes} 条（已剔除）" + ("　⚠️ 并发锁可能失效" if dupes else "　✅"))
    under = int((df.dte_at_entry < MIN_DTE).sum())
    out.append(f"  入场 DTE < {MIN_DTE} 的 {under} 笔 / {len(df)}"
               + ("　⚠️ 违反到期下限" if under else "　✅"))
    if df.dte_left_at_exit.notna().any():
        out.append(f"  出场时最少剩余 DTE {df.dte_left_at_exit.min():.1f} 天"
                   + ("　⚠️ 逼近到期" if df.dte_left_at_exit.min() < 7 else ""))
    return out


def report(days: int) -> str:
    d = load_ledger()
    if d.empty:
        return "期权纸面账本无已平仓记录。"
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    recent = d[d.closed_at >= cutoff]

    lines = ["=== 期权纸面复盘（模拟，从未下单）==="]
    lines += _block(recent, f"最近 {days} 天") + [""]
    lines += _block(d, "全样本") + [""]
    lines += _quality(d) + [""]

    base = recent if len(recent) >= 10 else d
    tag = f"最近{days}天" if len(recent) >= 10 else "全样本"
    for col, label in (("strategy", "策略"), ("tf", "周期")):
        g = base.groupby(col).agg(笔数=("symbol", "size"),
                                  正股R=("stock_r", "mean"),
                                  期权mid=("opt_return_mid_pct", "mean"),
                                  保守=("opt_return_pct", "mean")).round(2)
        lines += [f"── 按{label}（{tag}）──", g.to_string(), ""]

    bucket = pd.cut(base.entry_spread_pct, [0, 5, 10, 20, 1e4],
                    labels=["<5%", "5-10%", "10-20%", ">20%"])
    g = base.groupby(bucket, observed=True).agg(笔数=("symbol", "size"),
                                                期权mid=("opt_return_mid_pct", "mean"),
                                                保守=("opt_return_pct", "mean"),
                                                正股R=("stock_r", "mean")).round(2)
    lines += [f"── 按入场价差（{tag}）──", g.to_string(), ""]

    cols = ["symbol", "tf", "strategy", "direction", "dte_at_entry",
            "stock_r", "opt_return_mid_pct", "opt_return_pct", "exit_reason"]
    lines += ["── 最好 5 笔 ──", base.nlargest(5, "opt_return_mid_pct")[cols].round(2).to_string(index=False), "",
              "── 最差 5 笔 ──", base.nsmallest(5, "opt_return_mid_pct")[cols].round(2).to_string(index=False)]
    return "\n".join(lines)


def telegram(days: int) -> None:
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    d = load_ledger()
    if d.empty:
        return
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    r = d[d.closed_at >= cutoff]
    lines = [f"🎲 期权纸面周复盘（模拟，未下单）"]
    if r.empty:
        lines.append(f"最近 {days} 天无平仓记录")
    else:
        mid, cons = r.opt_return_mid_pct, r.opt_return_pct
        lines += [f"本周 {len(r)} 笔　mid {mid.mean():+.2f}%　胜率 {(mid > 0).mean() * 100:.0f}%",
                  f"保守口径 {cons.mean():+.2f}%　价差成本 {mid.mean() - cons.mean():.1f} 点/笔",
                  f"同期正股 {r.stock_r.mean():+.2f}R　胜率 {(r.stock_r > 0).mean() * 100:.0f}%"]
        cr = capture_ratio(r)
        if cr:
            lines.append(f"每赚1R→期权 {abs(cr[0]):.1f}%　每亏1R→期权 -{abs(cr[1]):.1f}%　"
                         f"赢输比 {cr[2]:.2f}")
    cr_all = capture_ratio(d)
    lines += ["", f"全样本 {len(d)} 笔　mid {d.opt_return_mid_pct.mean():+.2f}%　"
                  f"正股 {d.stock_r.mean():+.2f}R"]
    if cr_all:
        lines.append(f"全样本赢输比 {cr_all[2]:.2f}"
                     + ("（<1：亏损放大更多）" if cr_all[2] < 1 else ""))
    dupes, under = d.attrs.get("dupes_dropped", 0), int((d.dte_at_entry < MIN_DTE).sum())
    if dupes or under:
        lines += ["", f"⚠️ 账本：重复 {dupes} 条／DTE 越界 {under} 笔"]
    lines.append("详情：logs/options_paper_log.csv")

    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": "\n".join(lines)}, timeout=10)
    except requests.RequestException:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="期权纸面账本复盘")
    ap.add_argument("--days", type=int, default=7, help="近 N 天（默认7）")
    ap.add_argument("--telegram", action="store_true", help="同时推送 TG")
    args = ap.parse_args()
    print(report(args.days))
    if args.telegram:
        telegram(args.days)


if __name__ == "__main__":
    main()

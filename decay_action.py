"""
decay_action.py — 把衰减监控从"只看"变成"看了就查"

背景（2026-08-15，用户提出的关键质疑）：
  原先衰减监控只打印红/黄/绿，没有任何处置动作。但用户指出直接按实盘红灯降级
  有真实风险："降级了正好碰到之后的市场更合适，升级了正好碰到市场不合适"——
  红灯样本量只有 5-20 笔，两周的实盘偏离完全可能是市场风格切换的噪音，据此改
  结构就是在追噪音。用户的结论是"本质是不是先认真回测"，本模块即按此实现。

处置链条（红灯本身不构成降级依据）：
  连续 N 周红灯 → 自动用最新数据重跑成本压力 + walk-forward
    ├─ 重验证也挂  → 降级（结构确实坏了，实盘与历史双重确认）
    └─ 重验证通过  → 保留，标记"实盘偏离但结构未坏"，继续观察
  升级方向永远只走完整验证流程，绝不因为"实盘连续几周好"就自动恢复——
  那是同一个噪音陷阱的镜像。

降级写入 `logs/demoted_routes.json`（数据），不改 `alert_engine.py`（代码）：
  无人值守任务改源码不安全也不可审计；alert_engine 启动时读这份清单，命中的
  组合改为影子记录（继续攒数据以便观察是否恢复），不再推送 Telegram。
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

HISTORY_PATH = Path("logs/review_history.csv")
DEMOTED_PATH = Path("logs/demoted_routes.json")
RED_STREAK_TRIGGER = 2      # 连续几个批次红灯才触发重验证
PASS_BPS = 10
PASS_SHARPE = 0.6


def route_key(strategy: str, symbol: str, tf: str) -> str:
    return f"{strategy.lower()}|{symbol.upper()}|{tf}"


def load_demoted() -> dict:
    if not DEMOTED_PATH.exists():
        return {}
    try:
        return json.loads(DEMOTED_PATH.read_text())
    except Exception:
        return {}


def save_demoted(data: dict) -> None:
    DEMOTED_PATH.parent.mkdir(exist_ok=True)
    DEMOTED_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def red_streaks(min_streak: int = RED_STREAK_TRIGGER) -> list[dict]:
    """返回当前处于连续红灯状态的组合（按最近批次向前数）。"""
    if not HISTORY_PATH.exists():
        return []
    try:
        hist = pd.read_csv(HISTORY_PATH)
    except Exception as exc:
        print(f"⚠ review_history.csv 解析失败: {exc}")
        return []
    if hist.empty or "tf" not in hist.columns:
        return []

    out = []
    for (strategy, symbol, tf), group in hist.groupby(["strategy", "symbol", "tf"]):
        seq = group.sort_values("timestamp")
        # 只数最近连续的红：一旦遇到非红就停，避免把历史上零散的红灯累加成"连续"
        streak = 0
        for status in reversed(seq["status"].tolist()):
            if status == "红":
                streak += 1
            elif status == "样本不足":
                continue          # 样本不足是"没测"，不打断连续性也不计入
            else:
                break
        if streak >= min_streak:
            last = seq.iloc[-1]
            out.append({"strategy": strategy, "symbol": symbol, "tf": tf,
                        "streak": streak, "mean_r": float(last["mean_r"]),
                        "baseline_r": float(last["baseline_r"]),
                        "z": float(last["z_vs_baseline"]), "n": int(last["n"])})
    return sorted(out, key=lambda r: r["z"])


def revalidate(strategy: str, symbol: str, tf: str) -> dict | None:
    """用最新数据重跑该组合的成本压力 + walk-forward。"""
    import warnings
    warnings.filterwarnings("ignore")
    import rsi2_backtest as r2
    import validate_watchlist as vw

    # 影子策略名（如 RSI2_IBS_shadow）不对应实盘路由，不做重验证
    base = strategy.lower().replace("52w", "")
    if base.endswith("_shadow") or base not in ("confluence", "rsi2", "mr", "breakout"):
        return None

    qqq = {t: r2.load_data("QQQ", t) for t in ("1h", "4h", "1d")}
    try:
        return vw.validate_one(base, symbol, tf, qqq, r2.load_vix())
    except Exception as exc:
        print(f"  ⚠ 重验证 {symbol} {tf} {base} 失败: {exc}")
        return None


def process(dry_run: bool = False) -> list[str]:
    """跑完整处置链条，返回给 Telegram 的文本行。"""
    lines: list[str] = []
    streaks = red_streaks()
    if not streaks:
        return lines

    demoted = load_demoted()
    lines.append(f"🔬 连续{RED_STREAK_TRIGGER}周以上红灯 {len(streaks)} 项，已自动重验证：")

    for item in streaks:
        key = route_key(item["strategy"], item["symbol"], item["tf"])
        tag = f"{item['strategy']}/{item['symbol']}/{item['tf']}"
        if key in demoted:
            lines.append(f"· {tag}：已于 {demoted[key]['demoted_at'][:10]} 降级，跳过")
            continue

        res = revalidate(item["strategy"], item["symbol"], item["tf"])
        if res is None:
            lines.append(f"· {tag}：非实盘路由或数据不足，跳过重验证")
            continue

        cost_ok = res.get("cost_verdict") == "pass"
        wf_bad = res.get("wf_verdict") == "fail"
        s10 = res.get(f"sharpe_{PASS_BPS}bps")

        if not cost_ok or wf_bad:
            lines.append(f"· {tag} ❌ 重验证未通过（10bps={s10} wf={res.get('wf_verdict')}）"
                         f"→ 降级为影子")
            if not dry_run:
                demoted[key] = {
                    "demoted_at": datetime.now().isoformat(timespec="seconds"),
                    "reason": f"连续{item['streak']}周红灯且重验证未通过",
                    "live_mean_r": item["mean_r"], "expected_r": item["baseline_r"],
                    "live_z": item["z"],
                    "reval_sharpe_10bps": s10, "reval_wf": res.get("wf_verdict"),
                    "reval_n": res.get("n"),
                }
        else:
            lines.append(f"· {tag} ✅ 重验证通过（10bps={s10} wf={res.get('wf_verdict')}）"
                         f"→ 保留，实盘偏离但结构未坏")

    if not dry_run:
        save_demoted(demoted)
    if demoted:
        lines.append(f"当前降级中 {len(demoted)} 项（见 logs/demoted_routes.json）")
    return lines


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", help="只列出连续红灯项，不重验证")
    args = ap.parse_args()

    if args.list:
        for s in red_streaks():
            print(f"{s['strategy']}/{s['symbol']}/{s['tf']}: 连续{s['streak']}批次红灯 "
                  f"均R{s['mean_r']:+.2f} vs 期望{s['baseline_r']:+.2f} z={s['z']:+.2f}")
    else:
        for line in process(dry_run=args.dry_run):
            print(line)

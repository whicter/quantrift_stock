"""backup_ledgers.py — 把**不可再生**的账本镜像到 X9_Pro。

═══ 为什么只备这几个文件 ═══
分三类，只有第一类值得备：

  ① 不可再生（本脚本的范围，约 1.7 MB）
     `signal_log.csv`        引擎当时**实际发出**的信号，带那一刻的 params/
                             market_score/vix 快照。输入是当时的盘中行情，过去就没了。
     `options_paper_log.csv` 开/平仓那一分钟的期权 bid/ask/IV/OI。期权报价没有免费
                             历史源，这是我们唯一的样本。
     `review_history.csv`    衰减监控的历史判级。重算只能用今天的价格，还原不出当时。
     `paper_equity.csv` + `.paper_positions.json` + `.open_ideas.json`
     `options_skipped.csv` / `options_whitelist_live.csv`
     `.sent_signals.json`    去重状态；丢了会重复推送。
     `.env`                  TG 凭证。
     ——这些全被 `.gitignore` 的 `logs/*.csv` 挡在版本控制外，此前**只有系统盘一份**。

  ② 可再生但重拉很贵：`data/` 下 6.5 GB 历史 CSV。
     **本脚本不碰它们**——它们本来就在 X9_Pro 上（`data/` 是指向它的符号链接），
     往同一块盘再复制一份等于没有备份。要真正防它，得放到另一块物理盘
     （兄弟项目 `stock_volatility_alert` 备到 WD_BLACK 就是这个道理）。

  ③ 不必备：`backfill_*.csv`（29 MB，`historical_backfill.py --write` 十分钟重算）、
     `.venv`、运行日志、模型缓存。

═══ 镜像不能无脑覆盖 ═══
账本是**只增不减**的。源文件如果变小了，说明出了事（截断、写坏、被误删），这时
覆盖备份等于把损坏复制过去，把唯一的好副本也毁掉。所以：**变小就拒绝覆盖并告警**，
保留上一份。这条是本仓库反复踩过的「静默失败」的同一类防线。

每次写：`latest/`（最新一份）+ `daily/YYYY-MM-DD/`（当天一份，保留最近 KEEP_DAYS 天）。

用法：
    python3.11 backup_ledgers.py              # 执行备份
    python3.11 backup_ledgers.py --verify-only  # 只校验，不写
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DEST = Path("/Volumes/X9_Pro/data_seriliazation/quantrift_stock/backup")
KEEP_DAYS = 30
STATE = ROOT / "logs/.backup_state.json"
HEARTBEAT = ROOT / "logs/.backup_heartbeat"

# 只增不减的账本（变小 ⇒ 拒绝覆盖）
APPEND_ONLY = [
    "logs/signal_log.csv",
    "logs/options_paper_log.csv",
    "logs/paper_equity.csv",
    "logs/review_history.csv",
    "logs/options_skipped.csv",
]
# 会整体重写的状态文件（大小可增可减，不做单调性检查）
MUTABLE = [
    "data/.paper_positions.json",
    "data/.open_ideas.json",
    "data/.sent_signals.json",
    "data/.data_sources.json",
    "logs/options_whitelist_live.csv",
    ".env",
]
FILES = APPEND_ONLY + MUTABLE


def _tg(msg: str) -> None:
    token, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT_ID")
    if not token or not chat:
        print("[TG] 未配置凭证，跳过推送")
        return
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode(),
            timeout=15)
    except Exception as exc:
        print(f"[TG] 推送失败: {exc}")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true", help="只校验，不写入")
    args = ap.parse_args()

    print(f"=== backup_ledgers {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    if not DEST.parent.parent.exists():
        print(f"⚠ X9_Pro 未挂载（{DEST.parent.parent} 不存在），跳过本轮")
        _tg("⚠️ quantrift_stock 账本备份跳过：X9_Pro 未挂载")
        return 0

    state = _load_state()
    problems: list[str] = []
    planned: list[tuple[Path, int, str]] = []

    for rel in FILES:
        src = ROOT / rel
        if not src.exists():
            problems.append(f"⚠️ 源文件不存在：{rel}")
            print(f"  {rel:<38} 不存在 ⚠️")
            continue
        size = src.stat().st_size
        prev = state.get(rel, {})
        shrink = rel in APPEND_ONLY and prev.get("size") and size < prev["size"]
        tag = ""
        if shrink:
            tag = f"  ⚠️ 变小 {prev['size']}→{size}，拒绝覆盖"
            problems.append(
                f"⚠️ {rel} 比上次备份小了（{prev['size']} → {size} 字节）。"
                f"账本只增不减，变小说明被截断或写坏——**已拒绝覆盖**，"
                f"X9_Pro 上保留的仍是上一份好副本。先查源文件再决定。")
        elif prev.get("sha") and prev["sha"] == _sha(src):
            tag = "  （未变）"
        print(f"  {rel:<38} {size:>9,} 字节{tag}")
        if not shrink:
            planned.append((src, size, rel))

    if args.verify_only:
        print(f"\n--verify-only：本应备份 {len(planned)} 个文件，发现 {len(problems)} 个问题")
        for p in problems:
            print("  " + p)
        return 0

    today = date.today().isoformat()
    latest, daily = DEST / "latest", DEST / "daily" / today
    latest.mkdir(parents=True, exist_ok=True)
    daily.mkdir(parents=True, exist_ok=True)

    total = 0
    for src, size, rel in planned:
        name = rel.replace("/", "_")
        for d in (latest, daily):
            tmp = d / (name + ".tmp")
            shutil.copy2(src, tmp)
            os.replace(tmp, d / name)      # 原子落地，避免半截文件
        state[rel] = {"size": size, "sha": _sha(src), "at": datetime.now().isoformat(timespec="seconds")}
        total += size

    # 回读校验：备份件必须与源一致
    bad = [rel for _, _, rel in planned
           if _sha(latest / rel.replace("/", "_")) != state[rel]["sha"]]
    if bad:
        problems.append(f"⚠️ 回读校验不一致：{bad}")

    cutoff = date.today() - timedelta(days=KEEP_DAYS)
    for d in sorted((DEST / "daily").iterdir()):
        try:
            if date.fromisoformat(d.name) < cutoff:
                shutil.rmtree(d)
        except ValueError:
            continue

    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    HEARTBEAT.write_text(str(int(time.time())))
    kept = len(list((DEST / "daily").iterdir()))
    print(f"\n已备份 {len(planned)} 个文件 / {total:,} 字节 → {DEST}")
    print(f"每日快照保留 {kept} 份（上限 {KEEP_DAYS} 天）")
    if problems:
        _tg("🗄 quantrift_stock 账本备份有问题\n\n" + "\n\n".join(problems))
        print(f"⚠ {len(problems)} 个问题，已推送")
    else:
        print("备份完成，无异常")
    return 0


if __name__ == "__main__":
    sys.exit(main())

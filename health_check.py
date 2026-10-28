"""health_check.py — 磁盘余量 + 定时任务存活监控（只读，不下单、不改状态）

为什么需要它：本项目已经三次踩同一类坑，每次都是"任务照常退出 0、日志不报错、
pm2 显示 stopped（和正常跑完一样）"，只有日志文件 mtime 不更新能看出来：

  2026-09-03  夜间 IB 保鲜中途掉线          无人察觉 13 天
  2026-09-03  36 条 RSI2 4h 路由零信号      无人察觉一个上线周期（对照工具自己也坏了 6 周）
  2026-09-23  磁盘写满 → 5 个 cron 停摆     无人察觉 9 天（9/27 周复盘直接丢失）

每一次的发现方式都是"人恰好去翻日志"。LEARNING.md 里那句"监控工具本身也需要
监控"写了一个月，但一直没有东西在看这些任务是否还活着。

检查三类：
  1. 磁盘余量（系统盘 + 外置盘挂载状态）——9/23 的根因就是系统盘写满
  2. 各定时任务的产出文件是否按预期刷新——唯一能发现静默停摆的信号
  3. 主引擎是否在扫（signal_log mtime）

阈值取得宽松（日级任务给 80 小时，覆盖周末；小时级给 3 小时），宁可漏报一轮也
不要每天误报——会叫的狼来了没人听，和没有监控是一样的。

自身也会被监控：每轮写 `logs/.health_heartbeat`，`alert_engine` 每小时扫描时检查
这个文件的年龄，超过 3 小时会在控制台提示（见 alert_engine._check_watchdog）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
HEARTBEAT = ROOT / "logs/.health_heartbeat"
ALERT_STATE = ROOT / "logs/.health_alert_state.json"
EXTERNAL = Path("/Volumes/X9_Pro/data_seriliazation/quantrift_stock")

DISK_WARN_GB = 25.0      # 低于此值告警
DISK_URGENT_GB = 10.0    # 低于此值标记为紧急

# (产出文件, 最大允许年龄小时, 任务名)
# 日级任务给 80 小时：周五 14:40 跑完到周一 13:20 约 71 小时，留余量。
# (产出文件, 最大允许年龄小时, 任务名, 健康标记)
#
# ⚠️ 第四条字段是 2026-10-22 加的，起因是 mtime 根本不足以判定产出有效：
# `signal_review` 从 10/11 起每轮都崩在 KeyError 'High'，**traceback 照样写进
# weekly_review.log**，mtime 每周正常刷新，本脚本连续两周报「全部正常」。
# 而 `run_weekly_review.sh` 有 `set -e`，signal_review 一挂，期权复盘根本不执行
# ——`options_review.log` 停在 10/04 却从来没被监控过，因为它压根不在清单里。
#
# 所以现在要求：文件尾部必须出现「这一轮真的跑完了」的标记，且最后一次标记之后
# 不得再有 traceback。标记为 None 表示该文件只看 mtime（心跳文件没有内容特征）。
WATCHED = [
    # 用 pm2 输出日志而不是 signal_log.csv：后者只在**有信号时**才写，
    # 无信号的几个小时会被误判成引擎死了。pm2 out 每轮扫描都有输出。
    ("~/.pm2/logs/stock-alert-out.log", 3, "stock-alert（主引擎，每小时）", "扫描完成"),
    ("logs/options_paper.log",       3, "stock-options-paper（每小时 :10）", "期权纸面"),
    ("logs/nightly_ib_refresh.log", 80, "stock-nightly-ib-refresh（交易日 14:40）", "本轮"),
    ("logs/daily_screener.log",     80, "stock-daily-screener（交易日 13:20）", "[Telegram]"),
    ("logs/watchlist_events.log",   80, "stock-watchlist-events（交易日 13:35）", "[Telegram]"),
    ("logs/weekly_review.log",     216, "stock-weekly-review·正股（周日 18:15）", "汇总统计"),
    # 期权复盘单列一项：它是 run_weekly_review.sh 的**第二条命令**，前一条崩掉时
    # 它不会执行，而 weekly_review.log 的 mtime 看不出这件事。
    ("logs/options_review.log",    216, "stock-weekly-review·期权（周日 18:15）", "期权纸面复盘"),
    # 只看真实盘中重测成功后写入的心跳；盘后拒绝也会更新运行日志，不能据此判健康。
    ("logs/.options_whitelist_heartbeat", 216, "stock-options-whitelist（周三 11:00）", None),
    # 同理看心跳：X9_Pro 未挂载或拒绝覆盖时也会写运行日志，不能据此判健康。
    ("logs/.backup_heartbeat", 30, "stock-backup-ledgers（每日 21:05）", None),
]

TAIL_BYTES = 20000      # 只读尾部，日志有几十 MB


def _tg(msg: str) -> bool:
    token, chat = os.getenv("TG_TOKEN"), os.getenv("TG_CHAT_ID")
    if not token or not chat:
        print("[TG] 未配置凭证，跳过推送")
        return False
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode(),
            timeout=15)
        print("[TG] 推送成功")
        return True
    except Exception as exc:          # 推送失败绝不影响检查本身
        print(f"[TG] 推送失败: {exc}")
        return False


def _load_alert_state() -> set[str]:
    """读取上轮仍未解决的问题键；损坏的状态文件不能阻断检查。"""
    try:
        data = json.loads(ALERT_STATE.read_text())
        return {str(key) for key in data.get("active", [])}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return set()


def _save_alert_state(active: set[str]) -> None:
    ALERT_STATE.write_text(json.dumps({"active": sorted(active)}, ensure_ascii=False) + "\n")


def _new_problem_messages(
    problems: list[tuple[str, str]], previous: set[str]
) -> list[str]:
    """同一未解决问题只通知一次；新增问题或问题集合改变时才推送。"""
    return [message for key, message in problems if key not in previous]


def check_disk() -> list[tuple[str, str]]:
    out = []
    usage = shutil.disk_usage("/System/Volumes/Data")
    free_gb = usage.free / 1024 ** 3
    tag = "🔴" if free_gb < DISK_URGENT_GB else ("⚠️" if free_gb < DISK_WARN_GB else "")
    line = f"系统盘可用 {free_gb:,.1f} GB / {usage.total / 1024**3:,.0f} GB"
    print(f"  {line}")
    if tag:
        out.append(("disk:system", f"{tag} {line}（低于 {DISK_WARN_GB:.0f} GB 阈值；"
                   f"2026-09-23 写满时打掉了 5 个定时任务，9 天无人察觉）"))
    if not EXTERNAL.exists():
        out.append(("disk:external", "⚠️ 外置盘未挂载：data/ 下 2,800+ 个历史 CSV 是指向它的符号链接，"
                   "夜间保鲜/回测/选股会受影响"))
        print("  外置盘：未挂载 ⚠️")
    else:
        ext = shutil.disk_usage(EXTERNAL)
        print(f"  外置盘可用 {ext.free / 1024**3:,.0f} GB")
    return out


def check_jobs() -> list[tuple[str, str]]:
    out = []
    now = time.time()
    for rel, max_age_h, name, marker in WATCHED:
        path = Path(rel).expanduser() if rel.startswith("~") else ROOT / rel
        if not path.exists():
            out.append((f"job:{rel}", f"⚠️ {name}：产出文件不存在（{rel}）"))
            print(f"  {name}: 文件不存在 ⚠️")
            continue
        age_h = (now - path.stat().st_mtime) / 3600
        stale = age_h > max_age_h
        note = ""
        if marker:
            try:
                with open(path, "rb") as fh:
                    fh.seek(max(0, path.stat().st_size - TAIL_BYTES))
                    tail = fh.read().decode("utf-8", errors="replace")
            except OSError as exc:
                tail = ""
                note = f"  读取失败 {exc}"
            pos = tail.rfind(marker)
            if pos < 0:
                note = f"  尾部无「{marker}」⚠️"
                out.append((f"content:{rel}",
                            f"⚠️ {name}：日志尾部找不到成功标记「{marker}」——"
                            f"mtime 是新的但这一轮没跑完（2026-10-22 周复盘崩溃两周就是这种）"))
            elif "Traceback (most recent call last)" in tail[pos:]:
                note = "  最后一次成功之后有 traceback ⚠️"
                out.append((f"content:{rel}",
                            f"⚠️ {name}：最后一次成功标记之后出现 traceback，"
                            f"最近一轮很可能已崩溃 → `tail -40 {rel}`"))
        print(f"  {name}: {age_h:5.1f}h 前更新（上限 {max_age_h}h）"
              + ("  ⚠️" if stale else "") + note)
        if stale:
            out.append((f"job:{rel}", f"⚠️ {name} 已 {age_h:.0f} 小时没有产出（上限 {max_age_h}h）→ "
                       f"检查 `pm2 describe` 与日志 mtime；修法见 CLAUDE.md"
                       f"「磁盘写满打掉 5 个定时任务」"))
    return out


def main() -> int:
    print(f"=== health_check {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    problems: list[tuple[str, str]] = []
    for fn in (check_disk, check_jobs):
        try:
            problems += fn()
        except Exception as exc:      # 单项检查失败不能让整个守护进程哑掉
            problems.append((f"check:{fn.__name__}", f"⚠️ 检查项 {fn.__name__} 自身异常：{exc}"))
            print(f"  {fn.__name__} 异常: {exc}")
    HEARTBEAT.parent.mkdir(exist_ok=True)
    HEARTBEAT.write_text(str(int(time.time())))
    previous = _load_alert_state()
    active = {key for key, _ in problems}
    new_messages = _new_problem_messages(problems, previous)
    _save_alert_state(active)
    if new_messages:
        _tg("🏥 quantrift_stock 健康检查发现问题\n\n" + "\n\n".join(new_messages))
        print(f"\n发现 {len(problems)} 个问题，其中 {len(new_messages)} 个为新增，已推送")
    elif problems:
        print(f"\n发现 {len(problems)} 个未解决问题，与上轮相同，不重复推送")
    else:
        print("\n全部正常")
    return 0                           # 永远正常退出，不触发 pm2 crash-restart


if __name__ == "__main__":
    sys.exit(main())

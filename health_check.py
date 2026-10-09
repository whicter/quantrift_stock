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
EXTERNAL = Path("/Volumes/X9_Pro/data_seriliazation/quantrift_stock")

DISK_WARN_GB = 25.0      # 低于此值告警
DISK_URGENT_GB = 10.0    # 低于此值标记为紧急

# (产出文件, 最大允许年龄小时, 任务名)
# 日级任务给 80 小时：周五 14:40 跑完到周一 13:20 约 71 小时，留余量。
WATCHED = [
    # 用 pm2 输出日志而不是 signal_log.csv：后者只在**有信号时**才写，
    # 无信号的几个小时会被误判成引擎死了。pm2 out 每轮扫描都有输出。
    ("~/.pm2/logs/stock-alert-out.log", 3, "stock-alert（主引擎，每小时）"),
    ("logs/options_paper.log",       3, "stock-options-paper（每小时 :10）"),
    ("logs/nightly_ib_refresh.log", 80, "stock-nightly-ib-refresh（交易日 14:40）"),
    ("logs/daily_screener.log",     80, "stock-daily-screener（交易日 13:20）"),
    ("logs/watchlist_events.log",   80, "stock-watchlist-events（交易日 13:35）"),
    ("logs/weekly_review.log",     216, "stock-weekly-review（周日 18:15）"),
    ("logs/options_whitelist.log", 216, "stock-options-whitelist（周三 11:00）"),
]


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
        print("[TG] 推送成功")
    except Exception as exc:          # 推送失败绝不影响检查本身
        print(f"[TG] 推送失败: {exc}")


def check_disk() -> list[str]:
    out = []
    usage = shutil.disk_usage("/System/Volumes/Data")
    free_gb = usage.free / 1024 ** 3
    tag = "🔴" if free_gb < DISK_URGENT_GB else ("⚠️" if free_gb < DISK_WARN_GB else "")
    line = f"系统盘可用 {free_gb:,.1f} GB / {usage.total / 1024**3:,.0f} GB"
    print(f"  {line}")
    if tag:
        out.append(f"{tag} {line}（低于 {DISK_WARN_GB:.0f} GB 阈值；"
                   f"2026-09-23 写满时打掉了 5 个定时任务，9 天无人察觉）")
    if not EXTERNAL.exists():
        out.append("⚠️ 外置盘未挂载：data/ 下 2,800+ 个历史 CSV 是指向它的符号链接，"
                   "夜间保鲜/回测/选股会受影响")
        print("  外置盘：未挂载 ⚠️")
    else:
        ext = shutil.disk_usage(EXTERNAL)
        print(f"  外置盘可用 {ext.free / 1024**3:,.0f} GB")
    return out


def check_jobs() -> list[str]:
    out = []
    now = time.time()
    for rel, max_age_h, name in WATCHED:
        path = Path(rel).expanduser() if rel.startswith("~") else ROOT / rel
        if not path.exists():
            out.append(f"⚠️ {name}：产出文件不存在（{rel}）")
            print(f"  {name}: 文件不存在 ⚠️")
            continue
        age_h = (now - path.stat().st_mtime) / 3600
        stale = age_h > max_age_h
        print(f"  {name}: {age_h:5.1f}h 前更新（上限 {max_age_h}h）" + ("  ⚠️" if stale else ""))
        if stale:
            out.append(f"⚠️ {name} 已 {age_h:.0f} 小时没有产出（上限 {max_age_h}h）→ "
                       f"检查 `pm2 describe` 与日志 mtime；修法见 CLAUDE.md"
                       f"「磁盘写满打掉 5 个定时任务」")
    return out


def main() -> int:
    print(f"=== health_check {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    problems: list[str] = []
    for fn in (check_disk, check_jobs):
        try:
            problems += fn()
        except Exception as exc:      # 单项检查失败不能让整个守护进程哑掉
            problems.append(f"⚠️ 检查项 {fn.__name__} 自身异常：{exc}")
            print(f"  {fn.__name__} 异常: {exc}")
    HEARTBEAT.parent.mkdir(exist_ok=True)
    HEARTBEAT.write_text(str(int(time.time())))
    if problems:
        _tg("🏥 quantrift_stock 健康检查发现问题\n\n" + "\n\n".join(problems))
        print(f"\n发现 {len(problems)} 个问题，已推送")
    else:
        print("\n全部正常")
    return 0                           # 永远正常退出，不触发 pm2 crash-restart


if __name__ == "__main__":
    sys.exit(main())

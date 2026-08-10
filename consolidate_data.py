"""
consolidate_data.py — 把 data/ 下的历史行情 CSV 迁到外置盘，本地只留符号链接

背景（2026-08-09）：data/ 下 3000+ 个历史行情 CSV（416M）不是实时告警引擎的
主数据源（那是 yfinance），只在缺口填补/整体拉空兜底、以及夜间刷新/回测/选股
等离线任务里才会被读写——不需要占本地盘。真正频繁读写的几个小文件
（.sent_signals.json / .paper_positions.json / .data_sources.json /
screener_results.csv / russell2000_tickers.txt）体积很小，留在本地。

做法：对 data/ 下每个真实（非符号链接）*.csv 文件，搬到外置盘对应路径，
原地留一个同名符号链接指回去。全部通过硬编码/配置的 "data/xxx.csv" 相对路径
访问的代码（fetch_ib_data.py、backtest_runner.py、screener.py、alert_engine.py
的兜底逻辑等）完全不用改——Python 的文件 I/O 会透明地跟随符号链接读写，
新一轮 nightly refresh 直接写透到外置盘。

幂等：已经是符号链接的文件直接跳过，只处理还在本地的真实文件——所以
本脚本既用于这次的一次性迁移，也用作以后的定期清理任务（新加的标的、
临时脚本产生的新 CSV，只要还没做过符号链接，下次跑这个脚本就会被搬走）。

用法：
  python consolidate_data.py            # 执行迁移
  python consolidate_data.py --dry-run  # 只打印将要迁移的文件，不动
"""

import argparse
import shutil
from pathlib import Path

LOCAL_DIR = Path("data")
EXTERNAL_ROOT = Path("/Volumes/X9_Pro/data_seriliazation/quantrift_stock/data")

# 不是"历史行情"，是实时扫描每轮都要读/每日要重写的小文件——留在本地，
# 不能符号链接到外置盘（外置盘掉线会直接影响 alert_engine 的选股标注）。
KEEP_LOCAL = {"screener_results.csv"}


def consolidate(dry_run: bool = False) -> tuple[int, int]:
    if not EXTERNAL_ROOT.parent.parent.exists():
        print(f"⚠ 外置盘未挂载（{EXTERNAL_ROOT.parent.parent}不存在），跳过本轮整理")
        return 0, 0

    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)

    moved, skipped = 0, 0
    for path in sorted(LOCAL_DIR.glob("*.csv")):
        if path.is_symlink() or path.name in KEEP_LOCAL:
            skipped += 1
            continue
        dest = EXTERNAL_ROOT / path.name
        if dry_run:
            print(f"[将迁移] {path} -> {dest}")
            moved += 1
            continue
        try:
            shutil.move(str(path), str(dest))
            path.symlink_to(dest)
            moved += 1
        except Exception as e:
            print(f"  ⚠ {path.name} 迁移失败: {e}")

    print(f"{'(演练) ' if dry_run else ''}迁移 {moved} 个文件，跳过 {skipped} 个已是符号链接的文件")
    return moved, skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    consolidate(dry_run=args.dry_run)

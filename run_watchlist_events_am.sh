#!/bin/zsh
# 每交易日 07:45 PT（10:45 ET，开盘75分钟后）：盘中事件雷达
# 抓开盘 gap / 早盘异动——SHOP 2026-07-27 +12.4% 这类新闻驱动暴拉，
# 收盘后雷达要等 6 小时才报，盘中轮次开盘后 75 分钟即报。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 watchlist_events.py --telegram --intraday >> logs/watchlist_events.log 2>&1

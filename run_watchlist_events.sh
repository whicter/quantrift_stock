#!/bin/zsh
# 每交易日收盘后：watchlist 全池事件雷达（52W突破/放量新高/异动）-> Telegram
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 watchlist_events.py --telegram >> logs/watchlist_events.log 2>&1

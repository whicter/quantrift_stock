#!/bin/zsh
# 每交易日收盘后：watchlist 全池因子选股 Top15 -> Telegram
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 screener.py --universe watchlist --top 15 --telegram >> logs/daily_screener.log 2>&1

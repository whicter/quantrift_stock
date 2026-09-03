#!/bin/zsh
# Cron/pm2-safe weekly review.  It only reads market data and sends Telegram.
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 signal_review.py --days 90 --monitor --telegram >> logs/weekly_review.log 2>&1
# 期权纸面账本复盘。2026-09-03 之前它从上线起就没被复盘过——开了单不看结果，
# 模拟本身没有意义。只读账本，不碰仓位。
/opt/homebrew/bin/python3.11 options_review.py --days 7 --telegram >> logs/options_review.log 2>&1

#!/bin/zsh
# Cron/pm2-safe weekly review.  It only reads market data and sends Telegram.
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 signal_review.py --days 90 --monitor --telegram >> logs/weekly_review.log 2>&1

#!/bin/zsh
# 执行账本：Telegram 长轮询，记录用户实际成交。绝不下单、不连 IB。
set -euo pipefail
cd "$(dirname "$0")"
exec /opt/homebrew/bin/python3.11 -u execution_ledger.py >> logs/execution_ledger.log 2>&1

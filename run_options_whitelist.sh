#!/bin/zsh
# 盘中重测已路由标的的期权可交易性。只读，不下单。
# 必须在美股盘中跑——脚本自身会拒绝盘后执行（盘后价差是盘中数倍）。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 options_whitelist.py >> logs/options_whitelist.log 2>&1

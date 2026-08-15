#!/bin/zsh
# 每小时 :10（主扫描 :00 之后）：为仍在场内的新信号开期权纸面仓，
# 并对正股已出场的仓位按当前报价平仓。绝不下单、不连 IB。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 -u options_paper.py >> logs/options_paper.log 2>&1

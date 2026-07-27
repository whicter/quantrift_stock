#!/bin/zsh
# 每月1日：rejected 池四策略复检+全套验证，通过者推送候选报告（不自动接入）
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 revalidate_rejected.py --telegram >> logs/monthly_reval.log 2>&1

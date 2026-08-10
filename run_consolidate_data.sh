#!/bin/zsh
# 每周日 19:00 PT：把当周新产生的历史行情CSV（新标的、临时脚本写入的）
# 迁到外置盘，本地留符号链接。已是符号链接的文件自动跳过（幂等）。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 consolidate_data.py >> logs/consolidate_data.log 2>&1

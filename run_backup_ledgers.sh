#!/bin/zsh
# 每日 21:05 PT：把不可再生的账本镜像到 X9_Pro。
# 只备「丢了补不回来」的那 11 个文件（约 2.3 MB）；6.5 GB 历史 CSV 本来就在
# X9_Pro 上，再复制一份等于没备份——理由见 backup_ledgers.py 文件头。
set -uo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 backup_ledgers.py >> logs/backup_ledgers.log 2>&1

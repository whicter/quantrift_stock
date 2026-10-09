#!/bin/zsh
# 每小时 :25：磁盘余量 + 定时任务存活监控（只读，有问题才推 TG）
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 health_check.py >> logs/health_check.log 2>&1

#!/bin/zsh
# 每交易日 14:00 PT（17:00 ET，收盘后1小时）：IB 全池历史合并补拉
# 让本地 IB 数据（回测/回放/1d缺口填补的权威来源）始终最多落后一天。
# 期货侧现仅一个 ib-market-data-fetcher，Gateway 历史数据额度余量充足；
# fetch_ib_data 自带 6s/请求限速，约200次请求 ≈ 20-35 分钟。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 fetch_ib_data.py --merge >> logs/nightly_ib_refresh.log 2>&1

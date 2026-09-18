#!/bin/zsh
# 每交易日 14:40 PT（17:40 ET）：IB 全池历史合并补拉。避开 Gateway 14:30 自重启（IBC AutoRestartTime）
# 让本地 IB 数据（回测/回放/1d缺口填补的权威来源）始终最多落后一天。
# 期货侧现仅一个 ib-market-data-fetcher，Gateway 历史数据额度余量充足；
# fetch_ib_data 自带 12s/请求限速，约 250 次请求 ≈ 55 分钟。
set -euo pipefail
cd "$(dirname "$0")"
/opt/homebrew/bin/python3.11 fetch_ib_data.py --merge >> logs/nightly_ib_refresh.log 2>&1

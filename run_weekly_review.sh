#!/bin/zsh
# Cron/pm2-safe weekly review.  It only reads market data and sends Telegram.
#
# ⚠️ 2026-10-22：这里原来是 `set -euo pipefail` + 两条命令顺序执行。
# signal_review 从 10/11 起每轮崩在 KeyError 'High'，`set -e` 于是让**期权复盘
# 根本没机会执行**——一个 bug 吃掉了两份复盘，而 weekly_review.log 的 mtime
# 照常刷新，监控也看不出来。两条复盘互不依赖，不该共命运。
#
# 现在：各自独立执行、各自记录退出码，任一失败都推 TG（失败本身必须可见），
# 整体退出码取两者之和，pm2 日志里一眼能看出是谁挂了。
set -uo pipefail
cd "$(dirname "$0")"

_notify_fail() {   # $1=环节名 $2=日志文件
  [[ -n "${TG_TOKEN:-}" && -n "${TG_CHAT_ID:-}" ]] || return 0
  curl -sS -o /dev/null -X POST "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TG_CHAT_ID}" \
    --data-urlencode "text=⚠️ 周复盘「$1」失败，本周该部分没有结果。查：tail -40 $2" || true
}

/opt/homebrew/bin/python3.11 signal_review.py --days 90 --monitor --telegram \
  >> logs/weekly_review.log 2>&1
rc_stock=$?
[[ $rc_stock -ne 0 ]] && { echo "signal_review 退出码 $rc_stock"; _notify_fail "正股复盘" "logs/weekly_review.log"; }

# 期权纸面账本复盘。2026-09-03 之前它从上线起就没被复盘过——开了单不看结果，
# 模拟本身没有意义。只读账本，不碰仓位。**不依赖上一条的成败。**
/opt/homebrew/bin/python3.11 options_review.py --days 7 --telegram \
  >> logs/options_review.log 2>&1
rc_opt=$?
[[ $rc_opt -ne 0 ]] && { echo "options_review 退出码 $rc_opt"; _notify_fail "期权复盘" "logs/options_review.log"; }

exit $(( rc_stock + rc_opt ))

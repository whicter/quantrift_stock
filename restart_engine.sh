#!/bin/bash
# 重启告警引擎（pm2 管理）
PATH=/opt/homebrew/bin:$PATH pm2 restart stock-alert

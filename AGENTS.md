# quantrift_stock — AGENTS.md

> **语言规则**：只用中文或英文回复，绝对不能出现韩语或其他语言。

> **DO NOT send optional commentary.**

> 本项目仅发 Telegram 信号告警，**不下单**。

## 环境

| 项目 | 值 |
|---|---|
| Mac Studio hostname | `mac-studio`（用户 congrenhan） |
| 项目路径（Mac Studio） | `/Users/congrenhan/Documents/quantrift_stock` |
| 项目路径（本机） | `/Users/cohan/Documents/quantrift_stock` |
| Python（Mac Studio） | `/opt/homebrew/bin/python3.11` |
| IB Gateway 实盘端口 | 4001（只在 Mac Studio） |
| IB Gateway 模拟盘端口 | 4002 |
| clientId | **2**（期货引擎用 1，不能冲突） |
| GitHub remote | `git@github.com:whicter/quantrift_stock.git`（SSH） |

## 代码同步工作流

```bash
# 1. 把本机代码拷贝到 Mac Studio
rsync -av --exclude='.git' \
  /Users/cohan/Documents/quantrift_stock/ \
  mac-studio:/Users/congrenhan/Documents/quantrift_stock/

# 2. Mac Studio push 到 GitHub
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && git push"

# 3. 本机 pull GitHub repo
cd /Users/cohan/Documents/quantrift_stock && git pull origin master
```

## 常用命令

```bash
# 数据拉取（Mac Studio 上跑，连 IB Gateway）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py"

# 单标的单周期
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py --symbol NVDA --tf 1h"

# 补拉前审计、Gateway 恢复后的单标的验证、再合并全量历史
/opt/homebrew/bin/python3.11 data_audit.py --write
/opt/homebrew/bin/python3.11 fetch_ib_data.py --symbol NVDA --tf 1d --merge
/opt/homebrew/bin/python3.11 fetch_ib_data.py --merge
/opt/homebrew/bin/python3.11 fetch_data.py --merge  # IB HMDS 断连时的 yfinance 备用回补
/opt/homebrew/bin/python3.11 historical_backfill.py --write

# IB 不可用时用 yfinance 拉新标的数据（直接在 Mac Studio 跑）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 -c \"
import yfinance as yf, pandas as pd
from pathlib import Path
for sym in ['RKLB']:
    for tf, period, interval in [('1d','3y','1d'),('1h','60d','1h'),('4h','60d','1h')]:
        raw = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=True)
        df = raw[['Open','High','Low','Close','Volume']].rename(columns=str.lower)
        df.index.name = 'date'
        if df.index.tz: df.index = df.index.tz_convert('America/New_York').tz_localize(None)
        if tf == '4h':
            df = df.resample('4h',label='right',closed='right').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna(subset=['close'])
        df.to_csv(f'data/{sym}_{tf}.csv')
        print(f'{sym} {tf}: {len(df)} bars')
\""

# 数据同步回本机
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ /Users/cohan/Documents/quantrift_stock/data/

# 批量回测（本机跑）
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py --symbol NVDA --tf 1h

# 启动告警引擎（前台，--port 参数已不使用，保留兼容性）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 alert_engine.py"

# 查看告警引擎状态
ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 status"

# 查看日志
ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 logs stock-alert --lines 50"

# git push（必须用 -A 转发 SSH agent）
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && git push"
```

**绝对不要做：**
- 不要在本机直接连 127.0.0.1:4001/4002
- git push 必须用 `ssh -A`，否则没有 GitHub 权限
- 不要在 alert_engine.py 里加任何下单逻辑

## 策略架构

- **核心文件**：`alert_engine.py`（信号监控）、`strategy.py`（ConfluenceStrategy）、`indicators.py`（compute_signals）、`config.yaml`（参数）
- **品种**：见 `config.yaml` symbols 列表
- **周期**：1h / 4h / 1d，三周期独立信号
- **策略路由**：`STRATEGY_MAP` 按 `(symbol, tf)` 路由到 confluence / rsi2 / breakout
- **52周突破**：`BREAKOUT_PARAMS` 独立配置（NVDA/MU/MSFT/PLTR/TSLA/AAPL），仅日线
- **出场模式**：`use_staged_tp=True`，止损用 utTS，TP1/TP2 固定 ATR 倍数
- **数据源**：`fetch_bars()` 使用 **yfinance**（无 IB pacing 限制，15 分钟延时，够用）
- **clientId**：IB 连接已从 alert_engine 移除，clientId=2 仅 fetch_ib_data.py 使用

### IB 历史数据运行状态（2026-07-24 已恢复）

- **HMDS 断连已解决**：2026-07-18 发现的 `2105: HMDS data farm connection is broken: ushmds` 于 2026-07-24 04:55 通过重启 Gateway 解决。经用户明确批准后执行 `quantrift_index_future/restart_gateway.sh`（SIGKILL + launchd `com.quantrift.ibc.plist` KeepAlive 自动拉起）；重启触发 Second Factor Authentication，用户在手机 IBKR App 批准后 05:02 登录完成，4001 端口恢复监听。
- **恢复序列已跑完**：① NVDA 1d 单标的验证成功（2512行）② `fetch_ib_data.py --merge` 全量补拉 42 次请求 0 失败 ③ `data_audit.py --write` 复审：全部 `fresh`，数据来源已从 `yfinance` 切回 `ib`，覆盖至 2026-07-23 ④ `historical_backfill.py --write` 重跑：7302 候选信号，9986 条已决，2135 条影子。
- **期货 bot 未受影响**：同机 8 个 `ib-bot*` pm2 进程重连期间 PID 和重启计数均未变化，未触发 crash-restart。
- **ETF 扫描器数据已回补**：`fetch_etf_data.py` 在 Gateway 恢复后重跑，47 个 ETF + SPY/QQQ + VIX 共 50 次请求全部成功；此前停留在 2026-06-17/18 的文件均已刷新至 2026-07-23（VIX 至 07-24）。ETF 扫描结果现可视为最新。
- **历史事实保留**：`fetch_ib_data.py` 对合约解析和历史请求仍保留 45 秒超时（当时用于诊断 HMDS 断连，现继续作为常规保护）；2026-07-18 曾用 `fetch_data.py --merge` 做 yfinance 备用回补覆盖 72 个文件，该记录仅作历史参考，当前数据源已是 IB。

## 告警格式

```
📊 NVDA 1h 做多信号
  价格: $887.5  ATR: $18.2
  Bull得分: 5/6  ADX: 32.4
  TP1: $905.7  TP2: $923.9  SL(utTS): $851.2
```

## 回测工具

```bash
# 全量批跑（本机）
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py

# 单标的
.venv/bin/python backtest_runner.py --symbol NVDA

# 单标的单周期
.venv/bin/python backtest_runner.py --symbol NVDA --tf 1h

# 按不同指标排序
.venv/bin/python backtest_runner.py --sort sharpe   # 默认
.venv/bin/python backtest_runner.py --sort dd
```

## TODO

详见 `TASK.md`。

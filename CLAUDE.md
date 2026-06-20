# quantrift_stock — CLAUDE.md

> **语言规则**：只用中文或英文回复，绝对不能出现韩语或其他语言。

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

# 数据同步回本机
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ /Users/cohan/Documents/quantrift_stock/data/

# 批量回测（本机跑）
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py --symbol NVDA --tf 1h

# 启动告警引擎（前台）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 alert_engine.py --port 4002"

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
- **出场模式**：`use_staged_tp=True`，止损用 utTS，TP1/TP2 固定 ATR 倍数
- **clientId**：固定 2，不能与期货引擎（clientId=1）冲突

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

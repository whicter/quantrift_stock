# quantrift_stock — CLAUDE.md

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

### 场景 A：本机改了代码 → 推送到 Mac Studio + GitHub

```bash
# 1. 本机 → Mac Studio（排除 data/logs/.venv 等大目录）
rsync -av --exclude='.git' --exclude='data/' --exclude='logs/' --exclude='.venv/' --exclude='__pycache__/' \
  /Users/cohan/Documents/quantrift_stock/ \
  mac-studio:/Users/congrenhan/Documents/quantrift_stock/

# 2. Mac Studio commit + push（必须用 -A 转发 SSH agent）
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && \
  git add -A && \
  git commit -m 'your message' && \
  git push"
```

### 场景 B：Mac Studio 有独立改动 → 同步回本机

```bash
# 1. 先看 Mac Studio 有哪些改动
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && git status --short"

# 2. 把改动的文件同步回本机（按实际文件名替换）
rsync -av \
  mac-studio:/Users/congrenhan/Documents/quantrift_stock/文件1.py \
  mac-studio:/Users/congrenhan/Documents/quantrift_stock/文件2.py \
  /Users/cohan/Documents/quantrift_stock/

# 3. Mac Studio commit + push
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && \
  git add 文件1.py 文件2.py && \
  git commit -m 'your message' && \
  git push"
```

### 注意
- 本机**没有 GitHub SSH 权限**，所有 git push 必须通过 Mac Studio
- `git push` 必须用 `ssh -A`（SSH agent forwarding），否则报权限错误

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
- **策略路由**：`STRATEGY_MAP` 按 `(symbol, tf)` 路由到 confluence / rsi2 / breakout / mr；**未显式列出的组合不发信号**（2026-07-26 起取消默认 confluence fall-through）
- **52周突破**：`BREAKOUT_PARAMS` 独立配置（NVDA/MU/MSFT/PLTR/TSLA/AAPL + 2026-07-25 新增 DGRO/SPYM/VOO/VTI），仅日线
- **MR 均值回归**（2026-07-25 首次接入实时扫描）：`check_mr_signal()` + `MR_PARAMS`，只做多，入场 z-score≤-0.9 + RSI<40 + ADX<25 + close>200SMA，出场纯 ATR 追踪+时间止损（无固定TP）。目前仅 `TSM`(1h)/`FDVV`(1h) 接入；`mr_backtest.py` 存在多年但此前从未接入实时告警，是这次才补的缺口
- **RSI2-Trend 变体（2026-08-15）**：非独立策略，是 RSI2 + `{use_rs_filter:False, max_hold_bars:30}` 的参数覆盖，适配"长期趋势型"标的（200SMA上方≥65%、年化波动≤40%）。已接入 LLY/CSCO/ISRG/AVDV/VYM/DGRO/TSM/CRWD 的 1d。**8个标的共用同一套参数，不可逐标的调参**（泛化检验依赖于此）
- **出场模式**：`use_staged_tp=True`，止损用 utTS，TP1/TP2 固定 ATR 倍数
- **数据源（2026-07-27 起为混合架构）**：`fetch_bars()` 以 yfinance 为主（软限制，15分钟延时）；1d 近期缺 bar 用本地 IB 数据实时填补；yfinance 拉空时整段回退本地 IB 数据；本地 IB 数据由 `stock-nightly-ib-refresh`（每交易日 14:00 PT）自动 `--merge` 保鲜，最多落后一个交易日。引擎**不直连 IB**（历史教训：Error 162 crash-restart 循环）。单轮扫描拉取失败率 >20% 会发 Telegram 告警；财报日期按日缓存（省 ~90 请求/小时）。
- **完整 bar 语义（2026-07-27 起）**：信号只在**完整 bar** 上产生——盘中不再有 1d 信号（当日 bar 16:00 ET 收盘后才纳入），1h/4h 丢弃进行中的 bar；且信号仅在 bar 收盘后的新鲜窗口内发出（1h=4h/4h=12h/1d=30h），数据缺口或重启不补发陈旧信号。与回测"完整 bar 收盘决策"语义对齐。
- **clientId**：IB 连接已从 alert_engine 移除，clientId=2 仅 fetch_ib_data.py 使用

### IB 历史数据运行状态（2026-07-24 已恢复）

- **HMDS 断连已解决**：2026-07-18 发现的 `2105: HMDS data farm connection is broken: ushmds` 于 2026-07-24 04:55 通过重启 Gateway 解决。经用户明确批准后执行 `quantrift_index_future/restart_gateway.sh`（SIGKILL + launchd `com.quantrift.ibc.plist` KeepAlive 自动拉起）；重启触发 Second Factor Authentication，用户在手机 IBKR App 批准后 05:02 登录完成，4001 端口恢复监听。
- **恢复序列已跑完**：① NVDA 1d 单标的验证成功（2512行）② `fetch_ib_data.py --merge` 全量补拉 42 次请求 0 失败 ③ `data_audit.py --write` 复审：全部 `fresh`，数据来源已从 `yfinance` 切回 `ib`，覆盖至 2026-07-23 ④ `historical_backfill.py --write` 重跑：7302 候选信号，9986 条已决，2135 条影子。
- **期货 bot 未受影响**：同机 8 个 `ib-bot*` pm2 进程重连期间 PID 和重启计数均未变化，未触发 crash-restart。
- **ETF 扫描器数据已回补**：`fetch_etf_data.py` 在 Gateway 恢复后重跑，47 个 ETF + SPY/QQQ + VIX 共 50 次请求全部成功；此前停留在 2026-06-17/18 的文件均已刷新至 2026-07-23（VIX 至 07-24）。ETF 扫描结果现可视为最新。
- **历史事实保留**：`fetch_ib_data.py` 对合约解析和历史请求仍保留 45 秒超时（当时用于诊断 HMDS 断连，现继续作为常规保护）；2026-07-18 曾用 `fetch_data.py --merge` 做 yfinance 备用回补覆盖 72 个文件，该记录仅作历史参考，当前数据源已是 IB。

## 后台任务（pm2，均已 pm2 save）

| 任务 | 时间 | 作用 |
|---|---|---|
| `stock-alert` | 常驻，每小时 | 主告警引擎（108标的/130条路由） |
| `stock-exec-ledger` | 常驻长轮询 | 执行账本，接收「接 NVDA 176.5」记录真实成交（**绝不下单**） |
| `stock-nightly-ib-refresh` | 交易日 14:00 PT | IB 全池 `--merge` 保鲜本地数据 |
| `stock-daily-screener` | 交易日 13:20 PT | 因子选股 Top15 → TG |
| `stock-watchlist-events-am` | 交易日 07:45 PT | 事件雷达·盘中 → TG |
| `stock-watchlist-events` | 交易日 13:35 PT | 事件雷达·收盘 → TG |
| `stock-weekly-review` | 周日 18:15 PT | 90天复盘+衰减监控 → TG |
| `stock-weekly-data-consolidate` | 周日 19:00 PT | 历史CSV迁外置盘留符号链接 |
| `stock-monthly-reval` | 每月1日 06:00 PT | rejected 池复检 |

## 信号投递与降级（2026-08-15 起）

- **按板块合并推送**：本轮信号先入队，扫描结束按板块合并，每板块一条消息；
  同板块多条时附「⚠️ 同板块集中：做多N/做空M」——相关性集中度分开发时看不见。
  **不做任何过滤，全部信号照发**。
- **降级路由**：`logs/demoted_routes.json` 里的组合仍计算并记入 signal_log，
  但不推送。由 `decay_action.py`（连续红灯 → 自动重验证 → 双挂才降级）写入，
  **是数据不是代码**——无人值守任务不改 `STRATEGY_MAP` 源码。

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

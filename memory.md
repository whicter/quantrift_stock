# quantrift_stock — 项目级 Memory

> 此文件仅供 Claude Code 在本项目会话中参考，内容从全局 MEMORY.md 提取。

## 项目规则

- **绝对不能输出模棱两可的猜测**（如"可能是IBKR限制"、"或许是维护窗口"）。只说能从日志/代码中证明的事实。不能证明的原因就说"原因未知，需要查日志"。
- **干跑（--dry-run）绝对不能用 clientId 20**（主bot用20，会踢掉主bot）。
- **Bash 直接跑，不问确认**：本项目所有 Bash 命令直接执行，不要问"要不要执行"。
- **参数改动必须先问用户确认**，不能自己决定（如冷却时间、阈值等）。

## SSH / 同步规则

- **本机无 GitHub SSH 权限**：所有 `git push` 必须通过 Mac Studio，用 `ssh -A mac-studio "..."`。
- **远程命令**：用 `ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && ..."` 执行。
- **代码同步**：本机 → Mac Studio 用 rsync（见 CLAUDE.md 场景A）；Mac Studio → 本机用 rsync（场景B）。
- **不要**在本机直接连 127.0.0.1:4001/4002。
- **不要**在 `alert_engine.py` 里加任何下单逻辑（本项目仅发 Telegram 信号）。

## 数据源架构

- **alert_engine.py** 数据源已切换至 **yfinance**（无 IB pacing 限制，15分钟延时，够用）。
  - `fetch_bars()` 内部使用 `yf.Ticker(symbol).history(period, interval)`。
  - 4h 周期：fetch 1h 数据后 `resample("4h", label="right", closed="right")` 聚合。
  - `ib` 参数保留签名兼容性，实际传 `None`。
- **IB pacing 风险**：Error 162 → crash-restart 无限循环教训。`alert_engine.py` 已彻底不连 IB。
  - `clientId=2` 仅 `fetch_ib_data.py` 使用。
- **df_1d_cache**：主循环中按 `(symbol, "1d")` 缓存 DataFrame，breakout 扫描复用，避免重复 fetch。
  - DataFrame bool 判断要用 `_cached if _cached is not None else fetch_bars(...)`，不能用 `or`（ValueError）。

## 策略速查

| 文件 | 用途 |
|------|------|
| `alert_engine.py` | 主告警引擎，每小时扫描，yfinance 数据 |
| `strategy.py` | ConfluenceStrategy |
| `indicators.py` | compute_signals, _atr, _sma |
| `config.yaml` | 参数、symbols 分组、STRATEGY_MAP 路由 |
| `backtest_runner.py` | Confluence/RSI2 批量回测（本机跑） |
| `breakout_backtest.py` | 52W高点突破策略回测 |
| `etf_scanner.py` | ETF板块轮动扫描，45 ETF |
| `screener.py` | 多指数周频因子选股（NDX100/SP500等） |
| `mag7_rotation.py` | MAG7 周频相对强弱轮动 |
| `signal_review.py` | 信号复盘（读 logs/signal_log.csv） |

## BREAKOUT_PARAMS（当前接入实盘的标的）

| 标的 | confirm | trail× | sl× | hold | vol | Sharpe |
|------|---------|--------|-----|------|-----|--------|
| NVDA | 1 | 3.0 | 1.5 | 20 | 否 | 0.761 |
| MU   | 1 | 3.0 | 1.5 | 20 | 是 | 0.843 |
| MSFT | 1 | 2.5 | 1.5 | 20 | 否 | 0.628 |
| PLTR | 1 | 2.5 | 1.5 | 20 | 否 | 0.825 |
| TSLA | 1 | 2.5 | 1.5 | 10 | 否 | 0.935 |
| AAPL | 2 | 2.0 | 1.5 | 20 | 是 | 1.161（9笔，样本少） |

## pending_high_vol 观察标的

| 标的 | 结论 |
|------|------|
| RKLB | 突破 Sharpe 0.934（13笔），继续观察至 2026 年底 |
| NBIS | 数据仅 1.7 年，全策略不达标，维持 pending |
| IREN | 1h Confluence 1.09 但仅 11 笔，不稳定，维持 pending |

## 告警引擎部署

- **pm2 进程名**：`stock-alert`
- **查看状态**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 status"`
- **查看日志**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 logs stock-alert --lines 50"`
- **重启**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 restart stock-alert"`
- **实盘验证**：2026-06-21 STX 4h + 1d 做多信号触发并推送 Telegram ✅

## Session UUID

`9b2abbce-01cb-462e-935d-2d2a763bc932`
恢复：`cd ~/Documents/quantrift_stock && cr`

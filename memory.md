# quantrift_stock — 项目级 Memory

> 此文件仅供 Claude Code 在本项目会话中参考，内容从全局 MEMORY.md 提取。

## 项目规则

- **绝对不能输出模棱两可的猜测**（如"可能是IBKR限制"、"或许是维护窗口"）。只说能从日志/代码中证明的事实。不能证明的原因就说"原因未知，需要查日志"。
- **干跑（--dry-run）绝对不能用 clientId 20**（主bot用20，会踢掉主bot）。
- **Bash 直接跑，不问确认**：本项目所有 Bash 命令直接执行，不要问"要不要执行"。
- **参数改动必须先问用户确认**，不能自己决定（如冷却时间、阈值等）。
- **DO NOT send optional commentary.**

## Codex 仓库工作规则

- **分阶段工作**：仓库工作必须明确拆分为 Review / Design / Implementation / Verification / Deployment readiness。用户只要求 review 时，不改文件、不提交、不格式化、不更新文档、不顺手重构、不直接进入实现。用户只要求 design 时，只说明行为、影响文件、状态变化、失败处理、测试计划和回滚计划，不实现。用户要求 implement 时，只改已批准范围。
- **不能声称全仓库覆盖，除非有证据**：不要说"我看完了所有代码"或"整个仓库都检查了"。需要给可验证覆盖报告：已读文件、部分读取文件、未读文件、入口文件、引擎文件、共享库、配置、状态管理、运维脚本、测试、作为事实来源的文档；每个相关文件标记 fully reviewed / partially reviewed / located but not reviewed / not found / excluded with reason。
- **每个发现必须有证据**：代码审查发现需包含 Severity(P0-P3)、Confidence、文件、函数/类、代码路径、触发条件、当前行为、期望行为、最坏后果、代码证据、建议修复、是否改变交易/业务行为、必需测试。发现要分为 confirmed bugs / likely bugs / design risks / operational risks / documentation inconsistencies。架构偏好不能写成确认 bug。
- **事实和假设必须分开**：明确标注 confirmed from code / confirmed from tests / confirmed from runtime output / inferred from surrounding logic / assumed because evidence is unavailable。代码、文档、配置冲突时，报告冲突并说明当前哪个来源实际生效。
- **最小改动范围**：优先最小正确改动。不要重构无关代码、改无关命名、整文件格式化、升级依赖、改公共接口。任何 instrument、position size、entry/exit、SL/TP、交易时间、bar 构造、策略参数、reconciliation 行为变化，都必须明确标为 strategy behavior change，并先获批准。
- **实现前先说明范围**：实现前列出要改文件、要改函数、预计行数范围、新状态字段、接口变化、运行时行为变化、测试覆盖、回滚方法。小修如果变成大 diff，必须停下说明原因。
- **提交粒度**：一个 commit 只包含一个可独立测试和回滚的风险/修复。不要把无关改动混在一起。不要提交运行状态文件、秘密、生成文件、备份、本地环境文件或无关既有改动。
- **验证不能只靠编译**：`py_compile` 只代表语法通过，不代表运行正确。根据改动选择 unit test、regression test、deterministic replay、backtest comparison、dry-run、paper test、断连/重启/缺 bar/重复回调/陈旧数据等模拟。必须区分 syntax verified / unit tested / integration tested / dry-run tested / paper-account tested / production tested。
- **测试/回测证据必须可复现**：报告 exact command、git commit、配置、数据源、数据日期范围、相关环境变量、初始资金、佣金/滑点、仓位大小、交易笔数、PnL、Sharpe、MaxDD、测试结果、前后对比。不可复现结果只能标为 preliminary。
- **生产系统 fail closed**：无法确认数据新鲜度、bar 完整性、合约身份、持仓归属、open-order 归属、状态一致性、保护单存在、市场 session 有效性时，不开新风险。默认动作：暂停新入场、保留现有保护、告警、记录具体不一致、要求确定性恢复。
- **完成标准必须明确**：任务完成只在 requested scope 已实现、无关文件未改、必需测试通过、失败/跳过测试已披露、运行时行为变化已总结、剩余风险已列出、回滚方式已提供后成立。达到完成标准后停止，不继续优化。
- **生产相关改动要可追踪**：提供 finding ID、commit ID、改动文件、执行测试、测试输出、已知限制、部署前提、回滚 commit/命令。审查者要能追踪 finding → design → implementation → verification → deployment decision。
- **交易系统专项检查**：自动交易代码必须关注数据新鲜度/完整性、时区和 session、完成 bar vs 未完成 bar、历史/实时连续性、contract month/localSymbol/conId/clientId/orderRef/orderId/permId、parent-child、OCA、partial fills、重复回调、断连重连、Gateway/bot 重启、持仓归属、shared-contract 冲突、状态对账、孤儿订单、无保护持仓、残余 spread legs、重复入场、陈旧信号、fail-safe alerts。

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
- **IB 历史数据健康状态（2026-07-18）**：API 会话、`reqCurrentTime()` 和 NVDA 合约解析成功；Gateway 返回 `2105: HMDS data farm connection is broken: ushmds`，NVDA 5 日历史请求在 15 秒诊断超时。已证实为 US HMDS 断连，不能猜测为 pacing、clientId 或合约问题。`fetch_ib_data.py` 使用 45 秒请求上限；下一项待验证恢复动作是重启 Gateway，再用单标的历史请求验证。Gateway 同时服务期货 bot，重启属于运维操作，不能擅自执行。
- **yfinance 备用回补（2026-07-18）**：`fetch_data.py` 已修复为当前 symbols 分组，支持 `--merge`、原子写入、`data/.data_sources.json` 来源清单和 20 秒请求上限。全量运行后 72 个 `symbol × tf` 文件均为 fresh、末端 2026-07-17、来源 yfinance；随后历史回填已重跑。
- **ETF 扫描器数据缺口（2026-07-18）**：其 47 个 ETF/基准日线不属于 `fetch_data.py` 的 24 标的池。`SMH`、`SOXX`、`SPY`、`QQQ` 已至 2026-07-17，`QTUM`/`UFO` 至 2026-07-01，其余 41 个停在 2026-06-18；共 43 个待回补。未更新前不得根据 ETF 扫描器输出做新的轮动结论。
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

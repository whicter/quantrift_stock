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

## 数据源架构（2026-07-27 起为混合模式）

- **实时扫描主源 yfinance**：软限制（非官方接口，偶发瞬时拉空/整根缺bar），每小时约 200-270 请求（财报按日缓存后）。失败率 >20%/轮会发 Telegram 告警。
- **本地 IB 数据 = data/*.csv 磁盘快照**：由 `stock-nightly-ib-refresh`（每交易日 14:00 PT）自动 `fetch_ib_data --merge` 保鲜（108标的），最多落后一个交易日。它是回测/回放/期望表的权威数据源。
- **两级兜底**：1d 近期缺 bar 用本地 IB 实时填补（仅近10天窗口，防复权基准错位）；yfinance 整体拉空时整段回退本地 IB（整段替换不拼接，避免 IB 整点锚 vs yf 半点锚混网格）。
- **引擎绝不直连 IB**：IB 历史接口 60请求/10分钟（Gateway 全局），每小时扫描需求超其 5 倍；直连曾致 Error 162 → crash-restart 死循环。yfinance 大面积失败时直连兜底会瞬间打爆配额——所以兜底必须走本地存储。
- **完整 bar 语义**：信号只在完整 bar 上产生（1d 收盘后、1h/4h 丢进行中bar），且仅在新鲜窗口内发出（1h=4h/4h=12h/1d=30h）。2026-07-27 曾因半根bar缺陷在早盘急跌时发出一串 1d 做多（已作废）。
- **共享文件写入必须合并语义**：`fetch_etf_data` 曾用覆盖写截断 QQQ/SPY/SMH/SOXX 十年历史（已改merge）；追加式 CSV 必须校验 schema（screener_results.csv 曾混入双 schema 致解析静默失败）。
- **df_1d_cache**：主循环中按 `(symbol, "1d")` 缓存 DataFrame，breakout 扫描复用，避免重复 fetch。
  - DataFrame bool 判断要用 `_cached if _cached is not None else fetch_bars(...)`，不能用 `or`（ValueError）。

## pm2 任务清单（quantrift_stock，均已 pm2 save）

| 任务 | 时间 | 作用 |
|---|---|---|
| `stock-alert` | 常驻，每小时扫描 | 主告警引擎（103+标的） |
| `stock-nightly-ib-refresh` | 交易日 14:00 PT | IB 全池 `--merge` 保鲜本地数据 |
| `stock-daily-screener` | 交易日 13:20 PT | watchlist 全池因子选股 Top15 → TG |
| `stock-watchlist-events` | 交易日 13:35 PT | 事件雷达·收盘（52W突破/放量新高/异动）→ TG |
| `stock-watchlist-events-am` | 交易日 07:45 PT | 事件雷达·盘中（开盘75分钟后，量比按已过时段折算）→ TG |
| `stock-weekly-review` | 周日 18:15 PT | 90天复盘+衰减监控 → TG |
| `stock-monthly-reval` | 每月1日 06:00 PT | rejected 池复检，候选报告（不自动接入） |

## 策略速查

| 文件 | 用途 |
|------|------|
| `alert_engine.py` | 主告警引擎，每小时扫描，混合数据源（见上） |
| `strategy.py` | ConfluenceStrategy |
| `indicators.py` | compute_signals, _atr, _sma |
| `config.yaml` | 参数、symbols 分组、STRATEGY_MAP 路由 |
| `backtest_runner.py` | Confluence/RSI2 批量回测（本机跑） |
| `breakout_backtest.py` | 52W高点突破策略回测 |
| `etf_scanner.py` | ETF板块轮动扫描，45 ETF |
| `screener.py` | 多指数周频因子选股（NDX100/SP500等） |
| `mag7_rotation.py` | MAG7 周频相对强弱轮动 |
| `signal_review.py` | 信号复盘（读 logs/signal_log.csv） |
| `mr_backtest.py`/`mr_signals.py`/`mr_strategy.py` | MR均值回归回测；2026-07-25 起 `alert_engine.py` 的 `check_mr_signal()` 也直接实现同一入场规则用于实时扫描 |

## BREAKOUT_PARAMS（当前接入实盘的标的）

| 标的 | confirm | trail× | sl× | hold | vol | Sharpe |
|------|---------|--------|-----|------|-----|--------|
| NVDA | 1 | 3.0 | 1.5 | 20 | 否 | 0.761 |
| MU   | 1 | 3.0 | 1.5 | 20 | 是 | 0.843 |
| MSFT | 1 | 2.5 | 1.5 | 20 | 否 | 0.628 |
| PLTR | 1 | 2.5 | 1.5 | 20 | 否 | 0.825 |
| TSLA | 1 | 2.5 | 1.5 | 10 | 否 | 0.935 |
| AAPL | 2 | 2.0 | 1.5 | 20 | 是 | 1.161（9笔，样本少） |
| DGRO/SPYM/VOO/VTI | 1 | 2.5 | 1.5 | 20 | 否 | 0.66/0.64/0.61/0.63（2026-07-25 watchlist批量新增，默认参数未调优） |

## MR_PARAMS（2026-07-25 首次接入实时扫描）

| 标的 | bb_mult | rsi_os | adx_max | atr_sl× | atr_trail× | hold | Sharpe |
|------|---------|--------|---------|---------|-----------|------|--------|
| TSM  | 2.0 | 40 | 25 | 2.0 | 2.5 | 48 | 1.281（N=31，勉强过30笔门槛） |
| FDVV | 2.0 | 40 | 25 | 2.0 | 2.5 | 48 | 0.619（N=38） |
| MKSI | 2.0 | 40 | 25 | 2.0 | 2.5 | 48 | 0.623（N=31，2026-07-25 网格批次接入） |

## pending_high_vol 观察标的

| 标的 | 结论 |
|------|------|
| RKLB | 突破 Sharpe 0.934（13笔），继续观察至 2026 年底；1d/4h 已由 watchlist 批次接入（Confluence 1d 1.06 / RSI2 4h 0.91） |
| NBIS | 数据仅 1.7 年，全策略不达标，维持 pending |
| SHOP | 2026-07-27 用户因当日+12.4%暴拉要求加入。四策略×三周期全测：Confluence/RSI2/Breakout fail；MR 1h 10bps=0.93 但 N=22<30，samples不足暂不接入，仅在 watchlist universe 内（daily screener + 事件雷达覆盖） |
| ~~IREN~~ | **2026-07-26 已升级接入**：数据刷新后 1h Confluence N=230 Sharpe 1.15，30bps 仍 0.72，wf 训练0.73→测试1.76 |

## 告警引擎部署

- **pm2 进程名**：`stock-alert`
- **查看状态**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 status"`
- **查看日志**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 logs stock-alert --lines 50"`
- **重启**：`ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 restart stock-alert"`
- **实盘验证**：2026-06-21 STX 4h + 1d 做多信号触发并推送 Telegram ✅

## Session UUID

`9b2abbce-01cb-462e-935d-2d2a763bc932`
恢复：`cd ~/Documents/quantrift_stock && cr`

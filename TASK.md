# TASK.md — quantrift_stock

## 进行中

无

## 已完成（最近）

### M — 用户 watchlist 批量接入（2026-07-25）

**背景**：用户提供两版 watchlist.txt（205 -> 175(清洗后) 个代码），要求判断有效性并接入 alert_engine。

- [x] **第一版 watchlist（205个代码）根源排查**：核实其中大量无法识别代码（ACAC/AIRJ/BATL等）来自用户提供的 `adanos.org` Reddit热度榜单页面——该页面每个 ticker 前有取代码前1-2位字母的徽标图标，抓取时徽标与完整代码断开会残留半截代码（如 `FX FXAIX` 只剩 `FX`，`MQ MQG` 只剩 `MQ`）。该榜单每小时刷新，无法逐个精确复原，改用真实数据拉取结果做最终判断。
- [x] **第二版 watchlist（195个代码）美股交易所核实**：`yfinance fast_info` 查交易所/币种，对无法直接解析的代码额外用常见外国后缀（.SW/.AX/.TO/.L/.DE等）反查真实上市地。确认 21 个非美股代码并从 `watchlist.txt` 移除：`ABBN`(瑞士ABBN.SW) `AVG`(澳洲) `CBE`(澳洲) `CESG`(伦敦) `CVD`(加拿大) `DHHF`(澳洲) `HHIS`(加拿大) `HULC`(加拿大) `MSTE`(加拿大) `MQG`(澳洲，麦格理) `PRL`(加拿大) `TTM`(澳洲) `VDHG`(澳洲) `VEQT`(加拿大) `VOW`(德国，大众) `VWRA`(瑞士) `XEQT`(加拿大) `DLA HFC INVEST KPL`(任何后缀均无法解析)。`BRK` 修正为 `BRK-B`（纽交所真实代码）。
- [x] **数据拉取 + 三策略批量回测**：清洗后 175 个代码中 156 个是系统外的全新标的（另加用户指定的 RBLX，共157个）。yfinance 批量拉取 1d/1h/4h（153/144 成功，少数因近期上市/退市数据不足），对每个 `(symbol,tf)` 跑 Confluence + RSI2（默认参数）+ Breakout（仅1d，默认参数）三套回测，取每组合最优 Sharpe。
- [x] **结果过滤与晋升门槛**：Sharpe≥0.6 且 N≥30 共 54 条 `(symbol,tf)` 组合，剔除退化结果（`XHLF` breakout Sharpe 2.4 但 WR=100%/RR=0，货币基金近零波动率导致 ATR 止盈止损逻辑失效的伪信号）、货币基金/短债ETF（`SGOV`）、杠杆反向ETF（`SOXS`/`SPXU` 达标但不自动接入，风险特征未验证）。最终 **30 个标的、35 个 (symbol,tf) 组合**通过筛选。
- [x] **接入 alert_engine.py**：`config.yaml` 新增 `watchlist_2026_07` 标的组（30个），`alert_engine.py` 的 `ALL_SYMBOLS`、`STRATEGY_MAP`（+31条）、`RSI2_PARAMS`（+17条）、`BREAKOUT_PARAMS`（+4条：DGRO/SPYM/VOO/VTI）全部更新。完整 import 验证：`ALL_SYMBOLS` 17→47，`STRATEGY_MAP` 37→68，`RSI2_PARAMS` 22→39，`BREAKOUT_PARAMS` 6→10，数量吻合，无 key 覆盖问题。
- [ ] **参数尚未逐个网格优化**：本批全部使用默认参数（RSI2: entry=10/atr_trail=2.0(1h)or2.5(4h,1d)/score=2；Breakout: confirm=1/trail=2.5/sl=1.5/hold=20），后续可用 `rsi2_backtest.py --symbol X --optimize` / `breakout_backtest.py --optimize` 逐个精调。
- [ ] **成本压力测试/Walk-Forward 验证未做**：这批标的直接用单一样本回测 Sharpe 门槛接入，未经过现有主池标的都做过的 0-30bps 成本压力测试和训练/测试分段验证（见 LEARNING.md「上线验证结论」），建议观察 1-2 个月实盘信号质量后再补做。
- [ ] **杠杆/反向ETF专项评估**：`SOXS`(1h Confluence Sharpe 1.19) `SPXU`(1h/1d Confluence Sharpe 1.22/0.60) 达标但因杠杆衰减特性从未验证，暂不接入，留待专项研究决定是否需要独立参数体系。
- [x] **补跑用户追问标的（2026-07-25）**：用户核对系统是否包含 `INTC/META/HOOD/EU/XYZ/COIN/IBM/DELL` 八个代码。核实结果：`INTC`(watch组已在跑)/`META`(mega_cap已在跑)/`IBM`(本轮已接入)三个已在系统；`DELL` 在 `watch_candidates`（未接入ALL_SYMBOLS，未实际扫描）；`HOOD/EU/XYZ/COIN` 完全不在系统。对 `HOOD/EU/XYZ/COIN/DELL` 五个补跑三策略回测：**`DELL`(1h Confluence Sharpe 0.83 N=70；4h RSI2 Sharpe 0.853 N=38) 和 `HOOD`(1h RSI2 Sharpe 1.108 N=142；4h RSI2 Sharpe 0.644 N=51) 达标接入** `watchlist_2026_07`（DELL 同时从 `watch_candidates` 移除，避免重复归属）；`COIN`(三周期 Sharpe 0.03~0.28，全部不达标)、`EU`(即 enCore Energy，NASDAQ小盘铀矿股，三周期 Sharpe -0.55~0.13，不达标)、`XYZ`(Block Inc，三周期 Sharpe -1.02~0.56，不达标) 均未接入。`import` 验证：`ALL_SYMBOLS` 47→49，`STRATEGY_MAP` 68→72，`RSI2_PARAMS` 39→42，数量吻合。
- [x] **`watchlist.txt` 文件本身同步更新**：此前只更新了 `config.yaml`/`alert_engine.py`（系统内部配置），未回写用户提供的原始 `watchlist.txt` 文件本身。补充把 `HOOD`/`EU`/`COIN`/`DELL` 四个写回文件（`XYZ` 已在文件中），文件从 176 行增至 180 行。
- [x] **`watchlist.txt` 180 个代码完整性核对**：与本轮所有回测/系统记录交叉核对，176 个已处理（含系统原有、已接入、已测试未达标三类），**3 个遗漏未处理**：`BSP`(Bending Spoons，意大利科技股) `RAM`(Roundhill DRAM 2倍杠杆ETF) `SPCX`(Space Exploration Technologies Corp 关联标的)——核查后确认是真实美股代码（yfinance fast_info 交易所=NMS/BTS，币种USD），但均为近1个月内新上市，1d 数据仅 16-28 行，无法产生有意义的回测样本（低于 RSI2 的 MIN_TRADES=15 门槛），比照 `pending_high_vol`（RKLB/NBIS/IREN）先例列为"数据不足，暂缓"，不强行跑批量回测凑数字。
- [x] **MR（均值回归）策略补测未达标标的**：对本轮所有未达标的 126 个候选标的（排除已知货币基金/杠杆ETF 19个后共107个）跑 `mr_backtest.py` 默认参数回测，覆盖 1h/4h/1d。结果：**仅 2 个达标**——`TSM` 1h Sharpe 1.281 N=31（勉强过 N≥30 门槛）、`FDVV` 1h Sharpe 0.619 N=38；其余 105 个（含用户关心的 `COIN` 1h Sharpe -0.618、`EU` 1h Sharpe -0.621）在 MR 框架下依然不达标，甚至比 Confluence/RSI2 更差。**发现架构缺口**：`mr_signals.py`/`mr_backtest.py` 从未接入 `alert_engine.py` 实时扫描——`STRATEGY_MAP` 分发逻辑只识别 `confluence`/`rsi2`/`breakout`，没有 `check_mr_signal()` 函数。
- [x] **MR 实时接入（用户明确要求补建）**：新增 `check_mr_signal()`（对齐 `mr_strategy.py` 入场逻辑：z-score≤-0.9 + RSI<rsi_os + ADX<adx_max + close>trendSMA，只做多，无 TP，SL=初始ATR种子后续转追踪）+ `build_mr_alert()` 消息格式 + `MR_PARAMS` 参数表 + `STRATEGY_MAP` 分发新增 `"mr"` 分支，`TSM`(1h)/`FDVV`(1h) 接入 `watchlist_2026_07`。**同时修复关联的复盘缺口**：`review_core.py` 的 `evaluate()` 此前只区分 `rsi2` 和"其余全按 Confluence 处理（需要 tp1/tp2）"，MR 只有 SL 没有 TP，会被错误复盘；新增 `eval_mr()`（纯 ATR 追踪出场+时间止损，不含 RSI2 的半仓/RSI出场逻辑）并接入分发。**修复过程中发现并纠正一个子串匹配 bug**：最初用 `"mr" in strategy` 判断会误伤 `MRVL_WideExit`（小写后 `mrvl_wideexit` 恰好包含"mr"子串），改为精确匹配 `strategy == "mr" or strategy.startswith("mr_")`。`paper_portfolio.py`/`alert_engine.py` 的 `SEMIS`/`SEMI_SYMBOLS` 集合补充 `TSM`（真实半导体股，此前遗漏，现可正确触发 SOXX 弱势警告）。验证：全历史扫描 `check_mr_signal` 在 TSM/FDVV 1h 上分别触发 67/83 次入场条件（对应回测 N=31/38 笔交易，量级合理）；`test_review_core.py` 新增 2 个测试（ATR追踪出场数值验证 + MRVL_WideExit 误路由回归测试），12 个测试全部通过；`import` 验证 `ALL_SYMBOLS` 49→51，`STRATEGY_MAP` 72→74。
- [x] **`watchlist.txt` 收进仓库版本控制 + 建立持久化处理记录**：用户反复手动粘贴全量代码列表（最终扩充到293个）维护成本高，且此前已发生过 config.yaml 与外部 txt 文件（`/Users/congrenhan/Downloads/watchlist.txt`）drift 的问题。新增两个 git 跟踪文件：`watchlist.txt`（项目根目录，用户可直接编辑代替每次粘贴全量）+ `watchlist_history.csv`（每个代码的处理状态：promoted/rejected/non_us_or_invalid/insufficient_data/duplicate_format等，含策略/周期/Sharpe/N/日期/备注），替代此前依赖 `/tmp` 临时文件重建"已处理集合"的脆弱做法（`/tmp` 文件不会跨会话保留）。`logs/*.csv` 在 `.gitignore` 中被排除，故该记录文件放在项目根目录而非 `logs/`。
- [x] **第四版 watchlist（用户扩充至293个代码）批量回测**：与 `watchlist_history.csv` 交叉核对，293 个中 90 个此前从未处理（`BRK.B` 为已处理 `BRK-B` 的格式重复，实际 89 个全新）。数据拉取：82/89 有 1d 数据（`ACAC/FX/LTV/OS/RE/SMS/TITI` 7 个再次确认无数据，与第一版列表的判断吻合，进一步印证是网页抓取残片而非真实代码），77/82 有完整 1h/4h（`ETHU/IBIT`加密货币ETF + `GEV/LSL/RR`次新股仅1d数据，标记数据不足）。四策略（Confluence/RSI2/Breakout/**MR**，MR 首次纳入标准批量流程）回测后 Sharpe≥0.6 且 N≥30 共 25 组合。**`SMR` 1h RSI2 Sharpe 0.686 但最大回撤达 -95.12%（小盘核能股结构性暴涨暴跌），判定风险过高单独排除，不接入**——不能只看 Sharpe 门槛，极端回撤本身就是拒绝理由。最终 **21 个标的、24 个 (symbol,tf) 组合接入**（8 Confluence / 15 RSI2 / 1 MR：`MKSI` 1h）。`GOOG` 达标（4h RSI2 Sharpe 0.875）但标注为与已有 `GOOGL`（mega_cap组）走势高度相关的重复板块敞口，予以保留但需注意。`import` 验证：`ALL_SYMBOLS` 51→72，`STRATEGY_MAP` 74→98，`RSI2_PARAMS` 42→57，`MR_PARAMS` 2→3，数量吻合；12 个测试全部通过。
- [x] **四策略覆盖完整性核查（用户追问"都跑过全部策略回测了吗"）**：交叉核对 `watchlist_2026_07` 全部 55 个标的的历史回测记录，发现 **35 个标的从未测试过 MR**——第二/三版批次跑的时候 MR 还没接入实时系统，之后的 MR 补测又只针对"三策略全不达标"的标的，已用 Confluence/RSI2/Breakout 达标接入的就没有回头测 MR，这是真实覆盖缺口。另确认 12 个"缺 Breakout"的标的（AIS/CRCL/CRWV/DJT/GME/LUNR/MSOS/RBLX/USAR/CBUS/ONDS/OSCR）**不是漏测**，重跑验证是正常返回 `None`（信号笔数低于 `MIN_TRADES=8`门槛），Breakout 覆盖实际完整。补测 35 个标的的 MR：28 组合有有效结果，**0 组合达到 Sharpe≥0.6 且 N≥30**（最高 `RBLX` 1h Sharpe 0.651 但 N=19 不足），确认现有 Confluence/RSI2 选择仍是这些标的的最优策略，无需变更。结果已写入 `watchlist_history.csv`，四策略覆盖现已完整。
- [x] **184 个"任何策略都不达标"标的的新方案研究**：交叉 `watchlist_history.csv` 全部记录，找出跨四轮回测、四套策略均未晋升的 184 个标的，分类：杠杆/反向ETF 8个（结构性不适合）、货币基金/短债 11个（近零波动，ATR框架失效）、宽基/被动配置ETF 34个、个股/其他 131个（其中 60 个默认参数 Sharpe 已达 0.35-0.6，值得网格优化）。
  - **网格优化（60个"接近达标"个股）**：复用 `rsi2_backtest.py` GRID（324组合）+ `backtest_runner.py` OPTIMIZE_GRID（60组合）对每个标的×周期跑满，共约7万次回测（后台约50分钟）。**42 个 (symbol,tf) 组合达标**（16 Confluence / 26 RSI2），`SLS` 1h RSI2 最大回撤 -56.9% 风险过高排除（改用其 Confluence 1h 结果接入）。最终 **36 个标的**接入 `watchlist_2026_07`：`AAOI AIRJ ALL AMC APLD APO BA BBW CCJ CRSP DUOL FOF FWRG GFS GL HBM KO LLY MO MSTR NFLX PB QCOM RBC RGTI SAP SKM SLS SMCI SNAP SPXC STLA TMC UP USO VC`。⚠️ 其中 `RGTI`(1h DD-42.4%)/`AIRJ`(1h DD-35.6%)/`CCJ`(1h DD-30.2%)/`MSTR`(1h DD-29.0%)/`UP`(1h DD-31.3%) 等多个 RSI2 组合最大回撤明显高于原主池标的（原主池多在 5-20% 区间），已在代码注释标注"需关注"，接入后需观察实盘信号质量，必要时收紧 `atr_sl_mult`。`import` 验证：`ALL_SYMBOLS` 72→108，`STRATEGY_MAP` 98→140，`RSI2_PARAMS` 57→83，`watchlist_2026_07` 55→91，数量吻合；12 个测试全部通过。
  - **相对强弱轮动方案（34个宽基/被动配置ETF）探索，结论：不推荐接入**：复用 `mag7_rotation.py` 已验证的方法论（`run_rotation()` 新增 `symbols` 参数支持任意标的池），新建 `etf_rotation_backtest.py` 对这批 ETF 跑轮动扫描。结果：无 risk-off 过滤时最优 Sharpe 0.856（top_n=4, rs=60d）但最大回撤 -57.7%，**比等权持有基准的 -41.1% 回撤还差**；加 risk-off 过滤后回撤收窄到 -15%~-37%，但 Sharpe 跌到 0.475 以下。结论：这批 ETF 构成过于混杂（宽基指数+小盘因子+期权收益型+成长风格混在一起），相对强弱排名找不到干净边际，与 MAG7 轮动（Sharpe 1.066，同方法论）完全不可比。**不建议接入实盘**，代码保留供后续按更同质子分组重新设计。
  - **货币基金/短债(11)、杠杆反向ETF(8) 明确不追加新方案**：结构性不适配现有及探索过的所有策略类型（绝对水平择时和相对强弱轮动都需要标的本身有足够波动率/趋势可辨识），继续排除。
- [x] **`SPCX`/`SPXC` 用户核实两者未混淆**：确认 `watchlist_history.csv` 中 `SPCX`（Space Exploration Technologies Corp，SpaceX关联，数据不足暂缓）与 `SPXC`（SPX Technologies，工业设备商，网格优化救回接入）是两条独立记录，代码里也只接入了 `SPXC`，未误接 `SPCX`。
- [x] **`SPCX` 应用户明确要求接入实盘扫描（未经回测验证的特例）**：确认数据仍仅28行1d（6/12上市），任何策略都无法产生有意义回测。告知用户"若不指定策略，Confluence 默认门槛(50根1h K线)会被 SPCX 的201根1h数据满足，将立即产生未经验证的实盘信号"，用户明确选择现在接入。加入 `watchlist_2026_07`，未在 `STRATEGY_MAP` 显式指定策略（走默认confluence），代码注释标注"系统里唯一未经任何回测验证就接入实盘的标的"，需等1d数据积累到210天（RSI2/MR）、252天（Breakout）后补跑回测重新评估。`watchlist_history.csv` 状态改为 `promoted_unvalidated`（区别于其他经过验证的 `promoted`）。`import` 验证：`ALL_SYMBOLS` 108→109。已重启 `stock-alert` pm2 进程使其生效。

### N — 复盘保真度修复（2026-07-25，已完成）

**触发**：用户要求"先确认复盘逻辑有据可循、有意义，而不是一堆没用或缺失的信息"，随后追问三点：本地 CSV 价格是否正确、4h 做空信号的实际出场时刻与止损价是否有记录、持仓上限一刀切是否合理。代码级+数据级审计结论见 LEARNING.md「复盘保真度审计」。

**审计已确认的事实**（不需再验证）：
- 日线价格准确：IB `ADJUSTED_LAST` 与 yfinance `auto_adjust` 抽查 0.000% 差异
- 1h/4h 存在采样锚点错位（IB 整点 vs yf 半点；离线 label=left vs 实时 label=right）——属回测/实盘结构性偏差，**本次不修**，改动会影响实时信号触发时点，需单独评估
- 止损价有记录（`signal_log.csv` 的 `sl` 列 + Telegram 消息），但出场时刻无记录，且"持仓: 最长 2 交易日"文案错误
- `params_json` 早已完整落盘每条信号的真实参数，但复盘链路从未读取

**六项修复（全部只改复盘/账本/文案，不触碰任何策略参数与信号触发逻辑）**：

- [x] **修复1 — 4h 回放改用 4h CSV**：`signal_review._load_local_csv` 的 tf 映射表补 `4h`，让 4h 信号用 `{sym}_4h.csv` 回放而非落到 1h 分支；`_batch_download` 的 interval 分组同步区分 4h。
- [x] **修复2 — 持仓上限改为按信号自带参数**：新增解析优先级 `params_json.max_hold_bars` → (策略, 周期) 默认表（对齐 `rsi2_backtest`/`mr_backtest`/`breakout_backtest`/`config.yaml` 各自的真实默认值）→ 兜底常量，替换硬编码 `MAX_BARS = {1h:10, 4h:10, 1d:15}`。这是 RSI2 复盘胜率 7% vs 回测 60-70% 落差的直接原因。
- [x] **修复3 — `paper_portfolio.update` 同步**：虚拟持仓平仓判断改用修复2 的同一套解析逻辑，消除虚拟净值曲线的同源污染。
- [x] **修复4 — 衰减监控加最小样本量门槛**：N<5 的 (策略,标的) 组合标注"样本不足"，不参与红黄绿判定，避免 N=1/N=2 发出噪声警报。
- [x] **修复5 — 告警文案修正持仓时间**：`_HOLD_DESC` 按 RTH 每日 bar 数（1h=7根/日，4h=2根/日，1d=1根/日）正确换算，并显示具体 bar 数与对应交易日；文案取该信号真实的 `max_hold_bars` 而非全局常量。
- [x] **修复6 — Telegram 周报摘要增信息量**：现摘要仅"信号N条/已决N条/均R"，补充按策略拆分、红灯清单、以及"基线=0R（临时占位）"的显式标注，避免读者把 z 分数误读为对回测期望的偏离。

**实施与验证结果（2026-07-25 完成）**：

- **核心改动**：`review_core.py` 新增 `hold_bars()` / `hold_description()` / `BARS_PER_DAY` / `_FALLBACK_HOLD_BARS`，成为持仓上限的**单一事实源**。解析优先级：信号自带 `params_json.max_hold_bars` → 该策略族的回测默认值 → 兜底。`evaluate()` 的 `max_bars` 参数改为可选，默认按信号自身解析。
- **实测对比（`signal_review.py --days 90`，124 条信号）**：

  | 指标 | 修复前 | 修复后 |
  |---|---|---|
  | RSI2 胜率 | **7%** | **48%** |
  | RSI2 均R | −0.58R | **+0.12R** |
  | RSI2 已决数 | 14 | 23 |
  | Confluence 胜率 | 38% | 19% |

  **RSI2 从 7% 回到 48%（接近回测的 60-70% 区间），证实原数字是复盘口径造成的假象而非策略失效**——若此前据此下线 RSI2，就是被错误数据误导。Confluence 从 38% 降到 19% 方向同样合理：修复前 4h 信号只用 1h 数据回放 10 小时，大量信号在真正触及止损前就被"时间止损"了结记为小额盈亏，现在按真实窗口跑满，该打的止损如实打出来了。
- **衰减监控**：红黄绿从 20 项收敛到 7 项有统计意义的组合（按 z 排序），其余 19 项归入"样本不足未判级"，消除了 N=1/N=2 的噪声警报。
- **连带修复**：`historical_backfill.py` 也带有同一硬编码常量（同样污染历史账本），一并改为按事件参数解析，`MAX_BARS` 替换为仅约束回放切片长度的 `CONTEXT_PAD=96`；已重跑 `--write`（20,918 条候选，23,181 条已决，4,946 条影子）。
- **测试**：`test_review_core.py` 新增 5 个用例（快照优先、按策略/周期回退、影子名归族、4h 交易日换算、`evaluate` 默认窗口），全套 17 个测试通过。
- **未纳入本次范围**：1h/4h 采样锚点错位（IB 整点 vs yf 半点、离线 label=left vs 实时 label=right）会改变实时信号触发时点，属策略行为变化，需单独评估后再决定。

### O — 策略改进（2026-07-26 制定，基于修复后的可信复盘数据）

**前提**：N 节修复后复盘口径才可信，本节所有结论建立在修正后的数字上。最近 90 天 98 条已决 live 信号的归因：

| 策略 × 方向 | N | 均R | 胜率 |
|---|---|---|---|
| Confluence 做多 | 17 | −1.20R | 17.6% |
| Confluence 做空 | 52 | −0.89R | 21.2% |
| RSI2 做多 | 29 | −0.24R | 37.9% |

Confluence 按周期：1h 做多 −0.74R / 做空 −0.75R；4h 做多 −1.64R / 做空 −1.00R；1d 样本仅 5 条。出场分布：止损 48、时间止损 43、ADR/SSL 追踪出场 7——**几乎没有信号活到追踪出场阶段**。

#### ① Confluence 实盘亏损归因（2026-07-26 已完成，结论：证据不足，不调参）

**⚠️ 上表（Confluence 做多 −1.20R 等）已被本次归因推翻，不可作为决策依据**，原因见下。

归因过程与结论：

- [x] **排除采样锚点错位**：同一批 69 条实盘 Confluence 信号分别用 IB bar 与 yfinance bar 回放，均R 仅差 **0.094R**，69 条中仅 2 条结论不同。N 节遗留的"锚点错位"疑虑到此排除，不是亏损成因。
- [x] **排除"实盘 vs 回放标的池可比"的伪对比**：曾用实盘 −1.40R 对比回放 +0.37R 得出"实施偏差"结论，**该对比无效**——实盘 Confluence 只覆盖 14 个老标的，回放覆盖 38 个（含 7/25 才接入的新标的），77 条 vs 201 条仅 11 条重合。收敛到同一批 14 个标的重算后差距仍在（6月实盘 −1.40R vs 回放同池 +0.19R），故进一步深挖。
- [x] **发现真正根因：绝大多数实盘记录的参数快照缺失，其复盘 R 值不可信**。86 条 live 信号中仅 **12 条**（2026-07-20 schema 升级后）带完整 `params_json`；其余 74 条（06-25 ~ 07-17）在复盘时只能使用回退默认值，**未必是当时真实生效的参数**。两组结果截然相反：

  | 分组 | N | 均R |
  |---|---|---|
  | Confluence **有**参数快照 | 6 | **+0.29R** |
  | Confluence **无**参数快照 | 63 | −1.09R |
  | RSI2 有参数快照 | 6 | −0.77R |
  | RSI2 无参数快照 | 23 | −0.10R |

  所谓"6 月惨案（−1.40R）"全部来自无快照的旧记录。
- [x] **最终结论：当前无任何证据表明 Confluence（或其他策略）存在问题**。唯一确定的事实是**可信实盘样本仅 12 条**，在此之上做任何参数调整都是对噪声拟合。**不调参**。
- [ ] **后续动作**：持续积累带参数快照的实盘信号，达到 30-50 条已决后重新评估。在此之前 ① 保持关闭。

**方法论教训**：归因过程中我两次基于错误口径得出结论（先误用 `is_shadow==0` 漏掉 86 条旧记录，后用不可比的标的池做跨源对比），均在下一步验证中被推翻。涉及跨数据源/跨时期对比时，必须先确认两侧的样本构成可比、字段完整性一致，再解读差异。

#### ② 衰减监控基线：0R 占位 → 回测期望表（2026-07-26 已完成）

- [x] 新建 `build_expectations.py`，从 15,969 条已决回放（非影子）按 `(策略,标的,周期)` 聚合均R/σ，生成 `strategy_expectations.json`（136 个组合）。该文件**纳入 git 跟踪**——`logs/*.csv` 被 gitignore，而监控结论必须与产生它的期望表一起可复现。
- [x] 判定从 `z = 均R/σ`（基准0R，含义"最近是否亏钱"）改为 `z = (均R − 历史期望)/σ`（含义"是否显著差于自身历史"）。监控分组同步加入 `tf` 维度（同一标的 1h 与 1d 表现差异大，期望表本就按周期分键）。
- [x] 实例：`RSI2 MRVL 1d` 从"−0.77R 红灯"变为"−0.77R vs 期望 +0.60R，z=−4.15"，判定有了明确依据。
- [x] Telegram 周报的红灯清单与基线说明同步改用期望表。
- [x] **最小样本量定为 25 而非 30**：RSI2 MRVL/MU/SMH 1d 回放样本 25-27 条，用 30 会把正在被监控的组合排除在期望表外，反退回占位符。
- [ ] **已知覆盖缺口（如实标注未掩盖）**：33 个实盘组合中 **19 个在回放里无数据**，因其走 `STRATEGY_MAP` 未显式列出的默认 Confluence 路由（AAPL 1h、AMZN 全周期、INTC、SMH 1h、QQQ 1h/4h、TSLA 1h 等），而 `historical_backfill.py` 明确跳过 fall-through 路由。这些组合监控输出显式标注 `(占位)`。补齐需让回放覆盖默认路由，属独立改动。

#### ③ Quality 星标预测力校准（2026-07-26 已完成，结论：无预测力，已移除）

- [x] ~~实盘分桶 0-4 −0.56R / 5-7 −0.91R / 8-10 +0.01R~~ 该结论被 ① 推翻（74/86 条实盘记录缺参数快照），改用 backfill 大样本重做。
- [x] **15,969 条已决回放检验结果：quality 与实际 R 相关系数 +0.0024**（Confluence +0.0042，RSI2 **−0.0077** 反向）。高分组(8-10) vs 低分组(3-5)：Confluence 差 +0.034R（t=+0.45），RSI2 差 −0.069R（t=−0.68），**均远未达统计显著**。各分档均R 全落在 +0.41~+0.53 窄带内，RSI2 的 8 分档（+0.42）不如 5 分档（+0.52）。
- [x] **⭐ 星标已从三类告警消息中移除**（Confluence/RSI2/MR），避免传递数据不支持的置信度。
- [x] **quality 字段本身保留**：多周期共振加分与 `meta_label` 仍在消费该字段，且保留供后续重新设计评分公式时研究。

#### ④ 新接入标的的上线验证补做（2026-07-26 已完成）

- [x] 新建 `validate_watchlist.py`：成本压力（0/5/10/20/30 bps，以 10bps 仍达 Sharpe≥0.6 为合格线，因 IB round-trip 约 5-10bps）+ Walk-forward（时间前 60% 训练 / 后 40% 测试，任一段 <15 笔标记 insufficient 不强给结论）。`backtest_runner.run_backtest` 新增可选 `df_override` 以支持分段回测。
- [x] **107 个组合验证结果**：

  | 检验 | 结果 |
  |---|---|
  | 成本压力 | pass **99** / fail 8 |
  | Walk-forward | pass 42 / insufficient 37 / **fail 22** / marginal 6 |

- [x] **成本压力总体良好**，8 个失败全部来自网格优化批次（常规批量接入 0 个失败）。最严重 `LLY 1h`：0bps 0.529 → 10bps **0.010** → 30bps −1.061，典型高频小赚型被佣金吃光。
- [x] **Walk-forward 暴露真实过拟合**，且**不限于网格优化批次**：可判定组合中网格批次 fail 率 34%（12/35），常规批次 29%（10/35），两者接近——说明默认参数批量接入同样有约三成撑不住样本外。前 5 名为崩塌式：`GME 1h`（训练1.18→测试**−2.24**）、`CEG 1h`（1.13→−0.99）、`STLA 4h`（1.89→−0.96）、`DUOL 1h`（1.79→−0.93）、`CCJ 1h`（1.26→−0.77）。**关键点：这些标的全样本 10bps Sharpe 均在 0.6~1.14 之间看起来完全合格，只有分段验证才暴露问题**。
- [x] **降级处置（9 个组合）**：标准为「样本外测试期 Sharpe < 0」或「10bps 下 Sharpe < 0.3」。其中 `CEG/DUOL/FWRG/GME/PYPL/STLA` 六个标的的唯一路由被降级，已整体移出 `watchlist_2026_07`（86 个标的）；`CCJ/LLY/UP` 各降级一个周期但保留其他合格路由。`alert_engine.py` 中对应 `STRATEGY_MAP` 条目改为注释保留（含降级原因与原始指标），不直接删除以便追溯。
- [x] 验证：`ALL_SYMBOLS` 109→103，`STRATEGY_MAP` 140→131，降级路由确认失效、保留路由确认完好，17 个测试通过。完整结果见 `watchlist_validation.csv`。
- [ ] **未处置项**：其余 13 个 walk-forward fail 组合（测试期 Sharpe 在 0~0.44 之间，未转负）暂予保留观察，避免一次性砍掉过多标的导致信号枯竭；建议积累实盘样本后结合 ② 的衰减监控再决定。

#### ⑤ 默认路由未验证缺口（2026-07-26 发现，**当前系统最大风险敞口**）

**问题**：`STRATEGY_MAP` 未显式列出的 `(标的,周期)` 组合会 **fall-through 到默认 Confluence** 并照常发信号。`ALL_SYMBOLS` 103 个标的 × 3 周期 = 309 个组合，其中仅 126 个有显式路由，**183 个走默认路由且从未按该路由验证过**（涉及 97 个标的）。

**实际影响（非理论风险）**：
- **实盘 114 条 live 信号中，57 条（50%）来自默认路由**。
- 154/183 个组合**曾被明确回测判定不达标**却仍在发信号；其中 **15 个 Confluence Sharpe 为负**：`CRWV 1d(−1.27)` `CRCL 4h(−1.24)` `SPYM 1h(−1.03)` `PKW 1h(−0.82)` `GFS 1d(−0.67)` `USAR 1d(−0.65)` `SPYM 4h(−0.53)` `BAC 4h(−0.48)` `MORN 1h(−0.38)` `DJT 4h(−0.34)` `VOO 4h(−0.20)` `OSCR 1d(−0.18)` `GOOG 1h(−0.10)` `PB 1d(−0.09)` `DJT 1d(−0.03)`。
- 另有 22 个组合**从未做过任何回测**。
- **与 ② 的占位符现象同源**：衰减监控里标红却显示"(占位)"的 `SMH 1h`(8条实盘信号)、`SNDK 4h`(5条)、`QQQ 1h`(6条) 全部是默认路由——`historical_backfill.py` 明确跳过 fall-through，所以它们既无回放期望值、也从未被验证。

**为何一直没被发现**：`SPCX` 此前被标注为"系统唯一未经回测就接入实盘的标的"，该表述**不准确**——它只是唯一被显式标注的，实际有 183 个组合处于同样状态。

**待决策的处置方向**（改动会显著减少信号量，需先确认取向）：
- [ ] **方案A（保守，推荐）**：把 fall-through 默认从 `confluence` 改为 **不发信号**，只有显式列入 `STRATEGY_MAP` 的组合才扫描。影响：实盘信号量约减半，但保留的都是验证过的。需同步确认原主池 17 标的的默认路由组合（AAPL 1h/4h、AMZN 全周期、INTC、SMH 1h、QQQ 1h/4h、TSLA 1h 等）是否有意为之。
- [ ] **方案B（折中）**：保留默认路由但先关闭已知为负的 15 个组合，其余标注"未验证"后台观察。
- [ ] **方案C（补验证）**：对 183 个组合批量跑 Confluence 回测 + 上线验证，达标者转显式路由、不达标者关闭。成本最高但最彻底。
- [ ] 无论选哪个方案，都需让 `historical_backfill.py` 覆盖默认路由，否则 ② 的期望表永远补不齐这 19/33 的缺口。

#### ⑥ 无覆盖标的的处置：watchlist 选股宇宙 + 季度复检（2026-07-26 已完成）

**触发**：用户追问"没有覆盖的 ticker（尤其个股）怎么办"。核查发现此前"screener 已覆盖它们"的说法**有漏洞**——screener 只扫指数成分池（NDX100/SP500/Dow30/R2000），watchlist 里 **25 个个股既无策略路由、也不在任何指数池内，完全无人看管**（含 ASTS/RKLB/NBIS/DUOL/GEV/LINK/ZION 等）。

- [x] **`universes.py` 新增 `watchlist` 宇宙**：从 `watchlist.txt` 加载（285个，按 `watchlist_history.csv` 自动过滤 non_us_or_invalid / no_data_unverified，`BRK.B`→`BRK-B` 格式转换），基准 SPY；`screener.py --universe watchlist` 已接入并实测跑通（原孤儿 GEV 排第6、LINK 第11、WDC 第7）。**周频因子选股现在覆盖用户关注的全部标的**——个股不需要常驻策略，需要的是轮换发现机制：动量转强自然进 Top 榜。
- [x] **~~季度复检（文档化流程）~~ → 升级为月度自动化（2026-07-26，应用户"周/季度都太慢"反馈）**：新建 `revalidate_rejected.py`——每月1日 06:00 自动对 rejected 池重跑四策略回测，初筛通过者追加成本压力(10bps)+walk-forward 全套验证，全部通过才推送"待接入候选"报告；**不自动接入**，标的/参数变更仍需人工确认。频率刻意封顶在月度：反复重测同一批标的会抬高多重比较假阳性，脚本 docstring 内已注明"不要再加密到每周"。依据实证：`DELL`(7/2拒→7/25收)、`IREN`(旧评估不稳→刷新后接入)、`HOOD`(第二批达标)。
- [x] **发现机制全部自动化 + 提速为每日（2026-07-26）**：pm2 新增三个定时任务（`ecosystem.config.js`，已 `pm2 save`）：
  - `stock-daily-screener` 每交易日 13:20 PT（收盘后20分钟）：watchlist 全池因子选股 Top15 → Telegram。周频→**每日**。
  - `stock-watchlist-events` 每交易日 13:35 PT：**新建 `watchlist_events.py` 事件雷达**——52周新高突破 / 20日新高+2×放量 / ±5%异动+放量，覆盖全部 285 个 watchlist 标的（含无策略路由的个股），消息显式标注"发现型提醒，未经过策略验证，无TP/SL"。首轮实测：LMT 放量新高+10.5%、TSLA 异动-14.5% 等 10 条。
  - `stock-monthly-reval` 每月1日 06:00 PT：上述 rejected 池复检。
  - 配套修复：`screener._load_csv` 加 4 天陈旧检查（每日自动跑不能静默用停更快照算因子），yfinance 兜底从逐个请求改为 50 只/批的批量下载（285 标的全量兜底也能在几分钟内完成，不会被限流拖死）。
- [x] 处置总原则已记入 LEARNING.md：不是每个标的都需要一条策略，"无策略 + 每日发现机制 + 月度复检"就是无覆盖个股的完整答案。

#### ⑦ fetch_etf_data 覆盖事故与修复（2026-07-27，数据完整性）

**事故**：`fetch_etf_data.py` 对输出文件是**直接覆盖**而非合并，且其清单包含与主策略池共用的 `SPY/QQQ/SMH/SOXX`。2026-07-24 IB 恢复后重跑 ETF 回补时，把这四个文件刚恢复的十年日线**截断成两年**（2512→501行）。**7/24-7/26 之间所有基于 1d 的下游产物都被污染**：历史回放（SMH 1d 只回放出 27 笔，实为 208 笔）、期望表、以及全部 1d 路由的验证（QQQ regime 过滤只剩两年历史）。1h/4h 不受影响。发现路径：动量轮动实验里 risk_off 分支前半段整段空仓（Sharpe 恰好 0.000）——异常数字顺藤摸瓜找到根因。
- [x] **堵 bug**：`fetch_etf_data.fetch_symbol` 改为合并写入（保留旧历史，重复时间戳以新拉取为准）。
- [x] **恢复数据**：IB `--merge` 重拉四个文件，全部回到 2510-2512 行（2016起，至7/24）。
- [x] **重建下游**：`historical_backfill --write`（已决 15,969→**17,367**）+ `build_expectations.py` 重新生成。
- [x] **重验全部 1d 显式路由**：watchlist 批次同口径判定翻转 3 个——**`SNAP 1d`(10bps 0.40, 样本外-0.09)、`OUST 1d`(10bps 0.06)、`ONDS 1d`(10bps 0.41) 降级**（SNAP/OUST 失去唯一路由移出扫描池 86→84+2=86…净84+ONDS保留1h）；`PYPL/UP 1d` 维持降级；`MSOS/RBLX/SOFI/TMC/HOOD 1d` 复验通过维持。
- [ ] **原主池 1d 路由的重验数字不采信（口径缺口，遗留）**：STX/TSLA/SPY/SMH/SOXX/AAPL/MRVL/PLTR 1d 在这轮重验显示 fail_cost，但它们当年是用网格最优参数（含 hold≤15 等）验证的，而 `RSI2_PARAMS` 落地时**没有记录 `max_hold_bars`**，重验只能用默认 10，口径不公平。待办：把各标的的最优 hold 补进 `RSI2_PARAMS`，再做一次公平重验；在此之前交由衰减监控（现已有可信期望表）裁决。

#### ⑧ 网上搜索的新策略家族评估（2026-07-27，结论：全部不接入）

应用户"去网上搜一下还有没有没用过的策略"要求，检索后筛出两个有据可依、基础设施现成的家族实测，另两个按文献直接排除：
- [x] **Donchian 20/10 与 55/20 通道突破**（Turtle 风格，异于已测的 252 日）：86 只个股池，中位 Sharpe 仅 0.23-0.30；达标的 9 只全部是已有更优路由的标的（AAPL/NVDA/MU…）。**不增量，不接入。**
- [x] **长多头横截面动量轮动**（文献支持多头腿 +7.9%/年）：QQQ 数据修复前曾测出"样本外 Sharpe 1.0+"，修复后证实是假象。全历史下前半选参→样本外 Sharpe 0.906 但 **DD -43%**，且池子由"今天已达标"的股票构成，**幸存者/选择偏差无法消除**（PLTR/RBLX 等当今赢家自动在后半段加入）。对比 MAG7 轮动（1.066/DD-34%，偏差小得多）无优势。**不接入**；如未来要做需要时点化宇宙（point-in-time universe），当前没有。
- [x] **隔夜效应（close-to-open）**：文献自认按真实执行时间（9:31）测会大幅缩水，且日日换手过不了本系统 10bps 成本关。**按文献排除。**
- [x] **月末效应（turn-of-month）**：近十年已消失（多来源一致）。**按文献排除。**

#### ⑨ 盘中半根 bar 触发信号 + benchmark regime 旁路（2026-07-27，用户实盘质疑暴露）

**触发**：用户质疑"07:00 PT 大盘加速下跌时系统发了一串做多（含 QQQ）"。核查确认是**三个真实缺陷的叠加**，当日 07:00-08:00 发出的 6 条 1d 做多（MRVL/SOXX/SMH/QQQ/SPY + DGRO breakout）**全部为缺陷产物，应作废**（记录保留在 signal_log 作事实存档，复盘解读时剔除）：

- [x] **缺陷1 — 盘中半根 bar 被当完整 bar 用**：yfinance 会返回当前未走完的 bar，`fetch_bars` 未过滤。07:00 PT（10:00 ET 开盘半小时）时"今日日线"只走了半小时，早盘急跌让 RSI2(2周期) 在这半根 bar 上瞬间超卖 → 触发做多。**回测信号全部产生于完整 bar 收盘，从未见过盘中数据**——回测验证的是"跌完一整天后按收盘决策"，实盘却在"跌到一半时抄底"，语义完全错位。修复：`_drop_forming_bar()`——1d 在 16:00 ET 收盘前丢当日 bar，1h 丢起始+1h>now 的，4h 丢结束时刻>now 的；`fetch_bars` 统一生效（主循环+breakout 共用）。
- [x] **缺陷2 — benchmark 的 regime 评分被整体旁路**：设计意图（config 注释）是 QQQ/SPY 只跳过"与 QQQ 比相对强度"，但代码把整个 regime 计算都跳了，market_score 停在初始值 4.0——大盘怎么跌，QQQ 自己的信号都显示 Regime 4/4 满分放行。修复后 QQQ/SPY 同样计算真实趋势分（当日实测 4.0→2.0）。
- [x] **缺陷3（修复1的衍生问题，当轮扫描即暴露）— 陈旧 bar 信号补发**：丢弃半根 bar 后最后完整 bar 变为 07-23（yfinance 恰好缺 07-24 周五 bar，IB 本地有，属 yfinance 偶发缺失），dedup 键随 bar_date 变化 → 引擎把四天前 bar 的信号当新信号补发（QQQ/SPY 1d 做多各一条，同样作废）。修复：`_bar_fresh()` 新鲜度检查——信号仅在 bar 收盘后有效窗口内可发（1h=4小时/4h=12小时/1d=30小时），数据缺口或停机重启后不补发陈旧信号。
- [x] **验证**：修复后当轮扫描 0 条新信号，全部 1d 组合被"最后完整bar(2026-07-23)已陈旧"正确拦截；今晚收盘后 07-27 完整 bar 生成，1d 扫描自动恢复。17 个测试通过。
- [ ] **遗留观察**：1d 信号现在只会在收盘后（13:00 PT 起）的扫描发出，盘中不再有 1d 新信号——这是与回测语义对齐的正确行为，但信号节奏会比之前"安静"，属预期变化。

#### ⑩ 数据源混合架构与观测性（2026-07-27）

- [x] **夜间 IB 自动刷新**：pm2 `stock-nightly-ib-refresh`（交易日 14:00 PT），`fetch_ib_data --merge` 全池保鲜；`fetch_ib_data` 的标的清单补上 `watchlist_2026_07` 组（此前 PANW/IREN/WDC 等根本不在补拉范围，共108标的）。前提变化：期货侧已收敛为单一 `ib-market-data-fetcher`，Gateway 配额富余（用户指出）。
- [x] **1d 近期缺口填补**：`_fill_recent_gaps_from_local()`——yfinance 缺整根 bar 时（07-24 全池日线缺失实例）用本地 IB 补，仅 1d、仅近10天窗口、排除当日半根 bar。1h/4h 不拼接（IB 整点锚 vs yf 半点锚，混网格毁指标）。
- [x] **整段拉空兜底**：`_local_bars()`——yfinance 返回空/异常时整段回退本地 IB 数据（整段替换无混网格问题）；**刻意不让引擎直连 IB 现查**：yfinance 大面积失败时兜底请求也大面积发生，直连会瞬间打爆 60次/10分钟配额（Error 162 老路）。本地 4h 为 label=left，其防御按 stamp+4h 计算 bar 结束。
- [x] **yfinance 软限制应对**：财报日期按日缓存（原每小时 ~90 次 quoteSummary，占扫描请求量近1/3）；单轮拉取失败率 >20% 发 Telegram 告警（防大面积限流时扫描"静默变瘦"）；扫描尾部显示拉取成功率。
- [x] **screener_results.csv 双重故障修复**：①schema 混入（daily screener 新格式盲目追加旧文件→解析崩溃→异常被吞且误报"不存在"，~11小时）——`save_csv` 现校验列结构、不一致归档重建，解析失败如实报错；②**更严重的无声陈旧**：7月初至自动化上线前，扫描里的"本周因子选股"一直是 6-30 的旧排名（近4周），无任何症状。教训见 LEARNING.md。
- [x] **选股宇宙应用结构性排除**：SGOV（货币基金）曾因零波动令"风险调整动量"因子爆表排进 Top5，`_load_watchlist` 现排除与月度复检相同的结构性清单。

#### ⑪ SHOP 加入 watchlist（2026-07-27，用户因当日暴拉要求）

- [x] 拉取 SHOP 1d/1h/4h 历史数据（yfinance，1d 2512行覆盖10年）
- [x] 四策略×三周期全测（`validate_watchlist.validate_one` 复用）：
  | 策略 | 周期 | 10bps Sharpe | maxDD | 结论 |
  |---|---|---|---|---|
  | Confluence | 1h/4h/1d | -0.01 / -1.36 / -0.27 | 均较小 | fail（成本压力/样本内即负） |
  | RSI2 | 1h/4h/1d | 0.07 / 0.01 / 0.34 | -28.9%/-17%/-38.4% | fail（1d wf仅marginal 0.40，风险偏高不接入） |
  | MR | 1h | **0.93（pass）** | -0.0% | **N=22 < 30 门槛，样本不足** |
  | Breakout | 1d | -0.296 | **-56.6%** | fail（超风控阈值） |
- [x] 结论：**不接入实盘**，10 条测试记录写入 `watchlist_history.csv`；MR 1h 列入 `pending_high_vol` 观察（config.yaml），待样本量增长后复检
- [x] SHOP 加入 `watchlist.txt`（267标的），自动纳入 daily screener + 双时段事件雷达（EOD 13:35 PT / 盘中 10:45 ET）覆盖范围——用户的实际诉求（"暴拉能否更快发现"）已由此满足，不依赖策略路由

#### ⑫ 事件雷达盘中轮次 + 缺口导致的跌幅双倍计算（2026-07-27）

**触发**：用户问"SHOP 这种暴拉能提前侦测吗"。回答分层：新闻驱动无法提前预测；催化剂日历（财报）可提前；发现延迟可从收盘后6小时压缩到开盘后1小时——已实现。

- [x] **新增盘中事件雷达**：`stock-watchlist-events-am`（交易日 07:45 PT / 10:45 ET），`watchlist_events.py --intraday`——量比按已过时段折算（`session_frac`），避免早盘真实放量被全天均量稀释漏报。实测抓到 AAPL 盘中破52周新高。
- [x] **SHOP 加入 watchlist**（四策略验证不达标，仅进观察名单，详见 ⑪）——已使其自动进入两次事件雷达 + daily screener 覆盖范围。
- [x] **发现并修复：跌幅双倍计算 bug**：用户实测发现 SMH 显示"-5.5%异动"，但真实盘中跌幅仅 -2.25%。核查：yfinance 当日序列缺 07-24 那根 bar（与此前 QQQ/SPY 缺口同类问题，非一次性事故），`watchlist_events.py` 用 naive `iloc[-1]/iloc[-2]` 相邻比较，缺口导致悄悄跨 07-23→07-27 两个交易日当一天算（580.17→561.19→548.55，真实两段 -3.4%/-2.25%，误算成单日 -5.45%）。修复：接入与 `alert_engine.fetch_bars` 相同的 `_fill_recent_gaps_from_local()`，用本地 IB 数据补齐近期缺口后再计算涨跌/量比。复测 SMH 不再触发异动阈值（真实-2.25%本就低于5%门槛）。
- [ ] **遗留观察**：yfinance 缺整根 1d bar 已出现两次（QQQ/SPY/SMH/SOXX 全池一次，SMH 单独一次），可能是频繁模式而非孤立事故；两条消费链路（alert_engine、watchlist_events）现已共用同一补丁，但若还有其他脚本直接用 yfinance 日线做相邻日比较（如 screener.py 的动量因子），需要排查是否有同类风险。

#### ⑬ 谐波形态策略原型验证（2026-07-28，用户提议）

**背景**：用户问"谐波分析是什么策略"后要求单独做原型验证 QQQ 和 SPY——不接入 alert_engine，纯研究探针。

- [x] 新建 `harmonic_signals.py`（ATR阈值zigzag摆动点 + Gartley/Bat/Butterfly/Crab 比例匹配 + D点PRZ投射，逐bar扫描无lookahead）+ `harmonic_strategy.py`（复用 mr_strategy.py 的ATR追踪+时间止损机制，初始止损种子改为X点结构失效位）+ `harmonic_backtest.py`（含 `--validate` 成本压力+walk-forward）
- [x] **结果：全部6个组合（QQQ/SPY × 1h/4h/1d）信号数均 <15 笔门槛**（QQQ 1h=9/4h=4/1d=4；SPY 1h=4/4h=3/1d=6，1d已是10年历史）。谐波形态四段比例同时匹配本身是低频事件，仅测2个标的注定样本枯竭。
- [x] **结论：insufficient，不下有效/无效结论**——不像单标的硬凑理由，如需真正验证需池化至数十个标的（如整个watchlist）才可能凑够统计样本量，待用户决定是否扩大范围。

#### ⑭ 用户批量加入18个标的（2026-08-02）

**输入**：MAR/SNAP/ON/AMET/MCD/ALAB/MRK/LLY/UBER/CRCL/AXON/NVO/U/ABNB/AAOI/UUUU/TTD/MP/OKLO

- [x] **验真+去重**：`AMET` 经 yfinance 核实为无效代码（无价格数据，"possibly delisted"），未加入，已告知用户。SNAP/LLY/UBER/CRCL/NVO/AAOI/OKLO 已在 watchlist 中测试过，跳过重复工作。真正新增 11 个：MAR/ON/MCD/ALAB/MRK/AXON/U/ABNB/UUUU/TTD/MP
- [x] **四策略×三周期全测**（110个组合，`validate_watchlist.validate_one` 复用）：
  | 标的 | 达标路由 | 10bps Sharpe | N | wf |
  |---|---|---|---|---|
  | MAR | rsi2 1h | 0.691 | 62 | pass（训练0.51→测试1.04） |
  | ALAB | rsi2 1h | 0.835 | 92 | marginal（训练1.00→测试0.57，样本量大予以接入） |
  | TTD | confluence 1h | 0.65 | 102 | pass（训练0.57→测试1.71） |
  | AXON | confluence 4h（未接入） | 0.64 | 32 | insufficient（分段各仅19/10笔太薄） |
  | ON/MCD/MRK/U/ABNB/UUUU/MP | 无 | — | — | 全部组合10bps成本压力不达标或maxDD超阈值 |
- [x] **接入实盘**：MAR/ALAB/TTD 三条路由写入 `STRATEGY_MAP`，加入 `config.yaml` watchlist_2026_07；AXON 放入 `pending_high_vol` 观察（cost达标但wf样本太薄，不同于SHOP-MR的"N<30"，是"N过30但wf分段不足"这种新的边界情况）
- [x] **110 条测试记录**全部写入 `watchlist_history.csv`（含未达标的，如实记录不隐藏）
- [x] 全部 18 个原始标的（除AMET）已在 `watchlist.txt` 中，自动进入 daily screener + 双时段事件雷达覆盖范围

#### ⑭ watchlist.txt 批量写入把11个代码挤成一行（2026-08-02，用户追问触发发现）

**触发**：用户问"alab, lite, cohr, voyg 在列表里么"，查证时发现 08-02 那次18标的批量添加（commit 8aeb467）虽然回测、路由（`STRATEGY_MAP`）、`config.yaml`（`watchlist_2026_07`）三处都正确写入了 MAR/ALAB/TTD，但写 `watchlist.txt` 时把 11 个新代码（MAR/ON/MCD/ALAB/MRK/AXON/U/ABNB/UUUU/TTD/MP）**合并成一行空格分隔的字符串**，而不是每行一个。commit message 明确宣称"每个标的都进了daily screener和事件雷达覆盖"，但实际这一整行被 `universes._load_watchlist()` 当成了**一个**畸形代码，11 个标的全部**不在**实际生效的 watchlist universe 中——已路由的 3 个（MAR/ALAB/TTD）实盘信号不受影响（路由不依赖 watchlist.txt），但另外 8 个未路由标的（ON/MCD/MRK/AXON/U/ABNB/UUUU/MP）此前完全没有任何覆盖，跟从未加入过一样。

- [x] **修复**：拆成 11 行，重新排序去重，验证全部 11 个标的均在 `universes.get_universe("watchlist")` 返回集合中
- [x] **确认未受影响的部分**：`config.yaml` watchlist_2026_07（ALAB/MAR/TTD 正确的逗号分隔列表）、`STRATEGY_MAP`（ALAB/MAR/TTD 路由）、`watchlist_history.csv`（110条测试记录完整）均无问题，只有 `watchlist.txt` 这一处写坏
- [ ] **教训待写入 LEARNING.md**：批量写入类操作（尤其是拼接多个值到一个文件）必须在写入后立即用消费方的实际读取路径验证（如这里应该跑一次 `get_universe("watchlist")` 确认计数=预期新增数），不能只看"diff 里加了一行"就当作成功——这次连 commit message 都写错了（"every ticker is now in watchlist.txt"是假的），说明单纯读 diff 也可能被表面现象误导。

#### ⑮ LITE/COHR/VOYG 加入验证（2026-08-04，用户在追问ALAB时一并要求）

- [x] yfinance 验真通过（均为真实标的：Lumentum/Coherent/Voyager Technologies）；VOYG 2025-06-11上市，历史仅287个交易日
- [x] 拉取数据时发现 **1d 最后一行 OHLC 全 NaN（volume非空）**，三个标的都撞上——不是策略问题，是这次拉取当天的数据质量问题；`dropna(subset=['close'])` 清洗后重跑 1d 验证
- [x] 四策略×三周期全测（30个组合，含 mr/1d 等信号数0的空结果）：
  | 标的 | 最佳组合 | 10bps Sharpe | N | 结论 |
  |---|---|---|---|---|
  | LITE | RSI2 1h | 0.707（过成本关） | 95 | **wf fail**：训练1.158→测试0.214，远低于训练一半，衰减明显，reject |
  | COHR | RSI2 4h | 1.022（过成本关） | **28<30** | 样本不足，同 AXON 先例，列入 `pending_high_vol` 观察 |
  | VOYG | RSI2 1h | 0.282（不过成本关） | 37 | wf 虽 pass 但成本关不过，reject；历史仅286个交易日，样本天花板有限 |
- [x] 结论：**三个都不接入实盘**，30条测试记录写入 `watchlist_history.csv`；COHR RSI2 4h 加入 `config.yaml pending_high_vol`；三个标的均加入 `watchlist.txt`（**写入后立即用 `get_universe("watchlist")` 逐个验证**，吸取 ⑭ 的教训，未再犯合并成一行的错）

#### 已在流水线中、本节不重复动作

- 4 个影子实验（TSLA 出场变体 / MRVL 宽出场 / RSI2+IBS / RKLB 突破）在等样本积累
- Pyramiding 完整状态机（见 L 节）
- 采样锚点统一（见 N 节未纳入项，独立课题）

**执行顺序**：①+② 一次性完成（同吃 backfill 期望分布），③ 顺路核查字段，④ 后台批量跑。

## 待完成（优先级顺序）

### A — alert_engine 剩余功能

- [x] RSI2 v2 集成到 `alert_engine.py`
- [x] ConfluenceStrategy 告警整合（MU/MRVL/SNDK/STX）
- [x] ALL_SYMBOLS 修复（旧字段 → 新分组名）
- [x] Market Regime Score 实时计算（QQQ bar + VIX）
- [x] Market Regime Score 加入告警通知（Confluence + RSI2 均已加 Regime 行，含 VIX 值）
- [x] 多标的多信号处理：每条信号独立发送，标题注明标的/周期/策略，无需代码层过滤

### B — 数据接入

- [x] **VIX 数据接入**：YFinanceProvider `^VIX`，15 分钟延时，已集成到 alert_engine
- [x] **数据接入层抽象**：`data_providers.py` MarketDataProvider 基类，支持 yfinance / tastytrade（已实现）/ IB（占位），`config.yaml` 一行切换
- [x] **Tastytrade 认证**：完整 auth 流程（security question + OTP），remember-token 写入 `.env`，后续自动续期
- [x] **Tastytrade VIX**：`TastytradeProvider.fetch_vix()` 内部转发 YFinanceProvider（REST API 无直接 VIX 价格端点，DXLink 不必要）
- [x] SNDK 历史数据：2025-02-20 重新上市，仅用 1h 数据，`STRATEGY_MAP` 已只配 `("SNDK", "1h")`

### C — 参数稳定性验证（已完成）

- [x] **成本压力测试**：MU/SNDK 1h 全段合格；MRVL 1h 10bps 内合格；GOOGL 1h RSI2 成本敏感，移除实盘候选
- [x] **参数邻域稳定性**：SOXX/META/GOOGL 1d Top-5 spread < 0.09，全部稳定
- [x] **Walk-forward 验证**：8/9 RSI2 1d 通过，无过拟合；MSFT 测试期 N 不足（信号稀少，非过拟合）

### D — 风控层

- [x] Market Regime Score ≤ 1 时告警通知包含评分，人工判断是否执行
- [x] 多信号优先级：消息标注标的/周期/策略，不做代码层强制去重
- [x] **信号去重**：同一根 bar 触发的信号只发一次 Telegram，`_sent_signals` dict 记录 `(symbol, tf, strategy, direction) → bar_date`，新 bar 出现才重新判断
- [x] **重启去重持久化**：`_sent_signals` 写入 `data/.sent_signals.json`，启动时加载（保留最近 7 天记录，覆盖周末重启场景），重启后不重复发送同一根 bar 的信号
- [x] **做空 Regime 过滤**：`max_market_score_short: 2`（config.yaml 三周期），market_score ≥ 3 时 Confluence 做空信号被自动过滤，防止强牛市逆势做空
- [x] **通知加持仓时间**：SL 行末追加"持仓: 最长 X"（1h=10小时，4h=2交易日，1d=3周）
- [ ] 单标的最大风险敞口（0.75% equity）：需持仓状态，跳过（人工自律）
- [ ] 半导体总暴露上限（≤ 45%）：同上，跳过

### E — 部署（已完成）

- [x] **Telegram 配置**：token + chat_id 已写入 `.env`，测试消息发送成功
- [x] **pm2 集成**：`stock-alert` 以 `/bin/bash -c python3.11 alert_engine.py --port 4001` 方式启动，与 `ib-bot` 模式一致，`pm2 save` 已保存
- [x] **`restart_engine.sh`**：`PATH=/opt/homebrew/bin:$PATH pm2 restart stock-alert`
- [x] **实盘验证**：2026-06-21 20:03 ET 扫描 15 个标的，STX 4h + 1d 做多信号触发并推送 Telegram ✅

### H — ETF 板块轮动扫描器（已完成）

- [x] **`etf_scanner.py`**：Rotation Score（0-100 追强）+ Reversal Score（0-100 超跌反转）+ Weakness Score（0-100 做空候选），45 只 ETF，9 个分组，含 ETF 中文名称
- [x] **`fetch_etf_data.py`**：IB Gateway 日线数据抓取器（45 ETF + SPY + QQQ + VIX），`data/{ETF}_1d.csv`，2年历史
- [x] **IB VIX**：`fetch_etf_data.py --symbol VIX` → IB `Index('VIX','CBOE','USD')` 合约，`data/VIX_1d.csv`
- [x] **ETF 替换**：IRBO（已退市） → ARTY；VPN（已退市） → DTCR
- [x] **量子/太空 ETF 加入**（2026-07-02）：新增分组"量子/太空"→ QTUM（Defiance量子计算ETF）、UFO（Procure太空ETF），同步更新 `etf_scanner.py` + `fetch_etf_data.py`
- [x] **市场环境判断**：SPY 200MA + 20MA>50MA + QQQ/SPY 相对趋势 + VIX，输出 Risk-On / Neutral / Risk-Off
- [x] **Telegram 推送**：`--telegram` 参数，输出轮动 Top5 + 超跌 Top5 + 做空候选 Top5，含 ETF 名称
- [x] **Weakness Score（做空候选）**：`calc_weakness_score()`，Rotation Score 镜像因子（<50MA/200MA/跑输SPY20d/60d/RS趋弱/RS新低/放量下跌），RSI<35 超跌标的自动跳过，阶段标签：做空确认(≥60) / 弱势观察(≥40)

**用法**（每周更新数据 + 随时扫描）：
```bash
# Mac Studio 更新数据（约5分钟）
/opt/homebrew/bin/python3.11 fetch_etf_data.py

# 本机跑扫描
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ data/
.venv/bin/python etf_scanner.py --top 10
```

### F — MR 策略（暂缓）

- [ ] MR 策略全部时间框架笔数 < 50，暂停使用
- [ ] 如需重启：z-score 波动率自适应 + close > 100SMA + ADX slope 检查

### G — 研究（低优先级）

- [x] **PEAD（财报后漂移）**：`pead_backtest.py` 框架完成，已接入 Alpha Vantage 免费 API（5年历史，`--av-key KEY` 抓取）。结论：**PEAD 在本标的池不成立**（全体 WR=34.2%，avgRet=-1.58%，9只标的全部亏损）。大市值科技/半导体财报信息消化极快，当天基本 price in，无漂移空间。TSLA 同样无效（WR≈50%，avgRet≈0）。彻底放弃。
- [x] **MAG7 周频相对强弱轮动**：`mag7_rotation.py`，最优 top=3, rs=90d, risk_off=True → Sharpe 1.066，MaxDD -34%，显著优于等权 MAG7 基准（0.802）
- [x] ConfluenceStrategy 降维实验：3 层 vs 6 分项对比，**原始 6 分项全面胜出**，维持不变（见 LEARNING.md）
- [x] **VIX 急升回落抄底**：vix_spike_recovery 指标（近10日 VIX>25 且当前回落）回测验证 MSFT +0.075 / NVDA +0.070 / MU +0.062；已集成 `rsi2_backtest.py --vix-spike-test` 和 `alert_engine.py`

## 已完成

- [x] 项目框架搭建（目录结构、文档、配置、核心脚本）
- [x] 下载所有标的历史数据（`fetch_data.py` / `fetch_ib_data.py`）
- [x] ConfluenceStrategy 全量批量回测（`backtest_runner.py`）
- [x] 对每个标的 × 每个周期独立优化参数（ADX 阈值、ut_key、min_score）
- [x] MR + ATR Trail 策略（`mr_signals.py`, `mr_strategy.py`, `mr_backtest.py`）— 样本不足暂缓
- [x] EMA Pullback 策略（`ema_*.py`）— WR 过低，已放弃
- [x] RSI2 策略 v1 → v2（Market Regime Score + 加权 RS + Pullback Filter + 分批出场 C）
- [x] RSI2 v2 参数网格优化（全标的 × 全周期）
- [x] TSLA 专项分析（ConfluenceStrategy + RSI2 + 纯追踪出场对比）—— 天花板 0.5
- [x] NVDA 1h 结构性剔除（两套策略全网格均负）
- [x] AMZN 专项策略（20日高点回撤 + RSI 恢复）—— 最优 Sharpe 0.308，彻底剔除
- [x] SNDK / STX 基准回测（SNDK 1h Sharpe 1.51；STX 全周期 0.69-0.87）
- [x] RSI2 扩展到 MRVL/NVDA（NVDA 1d 0.867 / MRVL 1d 0.748，优于 Confluence）
- [x] Market Regime Score 加入 ConfluenceStrategy（indicators.py + strategy.py + backtest_runner.py）
- [x] MRVL/TSLA 保本止损（use_breakeven_after_tp1，strategy.py）
- [x] 整理全量回测结论到 LEARNING.md（三套策略 × 全标的 × 全周期）
- [x] 成本压力测试 + 参数邻域稳定性 + Walk-forward 验证（结论见 LEARNING.md）
- [x] VIX 数据接入 + 数据接入层抽象（`data_providers.py`）
- [x] Tastytrade 认证实现（remember-token 模式，无需重复 OTP）
- [x] GOOGL 1h RSI2 移除实盘候选（成本压力测试不达标）
- [x] alert_engine pm2 实盘部署，Telegram 推送验证（STX 信号实测成功）
- [x] RSI2 v2 成交量加分（vol_score）：回测验证 META/MSFT/GOOGL/MU 1d 各提升 +0.01~+0.05 Sharpe；已集成到 `rsi2_backtest.py` 和 `alert_engine.py`；SOXX/NVDA/MRVL 无效，未开启
- [x] RSI2 v2 VIX 急升回落（vix_spike）：MSFT +0.075 / NVDA +0.070 / MU +0.062；ETF/META/GOOGL 无效；已集成
- [x] **信号质量评分（0-10）**：Confluence = signal_pts(5) + adx_pts(2.5) + regime_pts(2.5)；RSI2 = rsi2_pts(4) + regime_pts(4) + vol_pts(1)；Telegram 标题显示 ⭐ N/10
- [x] **ETF 板块轮动扫描器**：`etf_scanner.py` + `fetch_etf_data.py`，IB 数据，45 ETF，Rotation + Reversal + Weakness 三套评分，含 VIX（IB Index 合约）
- [x] **信号去重 + 重启持久化**：`_sent_signals` dict，同一根 bar 的信号只发一次 Telegram；发送后写入 `data/.sent_signals.json`，重启后仍有效（当天记录自动保留，次日自动过期）
- [x] **PLTR 加入标的池**：RSI2 全三周期（1d Sharpe 0.863 / 1h 0.641 / 4h 0.606），Confluence 全周期为负，已加入 `config.yaml` + `alert_engine.py`（STRATEGY_MAP + RSI2_PARAMS），归入 `mega_cap` 组
- [x] **信号日志 + 复盘脚本**：`alert_engine.py` 每次发 Telegram 同步写入 `logs/signal_log.csv`（永久保留）；`signal_review.py` 读日志、拉 yfinance 价格、逐条评估 TP1/TP2/SL 命中结果及 R 倍数；支持 `--add` 手动补录历史信号
- [x] **复盘时间止损**：MAX_BARS 上限（1h=10，4h=10，1d=15），超出按收盘价时间止损（⏱）；修复做空止损 R 值符号错误（去除多余 `× -1`）
- [x] **`fetch_ib_data.py` 分组名修复**：旧 `mag7/semis/etfs` → 当前 `momentum/high_vol/storage/mega_cap/watch/pending/sector_etf/broad_etf`，含 PLTR
- [x] **`fetch_ib_data.py` 新分组补录**（2026-07-02）：ALL_SYMBOLS 加入 `watch_candidates`、`pending_high_vol`，确保新标的随默认批量拉取不遗漏
- [x] **watch_candidates 回测**（2026-07-02）：INTC/AMD/AMAT/KLAC/DELL 全周期 Confluence 回测。INTC 1h Sharpe 0.67 达标 → 升级 `watch` 组 + symbol_params；其余留 watch_candidates
- [x] **财报前警告**（2026-07-02）：`_fetch_all_earnings()` 每次扫描批量查 yfinance，7日历日内有财报的标的信号消息末尾追加 `⚠️ 财报约X交易日后，谨慎开新仓`，不阻断信号
- [x] **板块 ETF 对齐标注**（2026-07-02）：每次扫描拉 SOXX 1d 计算 MA50，半导体标的（MU/MRVL/STX/SNDK/NVDA/INTC 等）触发信号时若 SOXX < MA50 则追加 `⚠️ SOXX 弱势（< MA50），半导体板块逆风`
- [x] **VIX 结构性择时**（2026-07-02，验证无效）：+0.5 boost 对整数阈值无效，+1 boost 仅 MU +0.035 / META 变差，整体无附加价值。框架保留在 `rsi2_backtest.py --vix-structural-test`，不集成实盘
- [x] **选股排名联动标注**（2026-07-08）：`_load_screener_ranks()` 每次扫描读 `data/screener_results.csv` 最新 Top10，触发信号时追加 `📊 本周因子选股 #N`

### I — 新策略研究（优先级顺序）

- [x] **MAG7 轮动 → 实盘提醒**：`alert_engine.py` 新增 `check_mag7_rotation_signal(vix)` + `build_mag7_alert()`。每周首次扫描触发（不限周几），dedup key 用本周周一日期防重发。通知含：本周/上周持仓对比、换仓标记、VIX 分级建议（<20正常/20-25缩小/25-30减半/>30不开仓）、21天内财报警告（避免财报周卖 Put）。QQQ<200SMA 时显示空仓。pm2 启动改用 `-u` unbuffered + `--cwd` 修复工作目录问题。

#### 高性价比（有回测支撑，改动小，优先实施）

- [x] **财报前警告**（2026-07-02）：`_fetch_all_earnings()` 批量查询所有非ETF标的，7日历日内有财报则信号消息追加 `⚠️ 财报约X交易日后，谨慎开新仓`。不阻断信号，仅警示。扫描日志示例：`查询财报日期... 无近期财报`

- [x] **板块 ETF 对齐标注**（2026-07-02）：每次扫描开始时拉取 SOXX 1d，计算 MA50，SOXX < MA50 则对 `SEMI_SYMBOLS`（MU/MRVL/STX/SNDK/NVDA/INTC/AMD/AMAT/KLAC）的信号追加 `⚠️ SOXX 弱势（< MA50），半导体板块逆风`。扫描日志示例：`SOXX 1d: $599.70  MA50: $542.72  强势 ✅`

- [x] **VIX 结构性择时**（2026-07-02，已验证无效，不集成）：回测结论：
  - **+0.5 boost**：delta 全为 0.0。根本原因：`min_market_score` 是整数阈值（1/2/3），+0.5 永远无法跨越整数边界，在当前 score 结构下数学上无效。
  - **+1 boost**：MU +0.035（微弱），META 反而变差（Sharpe -0.308），其余全部 delta=0。
  - 结论：VIX < VIX_MA20 作为 score boost 对 RSI2 v2 无附加价值。代码框架已加入 `rsi2_backtest.py`（`--vix-structural-test`），不集成到 `alert_engine.py`。

#### 中性价比（逻辑扎实，需一定实现成本）

- [x] **选股排名联动标注**（2026-07-02）：`_load_screener_ranks()` 每次扫描读 `data/screener_results.csv` 最新 Top10，触发信号时追加 `📊 本周因子选股 #N`。文件不存在时静默跳过。screener_results.csv 需定期同步至 Mac Studio。

- [ ] **TP1 后追加（Pyramiding）**（优先级 4）：完整纸面状态机尚未完成。目标：TP1 触达后下一根 bar 若继续创新高，在 TP1 价位补回减掉的半仓，止损上移至 TP1。当前仅有 Telegram 人工提示，不改变任何真实仓位。

- [x] **52周高点突破**（2026-07-08完成）：`breakout_backtest.py` 新建，网格优化 36 组合。接入 `alert_engine.py`（`check_breakout_signal` + `build_breakout_alert`），`BREAKOUT_PARAMS` 含 NVDA/MU/MSFT/PLTR/TSLA/AAPL（2026-07-09 加入）。数据源从 IB 切换至 yfinance（解决 IB pacing 限制）。
  - NVDA 0.761 / MU 0.843 / PLTR 0.825 / TSLA 0.935 / MSFT 0.628 / AAPL 1.161（9笔样本少）

#### 图形形态识别（研究结论，2026-07-02）

两类形态需区分：
- **K线组合**（锤子/吞没/十字星）：TA-Lib / pandas-ta 够用
- **图形结构形态**（头肩/楔形/三角/旗形）：需基于局部高低点 + 趋势线 + 斜率 + 突破确认自己写规则

推荐库（按优先级）：
1. `BennyThadikaran/stock-pattern`：最成熟的 CLI scanner，支持 common chart patterns + harmonic patterns
2. `white07S/TradingPatternScanner`：有 PyPI 包 `tradingpattern`，支持头肩/三角/楔形/通道，含 Savitzky-Golay 去噪版头肩算法
3. `zeta-zetra/chart_patterns`：轻量 API，支持头肩/旗形/三角/pennant
4. `neurotrader888/TechnicalAnalysisAutomation`：头肩算法写得系统化（时间对称/颈线/早期/确认检测）

正确使用姿势（只做 candidate generator，不直接当信号）：
- 局部极值层 → 几何规则层 → 成交量层 → 趋势背景层 → 突破确认层 → 回测验证层
- **lookahead bias 风险**：只允许在突破颈线那根 bar 入场，不能用识别后的历史数据拟合
- 对本系统最有价值的形态：旗形/三角旗形（RSI2 回调）、上升/下降三角（Confluence 突破）
- 头肩顶/底优先级低（与 RSI2 关系弱），楔形误判多（暂缓）

- [ ] **图形形态识别**（低优先级，待高优先项完成后研究）：先用 stock-pattern 跑现有标的池验证识别质量，再考虑接入 alert_engine.py

#### 低性价比（暂缓）

- [ ] **SMH vs SOXX 配对轮动**（暂缓）：计算两者 20d/60d 相对收益差，差值超过 252d 历史 2σ 时做多领先方。需新建 `smh_soxx_backtest.py` 验证再接入。预期信号频率低（6-8 周一次），两者持仓重叠 70%，优势可能有限。

- [ ] **TSLA 4h 出场模式切换**（暂缓）：回测验证 `use_staged_tp=false` 在 4h 大幅优于 staged（Sharpe 1.29 vs 0.28，PF 3.97 vs 1.16）。但样本仅 14 笔，谨慎。待观察实盘信号质量后决定是否修改 `config.yaml`。

#### 新标的候选（已加入 config.yaml，待回测验证）

已于 2026-07-02 加入 config.yaml，分组如下：

**`watch_candidates`**（选股初筛 Top5，半导体/科技，参数适配性待验证）：

回测结果（2026-07-02，Confluence 默认参数）：

| 标的 | 1h | 4h | 1d | 结论 |
|------|----|----|-----|------|
| INTC | **0.67** ✅ | 0.11 | 0.56 | 升级 watch；1h 95笔主力 |
| AMD  | -0.75 | 0.13 | 0.52 | 留 watch_candidates |
| AMAT | -0.81 | 0.12 | 0.36 | 留 watch_candidates |
| KLAC | -0.11 | -1.08 | 0.05 | 留 watch_candidates |
| DELL | -0.07 | -0.24 | 0.26 | 留 watch_candidates |

- [x] **INTC**：1h Sharpe 0.67（95笔）≥ 0.6，已升级至 `watch`，symbol_params 已加
- [ ] **AMD**：1d Sharpe 0.52，未达 0.6，继续观察选股排名
- [ ] **AMAT**：1d Sharpe 0.36，未达标
- [ ] **KLAC**：全周期不合格（1d 0.05），不适合本策略框架
- [ ] **DELL**：全周期不合格（1d 0.26），不适合本策略框架

**`pending_high_vol`**（高波动/新兴，已回测 2026-07-09）：

回测结果（Confluence + 突破，默认参数）：

| 标的 | Confluence 1h | 4h | 1d | 突破最优 | 结论 |
|------|--------------|-----|-----|---------|------|
| RKLB | -0.74 | -0.33 | 0.75 | **0.934**（13笔） | 突破有信号，样本偏少，留 watch |
| NBIS | -2.37 | 0.10 | 0.57 | 无有效结果 | 数据不足（1.7年），暂缓 |
| IREN | **1.09** | 0.72 | -0.64 | 无有效结果 | 1h 仅11笔，不稳定，暂缓 |

- [ ] **RKLB**：突破策略有效（Sharpe 0.934），但 13 笔样本不足。继续观察至 2026 年底积累更多数据再决定接入
- [ ] **NBIS**：全策略不达标，数据仅 429 日线 bar。维持 pending，待 2 年以上数据
- [ ] **IREN**：1h Confluence 1.09 但仅 11 笔，1d 负值，强周期性需专项参数。维持 pending

### J — 轻量选股初筛（方案 A）

目标：对多个指数（NDX100 / S&P 500 / Dow 30 / Russell 2000）计算 5 个 WQ-style 因子，每周筛出 Top 20-30 进入"观察池"，再用现有 Confluence/RSI2 系统择时入场。

**核心文件**：

- [x] **`universes.py`**：各指数成分股列表统一管理，`screener.py` 和 `fetch_ib_data.py` 共用
  - DOW30（30只，硬编码）、NDX100（~85只，硬编码）、SP500（~360只，硬编码）
  - Russell 2000（~2200只，从 `data/russell2000_tickers.txt` 动态加载）
  - `get_universe(name)` → `(tickers, benchmark_etf, label)`
  - 每年6月 Russell 重组后重跑 `fetch_russell2000_tickers.py` 更新

- [x] **`fetch_russell2000_tickers.py`**：从 NASDAQ 官方 symbol 目录构建 Russell 2000 近似成分列表
  - 数据源：`nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt`（官方每日更新，免费）
  - 过滤：纯字母 ticker + 排除 ETF/权证/优先股/单位 + 排除已知大型股
  - 输出：`data/russell2000_tickers.txt`（约 2200 只普通股）

- [x] **`screener.py`**：多指数周频因子选股，`--universe ndx100/sp500/dow30/russell2000/all`
  - **数据优先级**：`data/{SYM}_1d.csv`（IB数据）→ yfinance fallback（IB缺数据时）
  - **5个因子**（仅用 OHLCV）：
    - F1 跳期动量：`close[-6]/close[-66]-1`（60日，跳过最近5日避免反转）
    - F2 相对强度：`0.4×RS20 + 0.6×RS60 vs 基准ETF`（QQQ/SPY/DIA/IWM）
    - F3 量价背离（Alpha#12）：`sign(Δvol)×(-Δclose)` 20日均值
    - F4 风险调整动量：`ret_20 / std(daily_ret, 20)`（类 Sharpe）
    - F5 接近52周高点：`close / rolling_max(252)`
  - z-score 标准化后等权合成，全域排名取 Top N
  - `--top N`（默认20）+ `--telegram` + `--no-save` 参数
  - 结果追加写入 `data/screener_results.csv`（含 universe 列）
  - **交易参考价位**（每只股票输出）：
    - 入场：当前价（立即追）/ 等回踩（见支撑位）
    - TP1 = 入场价 + 2.0×ATR14；TP2 = +3.5×ATR14；SL = -1.5×ATR14
    - **多级别支撑位**：[大] MA200 / 季低（60日Low）；[中] MA50；[小] MA20 / 1M低 / MA10 / 2W低
    - 只显示低于当前价的支撑（高于当前价的为阻力，不显示）
    - Telegram 每只标的三行：综合得分+标签 / TP1·TP2·SL / 支撑位分级

- [x] **`fetch_ib_data.py`**：新增 `--universe ndx100/sp500/dow30/russell2000`
  - 仅拉日线（screener 不需要 1h/4h），含基准 ETF（QQQ/SPY/DIA/IWM）
  - IB pacing 说明：串行最优（并行会叠加请求数超过 60次/10分钟限制）

**IB 数据状态**（2026-07-01）：
- [x] NDX100：~86只，已完成
- [x] SP500：364只，已完成（logs/fetch_screener.log）
- [x] Russell 2000：~2187只，已完成（logs/fetch_screener_russell.log，clientId=3）

**首次运行记录**（2026-07-01）：NDX/SP500/Russell 2000 三池选股已全部跑通并推送 Telegram，支撑位输出正常。

**标准工作流**（每周一）：
```bash
# 1. 更新数据（Mac Studio，IB Gateway 须开启，clientId=3）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py --universe ndx100 --port 4001"   # ~9分钟
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py --universe sp500 --port 4001"    # ~36分钟
# Russell 2000 数据更新（每周可选，或仅每年6月重组后）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py --universe russell2000 --port 4001"  # ~3.6小时

# 2. 运行选股并推送 Telegram（Mac Studio 上直接跑，无需同步数据到本机）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 screener.py --universe ndx100    --top 15 --telegram"
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 screener.py --universe sp500     --top 15 --telegram"
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 screener.py --universe russell2000 --top 15 --telegram"

# 3.（可选）同步数据到本机查看
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ data/

# Russell 2000 成分更新（每年 6 月重组后）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_russell2000_tickers.py"
```

**选股输出说明**（每只股票）：
- 综合得分 + 标签（动量↑ / RS强 / 近高点）
- 入场：当前价（追强）/ 等回踩支撑
- 目标：TP1（+2ATR）、TP2（+3.5ATR）、SL（-1.5ATR）
- 支撑分级：[大] MA200/季低 → [中] MA50 → [小] MA20/1M低/MA10/2W低（只显示低于当前价的）
- ATR% 衡量波动：>8% 需缩小仓位

**Russell 2000 使用提示**：小票噪声大，优先看市值较大（价格 >$20）、ATR% < 8% 的标的；低价股高 ATR% 排名靠前多为流动性噪声，参考价值低。

**IB pacing 限制**：60次请求/10分钟（gateway全局）。串行 6s/次 ≈ 10次/分钟略超但IB有容忍；
并行两进程会叠加到 20次/分钟 → 大量 Error 162 取消，总耗时反而更长（需改 20s/次 → 12小时）。

- [ ] **参考资源**：
  - [WorldQuant 101 Formulaic Alphas](https://github.com/yli188/WorldQuant_alpha101_code)：因子公式参考
  - [alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded)：因子 IC / 衰减分析工具

### K — 复盘闭环与策略进化机制（2026-07-18 制定）

**背景**：本项目无实盘下单，`logs/signal_log.csv` + `signal_review.py` 是唯一的真实账本，是复盘和进化的核心资产。当前复盘口径与实盘出场逻辑不一致，导致统计结果失真，无法可靠驱动策略升降级决策。以下按 Phase 1→5 顺序实施，前一阶段是后一阶段的地基。

#### Phase 1（优先级最高，零风险，只改 signal_review.py）— 复盘保真度（已完成）

- [x] **复盘状态机对齐实盘出场逻辑**：新增 `review_core.py`，按 close-driven 实盘规则回放 Confluence 34%/33%/33% staged TP、utTS/sslExit，以及 RSI2 ATR trail/RSI 半仓/时间止损，输出加权 R。
- [x] **同 bar 内 SL/TP 判定精细化**：记录 Open 跳空的确定顺序；OHLC 双触达时明确写入不可判序标记，而非伪装成 SL 优先的确定结果。
- [x] **Quality 分数校准**：`signal_review.py` 输出 0-4/5-7/8-10 三桶的已决胜率和均 R。
- [x] **复盘自动化**：`stock-weekly-review` 由 PM2 每周日 18:15 触发，执行 90 天复盘、更新监控并推送 Telegram 摘要；保留 `run_weekly_review.sh` 供手动执行。

#### Phase 2 — 影子信号流（Shadow Signals，已完成）

- [x] **框架**：影子记录统一以 `_shadow` 后缀写入同一账本，不发送 Telegram，保留 source strategy 和参数快照。
- [x] **候选1：TSLA 4h 纯 sslExit 追踪出场**：`TSLA_SSLTrail_shadow`。
- [x] **候选2：MRVL 1h 出场放宽**：`MRVL_WideExit_shadow`（TP2 再放宽 1 ATR）。
- [x] **候选3：RKLB 突破策略转正观察**：`RKLB_Breakout_shadow`。
- [x] **候选4：RSI2 加 IBS 过滤**：`RSI2_IBS_shadow`，仅 IBS < 0.2 记录。

#### Phase 3 — Paper Portfolio 虚拟持仓状态机（已实际运行，Pyramiding 仍为提示阶段）

- [x] **虚拟持仓账本**：`paper_portfolio.py` 已实际运行；2026-07-23 核实 `data/.paper_positions.json` 存在，equity 100071.42，16 笔未平仓虚拟持仓（TSLA/AAPL/META/SPY/QQQ/AMZN/INTC 等）；全程无下单接口，纯记录回放。
- [x] **板块暴露警示**：`risk_warnings()` 已接入 `alert_engine.py`（第777行）并在 `open_position()` 时调用；核实当前持仓池中同标的重复开仓（如 TSLA 1h、AAPL 1d、QQQ 1d 均出现≥2次）已触发单标的风险提示路径；半导体板块暴露（`SECTOR_LIMIT=0.45`）逻辑就绪，但当前 16 笔持仓中暂无 `SEMIS` 集合标的，尚未实际触发该分支，需等待半导体信号出现后复核。
- [x] **单标的风险敞口提示**：同上，`same_symbol >= 1` 分支已由真实重复持仓触发验证。
- [ ] **TP1 后 Pyramiding 提示**：`alert_engine.py` 第1202-1203行已接入，`paper_update()` 产生 `pyramid` 事件时推送 Telegram 提示（"仅提示，不执行任何下单"），但**不改变虚拟仓位数量**；完整 Pyramiding 状态机（补回半仓、止损上移至TP1）仍未实现，此项保持未完成。
- [x] **虚拟净值曲线**：`logs/paper_equity.csv` 已生成并持续更新，2026-07-20 至 2026-07-23 共 13 条平仓记录，equity 从 100000.0 → 100071.42。

#### Phase 4 — 衰减监控与市场状态路由（已完成）

- [x] **策略衰减红黄灯**：`--monitor` 维护 `logs/review_history.csv`，最近 20 笔以 0R 中性基线计算 z 分数，样本稳定后可用回测期望表替换基线。
- [x] **多周期共振加分**：同一轮扫描已触发的同标的信号 quality +1 并追加共振标记。
- [x] **市场状态 × 策略路由**：主扫描按 ETF 扫描器同定义计算 Risk-On/Neutral/Risk-Off；Risk-On chop 降趋势类质量，Risk-Off 仅保留 ETF 信号。
- [x] **VIX 分级仓位建议推广**：已加入 Confluence/RSI2/breakout 消息。

#### Phase 5（样本 ≥150-200 条已决信号后，避免过拟合）— Meta-labeling（框架完成，严格等待门槛）

- [x] **信号质量二级过滤**：新增依赖最小的逻辑回归训练器与 `--train-meta`。少于 150 条已决信号时拒绝训练；达到门槛后保存模型并仅输出仓位建议，不自动过滤信号。

#### 明确不做（已有结论，不重复投入）

- PEAD / AMZN 专项策略 / EMA Pullback：已证伪，见 LEARNING.md
- 图形形态识别提前介入：高实现成本 + lookahead bias 风险，维持 TASK.md 原有低优先级
- MR 策略重启：全周期 N<50，等结构性改善再议

**落地顺序**：Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5（样本积累后）。Phase 1-2 是地基（可信复盘数据 + 零成本实验通道），之后任何新策略想法走"影子流 → 复盘对比 → 转正"标准路径。

### L — 历史回填与样本积累（2026-07-18 制定）

**目标**：不等待未来实时信号，使用可追溯的历史 OHLCV 回放来验证状态机、积累影子策略样本和运行纸面组合。实时账本与历史模拟账本必须严格隔离。

#### 数据与账本边界

- [x] **文档状态修正**：I 节 Pyramiding 保持未完成；K / Phase 3 改为“代码存在，未完成运行验证”，不得将人工提示或未触发的实现等同于完成。
- [x] **历史数据覆盖审计**：`data_audit.py --write` 输出全部主策略及影子候选的 `symbol × tf` CSV 起止时间、缺口与数据来源报告。2026-07-18 初审生成 48 个 IB 原始周期补拉计划；IB 的 US HMDS 断连后，已通过 yfinance 合并补拉全部 72 个 `symbol × tf` 文件。复审：全部 `fresh`，覆盖至 2026-07-17，来源 `yfinance`。
- [x] **IB 历史数据补拉**：2026-07-24 04:55 用户明确批准后，通过 `quantrift_index_future/restart_gateway.sh`（SIGKILL + launchd `com.quantrift.ibc.plist` KeepAlive 自动拉起）重启 Gateway；重启触发了 Second Factor Authentication，由用户在手机 IBKR App 上批准后 05:02 登录完成，4001 端口恢复监听。恢复序列：① NVDA 1d 单标的验证成功（2512行）② `fetch_ib_data.py --merge` 全量补拉 42 次请求 0 失败 ③ `data_audit.py --write` 复审：全部 `fresh`，来源已从 `yfinance` 切回 `ib`，覆盖至 2026-07-23，需 IB 补拉 0 项 ④ `historical_backfill.py --write` 重跑：7302 候选信号，9986 条已决，2135 条影子。同机 8 个期货 bot（`ib-bot*`）重连期间 PID/重启计数未变化，未触发 crash-restart。
- [x] **yfinance 历史回补**：IB HMDS 断连期间，`fetch_data.py --merge` 已为全部 24 个配置标的刷新 1d、1h 与 4h（由 1h 重采样），共 72 个文件；保留旧历史、覆盖重复 bar、写入 `data/.data_sources.json`，并为每次请求设置 20 秒上限。
- [x] **ETF 扫描器日线回补**：该扫描器的 47 个 ETF/基准不属于 `fetch_ib_data.py` 的 24 标的池，需单独用 `fetch_etf_data.py` 拉取。2026-07-24 IB 恢复后执行：50 次请求（47 ETF + SPY/QQQ + VIX）全部成功、0 失败；`XLK`/`XBI` 等此前停留在 2026-06-17/18 的文件均已刷新至 2026-07-23（VIX 至 07-24）。

#### 历史回放

- [x] **独立历史信号账本**：`historical_backfill.py --write` 已生成 `logs/backfill_signal_log.csv`；逐 bar 回放 Confluence、RSI2 与 Breakout，不写入实时 `logs/signal_log.csv`。已在 yfinance 数据刷新后重跑，当前 6,285 条候选，数据末端为 2026-07-17。
- [x] **影子策略历史回填**：TSLA 4h sslExit、MRVL 1h 宽出场、RKLB Breakout、RSI2 + IBS 已分别写入独立影子记录。最新回放包含 1,813 条影子候选；仅作为历史模拟，不能替代实时样本。
- [x] **历史虚拟组合回填**：`historical_backfill.py --write` 已输出 `logs/backfill_paper_equity.csv`（9986 行事件，2016-09 至 2026-07-23），逐条记录 `symbol_weight`/`semi_exposure`/`equity_after`/`drawdown_pct`。⚠️ 已知问题：按固定 `risk_pct=0.75%` 复利计算，10 年跨度权益从 100000 涨到约 760 万，属于长周期复利模拟的预期数值膨胀（非 bug，但不能直接当作真实收益率参考），回撤统计（如 -56%）需要结合这一点解读；未做仓位上限/权益重置处理。

#### 复盘与转正门槛

- [x] **复盘来源分层**：实时日志新增 `source=live/shadow`；历史回填固定为 `historical_backfill` 并隔离存储；Meta-label 默认仅用 `live` 已决样本。
- [ ] **Pyramiding 完整验证**：明确仅 Telegram 人工提示或完整纸面加仓状态；若后者，TP1 后创新高时补回半仓、保护止损移至 TP1，并由历史回放验证。
- [ ] **持续收集复核**：确认新实时信号可创建 `data/.paper_positions.json` 与 `logs/paper_equity.csv`；定期审查影子样本数量，达到统计门槛后才转正。

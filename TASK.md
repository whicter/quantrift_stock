# TASK.md — quantrift_stock

## 进行中

无

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
- [ ] **IB 历史数据补拉**：现有 CSV 不足时由 IB 补拉；1h 约两年、4h 由 1h 重采样、1d 更长历史。保留拉取时间、来源与合并记录；IB 无法覆盖的缺口才使用 yfinance，并标记来源。已确认阻塞：Gateway API 连接、服务器时间和 NVDA 合约解析都成功；Gateway 返回 `2105: HMDS data farm connection is broken: ushmds`，NVDA 5 日历史请求超时无 bar。此为 US 历史数据 farm 断连；下一项待验证的恢复动作是在不影响期货 bot 的维护窗口重启 Gateway，单标的验证成功后再执行 `fetch_ib_data.py --merge`。
- [x] **yfinance 历史回补**：IB HMDS 断连期间，`fetch_data.py --merge` 已为全部 24 个配置标的刷新 1d、1h 与 4h（由 1h 重采样），共 72 个文件；保留旧历史、覆盖重复 bar、写入 `data/.data_sources.json`，并为每次请求设置 20 秒上限。
- [ ] **ETF 扫描器日线回补**：该扫描器的 47 个 ETF/基准不属于上述 72 文件审计范围。2026-07-18 检查：`SMH`、`SOXX`、`SPY`、`QQQ` 已至 2026-07-17；`QTUM`、`UFO` 停在 2026-07-01；其余 41 个 ETF 停在 2026-06-18。共 43 个 ETF 日线待更新；IB HMDS 未恢复时需增加并运行 yfinance 合并回补。

#### 历史回放

- [x] **独立历史信号账本**：`historical_backfill.py --write` 已生成 `logs/backfill_signal_log.csv`；逐 bar 回放 Confluence、RSI2 与 Breakout，不写入实时 `logs/signal_log.csv`。已在 yfinance 数据刷新后重跑，当前 6,285 条候选，数据末端为 2026-07-17。
- [x] **影子策略历史回填**：TSLA 4h sslExit、MRVL 1h 宽出场、RKLB Breakout、RSI2 + IBS 已分别写入独立影子记录。最新回放包含 1,813 条影子候选；仅作为历史模拟，不能替代实时样本。
- [ ] **历史虚拟组合回填**：按回填信号时间顺序模拟开仓、TP1、止损、追踪出场、纸面 Pyramiding，输出 `logs/backfill_paper_equity.csv`，统计半导体暴露、单标的风险、净值与回撤。

#### 复盘与转正门槛

- [x] **复盘来源分层**：实时日志新增 `source=live/shadow`；历史回填固定为 `historical_backfill` 并隔离存储；Meta-label 默认仅用 `live` 已决样本。
- [ ] **Pyramiding 完整验证**：明确仅 Telegram 人工提示或完整纸面加仓状态；若后者，TP1 后创新高时补回半仓、保护止损移至 TP1，并由历史回放验证。
- [ ] **持续收集复核**：确认新实时信号可创建 `data/.paper_positions.json` 与 `logs/paper_equity.csv`；定期审查影子样本数量，达到统计门槛后才转正。

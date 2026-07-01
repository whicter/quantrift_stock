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

### I — 新策略研究（优先级顺序）

- [x] **MAG7 轮动 → 实盘提醒**：`alert_engine.py` 新增 `check_mag7_rotation_signal(vix)` + `build_mag7_alert()`。每周首次扫描触发（不限周几），dedup key 用本周周一日期防重发。通知含：本周/上周持仓对比、换仓标记、VIX 分级建议（<20正常/20-25缩小/25-30减半/>30不开仓）、21天内财报警告（避免财报周卖 Put）。QQQ<200SMA 时显示空仓。pm2 启动改用 `-u` unbuffered + `--cwd` 修复工作目录问题。

- [ ] **VIX 结构性择时**（优先级 2）：现有逻辑仅判断 VIX > 20（硬阈值）和 spike 回落。扩展为：每轮扫描计算 VIX 20日均线，`vix < vix_ma20` 作为 +0.5 score boost（不做硬 gate，避免错过 spike 后最佳 RSI2 入场）。需同步验证 `rsi2_backtest.py` + `backtest_runner.py`（加 `vix_structural` 参数）。

- [ ] **52周高点突破**（优先级 3）：`indicators.py` 加 `high_252 = df["High"].rolling(252, min_periods=200).max()`，信号为 `close > high_252.shift(1)` 且 `isHighVol`。写 `check_breakout_signal()` 接入 `alert_engine.py`，仅日线。**须先在 `rsi2_backtest.py` / `backtest_runner.py` 回测验证再上实盘**，半导体股假突破比例高，需 2 日收盘确认逻辑。

- [ ] **SMH vs SOXX 配对轮动**（优先级 4，暂缓）：计算两者 20d/60d 相对收益差，差值超过 252d 历史 2σ 时做多领先方。需新建 `smh_soxx_backtest.py` 验证再接入。预期信号频率低（6-8 周一次），两者持仓重叠 70%，优势可能有限。

- [ ] **TSLA 4h 出场模式切换**：回测验证 `use_staged_tp=false` 在 4h 大幅优于 staged（Sharpe 1.29 vs 0.28，PF 3.97 vs 1.16）。但样本仅 14 笔，谨慎。待观察实盘信号质量后决定是否修改 `config.yaml`。

### J — 轻量选股初筛（方案 A）

目标：对纳斯达克 100 计算 5 个 WQ-style 因子，每周筛出 Top 20 进入"观察池"，再用现有 Confluence/RSI2 系统择时入场。不引入 QLib，完全复用现有基础设施。

- [x] **`screener.py`**：5因子选股初筛，yfinance 1Y 日线批量下载，NDX 100 全量计算：
  - **F1 跳期动量**：`close[-6]/close[-66]-1`（60日收益跳过最近5日，避免短期反转）
  - **F2 相对强度**：`0.4×RS20 + 0.6×RS60 vs QQQ`（复用 etf_scanner.py 模式）
  - **F3 量价背离（Alpha#12）**：`sign(Δvol)×(-Δclose)` 20日均值（上涨放量=积累信号）
  - **F4 风险调整动量**：`ret_20 / std(daily_ret, 20)`（单位波动率收益，类 Sharpe）
  - **F5 接近52周高点**：`close / rolling_max(252)`（突破强度）
  - 5因子各自 z-score 标准化后等权相加，全域排名取 Top N
  - `--top N`（默认20）+ `--telegram` 参数，结果追加写入 `data/screener_results.csv`

- [ ] **与现有系统对接**（可选，人工决策优先）：Top 20 标的供人工参考，不自动写入 config.yaml

**用法**：
```bash
# Mac Studio 运行（无需 IB，yfinance 直接下载）
python3.11 screener.py                   # 终端输出 Top 20
python3.11 screener.py --top 30          # Top 30
python3.11 screener.py --telegram        # 推送 Telegram

# 可选：每周一 5:30 AM PDT 定时运行
# 30 5 * * 1 cd /Users/congrenhan/Documents/quantrift_stock && python3.11 screener.py --telegram >> logs/screener.log 2>&1
```

- [ ] **参考资源**：
  - [WorldQuant 101 Formulaic Alphas](https://github.com/yli188/WorldQuant_alpha101_code)：因子公式参考
  - [alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded)：因子 IC / 衰减分析工具

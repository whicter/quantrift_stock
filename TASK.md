# TASK.md — quantrift_stock

## 进行中

- [ ] 实现 `alert_engine.py` IB 数据接入（`reqHistoricalData`）
- [ ] 告警引擎整合到 pm2（`pm2 start alert_engine.py --name stock-alert`）
- [ ] Telegram 告警测试

## 待完成（优先级顺序）

### A — RSI2 策略优化（主力策略，最高优先级）

- [ ] **Market Regime Score**：替换 QQQ > 100SMA 单条件，改为 6 维打分（QQQ > 100/200SMA、20SMA>50SMA、5d 收益、VIX、20d 低点），MarketScore >= 2 才开仓
- [ ] **Pullback Location Filter**：入场条件加 `close > 100SMA` AND `close < 20SMA`，避免高位假回调
- [ ] **加权 RS 过滤**：RS_Score = 0.4×RS_20 + 0.6×RS_60，替换单一 60d 收益；SOXX/SMH 改用 close > 100SMA
- [ ] **分批出场模型对比**：回测 A/B/C/D 四种出场，重点测 C（RSI2>80 出半 + ATR trail 出剩余）
- [ ] **时间止损换算**：4h hold 改为 12-24 bars（≈ 6-12 交易日），与 1d hold 10-15 对齐
- [ ] 优化完成后重跑 MSFT/GOOGL/META/SOXX/SMH/QQQ 对比 v1 和 v2

### C — MR 策略可信度核查（第二优先级）

- [ ] 拉取 SOXX/SMH/QQQ MR 策略的 trade count、max drawdown、平均持仓天数、最大单笔亏损
- [ ] 按年分解 PnL（确认盈利是否集中在少数年份）
- [ ] 如果笔数 < 50，重新评估 PF=5.17 可信度
- [ ] **z-score 波动率自适应**：ATR percentile > 70 时用 z ≤ -1.5，否则 z ≤ -0.9
- [ ] **加 close > 100SMA**：替换仅 200SMA 的趋势过滤
- [ ] **ADX slope 检查**：ADX < 25 AND 没有连续 3 根上升

### B — 标的分类重构（第三优先级）

- [ ] AMZN 从主策略池删除（Sharpe 上限 0.27，已确认无效）
- [ ] TSLA 单独处理（不与 NVDA/MU 混桶）
- [ ] AAPL 降权（Sharpe 0.35，边际效益低）
- [ ] 更新 `config.yaml` 标的分组
- [ ] 重新对新标的池（NVDA/MU/MRVL, MSFT/GOOGL/META, SOXX/SMH/QQQ）跑完整优化

### 策略集成（长期）

- [ ] 将 RSI2 策略（v2）集成到 `alert_engine.py`
- [ ] 将 MR+ATR Trail 策略集成到 `alert_engine.py`
- [ ] Market Regime Score 实时计算模块

### 数据与研究

- [ ] **VIX 数据接入**：用于 Market Regime Score（`^VIX` via yfinance 可直接拉取）
- [ ] **PEAD（财报后漂移）**：接入财报日期 + EPS 超预期数据（yfinance earnings calendar 或 EODHD API）
- [ ] **MAG7 周频相对强弱轮动**：按 60 日收益排名，持最强 2-3 只，每周调仓
- [ ] **AMZN 专项**：测试「距 20 日高点回撤 5-10% + RSI 40-55」进场方式
- [ ] 确认 SNDK 上市日期（2025-02-20 重新上市，历史数据有限）

### ConfluenceStrategy 降维（低优先级）

- [ ] 把 6 分项降为 3 层（趋势必须 + 触发信号 + 加分项，见 LEARNING.md）
- [ ] CD 背离降权，不纳入主评分

### 风控（未来）

- [ ] 多标的同时发信号时的优先级规则
- [ ] 连接 IB 查账户可用资金，不足时暂停发告警

## 已完成

- [x] 项目框架搭建（目录结构、文档、配置、核心脚本）
- [x] 下载所有标的历史数据（`fetch_data.py` / `fetch_ib_data.py`）
- [x] ConfluenceStrategy 全量批量回测（`backtest_runner.py`）
- [x] 对每个标的 × 每个周期独立优化参数（ADX 阈值、ut_key、min_score）
- [x] MR + ATR Trail 策略（`mr_signals.py`, `mr_strategy.py`, `mr_backtest.py`）
- [x] EMA Pullback 策略（`ema_*.py`）— WR 过低，已放弃
- [x] RSI2 策略 v1（`rsi2_backtest.py`）含 QQQ 过滤 + 相对强度
- [x] RSI2 v1 参数网格优化（MSFT 4h Sharpe=1.13，SOXX 1h Sharpe=1.14）
- [x] 整理回测结论到 LEARNING.md（三类品种 × 三套策略）
- [x] 更新 README.md、TASK.md 文档

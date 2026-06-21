# TASK.md — quantrift_stock

## 进行中

- [ ] 实现 `alert_engine.py` IB 数据接入（`reqHistoricalData`）
- [ ] 告警引擎整合到 pm2（`pm2 start alert_engine.py --name stock-alert`）
- [ ] Telegram 告警测试

## 待完成

### 策略集成
- [ ] 将 RSI2 策略集成到 `alert_engine.py`（目前只有 ConfluenceStrategy）
- [ ] SOXX/SMH 的 RSI2 信号关掉 `use_rs_filter`（行业 ETF 无需跑赢 QQQ）
- [ ] 将 MR+ATR Trail 策略集成到 `alert_engine.py`（用于 ETF 品种）

### 数据与策略研究
- [ ] **PEAD（财报后漂移）**：接入财报日期 + EPS 超预期数据（yfinance earnings calendar 或 EODHD API）
- [ ] **MAG7 周频相对强弱轮动**：按 60 日收益排名，持最强 2-3 只，每周调仓
- [ ] **AMZN 专项**：测试「距 20 日高点回撤 5-10% + RSI 40-55」进场方式（区别于 BB 下轨）

### 数据
- [ ] 确认 SNDK 上市日期（2025-02-20 重新上市，历史数据有限）
- [ ] 4h 数据：确认重采样逻辑正确（yfinance 不直接提供 4h）

### 风控（未来）
- [ ] 多标的同时发信号时的优先级规则
- [ ] 连接 IB 查账户可用资金，不足时暂停发告警

## 已完成

- [x] 项目框架搭建（目录结构、文档、配置、核心脚本）
- [x] 下载所有标的历史数据（`fetch_data.py` / `fetch_ib_data.py`）
- [x] ConfluenceStrategy 全量批量回测（`backtest_runner.py`）
- [x] 对每个标的 × 每个周期独立优化参数（ADX 阈值、ut_key、min_score）
- [x] MR + ATR Trail 策略（`mr_signals.py`, `mr_strategy.py`, `mr_backtest.py`）
- [x] EMA Pullback 策略（`ema_signals.py`, `ema_strategy.py`, `ema_backtest.py`）— WR 过低，已放弃
- [x] RSI2 策略（`rsi2_backtest.py`）含 QQQ 市场过滤 + 相对强度过滤
- [x] RSI2 策略参数网格优化（MSFT 4h Sharpe=1.13，SOXX 1h Sharpe=1.14）
- [x] 整理各标的回测结论到 `LEARNING.md`（三类品种 × 三套策略）

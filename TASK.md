# TASK.md — quantrift_stock

## 进行中

- [ ] 下载所有标的历史数据（`fetch_data.py`）
- [ ] 全量批量回测（`backtest_runner.py --all`）
- [ ] 整理各标的回测结论到 `LEARNING.md`

## 待完成

### 核心功能
- [ ] 对每个标的 × 每个周期独立优化参数（ADX阈值、ut_key、min_score）
- [ ] 实现 `alert_engine.py` IB 数据接入（`reqHistoricalData`）
- [ ] 告警引擎整合到 pm2（`pm2 start alert_engine.py --name stock-alert`）
- [ ] Telegram 告警测试

### 数据
- [ ] 4h 数据从 1h 重采样（yfinance 不直接提供 4h）
- [ ] 确认 SNDK 上市日期（2025-02-20 重新上市，历史数据有限）

### 优化
- [ ] 找出各标的最优参数组合（重点：ADX、ut_key、min_score）
- [ ] ETF（QQQ/SPY/SOXX/SMH）与个股参数是否需要分开调优

### 风控（未来）
- [ ] 多标的同时发信号时的优先级规则
- [ ] 连接 IB 查账户可用资金，不足时暂停发告警

## 已完成

- [x] 项目框架搭建（目录结构、文档、配置、核心脚本）

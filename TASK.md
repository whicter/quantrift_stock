# TASK.md — quantrift_stock

## 进行中

- [ ] 告警引擎整合到 pm2（`pm2 start ecosystem.config.js`，需先连 IB Gateway）
- [x] Telegram 告警测试 ✅（token + chat_id 已配置，测试消息发送成功）

## 待完成（优先级顺序）

### A — alert_engine 剩余功能

- [x] RSI2 v2 集成到 `alert_engine.py`
- [x] ConfluenceStrategy 告警整合（MU/MRVL/SNDK/STX）
- [x] ALL_SYMBOLS 修复（旧字段 → 新分组名）
- [x] Market Regime Score 实时计算（QQQ bar + VIX）
- [ ] 同一标的多信号去重规则（MU 1h Confluence 和 MU 1d RSI2 同时触发时的优先级）

### B — 数据接入

- [x] **VIX 数据接入**：`data_providers.py` YFinanceProvider，`^VIX` yfinance，15 分钟延时，已集成到 alert_engine
- [x] **数据接入层抽象**：`data_providers.py` MarketDataProvider 基类，支持 yfinance / tastytrade（占位）/ IB（占位），`config.yaml` 一行切换
- [ ] 确认 SNDK 历史数据范围（2025-02-20 重新上市，1h 回测数据是否足够）
- [x] **Tastytrade VIX 接入**：`TastytradeProvider.fetch_vix()` 实现完成。tastytrade REST API 无直接 VIX 指数价格端点（需 DXLink websocket），内部复用 YFinanceProvider（^VIX，15min延时，对日线 Regime 判断无影响）。remember-token 已写入 `.env`，后续无需重新登录。

### C — 参数稳定性验证（已完成）

- [x] **成本压力测试**：MU/SNDK 1h 全段合格；MRVL 1h 10bps 内合格；GOOGL 1h RSI2 成本敏感，移除实盘候选
- [x] **参数邻域稳定性**：SOXX/META/GOOGL 1d Top-5 spread < 0.09，全部稳定
- [x] **Walk-forward 验证**：8/9 RSI2 1d 通过，无过拟合；MSFT 测试期 N 不足（信号稀少，非过拟合）

### D — 风控层（上线前）

- [ ] 同标的最大风险敞口：单标的 max 0.75% equity
- [ ] 半导体总暴露上限：SOXX + SMH + MU + MRVL + NVDA + SNDK + STX ≤ 45%
- [x] Market Regime Score 加入告警通知（Confluence + RSI2 两种格式均已加 Regime 行，含 VIX 值）
- [x] 多标的多信号处理：每条信号独立发送，消息标题注明标的/周期/策略，无需代码层过滤

### E — MR 策略（暂缓）

- [ ] MR 策略全部时间框架笔数 < 50，暂停使用
- [ ] 如需重启：z-score 波动率自适应 + close > 100SMA + ADX slope 检查

### F — 研究（低优先级）

- [ ] **PEAD（财报后漂移）**：财报日期 + EPS 超预期数据（yfinance earnings calendar）
- [ ] **MAG7 周频相对强弱轮动**：按 60 日收益排名，持最强 2-3 只，每周调仓
- [ ] ConfluenceStrategy 降维：6 分项降为 3 层（趋势必须 + 触发信号 + 加分项）

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
- [x] VIX 数据接入（`data_providers.py` YFinanceProvider，已集成到 alert_engine Market Regime Score）
- [x] 数据接入层抽象（`data_providers.py`，支持多 provider 扩展，凭证用 `.env`）
- [x] GOOGL 1h RSI2 移除实盘候选（成本压力测试不达标）

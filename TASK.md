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
- [ ] 单标的最大风险敞口（0.75% equity）：需持仓状态，跳过（人工自律）
- [ ] 半导体总暴露上限（≤ 45%）：同上，跳过

### E — 部署（已完成）

- [x] **Telegram 配置**：token + chat_id 已写入 `.env`，测试消息发送成功
- [x] **pm2 集成**：`stock-alert` 以 `/bin/bash -c python3.11 alert_engine.py --port 4001` 方式启动，与 `ib-bot` 模式一致，`pm2 save` 已保存
- [x] **`restart_engine.sh`**：`PATH=/opt/homebrew/bin:$PATH pm2 restart stock-alert`
- [x] **实盘验证**：2026-06-21 20:03 ET 扫描 15 个标的，STX 4h + 1d 做多信号触发并推送 Telegram ✅

### F — MR 策略（暂缓）

- [ ] MR 策略全部时间框架笔数 < 50，暂停使用
- [ ] 如需重启：z-score 波动率自适应 + close > 100SMA + ADX slope 检查

### G — 研究（低优先级）

- [ ] **PEAD（财报后漂移）**：财报日期 + EPS 超预期数据（yfinance earnings calendar）
- [ ] **MAG7 周频相对强弱轮动**：按 60 日收益排名，持最强 2-3 只，每周调仓
- [ ] ConfluenceStrategy 降维：6 分项降为 3 层（趋势必须 + 触发信号 + 加分项）
- [ ] **VIX 急升回落抄底**：VIX spike → 回落 + RSI2 超卖，作为第二抄底指标（回测待做）

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

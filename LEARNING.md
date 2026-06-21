# LEARNING.md — 回测观察与经验

> 持续更新。每次回测后记录关键发现，用于指导参数优化和策略改进。

---

## 核心结论（2025-06）

### 品种分类

经过多轮策略测试，15 个标的分为三类，需要不同的策略：

| 类别 | 标的 | 适配策略 | 原因 |
|------|------|----------|------|
| 高 beta 动量股 | NVDA, TSLA, SNDK, MU, STX, MRVL | ConfluenceStrategy | 高 ADX、急涨急跌，UTBot + SSL 信号质量高 |
| 大市值慢牛股 | MSFT, GOOGL, META, AAPL, AMZN | RSI2（日线/4h） | 趋势平稳，RSI14 极少超卖，RSI2 在上升趋势内频繁触底 |
| 宽基 ETF | SOXX, SMH, QQQ, SPY | RSI2 + MR×ATR | 适合两套策略，RSI2 信号最多，MR+ATR 胜率更高 |

### 策略演进过程（重要）

1. **ConfluenceStrategy 在大市值股失败**：MSFT/AMZN/GOOGL 日内 ADX 长期偏低，UTBot + SSL 的动量信号在慢牛行情中几乎不触发，或在 5-10% 小回调中频繁产生假多空信号。
2. **纯 MR（中轨止盈）WR 高但 RR 低**：BB 下轨 + RSI < 40 进场有 75-84% WR，但到中轨止盈限制了 RR（0.8x），捕捉不到趋势续涨。
3. **EMA Pullback（21 EMA 回踩）WR 只有 28-43%**：进场过早，价格触及 21 EMA 但回调未完，易被止损出场。
4. **RSI2 策略解决了 MSFT/GOOGL 信号稀少问题**：2 周期 RSI 对连续下跌极度敏感，在上升趋势内 RSI2 < 5 每年出现 40-60 次（RSI14 < 40 只有 5-15 次）。配合 QQQ 市场过滤 + 相对强度，WR 稳定在 60-73%。

### 关键规律

- **1h 在大市值股基本无效**：RSI2 在 1h 噪声过大，大部分 Sharpe 为负。4h 和 1d 是可用周期。
- **exit=80（RSI2）比 exit=70 好**：让反弹跑足再出场，RR 明显改善。
- **QQQ 过滤 + 相对强度显著改善 MSFT/GOOGL/AMZN**：只在个股跑赢大盘且 QQQ 在 100 SMA 上方时入场，过滤掉弱势阶段的假信号。
- **SOXX/SMH 关掉 RS 过滤更好**：行业 ETF 有时相对 QQQ 弱但本身仍有好信号。
- **AMZN 是最难处理的标的**：任何策略优化后 Sharpe 最高只有 0.27，建议用 ConfluenceStrategy 或接受信号频率极低。

---

## 策略一：ConfluenceStrategy（高 beta 动量股）

适用：NVDA, TSLA, SNDK, MU, STX, MRVL + 部分 ETF

改进版本（按优先级 B-A-D 实施）：
- **B**：加趋势过滤（`use_trend_filter=True`），1h 用 200h SMA，4h 用 100×4h SMA，只在趋势方向开仓
- **A**：TP2 倍数放宽（1h: 4×ATR，4h/1d: 3×ATR），让利润单跑更远
- **D**：固定初始止损（`use_fixed_initial_sl=True`），stage=1 用 atr_sl_mult × ATR，TP1 后切换追踪止损

参数存储：`config.yaml` → `symbol_params`（每个标的独立覆盖 adx_threshold、ut_key、min_score）

### 横向对比（ConfluenceStrategy 优化后，1d 最佳 Sharpe）

| 标的 | 最佳 Sharpe | 周期 | WR |
|------|------------|------|-----|
| NVDA | 较高 | 1d | — |
| TSLA | 较高 | 1d | — |
| SNDK | 中等 | 1h/4h | — |
| MU | 中等 | 1d | — |
| STX | 中等 | 1h | — |
| MRVL | 中等 | 4h | — |

> 注：ConfluenceStrategy 详细数字在 `logs/backtest_results.csv` 中

---

## 策略二：RSI2 + QQQ 过滤 + 相对强度（大市值慢牛股 + ETF）

文件：`rsi2_backtest.py`，信号在 `rsi2_backtest.py` 内直接计算（无独立 signals 文件）

核心逻辑：
- 入场：close > 200 SMA（上升趋势）AND RSI2 < entry（短期超卖）AND QQQ > 100 SMA（risk-on）AND 个股 60 日收益 > QQQ（相对强）
- 出场：RSI2 > exit（短期恢复）OR ATR 追踪止损 OR 时间止损

### 优化后最佳参数

| 标的 | 周期 | Sharpe | WR | entry | exit | trail | hold |
|------|------|--------|-----|-------|------|-------|------|
| SOXX | 1h | **1.14** | 52.7% | 10 | 80 | 2× | 15 |
| MSFT | 4h | **1.13** | 73.3% | 15 | 80 | 2× | 15 |
| SOXX | 4h | **1.13** | 61.8% | 10 | 80 | 2× | 10 |
| GOOGL | 4h | **1.00** | 62.5% | 10 | 80 | 3× | 10 |
| SOXX | 1d | **1.00** | 64.7% | 5 | 80 | 3× | 15 |
| QQQ | 1d | 0.89 | 64.2% | 10 | 80 | 3× | 10 |
| SMH | 1d | 0.87 | 61.3% | 5 | 70 | 2× | 5 |
| SMH | 4h | 0.86 | 70.3% | 5 | 70 | 2× | 15 |
| GOOGL | 1h | 0.90 | 53.0% | 5 | 80 | 3× | 15 |
| META | 1d | 0.62 | 61.9% | 15 | 80 | 3× | 10 |
| MSFT | 1d | 0.64 | 60.0% | 5 | 80 | 2× | 15 |
| AAPL | 1d | 0.35 | 66.3% | 10 | 80 | 2.5× | 15 |
| AMZN | 1d | 0.27 | 63.6% | 10 | 80 | 2× | 10 |

注意：SOXX/SMH 建议关掉 `use_rs_filter`（行业 ETF 相对 QQQ 弱时仍有好信号）

---

## 策略三：MR 进场 × ATR 追踪出场（宽基 ETF 高胜率方案）

文件：`mr_backtest.py`, `mr_strategy.py`, `mr_signals.py`

核心逻辑：
- 进场：z-score ≤ -0.9（接近 BB 下轨）AND RSI < 40 AND ADX < 25 AND close > 200 SMA（只做多）
- 出场：ATR 追踪止损（不在中轨止盈，让趋势跑起来）

| 标的 | 周期 | Sharpe | WR | RR | PF |
|------|------|--------|-----|----|----|
| SOXX | 1d | 0.71 | 61.9% | 3.41 | 5.17 |
| SMH | 1d | 0.70 | 55.0% | 5.15 | 5.48 |
| QQQ | 1d | 0.59 | 47.4% | 2.71 | 2.55 |
| META | 1d | 0.37 | 60.0% | 1.69 | 2.62 |
| AAPL | 1d | 0.35 | 44.4% | 2.54 | 2.34 |

---

## 待研究

- **PEAD（财报后漂移）**：需要财报日期 + EPS 超预期数据，可通过 yfinance earnings calendar 或 EODHD API 获取
- **MAG7 周频相对强弱轮动**：跨标的排名持最强 2-3 只，每周调仓，本质是投资组合管理而非单点告警
- **AMZN 专项**："距 20 日高点回撤 5-10% + RSI 40-55"的思路，不同于 BB 下轨，更符合 AMZN 实际波动模式

---

## 关键参数文件

- `config.yaml` → ConfluenceStrategy 各标的参数
- `logs/backtest_results.csv` → ConfluenceStrategy 全量回测结果
- `logs/rsi2_backtest_results.csv` → RSI2 策略回测结果
- `logs/rsi2_optimized_params.csv` → RSI2 优化后最优参数
- `logs/mr_backtest_results.csv` → MR + ATR Trail 回测结果

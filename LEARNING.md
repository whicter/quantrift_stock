# LEARNING.md — 回测观察与经验

> 持续更新。每次回测后记录关键发现，用于指导参数优化和策略改进。

---

## 核心结论（2025-06）

### 品种分类（v2，更细）

| 类别 | 标的 | 适配策略 | 备注 |
|------|------|----------|------|
| AI/半导体趋势股 | NVDA, MU, MRVL | ConfluenceStrategy | 高 ADX、动量延续性强 |
| 高波动单股 | TSLA | 单独处理 | idiosyncratic risk 太强，不能与 NVDA/MU 混桶 |
| 存储周期股 | SNDK, STX | ConfluenceStrategy（谨慎）| 周期性强，财报驱动，普通 RSI2 不适合 |
| Mega-cap compounders | MSFT, GOOGL, META | RSI2 + market regime | 趋势平稳，RSI2 高频触底，4h/1d 有效 |
| 弱化/待观察 | AAPL, AMZN | 降权或剔除 | Sharpe 低（AAPL 0.35, AMZN 0.27），不进主策略池 |
| 半导体 ETF | SOXX, SMH | RSI2 + MR（不强制 RS vs QQQ）| 有时相对 QQQ 弱但本身信号有效 |
| 宽基 ETF | QQQ, SPY | RSI2 / MR / regime benchmark | 不参与 RS 过滤（本身就是基准）|

### 策略演进过程（重要）

1. **ConfluenceStrategy 在大市值股失败**：MSFT/AMZN/GOOGL 日内 ADX 长期偏低，UTBot + SSL 几乎不触发，或在 5-10% 小回调中产生假信号。
2. **纯 MR（中轨止盈）WR 高但 RR 低**：BB 下轨 + RSI < 40 有 75-84% WR，但中轨止盈限制 RR（0.8x）。
3. **EMA Pullback（21 EMA 回踩）WR 只有 28-43%**：进场过早，价格触及 21 EMA 但回调未完，已放弃。
4. **RSI2 解决了 MSFT/GOOGL 信号稀少问题**：RSI2 < 5 每年触发 40-60 次（RSI14 < 40 只有 5-15 次）。配合 QQQ 过滤 + 相对强度，WR 60-73%。

### 关键规律

- **1h 在大市值股基本无效**：RSI2 在 1h 噪声过大，Sharpe 多为负。4h 和 1d 是可用周期。
- **exit=80 比 exit=70 好**：反弹经常不止一根 K，等足了出场 RR 明显改善。
- **SOXX/SMH 不应强制 RS vs QQQ**：行业 ETF 有时整体弱于 QQQ 但本身仍有好信号，用自身趋势（> 100SMA）过滤即可。
- **AMZN 从主策略池删除**：任何策略 Sharpe 上限 0.27，回调延续性差，趋势切换剧烈。
- **TSLA 单独处理**：受马斯克消息/交付量/Robotaxi/期权流驱动，走势与 NVDA/MU 本质不同。
- **4h hold 15 ≠ 日线 hold 15**：4h 15根 ≈ 7-8 交易日；时间止损要按交易日换算，不能直接比较两个周期的 bar 数。

---

## 框架升级：市场状态 × 标的 × 策略（待实现）

现在的框架是「标的 → 固定策略」，下一步升级为「市场状态 → 标的池 → 策略模式 → 仓位」。

| 市场状态 | 判断条件 | 允许策略 |
|----------|----------|----------|
| Risk-on trend | QQQ > 100/200SMA，ADX 上升 | RSI2 回调买入、趋势跟随 |
| Risk-on chop | QQQ > 200SMA，但 ADX 低 | MR + ATR Trail |
| Risk-off | QQQ < 200SMA | 空仓或极小仓，只做 ETF 深度回调 |
| Panic rebound | VIX 急升后回落，QQQ 远离均线 | ETF 均值回归优先 |
| Earnings window | 个股财报前后 | 降仓或专用财报策略 |

**Market Regime Score**（QQQ 打分制，替代单条件 QQQ > 100SMA）：

```
MarketScore =
  +1 if QQQ > 100SMA
  +1 if QQQ > 200SMA
  +1 if QQQ 20SMA > 50SMA
  +1 if QQQ 5日收益 > 0
  -1 if VIX > 20
  -1 if QQQ 跌破前20日低点

MarketScore >= 2 → 允许正常开仓
MarketScore == 1 → 半仓
MarketScore <= 0 → 不开新仓
```

> 原因：QQQ 在 100SMA 附近来回震荡时，单条件过滤容易 whipsaw。

---

## 策略一：ConfluenceStrategy（动量股）

适用：NVDA, MU, MRVL（TSLA/SNDK/STX 谨慎）

**待改进方向（降维防过拟合）**：
- 当前：6 分项评分（UTBot + SSL + RSI + MACD + Squeeze + CD 背离）+ ADX + 分批止盈 + ATR trail，自由度过高
- 建议改为 3 层结构：
  - **第一层（必须满足）**：close > 100SMA AND 20SMA > 50SMA AND ADX > 20
  - **第二层（触发信号，满足其一）**：UTBot bullish OR SSL bullish OR Squeeze release
  - **第三层（加分项）**：+1 MACD histogram > 0，+1 RSI 50-70，总分 ≥ 3 才进
- CD 背离降权：在高 beta 动量股上容易早出/早进，不做主分

参数存储：`config.yaml` → `symbol_params`（每个标的独立覆盖 adx_threshold、ut_key、min_score）

---

## 策略二：RSI2 + Market Regime（Mega-cap + ETF）

文件：`rsi2_backtest.py`

### v1 核心逻辑（已回测）

- 入场：close > 200SMA AND RSI2 < entry AND QQQ > 100SMA AND 个股 60d 收益 > QQQ
- 出场：RSI2 > exit OR ATR 追踪止损 OR 时间止损

### v2 改进方向（待实现，按 A 优先级）

**① Market Regime Score**（替换单条件 QQQ > 100SMA）：见上方框架升级。

**② Pullback Location Filter**（替换纯 RSI2 阈值）：

```
入场条件改为：
  close > 200SMA      （大趋势向上）
  close > 100SMA      （中期趋势完整，避免接刀）
  close < 20SMA       （短期超卖、回调位置合理）
  RSI2 < entry
  MarketScore >= 2
```

避免高位"假回调"（RSI2 < 10 但价格已在 20SMA 之上大幅延伸）。

**③ 加权 RS 过滤**（替换单一 60d 收益）：

```python
RS_20 = stock_20d_return - QQQ_20d_return
RS_60 = stock_60d_return - QQQ_60d_return
RS_Score = 0.4 * RS_20 + 0.6 * RS_60
# 入场要求 RS_Score > 0
```

SOXX/SMH 不用 RS_Score，改用 `close > 100SMA` 替代。

**④ 分批出场模型 C**（替换 RSI2 > 80 全出）：

```
RSI2 > 80：平掉 1/2
剩余 1/2：ATR 追踪止损出场
```

> 待回测对比 A（RSI2>80全出）/ B（70出半,85全出）/ C（80出半,ATR出剩）/ D（1.5R出半,80全出）

**⑤ 时间止损换算**：

| 周期 | max hold bars | 约等于交易日 |
|------|--------------|------------|
| 1d | 10-15 | 10-15 天 |
| 4h | 12-24 | 6-12 天 |
| 1h | 基本不用 | — |

### v2 优化后最佳参数（当前版本）

出场模型 C（RSI2>80 出半 + ATR trail 出剩余），加权 RS，Market Regime Score。

| 标的 | 周期 | Sharpe | WR | N | entry | trail | hold | score | pullback |
|------|------|--------|----|---|-------|-------|------|-------|---------|
| MSFT | 4h | **1.66** | 81.5% | 27⚠️ | 15 | 2× | 5 | ≥1 | N |
| GOOGL | 4h | **1.64** | 66.7% | 33⚠️ | 5 | 3× | 15 | ≥3 | N |
| SOXX | 1d | **1.22** | 73.6% | 121 | 5 | 3× | 15 | ≥1 | N |
| GOOGL | 1h | **1.12** | 63.6% | 118 | 5 | 2.5× | 15 | ≥1 | N |
| META | 1d | **1.02** | 74.5% | 94 | 5 | 2.5× | 15 | ≥2 | N |
| META | 1h | **1.01** | 63.4% | 41 | 5 | 2× | 5 | ≥3 | Y |
| SMH | 1d | **0.98** | 69.7% | 119 | 5 | 2.5× | 15 | ≥2 | N |
| SOXX | 1h | 0.90 | 58.4% | 125 | 5 | 3× | 15 | ≥3 | N |
| GOOGL | 1d | 0.89 | 67.2% | 134 | 15 | 2× | 5 | ≥2 | N |
| SMH | 4h | 0.85 | 63.0% | 27⚠️ | 5 | 2.5× | 15 | ≥2 | Y |
| SPY | 4h | 0.79 | 63.8% | 58 | 15 | 2.5× | 15 | ≥1 | N |
| SOXX | 4h | 0.79 | 60.7% | 28⚠️ | 5 | 2× | 15 | ≥1 | Y |
| MSFT | 1d | 0.76 | 60.6% | 99 | 5 | 2.5× | 15 | ≥1 | N |
| QQQ | 1d | 0.72 | 70.3% | 185 | 10 | 3× | 10 | ≥1 | N |
| SPY | 1d | 0.62 | 68.8% | 93 | 15 | 3× | 15 | ≥1 | Y |
| AAPL | 1d | 0.60 | 65.6% | 96 | 15 | 3× | 15 | ≥2 | N |

> ⚠️ = 笔数 < 50，结果仅供参考（4h 数据历史约 2.7 年）
> 注：优化中 `rsi2_exit` 参数对 Model C 无效（已从 GRID 移除）

**v1 → v2 主要变化**：

| 标的/周期 | v1 Sharpe | v2 Sharpe | 变化 |
|---------|-----------|-----------|-----|
| SOXX 1d | 1.00 | **1.22** | ↑+0.22 |
| META 1d | 0.62 | **1.02** | ↑+0.40 |
| MSFT 4h | 1.13 | **1.66** | ↑+0.53（4h 仅 27 笔）|
| GOOGL 4h | 1.00 | **1.64** | ↑+0.64（4h 仅 33 笔）|
| GOOGL 1h | 0.90 | **1.12** | ↑+0.22 |
| SMH 1d | 0.87 | **0.98** | ↑+0.11 |
| MSFT 1d | 0.64 | **0.76** | ↑+0.12 |

### v1 优化后最佳参数（历史参考，已被 v2 取代）

出场模型 A（RSI2>80 全出），单条件 QQQ > 100SMA，60d RS 过滤。

| 标的 | 周期 | Sharpe | WR | entry | exit | trail | hold |
|------|------|--------|----|-------|------|-------|------|
| SOXX | 1h | 1.14 | 52.7% | 10 | 80 | 2× | 15 |
| MSFT | 4h | 1.13 | 73.3% | 15 | 80 | 2× | 15 |
| SOXX | 4h | 1.13 | 61.8% | 10 | 80 | 2× | 10 |
| GOOGL | 4h | 1.00 | 62.5% | 10 | 80 | 3× | 10 |
| SOXX | 1d | 1.00 | 64.7% | 5 | 80 | 3× | 15 |

---

## 策略三：MR 进场 × ATR 追踪出场（ETF）

文件：`mr_backtest.py`, `mr_strategy.py`, `mr_signals.py`

核心逻辑：
- 进场：z-score ≤ -0.9 AND RSI < 40 AND ADX < 25 AND close > 200SMA
- 出场：ATR 追踪止损

| 标的 | 周期 | Sharpe | WR | RR | PF | 笔数 | 可信度 |
|------|------|--------|----|----|----|----|------|
| SOXX | 1d | 0.71 | 61.9% | 3.41 | 5.17 | **21** | ❌ 不足 |
| SMH | 1d | 0.70 | 55.0% | 5.15 | 5.48 | **20** | ❌ 不足 |
| QQQ | 1d | 0.59 | 47.4% | 2.71 | 2.55 | **19** | ❌ 不足 |
| META | 1d | 0.37 | 60.0% | 1.69 | 2.62 | — | ❌ 未验证 |
| AAPL | 1d | 0.35 | 44.4% | 2.54 | 2.34 | — | ❌ 未验证 |

> ⚠️ **C 核查结论（2025-06）：MR 1d 策略结果不可信**
>
> 全部时间框架笔数均低于 50（SOXX/SMH/QQQ 1d 只有 19-21 笔，1h 只有 17-19 笔）。
> PF=5.17/5.48 明显是小样本噪声：
> - SOXX/SMH 2019 全年零交易（策略完全休眠）
> - 主要盈利集中在 2021 牛市和 2024 AI 行情
> - 仓位设置为 1 股（$127-353）占 $100k 账户 0.13-0.35%，绝对回报极小
>
> **结论：MR 策略的 Sharpe/PF 计算技术上正确，但样本量不足，无统计意义。需要重新调参。**

### 需要核查的指标（已完成）

- [x] trade count：SOXX 21 / SMH 20 / QQQ 19（1d），均低于 50
- [x] 2019 零交易（SOXX/SMH），2020 零交易（QQQ）
- [x] 仓位极小（1 share = 0.13% 账户），Sharpe 有效但统计意义差
- [x] 盈利集中在 2021 和 2024 牛市行情

### v2 改进方向（待实现）

**核心问题**：当前参数（z ≤ -0.9 + RSI < 40 + ADX < 25）信号频率太低，1d/1h 都只有 17-21 笔。需要在放宽过滤条件（增加笔数）和保持精准度（保持 WR）之间取得平衡。MR 策略对 ETF 的概念是正确的，但参数需要重新调优。

**① z-score 波动率自适应**：

```python
if ATR_percentile > 70:   # 高波动环境
    z_entry = -1.5
else:
    z_entry = -0.9
```

避免高波动下过早接刀。

**② 加 close > 100SMA**（替换仅 200SMA）：

```
close > 100SMA AND close > 200SMA
```

跌到 200SMA 上方一点点时可能已经很危险，100SMA 是更早的保护线。

**③ ADX 检查加 slope 条件**：

```
ADX < 25 AND ADX 没有连续 3 根上升
```

ADX 低但上升中意味着趋势正在形成，不是真正的震荡。

**④ AMZN 从 MR 策略删除**：回调延续性差，已确认无效。

---

## 待研究

- **PEAD（财报后漂移）**：需要财报日期 + EPS 超预期数据（yfinance earnings calendar 或 EODHD API）
- **MAG7 周频相对强弱轮动**：跨标的排名持最强 2-3 只，每周调仓
- **AMZN 专项**："距 20 日高点回撤 5-10% + RSI 40-55"，不同于 BB 下轨
- **VIX 数据接入**：用于 Market Regime Score 的 VIX > 20 判断

---

## 关键参数文件

- `config.yaml` → ConfluenceStrategy 各标的参数
- `logs/backtest_results.csv` → ConfluenceStrategy 全量回测结果
- `logs/rsi2_backtest_results.csv` → RSI2 策略回测结果
- `logs/rsi2_optimized_params.csv` → RSI2 优化后最优参数
- `logs/mr_backtest_results.csv` → MR + ATR Trail 回测结果

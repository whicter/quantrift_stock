# LEARNING.md — 回测观察与经验

> 持续更新。每次回测后记录关键发现，用于指导参数优化和策略改进。

---

## 上线验证结论（2026-06，成本压力 + 邻域稳定性 + Walk-Forward）

### 成本压力测试（0/5/10/20/30 bps）

| 标的 | 周期 | 策略 | 0bps | 10bps | 20bps | 30bps | 结论 |
|------|------|------|------|-------|-------|-------|------|
| MU   | 1h | Confluence | 1.60 | 1.44 | 1.28 | 1.10 | ✅ 全段合格 |
| SNDK | 1h | Confluence | 1.68 | 1.51 | 1.34 | 1.17 | ✅ 全段合格 |
| MRVL | 1h | Confluence | 1.31 | 0.94 | 0.56 | 0.17 | ⚠ 10bps以内合格，20bps降级 |
| GOOGL| 1h | RSI2 v2   | 0.71 | 0.31 | -0.10| -0.51| ❌ 只在0bps合格，成本敏感 |

**关键发现**：
- MRVL 1h 在 IB 实际佣金（约 5-10 bps round-trip）下 Sharpe 0.94-1.13，仍可接受
- GOOGL 1h RSI2 在任何真实佣金下均不达标，**从实盘候选名单移除**
- MU/SNDK 1h 非常稳健，佣金敏感性低（每 10 bps 只降约 0.18）

### 参数邻域稳定性（RSI2 1d 核心标的）

| 标的 | 最优参数 | Top-5 Sharpe 范围 | Spread | 评级 |
|------|----------|------------------|--------|------|
| SOXX 1d | entry=5, trail=3×, hold=15, score=1 | 1.193~1.275 | 0.082 | ✅ 稳定 |
| META 1d | entry=5, trail=2.5×, hold=15, score=2 | 0.958~1.018 | 0.060 | ✅ 非常稳定 |
| GOOGL 1d| entry=15, trail=2×, hold=5, score=2 | 0.869~0.956 | 0.087 | ✅ 稳定 |

- SOXX：entry=3 略优于 entry=5（1.275 vs 1.222），但差异很小，保持 entry=5 更保守
- META：entry=5/8 等效（0.92 hold=15 决定性因素），对 entry 阈值不敏感
- GOOGL 1d：entry=20 更优（0.956），目前 alert_engine 用 entry=15（保守）

### Walk-Forward 验证（RSI2 1d: 训练 2020-2022 → 测试 2023-至今）

| 标的 | 训练 Sharpe | 训练 N | 测试 Sharpe | 测试 N | 结论 |
|------|------------|--------|------------|--------|------|
| SOXX | 0.913 | 90 | **1.257** | 38 | ✅ 测试优于训练 |
| META | 1.079 | 53 | 0.680 | 28 | ✅ 合格 |
| GOOGL| 0.977 | 79 | 0.866 | 39 | ✅ 稳定 |
| NVDA | 0.841 | 67 | 0.660 | 34 | ✅ 合格 |
| MU   | 0.309 | 48 | **1.422** | 40 | ✅ 测试远优（AI 周期驱动）|
| MRVL | 0.405 | 92 | 0.667 | 41 | ✅ 合格 |
| SMH  | 1.055 | 81 | 0.984 | 43 | ✅ 高度稳定 |
| QQQ  | 0.493 | 104 | **1.097** | 61 | ✅ 测试优于训练 |
| MSFT | 0.729 | 74 | N/A | — | ⚠ 测试期 N 不足（RSI2<5 信号稀少）|

**Walk-Forward Confluence（训练 2023 → 测试 2024-至今，1h 数据有限）**：
- 1h 数据仅约 2 年（IB 730天限制），无法做有意义的 50/50 分割
- MU/MRVL/SNDK/STX 1h 测试结果等同全量回测结果，策略本身无过拟合迹象（信号简单、参数少）
- STX 1d 训练 Sharpe 0.02 → 测试 0.68，说明 STX 近两年动量更强，策略有效

**总体结论**：
- 8/9 个 RSI2 1d 标的通过 Walk-Forward（唯 MSFT 测试期样本不足）
- 无明显过拟合迹象：多数测试 Sharpe ≥ 训练 Sharpe，说明 2023-2025 行情对策略更友好
- GOOGL 1h RSI2 成本敏感，已从实盘候选移除

---

## 核心结论（2025-06，含 Market Regime + RSI2 扩展）

### 品种分类（v3，全标的验证后）

| 类别 | 标的 | 适配策略 | 备注 |
|------|------|----------|------|
| AI/半导体动量股 | NVDA, MRVL | Confluence 1h + RSI2 v2 1d | NVDA 1d RSI2 Sharpe 0.867 > Confluence 0.64；MRVL 1d RSI2 0.748 > Confluence 0.37 |
| 存储动量股 | MU | Confluence 1h + RSI2 v2 1d | 1h 趋势强（1.44），1d RSI2（0.94）|
| 存储周期股（新入池） | SNDK | Confluence 1h ✅ | 1h Sharpe 1.51 N=95，可信；1d Sharpe 1.83 N=20 不可信 |
| 存储周期股（新入池） | STX | Confluence 1h/4h/1d | 1h 0.87 / 4h 0.81 / 1d 0.69，全周期可用 |
| 高波动单股 | TSLA | Confluence 1d（天花板）| Sharpe 0.50，RR 0.61，保本止损已加；天花板约 0.5 |
| Mega-cap compounders | MSFT, GOOGL, META | RSI2 v2 + Market Regime | 趋势平稳，RSI2 高频触底 |
| 弱化/待观察 | AAPL | RSI2 1d 降权 | Sharpe 0.60 勉强可用 |
| 专项研究 | AMZN | 20日高点回撤策略 | 专项策略 Sharpe 0.308，仍不可用；结构性困难 |
| 半导体 ETF | SOXX, SMH | RSI2 v2（不强制 RS vs QQQ）| SOXX 1d 1.22 / SMH 1d 0.98 |
| 宽基 ETF | QQQ, SPY | RSI2 / regime benchmark | 不参与 RS 过滤（本身就是基准）|

### 策略演进过程（重要）

1. **ConfluenceStrategy 在大市值股失败**：MSFT/AMZN/GOOGL 日内 ADX 长期偏低，UTBot + SSL 几乎不触发，或在 5-10% 小回调中产生假信号。
2. **纯 MR（中轨止盈）WR 高但 RR 低**：BB 下轨 + RSI < 40 有 75-84% WR，但中轨止盈限制 RR（0.8x）。
3. **EMA Pullback（21 EMA 回踩）WR 只有 28-43%**：进场过早，价格触及 21 EMA 但回调未完，已放弃。
4. **RSI2 解决了 MSFT/GOOGL 信号稀少问题**：RSI2 < 5 每年触发 40-60 次（RSI14 < 40 只有 5-15 次）。配合 QQQ 过滤 + 相对强度，WR 60-73%。

### 关键规律

- **1h 在大市值股基本无效**：RSI2 在 1h 噪声过大，Sharpe 多为负。4h 和 1d 是可用周期。
- **NVDA 1h 结构性剔除**：ConfluenceStrategy 全网格（60 组合）最优 Sharpe -0.72，RSI2 v2 也是 -0.93。不是参数问题，1h 粒度下 NVDA 噪声完全淹没技术信号，两套策略均不可用。
- **MU 策略分层**：MU 不同周期适配不同策略。1h 用 ConfluenceStrategy（Sharpe 1.58），4h 两套均可（Confluence 1.04 / RSI2 1.67⚠️），1d Confluence 废（Sharpe 0.23，PF<1）→ 换 RSI2 v2（entry=5, trail=3×, hold≤10, score≥3）救活至 Sharpe 0.94。
- **同一标的不同周期可能需要不同策略**：MU 的案例说明不应强行用一套策略覆盖所有周期，要按周期独立评估。
- **exit=80 比 exit=70 好**：反弹经常不止一根 K，等足了出场 RR 明显改善。
- **SOXX/SMH 不应强制 RS vs QQQ**：行业 ETF 有时整体弱于 QQQ 但本身仍有好信号，用自身趋势（> 100SMA）过滤即可。
- **NVDA 1d 应改用 RSI2 v2**：RSI2 1d Sharpe 0.867（N=115）远超 Confluence 0.64，RR 1.14 vs 1.08，全面更优。参数：entry=5, trail=2×, hold≤15, score≥1。
- **MRVL 1d 应改用 RSI2 v2**：Confluence 1d Sharpe 0.37 → RSI2 0.748（N=66），翻倍。参数：entry=15, trail=2×, hold≤5, score≥2。
- **SNDK 1h 是隐藏强标的**：ConfluenceStrategy 1h Sharpe 1.51，WR 65.3%，N=95，可信。1d Sharpe 1.83 但 N=20 不可信。
- **STX 全周期均可用**：1h 0.87 / 4h 0.81 / 1d 0.69，三周期结果一致，可信度高。
- **Market Regime Score 对动量股效果有限**：MU/MRVL 1h 加 Regime 过滤后 Sharpe 略降（-0.1 左右），动量股信号在弱市仍有效；ETF 和 Mega-cap 受益更大。
- **AMZN 专项策略也失败**：20日高点回撤策略（pullback + RSI 恢复）全网格最优 Sharpe 0.308（N=82），结构性确认 AMZN 对技术策略不友好，彻底剔除主池。
- **TSLA 单独处理**：受马斯克消息/交付量/Robotaxi/期权流驱动，走势与 NVDA/MU 本质不同。两套策略均测试，Sharpe 天花板约 0.5，保本止损已加但改善有限。不进主池。
- **4h hold 15 ≠ 日线 hold 15**：4h 15根 ≈ 7-8 交易日；时间止损要按交易日换算，不能直接比较两个周期的 bar 数。
- **MU 策略分层**：MU 不同周期适配不同策略。1h ConfluenceStrategy（1.44），4h Confluence（1.07），1d RSI2 v2（0.94）。
- **SOXX/SMH 不应强制 RS vs QQQ**：行业 ETF 有时整体弱于 QQQ 但本身仍有好信号，用自身趋势（> 100SMA）过滤即可。
- **同一标的不同周期可能需要不同策略**：MU/NVDA/MRVL 均展示了周期间策略差异，不应强行一套策略覆盖全周期。

---

## 当前策略池汇总（2025-06 v2，含 Market Regime + RSI2 扩展）

> 仅列 N ≥ 50 或有明确说明的组合；⚠️ = N < 50，仅参考。

### Confluence Strategy 池

| 标的 | 周期 | Sharpe | WR | N | RR | 关键参数 |
|------|------|--------|----|---|----|---------|
| **MU** | 1h | **1.44** | 63.6% | 77 | 1.28 | adx=30, ut_key=2.0 |
| **SNDK** | 1h | **1.51** | 65.3% | 95 | 1.13 | adx=15, ut_key=1.5（默认）|
| **MRVL** | 1h | **0.94** | 60.4% | 149 | 0.88 | adx=15, ut_key=1.0，保本止损已加 |
| **MU** | 4h | **1.07** | 61.4% | 70 | 1.07 | adx=20, ut_key=1.0 |
| **STX** | 1h | 0.87 | 58.9% | 107 | 1.07 | adx=30, ut_key=3.0 |
| **STX** | 4h | 0.81 | 58.8% | 51 | 1.21 | adx=25, ut_key=1.5 |
| **STX** | 1d | 0.69 | 64.0% | 114 | 1.38 | adx=20, ut_key=1.5 |
| NVDA | 1d | 0.64 | 75.0% | 52 | 1.08 | adx=30, ut_key=2.5（RSI2 更优，见下）|
| MRVL | 4h | 0.72 | 66.7% | 30⚠️ | 1.24 | adx=30, ut_key=3.0 |
| TSLA | 1d | 0.42 | 70.8% | 96 | 0.61 | adx=25，保本止损已加，天花板 |
| SNDK | 1d | 1.83⚠️ | 80.0% | 20 | 0.85 | N 不足，不可信 |

### RSI2 v2 池

| 标的 | 周期 | Sharpe | WR | N | RR | 关键参数 |
|------|------|--------|----|---|----|---------|
| **SOXX** | 1d | **1.22** | 73.6% | 121 | — | entry=5, trail=3×, hold≤15, score≥1 |
| **GOOGL** | 1h | **1.12** | 63.6% | 118 | — | entry=5, trail=2.5×, hold≤15, score≥1 |
| **META** | 1d | **1.02** | 74.5% | 94 | — | entry=5, trail=2.5×, hold≤15, score≥2 |
| **SMH** | 1d | 0.98 | 69.7% | 119 | — | entry=5, trail=2.5×, hold≤15, score≥2 |
| **NVDA** | 1d | **0.754** | 62.3% | 130 | 1.18 | entry=5, trail=2×, hold≤15, score≥1, vix✓ ✅ 优于 Confluence |
| **MU** | 1d | **0.896** | 66.3% | 89 | 2.18 | entry=5, trail=3×, hold≤15, score≥3, vol✓, vix✓ |
| **MRVL** | 1d | **0.748** | 72.7% | 66 | 0.96 | entry=15, trail=2×, hold≤5, score≥2 ✅ 优于 Confluence |
| SOXX | 1h | 0.90 | 58.4% | 125 | — | entry=5, trail=3×, hold≤15, score≥3 |
| GOOGL | 1d | 0.89 | 67.2% | 134 | — | entry=15, trail=2×, hold≤5, score≥2 |
| SPY | 4h | 0.79 | 63.8% | 58 | — | entry=15, trail=2.5×, hold≤15, score≥1 |
| MSFT | 1d | **0.849** | 64.5% | 110 | 1.21 | entry=5, trail=2.5×, hold≤15, score≥1, vol✓, vix✓ |
| QQQ | 1d | 0.72 | 70.3% | 185 | — | entry=10, trail=3×, hold≤10, score≥1 |
| SPY | 1d | 0.62 | 68.8% | 93 | — | entry=15, trail=3×, hold≤15, score≥1 |
| AAPL | 1d | 0.60 | 65.6% | 96 | — | entry=15, trail=3×, hold≤15, score≥2 |
| MSFT | 4h | 1.66⚠️ | 81.5% | 27 | — | entry=15, trail=2×, hold≤5, score≥1 |
| GOOGL | 4h | 1.64⚠️ | 66.7% | 33 | — | entry=5, trail=3×, hold≤15, score≥3 |

**剔除（结构性不可用）**：
- NVDA 1h：两套策略全网格均负，结构性剔除
- MU 1d（ConfluenceStrategy）：Sharpe 0.23，已换 RSI2
- MRVL 1d（ConfluenceStrategy）：Sharpe 0.37，已换 RSI2
- AMZN：通用策略 + 专项策略均 Sharpe < 0.35，彻底剔除主池
- TSLA 1h/4h：两套均无效或样本不足

---

## TSLA 专项分析（2025-06）

### 测试结论

TSLA 在 ConfluenceStrategy 和 RSI2 v2 两套框架下均测试，**Sharpe 天花板约 0.5-0.6**，这是 TSLA 本身特性决定的，不是参数问题。

**特性根因**：
- 收益分布胖尾：小幅震荡 + 偶发 10-20% 跳空（Musk 推文、交付数据、Robotaxi）
- 高 IV、期权 Gamma 集中，止损位置经常在期权驱动的"stop hunt"价位附近
- WR 高（ConfluenceStrategy 1d 达 71%）但 RR 低（0.63）：方向判断对，但固定 ATR 止盈在大趋势启动前就出场

### 策略对比（最优参数）

| 策略 | 周期 | Sharpe | WR | N | RR | MaxDD | 可信度 |
|------|------|--------|----|---|----|-------|--------|
| ConfluenceStrategy | 1d adx=25 | **0.50** | **71.4%** | **98** | 0.63 | — | ✅ 可信 |
| ConfluenceStrategy | 4h adx=30 | 0.60 | 60.9% | 23⚠️ | 1.06 | — | ❌ 样本不足 |
| RSI2 v2 | 1h | 0.57 | 56.2% | 80 | **1.01** | -13.4% | ✅ 可信 |
| RSI2 v2 | 1d | 0.28 | 55.6% | 90 | 0.97 | -55.7% | ❌ MaxDD 过大 |

### 出场模式探索：纯 sslExit 追踪（use_staged_tp=False）

| 周期 | adx | 出场 | Sharpe | WR | N | RR |
|------|-----|------|--------|----|---|----|
| 4h | 30 | 分批TP（当前） | 0.60 | 60.9% | 23⚠️ | 1.06 |
| 4h | 30 | **纯sslExit追踪** | **1.34** | 56.2% | 16⚠️ | **3.89** |
| 4h | 25 | 纯sslExit追踪 | 0.52 | 38.5% | 26⚠️ | 2.42 |
| 4h | 20 | 纯sslExit追踪 | -0.05 | 26.2% | 42 | 2.74 |
| 1d | 25 | 分批TP | 0.50 | 71.4% | 98 | 0.63 |
| 1d | 25 | 纯sslExit追踪 | 0.29 | 46.1% | 76 | 1.82 |

**关键发现**：
- 4h adx=30 + 纯追踪 Sharpe=1.34 亮眼，但 16 笔不可信（4h 历史仅 2.7 年）
- adx 降低（25/20）引入弱趋势信号，纯追踪模式下 WR 从 56% 跌到 26-38%，Sharpe 同步下跌
- 1d 两种出场模式 Sharpe 相近（0.50 vs 0.29），出场方式不是 1d 的决定性因素
- **结论**：adx=30 是 TSLA 4h 的强过滤条件，不能放松；但 4h 数据不足，无法置信

### 最终配置（写入 config.yaml）

```yaml
TSLA:
  1h:  {adx_threshold: 25.0, ut_key: 2.5, min_score: 4}   # 1h 无效，保持默认不做主力
  4h:  {adx_threshold: 30.0, ut_key: 3.0, min_score: 5}   # 样本不足，仅参考
  1d:  {adx_threshold: 25.0, ut_key: 2.0, min_score: 4}   # 最可信：Sharpe 0.50，98笔
```

**处置决定**：TSLA 保持 `high_vol` 分组，不纳入主力策略池。ConfluenceStrategy 1d（adx=25）作为当前最优选择，Sharpe 0.50 为合理预期上限。不再投入参数研发，等待更长 4h 历史数据后重新评估。

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

**降维实验结论（2026-06，已验证，不推荐）**：

对比 3 层结构 vs 原始 6 分项（Confluence 主力标的）：

| 标的 | 周期 | 原始 Sharpe | 3层 score≥1 | 3层 score≥2 | 结论 |
|------|------|------------|------------|------------|------|
| MU   | 1h   | **1.44**   | 1.40 | 0.59 | 原始胜 |
| SNDK | 1h   | **1.51**   | 1.32 | 1.03 | 原始胜 |
| MRVL | 1h   | **0.94**   | 0.80 | 0.56 | 原始胜 |
| STX  | 1h   | **0.87**   | -0.10 | 0.88 | 原始胜 |
| STX  | 1d   | **0.69**   | 0.58 | 0.59 | 原始胜 |

**结论：原始 6 分项评分不需要降维**。各分量（含 CD 背离）共同贡献，简化后信号质量下降，Sharpe 全面降低。当前 6 分项架构维持不变。

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

### v2 优化后最佳参数（当前版本，含成交量加分 vol_score）

出场模型 C（RSI2>80 出半 + ATR trail 出剩余），加权 RS，Market Regime Score。
vol✓ = use_vol_score=True（成交量 > 20日均量 × 1.5 时 market_score +1）

| 标的 | 周期 | Sharpe | WR | N | entry | trail | hold | score | vol | pullback |
|------|------|--------|----|---|-------|-------|------|-------|-----|---------|
| MSFT | 4h | **1.66** | 81.5% | 27⚠️ | 15 | 2× | 5 | ≥1 | — | N |
| GOOGL | 4h | **1.64** | 66.7% | 33⚠️ | 5 | 3× | 15 | ≥3 | — | N |
| SOXX | 1d | **1.22** | 73.6% | 121 | 5 | 3× | 15 | ≥1 | — | N |
| GOOGL | 1h | **1.12** | 63.6% | 118 | 5 | 2.5× | 15 | ≥1 | — | N |
| META | 1d | **1.071** | 72.0% | 100 | 15 | 2.5× | 15 | ≥2 | ✓ | N |
| META | 1h | **1.01** | 63.4% | 41 | 5 | 2× | 5 | ≥3 | — | Y |
| SMH | 1d | **0.98** | 69.7% | 119 | 5 | 2.5× | 15 | ≥2 | — | N |
| MU | 1d | **0.948** | 67.0% | 88 | 5 | 3× | 15 | ≥1 | ✓ | N |
| GOOGL | 1d | **0.906** | 67.6% | 136 | 15 | 2× | 5 | ≥2 | ✓ | N |
| SOXX | 1h | 0.90 | 58.4% | 125 | 5 | 3× | 15 | ≥3 | — | N |
| SMH | 4h | 0.85 | 63.0% | 27⚠️ | 5 | 2.5× | 15 | ≥2 | — | Y |
| NVDA | 1d | 0.867 | 67.8% | 115 | 5 | 2× | 15 | ≥1 | — | N |
| SPY | 4h | 0.79 | 63.8% | 58 | 15 | 2.5× | 15 | ≥1 | — | N |
| MSFT | 1d | **0.797** | 61.8% | 102 | 5 | 2.5× | 15 | ≥1 | ✓ | N |
| SOXX | 4h | 0.79 | 60.7% | 28⚠️ | 5 | 2× | 15 | ≥1 | — | Y |
| MRVL | 1d | 0.748 | 72.7% | 66 | 15 | 2× | 5 | ≥2 | — | N |
| QQQ | 1d | 0.72 | 70.3% | 185 | 10 | 3× | 10 | ≥1 | — | N |
| SPY | 1d | 0.62 | 68.8% | 93 | 15 | 3× | 15 | ≥1 | — | Y |
| AAPL | 1d | 0.60 | 65.6% | 96 | 15 | 3× | 15 | ≥2 | — | N |

> ⚠️ = 笔数 < 50，结果仅供参考（4h 数据历史约 2.7 年）
> 注：优化中 `rsi2_exit` 参数对 Model C 无效（已从 GRID 移除）

**VIX 急升回落（vix_spike）回测结论（2026-06）**：

定义：近 10 日 VIX max > 25（恐慌触发）且当前 VIX < 3 日前（恐慌消退），market_score +1。

| 标的 | vix关闭 Sharpe | vix开启 Sharpe | 提升 | 结论 |
|------|---------------|----------------|------|------|
| MSFT 1d | 0.774 | 0.849 | **+0.075** | ✅ 有效 |
| NVDA 1d | 0.684 | 0.754 | **+0.070** | ✅ 有效 |
| MU 1d | 0.834 | 0.896 | **+0.062** | ✅ 有效 |
| SOXX 1d | 0.767 | 0.767 | — | ❌ 无效 |
| SMH 1d | 0.644 | 0.611 | -0.033 | ❌ 略降 |
| META/GOOGL/MRVL/QQQ/SPY/AAPL 1d | — | — | 0 | ❌ 无效 |

规律：MSFT/NVDA/MU 在 VIX 急升后的恐慌回落底部信号质量更高；ETF（SOXX/SMH）流动性驱动、与 VIX 恐慌情绪脱钩；Mega-cap 中 META/GOOGL 因个股逻辑更强，VIX 对信号质量影响不显著。

**成交量加分回测结论（2026-06）**：

| 标的 | 旧 Sharpe | 新 Sharpe | 提升 | vol✓ |
|------|-----------|-----------|------|------|
| META 1d | 1.020 | 1.071 | +0.05 | ✅ |
| MSFT 1d | 0.760 | 0.797 | +0.04 | ✅ |
| GOOGL 1d | 0.890 | 0.906 | +0.02 | ✅ |
| MU 1d | 0.940 | 0.948 | +0.01 | ✅ |
| SOXX 1d | 1.222 | 1.222 | — | ❌ |
| NVDA 1d | 0.867 | 0.867 | — | ❌ |
| MRVL 1d | 0.748 | 0.748 | — | ❌ |

规律：Mega-cap（META/MSFT/GOOGL）和 MU 放量超卖是更可信的底部信号；ETF（SOXX）流动性天然大，NVDA/MRVL 机构驱动，成交量信噪比低，vol_score 无效。

**v1 → v2 主要变化**：

| 标的/周期 | v1 Sharpe | v2 Sharpe | 变化 |
|---------|-----------|-----------|-----|
| SOXX 1d | 1.00 | **1.22** | ↑+0.22 |
| META 1d | 0.62 | **1.071** | ↑+0.45 |
| MSFT 4h | 1.13 | **1.66** | ↑+0.53（4h 仅 27 笔）|
| GOOGL 4h | 1.00 | **1.64** | ↑+0.64（4h 仅 33 笔）|
| GOOGL 1h | 0.90 | **1.12** | ↑+0.22 |
| SMH 1d | 0.87 | **0.98** | ↑+0.11 |
| MSFT 1d | 0.64 | **0.797** | ↑+0.16 |

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

## PEAD 研究结论（2026-06，彻底放弃）

### 数据接入

- Alpha Vantage 免费 API（注册即用，25次/天），`surprisePercentage` 字段返回百分比，存储时除以 100 转小数格式
- 用法：`python pead_backtest.py --av-key YOUR_KEY`（5年历史，约 80 笔/标的）
- yfinance 仅返回最近 4 季度，样本不足

### 回测结论（9只标的 × 5年，678笔）

| 指标 | 结果 |
|------|------|
| 全体 WR | 34.2% |
| avgRet | -1.58% |
| 9只标的 | 全部亏损 |
| 各持有天数（1/2/3/5/10d）| 全部为负 |
| TSLA 单独测试 | WR≈50%，avgRet≈0，亦无效 |

**根本原因**：大市值科技/半导体股分析师覆盖极密，财报信息在公布当天（甚至盘后）基本完全 price in，后续漂移方向随机。PEAD 效应主要存在于中小盘、低分析师覆盖的股票。**本标的池结构性不适合 PEAD，彻底放弃。**

---

## MAG7 周频相对强弱轮动（2026-06，`mag7_rotation.py`）

### 策略逻辑

每周一按 N 日收益排名，持仓 Top-K 只 MAG7（MSFT/GOOGL/META/AAPL/NVDA/AMZN/TSLA），等权分配。

可选 Risk-off：QQQ < 200SMA 时全部空仓。

### 参数敏感性扫描结论

| top_n | rs 周期 | risk_off | Sharpe | 年化% | MaxDD% | 胜率% |
|-------|---------|----------|--------|-------|--------|-------|
| 3 | 90d | ✅ | **1.066** | 30.7 | **-34.0** | 46.7 |
| 3 | 60d | ✅ | 0.991 | 28.1 | -33.9 | 46.2 |
| 2 | 90d | ✅ | 0.967 | 33.0 | -41.0 | 46.3 |
| 3 | 40d | ✅ | 0.760 | 20.7 | -35.4 | 45.0 |
| 3 | 90d | ❌ | 0.884 | 30.3 | -59.9 | 58.1 |
| **等权 MAG7（基准）** | — | ❌ | 0.802 | 22.8 | -53.5 | — |

**关键发现**：
- **Risk-off（QQQ<200SMA 空仓）是最重要的提升**：MaxDD 从 -59.9% → -34.0%，Sharpe 0.884 → 1.066
- **90 日 RS 远优于 20/40 日**：MAG7 动量持续数月，短周期 RS 信噪比差
- **top=3 优于 top=1/2**：分散降低单股集中风险，Sharpe 更优
- **最优参数**：top=3，rs=90d，risk_off=True → **Sharpe 1.066，年化 30.7%，MaxDD -34.0%**
- 策略显著优于等权持有 MAG7 基准（Sharpe 1.066 vs 0.802，MaxDD -34% vs -54%）

### 持仓频率（最优参数，502 周）

| 标的 | 持仓频率 | 说明 |
|------|---------|------|
| NVDA | 57.6% | AI 周期动量持续最长 |
| TSLA | 40.0% | 高 beta，爆发期排名高 |
| META | 33.7% | 2022 反弹后持续强势 |
| AAPL | 29.3% | 稳定性持仓 |
| MSFT/AMZN/GOOGL | 23-27% | 轮动出现 |

### 注意事项

- 回测从 2016 年起（约 10 年），含 NVDA AI 行情；实盘需观察 AI 周期是否持续
- 交易成本 0.1%/单边，每周调仓约 0.2% 往返成本，已含于回测
- 周胜率 46.7%（低于 50%）正常：动量策略靠少数大赢弥补频繁小亏
- 文件：`mag7_rotation.py`，结果：`logs/mag7_rotation.csv`
---

## ETF 板块轮动扫描器（2026-06，`etf_scanner.py`）

### 设计目标

在现有个股信号体系（RSI2 + Confluence）之外，提供**板块层面宏观扫描**：找资金流入的强势板块（追强）+ 找超跌开始修复的板块（抄底候选）+ 找持续跑输大盘的弱势板块（做空候选）。

### 三套评分

**Rotation Score（0-100，追强）**：

| 因子 | 条件 | 分数 |
|------|------|------|
| 趋势 | 收盘 > 50MA | +15 |
| 长期趋势 | 收盘 > 200MA | +15 |
| 短期动量 | ETF 20日收益 > SPY 20日收益 | +15 |
| 中期动量 | ETF 60日收益 > SPY 60日收益 | +15 |
| RS 强度 | ETF/SPY > 其 20MA | +15 |
| RS 新高 | ETF/SPY 处于 20日新高（±0.5%）| +15 |
| 量能 | 成交量 > 20日均量 | +10 |

分数 ≥ 75：强势追强候选；60-75：观察/等回踩；< 45：弱势不碰

**Reversal Score（0-100，超跌反转）**：

前提：RSI(14) < 40 且 收盘 < 50MA × 0.95（未满足前提 score=0）

| 因子 | 条件 | 分数 |
|------|------|------|
| 极度超跌 | RSI < 30 | +15 |
| 深度偏离 | 收盘 < 50MA × 0.92 | +15 |
| 恐慌放量 | 成交量 > 1.5× 均量 | +10 |
| 止跌 | 收盘 > 5MA | +15 |
| 反包 | 收盘 > 前日最高价 | +15 |
| RS 修复 | ETF/SPY 连续 3 天上升 | +15 |
| 均线修复 | 收盘距 20MA < 5% | +15 |

分数 ≥ 45："反转确认"；< 45："超跌待确认"（不是买入信号）

**Weakness Score（0-100，做空候选）**：

前提过滤：RSI(14) < 35 的标的反弹风险高，自动跳过（标记"超跌跳过"）

| 因子 | 条件 | 分数 |
|------|------|------|
| 短期破位 | 收盘 < 50MA | +15 |
| 长期趋弱 | 收盘 < 200MA | +15 |
| 短期跑输 | ETF 20日收益 < SPY 20日收益 | +15 |
| 中期跑输 | ETF 60日收益 < SPY 60日收益 | +15 |
| RS 趋弱 | ETF/SPY < 其 20MA | +15 |
| RS 新低 | ETF/SPY 处于 20日新低（±0.5%）| +15 |
| 放量确认 | 成交量 > 20日均量（卖盘确认）| +10 |

分数 ≥ 60："做空确认"；40-59："弱势观察"；< 40："弱势不足"

**关键设计**：RSI<35 超跌标的不适合做空（已有反弹风险），Rotation Score 垫底 + Weakness Score 高才是有效空头候选。

实盘示例（2026-06-21，Risk-On 环境）：做空确认 ETF = XLE/XOP（能源，RS20d -11~-13%，RS60d -26~-30%）、IHI（医疗设备 RS60d -24%）、GDX（金矿 RS60d -16%）、XLY（可选消费 RS60d -8%）

### 市场环境判断

| 环境 | 条件 | 策略建议 |
|------|------|---------|
| 🟢 Risk-On | SPY>200MA + 20MA>50MA + QQQ/SPY趋势↑ + VIX<25 | 追强为主 |
| 🟡 Neutral | SPY>200MA + VIX<25，但不满足 Risk-On 全部 | 只做强势回踩 |
| 🔴 Risk-Off | SPY<200MA 或 VIX≥25 | 观察防御板块，不追高 |

### ETF 分组（45只）

| 组 | ETF |
|----|-----|
| 大板块 | XLK 科技、XLC 通信、XLY 可选消费、XLP 必需消费、XLV 医疗、XLF 金融、XLI 工业、XLE 能源、XLB 原材料、XLU 公用事业、XLRE 房地产 |
| 科技/AI | IGV 软件、CIBR/HACK 网络安全、SKYY/CLOU 云计算、BOTZ AI机器人、ARTY AI未来科技、AIQ AI科技 |
| 半导体 | SMH、SOXX、XSD |
| 金融细分 | KBE 银行、KRE 区域银行、KIE 保险 |
| 医疗/生技 | XBI 生技等权、IBB 生技、IHI 医疗设备 |
| 国防/运输 | ITA、XAR（航天国防）、IYT 运输 |
| 消费/住宅 | XHB 住宅/家装、ITB 住宅、XRT 零售等权 |
| 能源/资源 | XOP 油气、ICLN 清洁能源、TAN 太阳能、GDX 金矿、GDXJ 小型金矿 |
| 房地产 | VNQ、IYR（REITs）、SRVR 数据中心REITs、DTCR 数字基建 |

注：IRBO（已退市）→ ARTY；VPN（已退市）→ DTCR

### 实盘观察结论（2026-06-21）

市场环境：🟢 Risk-On，VIX 16.4

**轮动强势**：SMH/SOXX（90分，vs200MA +60-77%，半导体延续强势）；XBI（100分，生技补涨）；DTCR（100分，数据中心/数字基建）；XHB（85分，住宅建筑近期最强，RS20d +11.3%）

**超跌候选**：GDXJ/XOP/XLE（RSI 37-39，vs50MA -6~-9%），但 RS3↑ 全为 ✗，属"超跌待确认"，非买入信号。能源/金矿尚未出现反转确认。

### 关键认知

- **核心原则**：真正值得买的不是"跌得最多的 ETF"，而是**跌完后开始重新跑赢 SPY 的 ETF**
- Rotation Score 高说明资金正在流入，可追；Reversal Score < 45 只是超跌，不是抄底信号
- ETF/SPY 相对强度连续上升是抄底成立的必要条件

---

## 系统架构（2026-06 当前状态）

### 数据接入层（data_providers.py）

```
config.yaml: data.provider: "yfinance"
        ↓
MarketDataProvider (ABC)
  ├── YFinanceProvider   ← 当前：fetch_ohlcv + fetch_vix(^VIX, 15min延时)
  └── TastytradeProvider ← 占位：fetch_vix($VIX.X, 实时)，填 SDK 代码即可启用
```

- 切换数据源：`config.yaml` 改一行 `provider`，其他代码不动
- 凭证：`.env` 文件（gitignore），`TT_USERNAME` / `TT_PASSWORD`
- VIX 已集成到 alert_engine Market Regime Score（有数据时 score 范围 -1~5，无数据 0~4）

**VIX 数据源调研结论**（2026-06，已更新）：
- **IB `Index('VIX','CBOE','USD')` ✅**：`reqHistoricalData whatToShow=TRADES` 可成功拉取 VIX 日线历史数据（2年），`fetch_etf_data.py --symbol VIX` 已实现，保存为 `data/VIX_1d.csv`。用于 ETF 扫描器市场环境判断。
- **alert_engine VIX**：仍用 yfinance `^VIX` 实时拉取（via `data_providers.py`），15 分钟延时，对日线 Regime 打分够用，无需改动
- Tastytrade API：`/market-metrics?symbols=VIX` 返回 VIX 期权 IV，非 VIX 指数价格；DXLink websocket 实现复杂，不必要
- **结论**：ETF 扫描器用 IB（`fetch_etf_data.py` 预下载）；alert_engine 用 yfinance（实时单次拉取）

### alert_engine 策略路由（STRATEGY_MAP）

每个 `(symbol, tf)` 明确指定策略，避免同标的多策略重复告警：

| 策略 | 标的 × 周期 |
|------|------------|
| Confluence | MU 1h/4h、MRVL 1h/4h、NVDA 4h、SNDK 1h、STX 1h/4h/1d、TSLA 1d |
| RSI2 v2 | NVDA/MRVL/MU 1d、MSFT 1d/4h、GOOGL 1d/4h（1h 成本不达标已移除）、META 1h/1d、SOXX/SMH 1h/4h/1d、QQQ 1d、SPY 1d/4h、AAPL 1d |

### 关键参数文件

- `config.yaml` → 策略参数（per symbol × tf）+ `data.provider` 数据源选择
- `data_providers.py` → 数据接入抽象层
- `.env` → 私密凭证（tastytrade 账号，gitignore）
- `.env.example` → 凭证模板（可提交）
- `logs/backtest_results.csv` → ConfluenceStrategy 全量回测结果
- `logs/rsi2_v2_backtest_results.csv` → RSI2 v2 回测结果
- `logs/rsi2_v2_optimized_params.csv` → RSI2 v2 最优参数

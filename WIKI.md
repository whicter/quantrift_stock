# WIKI.md — quantrift_stock 策略文档

## 策略概述

继承自 `quantrift_index_future` 的 ConfluenceStrategy，原参数针对 NQ/ES 期货优化。
本项目将其应用于美股个股和 ETF，仅发信号告警，不执行下单。

## 信号评分系统（满分 6）

| 分项 | 多头条件 | 空头条件 |
|---|---|---|
| B1 UTBot | close > utTS | close < utTS |
| B2 SSL | close > BBMC & ssl1 (或 buyCont) | close < BBMC & ssl1 (或 sellCont) |
| B3 RSI | RSI > 50 | RSI < 50 |
| B4 MACD | MACD线 > 信号线 | MACD线 < 信号线 |
| B5 Squeeze | sqzVal > 0 且上升 | sqzVal < 0 且下降 |
| B6 CD背离 | 底背离 | 顶背离 |

入场条件：`bull_score >= min_score`（默认5）且 ADX ≥ adx_threshold（默认25）且放量

## 出场逻辑（staged_tp=True 模式）

```
stage 1（满仓）→ 止损：utTS穿越
                → TP1：entry + 1×ATR（平 34%）→ stage 2
stage 2（持66%）→ 止损：utTS穿越
                → TP2：entry + 2×ATR（平剩余50%）→ stage 3
stage 3（持33%）→ sslExit 跟踪止盈（吃大趋势）
```

## 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `min_score` | 5 | 入场最低得分（满分6） |
| `adx_threshold` | 25.0 | ADX趋势强度过滤（股票推荐20-30） |
| `ut_key` | 1.5 | UTBot止损宽度（越大越松，回撤大但不易被扫） |
| `atr_tp1_mult` | 1.0 | TP1位置 = entry ± 1×ATR |
| `atr_tp2_mult` | 2.0 | TP2位置 = entry ± 2×ATR |
| `tp1_portion` | 0.34 | TP1平仓比例（1手时无效，整数取整为0） |
| `ssl_len` | 20 | SSL主线周期 |
| `exit_len` | 15 | sslExit追踪线周期 |

## 与期货版本的差异

| 项目 | 期货（quantrift_index_future） | 股票（quantrift_stock） |
|---|---|---|
| 合约乘数 | MNQ=$2/点，MES=$5/点 | 无（$1/点 = 每股） |
| `contract_size` | 2（MNQ） | 1 |
| 交易时段 | 近24h（周日-周五） | 09:30-16:00 ET |
| 滚动合约 | ContFuture 自动处理 | 不需要 |
| 保证金 | 期货固定 | Reg T 50%（日内25%） |
| 执行 | 实盘下单 | **仅 Telegram 告警** |
| clientId | 1 | 2 |

## 回测结论

> 持续更新，详见 `LEARNING.md`

| 标的 | 周期 | Sharpe | MaxDD | 胜率 | 笔数 | 备注 |
|---|---|---|---|---|---|---|
| （待填入） | | | | | | |

## 数据说明

- **告警运行时**：1h / 1d 由 yfinance 直接下载（约 15 分钟延时）
- **离线历史回测/回填**：优先使用 `data/{SYMBOL}_{TF}.csv`；IB Gateway 仅用于显式补拉并合并，4h 由 1h 重采样
- **4h**：由 1h 重采样（OHLCV 聚合规则：O=first, H=max, L=min, C=last, V=sum）
- **⚠️ 采样锚点差异（2026-07-25 核实，回测 vs 实盘的已知偏差源）**：
  - IB 1h bar 用**整点锚**（09:30/10:00/11:00/…/15:00，每交易日 7 根）；yfinance 1h bar 用**半点锚**（09:30/10:30/…/15:30，每交易日 7 根）。同名"1h bar"覆盖的时间片错开 30 分钟。
  - 4h 更明显：离线 CSV（`fetch_ib_data.resample_4h`）用 `closed="left", label="left"` → bar 标 08:00/12:00；实时 `alert_engine.fetch_bars` 用 `closed="right", label="right"` → bar 标 12:00/16:00。同一天 NVDA 2026-07-23 两边收盘价分别为 208.18/208.69（离线）与 209.63/208.70（实时）。
  - **性质**：不是数据错误，是回测与实盘看到的 K 线边界不同。统一约定会改变实时信号本身（属策略行为变化），需单独评估后再决定，当前仅记录在案。
- **日线价格准确性已验证**：IB 用 `ADJUSTED_LAST` + `useRTH=True`，yfinance 用 `auto_adjust=True`，口径一致。2026-07-25 抽查 NVDA/JPM/KO 近 5 个交易日收盘价，两边差异 **0.000%**。
- **RTH 下每日 bar 数（时间止损换算基准）**：1h = 7 根/交易日；**4h = 2 根/交易日**（08:00、12:00）；1d = 1 根/交易日。任何"最长持仓 N 根"的表述都必须按此换算成交易日，不能按日历 24 小时除。
- **数据存储**：`data/{SYMBOL}_{TF}.csv`；用 `data_audit.py --write` 查看覆盖、陈旧度和补拉计划
- **2026-07-24 运行状态**：2026-07-18 发现的 IB Gateway US 历史数据 farm `ushmds` 断连已解决（经用户批准重启 Gateway + 手机 2FA 批准），IB 补拉恢复正常；72 个 `symbol × tf` 文件已用 `fetch_ib_data.py --merge` 重新覆盖至 2026-07-23，来源为 `ib`（此前 2026-07-18 的 yfinance 合并记录仅作历史参考）
- **ETF 扫描器数据独立**：47 个 ETF/基准日线不包含在上述 72 文件中；2026-07-18 曾有 43 个陈旧，2026-07-24 Gateway 恢复后已用 `fetch_etf_data.py` 全部回补，覆盖至 2026-07-23（VIX 至 07-24），ETF 轮动扫描现可直接使用最新数据
- **SNDK**：2025-02-20 重新上市，历史数据有限（约1年）

## 告警格式

```
📊 NVDA 1h 做多信号
  价格: $887.5  ATR: $18.2
  Bull得分: 5/6  ADX: 32.4
  TP1: $905.7  TP2: $923.9  SL(utTS): $851.2
  时间: 2026-06-20 14:00 ET
```

## 信号的执行语义（人工执行时如何落地）

一条信号发出后，"什么时候该出场"由三个条件先到先算：

| 出场条件 | 依据 | 消息里有没有 |
|---|---|---|
| 触及 TP | `tp1`/`tp2`（Confluence 有；RSI2/MR 无固定 TP） | ✅ 有 |
| 触及 SL | `sl`（入场时刻快照值） | ✅ 有 |
| 时间止损 | 从**下一根 bar** 起数满 N 根仍未触发 TP/SL，按当根收盘价平仓 | ✅ 2026-07-25 起标注具体 bar 数与交易日 |

**时间止损的 N 取自该信号自身的策略参数**（`signal_log.csv` 的 `params_json.max_hold_bars`），不是全局固定值。换算成交易日要按上文"RTH 下每日 bar 数"：4h 的 10 根 = 5 个交易日，不是 2 个。

**SL 是入场快照，不是固定值**：Confluence 的 `SL(utTS)` 是 utTS 追踪线在入场时刻的读数，之后每根 bar 都会向有利方向移动；RSI2/MR 的 SL 同理（ATR 追踪）。消息只推送入场时的初始值，不再推送后续更新——人工执行时若要完全复刻策略，需自行按 `atr_trail_mult` 滚动上移止损。

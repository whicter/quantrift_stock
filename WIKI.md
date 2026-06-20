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

- **1h / 1d**：yfinance 直接下载
- **4h**：由 1h 重采样（OHLCV 聚合规则：O=first, H=max, L=min, C=last, V=sum）
- **数据存储**：`data/{SYMBOL}_{TF}_{start}_{end}.csv`
- **SNDK**：2025-02-20 重新上市，历史数据有限（约1年）

## 告警格式

```
📊 NVDA 1h 做多信号
  价格: $887.5  ATR: $18.2
  Bull得分: 5/6  ADX: 32.4
  TP1: $905.7  TP2: $923.9  SL(utTS): $851.2
  时间: 2026-06-20 14:00 ET
```

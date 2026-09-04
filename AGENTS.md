# quantrift_stock — AGENTS.md

> **语言规则**：只用中文或英文回复，绝对不能出现韩语或其他语言。

> **DO NOT send optional commentary.**

> 本项目仅发 Telegram 信号告警，**不下单**。

## 环境

| 项目 | 值 |
|---|---|
| Mac Studio hostname | `mac-studio`（用户 congrenhan） |
| 项目路径（Mac Studio） | `/Users/congrenhan/Documents/quantrift_stock` |
| 项目路径（本机） | `/Users/cohan/Documents/quantrift_stock` |
| Python（Mac Studio） | `/opt/homebrew/bin/python3.11` |
| IB Gateway 实盘端口 | 4001（只在 Mac Studio） |
| IB Gateway 模拟盘端口 | 4002 |
| clientId | **2**（期货引擎用 1，不能冲突） |
| GitHub remote | `git@github.com:whicter/quantrift_stock.git`（SSH） |

## 代码同步工作流

```bash
# 1. 把本机代码拷贝到 Mac Studio
rsync -av --exclude='.git' \
  /Users/cohan/Documents/quantrift_stock/ \
  mac-studio:/Users/congrenhan/Documents/quantrift_stock/

# 2. Mac Studio push 到 GitHub
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && git push"

# 3. 本机 pull GitHub repo
cd /Users/cohan/Documents/quantrift_stock && git pull origin master
```

## 常用命令

```bash
# 数据拉取（Mac Studio 上跑，连 IB Gateway）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py"

# 单标的单周期
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py --symbol NVDA --tf 1h"

# 补拉前审计、Gateway 恢复后的单标的验证、再合并全量历史
/opt/homebrew/bin/python3.11 data_audit.py --write
/opt/homebrew/bin/python3.11 fetch_ib_data.py --symbol NVDA --tf 1d --merge
/opt/homebrew/bin/python3.11 fetch_ib_data.py --merge
/opt/homebrew/bin/python3.11 fetch_data.py --merge  # IB HMDS 断连时的 yfinance 备用回补
/opt/homebrew/bin/python3.11 historical_backfill.py --write

# IB 不可用时用 yfinance 拉新标的数据（直接在 Mac Studio 跑）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 -c \"
import yfinance as yf, pandas as pd
from pathlib import Path
for sym in ['RKLB']:
    for tf, period, interval in [('1d','3y','1d'),('1h','60d','1h'),('4h','60d','1h')]:
        raw = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=True)
        df = raw[['Open','High','Low','Close','Volume']].rename(columns=str.lower)
        df.index.name = 'date'
        if df.index.tz: df.index = df.index.tz_convert('America/New_York').tz_localize(None)
        if tf == '4h':
            df = df.resample('4h',label='right',closed='right').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna(subset=['close'])
        df.to_csv(f'data/{sym}_{tf}.csv')
        print(f'{sym} {tf}: {len(df)} bars')
\""

# 数据同步回本机
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ /Users/cohan/Documents/quantrift_stock/data/

# 批量回测（本机跑）
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py --symbol NVDA --tf 1h

# 启动告警引擎（前台，--port 参数已不使用，保留兼容性）
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 alert_engine.py"

# 查看告警引擎状态
ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 status"

# 查看日志
ssh mac-studio "PATH=/opt/homebrew/bin:$PATH pm2 logs stock-alert --lines 50"

# git push（必须用 -A 转发 SSH agent）
ssh -A mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && git push"
```

**绝对不要做：**
- 不要在本机直接连 127.0.0.1:4001/4002
- git push 必须用 `ssh -A`，否则没有 GitHub 权限
- 不要在 alert_engine.py 里加任何下单逻辑

## 策略架构

- **核心文件**：`alert_engine.py`（信号监控）、`strategy.py`（ConfluenceStrategy）、`indicators.py`（compute_signals）、`config.yaml`（参数）
- **品种**：见 `config.yaml` symbols 列表
- **周期**：1h / 4h / 1d，三周期独立信号
- **策略路由**：`STRATEGY_MAP` 按 `(symbol, tf)` 路由到 confluence / rsi2 / breakout / mr；**未显式列出的组合不发信号**（2026-07-26 起取消默认 confluence fall-through）
- **52周突破**：`BREAKOUT_PARAMS` 独立配置（NVDA/MU/MSFT/PLTR/TSLA/AAPL + 2026-07-25 新增 DGRO/SPYM/VOO/VTI），仅日线
- **MR 均值回归**（2026-07-25 首次接入实时扫描）：`check_mr_signal()` + `MR_PARAMS`，只做多，入场 z-score≤-0.9 + RSI<40 + ADX<25 + close>200SMA，出场纯 ATR 追踪+时间止损（无固定TP）。目前仅 `TSM`(1h)/`FDVV`(1h) 接入；`mr_backtest.py` 存在多年但此前从未接入实时告警，是这次才补的缺口
- **RSI2-Trend 变体（2026-08-15）**：非独立策略，是 RSI2 + `{use_rs_filter:False, max_hold_bars:30}` 的参数覆盖，适配"长期趋势型"标的（200SMA上方≥65%、年化波动≤40%）。已接入 LLY/CSCO/ISRG/AVDV/VYM/DGRO/TSM/CRWD 的 1d。**8个标的共用同一套参数，不可逐标的调参**（泛化检验依赖于此）
- **出场模式**：`use_staged_tp=True`，止损用 utTS，TP1/TP2 固定 ATR 倍数
- **数据源（2026-07-27 起为混合架构）**：`fetch_bars()` 以 yfinance 为主（软限制，15分钟延时）；1d 近期缺 bar 用本地 IB 数据实时填补；yfinance 拉空时整段回退本地 IB 数据；本地 IB 数据由 `stock-nightly-ib-refresh`（每交易日 14:00 PT）自动 `--merge` 保鲜，最多落后一个交易日。引擎**不直连 IB**（历史教训：Error 162 crash-restart 循环）。单轮扫描拉取失败率 >20% 会发 Telegram 告警；财报日期按日缓存（省 ~90 请求/小时）。
- **完整 bar 语义（2026-07-27 起）**：信号只在**完整 bar** 上产生——盘中不再有 1d 信号（当日 bar 16:00 ET 收盘后才纳入），1h/4h 丢弃进行中的 bar；且信号仅在 bar 收盘后的新鲜窗口内发出（1h=4h/4h=12h/1d=30h），数据缺口或重启不补发陈旧信号。与回测"完整 bar 收盘决策"语义对齐。
- **想法级去重（2026-09-03 起）**：引擎此前没有持仓状态，只要入场条件还成立就
  每根 bar 重新播报同一个交易想法——90 天内 470 条信号其实只有 210 个独立想法，
  NVDA/RSI2 曾连播 5 天、QQQ 连播 12 条。判定「是否同一想法」用 `review_core`
  的出场逻辑（`_is_repeat_idea` + `data/.open_ideas.json`），与回测「一次交易」
  的定义完全对齐。重播仍写进 `signal_log`（`is_repeat=1`，账本记全）但不推送、
  不计入复盘。效果：推送 -42%，Confluence 均 R 从 +0.224 回到 +0.289（回测期望
  +0.285）——所谓的「Confluence 衰减」完全是这个口径造出来的假象。
- **4h 周期数据窗口**：`_YF_PERIOD["4h"] = "730d"`。此前是 `60d`，重采样只得
  ~119 根 4h bar，而 `check_rsi2_signal` 开头 `if len(df) < 210: return None`
  （SMA200 要 200 根）——**36 条 RSI2 4h 路由从上线起一条信号都没发过**，
  signal_log 里 RSI2/4h 历史累计为 0。730d 下有 ~1,707 根。
- **market_score 与回测对齐（2026-09-03 起）**：回测里「VIX>20」和「QQQ 跌破
  20 日低」两条罚分是并列的，期望表带着它们跑出来；实盘此前只搬了 VIX 那条，
  同一根 bar 的 score 比回测高 1 分，正好在大盘创新低最该收紧时放行。
  `vix_structural`(+0.5) 同样补上。
- **clientId**：IB 连接已从 alert_engine 移除，clientId=2 仅 fetch_ib_data.py 使用

### IB 历史数据运行状态（2026-07-24 已恢复）

- **HMDS 断连已解决**：2026-07-18 发现的 `2105: HMDS data farm connection is broken: ushmds` 于 2026-07-24 04:55 通过重启 Gateway 解决。经用户明确批准后执行 `quantrift_index_future/restart_gateway.sh`（SIGKILL + launchd `com.quantrift.ibc.plist` KeepAlive 自动拉起）；重启触发 Second Factor Authentication，用户在手机 IBKR App 批准后 05:02 登录完成，4001 端口恢复监听。
- **恢复序列已跑完**：① NVDA 1d 单标的验证成功（2512行）② `fetch_ib_data.py --merge` 全量补拉 42 次请求 0 失败 ③ `data_audit.py --write` 复审：全部 `fresh`，数据来源已从 `yfinance` 切回 `ib`，覆盖至 2026-07-23 ④ `historical_backfill.py --write` 重跑：7302 候选信号，9986 条已决，2135 条影子。
- **期货 bot 未受影响**：同机 8 个 `ib-bot*` pm2 进程重连期间 PID 和重启计数均未变化，未触发 crash-restart。
- **ETF 扫描器数据已回补**：`fetch_etf_data.py` 在 Gateway 恢复后重跑，47 个 ETF + SPY/QQQ + VIX 共 50 次请求全部成功；此前停留在 2026-06-17/18 的文件均已刷新至 2026-07-23（VIX 至 07-24）。ETF 扫描结果现可视为最新。
- **历史事实保留**：`fetch_ib_data.py` 对合约解析和历史请求仍保留 45 秒超时（当时用于诊断 HMDS 断连，现继续作为常规保护）；2026-07-18 曾用 `fetch_data.py --merge` 做 yfinance 备用回补覆盖 72 个文件，该记录仅作历史参考，当前数据源已是 IB。

## 后台任务（pm2，均已 pm2 save）

| 任务 | 时间 | 作用 |
|---|---|---|
| `stock-alert` | 常驻，每小时 | 主告警引擎（108标的/130条路由） |
| `stock-exec-ledger` | 常驻长轮询 | 执行账本，接收「接 NVDA 176.5」记录真实成交（**绝不下单**） |
| `stock-nightly-ib-refresh` | 交易日 14:00 PT | IB 全池 `--merge` 保鲜本地数据 |
| `stock-daily-screener` | 交易日 13:20 PT | 因子选股 Top15 → TG |
| `stock-watchlist-events-am` | 交易日 07:45 PT | 事件雷达·盘中 → TG |
| `stock-watchlist-events` | 交易日 13:35 PT | 事件雷达·收盘 → TG |
| `stock-weekly-review` | 周日 18:15 PT | 90天正股复盘+衰减监控 **+ 期权账本复盘** → TG |
| `stock-weekly-data-consolidate` | 周日 19:00 PT | 历史CSV迁外置盘留符号链接 |
| `stock-monthly-reval` | 每月1日 06:00 PT | rejected 池复检 |
| `stock-options-paper` | 每小时 :10 | 期权纸面模拟：对当轮新信号按 mid 开仓，正股出场时平仓（**绝不下单**） |
| `stock-options-whitelist` | 周三 11:00 PT | 盘中重测已路由标的期权价差/OI（**非交易时段拒绝运行**） |

## 期权纸面模拟（2026-08-15 起，绝不下单）

`options_paper.py` 在每轮扫描后 10 分钟运行：对**当轮新发出**的信号，按 **mid 价**
买入 ATM 期权并记账，正股策略出场时按 mid 平仓。

> **⚠️ 2026-09-03 之前的 136 笔记录全部作废**（账本里 `contaminated=1`，复盘自动
> 排除）。当时 `review_core.evaluate` 走到行情数据末尾会返回「时间止损」，于是
> 每个仓位开仓后一两根 bar 就被判为出场——中位持仓 6 小时、75% 不到 8 小时。
> 基于它得出的一切结论（赢输比、价差成本、持仓时长、「RSI2 用期权显著为负」）
> **均已撤回**。干净样本从 2026-09-03 起重新累积。原件 `.contaminated-20260903.bak`。

- 报价取 **yfinance 实时期权链**（options-lab 数据库 bid/ask 仅 7.6% 非空，
  只适合历史分析；它曾把 SMH/CSCO 误判为「期权太少」，实测 OI 分别 4650/2870）
- DTE = `clamp(持仓上限交易日 × 3.5, 30, 60)`，优先月度到期。**30 是硬下限**：
  低于 30 天的到期一律不选。理由是流动性不是 theta——实测同一标的近月 vs 次月
  ATM，PLTR OI 618→4,004、HOOD 208→3,161，价差双双腰斩。
- 准入看"有无真实双边市场"（OI≥50），**不按价差过滤**；账本同记保守口径
  （买ask/卖bid）供对照
- **出场判定与引擎同源**（`load_price()` → `alert_engine.fetch_bars`）。此前直接
  读本地 CSV，而本地由夜间 IB 任务保鲜、该任务会静默失败——25 个已路由标的的
  1h/4h 曾停在 8/21，导致之后开的仓 `future` 为空、出场判定永远得不出结果。
  信号用 yfinance 生成、出场却拿陈旧本地数据判，这个错配本身就是 bug。
- **金额口径**：`BUDGET_USD = 750`（与正股纸面组合 `RISK_PCT=0.75%` 同量级，
  两边盈亏才可比），记 `contracts` / `cost_usd` / `pnl_usd`。一张买不起就买一张，
  如实记真实成本。此前只记百分比，「到底赚了多少钱」根本算不出来。
- **归因字段**：入场与出场两端都记 IV 与标的价（`iv_entry`/`iv_exit`/
  `spot_entry`/`spot_exit`）。只有两端都有，才能把盈亏拆成「标的走了多少 /
  IV 变了多少 / 时间耗掉多少」，否则复盘只能说「亏了 3%」，回答不了亏在哪。
- **并发锁**（`data/.options_paper.lock`）：`main()` 只在结尾 `_save_state()`，
  两个实例同时跑会各自平掉同一批仓、各写一行账本。上线首月 149 行里有 23 行
  就是这么来的（已去重，原件 `.predupe-20260903.bak`）。
- 需要 `psycopg2-binary`（`options_liquidity.py` 读期权库时用）

### 期权账本复盘（`options_review.py`，2026-09-03 起）

期权账本从 8/15 上线到 9/3 **从未被复盘过**——`signal_review.py` 只看正股。
现已挂进 `run_weekly_review.sh`，周日随正股复盘一起推 TG。

核心指标是**捕获率**：正股每赚 1R 期权涨多少 %、每亏 1R 期权跌多少 %，两者之比。
孤立看期权盈亏无法区分"策略不行"和"期权这个载体不行"，捕获率把正股表现除掉，
只剩载体效率。赢输比配自助法 90% 区间一起看——点估计会骗人（污染样本时代
Confluence 点估计 1.20，区间却是 [0.23, 3.19]，什么都说明不了）。
复盘同时给美元口径，并自检账本质量（重复行、DTE 越界、作废样本、剩余 DTE）。

### 白名单重测（`options_whitelist.py`，2026-09-03 起）

两条硬约束，都是踩过坑写死的：

1. **非交易时段直接拒绝运行**。盘后做市商撤单放宽，同一张合约的价差是盘中
   的 3 倍（MU 2.3%→7.9%、PLTR 2.2%→7.6%）。用盘后数据筛白名单会把
   CSCO/LLY/JPM/QCOM/IBM/WMT 这些最流动的标的全部误杀。
2. **选合约直接调 `options_paper.pick_contract`**。按「30-60DTE 第一个到期」
   去测可能取到周度合约——实测 MU 周度 OI 只有 34、月度 3,777。测的必须是
   实盘真会买的那一张。

pm2 `stock-options-whitelist` 周三 11:00 PT（= 14:00 ET，盘中）跑。
**白名单在拿到盘中数据前不动。**

## 信号投递与降级（2026-08-15 起）

- **按板块合并推送**：本轮信号先入队，扫描结束按板块合并，每板块一条消息；
  同板块多条时附「⚠️ 同板块集中：做多N/做空M」——相关性集中度分开发时看不见。
  **不做任何过滤，全部信号照发**。
- **降级路由**：`logs/demoted_routes.json` 里的组合仍计算并记入 signal_log，
  但不推送。由 `decay_action.py`（连续红灯 → 自动重验证 → 双挂才降级）写入，
  **是数据不是代码**——无人值守任务不改 `STRATEGY_MAP` 源码。
- **衰减基准 = 同期回测（2026-09-03 起）**：`expectations.json` 的 `mean_r` 是
  十年长期均值，拿它判定最近 90 天等于把「这一季行情本来就不好」误读成「策略
  衰减」。实测同期回测 Confluence **-0.163**、RSI2 **-0.060**，而实盘（去重后）
  Confluence **+0.289** 其实是**跑赢**同期回测的。用长期均值当基准会在每段低于
  平均的行情里批量误报红灯 → 触发自动降级 → 正好把策略在最不该关的时候关掉。
  改用 `_same_period_baseline(90)`（读 `backfill_paper_equity.csv`，**只算真正
  开过仓的行**，`skip_*` 代表没开成的仓，混进来会稀释基准）；同期样本 <10 笔
  才退回长期均值。红灯从遍地收敛到 11 项。

## ⚠️ review_core 的「数据走完 ≠ 到持仓上限」（2026-09-03 修复）

**这是本项目迄今影响最大的一个 bug，整条模拟链都在量错东西。**

`review_core.evaluate` 三处 fallthrough 一律返回「时间止损」，分不清两件语义
完全相反的事：

| 情况 | 真实含义 | 修复前返回 |
|---|---|---|
| 走满了 `max_bars` | 仓位已了结 | 时间止损 ✅ |
| 行情数据就到这儿了 | **仓位还开着** | 时间止损 ❌ |

后果：

- `paper_portfolio.update()` 把每个刚开的仓在**下一轮扫描**就判为已平仓。
  484 笔里 459 笔是「时间止损」，平均持仓 **1.87 根 bar**，**68% 只持有 1 根
  bar**——而没有任何路由的持仓上限是 1。那条权益曲线量的根本不是策略，是
  「每笔交易一根 bar 就砍掉」。
- 权益因此从真实的 **+5.70%** 被记成 **-8.16%**（同期 SPY +4.19%）。
- `options_paper.close_finished()` 同样中招，账本里「持仓中位 6 小时」是这个
  bug 的产物，不是策略设计。**136 笔期权记录全部作废。**

修复：`if len(future) < max_bars: return {"outcome": "未决", ...}`。
未决返回保持各评估路径原有结构（测试靠 `"ambiguity"` 键判断走了哪条路径，
返回结构随出场与否而变会坑到调用方）。
原账本与持仓快照存 `logs/paper_equity.prebug-20260903.bak`、
`data/.paper_positions.prebug-20260903.bak`。

**教训**：凡是"回放到某个时点"的评估函数，「数据不够」和「条件达成」必须能
区分开。二者混同时，越是频繁调用（每小时扫描）错得越离谱，而且不报错、不崩溃，
只是安静地把所有统计量推向错误方向。

## 告警格式

```
📊 NVDA 1h 做多信号
  价格: $887.5  ATR: $18.2
  Bull得分: 5/6  ADX: 32.4
  TP1: $905.7  TP2: $923.9  SL(utTS): $851.2
```

## 回测工具

```bash
# 全量批跑（本机）
cd /Users/cohan/Documents/quantrift_stock && .venv/bin/python backtest_runner.py

# 单标的
.venv/bin/python backtest_runner.py --symbol NVDA

# 单标的单周期
.venv/bin/python backtest_runner.py --symbol NVDA --tf 1h

# 按不同指标排序
.venv/bin/python backtest_runner.py --sort sharpe   # 默认
.venv/bin/python backtest_runner.py --sort dd
```

## TODO

详见 `TASK.md`。

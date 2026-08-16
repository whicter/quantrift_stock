# quantrift_stock

Stock signal monitor with multi-strategy architecture.

**No order execution.** Signals are sent via Telegram only.

## Symbols

108 symbols across 130 explicit `(symbol, timeframe)` routes as of 2026-08-15.
Combinations not listed in `STRATEGY_MAP` emit nothing — there is no default
fall-through (removed 2026-07-26; see TASK.md section 5).

| Route family | Count | Notes |
|---|---|---|
| RSI2 v2 | 88 | Includes the 8 RSI2-Trend routes below |
| ConfluenceStrategy | 39 | Only strategy that shorts; 5 combos have `allow_short:false` |
| MR + ATR Trail | 3 | TSM/FDVV/MKSI 1h |
| Breakout 52W | 10 | `BREAKOUT_PARAMS`, daily only, runs alongside the above |

Every route is admitted through the same gate: Sharpe ≥ 0.6 at 10bps commission,
N ≥ 30 trades, and a 60/40 walk-forward whose test segment does not collapse.
Outcomes for every symbol ever tested — passing and failing — are in
`watchlist_history.csv`.

## Strategies

### 1. ConfluenceStrategy（高 beta 动量股）
- 6-component scoring: UTBot + SSL + RSI + MACD + Squeeze + CD Divergence
- ADX trend filter（only enter when ADX shows momentum）
- Staged TP exit: TP1 at 1×ATR, TP2 at 2×ATR, trail via sslExit

### 2. RSI2 + QQQ Filter + Relative Strength（大市值慢牛股 + ETF）
- Entry: close > 200 SMA AND RSI2 < threshold AND QQQ > 100 SMA (risk-on) AND stock 60d return > QQQ (relative strength)
- Exit: RSI2 > 80 OR ATR trailing stop OR time stop
- Best results: MSFT 4h (Sharpe 1.13), SOXX 1h (Sharpe 1.14)

### 3. RSI2-Trend（长期趋势型变体，2026-08-15）
- Not a separate strategy: the RSI2 engine with `use_rs_filter=False` and
  `max_hold_bars=30`, applied via `RSI2_PARAMS`
- Motivation: RSI2's relative-strength gate is meaningless for non-tech names
  (a pharma company need not outperform the Nasdaq to be worth buying), and a
  10-bar time stop ejects slow trends before they develop
- Routed on 1d for LLY, CSCO, ISRG, AVDV, VYM, DGRO, TSM, CRWD
- All eight share byte-identical parameters deliberately. The evidence for this
  variant is a pre-registered generalization test — the config was frozen, a
  target class was defined in advance (above 200SMA ≥65%, annualized vol ≤40%),
  and it was applied unchanged to all 223 evaluable symbols; 8 of the 10 that
  cleared the bar belong to that class against a 30% base rate. Per-symbol
  tuning would dissolve that argument into eight separate in-sample fits.

### 4. Options paper simulation (2026-08-15, no orders)

Not a signal strategy -- a measurement layer. When a signal fires,
`options_paper.py` buys an ATM option at the midpoint and closes it when the
underlying strategy exits, so option P&L can be compared against the stock's
theoretical R.

- Quotes come from yfinance's live chain. The options-lab Postgres has 320k
  contract snapshots but only 7.6% carry bid/ask and its cadence doesn't line
  up with our scans, so it's used for liquidity and IV history instead.
- Expiry targets `clamp(hold_days x 3.5, 30, 60)` and prefers monthlies. The
  cap matters: LLY's 30-day hold extrapolates to 105 DTE where open interest is
  39, against 602 at 34 DTE. Back-month theta savings don't cover that.
- 84 symbols qualify, admitted on whether a two-sided market exists (OI >= 50),
  not on spread width. Both mid-to-mid and ask-to-bid fills are recorded; their
  difference is the spread cost.
- Long-hold strategies and options are structurally mismatched -- the longer the
  hold, the further out the expiry, and the thinner the market. The RSI2-Trend
  routes (LLY aside) trade the underlying only.

### 5. MR + ATR Trail（均值回归）
- Entry: z-score ≤ −0.9 (near BB lower band) AND RSI < 40 AND ADX < 25 AND close > 200 SMA
- Exit: ATR trailing stop（不在中轨止盈，让趋势跑起来）
- Originally researched for broad ETFs (SOXX/SMH/QQQ/SPY) but paused for insufficient sample size across the board (see LEARNING.md); those four still run on RSI2 in production
- **2026-07-25**: first live deployment via `check_mr_signal()`, discovered through the watchlist batch probe rather than the original broad-ETF research — currently `TSM` (1h) and `FDVV` (1h) only, on unoptimized default params

## Timeframes

1h / 4h / 1d (independent signals per timeframe)

## Setup

```bash
pip install backtesting pandas yfinance pyyaml requests
pip install psycopg2-binary        # options_liquidity.py reads the options-lab PG

# Audit local coverage, then merge an IB refresh (Mac Studio only)
/opt/homebrew/bin/python3.11 data_audit.py --write
/opt/homebrew/bin/python3.11 fetch_ib_data.py --merge

# Sync data to local
rsync -av mac-studio:/Users/congrenhan/Documents/quantrift_stock/data/ /Users/cohan/Documents/quantrift_stock/data/

# Run backtests (local)
.venv/bin/python backtest_runner.py          # ConfluenceStrategy
.venv/bin/python rsi2_backtest.py            # RSI2 strategy
.venv/bin/python mr_backtest.py              # MR + ATR Trail

# Optimize parameters
.venv/bin/python rsi2_backtest.py --optimize
.venv/bin/python mr_backtest.py --optimize

# Start alert engine (Mac Studio only)
/opt/homebrew/bin/python3.11 alert_engine.py
```

## Architecture

```
yfinance (primary, 15-min delayed)      IB Gateway :4001 (clientId=2)
        │                                       │
        │  gaps / empty responses               │  fetch_ib_data.py --merge
        └──────────► data/*.csv ◄───────────────┘  (nightly 14:00 PT)
                        │
                   alert_engine.py   ── signals only on COMPLETE, FRESH bars
                        ├── route via STRATEGY_MAP (no default fall-through)
                        ├── skip routes listed in logs/demoted_routes.json
                        ├── queue signals, flush grouped BY SECTOR
                        └── Telegram alert (NEVER places orders)
                                    │
                   execution_ledger.py ◄── your replies ("接 NVDA 176.5")
                        └── logs/execution_log.csv = realized fills vs signals

                   options_paper.py  (:10, after each scan)
                        ├── yfinance live chain → ATM, monthly expiry
                        ├── DTE = clamp(hold_days x 3.5, 30, 60)
                        └── logs/options_paper_log.csv = option vs stock P&L
```

The engine never dials IB directly: its hourly scan needs ~300 historical
requests against a 60-per-10-minute Gateway quota shared with the futures
bots, which produced an Error 162 crash-restart loop in early July. IB feeds
the local store on a nightly schedule instead, and that store backfills
yfinance gaps and covers outright fetch failures.

## Files

| File | Purpose |
|---|---|
| `config.yaml` | Strategy parameters per symbol/timeframe |
| `indicators.py` | Technical indicators (UTBot, SSL, ADX, ATR, …) |
| `strategy.py` | ConfluenceStrategy (backtesting.py) |
| `signals.py` | Signal computation for ConfluenceStrategy |
| `mr_signals.py` | Signal computation for MR strategy |
| `mr_strategy.py` | MeanReversionStrategy (backtesting.py) |
| `mr_backtest.py` | MR + ATR Trail backtest runner & optimizer |
| `check_mr_signal()` (in `alert_engine.py`) | Live MR entry check (2026-07-25), mirrors `mr_strategy.py`'s rule directly rather than importing it |
| `ema_signals.py` | Signal computation for EMA Pullback (archived) |
| `ema_strategy.py` | EMABounceStrategy (archived, WR too low) |
| `ema_backtest.py` | EMA Pullback backtest runner (archived) |
| `rsi2_backtest.py` | RSI2 strategy: signals + strategy + runner + optimizer |
| `fetch_data.py` | Download OHLCV data via yfinance |
| `fetch_ib_data.py` | Download OHLCV data via IB Gateway |
| `backtest_runner.py` | Batch backtest (ConfluenceStrategy) |
| `alert_engine.py` | Live signal monitor, Telegram-only |
| `review_core.py` | 与实盘状态机对齐的逐 bar 复盘引擎 |
| `paper_portfolio.py` | 虚拟持仓、暴露警示与净值账本（无下单） |
| `signal_review.py` | 信号复盘、质量校准、衰减监控与 Meta-label 训练 |
| `decay_action.py` | 红灯连续N周 → 自动重验证 → 双挂才降级（写 `logs/demoted_routes.json`，不改代码） |
| `execution_ledger.py` | Telegram 长轮询记录真实成交，绝不下单 |
| `sector_map.py` | 标的→板块映射（带缓存），供信号按板块合并推送 |
| `options_paper.py` | 期权纸面模拟：信号当下按 mid 买 ATM，正股出场时平仓（**不下单**） |
| `options_liquidity.py` | 按各路由持仓上限匹配 DTE，筛出期权流动性够的标的 |
| `consolidate_data.py` | 历史行情CSV迁外置盘，本地留符号链接（幂等，每周自动） |
| `confluence_direction_test.py` / `rsi2_ibs_test.py` | 多空腿分离 / IBS过滤器 对照验证（研究脚本） |
| `harmonic_signals.py` / `harmonic_strategy.py` / `harmonic_backtest.py` | 谐波形态原型（研究用，样本不足未接入） |
| `CLAUDE.md` | Claude Code instructions |
| `TASK.md` | Pending tasks |
| `LEARNING.md` | Backtest observations and strategy findings |

## Alert Format

```
📊 NVDA 1h 做多信号
  价格: $887.5  ATR: $18.2
  Bull得分: 5/6  ADX: 32.4
  TP1: $905.7  TP2: $923.9  SL(utTS): $851.2
```

## Review Loop

```bash
.venv/bin/python signal_review.py --days 90 --monitor
.venv/bin/python signal_review.py --days 90 --monitor --train-meta
```

`run_weekly_review.sh` is the scheduled entry point; install the line in
`crontab.example` on Mac Studio. Meta-label training is intentionally blocked
until at least 150 resolved signals exist.

## Historical Data Audit

```bash
.venv/bin/python data_audit.py --write
```

This is read-only. It writes a coverage report and an IB refresh plan under
`logs/`. On 2026-07-18, the IB plan could not run because `ushmds` was
offline; `fetch_data.py --merge` refreshed all 72 configured `symbol × tf`
files through yfinance as a stopgap. As of 2026-07-24 the audit runs against
live IB data again: all 72 files report fresh with `source=ib`, coverage
through 2026-07-23. The 2026-07-18 yfinance pass is kept only as a historical
record in `data/.data_sources.json`.

This audit covers the alert/backfill symbol pool only. The ETF rotation scanner
maintains a separate 47-symbol daily dataset. It was stale as of 2026-07-18
(43 files behind); after the IB Gateway recovery on 2026-07-24, `fetch_etf_data.py`
was rerun and all 50 requests (47 ETFs + SPY/QQQ + VIX) succeeded — every file
is now current through 2026-07-23 (VIX through 07-24).

### IB Status (resolved 2026-07-24)

The `2105: HMDS data farm connection is broken: ushmds` condition reported on
2026-07-18 was resolved on 2026-07-24 04:55 by restarting IB Gateway, with
explicit user approval, via `quantrift_index_future/restart_gateway.sh`
(SIGKILL + launchd `com.quantrift.ibc.plist` KeepAlive auto-restart). The
restart triggered a Second Factor Authentication prompt that blocked
automatic login; the user approved it on the IBKR mobile app, and login
completed at 05:02 with port 4001 listening again.

Recovery sequence executed in full: a single-symbol NVDA 1d request succeeded
(2512 rows), `fetch_ib_data.py --merge` completed 42/42 requests with zero
failures, `data_audit.py --write` reported all files fresh with `source=ib`
through 2026-07-23, and `historical_backfill.py --write` re-ran producing
7,302 candidate signals (9,986 decided, 2,135 shadow). The 8 co-located
futures bots (`ib-bot*` under pm2) kept the same PID and restart count
throughout — no crash-restart was triggered.

`fetch_ib_data.py` still bounds contract and historical requests to 45
seconds as a standing safeguard, independent of this incident.

If the IB historical-data farm goes offline again before this is fixed
upstream, the same yfinance fallback used on 2026-07-18 remains available:

```bash
/opt/homebrew/bin/python3.11 fetch_data.py --merge
```

It preserves older bars, updates duplicate timestamps from yfinance, records
the source manifest, and limits every yfinance request to 20 seconds.

## Historical Backfill

```bash
.venv/bin/python historical_backfill.py --write
```

This replays only local OHLCV into the isolated
`logs/backfill_signal_log.csv` and `logs/backfill_paper_equity.csv` ledgers.
It never sends Telegram messages, writes to the live signal ledger, or connects
to IB. The paper ledger fixes 0.75% dollar risk when each position opens,
allows at most 10 simultaneous positions, and records semiconductor-exposure
warnings. It intentionally does not simulate Pyramiding until that state
machine is implemented and verified.

The latest replay (2026-07-18, refreshed yfinance CSVs through 2026-07-17)
contains 6,285 candidates, including 1,813 shadow candidates. It is historical
simulation data, not live-signal evidence.

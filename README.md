# quantrift_stock

Stock signal monitor with multi-strategy architecture.

**No order execution.** Signals are sent via Telegram only.

## Symbols

| Group | Tickers | Strategy |
|---|---|---|
| High-beta momentum | NVDA, TSLA, SNDK, MU, STX, MRVL | ConfluenceStrategy |
| Large-cap slow-trend | MSFT, GOOGL, META, AAPL, AMZN | RSI2 + QQQ filter + RS filter |
| Broad ETFs | SOXX, SMH, QQQ, SPY | RSI2 or MR + ATR Trail |

## Strategies

### 1. ConfluenceStrategy（高 beta 动量股）
- 6-component scoring: UTBot + SSL + RSI + MACD + Squeeze + CD Divergence
- ADX trend filter（only enter when ADX shows momentum）
- Staged TP exit: TP1 at 1×ATR, TP2 at 2×ATR, trail via sslExit

### 2. RSI2 + QQQ Filter + Relative Strength（大市值慢牛股 + ETF）
- Entry: close > 200 SMA AND RSI2 < threshold AND QQQ > 100 SMA (risk-on) AND stock 60d return > QQQ (relative strength)
- Exit: RSI2 > 80 OR ATR trailing stop OR time stop
- Best results: MSFT 4h (Sharpe 1.13), SOXX 1h (Sharpe 1.14)

### 3. MR + ATR Trail（宽基 ETF 高胜率方案）
- Entry: z-score ≤ −0.9 (near BB lower band) AND RSI < 40 AND ADX < 25 AND close > 200 SMA
- Exit: ATR trailing stop（不在中轨止盈，让趋势跑起来）
- Best results: SOXX 1d (Sharpe 0.71, WR 61.9%, RR 3.41)

## Timeframes

1h / 4h / 1d (independent signals per timeframe)

## Setup

```bash
pip install backtesting pandas yfinance pyyaml requests

# Download historical data (run on Mac Studio with IB Gateway)
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 fetch_ib_data.py"

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
ssh mac-studio "cd /Users/congrenhan/Documents/quantrift_stock && /opt/homebrew/bin/python3.11 alert_engine.py --port 4002"
```

## Architecture

```
IB Gateway :4001 (real) / :4002 (paper)
  └── alert_engine.py  clientId=2
        ├── fetch bars for each symbol × timeframe
        ├── compute_signals() / RSI2 signals
        ├── check entry conditions (per strategy)
        └── send Telegram alert (NO orders placed)
```

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
| `ema_signals.py` | Signal computation for EMA Pullback (archived) |
| `ema_strategy.py` | EMABounceStrategy (archived, WR too low) |
| `ema_backtest.py` | EMA Pullback backtest runner (archived) |
| `rsi2_backtest.py` | RSI2 strategy: signals + strategy + runner + optimizer |
| `fetch_data.py` | Download OHLCV data via yfinance |
| `fetch_ib_data.py` | Download OHLCV data via IB Gateway |
| `backtest_runner.py` | Batch backtest (ConfluenceStrategy) |
| `alert_engine.py` | Live signal monitor, Telegram-only |
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

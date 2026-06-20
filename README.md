# quantrift_stock

Stock signal monitor using the same Confluence strategy as `quantrift_index_future`.

**No order execution.** Signals are sent via Telegram only.

## Symbols

| Group | Tickers |
|---|---|
| MAG7 | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA |
| Semis | SNDK, MU, STX, MRVL |
| ETFs | SOXX, SMH, QQQ, SPY |

## Strategy

Same ConfluenceStrategy as the futures engine:
- 6-component scoring: UTBot + SSL + RSI + MACD + Squeeze + CD Divergence
- ADX trend filter
- Volume confirmation
- Staged TP exit (TP1 at 1×ATR, TP2 at 2×ATR, trail remainder via sslExit)

## Timeframes

1h / 4h / 1d (independent signals per timeframe)

## Setup

```bash
pip install backtesting pandas yfinance pyyaml requests

# Download historical data
python fetch_data.py

# Run backtests on all symbols
python backtest_runner.py

# Start alert engine (requires IB Gateway on :4001 or :4002)
python alert_engine.py --port 4002
```

## Architecture

```
IB Gateway :4001 (real) / :4002 (paper)
  └── alert_engine.py  clientId=2
        ├── fetch bars for each symbol × timeframe
        ├── compute_signals()
        ├── check entry conditions
        └── send Telegram alert (NO orders placed)
```

## Files

| File | Purpose |
|---|---|
| `config.yaml` | Strategy parameters per timeframe |
| `indicators.py` | Technical indicators (UTBot, SSL, ADX, …) |
| `strategy.py` | ConfluenceStrategy (backtesting.py) |
| `fetch_data.py` | Download OHLCV data via yfinance |
| `backtest_runner.py` | Batch backtest all symbols |
| `alert_engine.py` | Live signal monitor, Telegram-only |
| `CLAUDE.md` | Claude Code instructions |
| `TASK.md` | Pending tasks |
| `WIKI.md` | Strategy documentation |
| `LEARNING.md` | Observations and findings |

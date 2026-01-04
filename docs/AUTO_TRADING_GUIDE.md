# Automated Trading Guide

This guide explains how to use the automated trading system to automatically place trades on Kalshi when the model predicts a value edge.

## Overview

The automated trading system (`AutoTrader`) continuously scans Kalshi markets for tennis matches and automatically places trades when:
- Model prediction is **2% or more** higher than Kalshi's price (configurable)
- Expected value meets minimum threshold (default 5%)
- Market meets liquidity requirements (minimum volume)

## Quick Start

### 1. Dry Run (Recommended First)

Test the system without placing real orders:

```bash
python scripts/trading/run_auto_trader.py --dry-run
```

This will:
- Scan markets every 60 seconds
- Identify opportunities with 2%+ value edge
- Log what trades *would* be placed (but don't actually place them)

### 2. Single Scan

Run one scan and exit (useful for testing):

```bash
python scripts/trading/run_auto_trader.py --once --dry-run
```

### 3. Live Trading

**⚠️ WARNING: This will place real orders with real money!**

```bash
python scripts/trading/run_auto_trader.py --live
```

You'll be prompted to confirm before starting.

## Configuration Options

### Minimum Value Threshold

Set the minimum value edge required to trade (default: 2%):

```bash
# More conservative: 5% minimum edge
python scripts/trading/run_auto_trader.py --min-value 0.05 --dry-run

# More aggressive: 1% minimum edge
python scripts/trading/run_auto_trader.py --min-value 0.01 --dry-run
```

### Position Sizing

Control maximum contracts per trade:

```bash
# Smaller positions (max 5 contracts)
python scripts/trading/run_auto_trader.py --max-size 5 --dry-run

# Larger positions (max 20 contracts)
python scripts/trading/run_auto_trader.py --max-size 20 --dry-run
```

### Scan Frequency

Adjust how often markets are scanned:

```bash
# Scan every 30 seconds (faster)
python scripts/trading/run_auto_trader.py --scan-interval 30 --dry-run

# Scan every 5 minutes (slower, less API usage)
python scripts/trading/run_auto_trader.py --scan-interval 300 --dry-run
```

### Market Filters

Only trade markets closing soon and with sufficient volume:

```bash
# Only trade markets closing within 24 hours
python scripts/trading/run_auto_trader.py --max-hours 24 --dry-run

# Only trade markets with $5,000+ volume
python scripts/trading/run_auto_trader.py --min-volume 5000 --dry-run
```

### Expected Value Threshold

Set minimum expected value:

```bash
# Require 10% expected value
python scripts/trading/run_auto_trader.py --min-ev 0.10 --dry-run
```

## How It Works

1. **Market Scanning**: Every N seconds (default 60), the system scans Kalshi for tennis markets
2. **Opportunity Identification**: For each market, it:
   - Parses player names from market title
   - Matches players to database
   - Generates model prediction
   - Compares to Kalshi's current price
   - Calculates value edge and expected value
3. **Trade Execution**: If opportunity meets thresholds:
   - Calculates position size based on value edge
   - Checks for existing positions (avoids duplicates)
   - Places limit order at best bid price
   - Logs trade details

## Risk Management

The system includes several risk management features:

- **Position Sizing**: Scales position size based on value edge (more edge = larger position, up to max)
- **Duplicate Prevention**: Tracks traded markets to avoid placing multiple orders for the same market
- **Existing Position Check**: Checks Kalshi for existing positions before trading
- **Volume Filtering**: Only trades markets with sufficient liquidity
- **Time Window**: Only trades markets closing soon (default 48 hours)

## Logging

All trades and scans are logged to:
- Console output (real-time)
- `logs/auto_trader.log` (persistent log file)

Log entries include:
- Timestamp
- Market ticker and title
- Value edge and expected value
- Position size and price
- Order status

## Monitoring

While the trader is running, you'll see output like:

```
2024-01-15 10:30:00 - INFO - Starting market scan...
2024-01-15 10:30:05 - INFO - Found 3 tradable opportunities
2024-01-15 10:30:06 - INFO - [DRY RUN] Would place order: {'ticker': 'KXATPMATCH-...', 'side': 'yes', 'action': 'buy', 'count': 5, 'price': 62}
2024-01-15 10:30:06 - INFO -   Opportunity: Will Novak Djokovic win the Djokovic vs Nadal match?
2024-01-15 10:30:06 - INFO -   Value edge: 3.2%
2024-01-15 10:30:06 - INFO -   Expected value: 6.5%
2024-01-15 10:30:07 - INFO - Placed 1 trades in this scan
```

## Best Practices

1. **Start with Dry Run**: Always test with `--dry-run` first to understand behavior
2. **Conservative Thresholds**: Start with higher thresholds (5% value, 10% EV) and lower position sizes
3. **Monitor Closely**: Watch the logs and trades, especially when first going live
4. **Set Limits**: Use `--max-size` to limit position sizes
5. **Time Windows**: Use `--max-hours` to only trade markets closing soon (reduces risk)
6. **Volume Requirements**: Use `--min-volume` to ensure sufficient liquidity

## Troubleshooting

### No trades being placed

- Check that markets meet all thresholds (value, EV, volume, time window)
- Verify Kalshi API credentials are set correctly
- Check logs for error messages

### Too many trades

- Increase `--min-value` threshold
- Increase `--min-ev` threshold
- Decrease `--max-size`
- Increase `--min-volume`

### API errors

- Check Kalshi API credentials in `.env` file
- Verify network connection
- Check Kalshi API status

## Example Commands

```bash
# Conservative dry run
python scripts/trading/run_auto_trader.py \
  --dry-run \
  --min-value 0.05 \
  --min-ev 0.10 \
  --max-size 5 \
  --min-volume 5000

# Aggressive live trading (use with caution!)
python scripts/trading/run_auto_trader.py \
  --live \
  --min-value 0.02 \
  --min-ev 0.05 \
  --max-size 10 \
  --scan-interval 30

# Single scan test
python scripts/trading/run_auto_trader.py \
  --once \
  --dry-run \
  --min-value 0.02
```

## Safety Features

- **Dry Run Default**: Default mode is dry-run (simulation)
- **Confirmation Required**: Live trading requires explicit `--live` flag and confirmation
- **Position Tracking**: Tracks all trades to prevent duplicates
- **Error Handling**: Gracefully handles API errors and continues running
- **Logging**: Comprehensive logging for audit trail


# How to Run the System

## Architecture Overview

```
Kalshi API
   ↑
Market Data Service (port 5002) - ONLY place that calls Kalshi
   ↑
UI (port 5001) + run.py - ONLY read from service
```

## Step-by-Step Instructions

### 1. Start Market Data Service (REQUIRED FIRST)

**Terminal 1:**
```bash
cd /Users/ethanlung/Documents/projects/tennis-ml-model
python market_data_service.py
```

**What you'll see:**
```
Initializing Market Data Service...
Performing initial market fetch...
FETCHING FROM KALSHI
Fetched 24 markets from KXATPMATCH
Fetched 34 markets from KXWTAMATCH
Fetched 12 markets from KXUNITEDCUPMATCH
Initial cache populated
Background poller started
Starting Market Data Service on http://localhost:5002
```

**Keep this running** - it polls Kalshi every 12 seconds in the background.

### 2. Start Main UI

**Terminal 2:**
```bash
cd /Users/ethanlung/Documents/projects/tennis-ml-model
python app/app.py
# or
python run.py
```

**What you'll see:**
```
Initializing Tennis Trading System...
Loading player statistics database...
Loading prediction models...
Initializing Kalshi analyzer...
✅ Kalshi analyzer initialized
✅ Auto trader initialized
✅ System initialized successfully
 * Running on http://localhost:5001
```

**Open in browser:** `http://localhost:5001`

### 3. (Optional) Run Trading Engine

If you want to run automated trading separately:

**Terminal 3:**
```bash
cd /Users/ethanlung/Documents/projects/tennis-ml-model
python scripts/trading/run_auto_trader.py
```

## Verification

### Check Market Data Service is Working

```bash
# Check health
curl http://localhost:5002/health

# Should return:
# {
#   "status": "ok",
#   "generated_at": 1234567890,
#   "age_seconds": 5,
#   "polling_active": true
# }
```

### Check UI is Using Service

1. Open browser: `http://localhost:5001`
2. Check "Top Trading Opportunities" section
3. Watch Market Data Service logs - you should see "FETCHING FROM KALSHI" every 12 seconds
4. Spam refresh UI - you should NOT see "FETCHING FROM KALSHI" (proves UI uses cache)

## Troubleshooting

### Port 5002 Already in Use

```bash
# Find what's using it
lsof -ti:5002

# Kill it
kill <PID>

# Or change port in market_data_service.py (line ~266)
port = 5003  # or any other port
```

### Market Data Service Can't Connect to Kalshi

- Check Kalshi credentials in `config/settings.py`
- Check `keys/kalshi_private_key.txt` exists
- Check `KALSHI_ACCESS_KEY` environment variable

### UI Shows "No opportunities"

- Make sure Market Data Service is running
- Check service logs for errors
- Verify service is returning markets: `curl http://localhost:5002/markets`

### UI Still Calling Kalshi Directly

- Check browser console for errors
- Check Flask app logs
- Verify `MARKET_DATA_SERVICE_URL` in `app/app.py` is correct

## Quick Start (All in One)

```bash
# Terminal 1: Market Data Service
python market_data_service.py

# Terminal 2: Main UI  
python app/app.py
```

Then open `http://localhost:5001` in your browser.

## Important Notes

✅ **Market Data Service MUST be running first** - UI and trading engine depend on it  
✅ **Only Market Data Service calls Kalshi** - UI and run.py never touch Kalshi API  
✅ **Service polls every 12 seconds** - UI auto-refreshes every 15 seconds  
✅ **If service is down** - UI will show empty results (no Kalshi fallback)


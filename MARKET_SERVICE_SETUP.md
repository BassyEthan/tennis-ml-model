# Market Data Service Setup

## Quick Start

### 1. Start the Market Data Service

```bash
python market_data_service.py
```

The service will:
- Start on `http://localhost:5002`
- Fetch markets from Kalshi every 12 seconds
- Cache data in memory for fast access

### 2. Start Your Main UI

```bash
python app/app.py
# or
python run.py
```

Your UI will now:
- Read markets from the fast cache service (`http://localhost:5002/markets`)
- Never call Kalshi API directly in request handlers
- Fall back to direct Kalshi calls if service is unavailable

## Architecture

```
┌─────────────────┐
│  Market Data    │  ← Polls Kalshi every 12s
│  Service        │  ← Caches in memory
│  (port 5002)    │
└────────┬────────┘
         │ HTTP GET /markets
         │ (<5ms response)
         ▼
┌─────────────────┐
│  Main UI        │  ← Reads from cache
│  (port 5001)    │  ← Never calls Kalshi
└─────────────────┘
```

## Benefits

✅ **Fast**: Request handlers respond in <5ms (vs 100-500ms from Kalshi)  
✅ **Reliable**: API failures don't block UI requests  
✅ **Rate Limited**: Centralized polling prevents exceeding Kalshi limits  
✅ **Decoupled**: UI never touches Kalshi SDK directly

## Verification

Run the test script to verify everything works:

```bash
python test_market_service.py
```

## Troubleshooting

**Service won't start:**
- Check if port 5002 is available: `lsof -ti:5002`
- Check Kalshi credentials in `config/settings.py`

**UI can't connect:**
- Make sure market data service is running first
- Check `MARKET_DATA_SERVICE_URL` in `app/app.py` (default: `http://localhost:5002`)
- UI will fallback to direct Kalshi calls if service unavailable


# System Architecture & Data Flow

## 🎯 Core Principle

**Market Data Service is the ONLY place that calls Kalshi API.**
Everything else (UI, trading engine) reads from the service via HTTP.

---

## 📊 Current Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    KALSHI API (External)                        │
│              (Rate-limited, slow, unreliable)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ (Called every 12 seconds)
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│         MARKET DATA SERVICE (market_data_service.py)             │
│                    Port: 5002                                    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Background Polling Thread (runs every 12s)              │  │
│  │  - fetch_markets_from_kalshi()                           │  │
│  │  - Fetches: markets, prices, orderbooks, volume         │  │
│  │  - Enriches with orderbook data                          │  │
│  │  - Atomically updates in-memory cache                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  In-Memory Cache (thread-safe)                           │  │
│  │  {                                                        │  │
│  │    "generated_at": 1234567890,                           │  │
│  │    "markets": {                                           │  │
│  │      "markets": [...],  # List of market objects         │  │
│  │      "total_count": 150,                                 │  │
│  │      "enriched_count": 100                               │  │
│  │    }                                                      │  │
│  │  }                                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  HTTP Endpoints:                                                │
│  - GET /markets → Returns cached snapshot (<5ms)               │
│  - GET /health → Returns status + cache age                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ HTTP GET requests
                             │ (Fast, no Kalshi calls)
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
        ▼                                         ▼
┌──────────────────────┐              ┌──────────────────────┐
│   UI (app/app.py)    │              │  Trading Engine      │
│   Port: 5001         │              │  (auto_trader.py)     │
│                      │              │                      │
│  - /api/opportunities│              │  - scan_and_trade()  │
│    → Reads from      │              │    → Reads from      │
│      service         │              │      service         │
│                      │              │                      │
│  - Displays to user  │              │  - Places trades     │
│  - Auto-refreshes    │              │  - Uses cached data  │
│    every 15s         │              │                      │
└──────────────────────┘              └──────────────────────┘
```

---

## 🔄 Data Flow Example

### Scenario: User opens UI and views opportunities

1. **User opens browser** → `http://localhost:5001`

2. **UI JavaScript** → Calls `GET /api/opportunities`

3. **app/app.py** → `get_opportunities()` function:
   ```python
   # Makes HTTP request to market data service
   response = requests.get("http://localhost:5002/markets", timeout=2)
   markets = response.json()["markets"]["markets"]  # Extract list
   
   # Passes to analyzer (NO Kalshi call)
   tradable = kalshi_analyzer.scan_markets(markets=markets)
   ```

4. **Market Data Service** → Returns cached data from memory (<5ms)

5. **UI** → Displays opportunities to user

**Key Point:** At no point does the UI call Kalshi API. It only reads from the service.

---

## ✅ Architecture Complete - All Direct Kalshi Calls Removed

**Status:** All direct Kalshi API calls have been removed from `auto_trader.py`.

**What was fixed:**
1. **`place_trade()` method** - Now uses `_get_match_timing_from_service()` instead of `self.client.get_markets()`
2. **`scan_and_trade()` method** - Now uses cached match timing from service instead of direct Kalshi call

**How it works:**
- Market Data Service extracts and caches match timing information (`match_times` lookup map)
- `auto_trader.py` has a helper method `_get_match_timing_from_service()` that reads from service cache
- Both methods now use cached timing data (no Kalshi calls)
- Match timing is cached when markets are fetched in `scan_and_trade()`, avoiding repeated service calls

---

## ✅ What's Working Correctly

1. **Market Data Service** - Only place that calls Kalshi ✅
2. **UI (`app/app.py`)** - Only reads from service ✅
3. **Trading Engine (`scan_and_trade()`)** - Reads markets from service ✅
4. **Trading Engine (`place_trade()`)** - Uses service cache for match timing ✅
5. **Background Polling** - Runs every 12s, updates cache atomically ✅
6. **Thread Safety** - Cache updates are atomic, readers never see partial data ✅
7. **Match Timing** - Extracted and cached by service, no direct Kalshi calls ✅

---

## 🎯 Why This Architecture?

### Benefits:

1. **Speed** - UI/engine read from memory (<5ms) vs Kalshi API (500ms-2s)
2. **Rate Limit Protection** - Only 1 caller (service) instead of multiple
3. **Reliability** - Service handles failures gracefully, serves stale data if needed
4. **Decoupling** - UI/engine don't depend on Kalshi SDK or API directly
5. **Consistency** - All components see the same snapshot of market data

### How It Prevents Rate Limiting:

- **Before:** UI + Trading Engine + Manual scripts = 3+ callers → Rate limit exceeded
- **After:** Only Market Data Service calls Kalshi (every 12s) → Well under rate limit

---

## 🚀 How to Run

See `RUN_INSTRUCTIONS.md` for step-by-step guide.

**TL;DR:**
1. Start Market Data Service first (Terminal 1)
2. Start UI (Terminal 2)
3. Both read from service, never call Kalshi directly

---

## 🔍 Verification

**Check 1: Prove requests never call Kalshi**
- Spam refresh UI → Watch Market Data Service logs
- Should see "FETCHING FROM KALSHI" every 12s (background poller)
- Should NOT see it when you refresh UI (proves UI uses cache)

**Check 2: Prove staleness handling**
- Break Kalshi API key temporarily
- `/markets` still responds (serves stale cache)
- `/health` shows increasing `age_seconds`


# Simple Explanation: How Everything Works Together

## 🎯 The Big Picture (30-Second Version)

You have **3 main pieces** that work together:

1. **Market Data Service** - Fetches tennis match data from Kalshi, stores it in memory
2. **UI (Web Interface)** - Shows you opportunities and lets you trade
3. **Trading Engine** - Automatically finds good bets and places trades

**The key rule:** Only the Market Data Service talks to Kalshi. Everything else talks to the Market Data Service.

---

## 🏗️ The Three Components

### 1. Markeetween Kalshi t Data Service (Port 5002)
**Job:** Be the middleman band everything else

**IMPORTANT: Market Data Service has TWO separate parts:**

#### Part A: HTTP Server (Port 5002) - Thread 1
**What it does:**
- Listens for HTTP requests on port 5002
- When someone asks "What markets are available?", it reads from cache and responds
- **NEVER calls Kalshi** - only reads from cache

**HTTP Endpoints it serves:**
- `GET /markets` - Returns cached market data (<5ms response, never calls Kalshi)
- `GET /health` - Returns service status, cache age, and poller status

**How it works:**
- Runs in a Flask HTTP server thread
- When request comes in → reads from shared cache → returns data
- Fast because it's just reading from memory

#### Part B: Background Poller - Thread 2
**What it does:**
- Runs in a **separate background thread** (not part of the HTTP server)
- Every 12 seconds: Fetches from Kalshi API → Updates shared cache
- **No HTTP endpoints** - you can't call it via web requests
- Runs independently, doesn't wait for HTTP requests

**How it works:**
- Separate thread that runs continuously
- Every 12 seconds: `fetch_from_kalshi()` → `update_cache()`
- Updates the same cache that the HTTP server reads from

#### The Shared Cache
**What it is:**
- In-memory data structure (Python dictionary)
- Shared by both threads:
  - **Poller thread** writes to it (updates every 12 seconds)
  - **HTTP server thread** reads from it (when requests come in)

**Key Point:** The poller and port 5002 are **separate threads** in the **same process**. They don't call each other - they both use the same cache.

**Think of it like:** 
- **Port 5002** = The counter at a newsstand (serves customers)
- **Background Poller** = The delivery person (restocks the newsstand every 12 seconds)
- **Cache** = The newspaper rack (shared by both)
- They're both employees of the same newsstand, but do different jobs

---

### 2. UI (Web Interface) (Port 5001)
**Job:** Show you opportunities and let you interact

**What it does:**
- When you open the website, it asks Market Data Service: "What matches are available?"
- It analyzes those matches: "Which ones are good bets?"
- Shows you the top opportunities
- When you click "Start Trading", it tells the Trading Engine to look for opportunities

**HTTP Endpoints it serves:**
- `GET /` - Serves the main HTML page (web interface)
- `GET /healthz` - Health check endpoint
- `GET /api/players/search?q=<name>` - Search for players by name (autocomplete)
- `POST /api/predict` - Predict match outcome between two players (uses ML model)
- `GET /api/opportunities` - Get top trading opportunities (reads from Market Data Service)
- `GET /api/debug/markets` - Debug endpoint to check Market Data Service response
- `POST /api/trading/start` - Start automated trading (dry-run or live mode)

**Think of it like:** A dashboard that shows you what's happening and lets you control things.

---

### 3. Trading Engine (Part of UI App)
**Job:** Automatically find good bets and place trades

**What it does:**
- Asks Market Data Service: "What matches are available?"
- For each match, calculates: "Is this a good bet? (Model says 70% chance, Kalshi says 60% chance = good bet!)"
- If it finds a good bet, places a trade on Kalshi
- Reports back what it did

**How it's triggered:**
- Called via `POST /api/trading/start` endpoint (part of UI app)
- Reads market data from `GET http://localhost:5002/markets` (not Kalshi directly)
- Places orders directly to Kalshi API (only for order placement, not market data)

**Think of it like:** A robot trader that watches the markets and makes bets automatically.

---

## 🔄 How Data Flows (Step-by-Step)

### Scenario 1: You Open the Website

```
1. You type: http://localhost:5001
   ↓
2. Browser → UI Server: GET /
   ↓
3. UI Server → Browser: "Here's the HTML page"
   ↓
4. JavaScript on page runs: "I need to show opportunities"
   ↓
5. JavaScript → UI Server: GET /api/opportunities
   ↓
6. UI Server → Market Data Service: GET http://localhost:5002/markets
   ↓
7. Market Data Service: "Here's the cached data" (<5ms response)
   ↓
8. UI Server: "Let me analyze these markets..."
   - Matches players to markets
   - Runs ML model to predict winners
   - Calculates: "Is this a good bet?"
   ↓
9. UI Server → JavaScript: "Here are the top 5 opportunities"
   ↓
10. JavaScript → Browser: "Display these opportunities"
```

**Key Point:** The UI never talks to Kalshi. It only talks to Market Data Service.

---

### Scenario 2: Background Poller Updates Data

```
Every 12 seconds, automatically (in a separate thread):

1. Background Poller Thread (Thread 2): "Time to update!"
   (This is separate from the HTTP server on port 5002)
   ↓
2. Poller → Kalshi API: "What tennis matches are available?"
   ↓
3. Kalshi API: "Here are 70 matches..."
   ↓
4. Poller: "Let me get orderbook data for the first 100..."
   ↓
5. Poller: "Now I'll update the shared cache"
   ↓
6. Cache updated! (Old data replaced with new data)
   (The HTTP server on port 5002 will now serve this new data)
```

**Key Points:**
- This happens in a **separate thread** (Thread 2 - not the HTTP server thread)
- The poller **does NOT** serve HTTP requests - it just updates the cache
- Port 5002 HTTP server **does NOT** call the poller - they're independent threads
- They both use the same cache (poller writes, HTTP server reads)
- This happens automatically - you don't have to do anything

---

### Scenario 3: You Click "Start Trading"

```
1. You click: "Start Trading" (Dry Run)
   ↓
2. JavaScript → UI Server: POST /api/trading/start
   Body: {"mode": "dry-run"}
   ↓
3. UI Server → Trading Engine: "Scan for opportunities"
   ↓
4. Trading Engine → Market Data Service: GET http://localhost:5002/markets
   ↓
5. Market Data Service: "Here's the cached data" (<5ms)
   ↓
6. Trading Engine: "Let me analyze each market..."
   - For each market:
     * Match players
     * Run ML model
     * Calculate: "Is this a good bet?"
     * If yes: "Place a trade!"
   ↓
7. Trading Engine → Kalshi API: POST (place order) - only for placing orders
   ↓
8. Trading Engine → UI Server: "Here's what I did"
   ↓
9. UI Server → JavaScript: "Here are the results"
   Response: {"status": "completed", "trades_placed": [...], "logs": [...]}
   ↓
10. JavaScript → Browser: "Show trading logs"
```

**Key Point:** Trading Engine reads market data from Market Data Service, but places orders directly to Kalshi (that's okay - placing orders is different from reading market data).

---

## 📡 Complete Endpoint Reference

### Market Data Service - Two Separate Parts

#### Part 1: HTTP Server (Port 5002) - Thread 1

**GET Endpoints:**
- `GET /markets` - Returns full cached market snapshot
  - Response: `{"generated_at": timestamp, "markets": {...}}`
  - Response time: <5ms (reads from shared cache in memory)
  - **Never calls Kalshi** - only reads from cache
  - **Never calls poller thread** - they're separate
  
- `GET /health` - Health check
  - Response: `{"status": "ok", "generated_at": timestamp, "age_seconds": 5, "polling_active": true}`
  - Shows cache age and poller status

**How it works:**
- Runs in Flask HTTP server thread (Thread 1)
- Listens on port 5002 for HTTP requests
- When request comes in → reads from shared cache → returns data
- Does NOT call the poller thread
- Does NOT call Kalshi

#### Part 2: Background Poller - Thread 2

**No HTTP Endpoints:**
- This is a **background thread**, not an HTTP server
- You **cannot** make HTTP requests to it
- It runs independently in the background

**What it does:**
- Every 12 seconds: Fetches from Kalshi API → Updates shared cache
- Runs in a separate thread (Thread 2 - not the HTTP server thread)
- Updates the same cache that the HTTP server reads from

**How it works:**
- Separate thread that runs continuously
- Does NOT serve HTTP requests
- Does NOT communicate with the HTTP server thread
- They both just use the same shared cache

**Key Point:** The HTTP server (port 5002) and the poller are **separate threads** in the same process. They don't call each other - they both access the same in-memory cache.

---

### UI + Trading App (Port 5001)

**GET Endpoints:**
- `GET /` - Main web interface (serves HTML)
- `GET /healthz` - Health check (returns "ok")
- `GET /api/players/search?q=<name>` - Search players (autocomplete)
  - Returns: `{"players": [{"id": "...", "name": "..."}]}`
  
- `GET /api/opportunities` - Get top trading opportunities
  - Parameters: `?limit=5&min_value=0.05&min_ev=0.10&max_hours=48`
  - Internally calls: `GET http://localhost:5002/markets`
  - Returns: `{"opportunities": [...], "total_analyzed": 70, "total_tradable": 5}`
  
- `GET /api/debug/markets` - Debug endpoint to inspect Market Data Service response

**POST Endpoints:**
- `POST /api/predict` - Predict match outcome
  - Body: `{"player1": "...", "player2": "...", "surface": "Hard", ...}`
  - Returns: `{"player1": {...}, "player2": {...}, "predictions": {...}}`
  
- `POST /api/trading/start` - Start automated trading
  - Body: `{"mode": "dry-run"}` or `{"mode": "live"}`
  - Internally calls: `GET http://localhost:5002/markets`
  - Returns: `{"status": "completed", "trades_placed": [...], "logs": [...]}`

---

## 🧩 How It All Fits Together

### When You Run `python3 run.py`

```
┌─────────────────────────────────────────┐
│         python3 run.py                  │
│      (Main Process Starts)              │
└─────────────────┬───────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │  Step 1: Initialize         │
    │  Market Data Service        │
    │  (Takes 10-30 seconds)      │
    │                             │
    │  - Fetch from Kalshi        │
    │  - Store in memory          │
    │  - Start background poller  │
    └─────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │  Step 2: Create Flask Apps  │
    │  (Takes <1 second)          │
    │                             │
    │  - Market Data Service app  │
    │  - UI + Trading app         │
    └─────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────┐
    │  Step 3: Start Servers      │
    │  (Takes ~6 seconds)         │
    │                             │
    │  Thread 1: Market Data      │
    │    Service (port 5002)      │
    │                             │
    │  Thread 2: UI + Trading     │
    │    App (port 5001)          │
    │                             │
    │  Thread 3: Background      │
    │    Poller (runs every 12s)  │
    └─────────────────────────────┘
                  │
                  ▼
         ✅ System Running!
```

---

## 🔍 Real Example: What Happens When You Refresh the Page

Let's trace through exactly what happens:

### Time: 0.0 seconds
- You refresh the browser
- JavaScript on the page says: "I need to get opportunities"

### Time: 0.001 seconds
- JavaScript sends: `GET http://localhost:5001/api/opportunities`

### Time: 0.002 seconds
- UI Server receives the request
- UI Server says: "I need market data"
- UI Server sends: `GET http://localhost:5002/markets`

### Time: 0.007 seconds (5ms later)
- Market Data Service responds: "Here's the cached data"
- Market Data Service did NOT call Kalshi (it used cached data)

### Time: 0.008 seconds
- UI Server receives market data
- UI Server starts analyzing:
  - "Let me match players to markets..."
  - "Let me run the ML model..."
  - "Let me calculate which are good bets..."

### Time: 0.5 seconds
- UI Server finishes analyzing
- UI Server responds: "Here are the top 5 opportunities"

### Time: 0.501 seconds
- JavaScript receives the response
- JavaScript updates the page to show opportunities

**Total time:** ~0.5 seconds (mostly analysis, not waiting for Kalshi)

**If we called Kalshi directly:** Would take 0.5-1.0 seconds just to get data, then another 0.5 seconds to analyze = 1.0-1.5 seconds total

---

## 🎬 The Background Poller (The Unsung Hero)

While you're using the UI, this is happening in the background:

```
Time: 0 seconds
  → Poller: "Let me check Kalshi..."
  → Kalshi: "Here are 70 matches"
  → Poller: "Storing in cache..."
  → Cache updated!

Time: 12 seconds
  → Poller: "Let me check Kalshi again..."
  → Kalshi: "Here are 72 matches (2 new ones!)"
  → Poller: "Storing in cache..."
  → Cache updated!

Time: 24 seconds
  → Poller: "Let me check Kalshi again..."
  → (and so on...)
```

**Why this matters:**
- When you refresh the page, you get fresh data (updated within the last 12 seconds)
- You don't have to wait for Kalshi to respond (data is already in memory)
- Kalshi doesn't get overwhelmed with requests (only one request every 12 seconds)

---

## 🧠 Why This Architecture?

### Problem We're Solving:
- Kalshi API is slow (100-500ms per request)
- Kalshi has rate limits (too many requests = blocked)
- UI needs to be fast (users don't want to wait)
- Trading needs fresh data (but not necessarily instant)

### Our Solution:
- **One place** fetches from Kalshi (Market Data Service)
- **Everyone else** reads from that place (fast, in-memory)
- **Background updates** keep data fresh (every 12 seconds)
- **No rate limit issues** (only one request every 12 seconds)

### Benefits:
✅ **Fast:** UI responds in <0.5 seconds (vs 1-2 seconds)
✅ **Reliable:** If Kalshi is down, we still serve cached data
✅ **Simple:** One place to manage Kalshi connections
✅ **Scalable:** Can have many UI users without hitting rate limits

---

## 🎯 The Golden Rule

**ONLY Market Data Service calls Kalshi for market data.**

Everything else (UI, Trading Engine) reads from Market Data Service.

**Exception:** Trading Engine places orders directly to Kalshi (that's okay - placing orders is different from reading market data).

---

## 📊 Visual Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    KALSHI API                                │
│              (External, Slow, Rate-Limited)                   │
│                                                              │
│  Endpoints called:                                           │
│  - GET markets (every 12s by poller)                         │
│  - GET orderbook (every 12s by poller)                       │
│  - POST place_order (by Trading Engine when trading)        │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ (Only called here)
                            │ Every 12 seconds
                            ▼
┌─────────────────────────────────────────────────────────────┐
│         MARKET DATA SERVICE (One Process)                    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Thread 1: HTTP Server (Port 5002)                   │   │
│  │  - Listens for HTTP requests                         │   │
│  │  - GET /markets → Reads from cache                   │   │
│  │  - GET /health → Returns status                      │   │
│  │  - NEVER calls Kalshi                                │   │
│  │  - NEVER calls poller thread                         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Thread 2: Background Poller                          │   │
│  │  - Runs independently (separate thread)              │   │
│  │  - Fetches from Kalshi every 12s                     │   │
│  │  - Updates shared cache                              │   │
│  │  - NO HTTP endpoints (not accessible via web)        │   │
│  │  - NEVER called by HTTP server                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Shared In-Memory Cache (Used by both threads)       │   │
│  │  {                                                    │   │
│  │    "generated_at": timestamp,                        │   │
│  │    "markets": [...]                                  │   │
│  │  }                                                    │   │
│  │                                                       │   │
│  │  Thread 1 (HTTP Server): Reads from here            │   │
│  │  Thread 2 (Poller): Writes to here                  │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ (HTTP requests)
                            │ Fast, no Kalshi calls
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
┌───────────────────────┐           ┌───────────────────────┐
│   UI (Port 5001)      │           │  Trading Engine       │
│                       │           │  (Part of UI App)     │
│  GET /                │           │                       │
│  GET /api/opportunities│          │  Called via:          │
│  GET /api/players/... │           │  POST /api/trading/   │
│  POST /api/predict    │           │    start              │
│  POST /api/trading/   │           │                       │
│    start              │           │  Reads from:          │
│                       │           │  GET http://localhost:│
│  Reads from:          │           │    5002/markets       │
│  GET http://localhost:│           │                       │
│    5002/markets       │           │  Places orders:       │
│                       │           │  POST to Kalshi API   │
│  NEVER calls Kalshi   │           │  (only for orders)    │
│  directly             │           │                       │
└───────────────────────┘           └───────────────────────┘
```

---

## 🎓 Summary in Plain English

**Think of it like a restaurant:**

1. **Market Data Service** = The kitchen
   - Gets ingredients (data) from the supplier (Kalshi) every 12 seconds
   - Stores ingredients in the pantry (cache)
   - When you order, the kitchen uses ingredients from the pantry (fast!)

2. **UI** = The waiter
   - Takes your order (shows you opportunities)
   - Goes to the kitchen to get food (reads from Market Data Service)
   - Brings it to you (displays on screen)

3. **Trading Engine** = The chef
   - Looks at what's in the pantry (reads from Market Data Service)
   - Decides what to cook (finds good bets)
   - Actually cooks it (places trades on Kalshi)

**The key:** The kitchen (Market Data Service) is the only one that talks to the supplier (Kalshi). The waiter and chef just use what's in the pantry.

---

## ✅ Quick Checklist: Is It Working?

1. **Run:** `python3 run.py`
2. **See:** "✅ System is running!"
3. **Open:** `http://localhost:5001`
4. **See:** Opportunities appear on the page
5. **Check:** Console shows "FETCHING FROM KALSHI" every 12 seconds
6. **Refresh:** Page updates quickly (no waiting for Kalshi)

If all of these work, everything is connected correctly! 🎉



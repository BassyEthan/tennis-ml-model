"""
Market Data Service - Flask-based caching layer for Kalshi API

ARCHITECTURE OVERVIEW:
=====================

This service decouples Kalshi API calls from the UI and trading engine by:

1. **Background Polling**: A dedicated thread polls Kalshi every 12 seconds
2. **In-Memory Cache**: Latest market snapshot stored in memory (single source of truth)
3. **Fast HTTP Endpoints**: Request handlers read from cache only (<5ms response time)
4. **Thread-Safe**: Single writer (poller) / many readers (request handlers) model

WHY THIS DESIGN:
===============

**Latency**: Direct Kalshi API calls take 100-500ms. Cached reads take <5ms.
**Reliability**: API failures don't block request handlers. Cache serves stale data gracefully.
**Rate Limiting**: Centralized polling prevents exceeding Kalshi rate limits.
**Separation of Concerns**: UI/trading logic never touches Kalshi SDK directly.

CRITICAL RULE:
=============

NEVER call Kalshi API inside a request handler. All Kalshi calls happen
in the background polling thread only. Request handlers are read-only.
"""

import time
import threading
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from flask import Flask, jsonify

from src.trading.kalshi_client import KalshiClient, Environment
from config.settings import (
    KALSHI_ACCESS_KEY,
    KALSHI_PRIVATE_KEY_PATH,
    KALSHI_USE_PRODUCTION,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# In-memory cache (single source of truth)
# Structure: {
#   "generated_at": <unix_timestamp>,
#   "markets": {
#     "markets": [...],  # List of market objects
#     "total_count": <int>,
#     "enriched_count": <int>,
#     "match_times": {  # Lookup map for match timing (event_ticker -> timing fields)
#       "KXATPMATCH-26JAN03NAVTHO": {
#         "match_start_time": "...",
#         "expected_expiration_time": "...",
#         ...
#       }
#     }
#   }
# }
_cache: Dict[str, Any] = {
    "generated_at": 0,
    "markets": {}
}

# Thread-safe lock for cache updates (single writer / many readers)
_cache_lock = threading.RLock()

# Background polling control
_polling_active = threading.Event()
_polling_thread: Optional[threading.Thread] = None


def fetch_markets_from_kalshi() -> Optional[Dict[str, Any]]:
    """
    Fetch all tennis markets from Kalshi API.
    
    This is the ONLY function that calls Kalshi API.
    Called exclusively by the background polling thread.
    
    Returns:
        Kalshi markets response dict, or None on error
    """
    print("FETCHING FROM KALSHI")  # Debug: Prove requests never call this
    logger.info("FETCHING FROM KALSHI")  # Also log it
    try:
        # Initialize Kalshi client
        env = Environment.PROD if KALSHI_USE_PRODUCTION else Environment.DEMO
        client = KalshiClient(
            access_key=KALSHI_ACCESS_KEY,
            private_key_path=KALSHI_PRIVATE_KEY_PATH,
            environment=env,
        )
        
        # Fetch tennis markets from all known series
        tennis_series = ["KXATPMATCH", "KXWTAMATCH", "KXUNITEDCUPMATCH"]
        all_markets = []
        
        for series in tennis_series:
            try:
                response = client.get_markets(
                    series_ticker=series,
                    status="open",
                    limit=1000
                )
                markets = response.get("markets", [])
                all_markets.extend(markets)
                logger.info(f"Fetched {len(markets)} markets from {series}")
            except Exception as e:
                logger.warning(f"Error fetching {series}: {e}")
                continue
        
        # Enrich markets with orderbook data (prices, volume)
        enriched_markets = []
        for market in all_markets[:100]:  # Limit to 100 for performance
            ticker = market.get("ticker")
            if ticker:
                try:
                    orderbook = client.get_orderbook(ticker)
                    market["orderbook"] = orderbook
                except Exception as e:
                    logger.debug(f"Could not fetch orderbook for {ticker}: {e}")
                    market["orderbook"] = {}
            enriched_markets.append(market)
        
        # Extract match timing information for lookup by event_ticker
        # This allows auto_trader.py to get match start times without calling Kalshi
        match_times = {}
        for market in all_markets:  # Use all markets for timing, not just enriched
            event_ticker = market.get("event_ticker")
            if not event_ticker:
                continue
            
            # Skip if we already have timing for this event (markets share event_ticker)
            if event_ticker in match_times:
                continue
            
            # Extract all timing fields (match already has these from Kalshi)
            timing_info = {
                "match_start_time": market.get("match_start_time"),
                "start_time": market.get("start_time"),
                "scheduled_time": market.get("scheduled_time"),
                "expected_start_time": market.get("expected_start_time"),
                "expected_expiration_time": market.get("expected_expiration_time"),
                "expiration_time": market.get("expiration_time"),
                "close_time": market.get("close_time"),
                "event_close_time": market.get("event_close_time"),
            }
            
            # Only add if we have at least one timing field
            if any(timing_info.values()):
                match_times[event_ticker] = timing_info
        
        return {
            "markets": enriched_markets,
            "total_count": len(all_markets),
            "enriched_count": len(enriched_markets),
            "match_times": match_times  # Lookup map: event_ticker -> timing fields
        }
        
    except Exception as e:
        logger.error(f"Error fetching markets from Kalshi: {e}", exc_info=True)
        return None


def background_poller():
    """
    Background thread that polls Kalshi API every 12 seconds.
    
    This is the ONLY thread that writes to the cache.
    All request handlers are readers only.
    """
    logger.info("Background poller started")
    
    while _polling_active.is_set():
        try:
            # Fetch fresh data from Kalshi
            markets_data = fetch_markets_from_kalshi()
            
            if markets_data:
                # Atomic cache replacement (thread-safe)
                # Create new dict and replace entire cache reference
                new_cache = {
                    "generated_at": time.time(),
                    "markets": markets_data
                }
                
                with _cache_lock:
                    global _cache
                    _cache = new_cache  # Atomic replacement, not mutation
                
                logger.info(
                    f"Cache updated: {markets_data.get('total_count', 0)} total markets, "
                    f"{markets_data.get('enriched_count', 0)} enriched"
                )
            else:
                logger.warning("Failed to fetch markets, keeping existing cache")
                
        except Exception as e:
            logger.error(f"Error in background poller: {e}", exc_info=True)
        
        # Wait 12 seconds before next poll
        _polling_active.wait(12.0)


def start_background_poller():
    """Start the background polling thread."""
    global _polling_thread, _polling_active
    
    if _polling_thread and _polling_thread.is_alive():
        logger.warning("Background poller already running")
        return
    
    _polling_active.set()
    _polling_thread = threading.Thread(target=background_poller, daemon=True)
    _polling_thread.start()
    logger.info("Background poller thread started")


def stop_background_poller():
    """Stop the background polling thread."""
    global _polling_active
    _polling_active.clear()
    logger.info("Background poller stopped")


@app.route('/markets', methods=['GET'])
def get_markets():
    """
    Get the full cached market snapshot.
    
    Response time: <5ms (reads from memory only)
    Never calls Kalshi API.
    
    PROOF: This function does NOT call fetch_markets_from_kalshi().
    If you spam /markets, you will NOT see "FETCHING FROM KALSHI" logs.
    
    Returns:
        JSON with cached market data
    """
    # Read-only access (no lock needed for reading in Python due to GIL)
    # But we use lock for safety in case of future changes
    # NOTE: This is a READ-ONLY operation. We never call Kalshi here.
    with _cache_lock:
        cache_copy = _cache.copy()
    
    return jsonify(cache_copy)


@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        Status, timestamp, and cache age in seconds
    """
    with _cache_lock:
        generated_at = _cache.get("generated_at", 0)
        age_seconds = int(time.time() - generated_at) if generated_at > 0 else -1
    
    return jsonify({
        "status": "ok",
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "polling_active": _polling_active.is_set()
    })


def initialize_service():
    """Initialize the service on startup."""
    logger.info("Initializing Market Data Service...")
    
    # Do initial fetch synchronously (blocking)
    logger.info("Performing initial market fetch...")
    markets_data = fetch_markets_from_kalshi()
    
    if markets_data:
        with _cache_lock:
            global _cache
            _cache = {
                "generated_at": time.time(),
                "markets": markets_data
            }
        logger.info("Initial cache populated")
    else:
        logger.warning("Initial fetch failed, starting with empty cache")
    
    # Start background polling
    start_background_poller()
    logger.info("Market Data Service ready")


if __name__ == '__main__':
    # Initialize before starting server
    initialize_service()
    
    # Run on port 5002 (5000 often used by AirPlay on macOS, 5001 is main app)
    port = 5002
    logger.info(f"Starting Market Data Service on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)


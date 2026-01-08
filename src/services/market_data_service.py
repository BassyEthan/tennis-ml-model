"""
Market Data Service - Service module for Kalshi API caching

This module provides:
- In-memory cache for market data
- Background polling thread for Kalshi API
- Thread-safe cache access

The Flask app factory is in market_data_app.py
"""

import time
import threading
import logging
from typing import Dict, Any, Optional

from src.trading.kalshi_client import KalshiClient, Environment
from config.settings import (
    KALSHI_ACCESS_KEY,
    KALSHI_PRIVATE_KEY_PATH,
    KALSHI_USE_PRODUCTION,
)

# Configure logging
logger = logging.getLogger(__name__)

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
_poller_started = False  # Ensure poller starts exactly once


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


def start_market_data_service():
    """
    Start the Market Data Service.
    
    This function:
    1. Performs initial blocking fetch from Kalshi
    2. Populates cache
    3. Starts background polling thread (exactly once)
    
    This should be called before starting the Flask server.
    """
    global _poller_started
    
    if _poller_started:
        logger.warning("Market Data Service already started")
        return
    
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
    
    # Start background polling (exactly once)
    start_background_poller()
    _poller_started = True
    logger.info("Market Data Service ready")


def start_background_poller():
    """Start the background polling thread (idempotent)."""
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


def get_cache_snapshot() -> Dict[str, Any]:
    """
    Get a snapshot of the current cache (thread-safe read).
    
    Returns:
        Copy of the current cache
    """
    with _cache_lock:
        return _cache.copy()


def is_polling_active() -> bool:
    """Check if polling is active."""
    return _polling_active.is_set()



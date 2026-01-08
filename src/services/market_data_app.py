"""
Market Data Service - Flask app factory

This module provides the Flask application factory for the Market Data Service.
The service logic (cache, poller) is in market_data_service.py.
"""

import time
import logging
from flask import Flask, jsonify

from src.services.market_data_service import (
    get_cache_snapshot,
    is_polling_active
)

logger = logging.getLogger(__name__)


def create_market_data_app() -> Flask:
    """
    Create and configure the Market Data Service Flask app.
    
    Returns:
        Configured Flask application
    """
    app = Flask(__name__)
    
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
        cache_snapshot = get_cache_snapshot()
        return jsonify(cache_snapshot)
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """
        Health check endpoint.
        
        Returns:
            Status, timestamp, and cache age in seconds
        """
        cache_snapshot = get_cache_snapshot()
        generated_at = cache_snapshot.get("generated_at", 0)
        age_seconds = int(time.time() - generated_at) if generated_at > 0 else -1
        
        return jsonify({
            "status": "ok",
            "generated_at": generated_at,
            "age_seconds": age_seconds,
            "polling_active": is_polling_active()
        })
    
    return app



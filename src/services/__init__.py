"""
Services module for market data and other background services.
"""

from src.services.market_data_service import (
    start_market_data_service,
    stop_background_poller,
    get_cache_snapshot,
    is_polling_active
)
from src.services.market_data_app import create_market_data_app

__all__ = [
    'start_market_data_service',
    'stop_background_poller',
    'get_cache_snapshot',
    'is_polling_active',
    'create_market_data_app'
]


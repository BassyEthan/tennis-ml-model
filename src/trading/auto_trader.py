"""
Automated trading system for Kalshi markets.
Continuously scans for opportunities and places trades when value threshold is met.
"""

import time
import logging
import json
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo  # Python < 3.9 with backports
    except ImportError:
        # Fallback: use pytz if available
        try:
            import pytz
            ZoneInfo = lambda tz: pytz.timezone(tz)
        except ImportError:
            # Last resort: manual EST offset (UTC-5, doesn't handle DST)
            ZoneInfo = None
from pathlib import Path

from src.trading.kalshi_client import KalshiClient, Environment
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor


def format_time_est(dt: datetime) -> str:
    """Convert UTC datetime to EST and format for display."""
    if not dt:
        return ""
    if ZoneInfo:
        try:
            est_tz = ZoneInfo("America/New_York")  # Handles EST/EDT automatically
            # If naive, assume EST; if has timezone, convert to EST
            if dt.tzinfo is None:
                if hasattr(est_tz, 'localize'):
                    est_dt = est_tz.localize(dt)
                else:
                    est_dt = dt.replace(tzinfo=est_tz)
            else:
                est_dt = dt.astimezone(est_tz)
            return f" ({est_dt.strftime('%Y-%m-%d %I:%M %p EST')})"
        except:
            pass
    return ""
from config.settings import RAW_DATA_DIR, MODELS_DIR


# Ensure logs directory exists before configuring logging
Path("logs").mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/auto_trader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AutoTrader:
    """
    Automated trading system that scans Kalshi markets and places trades
    when model predictions exceed Kalshi prices by a threshold.
    """
    
    def __init__(
        self,
        kalshi_client: KalshiClient,
        analyzer: KalshiMarketAnalyzer,
        min_value_threshold: float = 0.02,  # 2% minimum value edge
        min_ev_threshold: float = 0.05,  # 5% minimum expected value
        max_position_size: int = 10,  # Maximum contracts per trade
        max_total_exposure: int = 100,  # Maximum total contracts across all positions
        scan_interval: int = 60,  # Seconds between scans
        max_hours_ahead: int = 48,  # Only trade markets closing within 48 hours
        min_volume: int = 1000,  # Minimum market volume in dollars
        dry_run: bool = True,  # If True, log trades but don't place them
    ):
        """
        Initialize automated trader.
        
        Args:
            kalshi_client: Initialized Kalshi client
            analyzer: Initialized Kalshi market analyzer
            min_value_threshold: Minimum value edge (model_prob - kalshi_prob) to trade
            min_ev_threshold: Minimum expected value to trade
            max_position_size: Maximum contracts per trade
            max_total_exposure: Maximum total contracts across all open positions
            scan_interval: Seconds between market scans
            max_hours_ahead: Only trade markets closing within this many hours
            min_volume: Minimum market volume in dollars
            dry_run: If True, simulate trades without placing orders
        """
        self.client = kalshi_client
        self.analyzer = analyzer
        self.min_value_threshold = min_value_threshold
        self.min_ev_threshold = min_ev_threshold
        self.max_position_size = max_position_size
        self.max_total_exposure = max_total_exposure
        self.scan_interval = scan_interval
        self.max_hours_ahead = max_hours_ahead
        self.min_volume = min_volume
        self.dry_run = dry_run
        
        # Track trades to avoid duplicates
        # CRITICAL: Track by event_ticker (match), not ticker (YES/NO side)
        # This prevents placing trades on both YES and NO sides of the same match
        self.traded_markets = set()  # Set of tickers we've already traded (for backward compatibility)
        self.traded_events = set()  # Set of event_tickers (matches) we've already traded
        self.trade_history = []  # List of all trades placed
        
        # Cache for match timing from Market Data Service (avoids repeated Kalshi calls)
        self._cached_match_times = {}  # event_ticker -> timing dict
        self._market_data_service_url = "http://localhost:5002"
        
        # Persistence file path
        self._persistence_file = Path("data/traded_events.json")
        self._persistence_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Background trading loop state
        self._trading_loop_thread: Optional[threading.Thread] = None
        self._trading_loop_running = False
        self._trading_loop_lock = threading.Lock()
        
        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)
        
        # Load persisted trade memory and fetch account state on startup
        self._load_trade_memory()
        self._sync_account_state()
        
        logger.info(f"AutoTrader initialized: min_value={min_value_threshold:.1%}, "
                   f"min_ev={min_ev_threshold:.1%}, max_size={max_position_size}, "
                   f"dry_run={dry_run}, traded_events={len(self.traded_events)}")
    
    def get_current_positions(self) -> Dict[str, Any]:
        """Get current positions from Kalshi."""
        try:
            positions = self.client.get_positions()
            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return {}
    
    def _sync_account_state(self):
        """
        Fetch account state from Kalshi on startup.
        
        Builds traded_events set from:
        - Current open positions
        - Recent executed orders (fills)
        
        This ensures we never re-trade events we already have positions in.
        """
        logger.info("🔄 Syncing account state from Kalshi...")
        
        # Track what we're adding for validation
        positions_added = 0
        orders_added = 0
        skipped_invalid = 0
        
        try:
            # 1. Get current open positions
            try:
                positions_response = self.get_current_positions()
                positions_list = positions_response.get("positions", [])
                
                if positions_list:
                    logger.info(f"   Found {len(positions_list)} open positions")
                    for pos in positions_list:
                        ticker = pos.get("ticker", "")
                        if not ticker:
                            skipped_invalid += 1
                            logger.debug(f"   ⚠️  Skipping position with no ticker: {pos}")
                            continue
                        
                        event_ticker = self._extract_event_ticker(ticker)
                        if event_ticker:
                            # Only add if not already in set (avoid duplicates)
                            if event_ticker not in self.traded_events:
                                self.traded_events.add(event_ticker)
                                positions_added += 1
                                logger.info(f"   ✅ Added event {event_ticker} from position: {ticker}")
                            else:
                                logger.debug(f"   ℹ️  Event {event_ticker} already in traded_events (from position: {ticker})")
                        else:
                            skipped_invalid += 1
                            logger.warning(f"   ⚠️  Could not extract event_ticker from position ticker: {ticker}")
                else:
                    logger.info("   No open positions found")
            except Exception as e:
                logger.warning(f"   ⚠️  Error fetching positions: {e}")
            
            # 2. Get recent executed orders (fills) - last 50 orders
            try:
                orders_response = self.client.get_orders(status="executed", limit=50)
                orders_list = orders_response.get("orders", [])
                
                if orders_list:
                    logger.info(f"   Found {len(orders_list)} recent executed orders")
                    for order in orders_list:
                        ticker = order.get("ticker", "")
                        if not ticker:
                            skipped_invalid += 1
                            logger.debug(f"   ⚠️  Skipping order with no ticker: {order}")
                            continue
                        
                        event_ticker = self._extract_event_ticker(ticker)
                        if event_ticker:
                            # Only add if not already in set (avoid duplicates)
                            if event_ticker not in self.traded_events:
                                self.traded_events.add(event_ticker)
                                orders_added += 1
                                logger.info(f"   ✅ Added event {event_ticker} from executed order: {ticker}")
                            else:
                                logger.debug(f"   ℹ️  Event {event_ticker} already in traded_events (from order: {ticker})")
                        else:
                            skipped_invalid += 1
                            logger.warning(f"   ⚠️  Could not extract event_ticker from order ticker: {ticker}")
                else:
                    logger.info("   No recent executed orders found")
            except Exception as e:
                logger.warning(f"   ⚠️  Error fetching executed orders: {e}")
            
            logger.info(f"   ✅ Account state synced:")
            logger.info(f"      - Events from positions: {positions_added}")
            logger.info(f"      - Events from orders: {orders_added}")
            logger.info(f"      - Skipped (invalid): {skipped_invalid}")
            logger.info(f"      - Total events in memory: {len(self.traded_events)}")
            
            # Save updated state to persistence
            self._save_trade_memory()
            
        except Exception as e:
            logger.error(f"❌ Error syncing account state: {e}", exc_info=True)
    
    def _load_trade_memory(self):
        """Load traded events from persistence file."""
        try:
            if self._persistence_file.exists():
                with open(self._persistence_file, 'r') as f:
                    data = json.load(f)
                    self.traded_events = set(data.get("traded_events", []))
                    logger.info(f"📂 Loaded {len(self.traded_events)} traded events from persistence file")
            else:
                logger.info("📂 No persistence file found, starting with empty trade memory")
        except Exception as e:
            logger.warning(f"⚠️  Error loading trade memory: {e}")
            self.traded_events = set()
    
    def _save_trade_memory(self):
        """Save traded events to persistence file."""
        try:
            data = {
                "traded_events": list(self.traded_events),
                "last_updated": datetime.now().isoformat()
            }
            with open(self._persistence_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"💾 Saved {len(self.traded_events)} traded events to persistence file")
        except Exception as e:
            logger.warning(f"⚠️  Error saving trade memory: {e}")
    
    def calculate_position_size(self, opportunity: Dict[str, Any]) -> int:
        """
        Calculate position size - ALWAYS returns 1 contract per trade.
        
        Args:
            opportunity: Opportunity dictionary from analyzer
            
        Returns:
            Always 1 contract (or 0 if below threshold)
        """
        # Use trade_value which is always positive (abs of value)
        # This ensures we use the actual edge, not the signed value
        trade_value = opportunity.get("trade_value", 0)
        if trade_value == 0:
            # Fallback to abs(value) if trade_value not set
            value = opportunity.get("value", 0)
            trade_value = abs(value)
        
        # Check if above threshold
        if trade_value < self.min_value_threshold:
            return 0
        
        # ALWAYS return 1 contract per trade (user requirement)
        return 1
    
    def _extract_event_ticker(self, ticker: str) -> Optional[str]:
        """
        Extract event_ticker (match identifier) from market ticker.
        
        Format: SERIES-DATE-EVENT-SUFFIX -> SERIES-DATE-EVENT
        Example: KXATPMATCH-26JAN03NAVTHO-THO -> KXATPMATCH-26JAN03NAVTHO
        
        Args:
            ticker: Market ticker (e.g., "KXATPMATCH-26JAN03NAVTHO-THO")
            
        Returns:
            Event ticker (match identifier) or None if cannot extract
        """
        if not ticker or not isinstance(ticker, str):
            return None
        
        # Must have at least one dash to have a suffix
        if '-' not in ticker:
            logger.warning(f"⚠️  Ticker has no dashes, cannot extract event_ticker: {ticker}")
            return None
        
        # Split on last dash to remove suffix (YES/NO/THO indicator)
        parts = ticker.rsplit('-', 1)
        if len(parts) != 2:
            logger.warning(f"⚠️  Ticker format unexpected, cannot extract event_ticker: {ticker}")
            return None
        
        event_ticker = parts[0]  # Everything before last dash
        
        # Validate: event_ticker should have at least 1 dash (SERIES-DATE-EVENT format)
        # This ensures we're not accidentally using a partial ticker
        if event_ticker.count('-') < 1:
            logger.warning(f"⚠️  Extracted event_ticker seems invalid (no dashes): {event_ticker} from {ticker}")
            return None
        
        return event_ticker
    
    def _get_match_timing_from_service(self, event_ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get match timing information from Market Data Service cache.
        
        This replaces direct Kalshi API calls for match timing.
        Uses cached data from the service (no Kalshi calls).
        
        Args:
            event_ticker: Event ticker (e.g., "KXATPMATCH-26JAN03NAVTHO")
            
        Returns:
            Dict with timing fields, or None if not found
        """
        # First check our local cache (from last service fetch)
        if event_ticker in self._cached_match_times:
            return self._cached_match_times[event_ticker]
        
        # If not in cache, fetch from service
        try:
            import requests
            response = requests.get(f"{self._market_data_service_url}/markets", timeout=2)
            if response.status_code == 200:
                markets_data = response.json()
                markets_dict = markets_data.get("markets", {})
                match_times = markets_dict.get("match_times", {})
                
                # Update local cache
                self._cached_match_times = match_times
                
                # Return timing for this event
                return match_times.get(event_ticker)
            else:
                logger.warning(f"Market data service returned status {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching match timing from service: {e}")
            return None
    
    def check_existing_position(self, ticker: str) -> bool:
        """
        Check if we already have a position in this market or any related market (same event).
        
        Args:
            ticker: Market ticker
            
        Returns:
            True if we already have a position in this market or any market for the same event
        """
        try:
            positions = self.get_current_positions()
            positions_list = positions.get("positions", [])
            
            # Extract event_ticker for this ticker
            event_ticker = self._extract_event_ticker(ticker)
            
            for pos in positions_list:
                pos_ticker = pos.get("ticker")
                if pos_ticker == ticker:
                    return True
                # Also check if position is in the same event (match)
                if event_ticker:
                    pos_event_ticker = self._extract_event_ticker(pos_ticker)
                    if pos_event_ticker == event_ticker:
                        return True
            return False
        except Exception as e:
            logger.warning(f"Error checking positions for {ticker}: {e}")
            return False
    
    def place_trade(self, opportunity: Dict[str, Any], min_minutes_before: int = 15) -> Optional[Dict[str, Any]]:
        """
        Place a trade for an opportunity.
        
        Args:
            opportunity: Opportunity dictionary from analyzer
            min_minutes_before: Minimum minutes before match start (default 15)
            
        Returns:
            Order response from Kalshi or None if failed
        """
        ticker = opportunity.get("ticker")
        trade_side = opportunity.get("trade_side")
        kalshi_odds = opportunity.get("kalshi_odds", {})
        
        if not ticker or not trade_side:
            logger.error(f"Invalid opportunity: missing ticker or trade_side")
            return None
        
        # CRITICAL: Extract event_ticker to prevent trading both YES and NO sides of same match
        event_ticker = self._extract_event_ticker(ticker)
        if not event_ticker:
            logger.error(f"❌ Cannot extract event_ticker from {ticker} - cannot proceed with trade (safety check)")
            logger.error(f"   This prevents accidentally trading the same match multiple times")
            return None
        
        # Check if we already traded this specific ticker
        if ticker in self.traded_markets:
            logger.info(f"Skipping {ticker}: already traded this ticker")
            return None
        
        # CRITICAL: Check if we already traded this event (match) - prevents YES/NO duplicates
        if event_ticker in self.traded_events:
            logger.warning(f"🚫 BLOCKED: Skipping {ticker}: already traded event {event_ticker} (preventing duplicate trade on same match)")
            return None
        
        # Check if we already have a position in this market or any market for the same event
        if self.check_existing_position(ticker):
            logger.warning(f"🚫 BLOCKED: Skipping {ticker}: already have position in this event (preventing duplicate trade)")
            # Mark event as traded to prevent future attempts
            self.traded_events.add(event_ticker)
            return None
        
        # CRITICAL: Check if match is within the trading window
        # Rules:
        # - Always: at least 10 minutes before match start
        # - No maximum time limit (can trade anytime before match start)
        try:
            # Get match timing from Market Data Service (NO Kalshi call)
            # Extract event_ticker from market ticker (format: SERIES-DATE-EVENT-SUFFIX)
            # e.g., KXATPMATCH-26JAN03NAVTHO-THO -> KXATPMATCH-26JAN03NAVTHO
            event_ticker = self._extract_event_ticker(ticker)
            if not event_ticker:
                logger.warning(f"Cannot extract event_ticker from {ticker}, skipping timing check")
                return None
            
            # Get timing from service cache (replaces direct Kalshi call)
            timing_info = self._get_match_timing_from_service(event_ticker)
            if not timing_info:
                logger.warning(f"  ⚠️ No timing info found for event {event_ticker} in service cache")
                return None
            
            # CRITICAL: Try to find the actual match start time, not expiration/close time
            # Expiration times are when the market CLOSES (after match ends), not when match starts
            # We want the match START time, which should be BEFORE the expiration
            # Prioritize match START time fields - these are when the match begins
            
            close_time = None
            time_field_used = None
            
            # First priority: Match start time fields (these are when the match begins)
            for field in ["match_start_time", "start_time", "scheduled_time", "expected_start_time"]:
                time_val = timing_info.get(field)
                if time_val:
                    close_time = time_val
                    time_field_used = field
                    logger.info(f"  ✅ Using match START time field: {field} = {time_val}")
                    break
            
            # If no match start time found, try to estimate from expiration time
            # Tennis matches typically last 2-3 hours, so match start ≈ expiration - 2.5 hours
            if not close_time:
                expiration_time = timing_info.get("expected_expiration_time") or timing_info.get("expiration_time") or timing_info.get("close_time")
                if expiration_time:
                    close_time = expiration_time
                    time_field_used = "estimated_from_expiration"
                    logger.warning(f"  ⚠️ No match start time field found. Using expiration time and estimating match start ≈ expiration - 2.5 hours")
                else:
                    logger.error(f"  ❌ REJECTED: No match start time or expiration time found for {ticker}. Cannot determine match time.")
                    logger.error(f"     Available fields: match_start_time={timing_info.get('match_start_time')}, start_time={timing_info.get('start_time')}, scheduled_time={timing_info.get('scheduled_time')}, expected_start_time={timing_info.get('expected_start_time')}")
                    return None
                
                # DEBUG: Log all time fields from service cache
                logger.info(f"🔍 DEBUG TIME PARSING for {ticker}:")
                logger.info(f"  Time field used: {time_field_used} = {close_time}")
                logger.info(f"  All available time fields from service:")
                logger.info(f"    match_start_time: {timing_info.get('match_start_time')}")
                logger.info(f"    start_time: {timing_info.get('start_time')}")
                logger.info(f"    scheduled_time: {timing_info.get('scheduled_time')}")
                logger.info(f"    expected_start_time: {timing_info.get('expected_start_time')}")
                logger.info(f"    expected_expiration_time: {timing_info.get('expected_expiration_time')}")
                logger.info(f"    expiration_time: {timing_info.get('expiration_time')}")
                logger.info(f"    close_time: {timing_info.get('close_time')}")
                logger.info(f"    event_close_time: {timing_info.get('event_close_time')}")
                
                if close_time:
                    # CRITICAL: Kalshi API returns times in UTC (with 'Z' suffix)
                    # We MUST parse as UTC first, then convert to EST for all calculations
                    # This ensures times match what Kalshi shows on their website
                    if ZoneInfo:
                        est_tz = ZoneInfo("America/New_York")
                        utc_tz = timezone.utc
                    else:
                        est_tz = timezone(timedelta(hours=-5))
                        utc_tz = timezone.utc
                    
                    if isinstance(close_time, str):
                        if 'T' in close_time:
                            # ISO format - check for timezone marker
                            if close_time.endswith('Z'):
                                # Explicitly UTC - parse as UTC, then convert to EST
                                dt_utc = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                                close_dt = dt_utc.astimezone(est_tz)
                                logger.info(f"  ✅ Parsed UTC with Z: {dt_utc} -> EST: {close_dt}")
                            elif '+' in close_time or (close_time.count('-') > 2 and 'T' in close_time):
                                # Has timezone offset - parse as-is, then convert to EST
                                dt_parsed = datetime.fromisoformat(close_time)
                                close_dt = dt_parsed.astimezone(est_tz)
                                logger.info(f"  ✅ Parsed with offset: {dt_parsed} -> EST: {close_dt}")
                            else:
                                # No timezone marker - assume UTC (Kalshi default), then convert to EST
                                date_part = close_time.split('T')[0]
                                time_part = close_time.split('T')[1].split('+')[0].split('-')[0].split('Z')[0]
                                naive_dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                                dt_utc = naive_dt.replace(tzinfo=utc_tz)
                                close_dt = dt_utc.astimezone(est_tz)
                                logger.info(f"  ✅ Parsed as UTC (no marker): {dt_utc} -> EST: {close_dt}")
                        else:
                            # Non-ISO format - assume UTC, then convert to EST
                            naive_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                            dt_utc = naive_dt.replace(tzinfo=utc_tz)
                            close_dt = dt_utc.astimezone(est_tz)
                            logger.info(f"  ✅ Parsed non-ISO as UTC: {dt_utc} -> EST: {close_dt}")
                    
                    # If we're using an expiration time, estimate match start by subtracting 2.5 hours
                    # Tennis matches typically last 2-3 hours, so match start ≈ expiration - 2.5 hours
                    if time_field_used == "estimated_from_expiration":
                        # Estimate match start time from expiration time
                        close_dt = close_dt - timedelta(hours=2.5)
                        logger.info(f"  ✅ Estimated match start from expiration: {close_dt} (expiration - 2.5 hours)")
                    else:
                        # Using actual match start time field - use as-is (no adjustment)
                        logger.info(f"  ✅ Using match start time field ({time_field_used}) - no adjustment needed")
                    
                    if close_dt:
                        # Work entirely in EST for calculations
                        now = datetime.now(est_tz)
                        time_diff_minutes = (close_dt - now).total_seconds() / 60
                        logger.info(f"  ⏰ Current EST time: {now}")
                        logger.info(f"  ⏰ Match EST time: {close_dt}")
                        logger.info(f"  ⏰ Time difference: {time_diff_minutes:.1f} minutes ({time_diff_minutes/60:.1f} hours)")
                        
                        # CRITICAL: Skip matches that have already started (negative time difference)
                        if time_diff_minutes < 0:
                            logger.warning(f"🔒 LOCKED OUT: Skipping {ticker}: match already started ({abs(time_diff_minutes):.1f} minutes ago)")
                            return None
                        
                        # Check minimum: must be at least 10 minutes before (always enforced)
                        if time_diff_minutes < min_minutes_before:
                            logger.warning(f"Skipping {ticker}: match starts in {time_diff_minutes:.1f} minutes, "
                                         f"need at least {min_minutes_before} minutes buffer")
                            return None
                        # No maximum time limit - can trade anytime before match start
        except Exception as e:
            logger.warning(f"Could not check match start time for {ticker}: {e}. Proceeding with caution.")
        
        # Calculate position size
        position_size = self.calculate_position_size(opportunity)
        if position_size == 0:
            logger.warning(f"Skipping {ticker}: position size calculated as 0")
            return None
        
        # Get current price from orderbook (use ask for buying - we need to buy at the ask price)
        try:
            orderbook = self.client.get_orderbook(ticker)
            
            # For buying, we need to look at asks (sellers), not bids
            # The ask price is what sellers are offering at
            asks = orderbook.get("asks", [])
            
            # Fallback: try side-specific ask fields
            if not asks:
                if trade_side == "yes":
                    yes_data = orderbook.get("yes", {})
                    asks = yes_data.get("asks", []) if isinstance(yes_data, dict) else []
                elif trade_side == "no":
                    no_data = orderbook.get("no", {})
                    asks = no_data.get("asks", []) if isinstance(no_data, dict) else []
            
            # Fallback: try direct ask fields
            if not asks:
                ask_price = orderbook.get("ask") or orderbook.get("yes_ask") or orderbook.get("no_ask")
                if ask_price:
                    best_ask_price = int(ask_price)
                else:
                    # Last resort: use price from opportunity data
                    yes_price = kalshi_odds.get("yes_price", 0)
                    no_price = kalshi_odds.get("no_price", 0)
                    if trade_side == "yes" and yes_price:
                        best_ask_price = int(yes_price)
                    elif trade_side == "no" and no_price:
                        best_ask_price = int(no_price)
                    else:
                        logger.warning(f"Using YES price from opportunity data: {yes_price} (orderbook had no asks)")
                        best_ask_price = int(yes_price) if yes_price else None
            else:
                # Use best ask price (lowest price someone is willing to sell at)
                best_ask_price = asks[0].get("price")
            
            if not best_ask_price:
                logger.warning(f"No ask price available for {ticker}")
                return None
            
            # Validate price is in valid range (1-99 cents)
            if best_ask_price < 1 or best_ask_price > 99:
                logger.error(f"Invalid price {best_ask_price} for {ticker} (must be 1-99 cents)")
                return None
            
            best_ask_price = int(best_ask_price)  # Ensure integer
        except Exception as e:
            logger.error(f"Error getting orderbook for {ticker}: {e}")
            # Fallback to opportunity data
            yes_price = kalshi_odds.get("yes_price", 0)
            no_price = kalshi_odds.get("no_price", 0)
            if trade_side == "yes" and yes_price:
                best_ask_price = int(yes_price)
                logger.info(f"Using YES price from opportunity data: {best_ask_price} (orderbook error)")
            elif trade_side == "no" and no_price:
                best_ask_price = int(no_price)
                logger.info(f"Using NO price from opportunity data: {best_ask_price} (orderbook error)")
            else:
                logger.error(f"Cannot determine price for {ticker}: {e}")
                return None
        
        # Place order - use yes_price or no_price based on trade_side
        if trade_side == "yes":
            order_data = {
                "ticker": ticker,
                "side": trade_side,
                "action": "buy",
                "count": position_size,
                "yes_price": best_ask_price,  # Kalshi requires yes_price for YES orders
            }
        elif trade_side == "no":
            order_data = {
                "ticker": ticker,
                "side": trade_side,
                "action": "buy",
                "count": position_size,
                "no_price": best_ask_price,  # Kalshi requires no_price for NO orders
            }
        else:
            logger.error(f"Invalid trade_side: {trade_side}")
            return None
        
        # Check dry_run mode
        if self.dry_run:
            logger.info(f"🧪 DRY RUN MODE: Would place order: {order_data}")
            logger.info(f"  Opportunity: {opportunity.get('title', 'Unknown')}")
            logger.info(f"  Value edge: {opportunity.get('trade_value', opportunity.get('value', 0)):.2%}")
            logger.info(f"  Expected value: {opportunity.get('expected_value', 0):.2%}")
            logger.info(f"  ⚠️  DRY RUN: Order NOT placed (simulation only - no real money)")
            # Return a simulated response for dry run
            # Include opportunity data for display
            players = opportunity.get('matched_players', ('', ''))
            bet_on_player = opportunity.get('bet_on_player')
            if not bet_on_player:
                if trade_side == 'yes':
                    bet_on_player = players[0] if players[0] else "Unknown"
                else:
                    bet_on_player = players[1] if players[1] else "Unknown"
            
            # Get model probability for the player we're betting on
            model_prob = opportunity.get('model_probability', 0)
            # If betting NO, model prob is for the asked player, so prob for bet_on_player is 1 - model_prob
            if trade_side == 'no':
                model_prob_bet = 1.0 - model_prob
            else:
                model_prob_bet = model_prob
            
            # Mark both ticker and event as traded even in dry run (prevents duplicates)
            self.traded_markets.add(ticker)
            event_ticker = self._extract_event_ticker(ticker)
            if event_ticker:
                self.traded_events.add(event_ticker)
                self._save_trade_memory()  # Persist immediately
                logger.info(f"✅ Marked event {event_ticker} as traded (DRY RUN - prevents duplicate trades on same match)")
            
            return {
                "ticker": ticker,
                "order": {
                    "ticker": ticker,
                    "side": trade_side,
                    "action": "buy",
                    "count": position_size,
                    "status": "dry_run_simulated",
                    "dry_run": True
                },
                "dry_run": True,
                "players": players,
                "bet_on_player": bet_on_player,
                "model_probability": model_prob_bet
            }
        
        # LIVE TRADING: Place real order
        try:
            logger.info(f"🔴 LIVE TRADING MODE: Placing REAL order on Kalshi: {order_data}")
            logger.info(f"  ⚠️  WARNING: This will place a REAL trade with REAL money!")
            logger.info(f"  Opportunity: {opportunity.get('title', 'Unknown')}")
            logger.info(f"  Value edge: {opportunity.get('trade_value', opportunity.get('value', 0)):.2%}")
            logger.info(f"  Expected value: {opportunity.get('expected_value', 0):.2%}")
            
            order_response = self.client.place_order(**order_data)
            
            logger.info(f"✅ ORDER PLACED SUCCESSFULLY: {order_response}")
            # Mark both ticker and event as traded to prevent duplicates
            self.traded_markets.add(ticker)
            event_ticker = self._extract_event_ticker(ticker)
            if event_ticker:
                self.traded_events.add(event_ticker)
                self._save_trade_memory()  # Persist immediately
                logger.info(f"✅ Marked event {event_ticker} as traded (prevents duplicate trades on same match)")
            
            # Extract player info for display
            players = opportunity.get('matched_players', ('', ''))
            bet_on_player = opportunity.get('bet_on_player')
            if not bet_on_player:
                if trade_side == 'yes':
                    bet_on_player = players[0] if players[0] else "Unknown"
                else:
                    bet_on_player = players[1] if players[1] else "Unknown"
            
            # Get model probability for the player we're betting on
            model_prob = opportunity.get('model_probability', 0)
            # If betting NO, model prob is for the asked player, so prob for bet_on_player is 1 - model_prob
            if trade_side == 'no':
                model_prob_bet = 1.0 - model_prob
            else:
                model_prob_bet = model_prob
            
            self.trade_history.append({
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "opportunity": opportunity,
                "order": order_response,
                "dry_run": False,
            })
            
            # Return trade result with ticker and player info for logging
            return {
                "ticker": ticker,
                "order": order_response,
                "dry_run": False,
                "players": players,
                "bet_on_player": bet_on_player,
                "model_probability": model_prob_bet
            }
        except Exception as e:
            logger.error(f"❌ Error placing order for {ticker}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def scan_and_trade(self) -> List[Dict[str, Any]]:
        """
        Scan markets for opportunities and place trades.
        
        Returns:
            List of trades placed in this scan
        """
        logger.info(f"\n{'=' * 70}")
        logger.info("🔍 STARTING MARKET SCAN")
        logger.info(f"{'=' * 70}")
        
        try:
            # Fetch markets from Market Data Service (ONLY place that calls Kalshi)
            # This ensures run.py never calls Kalshi directly
            markets = []
            try:
                import requests
                response = requests.get(f"{self._market_data_service_url}/markets", timeout=2)
                if response.status_code == 200:
                    markets_data = response.json()
                    markets_dict = markets_data.get("markets", {})
                    if isinstance(markets_dict, dict):
                        markets = markets_dict.get("markets", [])
                        # Cache match_times for later use (avoids repeated service calls)
                        match_times = markets_dict.get("match_times", {})
                        self._cached_match_times = match_times
                    elif isinstance(markets_dict, list):
                        markets = markets_dict
                    else:
                        markets = []
                else:
                    logger.warning(f"Market data service returned status {response.status_code}")
                    markets = []
            except Exception as e:
                logger.error(f"Market data service unavailable: {e}")
                markets = []
            
            # Always pass markets (even if empty) to prevent Kalshi fallback
            if markets is None:
                markets = []
            
            # Scan for tradable opportunities (show_all=True to get rejection reasons)
            # Use debug=True temporarily to see what's happening
            tradable, all_analyses = self.analyzer.scan_markets(
                limit=1000,
                min_value=self.min_value_threshold,
                min_ev=self.min_ev_threshold,
                debug=True,  # Enable debug to see market discovery
                show_all=True,  # Get all analyses to show rejection reasons
                max_hours_ahead=self.max_hours_ahead,
                min_volume=self.min_volume,
                markets=markets  # Pass markets from service (never call Kalshi directly)
            )
            
            # CRITICAL: Filter out already-traded event_tickers BEFORE ranking
            # This prevents re-trading events we already have positions in
            original_count = len(tradable)
            filtered_tradable = []
            skipped_traded = 0
            
            for opp in tradable:
                ticker = opp.get("ticker", "")
                if not ticker:
                    continue
                
                # Extract event_ticker to check if we've already traded this event
                event_ticker = self._extract_event_ticker(ticker)
                if not event_ticker:
                    # If we can't extract event_ticker, log warning but don't skip
                    # This allows trading even if extraction fails (safer than blocking)
                    logger.warning(f"   ⚠️  Could not extract event_ticker from {ticker}, proceeding with caution")
                    # Don't use ticker as fallback - that could cause false positives
                    # Instead, skip the duplicate check for this market
                    event_ticker = None
                
                # Check if we've already traded this event (only if extraction succeeded)
                if event_ticker and event_ticker in self.traded_events:
                    skipped_traded += 1
                    logger.info(f"   🚫 SKIPPING already traded event: {event_ticker} (ticker: {ticker})")
                    continue
                
                # Check if we have an existing position in this event
                if self.check_existing_position(ticker):
                    # Mark as traded to prevent future attempts (only if we can extract event_ticker)
                    if event_ticker:
                        self.traded_events.add(event_ticker)
                        self._save_trade_memory()  # Persist immediately
                    skipped_traded += 1
                    event_display = event_ticker if event_ticker else ticker
                    logger.info(f"   🚫 SKIPPING event with existing position: {event_display} (ticker: {ticker})")
                    continue
                
                # Market passed all filters - include it
                filtered_tradable.append(opp)
            
            tradable = filtered_tradable
            
            if skipped_traded > 0:
                logger.info(f"   🔒 Filtered out {skipped_traded} opportunities (already traded/held events)")
                logger.info(f"   ✅ {len(tradable)} new opportunities remaining (from {original_count} total)")
            
            # Sort tradable by market volume (descending) - same as opportunities endpoint
            tradable.sort(key=lambda x: x.get("market_volume") or 0, reverse=True)
            
            # Don't limit to top 5 - we'll trade progressively in batches
            # This allows trading the next 5 after the top 5 are traded
            remaining_tradable = tradable
            
            # Log summary
            logger.info(f"\n{'=' * 70}")
            logger.info(f"📊 SCAN SUMMARY")
            logger.info(f"{'=' * 70}")
            logger.info(f"   Markets analyzed: {len(all_analyses)}")
            logger.info(f"   Tradable opportunities: {len(tradable)}")
            logger.info(f"   Rejected: {len(all_analyses) - len(tradable)}")
            
            # Progressive trading: trade in batches of 5, continuing until no more opportunities
            all_trades_placed = []
            batch_number = 1
            batch_size = 5
            
            while remaining_tradable:
                # Get next batch of 5
                current_batch = remaining_tradable[:batch_size]
                
                if not current_batch:
                    break
                
                logger.info(f"\n{'=' * 70}")
                logger.info(f"💰 BATCH {batch_number} - TOP {len(current_batch)} OPPORTUNITIES (by volume)")
                logger.info(f"{'=' * 70}")
                
                # Log details for current batch
                for i, analysis in enumerate(current_batch, 1):
                    ticker = analysis.get("ticker", "Unknown")
                    title = analysis.get("title", "Unknown Market")
                    players = analysis.get("matched_players", ("", ""))
                    players_str = f"{players[0]} vs {players[1]}" if players[0] and players[1] else "Unknown players"
                    
                    is_tradable = analysis.get("tradable", False)
                    value = analysis.get("value", 0)
                    trade_value = analysis.get("trade_value", abs(value))  # Use trade_value if available, otherwise abs(value)
                    ev = analysis.get("expected_value", 0)
                    reason = analysis.get("reason", "")
                    market_volume = analysis.get("market_volume", 0)
                    
                    # Get time until match start from service cache (NO Kalshi call)
                    time_info = ""
                    try:
                        # Extract event_ticker from market ticker
                        event_ticker = self._extract_event_ticker(ticker)
                        if not event_ticker:
                            continue
                        
                        # Get timing from service cache (replaces direct Kalshi call)
                        timing_info = self._get_match_timing_from_service(event_ticker)
                        if not timing_info:
                            continue
                        
                        # CRITICAL: Prioritize match START times over expiration/close times
                        # Expiration times are when the market CLOSES (after match ends), not when match starts
                        # We want the match START time, which should be BEFORE the expiration
                        close_time = None
                        time_field_used = None
                        
                        # First priority: Match start time fields (these are when the match begins)
                        for field in ["match_start_time", "start_time", "scheduled_time", "expected_start_time"]:
                            time_val = timing_info.get(field)
                            if time_val:
                                close_time = time_val
                                time_field_used = field
                                break
                        
                        # CRITICAL: DO NOT use expiration/close times - they are when the market closes, not when the match starts
                        # If we can't find a match start time field, we cannot determine when the match actually starts
                        # Skip this market to avoid incorrect time calculations
                        if not close_time:
                            logger.warning(f"  ⚠️ Skipping {ticker}: No match start time field found. Cannot determine actual match start time.")
                            continue
                            
                            if close_time:
                                # CRITICAL: Kalshi API returns times in UTC (with 'Z' suffix)
                                # We MUST parse as UTC first, then convert to EST for all calculations
                                if ZoneInfo:
                                    est_tz = ZoneInfo("America/New_York")
                                    utc_tz = timezone.utc
                                else:
                                    est_tz = timezone(timedelta(hours=-5))
                                    utc_tz = timezone.utc
                                
                                if isinstance(close_time, str):
                                    if 'T' in close_time:
                                        # ISO format - check for timezone marker
                                        if close_time.endswith('Z'):
                                            # Explicitly UTC - parse as UTC, then convert to EST
                                            dt_utc = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                                            close_dt = dt_utc.astimezone(est_tz)
                                        elif '+' in close_time or (close_time.count('-') > 2 and 'T' in close_time):
                                            # Has timezone offset - parse as-is, then convert to EST
                                            dt_parsed = datetime.fromisoformat(close_time)
                                            close_dt = dt_parsed.astimezone(est_tz)
                                        else:
                                            # No timezone marker - assume UTC (Kalshi default), then convert to EST
                                            date_part = close_time.split('T')[0]
                                            time_part = close_time.split('T')[1].split('+')[0].split('-')[0].split('Z')[0]
                                            naive_dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                                            dt_utc = naive_dt.replace(tzinfo=utc_tz)
                                            close_dt = dt_utc.astimezone(est_tz)
                                    else:
                                        # Non-ISO format - assume UTC, then convert to EST
                                        naive_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                                        dt_utc = naive_dt.replace(tzinfo=utc_tz)
                                        close_dt = dt_utc.astimezone(est_tz)
                                    
                                    # DO NOT subtract 3 hours - match start time fields are already correct
                                    # The 3-hour subtraction was causing incorrect calculations
                                    # Use the parsed time as-is since we're using match start time fields
                                else:
                                    close_dt = None
                                
                                if close_dt:
                                    # Work entirely in EST for calculations
                                    now = datetime.now(est_tz)
                                    time_diff_minutes = (close_dt - now).total_seconds() / 60
                                    time_diff_hours = time_diff_minutes / 60
                                    
                                    # Log which field was used for debugging
                                    logger.debug(f"  Time field used: {time_field_used} = {close_time}")
                                    logger.debug(f"  Parsed time (EST): {close_dt}")
                                    logger.debug(f"  Current time (EST): {now}")
                                    logger.debug(f"  Time difference: {time_diff_hours:.2f} hours ({time_diff_minutes:.1f} minutes)")
                                    
                                    # Reject if using event_close_time and time is > 48 hours (tournament end, not match start)
                                    if time_diff_hours > 48 and time_field_used == "event_close_time":
                                        time_info = f" (⚠️ Using tournament end: {time_diff_hours:.1f}h - REJECTED, no valid match start time)"
                                    elif time_diff_hours > 168:  # > 7 days - definitely wrong
                                        time_info = f" (⚠️ Time is {time_diff_hours:.1f}h - REJECTED, likely tournament end)"
                                    elif time_diff_minutes < 0:
                                        time_info = f" (Match started {abs(time_diff_minutes):.0f} min ago)"
                                    elif time_diff_minutes < 15:
                                        time_info = f" (Match starts in {time_diff_minutes:.0f} min - TOO SOON)"
                                    elif time_diff_hours > 48:
                                        time_info = f" (⚠️ Match starts in {time_diff_hours:.1f}h - Suspicious, might be tournament end)"
                                    else:
                                        # Format time nicely
                                        if time_diff_hours >= 1:
                                            hours = int(time_diff_hours)
                                            minutes = int((time_diff_hours - hours) * 60)
                                            if minutes > 0:
                                                time_info = f" (Match starts in {hours}h{minutes}m)"
                                            else:
                                                time_info = f" (Match starts in {hours}h)"
                                        else:
                                            time_info = f" (Match starts in {time_diff_minutes:.0f} min)"
                    except Exception:
                        pass
                    
                    if is_tradable:
                        # Determine which player we're betting on
                        bet_on_player = analysis.get('bet_on_player')
                        if not bet_on_player:
                            # Fallback: use trade_side to determine
                            trade_side = analysis.get('trade_side', '')
                            if trade_side == 'yes':
                                bet_on_player = players[0] if players[0] else "Unknown"
                            else:
                                bet_on_player = players[1] if players[1] else "Unknown"
                        
                        model_prob = analysis.get('model_probability', 0)
                        kalshi_prob = analysis.get('kalshi_probability', 0)
                        kalshi_odds = analysis.get('kalshi_odds', {})
                        yes_price = kalshi_odds.get('yes_price', 0) if kalshi_odds else 0
                        no_price = kalshi_odds.get('no_price', 0) if kalshi_odds else 0
                        
                        logger.info(f"\n   [{i}/{len(top_tradable)}] {title}")
                        logger.info(f"      Match: {players_str}")
                        volume_str = f"${market_volume:,.0f}" if market_volume is not None else "N/A"
                        # Use trade_value (already absolute) or abs(value) for display
                        edge_display = analysis.get("trade_value", abs(value))
                        logger.info(f"      Edge: {edge_display:.1%} | EV: {ev:+.1%} | Volume: {volume_str}{time_info}")
                        logger.info(f"      Model Probability: {model_prob:.1%} | Kalshi Probability: {kalshi_prob:.1%}")
                        if yes_price and no_price:
                            logger.info(f"      Kalshi Odds: YES @ {yes_price:.1f}¢ | NO @ {no_price:.1f}¢")
                        logger.info(f"      🎯 BET ON: {bet_on_player} @ {yes_price:.1f}¢")
                        logger.info(f"      Ticker: {ticker}")
                    else:
                        logger.info(f"\n   ❌ Market #{i}: {title}")
                        logger.info(f"      Ticker: {ticker}")
                        logger.info(f"      Players: {players_str}")
                        if value or ev:
                            edge_display = analysis.get("trade_value", abs(value))
                            logger.info(f"      Value Edge: {edge_display:.1%} | Expected Value: {ev:.1%}")
                        if market_volume:
                            logger.info(f"      Market Volume: ${market_volume:,.0f}{time_info}")
                        elif market_volume is None:
                            logger.info(f"      Market Volume: N/A{time_info}")
                        logger.info(f"      Status: REJECTED")
                        if reason:
                            # Format reason (might be a list)
                            if isinstance(reason, list):
                                reason_str = " | ".join(reason)
                            else:
                                reason_str = str(reason)
                            logger.info(f"      Reason: {reason_str}")
                        else:
                            logger.info(f"      Reason: Unknown (check logs for details)")
                
                # Place trades for current batch
                logger.info(f"\n{'=' * 70}")
                logger.info(f"🔨 TRADING BATCH {batch_number} ({len(current_batch)} opportunities)")
                logger.info(f"{'=' * 70}")
                
                batch_trades = []
                for i, opp in enumerate(current_batch, 1):
                    value = opp.get("value", 0)
                    trade_value = opp.get("trade_value", abs(value))  # Use trade_value (already absolute) if available
                    ev = opp.get("expected_value", 0)
                    ticker = opp.get("ticker", "Unknown")
                    title = opp.get("title", "Unknown")
                    
                    if trade_value >= self.min_value_threshold and ev >= self.min_ev_threshold:
                        # Determine which player we're betting on
                        bet_on_player = opp.get('bet_on_player')
                        if not bet_on_player:
                            players = opp.get('matched_players', ('', ''))
                            trade_side = opp.get('trade_side', '')
                            if trade_side == 'yes':
                                bet_on_player = players[0] if players[0] else "Unknown"
                            else:
                                bet_on_player = players[1] if players[1] else "Unknown"
                        
                        model_prob = opp.get('model_probability', 0)
                        kalshi_prob = opp.get('kalshi_probability', 0)
                        kalshi_odds = opp.get('kalshi_odds', {})
                        yes_price = kalshi_odds.get('yes_price', 0) if kalshi_odds else 0
                        no_price = kalshi_odds.get('no_price', 0) if kalshi_odds else 0
                        
                        logger.info(f"\n   [{i}/{len(current_batch)}] {title}")
                        logger.info(f"      Model Probability: {model_prob:.1%} | Kalshi Probability: {kalshi_prob:.1%}")
                        if yes_price and no_price:
                            logger.info(f"      Kalshi Odds: YES @ {yes_price:.1f}¢ | NO @ {no_price:.1f}¢")
                        logger.info(f"      🎯 BET ON: {bet_on_player} @ {yes_price:.1f}¢ | Edge: {trade_value:.1%} | EV: {ev:+.1%}")
                        trade_result = self.place_trade(opp)
                        if trade_result:
                            batch_trades.append(trade_result)
                            all_trades_placed.append(trade_result)
                            # Log detailed trade placement info
                            if self.dry_run:
                                logger.info(f"      ✅ TRADE SIMULATED (DRY RUN): {bet_on_player} - {ticker}")
                            else:
                                order_id = trade_result.get("order", {}).get("order_id", "Unknown")
                                order_status = trade_result.get("order", {}).get("status", "Unknown")
                                logger.info(f"      ✅ TRADE PLACED (LIVE): {bet_on_player} - {ticker}")
                                logger.info(f"         Order ID: {order_id} | Status: {order_status}")
                        else:
                            logger.warning(f"      ❌ TRADE FAILED: {bet_on_player} - {ticker}")
                    else:
                        logger.debug(f"   [{i}/{len(current_batch)}] Skipping {ticker} (below thresholds)")
                
                # Log batch summary
                mode_indicator = "🧪 DRY RUN" if self.dry_run else "🔴 LIVE"
                trade_action = "simulated" if self.dry_run else "placed"
                logger.info(f"\n   ✅ BATCH {batch_number} COMPLETE ({mode_indicator} MODE)")
                logger.info(f"      Trades {trade_action} in this batch: {len(batch_trades)}/{len(current_batch)}")
                
                # After trading this batch, filter out the traded events from the remaining list
                # This allows the next batch to show the next 5 opportunities (not just skip ahead)
                # Re-filter the remaining list to exclude newly traded events
                new_remaining = []
                for opp in remaining_tradable:  # Check remaining opportunities
                    ticker = opp.get("ticker", "")
                    if not ticker:
                        continue
                    
                    event_ticker = self._extract_event_ticker(ticker)
                    if event_ticker and event_ticker in self.traded_events:
                        # Skip - already traded (in this batch or previously)
                        continue
                    
                    # Check if we have an existing position
                    if self.check_existing_position(ticker):
                        continue
                    
                    # Still available - add to next batch's remaining list
                    new_remaining.append(opp)
                
                # Update remaining list for next iteration (already sorted by volume)
                remaining_tradable = new_remaining
                
                # If no trades were placed in this batch, stop (no point continuing)
                if len(batch_trades) == 0:
                    logger.info(f"   ⚠️  No trades placed in batch {batch_number}, stopping progressive trading")
                    break
                
                batch_number += 1
                
                # Safety limit: don't trade more than 50 opportunities in a single scan
                if batch_number * batch_size > 50:
                    logger.info(f"   ⚠️  Reached safety limit of 50 opportunities per scan, stopping")
                    break
            
            # Final summary
            if not all_trades_placed:
                logger.info(f"\n{'=' * 70}")
                logger.info("⚠️  NO TRADABLE OPPORTUNITIES FOUND")
                logger.info(f"{'=' * 70}")
                return []
            
            mode_indicator = "🧪 DRY RUN" if self.dry_run else "🔴 LIVE"
            logger.info(f"\n{'=' * 70}")
            logger.info(f"✅ SCAN COMPLETE ({mode_indicator} MODE)")
            trade_action = "simulated" if self.dry_run else "placed"
            logger.info(f"   Total batches traded: {batch_number}")
            logger.info(f"   Total trades {trade_action}: {len(all_trades_placed)}")
            if all_trades_placed:
                logger.info(f"   📋 TRADES {'SIMULATED' if self.dry_run else 'EXECUTED'}:")
                for i, trade in enumerate(trades_placed, 1):
                    ticker = trade.get("ticker", "Unknown")
                    players = trade.get("players", ("", ""))
                    bet_on_player = trade.get("bet_on_player", "Unknown")
                    model_prob = trade.get("model_probability", 0)
                    
                    # Format player names
                    player1 = players[0] if len(players) > 0 and players[0] else "Unknown"
                    player2 = players[1] if len(players) > 1 and players[1] else "Unknown"
                    match_str = f"{player1} vs {player2}" if player1 != "Unknown" and player2 != "Unknown" else ticker
                    
                    is_dry_run = trade.get("dry_run", self.dry_run)
                    mode_label = "🧪 DRY RUN" if is_dry_run else "🔴 LIVE"
                    logger.info(f"      {i}. {mode_label} | {match_str} | BET ON: {bet_on_player} | Model Win Rate: {model_prob:.1%}")
            logger.info(f"{'=' * 70}")
            return all_trades_placed
            
        except Exception as e:
            logger.error(f"Error in scan_and_trade: {e}", exc_info=True)
            return []
    
    def start_trading_loop(self, loop_interval_minutes: int = 15):
        """
        Start background trading loop in a separate thread.
        
        Args:
            loop_interval_minutes: Minutes between trading scans (default 15)
        """
        with self._trading_loop_lock:
            if self._trading_loop_running:
                logger.warning("Trading loop is already running!")
                return
            
            self._trading_loop_running = True
            self._loop_interval_seconds = loop_interval_minutes * 60
        
        def _trading_loop():
            """Background trading loop worker."""
            mode_str = "🧪 DRY RUN MODE" if self.dry_run else "🔴 LIVE TRADING MODE"
            logger.info(f"🔄 Background trading loop started (interval: {loop_interval_minutes} minutes)")
            logger.info(f"   {mode_str}")
            logger.info(f"   Traded events memory: {len(self.traded_events)} events")
            
            try:
                while self._trading_loop_running:
                    loop_start_time = time.time()
                    
                    try:
                        mode_str = "🧪 DRY RUN MODE" if self.dry_run else "🔴 LIVE TRADING MODE"
                        logger.info(f"\n{'=' * 70}")
                        logger.info(f"🔄 Automatic trading scan started - {mode_str}")
                        logger.info(f"{'=' * 70}")
                        
                        # Scan and trade
                        trades = self.scan_and_trade()
                        
                        # Log summary with clear mode indication
                        if trades:
                            mode_indicator = "🧪 SIMULATED" if self.dry_run else "🔴 LIVE"
                            logger.info(f"{mode_indicator} Trades {'simulated' if self.dry_run else 'placed'}: {len(trades)}")
                            for i, trade in enumerate(trades, 1):
                                ticker = trade.get('ticker', 'Unknown')
                                players = trade.get('players', ('', ''))
                                bet_on_player = trade.get('bet_on_player', 'Unknown')
                                is_trade_dry_run = trade.get('dry_run', self.dry_run)
                                trade_mode = "🧪 DRY RUN" if is_trade_dry_run else "🔴 LIVE"
                                logger.info(f"   {i}. {trade_mode} {ticker}: {bet_on_player} (Match: {players[0]} vs {players[1]})")
                        else:
                            logger.info(f"ℹ️  No trades {'simulated' if self.dry_run else 'placed'} in this scan")
                        
                        logger.info(f"{'=' * 70}\n")
                        
                    except Exception as e:
                        logger.error(f"❌ Error in trading loop scan: {e}", exc_info=True)
                    
                    # Calculate sleep time
                    elapsed = time.time() - loop_start_time
                    sleep_time = max(0, self._loop_interval_seconds - elapsed)
                    
                    # Wait for next scan (but check _trading_loop_running periodically)
                    if sleep_time > 0:
                        logger.info(f"💤 Sleeping for {sleep_time/60:.1f} minutes until next scan...")
                        # Sleep in chunks to allow quick shutdown
                        chunks = int(sleep_time / 5) + 1
                        chunk_time = sleep_time / chunks
                        for _ in range(chunks):
                            if not self._trading_loop_running:
                                break
                            time.sleep(chunk_time)
                    else:
                        logger.warning(f"⚠️  Scan took {elapsed/60:.1f} minutes, longer than interval {loop_interval_minutes} minutes")
                        
            except KeyboardInterrupt:
                logger.info("Stopping background trading loop...")
            except Exception as e:
                logger.error(f"❌ Fatal error in trading loop: {e}", exc_info=True)
            finally:
                with self._trading_loop_lock:
                    self._trading_loop_running = False
                logger.info("🛑 Background trading loop stopped")
        
        # Start loop in background thread
        self._trading_loop_thread = threading.Thread(
            target=_trading_loop,
            daemon=False,  # Non-daemon so it doesn't exit when main thread exits
            name="TradingLoop"
        )
        self._trading_loop_thread.start()
        logger.info("✅ Background trading loop thread started")
    
    def stop_trading_loop(self):
        """Stop background trading loop."""
        with self._trading_loop_lock:
            if not self._trading_loop_running:
                logger.info("Trading loop is not running")
                return
            
            logger.info("Stopping background trading loop...")
            self._trading_loop_running = False
        
        # Wait for thread to finish (with timeout)
        if self._trading_loop_thread and self._trading_loop_thread.is_alive():
            self._trading_loop_thread.join(timeout=10)
            if self._trading_loop_thread.is_alive():
                logger.warning("Trading loop thread did not stop within timeout")
            else:
                logger.info("✅ Background trading loop stopped")
    
    def is_trading_loop_running(self) -> bool:
        """Check if background trading loop is running."""
        with self._trading_loop_lock:
            return self._trading_loop_running
    
    def run_continuous(self):
        """
        Run continuous trading loop (blocking version, for backward compatibility).
        
        NOTE: Prefer start_trading_loop() for non-blocking background execution.
        """
        logger.info("Starting continuous trading loop...")
        logger.info(f"Scan interval: {self.scan_interval} seconds")
        logger.info(f"Dry run mode: {self.dry_run}")
        
        try:
            while True:
                start_time = time.time()
                
                # Scan and trade
                trades = self.scan_and_trade()
                
                # Log summary
                if trades:
                    logger.info(f"Trades placed: {len(trades)}")
                    for trade in trades:
                        logger.info(f"  - {trade.get('ticker', 'Unknown')}: "
                                  f"{trade.get('count', 0)} contracts @ "
                                  f"{trade.get('price', 0)} cents")
                
                # Wait for next scan
                elapsed = time.time() - start_time
                sleep_time = max(0, self.scan_interval - elapsed)
                
                if sleep_time > 0:
                    logger.info(f"Sleeping for {sleep_time:.1f} seconds until next scan...")
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"Scan took {elapsed:.1f}s, longer than interval {self.scan_interval}s")
                    
        except KeyboardInterrupt:
            logger.info("Stopping continuous trading loop...")
        except Exception as e:
            logger.error(f"Error in continuous loop: {e}", exc_info=True)
            raise
    
    def get_trade_summary(self) -> Dict[str, Any]:
        """Get summary of all trades placed."""
        return {
            "total_trades": len(self.trade_history),
            "traded_markets": len(self.traded_markets),
            "trades": self.trade_history,
        }


def create_auto_trader(
    min_value_threshold: float = 0.02,
    min_ev_threshold: float = 0.05,
    max_position_size: int = 10,
    scan_interval: int = 60,
    dry_run: bool = True,
) -> AutoTrader:
    """
    Factory function to create an AutoTrader with default configuration.
    
    Args:
        min_value_threshold: Minimum value edge (default 2%)
        min_ev_threshold: Minimum expected value (default 5%)
        max_position_size: Maximum contracts per trade
        scan_interval: Seconds between scans
        dry_run: If True, simulate trades without placing orders
    """
    from config.settings import (
        KALSHI_ACCESS_KEY, KALSHI_PRIVATE_KEY_PATH, KALSHI_PRIVATE_KEY,
        KALSHI_BASE_URL, KALSHI_USE_PRODUCTION
    )
    from src.trading.kalshi_client import Environment
    
    # Determine environment
    if KALSHI_USE_PRODUCTION:
        env = Environment.PROD
    else:
        env = Environment.DEMO
    
    # Initialize Kalshi client (it will auto-load credentials from config)
    client = KalshiClient(
        access_key=KALSHI_ACCESS_KEY,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        environment=env,
    )
    
    # Initialize analyzer
    player_db = PlayerStatsDB(raw_data_dir=str(RAW_DATA_DIR))
    predictor = MatchPredictor(models_dir=str(MODELS_DIR))
    analyzer = KalshiMarketAnalyzer(
        kalshi_client=client,
        player_db=player_db,
        predictor=predictor,
    )
    
    # Create trader
    trader = AutoTrader(
        kalshi_client=client,
        analyzer=analyzer,
        min_value_threshold=min_value_threshold,
        min_ev_threshold=min_ev_threshold,
        max_position_size=max_position_size,
        scan_interval=scan_interval,
        dry_run=dry_run,
    )
    
    return trader


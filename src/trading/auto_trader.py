"""
Automated trading system for Kalshi markets.
Continuously scans for opportunities and places trades when value threshold is met.
"""

import time
import logging
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
        self.traded_markets = set()  # Set of tickers we've already traded
        self.trade_history = []  # List of all trades placed
        
        # Ensure logs directory exists
        Path("logs").mkdir(exist_ok=True)
        
        logger.info(f"AutoTrader initialized: min_value={min_value_threshold:.1%}, "
                   f"min_ev={min_ev_threshold:.1%}, max_size={max_position_size}, "
                   f"dry_run={dry_run}")
    
    def get_current_positions(self) -> Dict[str, Any]:
        """Get current positions from Kalshi."""
        try:
            positions = self.client.get_positions()
            return positions
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return {}
    
    def calculate_position_size(self, opportunity: Dict[str, Any]) -> int:
        """
        Calculate position size based on value edge and risk management.
        
        Args:
            opportunity: Opportunity dictionary from analyzer
            
        Returns:
            Number of contracts to trade
        """
        value_edge = opportunity.get("value", 0)
        expected_value = opportunity.get("expected_value", 0)
        market_volume = opportunity.get("market_volume", 0)
        
        # Base position size on value edge (more edge = larger position)
        # Scale from 1 to max_position_size based on value edge
        if value_edge < self.min_value_threshold:
            return 0
        
        # Linear scaling: 2% edge = 1 contract, 10% edge = max_position_size
        edge_range = 0.10 - self.min_value_threshold  # 0.08 (8%)
        if edge_range <= 0:
            edge_range = 0.01
        
        normalized_edge = (value_edge - self.min_value_threshold) / edge_range
        normalized_edge = max(0, min(1, normalized_edge))  # Clamp to [0, 1]
        
        position_size = int(1 + normalized_edge * (self.max_position_size - 1))
        
        # Also consider market volume - don't trade huge positions in low-volume markets
        if market_volume is not None and market_volume < 5000:
            position_size = min(position_size, 3)
        
        return max(1, min(position_size, self.max_position_size))
    
    def check_existing_position(self, ticker: str) -> bool:
        """
        Check if we already have a position in this market.
        
        Args:
            ticker: Market ticker
            
        Returns:
            True if we already have a position
        """
        try:
            positions = self.get_current_positions()
            positions_list = positions.get("positions", [])
            
            for pos in positions_list:
                if pos.get("ticker") == ticker:
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
        
        # Check if we already traded this market
        if ticker in self.traded_markets:
            logger.info(f"Skipping {ticker}: already traded")
            return None
        
        # Check if we already have a position
        if self.check_existing_position(ticker):
            logger.info(f"Skipping {ticker}: already have position")
            return None
        
        # CRITICAL: Check if match is within the trading window
        # Rules:
        # - Always: at least 10 minutes before match start
        # - No maximum time limit (can trade anytime before match start)
        try:
            # Get market data to check expiration time
            # Extract event_ticker from market ticker (format: SERIES-DATE-EVENT-SUFFIX)
            # e.g., KXATPMATCH-26JAN03NAVTHO-THO -> KXATPMATCH-26JAN03NAVTHO
            event_ticker = None
            if ticker and '-' in ticker:
                parts = ticker.rsplit('-', 1)  # Split on last dash
                if len(parts) == 2:
                    event_ticker = parts[0]  # Everything before last dash
            
            markets_response = self.client.get_markets(event_ticker=event_ticker, limit=1) if event_ticker else None
            if not markets_response:
                return None
            if markets_response.get("markets"):
                market = markets_response["markets"][0]
                # CRITICAL: Try to find the actual match start time, not expiration/close time
                # Expiration times are when the market CLOSES (after match ends), not when match starts
                # We want the match START time, which should be BEFORE the expiration
                # Prioritize match START time fields - these are when the match begins
                
                # DEBUG: Log all available time fields
                logger.info(f"🔍 DEBUG TIME FIELDS for {ticker}:")
                for field in ["match_start_time", "start_time", "scheduled_time", "expected_start_time", 
                             "expected_expiration_time", "expiration_time", "close_time", "event_close_time"]:
                    val = market.get(field)
                    if val:
                        logger.info(f"  {field}: {val}")
                
                close_time = None
                time_field_used = None
                
                # First priority: Match start time fields (these are when the match begins)
                for field in ["match_start_time", "start_time", "scheduled_time", "expected_start_time"]:
                    time_val = market.get(field)
                    if time_val:
                        close_time = time_val
                        time_field_used = field
                        logger.info(f"  ✅ Using match START time field: {field} = {time_val}")
                        break
                
                # Second priority: Only if no start time found, try expiration fields
                # But these are when the market closes (after match ends), so add warning
                if not close_time:
                    for field in ["expected_expiration_time", "expiration_time", "close_time"]:
                        time_val = market.get(field)
                        if time_val:
                            close_time = time_val
                            time_field_used = field
                            logger.warning(f"  ⚠️ WARNING: Using {field} (expiration time) instead of match start time - this may be 2-3 hours later than match start!")
                            break
                
                # Last resort: event_close_time (usually tournament end, not match start)
                if not close_time:
                    event_close = market.get("event_close_time")
                    if event_close:
                        close_time = event_close
                        time_field_used = "event_close_time"
                        logger.warning(f"  ⚠️ WARNING: Using event_close_time (last resort) - this is usually tournament end, not match start!")
                
                # DEBUG: Log all time fields to see what Kalshi is actually sending
                logger.info(f"🔍 DEBUG TIME PARSING for {ticker}:")
                logger.info(f"  Time field used: {time_field_used} = {close_time}")
                logger.info(f"  All available time fields:")
                logger.info(f"    match_start_time: {market.get('match_start_time')}")
                logger.info(f"    start_time: {market.get('start_time')}")
                logger.info(f"    scheduled_time: {market.get('scheduled_time')}")
                logger.info(f"    expected_start_time: {market.get('expected_start_time')}")
                logger.info(f"    expected_expiration_time: {market.get('expected_expiration_time')}")
                logger.info(f"    expiration_time: {market.get('expiration_time')}")
                logger.info(f"    close_time: {market.get('close_time')}")
                logger.info(f"    event_close_time: {market.get('event_close_time')}")
                
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
                    
                    # CRITICAL FIX: Kalshi times appear to be 3 hours ahead of actual match start
                    # Subtract 3 hours to get the actual match start time
                    # This accounts for a systematic offset in Kalshi's time data
                    if close_dt:
                        close_dt = close_dt - timedelta(hours=3)
                        logger.info(f"  ✅ Adjusted for 3-hour offset: {close_dt}")
                    else:
                        close_dt = None
                    
                    if close_dt:
                        # Work entirely in EST for calculations
                        now = datetime.now(est_tz)
                        time_diff_minutes = (close_dt - now).total_seconds() / 60
                        logger.info(f"  ⏰ Current EST time: {now}")
                        logger.info(f"  ⏰ Match EST time: {close_dt}")
                        logger.info(f"  ⏰ Time difference: {time_diff_minutes:.1f} minutes ({time_diff_minutes/60:.1f} hours)")
                        
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
        
        # Get current price from orderbook (use bid for buying)
        try:
            orderbook = self.client.get_orderbook(ticker)
            bids = orderbook.get("bids", [])
            
            if not bids:
                logger.warning(f"No bids available for {ticker}")
                return None
            
            # Use best bid price (highest price someone is willing to pay)
            best_bid_price = bids[0].get("price")
            if not best_bid_price:
                logger.warning(f"No price in orderbook for {ticker}")
                return None
        except Exception as e:
            logger.error(f"Error getting orderbook for {ticker}: {e}")
            return None
        
        # Place order
        order_data = {
            "ticker": ticker,
            "side": trade_side,  # "yes" or "no"
            "action": "buy",
            "count": position_size,
            "price": best_bid_price,  # Limit order at best bid
        }
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would place order: {order_data}")
            logger.info(f"  Opportunity: {opportunity.get('title', 'Unknown')}")
            logger.info(f"  Value edge: {opportunity.get('value', 0):.2%}")
            logger.info(f"  Expected value: {opportunity.get('expected_value', 0):.2%}")
            
            # Simulate successful order
            simulated_order = {
                "order_id": f"dry_run_{ticker}_{int(time.time())}",
                "status": "resting",
                "ticker": ticker,
                "side": trade_side,
                "count": position_size,
                "price": best_bid_price,
            }
            
            self.traded_markets.add(ticker)
            self.trade_history.append({
                "timestamp": datetime.now().isoformat(),
                "ticker": ticker,
                "opportunity": opportunity,
                "order": simulated_order,
                "dry_run": True,
            })
            
            return simulated_order
        else:
            try:
                logger.info(f"Placing order: {order_data}")
                order_response = self.client.place_order(**order_data)
                
                logger.info(f"Order placed successfully: {order_response}")
                self.traded_markets.add(ticker)
                self.trade_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "ticker": ticker,
                    "opportunity": opportunity,
                    "order": order_response,
                    "dry_run": False,
                })
                
                return order_response
            except Exception as e:
                logger.error(f"Error placing order for {ticker}: {e}")
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
            )
            
            # Sort tradable by market volume (descending) - same as opportunities endpoint
            tradable.sort(key=lambda x: x.get("market_volume") or 0, reverse=True)
            
            # Limit to top 5 opportunities (matching opportunities endpoint default)
            # This ensures live trading matches what's shown in Top Trading Opportunities
            top_tradable = tradable[:5]
            
            # Log summary
            logger.info(f"\n{'=' * 70}")
            logger.info(f"📊 SCAN SUMMARY")
            logger.info(f"{'=' * 70}")
            logger.info(f"   Markets analyzed: {len(all_analyses)}")
            logger.info(f"   Tradable opportunities: {len(tradable)}")
            logger.info(f"   Top opportunities (by volume): {len(top_tradable)}")
            logger.info(f"   Rejected: {len(all_analyses) - len(tradable)}")
            
            # Log details for TOP TRADABLE markets only (matching opportunities endpoint)
            if top_tradable:
                logger.info(f"\n{'=' * 70}")
                logger.info(f"💰 TRADABLE OPPORTUNITIES ({len(top_tradable)})")
                logger.info(f"{'=' * 70}")
                for i, analysis in enumerate(top_tradable, 1):
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
                    
                    # Get time until match start
                    time_info = ""
                    try:
                        # Try to get expiration time from market
                        # Extract event_ticker from market ticker
                        event_ticker = None
                        if ticker and '-' in ticker:
                            parts = ticker.rsplit('-', 1)
                            if len(parts) == 2:
                                event_ticker = parts[0]
                        market_data = self.client.get_markets(event_ticker=event_ticker, limit=1) if event_ticker else None
                        if not market_data:
                            continue
                        if market_data.get("markets"):
                            market = market_data["markets"][0]
                            # CRITICAL: Prioritize match START times over expiration/close times
                            # Expiration times are when the market CLOSES (after match ends), not when match starts
                            # We want the match START time, which should be BEFORE the expiration
                            close_time = None
                            time_field_used = None
                            
                            # First priority: Match start time fields (these are when the match begins)
                            for field in ["match_start_time", "start_time", "scheduled_time", "expected_start_time"]:
                                time_val = market.get(field)
                                if time_val:
                                    close_time = time_val
                                    time_field_used = field
                                    break
                            
                            # Second priority: Only if no start time found, try expiration fields
                            # But these are when the market closes (after match ends), so add warning
                            if not close_time:
                                for field in ["expected_expiration_time", "expiration_time", "close_time"]:
                                    time_val = market.get(field)
                                    if time_val:
                                        close_time = time_val
                                        time_field_used = field
                                        logger.warning(f"  ⚠️ Using {field} (expiration time) instead of match start time for {ticker} - this may be inaccurate")
                                        break
                            
                            # Last resort: event_close_time (usually tournament end, not match start)
                            if not close_time:
                                event_close = market.get("event_close_time")
                                if event_close:
                                    close_time = event_close
                                    time_field_used = "event_close_time"
                                    logger.warning(f"  ⚠️ Using event_close_time (last resort) for {ticker} - this is usually tournament end, not match start")
                            
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
                                    
                                    # CRITICAL FIX: Kalshi times appear to be 3 hours ahead of actual match start
                                    # Subtract 3 hours to get the actual match start time
                                    # This accounts for a systematic offset in Kalshi's time data
                                    if close_dt:
                                        close_dt = close_dt - timedelta(hours=3)
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
            
            if not top_tradable:
                logger.info(f"\n{'=' * 70}")
                logger.info("⚠️  NO TRADABLE OPPORTUNITIES FOUND")
                logger.info(f"{'=' * 70}")
                return []
            
            # Place trades for top opportunities (matching opportunities endpoint)
            logger.info(f"\n{'=' * 70}")
            logger.info(f"🔨 TRADING PHASE ({len(top_tradable)} opportunities)")
            logger.info(f"{'=' * 70}")
            
            trades_placed = []
            for i, opp in enumerate(top_tradable, 1):
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
                    
                    logger.info(f"\n   [{i}/{len(top_tradable)}] {title}")
                    logger.info(f"      Model Probability: {model_prob:.1%} | Kalshi Probability: {kalshi_prob:.1%}")
                    if yes_price and no_price:
                        logger.info(f"      Kalshi Odds: YES @ {yes_price:.1f}¢ | NO @ {no_price:.1f}¢")
                    logger.info(f"      🎯 BET ON: {bet_on_player} @ {yes_price:.1f}¢ | Edge: {trade_value:.1%} | EV: {ev:+.1%}")
                    trade_result = self.place_trade(opp)
                    if trade_result:
                        trades_placed.append(trade_result)
                        logger.info(f"      ✅ TRADE PLACED")
                    else:
                        logger.warning(f"      ❌ TRADE FAILED")
                else:
                    logger.debug(f"   [{i}/{len(top_tradable)}] Skipping {ticker} (below thresholds)")
            
            logger.info(f"\n{'=' * 70}")
            logger.info(f"✅ SCAN COMPLETE | Trades placed: {len(trades_placed)}/{len(top_tradable)}")
            logger.info(f"{'=' * 70}")
            return trades_placed
            
        except Exception as e:
            logger.error(f"Error in scan_and_trade: {e}", exc_info=True)
            return []
    
    def run_continuous(self):
        """
        Run continuous trading loop.
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


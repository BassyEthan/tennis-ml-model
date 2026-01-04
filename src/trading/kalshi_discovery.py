"""
Kalshi Market Discovery - Search for events and filter markets.
Fetches events by keyword, extracts markets, and applies robust layered filtering.
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from src.trading.kalshi_client import KalshiClient

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
            return est_dt.strftime('%Y-%m-%d %I:%M %p EST')
        except:
            pass
    # Fallback: show UTC if EST conversion fails
    if dt.tzinfo:
        return dt.strftime('%Y-%m-%d %H:%M UTC')
    return dt.strftime('%Y-%m-%d %H:%M')


# Tennis keyword list for Layer 2 filtering (ATP only)
TENNIS_KEYWORDS = [
    "tennis", "atp", "wimbledon", "us open", "french open", 
    "australian open", "roland garros", "davis cup", "united cup",
    "atp match", "united cup match", "atp tennis"
]

# Tennis series ticker patterns (for Layer 1) - ATP only
TENNIS_SERIES_TICKERS = [
    "kxatpmatch", "kxunitedcupmatch", "kxatp",
    "kxunitedcup", "kxwimbledon", "kxusopen", "kxfrenchopen", "kxrolandgarros"
]

# Exclusion keywords for Layer 3 (match structure heuristic)
EXCLUSION_KEYWORDS = [
    "tournament", "season", "medals", "champion", "wins more than",
    "will win", "championship", "cup winner", "tournament winner"
]

# WTA exclusion keywords (explicitly reject WTA markets)
WTA_EXCLUSION_KEYWORDS = [
    "wta", "women's tennis", "women tennis", "women's tour", "wta tour",
    "kxwtamatch", "kxwta", "wta match", "wta tennis"
]


def fetch_events(
    client: KalshiClient,
    keyword: str = "tennis",
    status: str = "open",
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Fetch events from Kalshi API by keyword.
    
    Args:
        client: Initialized KalshiClient
        keyword: Search keyword (e.g., "tennis", "nba")
        status: Event status filter (e.g., "open")
        limit: Maximum number of events to fetch
        
    Returns:
        List of event dictionaries
    """
    all_events = []
    cursor = None
    max_pages = 10  # Limit pagination
    
    for page in range(max_pages):
        try:
            response = client.get_events(
                search=keyword,
                status=status,
                limit=min(limit - len(all_events), 1000),
                cursor=cursor
            )
            
            # Handle different response structures
            events = response.get("events", [])
            if not events:
                # Try alternative structure
                events = response.get("data", [])
            if not events and isinstance(response, list):
                events = response
            
            all_events.extend(events)
            
            # Check for pagination
            cursor = response.get("cursor") or response.get("next_cursor")
            if not cursor or len(events) == 0:
                break
                
            if len(all_events) >= limit:
                break
                
        except Exception as e:
            # If events endpoint doesn't exist, return empty list
            print(f"⚠️  Events endpoint not available: {e}")
            break
    
    return all_events[:limit]


def flatten_markets(events: List[Dict[str, Any]], client: Optional[KalshiClient] = None) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Extract markets from events and create normalized market records.
    
    Returns tuples of (event, market) for filtering.
    
    Args:
        events: List of event dictionaries from Kalshi API
        client: Optional KalshiClient to fetch markets if events don't contain them
        
    Returns:
        List of (event, market) tuples
    """
    event_market_pairs = []
    
    for event in events:
        event_ticker = event.get("event_ticker") or event.get("ticker")
        event_title = event.get("title") or event.get("name") or ""
        event_description = event.get("description") or event.get("sub_title") or ""
        event_close_time = event.get("close_time") or event.get("expiration_time") or event.get("expected_expiration_time")
        category = event.get("category", "")
        series_ticker = event.get("series_ticker", "")
        
        # Extract series ticker from event ticker if not provided
        # Format: KXATPMATCH-26JAN03SWEOCO -> series is KXATPMATCH
        if not series_ticker and event_ticker:
            ticker_parts = event_ticker.split("-")
            if ticker_parts:
                potential_series = ticker_parts[0].upper()
                # Check if it matches a known tennis series pattern
                if any(pattern.upper() in potential_series for pattern in TENNIS_SERIES_TICKERS):
                    series_ticker = potential_series
        
        # Get markets from event
        event_markets = event.get("markets", [])
        if not event_markets:
            # Some APIs return markets directly in event
            if "market" in event:
                event_markets = [event["market"]]
            elif client and event_ticker:
                # Try to fetch markets for this event using event_ticker
                try:
                    response = client.get_markets(event_ticker=event_ticker, limit=100, status="open")
                    event_markets = response.get("markets", [])
                except Exception:
                    event_markets = []
            elif "ticker" in event and "title" in event and "event_ticker" not in event:
                # Event might be a market itself
                event_markets = [event]
        
        # If still no markets, treat the event as a market itself
        if not event_markets:
            event_markets = [event]
        
        for market in event_markets:
            # Create normalized event record
            normalized_event = {
                "event_title": event_title,
                "event_description": event_description,
                "event_ticker": event_ticker,
                "event_close_time": event_close_time,
                "category": category,
                "series_ticker": series_ticker,
            }
            
            event_market_pairs.append((normalized_event, market))
    
    return event_market_pairs


def layer1_series_category(event: Dict[str, Any], market: Dict[str, Any]) -> Optional[str]:
    """
    Layer 1: Series / category check (optional, best signal).
    
    Returns None if passes (or not applicable), or rejection reason if fails.
    """
    series_ticker = event.get("series_ticker", "").lower()
    category = event.get("category", "").lower()
    market_ticker = market.get("ticker", "").lower()
    event_title = event.get("event_title", "").lower()
    market_title = market.get("title", "").lower()
    
    # CRITICAL: Explicitly reject WTA markets
    full_text = f"{event_title} {market_title} {series_ticker} {category} {market_ticker}"
    if any(wta_kw in full_text for wta_kw in WTA_EXCLUSION_KEYWORDS):
        return "wta_market_excluded"
    
    # Check series ticker patterns (e.g., KXATPMATCH, KXUNITEDCUPMATCH) - ATP only
    if series_ticker and any(pattern in series_ticker for pattern in TENNIS_SERIES_TICKERS):
        return None  # Pass - strong signal from series ticker
    
    # Check if market ticker itself contains tennis series pattern
    # Format: KXATPMATCH-26JAN03SWEOCO
    if market_ticker:
        # Check if ticker starts with a tennis series pattern
        ticker_parts = market_ticker.split("-")
        if ticker_parts:
            ticker_prefix = ticker_parts[0].lower()
            if any(pattern in ticker_prefix for pattern in TENNIS_SERIES_TICKERS):
                return None  # Pass - strong signal from market ticker
    
    # Check category
    if category and ("tennis" in category or "sports" in category):
        return None  # Pass - category indicates tennis
    
    # Don't reject if not found - this is optional layer
    return None


def layer2_tennis_keywords(event: Dict[str, Any], market: Dict[str, Any]) -> Optional[str]:
    """
    Layer 2: Tennis keyword detection.
    
    Returns None if passes, or rejection reason if fails.
    """
    event_title = event.get("event_title", "").lower()
    event_description = event.get("event_description", "").lower()
    market_title = market.get("title", "").lower()
    market_subtitle = market.get("subtitle", "").lower()
    series_ticker = event.get("series_ticker", "").lower()
    market_ticker = market.get("ticker", "").lower()
    
    # Combine all text fields for keyword search
    full_text = f"{event_title} {event_description} {market_title} {market_subtitle} {series_ticker} {market_ticker}"
    
    # CRITICAL: Explicitly reject WTA markets first
    if any(wta_kw in full_text for wta_kw in WTA_EXCLUSION_KEYWORDS):
        return "wta_market_excluded"
    
    # Check for at least one tennis keyword
    if any(keyword in full_text for keyword in TENNIS_KEYWORDS):
        return None  # Pass
    
    # Also check for series ticker patterns (e.g., kxatpmatch) - ATP only
    if any(pattern in full_text for pattern in TENNIS_SERIES_TICKERS):
        return None  # Pass - found tennis series ticker pattern
    
    return "tennis_keywords"  # Fail


def layer3_match_structure(event: Dict[str, Any], market: Dict[str, Any]) -> Optional[str]:
    """
    Layer 3: Match structure heuristic.
    
    Returns None if passes, or rejection reason if fails.
    """
    event_title = event.get("event_title", "").lower()
    market_title = market.get("title", "").lower()
    full_title = f"{event_title} {market_title}"
    
    # CRITICAL: Explicitly reject WTA markets
    if any(wta_kw in full_title for wta_kw in WTA_EXCLUSION_KEYWORDS):
        return "wta_market_excluded"
    
    # Must contain " vs " or " v. "
    if " vs " not in full_title and " v. " not in full_title and " vs. " not in full_title:
        return "match_structure_no_vs"
    
    # Exclude if contains exclusion keywords
    for exclusion in EXCLUSION_KEYWORDS:
        if exclusion in full_title:
            return f"match_structure_excluded_{exclusion.replace(' ', '_')}"
    
    return None  # Pass


def layer4_market_structure(event: Dict[str, Any], market: Dict[str, Any]) -> Optional[str]:
    """
    Layer 4: Market structure validation.
    
    Returns None if passes, or rejection reason if fails.
    """
    status = market.get("status", "").lower()
    
    # Must be open
    if status not in ["open", "active"]:
        return "market_structure_not_open"
    
    # Must have both yes_price and no_price (or bid/ask)
    yes_price = market.get("yes_price") or market.get("yes_bid") or market.get("last_price")
    no_price = market.get("no_price") or market.get("no_bid")
    
    # Try to get from orderbook if not in market
    if yes_price is None or no_price is None:
        # Prices might be in cents, check those
        yes_price = market.get("yes_bid_dollars") or market.get("yes_ask_dollars") or market.get("last_price_dollars")
        no_price = market.get("no_bid_dollars") or market.get("no_ask_dollars")
    
    if yes_price is None or (isinstance(yes_price, (int, float)) and yes_price == 0):
        return "market_structure_no_yes_price"
    
    if no_price is None or (isinstance(no_price, (int, float)) and no_price == 0):
        return "market_structure_no_no_price"
    
    return None  # Pass


def layer5_expiration_window(event: Dict[str, Any], market: Dict[str, Any], max_hours: int = 72, min_minutes_before: int = 10, max_minutes_before: Optional[int] = None, min_volume_for_no_max: float = 5000) -> Optional[str]:
    """
    Layer 5: Expiration window check.
    
    Ensures markets are:
    - In the future (not started yet)
    - At least min_minutes_before minutes before match start (to allow time for order placement)
    - No maximum time limit (can trade anytime before match start)
    - Within max_hours from now
    
    Args:
        event: Event dictionary
        market: Market dictionary
        max_hours: Maximum hours until expiration
        min_minutes_before: Minimum minutes before match start (default 10 minutes buffer)
        max_minutes_before: (Deprecated - no longer used, kept for compatibility)
        min_volume_for_no_max: (Deprecated - no longer used, kept for compatibility)
    
    Returns None if passes, or rejection reason if fails.
    """
    # Try multiple time fields - event_close_time might be tournament end, not match start
    # CRITICAL: Prefer market-level times over event-level times
    # Market times are usually match-specific, event times are usually tournament-wide
    
    # First, try market-level fields (these are more likely to be match start times)
    # CRITICAL: Prioritize match START times over expiration/close times
    # Expiration times are when the market CLOSES (after match ends), not when match starts
    market_time_fields = [
        "match_start_time",          # Explicit match start (BEST - use this if available)
        "start_time",                # Market start time
        "scheduled_time",            # Scheduled time
        "expected_start_time",       # Expected start time
        "expected_expiration_time",  # Market expiration (usually when match ends or market closes)
        "expiration_time",           # Market expiration
        "close_time",                # Market close time
    ]
    
    # Then try event-level fields (but these might be tournament end times)
    event_time_fields = [
        "match_start_time",          # Event match start (if available)
        "start_time",                # Event start time
        "scheduled_time",            # Event scheduled time
        "expected_start_time",       # Event expected start time
        # NOTE: Do NOT use event_close_time or event expiration_time as they're usually tournament end
    ]
    
    close_time = None
    time_field_used = None
    
    # Try market fields first
    for field in market_time_fields:
        time_val = market.get(field)
        if time_val:
            close_time = time_val
            time_field_used = f"market.{field}"
            break
    
    # If no market time found, try event fields (but be cautious)
    if not close_time:
        for field in event_time_fields:
            time_val = event.get(field)
            if time_val:
                close_time = time_val
                time_field_used = f"event.{field}"
                break
    
    # Last resort: use event close/expiration, but only if it's reasonable (< 7 days)
    # This is usually the tournament end, not match start, so we'll validate it
    if not close_time:
        event_close = event.get("event_close_time") or event.get("close_time") or event.get("expiration_time")
        if event_close:
            # We'll use it but validate it's not too far in the future
            close_time = event_close
            time_field_used = "event.close_time (last resort)"
    
    if not close_time:
        # If no close time, we can't validate - be lenient
        return None
    
    try:
        # Parse close time
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
        else:
            return "expiration_window_invalid_format"
        
        # Work entirely in EST for calculations
        now = datetime.now(est_tz)
        time_diff_hours = (close_dt - now).total_seconds() / 3600
        time_diff_minutes = (close_dt - now).total_seconds() / 60
        
        # CRITICAL: If time is suspiciously far, it's likely tournament end, not match start
        # Reject times > 48 hours if they're from event-level fields (tournament end)
        # Reject times > 7 days (168 hours) even from market fields (definitely wrong)
        if time_diff_hours > 168:  # More than 7 days - definitely wrong, reject
            return f"expiration_window_too_far_{time_diff_hours:.1f}h (likely tournament end, not match start)"
        
        # If time is from event.close_time and > 48 hours, it's definitely tournament end
        if "event.close_time" in time_field_used and time_diff_hours > 48:
            return f"expiration_window_too_far_{time_diff_hours:.1f}h (event.close_time is tournament end, not match start)"
        
        # If time is > 48 hours, try to find a better time field
        if time_diff_hours > 48:  # More than 2 days - suspicious, try to find better
            # Try to find a closer time in other fields
            better_time = None
            better_field = None
            
            # Check all market time fields we haven't tried yet
            for field in market_time_fields:
                if field != time_field_used.replace("market.", ""):
                    time_val = market.get(field)
                    if time_val:
                        try:
                            # Work entirely in EST
                            if ZoneInfo:
                                est_tz = ZoneInfo("America/New_York")
                            else:
                                est_tz = timezone(timedelta(hours=-5))
                            
                            if isinstance(time_val, str):
                                if 'T' in time_val:
                                    # ISO format - extract and parse as EST
                                    date_part = time_val.split('T')[0]
                                    time_part = time_val.split('T')[1].split('+')[0].split('-')[0].split('Z')[0]
                                    naive_dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                                else:
                                    # Non-ISO format - parse as EST
                                    naive_dt = datetime.strptime(time_val, "%Y-%m-%d %H:%M:%S")
                                
                                # Assign EST timezone
                                if hasattr(est_tz, 'localize'):
                                    test_dt = est_tz.localize(naive_dt)
                                else:
                                    test_dt = naive_dt.replace(tzinfo=est_tz)
                            else:
                                continue
                            
                            # Work entirely in EST - no UTC conversion
                            test_diff_hours = (test_dt - now).total_seconds() / 3600
                            # If this time is closer and reasonable (< 7 days), use it
                            if 0 < test_diff_hours < 168 and test_diff_hours < time_diff_hours:
                                better_time = test_dt
                                better_field = f"market.{field}"
                        except:
                            continue
            
            # If we found a better time, use it
            if better_time:
                close_dt = better_time
                time_field_used = better_field
                time_diff_hours = (close_dt - now).total_seconds() / 3600
                time_diff_minutes = (close_dt - now).total_seconds() / 60
            # Otherwise, if it's still > 7 days and we used event.close_time, reject it
            elif time_diff_hours > 168 and "event.close_time" in time_field_used:
                return f"expiration_window_too_far_{time_diff_hours:.1f}h (likely tournament end, not match start)"
        
        # DEBUG: Log which time field was used (for suspicious times)
        if time_diff_hours > 48:  # More than 2 days
            market_ticker = market.get("ticker", "Unknown")
            # Only log if it's really suspicious (> 7 days)
            if time_diff_hours > 168:
                print(f"  ⚠️  DEBUG: Market {market_ticker} using {time_field_used}, time_diff={time_diff_hours:.1f}h (suspicious - might be tournament end)")
        
        # Must be in the future (with 2 hour grace period for markets that just closed)
        if time_diff_hours < -2:
            return "expiration_window_past"
        
        # CRITICAL: Must be at least min_minutes_before minutes before match start
        # This ensures we place bets BEFORE matches begin, not during
        if time_diff_minutes < min_minutes_before:
            return f"expiration_window_too_soon_{time_diff_minutes:.1f}min_need_{min_minutes_before}min"
        
        # No maximum time limit - all markets can trade anytime before match start
        # (as long as they meet the 10 minute minimum, which is already checked above)
        # Volume is no longer used to determine time limits
        
        # Must be within max_hours (but allow markets up to 14 days for tournament matches)
        # Tournament matches can be listed well in advance, so we use a more lenient limit
        effective_max_hours = max(max_hours, 336)  # At least 14 days (336 hours)
        if time_diff_hours > effective_max_hours:
            return f"expiration_window_too_far_{time_diff_hours:.1f}h"
        
        return None  # Pass
        
    except Exception as e:
        # If parsing fails, be lenient
        return None


def layer6_liquidity(event: Dict[str, Any], market: Dict[str, Any], min_volume: float = 200) -> Optional[str]:
    """
    Layer 6: Liquidity check.
    
    Returns None if passes, or rejection reason if fails.
    """
    volume = market.get("volume_dollars") or market.get("liquidity_dollars") or market.get("volume", 0)
    
    # Convert to float if string
    try:
        volume = float(volume) if volume else 0
    except (ValueError, TypeError):
        volume = 0
    
    # Convert volume units if needed
    # If we got volume_dollars or liquidity_dollars, it's already in dollars
    if market.get("volume_dollars") or market.get("liquidity_dollars"):
        # Already in dollars, use as-is
        pass
    elif volume > 1000000:
        # Very large number - definitely in cents, convert to dollars
        volume = volume / 100.0
    elif volume > 100000:
        # Large number - likely in cents, convert to dollars
        volume = volume / 100.0
    elif volume > 10000:
        # Medium number - could be either, but for active markets volumes are typically $1k-$50k
        # If it's in the 10k-100k range, it's probably already in dollars (matches website)
        # Only convert if it's clearly in cents (e.g., > 50k)
        if volume > 50000:
            volume = volume / 100.0
        # Otherwise assume already in dollars
    # If < 10k, assume already in dollars
    
    if volume < min_volume:
        return f"liquidity_too_low_{volume:.0f}"
    
    return None  # Pass


def is_valid_tennis_market(
    event: Dict[str, Any],
    market: Dict[str, Any],
    max_hours: int = 72,
    min_volume: float = 200,
    min_minutes_before: int = 10,  # Minimum minutes before match start
    max_minutes_before: Optional[int] = None,  # (Deprecated - no longer used, kept for compatibility)
    min_volume_for_no_max: float = 5000,  # (Deprecated - no longer used, kept for compatibility)
    log_rejections: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Final filter function - applies all layers.
    
    Args:
        event: Normalized event dictionary
        market: Market dictionary
        max_hours: Maximum hours until expiration
        min_volume: Minimum volume in dollars
        log_rejections: Whether to log rejection reasons
        
    Returns:
        Tuple of (is_valid, rejection_reason)
    """
    # Apply layers in order
    layers = [
        ("series_category", layer1_series_category),
        ("tennis_keywords", layer2_tennis_keywords),
        ("match_structure", layer3_match_structure),
        ("market_structure", layer4_market_structure),
        ("expiration_window", lambda e, m: layer5_expiration_window(e, m, max_hours, min_minutes_before, max_minutes_before, min_volume_for_no_max)),
        ("liquidity", lambda e, m: layer6_liquidity(e, m, min_volume)),
    ]
    
    for layer_name, layer_func in layers:
        rejection_reason = layer_func(event, market)
        if rejection_reason:
            if log_rejections:
                market_ticker = market.get("ticker", "unknown")
                print(f"  ❌ {market_ticker}: FAILED {layer_name} - {rejection_reason}")
            return False, f"{layer_name}:{rejection_reason}"
    
    return True, None


def filter_tennis_markets(
    event_market_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
    max_hours: int = 72,
    min_volume: float = 200,
    min_minutes_before: int = 10,  # Minimum minutes before match start (buffer for order placement)
    max_minutes_before: Optional[int] = None,  # (Deprecated - no longer used, kept for compatibility)
    min_volume_for_no_max: float = 5000,  # (Deprecated - no longer used, kept for compatibility)
    log_rejections: bool = True
) -> List[Dict[str, Any]]:
    """
    Filter event-market pairs through all layers and return valid tennis markets.
    
    Args:
        event_market_pairs: List of (event, market) tuples
        max_hours: Maximum hours until expiration
        min_volume: Minimum volume in dollars
        log_rejections: Whether to log rejection reasons
        
    Returns:
        List of normalized market dictionaries
    """
    valid_markets = []
    
    if log_rejections:
        print(f"\n🔍 Filtering {len(event_market_pairs)} event-market pairs through 6 layers...")
    
    for event, market in event_market_pairs:
        is_valid, rejection_reason = is_valid_tennis_market(
            event, market, max_hours, min_volume, 
            min_minutes_before=min_minutes_before,
            max_minutes_before=max_minutes_before,
            min_volume_for_no_max=min_volume_for_no_max,
            log_rejections=log_rejections
        )
        
        if is_valid:
            # Create normalized output record
            market_ticker = market.get("ticker", "")
            yes_price = market.get("yes_price") or market.get("yes_bid") or market.get("last_price")
            no_price = market.get("no_price") or market.get("no_bid")
            
            # Try dollars if cents
            if yes_price and isinstance(yes_price, (int, float)) and yes_price > 1:
                yes_price = yes_price / 100.0
            if no_price and isinstance(no_price, (int, float)) and no_price > 1:
                no_price = no_price / 100.0
            
            # Get volume - prioritize explicit dollar fields, then generic volume
            volume = market.get("volume_dollars") or market.get("liquidity_dollars") or market.get("volume", 0)
            try:
                volume = float(volume) if volume else 0
                # If we got volume_dollars or liquidity_dollars, it's already in dollars
                if market.get("volume_dollars") or market.get("liquidity_dollars"):
                    # Already in dollars, use as-is
                    pass
                elif volume > 1000000:
                    # Very large number - definitely in cents, convert to dollars
                    volume = volume / 100.0
                elif volume > 100000:
                    # Large number - likely in cents, convert to dollars
                    volume = volume / 100.0
                elif volume > 10000:
                    # Medium number - could be either, but for active markets volumes are typically $1k-$50k
                    # If it's in the 10k-100k range, it's probably already in dollars (matches website)
                    # Only convert if it's clearly in cents (e.g., > 50k)
                    if volume > 50000:
                        volume = volume / 100.0
                    # Otherwise assume already in dollars
                # If < 10k, assume already in dollars
            except (ValueError, TypeError):
                volume = 0
            
            valid_market = {
                "event_title": event.get("event_title", ""),
                "market_ticker": market_ticker,
                "yes_price": yes_price,
                "no_price": no_price,
                "volume": volume,
                "event_close_time": event.get("event_close_time") or market.get("close_time"),
            }
            valid_markets.append(valid_market)
    
    if log_rejections:
        print(f"✅ {len(valid_markets)} markets passed all filters")
    
    # Sort by: soonest event_close_time, then highest volume
    # Work entirely in EST
    if ZoneInfo:
        est_tz = ZoneInfo("America/New_York")
    else:
        est_tz = timezone(timedelta(hours=-5))
    
    def sort_key(m):
        close_time = m.get("event_close_time")
        volume = m.get("volume", 0)
        
        try:
            if isinstance(close_time, str):
                if 'T' in close_time:
                    # ISO format - extract and parse as EST
                    date_part = close_time.split('T')[0]
                    time_part = close_time.split('T')[1].split('+')[0].split('-')[0].split('Z')[0]
                    naive_dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                else:
                    # Non-ISO format - parse as EST
                    naive_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                
                # Assign EST timezone
                if hasattr(est_tz, 'localize'):
                    dt = est_tz.localize(naive_dt)
                else:
                    dt = naive_dt.replace(tzinfo=est_tz)
            else:
                # Default to far future in EST
                dt = datetime.now(est_tz) + timedelta(days=365)
            
            return (dt.timestamp(), -volume)
        except Exception:
            return (0, -volume)
    
    valid_markets.sort(key=sort_key)
    return valid_markets

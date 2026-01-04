"""
Kalshi Market Discovery - Search for events and filter markets.
Fetches events by keyword, extracts markets, and applies robust layered filtering.
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from src.trading.kalshi_client import KalshiClient


# Tennis keyword list for Layer 2 filtering
TENNIS_KEYWORDS = [
    "tennis", "atp", "wta", "wimbledon", "us open", "french open", 
    "australian open", "roland garros", "davis cup", "united cup",
    "atp match", "wta match", "united cup match", "atp tennis", "wta tennis"
]

# Tennis series ticker patterns (for Layer 1)
TENNIS_SERIES_TICKERS = [
    "kxatpmatch", "kxwtamatch", "kxunitedcupmatch", "kxatp", "kxwta",
    "kxunitedcup", "kxwimbledon", "kxusopen", "kxfrenchopen", "kxrolandgarros"
]

# Exclusion keywords for Layer 3 (match structure heuristic)
EXCLUSION_KEYWORDS = [
    "tournament", "season", "medals", "champion", "wins more than",
    "will win", "championship", "cup winner", "tournament winner"
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
    
    # Check series ticker patterns (e.g., KXATPMATCH, KXWTAMATCH, KXUNITEDCUPMATCH)
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
    
    # Check for at least one tennis keyword
    if any(keyword in full_text for keyword in TENNIS_KEYWORDS):
        return None  # Pass
    
    # Also check for series ticker patterns (e.g., kxatpmatch, kxwtamatch)
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


def layer5_expiration_window(event: Dict[str, Any], market: Dict[str, Any], max_hours: int = 72) -> Optional[str]:
    """
    Layer 5: Expiration window check.
    
    Returns None if passes, or rejection reason if fails.
    """
    close_time = event.get("event_close_time") or market.get("close_time") or market.get("expiration_time")
    
    if not close_time:
        # If no close time, we can't validate - be lenient
        return None
    
    try:
        # Parse close time
        if isinstance(close_time, str):
            if 'T' in close_time:
                close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            else:
                close_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                close_dt = close_dt.replace(tzinfo=timezone.utc)
        else:
            return "expiration_window_invalid_format"
        
        # Normalize to UTC
        if close_dt.tzinfo is None:
            close_dt = close_dt.replace(tzinfo=timezone.utc)
        else:
            close_dt = close_dt.astimezone(timezone.utc)
        
        now = datetime.now(timezone.utc)
        time_diff = (close_dt - now).total_seconds() / 3600  # hours
        
        # Must be in the future (with 2 hour grace period for markets that just closed)
        if time_diff < -2:
            return "expiration_window_past"
        
        # Must be within max_hours
        if time_diff > max_hours:
            return f"expiration_window_too_far_{time_diff:.1f}h"
        
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
    
    # If volume is in cents, convert to dollars
    if volume > 1000:
        volume = volume / 100.0
    
    if volume < min_volume:
        return f"liquidity_too_low_{volume:.0f}"
    
    return None  # Pass


def is_valid_tennis_market(
    event: Dict[str, Any],
    market: Dict[str, Any],
    max_hours: int = 72,
    min_volume: float = 200,
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
        ("expiration_window", lambda e, m: layer5_expiration_window(e, m, max_hours)),
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
            event, market, max_hours, min_volume, log_rejections
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
            
            volume = market.get("volume_dollars") or market.get("liquidity_dollars") or market.get("volume", 0)
            try:
                volume = float(volume) if volume else 0
                if volume > 1000:
                    volume = volume / 100.0
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
    def sort_key(m):
        close_time = m.get("event_close_time")
        volume = m.get("volume", 0)
        
        try:
            if isinstance(close_time, str):
                if 'T' in close_time:
                    dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                else:
                    dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.now(timezone.utc) + timedelta(days=365)
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            
            return (dt.timestamp(), -volume)
        except Exception:
            return (0, -volume)
    
    valid_markets.sort(key=sort_key)
    return valid_markets

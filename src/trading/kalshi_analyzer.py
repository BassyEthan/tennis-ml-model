"""
Kalshi Market Analyzer - Fetches Kalshi markets, matches to players,
and generates predictions for value trading opportunities.
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from difflib import SequenceMatcher
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
from src.trading.kalshi_client import KalshiClient
from src.trading.kalshi_discovery import fetch_events, flatten_markets, filter_tennis_markets
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor


def format_time_est(dt: datetime) -> str:
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


class KalshiMarketAnalyzer:
    """
    Analyzes Kalshi markets for tennis matches and identifies value trades.
    
    Workflow:
    1. Fetch available Kalshi markets
    2. Parse market titles to extract player names
    3. Match names to our player database
    4. Generate model predictions
    5. Compare predictions to Kalshi odds
    6. Identify value opportunities
    """
    
    def __init__(self, kalshi_client: Optional[KalshiClient] = None,
                 player_db: Optional[PlayerStatsDB] = None,
                 predictor: Optional[MatchPredictor] = None):
        """
        Initialize analyzer with required components.
        
        Args:
            kalshi_client: Initialized KalshiClient instance
            player_db: Initialized PlayerStatsDB instance
            predictor: Initialized MatchPredictor instance
        """
        self.kalshi = kalshi_client or KalshiClient()
        self.player_db = player_db
        self.predictor = predictor
        
        # Common tennis tournament keywords to filter markets
        self.tennis_keywords = [
            "tennis", "atp", "grand slam", "wimbledon", 
            "us open", "french open", "australian open", "roland garros",
            "united cup", "davis cup", "atp cup", "laver cup"
        ]
    
    def fetch_tennis_markets(self, limit: int = 100, 
                            event_ticker: Optional[str] = None,
                            debug: bool = False,
                            max_hours_ahead: int = 48,
                            min_volume: int = 0,
                            use_event_search: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch tennis-related markets from Kalshi.
        
        Args:
            limit: Maximum number of markets to fetch
            event_ticker: Optional event ticker to filter by
            debug: Print debug information about fetched markets
            
        Returns:
            List of market dictionaries
        """
        try:
            if debug:
                print(f"\n🔍 Fetching markets from Kalshi API...")
                print(f"   Parameters: limit={limit}, event_ticker={event_ticker}")
            
            # Strategy 1: Try direct market search by tennis series tickers (most reliable)
            markets = []
            if not event_ticker:
                if debug:
                    print(f"   Strategy 1: Searching markets by tennis series tickers...")
                
                # Known tennis series tickers from Kalshi
                tennis_series = ["KXATPMATCH", "KXUNITEDCUPMATCH"]  # ATP only
                
                all_markets_from_series = []
                for series in tennis_series:
                    try:
                        if debug:
                            print(f"   Searching series: {series}...")
                        
                        # Use pagination to fetch ALL markets, not just first batch
                        series_markets = []
                        cursor = None
                        max_batch_size = 1000
                        total_fetched = 0
                        
                        while True:
                            batch_limit = min(max_batch_size, limit - total_fetched)
                            if batch_limit <= 0:
                                break
                            
                            response = self.kalshi.get_markets(
                                series_ticker=series,
                                status="open",
                                limit=batch_limit,
                                cursor=cursor
                            )
                            
                            batch_markets = response.get("markets", [])
                            if batch_markets:
                                series_markets.extend(batch_markets)
                                total_fetched += len(batch_markets)
                                if debug and len(batch_markets) == batch_limit:
                                    print(f"   Fetched {len(batch_markets)} markets (total: {total_fetched})...")
                            
                            # Check for pagination cursor
                            cursor = response.get("cursor")
                            if not cursor or len(batch_markets) < batch_limit:
                                break  # No more pages or got fewer than requested
                            
                            # Safety limit: don't fetch more than requested
                            if total_fetched >= limit:
                                break
                        
                        if series_markets:
                            if debug:
                                print(f"   ✅ Found {len(series_markets)} markets in {series}")
                            all_markets_from_series.extend(series_markets)
                    except Exception as e:
                        if debug:
                            print(f"   ⚠️  Error fetching {series}: {e}")
                
                if all_markets_from_series:
                    if debug:
                        print(f"   ✅ Total markets from series search: {len(all_markets_from_series)}")
                    markets = all_markets_from_series
                else:
                    if debug:
                        print(f"   ⚠️  No markets found via series search, trying event search...")
            
            # Strategy 2: Try event search API with robust filtering (fallback)
            if not markets and not event_ticker:
                if debug:
                    print(f"   Strategy 2: Trying event search API with keyword 'tennis'...")
                try:
                    events = fetch_events(self.kalshi, keyword="tennis", status="open", limit=limit)
                    if events:
                        if debug:
                            print(f"   ✅ Found {len(events)} events via event search API")
                        # Flatten events into markets (pass client to fetch markets if needed)
                        event_market_pairs = flatten_markets(events, client=self.kalshi)
                        if debug:
                            print(f"   ✅ Extracted {len(event_market_pairs)} event-market pairs")
                        
                        # Apply robust layered filtering
                        filtered_markets = filter_tennis_markets(
                            event_market_pairs,
                            max_hours=max_hours_ahead,
                            min_volume=min_volume,
                            min_minutes_before=10,  # Minimum: trades placed at least 10 min before match start
                            max_minutes_before=None,  # No maximum time limit
                            min_volume_for_no_max=5000,  # (Deprecated - no longer used)
                            log_rejections=debug
                        )
                        
                        # Convert filtered markets back to original format for compatibility
                        # Need to get original market objects from pairs
                        markets = []
                        valid_tickers = {m.get("market_ticker") for m in filtered_markets}
                        for event, market in event_market_pairs:
                            if market.get("ticker") in valid_tickers:
                                markets.append(market)
                        
                        if debug:
                            print(f"   ✅ After robust filtering: {len(markets)} valid tennis markets")
                except Exception as e:
                    if debug:
                        print(f"   ⚠️  Event search API not available: {e}")
                        print(f"   Falling back to direct market search...")
                    import traceback
                    traceback.print_exc()
            
            # Strategy 2: Fallback to direct market search (if event search didn't work or event_ticker provided)
            if not markets or event_ticker:
                if debug:
                    if event_ticker:
                        print(f"   Using event_ticker filter: {event_ticker}")
                    else:
                        print(f"   Using direct market search...")
                
                all_markets = []
                cursor = None
                max_batch_size = 1000
                batches_to_fetch = (limit + max_batch_size - 1) // max_batch_size
                
                for batch_num in range(min(batches_to_fetch, 10)):
                    batch_limit = min(max_batch_size, limit - len(all_markets))
                    if batch_limit <= 0:
                        break
                        
                    response = self.kalshi.get_markets(
                        event_ticker=event_ticker,
                        limit=batch_limit,
                        cursor=cursor
                    )
                    
                    batch_markets = response.get("markets", [])
                    all_markets.extend(batch_markets)
                    
                    if debug:
                        print(f"   Batch {batch_num + 1}: Got {len(batch_markets)} markets (total: {len(all_markets)})")
                    
                    cursor = response.get("cursor")
                    if not cursor or len(batch_markets) < batch_limit:
                        break
                
                # If we got markets from direct search, use those
                if all_markets:
                    markets = all_markets
            
            # Apply full filtering to all markets (Strategy 1, 2, or 3)
            # All markets need to go through the robust layered filtering for consistency
            if markets and not event_ticker:
                try:
                    # Convert markets to event-market pairs format for filtering
                    event_market_pairs = []
                    for market in markets:
                        # Create a normalized event from market data
                        normalized_event = {
                            "event_title": market.get("event_title", ""),
                            "event_description": market.get("event_description", ""),
                            "event_ticker": market.get("event_ticker", ""),
                            "event_close_time": market.get("event_close_time") or market.get("close_time"),
                            "category": market.get("category", ""),
                            "series_ticker": market.get("series_ticker", ""),
                        }
                        event_market_pairs.append((normalized_event, market))
                    
                    # Apply robust layered filtering (same as Strategy 2)
                    if debug:
                        print(f"   🔍 Applying full filtering to {len(event_market_pairs)} markets...")
                    filtered_markets = filter_tennis_markets(
                        event_market_pairs,
                        max_hours=max_hours_ahead,
                        min_volume=min_volume,
                        min_minutes_before=10,  # Minimum: trades placed at least 10 min before match start
                        max_minutes_before=None,  # No maximum time limit
                        min_volume_for_no_max=10000,  # (Deprecated - no longer used)
                        log_rejections=debug
                    )
                    
                    # Convert back to original market format
                    valid_tickers = {m.get("market_ticker") for m in filtered_markets}
                    filtered = [m for m in markets if m.get("ticker") in valid_tickers]
                    
                    if debug:
                        print(f"   ✅ After full filtering: {len(filtered)} markets (from {len(markets)} original)")
                    
                    markets = filtered
                except Exception as e:
                    if debug:
                        print(f"   ⚠️  Filtering error (continuing with unfiltered): {e}")
            
            if debug:
                print(f"   ✅ Total markets fetched: {len(markets)}")
                if markets:
                    print(f"   ✅ Got {len(markets)} total markets from API")
                if not markets:
                    print(f"   ⚠️  WARNING: No markets returned!")
                else:
                    # Show sample of what we got
                    print(f"\n   Sample markets (first 5):")
                    for i, m in enumerate(markets[:5], 1):
                        print(f"     {i}. Title: '{m.get('title', 'N/A')}'")
                        print(f"        Ticker: {m.get('ticker', 'N/A')}")
                        print(f"        Category: {m.get('category', 'N/A')}")
                        print(f"        Event: {m.get('event_ticker', 'N/A')}")
                        print(f"        Status: {m.get('status', 'N/A')}")
                        print()
            
            # If we got markets but they're not tennis, we might need to search more
            # or use different API parameters
            
            if debug:
                print(f"Fetched {len(markets)} total markets from Kalshi")
                if markets:
                    print("\nSample market structure:")
                    sample = markets[0]
                    for key in ["ticker", "title", "subtitle", "category", "event_ticker", "series_ticker"]:
                        if key in sample:
                            print(f"  {key}: {sample[key]}")
            
            # First, try to parse ALL markets for player names (more reliable than keyword filtering)
            # This catches markets like "United Cup Zverev vs Griekspoor" even if "United Cup" isn't in keywords
            tennis_markets = []
            parsed_count = 0
            skipped_no_parse = 0
            from datetime import timezone
            # Work entirely in EST - no UTC
            if ZoneInfo:
                est_tz = ZoneInfo("America/New_York")
            else:
                est_tz = timezone(timedelta(hours=-5))
            
            now = datetime.now(est_tz)
            max_time = now + timedelta(hours=max_hours_ahead)
            
            if debug:
                print(f"\nProcessing {len(markets)} markets...")
                print(f"Searching ALL markets for tennis matches...")
                
                # Search through ALL markets for tennis-related content
                tennis_keywords_in_markets = []
                player_names_in_markets = []
                for m in markets:
                    title = m.get('title', '').lower()
                    subtitle = m.get('subtitle', '').lower()
                    full_text = f"{title} {subtitle}"
                    
                    # Check for tennis keywords
                    if any(kw in full_text for kw in ['tennis', 'atp', 'united cup', 'davis cup']):
                        tennis_keywords_in_markets.append(m.get('title', 'N/A'))
                    
                    # Check for known player names
                    known_players = ['zverev', 'griekspoor', 'gauff', 'swiatek', 'djokovic', 'nadal', 'fritz', 
                                    'harris', 'tsitsipas', 'ruud', 'auger', 'aliassime', 'raducanu', 'osaka', 
                                    'zhang', 'munar', 'fils', 'hurkacz', 'de minaur', 'ruusuvuori']
                    for player in known_players:
                        if player in full_text:
                            player_names_in_markets.append((m.get('title', 'N/A'), player))
                            break
                
                if tennis_keywords_in_markets:
                    print(f"\nFound {len(tennis_keywords_in_markets)} markets with tennis keywords:")
                    for title in tennis_keywords_in_markets[:10]:
                        print(f"  - {title}")
                
                if player_names_in_markets:
                    print(f"\nFound {len(player_names_in_markets)} markets with known player names:")
                    for title, player in player_names_in_markets[:10]:
                        print(f"  - {title} (contains: {player})")
                
                if not tennis_keywords_in_markets and not player_names_in_markets:
                    print(f"\n⚠️  No tennis keywords or known player names found in any of {len(markets)} markets!")
                    print(f"   This suggests tennis markets might be:")
                    print(f"   1. Not in the first {len(markets)} results (try increasing --limit)")
                    print(f"   2. Using different title formats")
                    print(f"   3. In a different category/series that needs filtering")
                    print(f"\n   Sample non-tennis markets received:")
                    for i, m in enumerate(markets[:5], 1):
                        print(f"     {i}. {m.get('title', 'N/A')} (category: {m.get('category', 'N/A')}, event: {m.get('event_ticker', 'N/A')})")
                
                # CRITICAL: Search through ALL markets, not just first few
                # Look for any market that might be tennis-related
                print(f"\n🔎 Searching ALL {len(markets)} markets for tennis matches...")
                all_titles_with_vs = []
                for m in markets:
                    title = m.get('title', '').lower()
                    if ' vs ' in title or ' v ' in title:
                        all_titles_with_vs.append((m.get('title', 'N/A'), m.get('ticker', 'N/A')))
                
                if all_titles_with_vs:
                    print(f"   Found {len(all_titles_with_vs)} markets with 'vs' in title:")
                    # Search for specific players the user is looking for
                    search_players = ['zverev', 'griekspoor', 'zhang', 'auger', 'aliassime', 'munar', 'fritz']
                    for title, ticker in all_titles_with_vs[:20]:
                        # Highlight if it might be tennis
                        is_tennis_like = any(name in title.lower() for name in 
                                           ['zverev', 'griekspoor', 'gauff', 'swiatek', 'djokovic', 'nadal', 
                                            'fritz', 'harris', 'tsitsipas', 'ruud', 'garin', 'mmoh', 'tennis',
                                            'zhang', 'auger', 'aliassime', 'munar'])
                        marker = " 🎾" if is_tennis_like else ""
                        # Highlight specific players user is looking for
                        for player in search_players:
                            if player in title.lower():
                                marker = f" ⭐ {player.upper()}"
                                break
                        print(f"     - {title}{marker} (ticker: {ticker})")
                    
                else:
                    print(f"   ⚠️  No markets found with 'vs' in title at all!")
            
            for market in markets:
                # First try to parse player names - if we can't parse it, skip time/volume checks
                players = self.parse_player_names(market)
                if not players:
                    skipped_no_parse += 1
                    title = market.get('title', 'N/A')
                    subtitle = market.get('subtitle', 'N/A')
                    if debug:
                        # Always show if it contains known player names, even if we can't parse
                        known_names = ['zverev', 'griekspoor', 'gauff', 'swiatek', 'djokovic', 'nadal', 'fritz', 
                                     'harris', 'tsitsipas', 'auger', 'aliassime', 'zhang', 'ruud', 'garin', 'mmoh',
                                     'munar', 'fils', 'hurkacz', 'de minaur']
                        if any(name in title.lower() or (subtitle and name in subtitle.lower()) for name in known_names):
                            print(f"  ⚠ Could not parse player names from: {title}")
                            if subtitle and subtitle != 'N/A':
                                print(f"     Subtitle: '{subtitle}'")
                            print(f"     Trying to debug - title structure: '{title}'")
                            # Try to show what patterns might match
                            if 'vs' in title.lower() or ' v ' in title.lower() or 'vs' in subtitle.lower():
                                print(f"     Contains 'vs' but pattern didn't match")
                                # Show what the regex would see
                                print(f"     Full text: '{title} {subtitle}'")
                    continue  # Skip if we can't parse player names
                
                # Filter by time - include markets within max_hours_ahead
                # IMPORTANT: Don't filter out markets that are very close (they might be starting soon!)
                market_time = self._parse_market_time(market)
                if market_time:
                    # Work entirely in EST - no UTC conversion
                    if ZoneInfo:
                        est_tz = ZoneInfo("America/New_York")
                    else:
                        est_tz = timezone(timedelta(hours=-5))
                    
                    # Ensure timezone is EST
                    if market_time.tzinfo is None:
                        # Naive datetime - assume EST
                        if hasattr(est_tz, 'localize'):
                            market_time = est_tz.localize(market_time)
                        else:
                            market_time = market_time.replace(tzinfo=est_tz)
                    elif market_time.tzinfo != est_tz:
                        # Convert to EST if it's another timezone (shouldn't happen if we parse correctly)
                        market_time = market_time.astimezone(est_tz)
                    
                    now_est = datetime.now(est_tz)
                    time_diff = (market_time - now_est).total_seconds() / 3600  # hours
                    
                    # Only skip if market is more than max_hours_ahead away
                    if time_diff > max_hours_ahead:
                        if debug:
                            est_time = format_time_est(market_time)
                            print(f"  Skipped (too far): {market.get('title', 'N/A')} (time: {est_time}, {time_diff:.1f}h away)")
                        continue
                    
                    # Don't skip markets that are very close (even if slightly in the past)
                    # Markets might still be tradeable if they're within a few hours
                    if time_diff < -2:  # More than 2 hours in the past
                        if debug:
                            est_time = format_time_est(market_time)
                            print(f"  Skipped (too far past): {market.get('title', 'N/A')} (time: {est_time}, {time_diff:.1f}h ago)")
                        continue
                    
                    # Log markets that are very close (might be starting soon)
                    if debug and -1 < time_diff < 3:  # Between 1 hour ago and 3 hours ahead
                        est_time = format_time_est(market_time)
                        print(f"  ⏰ Market starting soon: {market.get('title', 'N/A')} (time: {est_time}, {time_diff:.1f}h {'ago' if time_diff < 0 else 'ahead'})")
                
                # NOTE: Volume filtering is now done in scan_markets AFTER aggregation
                # This ensures we use total match volume, not individual market volume
                
                # If we got here, it's a valid tennis market
                tennis_markets.append(market)
                parsed_count += 1
                if debug and parsed_count <= 10:
                    time_str = format_time_est(market_time) if market_time else "N/A"
                    volume_str = f" (volume: ${self._get_market_volume(market):,.0f})" if self._get_market_volume(market) else ""
                    players_str = f" ({players[0]} vs {players[1]})"
                    print(f"  ✓ Parsed tennis match: {market.get('title', 'N/A')}{players_str} (time: {time_str}{volume_str})")
            
            # If we found markets by parsing, use those
            if tennis_markets:
                if debug:
                    print(f"\nFound {len(tennis_markets)} markets by parsing player names")
            else:
                # Fallback: filter by keywords if parsing didn't work
                if debug:
                    print("\nNo markets found by parsing. Trying keyword filtering...")
                
                for market in markets:
                    title = market.get("title", "").lower()
                    subtitle = market.get("subtitle", "").lower()
                    category = market.get("category", "").lower()
                    event_tick = market.get("event_ticker", "").lower() if market.get("event_ticker") else ""
                    series_tick = market.get("series_ticker", "").lower() if market.get("series_ticker") else ""
                    
                    # Check if it's a tennis market
                    is_tennis = any(
                        keyword in title or keyword in subtitle or keyword in category 
                        or keyword in event_tick or keyword in series_tick
                        for keyword in self.tennis_keywords
                    )
                    
                    # Also check if ticker contains TENNIS
                    ticker = market.get("ticker", "").upper()
                    if "TENNIS" in ticker:
                        is_tennis = True
                    
                    if is_tennis:
                        tennis_markets.append(market)
            
            if debug:
                print(f"\nSummary:")
                print(f"  Total markets processed: {len(markets)}")
                print(f"  Could not parse player names: {skipped_no_parse}")
                print(f"  Successfully parsed: {len(tennis_markets)}")
                if tennis_markets:
                    print("\nSample tennis markets:")
                    for i, m in enumerate(tennis_markets[:5], 1):
                        players = self.parse_player_names(m)
                        players_str = f" ({players[0]} vs {players[1]})" if players else ""
                        print(f"  {i}. {m.get('title', 'N/A')}{players_str}")
                else:
                    print(f"\n⚠️  NO TENNIS MARKETS FOUND")
                    print(f"\nPossible reasons:")
                    print(f"  1. No active tennis markets on Kalshi right now")
                    print(f"  2. Tennis markets require a specific event_ticker or series_ticker")
                    print(f"  3. Tennis markets might be created closer to match time")
                    print(f"\nTo find tennis markets:")
                    print(f"  - Check Kalshi website/app for active tennis markets")
                    print(f"  - Note the event ticker or series ticker from the market URL")
                    print(f"  - Use --event-ticker <TICKER> to filter for that event")
                    print(f"  - Example: python3 scripts/trading/scan_kalshi_markets.py --event-ticker TENNIS-UNITEDCUP-2024")
            
            # Final WTA exclusion filter - explicitly remove any WTA markets that slipped through
            wta_keywords = ["wta", "women's tennis", "women tennis", "women's tour", "wta tour", 
                           "kxwtamatch", "kxwta", "wta match", "wta tennis"]
            filtered_tennis_markets = []
            for market in tennis_markets:
                # Check all text fields for WTA keywords
                title = (market.get("title", "") or "").lower()
                subtitle = (market.get("subtitle", "") or "").lower()
                ticker = (market.get("ticker", "") or "").lower()
                event_title = (market.get("event_title", "") or "").lower()
                series_ticker = (market.get("series_ticker", "") or "").lower()
                
                full_text = f"{title} {subtitle} {ticker} {event_title} {series_ticker}"
                
                # Skip if contains any WTA keyword
                if any(wta_kw in full_text for wta_kw in wta_keywords):
                    if debug:
                        print(f"   ❌ Excluding WTA market: {market.get('ticker', 'Unknown')} - {title[:60]}")
                    continue
                
                filtered_tennis_markets.append(market)
            
            if debug and len(tennis_markets) != len(filtered_tennis_markets):
                print(f"   ⚠️  Excluded {len(tennis_markets) - len(filtered_tennis_markets)} WTA markets")
            
            return filtered_tennis_markets
        except Exception as e:
            print(f"Error fetching markets: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _parse_market_time(self, market: Dict[str, Any]) -> Optional[datetime]:
        """
        Parse market start time from market data.
        
        Tries various field names, prioritizing match start times over expiration times.
        Expiration times might be when the market closes (after match ends), not when match starts.
        """
        # Try various possible field names, in priority order
        # Market-level fields are preferred (they're match-specific)
        # CRITICAL: Prioritize match START times over expiration/close times
        # Expiration times are when the market CLOSES (after match ends), not when match starts
        time_fields = [
            "match_start_time",        # Explicit match start (BEST - use this if available)
            "start_time",              # Market start time
            "scheduled_time",          # Scheduled time
            "expected_start_time",      # Expected start time
            "expected_expiration_time", # Market expiration (might be match end, but closer than event end)
            "expiration_time",         # Market expiration
            "close_time",              # Market close time
            "expected_expiration",     # Alternative expiration field
            "event_time",              # Event time
            "market_time",             # Market time
            "expires_at"               # Expires at
        ]
        
        # Work entirely in EST - no UTC
        if ZoneInfo:
            est_tz = ZoneInfo("America/New_York")
        else:
            est_tz = timezone(timedelta(hours=-5))
        
        now = datetime.now(est_tz)
        best_time = None
        best_diff = float('inf')
        
        for field in time_fields:
            time_val = market.get(field)
            if time_val:
                try:
                    # Try parsing as ISO format string
                    # CRITICAL: Kalshi API returns times in UTC (with 'Z' suffix)
                    # We MUST parse as UTC first, then convert to EST for all calculations
                    utc_tz = timezone.utc
                    
                    if isinstance(time_val, str):
                        # Handle different formats
                        if 'T' in time_val:
                            # ISO format - check for timezone marker
                            if time_val.endswith('Z'):
                                # Explicitly UTC - parse as UTC, then convert to EST
                                dt_utc = datetime.fromisoformat(time_val.replace('Z', '+00:00'))
                                dt = dt_utc.astimezone(est_tz)
                            elif '+' in time_val or (time_val.count('-') > 2 and 'T' in time_val):
                                # Has timezone offset - parse as-is, then convert to EST
                                dt_parsed = datetime.fromisoformat(time_val)
                                dt = dt_parsed.astimezone(est_tz)
                            else:
                                # No timezone marker - assume UTC (Kalshi default), then convert to EST
                                date_part = time_val.split('T')[0]
                                time_part = time_val.split('T')[1].split('+')[0].split('-')[0].split('Z')[0]
                                naive_dt = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                                dt_utc = naive_dt.replace(tzinfo=utc_tz)
                                dt = dt_utc.astimezone(est_tz)
                        else:
                            # Non-ISO format - assume UTC, then convert to EST
                            naive_dt = datetime.strptime(time_val, "%Y-%m-%d %H:%M:%S")
                            dt_utc = naive_dt.replace(tzinfo=utc_tz)
                            dt = dt_utc.astimezone(est_tz)
                    elif isinstance(time_val, (int, float)):
                        # Unix timestamp - parse as UTC, then convert to EST
                        dt_utc = datetime.fromtimestamp(time_val, tz=utc_tz)
                        dt = dt_utc.astimezone(est_tz)
                    else:
                        continue
                    
                    # CRITICAL FIX: Kalshi times appear to be 3 hours ahead of actual match start
                    # Subtract 3 hours to get the actual match start time
                    # This accounts for a systematic offset in Kalshi's time data
                    dt = dt - timedelta(hours=3)
                    
                    # Work entirely in EST for calculations
                    # Calculate time difference in EST
                    time_diff_hours = abs((dt - now).total_seconds() / 3600)
                    
                    # Prefer times that are:
                    # 1. In the future (or very recent past, within 2 hours)
                    # 2. Not suspiciously far (> 7 days = likely tournament end)
                    # 3. Closer to now (more likely to be match start)
                    if -2 <= time_diff_hours < 168:  # Between 2 hours ago and 7 days ahead
                        if time_diff_hours < best_diff:
                            best_time = dt
                            best_diff = time_diff_hours
                    
                except (ValueError, TypeError):
                    continue
        
        # Return the best time found, or None if none found
        return best_time
    
    def _get_market_volume(self, market: Dict[str, Any], fetch_fresh: bool = True) -> Optional[float]:
        """
        Get market volume/pot size from market data.
        
        Tries to fetch fresh market data if available, then tries various field names.
        
        Args:
            market: Market dictionary (may be stale)
            fetch_fresh: If True, try to fetch fresh market data from API
            
        Returns volume in dollars, or None if not found.
        """
        ticker = market.get("ticker")
        
        # Try to fetch fresh market data if we have a ticker
        fresh_market = None
        client = getattr(self, 'kalshi', None) or getattr(self, 'client', None) or getattr(self, 'kalshi_client', None)
        if fetch_fresh and ticker and client:
            try:
                # Try to get fresh market data
                # Extract event_ticker from market ticker
                event_ticker = None
                if ticker and '-' in ticker:
                    parts = ticker.rsplit('-', 1)
                    if len(parts) == 2:
                        event_ticker = parts[0]
                markets_response = client.get_markets(event_ticker=event_ticker, limit=1) if event_ticker else None
                if not markets_response:
                    pass  # Fall back to provided market data
                else:
                    markets_list = markets_response.get("markets", [])
                if markets_list:
                    fresh_market = markets_list[0]
            except Exception:
                # If fetching fails, fall back to provided market data
                pass
        
        # Use fresh market if available, otherwise use provided market
        market_to_check = fresh_market if fresh_market else market
        
        # Try various possible field names (volume might be in cents or dollars)
        # Order matters - try most specific first
        # NOTE: Kalshi website shows "volume" which is current market volume in dollars
        # The API might return this in different fields or units
        volume_fields = [
            "volume_dollars",  # Most specific - explicitly in dollars (traded volume)
            "volume",  # Generic volume - this is the current market volume (traded volume)
            "volume_24h",  # 24-hour volume (traded volume)
            # NOTE: Do NOT use liquidity_dollars or liquidity - these are orderbook depth, not traded volume
            # "liquidity_dollars" is the total money available to trade, not what has been traded
            # Kalshi website shows "volume" which is the amount that has been traded
            # Avoid these - they might be cumulative or total:
            # "total_volume", "total_volume_dollars", "total_pot", "pot_dollars",
            # "open_interest", "total_liquidity", "market_volume"
            # Don't use yes_volume/no_volume - these are per-side volumes, not total market volume
        ]
        
        for field in volume_fields:
            volume_val = market_to_check.get(field)
            if volume_val is not None and volume_val != 0:
                try:
                    volume_float = float(volume_val)
                    
                    # If field name contains "dollars", it's already in dollars
                    if "dollars" in field.lower():
                        return volume_float
                    
                    # Kalshi API volumes: need to determine if in cents or dollars
                    # Based on Kalshi API documentation and behavior:
                    # - "volume" field is typically in cents for the API
                    # - "volume_dollars" field is explicitly in dollars
                    # 
                    # Heuristic: 
                    # - If >= 1,000,000, definitely in cents (even $10k = 1M cents)
                    # - If 10,000-1,000,000, could be either - but for active markets,
                    #   volumes are typically $1k-$50k, so:
                    #   - If we see 28,559, it's probably already in dollars
                    #   - If we see 2,855,900, it's definitely in cents
                    # - If < 10,000, assume already in dollars
                    if volume_float >= 1000000:
                        # Very large number - definitely in cents, convert to dollars
                        return volume_float / 100.0
                    elif volume_float >= 10000:
                        # Medium-large number - could be either
                        # For tennis markets, if it's in the 10k-1M range:
                        # - If it's a round number like 28,559 (close to expected $28.5k), it's probably dollars
                        # - If it's much larger like 2,855,900, it's in cents
                        # Conservative: if > 100k, assume cents; otherwise assume dollars
                        if volume_float > 100000:
                            return volume_float / 100.0
                        else:
                            # Between 10k-100k, assume already in dollars (matches Kalshi website display)
                            return volume_float
                    else:
                        # Small number - assume already in dollars
                        return volume_float
                except (ValueError, TypeError):
                    continue
        
        # If still not found, try to calculate from orderbook
        client = getattr(self, 'kalshi', None) or getattr(self, 'client', None) or getattr(self, 'kalshi_client', None)
        if ticker and client:
            try:
                orderbook = client.get_orderbook(ticker)
                # Some orderbooks have volume information
                orderbook_volume = orderbook.get("volume") or orderbook.get("total_volume")
                if orderbook_volume:
                    volume_float = float(orderbook_volume)
                    if volume_float > 10000:
                        return volume_float / 100.0
                    elif volume_float > 1000:
                        return volume_float / 100.0
                    else:
                        return volume_float
            except Exception:
                pass
        
        return None
    
    def parse_player_names(self, market: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """
        Extract player names from Kalshi market title/subtitle.
        
        Kalshi market formats:
        - "Will [Player1] win?" with subtitle "vs [Player2]"
        - "[Player1] vs [Player2]"
        - "[Player1] to win against [Player2]"
        - "United Cup [Player1] vs [Player2]: Group X"
        - "[Tournament] [Player1] vs [Player2]"
        
        Args:
            market: Market dictionary from Kalshi API
            
        Returns:
            Tuple of (player1_name, player2_name) or None if parsing fails
        """
        title = market.get("title", "")
        subtitle = market.get("subtitle", "")
        full_text = f"{title} {subtitle}"
        full_text_lower = full_text.lower()
        
        # Pattern 1: "Will [Player1] win the [Player1] vs [Player2] : [Info] match?"
        # Example: "Will Stefanos Tsitsipas win the Harris vs Tsitsipas : Group E match?"
        # Example: "Will Michael Mmoh win the Garin vs Mmoh : Qualification Round 1 match?"
        # Updated to handle hyphenated and multi-word names
        pattern1a = r"will\s+([A-Za-z\s]+?)\s+win\s+the\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+vs\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)"
        match1a = re.search(pattern1a, full_text, re.IGNORECASE)
        if match1a:
            asked_player = match1a.group(1).strip()  # The player Kalshi is asking about
            # Extract players from "Player1 vs Player2" part
            p1_from_vs = match1a.group(2).strip()
            p2_from_vs = match1a.group(3).strip()
            # Remove any trailing info like ": Group E match" or ": Qualification Round 1 match"
            p2_from_vs = re.sub(r"\s*:\s*.*$", "", p2_from_vs)
            
            # Determine which player Kalshi is asking about and order them consistently
            # Match by last name (more reliable)
            asked_lower = asked_player.lower()
            p1_lower = p1_from_vs.lower()
            p2_lower = p2_from_vs.lower()
            
            asked_last = asked_lower.split()[-1] if asked_lower.split() else ""
            p1_last = p1_lower.split()[-1] if p1_lower.split() else ""
            p2_last = p2_lower.split()[-1] if p2_lower.split() else ""
            
            # If Kalshi is asking about the second player in "vs", swap them so the asked player is player1
            # This ensures consistent ordering: the player Kalshi asks about becomes player1
            if asked_last == p2_last or (p2_last and asked_last == p2_last):
                # Kalshi is asking about player2, so swap to make them player1
                return (p2_from_vs, p1_from_vs)
            else:
                # Kalshi is asking about player1, keep order as-is
                return (p1_from_vs, p2_from_vs)
        
        # Pattern 1b: "Will [Player] win?" with "vs [Opponent]" in subtitle
        # This is the key pattern - we need to identify which player Kalshi is asking about
        pattern1b = r"will\s+([^?]+)\s+win"
        match1b = re.search(pattern1b, full_text, re.IGNORECASE)
        if match1b:
            kalshi_asked_player = match1b.group(1).strip()  # The player Kalshi is asking about
            # Look for "vs" pattern to find both players - handle hyphenated and multi-word names
            vs_match = re.search(r"([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+vs\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)", full_text, re.IGNORECASE)
            if vs_match:
                p1_from_vs = vs_match.group(1).strip()
                p2_from_vs = vs_match.group(2).strip()
                # Remove any trailing info
                p2_from_vs = re.sub(r"\s*:\s*.*$", "", p2_from_vs)
                
                # Determine which player Kalshi is asking about
                # Match the asked player to one of the players in the "vs" part
                kalshi_asked_lower = kalshi_asked_player.lower()
                p1_lower = p1_from_vs.lower()
                p2_lower = p2_from_vs.lower()
                
                # Check if asked player matches player1 or player2 (by last name or full name)
                asked_matches_p1 = (kalshi_asked_lower == p1_lower or 
                                   kalshi_asked_lower.split()[-1] == p1_lower.split()[-1] if kalshi_asked_lower.split() and p1_lower.split() else False)
                asked_matches_p2 = (kalshi_asked_lower == p2_lower or 
                                   kalshi_asked_lower.split()[-1] == p2_lower.split()[-1] if kalshi_asked_lower.split() and p2_lower.split() else False)
                
                # Return players in consistent order (p1, p2) and note which one Kalshi is asking about
                # Store this info in the market dict for later use
                if asked_matches_p1:
                    # Kalshi is asking about player1, return (p1, p2) - prediction will be for p1
                    return (p1_from_vs, p2_from_vs)
                elif asked_matches_p2:
                    # Kalshi is asking about player2, return (p2, p1) - prediction will be for p2
                    # But we need to keep track that we swapped them
                    return (p2_from_vs, p1_from_vs)
                else:
                    # Can't determine which player, default to (p1, p2)
                    return (p1_from_vs, p2_from_vs)
        
        # Pattern 2: "[Tournament] [Player1] vs [Player2]: [Group/Info]"
        # Example: "United Cup Zverev vs Griekspoor: Group F"
        # Updated to handle hyphenated and multi-word names
        pattern2 = r"([A-Za-z\s]+?)\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+vs\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)(?:\s*:\s*[^:]+)?$"
        match2 = re.search(pattern2, title, re.IGNORECASE)
        if match2:
            # Check if first group is a tournament name (common tennis tournaments)
            tournament = match2.group(1).strip()
            player1 = match2.group(2).strip()
            player2 = match2.group(3).strip()
            
            # If tournament name is too long or looks like a player name, adjust
            if len(tournament.split()) <= 3 and any(t in tournament.lower() for t in 
                ["cup", "open", "atp", "championship", "masters", "grand slam"]):
                # First group is tournament, next two are players
                return (player1, player2)
            else:
                # First group might be player1, second is player2
                # Try to extract from "Player1 vs Player2" pattern - handle hyphenated and multi-word names
                simple_vs = re.search(r"([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+vs\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)", title, re.IGNORECASE)
                if simple_vs:
                    return (simple_vs.group(1).strip(), simple_vs.group(2).strip())
        
        # Pattern 3: Simple "[Player1] vs [Player2]" or "[Player1] v [Player2]"
        # This should catch formats like "United Cup Zverev vs Griekspoor: Group F"
        # or just "Zverev vs Griekspoor" or "Auger-Aliassime vs Zhang"
        # Find all "vs" patterns and use the one that looks most like player names
        # Updated to handle hyphenated names and multi-word names better
        pattern3 = r"([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+v\.?s?\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)"
        matches3 = list(re.finditer(pattern3, title, re.IGNORECASE))
        if matches3:
            # If multiple matches, prefer the one that doesn't start with tournament keywords
            best_match = None
            for match in matches3:
                p1 = match.group(1).strip()
                p2 = match.group(2).strip()
                # Check if p1 looks like a tournament name
                is_tournament = (len(p1.split()) > 1 and 
                               any(term in p1.lower() for term in ["cup", "open", "championship", "atp", "tour"]))
                if not is_tournament:
                    best_match = match
                    break
            
            # If no good match found, use the last one (most likely to be players)
            if not best_match:
                best_match = matches3[-1]
            
            player1 = best_match.group(1).strip()
            player2 = best_match.group(2).strip()
            # Remove common suffixes and tournament info
            player2 = re.sub(r"\s*:\s*.*$", "", player2)  # Remove ": Group X"
            player2 = re.sub(r"\s+to\s+win.*$", "", player2, flags=re.IGNORECASE)
            
            # If player1 still looks like tournament, try to extract from after it
            if len(player1.split()) > 1 and any(term in player1.lower() for term in ["cup", "open", "championship"]):
                # Try to find players after tournament name - handle hyphenated and multi-word names
                after_tournament = title[title.lower().find(player1.lower()) + len(player1):].strip()
                simple_vs = re.search(r"([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+v\.?s?\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)", after_tournament, re.IGNORECASE)
                if simple_vs:
                    player1 = simple_vs.group(1).strip()
                    player2 = simple_vs.group(2).strip()
                    player2 = re.sub(r"\s*:\s*.*$", "", player2)
            
            # Clean up player names - remove any remaining tournament info
            player1 = re.sub(r"^(united\s+cup|atp|davis\s+cup)\s+", "", player1, flags=re.IGNORECASE).strip()
            player2 = re.sub(r"^(united\s+cup|atp|davis\s+cup)\s+", "", player2, flags=re.IGNORECASE).strip()
            
            return (player1, player2)
        
        # Pattern 4: "[Player1] to win against [Player2]"
        pattern4 = r"([A-Za-z\-\']+)\s+to\s+win\s+against\s+([A-Za-z\-\']+)"
        match4 = re.search(pattern4, full_text_lower, re.IGNORECASE)
        if match4:
            player1 = match4.group(1).strip()
            player2 = match4.group(2).strip()
            return (player1, player2)
        
        return None
    
    def match_player_name(self, kalshi_name: str, 
                         player_db: PlayerStatsDB,
                         debug: bool = False) -> Optional[str]:
        """
        Match Kalshi player name to our database name.
        
        Uses fuzzy matching to handle name variations:
        - "Novak Djokovic" vs "N. Djokovic"
        - "Rafael Nadal" vs "Rafa Nadal"
        - "Zverev" (last name only) vs "Alexander Zverev" (full name)
        - Case differences
        
        Args:
            kalshi_name: Player name from Kalshi
            player_db: PlayerStatsDB instance
            debug: Print debug information
            
        Returns:
            Matched player name from database, or None if no match found
        """
        kalshi_name_clean = kalshi_name.strip().lower()
        
        if debug:
            print(f"    Matching '{kalshi_name}' (cleaned: '{kalshi_name_clean}')")
        
        # Direct match
        if kalshi_name_clean in player_db.name_to_id:
            matched = player_db.id_to_name[player_db.name_to_id[kalshi_name_clean]]
            if debug:
                print(f"      → Direct match: '{matched}'")
            return matched
        
        # Extract last name from Kalshi name
        kalshi_parts = kalshi_name_clean.split()
        kalshi_last = kalshi_parts[-1] if kalshi_parts else ""
        
        # Try last name match first (most common case: "Zverev" -> "Alexander Zverev")
        # But be more careful - only match if last name is substantial (not just initials)
        if kalshi_last and len(kalshi_last) > 2:  # Last name must be at least 3 characters
            best_last_match = None
            best_last_score = 0.0
            
            for db_name in player_db.name_to_id.keys():
                db_parts = db_name.split()
                db_last = db_parts[-1] if db_parts else ""
                
                # Exact last name match (highest priority)
                if kalshi_last == db_last:
                    matched = player_db.id_to_name[player_db.name_to_id[db_name]]
                    if debug:
                        print(f"      → Exact last name match: '{matched}' (last name: '{kalshi_last}')")
                    return matched
                
                # Fuzzy last name match (if exact doesn't work)
                if db_last:
                    last_score = SequenceMatcher(None, kalshi_last, db_last).ratio()
                    if last_score > best_last_score:
                        best_last_score = last_score
                        best_last_match = db_name
            
            # Only use fuzzy last name match if similarity is very high (>= 0.90)
            if best_last_score >= 0.90 and best_last_match:
                matched = player_db.id_to_name[player_db.name_to_id[best_last_match]]
                if debug:
                    print(f"      → Fuzzy last name match: '{matched}' (score: {best_last_score:.2f})")
                return matched
        
        # Fuzzy match - find best match
        best_match = None
        best_score = 0.0
        
        for db_name in player_db.name_to_id.keys():
            # Try full name match
            score = SequenceMatcher(None, kalshi_name_clean, db_name).ratio()
            
            # Try last name only (common format: "Djokovic" vs "Novak Djokovic")
            db_parts = db_name.split()
            db_last = db_parts[-1] if db_parts else ""
            if kalshi_last and db_last:
                last_score = SequenceMatcher(None, kalshi_last, db_last).ratio()
                score = max(score, last_score * 0.95)  # Weight last name heavily
            
            # Also check if Kalshi name is contained in DB name or vice versa
            if kalshi_name_clean in db_name or db_name in kalshi_name_clean:
                score = max(score, 0.85)
            
            if score > best_score:
                best_score = score
                best_match = db_name
        
        # Lower threshold to 60% for better matching
        if best_score >= 0.60:
            matched = player_db.id_to_name[player_db.name_to_id[best_match]]
            if debug:
                print(f"      → Fuzzy match: '{matched}' (score: {best_score:.2f})")
            return matched
        
        if debug:
            print(f"      → No match found (best score: {best_score:.2f}, best match: '{best_match}')")
        return None
    
    def get_market_odds(self, market: Dict[str, Any], debug: bool = False) -> Optional[Dict[str, float]]:
        """
        Extract odds from Kalshi market.
        
        Kalshi uses price in cents (0-100) where:
        - Price 50 = 50% probability = 2.00 decimal odds
        - Price 33 = 33% probability = 3.03 decimal odds
        
        Args:
            market: Market dictionary from Kalshi API
            debug: Print debug information about market fields
            
        Returns:
            Dictionary with 'yes_price', 'no_price', 'yes_prob', 'no_prob'
            or None if market is closed/invalid
        """
        if debug:
            print(f"    Market fields: {list(market.keys())}")
            # Print all price-related fields
            price_fields = [k for k in market.keys() if any(term in k.lower() for term in ['price', 'bid', 'ask', 'prob', 'odds'])]
            if price_fields:
                print(f"    Price-related fields: {price_fields}")
                for field in price_fields:
                    print(f"      {field}: {market.get(field)}")
            else:
                print(f"    No price-related fields found. All fields: {list(market.keys())}")
        
        # Try different possible field names for bid/ask (check both snake_case and camelCase)
        yes_bid = (market.get("yes_bid") or market.get("yes_bid_price") or market.get("yesBid") or 
                  market.get("yes_bid_price_cents") or market.get("yesBidPrice"))
        yes_ask = (market.get("yes_ask") or market.get("yes_ask_price") or market.get("yesAsk") or
                  market.get("yes_ask_price_cents") or market.get("yesAskPrice"))
        no_bid = (market.get("no_bid") or market.get("no_bid_price") or market.get("noBid") or
                 market.get("no_bid_price_cents") or market.get("noBidPrice"))
        no_ask = (market.get("no_ask") or market.get("no_ask_price") or market.get("noAsk") or
                 market.get("no_ask_price_cents") or market.get("noAskPrice"))
        
        # Try different possible field names for last price
        last_price = (market.get("last_price") or market.get("lastPrice") or 
                     market.get("yes_price") or market.get("yesPrice") or
                     market.get("price") or market.get("current_price") or
                     market.get("last_price_cents") or market.get("lastPriceCents") or
                     market.get("last_trade_price") or market.get("lastTradePrice") or
                     market.get("close_price") or market.get("closePrice"))
        
        # Also try probability fields directly - these might already be probabilities (0-1)
        # OR they might be in percentage format (0-100)
        yes_prob_raw = market.get("yes_prob") or market.get("yesProb") or market.get("yes_probability") or market.get("probability")
        if yes_prob_raw is not None and isinstance(yes_prob_raw, (int, float)):
            if yes_prob_raw > 1.0:
                # It's in percentage/cents format, convert to probability
                last_price = last_price or (yes_prob_raw / 100.0)
            else:
                # It's already a probability, convert to cents for consistency
                last_price = last_price or (yes_prob_raw * 100)
        
        # Also check for percentage fields
        yes_pct = market.get("yes_percent") or market.get("yesPercent") or market.get("yes_percentage")
        if yes_pct is not None and isinstance(yes_pct, (int, float)) and 0 < yes_pct < 100:
            # Percentage is 0-100, already in cents format (65 = 65%)
            last_price = last_price or yes_pct
        
        # Try to find ANY numeric field between 0-100 that might be a price
        # EXCLUDE 100 and values very close to 0 or 100 (likely max/min values, not actual prices)
        if last_price is None:
            all_numeric_0_100 = {k: v for k, v in market.items() 
                                if isinstance(v, (int, float)) and 0 < v < 100}  # Exclude 0 and 100
            if all_numeric_0_100:
                if debug:
                    print(f"    Found numeric fields (0-100) that might be prices: {all_numeric_0_100}")
                # Try to find the most likely price field
                # Prefer fields with "price", "prob", "bid", "ask" in name
                price_candidates = []
                for k, v in all_numeric_0_100.items():
                    # Skip fields that are clearly not prices
                    if any(skip in k.lower() for skip in ["max", "min", "limit", "count", "total", "size", "volume"]):
                        continue
                    
                    score = 0
                    if "price" in k.lower():
                        score += 10
                    if "prob" in k.lower():
                        score += 8
                    if "bid" in k.lower() or "ask" in k.lower():
                        score += 5
                    if "yes" in k.lower():
                        score += 3
                    if 20 <= v <= 80:  # Reasonable probability range (not 1 or 99)
                        score += 5
                    # Penalize values that are too close to 0 or 100
                    if v < 2 or v > 98:
                        score -= 10
                    price_candidates.append((score, k, v))
                
                if price_candidates:
                    price_candidates.sort(reverse=True)
                    best_candidate = price_candidates[0]
                    # Only use if score is positive (not penalized too much)
                    if best_candidate[0] > 0:
                        if debug:
                            print(f"    🎯 Best price candidate: {best_candidate[1]} = {best_candidate[2]} (score: {best_candidate[0]})")
                        last_price = best_candidate[2]
                    else:
                        if debug:
                            print(f"    ⚠️  Best candidate has negative score, skipping: {best_candidate[1]} = {best_candidate[2]}")
                else:
                    # Fallback: try any value in reasonable range (exclude edge cases)
                    potential_prices = [v for v in all_numeric_0_100.values() if 2 <= v <= 98]
                    if potential_prices:
                        last_price = potential_prices[0]
                        if debug:
                            print(f"    ⚠️  Using potential price from numeric field: {last_price}")
        
        # Initialize yes_price
        yes_price = None
        
        # Use mid price if available, otherwise use last price
        if yes_bid is not None and yes_ask is not None:
            yes_price = (yes_bid + yes_ask) / 2
            if debug:
                print(f"    Using mid price from bid/ask: ({yes_bid} + {yes_ask}) / 2 = {yes_price}")
        elif last_price is not None:
            yes_price = last_price
            if debug:
                print(f"    Using last price: {yes_price}")
        
        # ALWAYS try orderbook - it's the most reliable source for current prices
        # Even if we found a price in market data, orderbook has real-time bid/ask
        ticker = market.get("ticker")
        if ticker:
            try:
                if debug:
                    if yes_price is None:
                        print(f"    No price in market data, fetching orderbook for {ticker}")
                    else:
                        print(f"    Also fetching orderbook for current prices: {ticker} (found {yes_price} in market data)")
                
                orderbook = self.kalshi.get_orderbook(ticker)
                
                if debug:
                    print(f"    Orderbook full response:")
                    print(f"      Type: {type(orderbook)}")
                    if isinstance(orderbook, dict):
                        print(f"      Top-level keys: {list(orderbook.keys())}")
                        # Print the full structure (limited to avoid spam)
                        import json
                        print(f"      Full structure (first 500 chars): {str(orderbook)[:500]}")
                
                # Orderbook is more reliable - use it if available, even if we found a price
                orderbook_price = None
                
                # Also check if orderbook response has market data nested
                if isinstance(orderbook, dict) and "market" in orderbook:
                    market_data = orderbook["market"]
                    if debug:
                        print(f"    Found nested market data in orderbook")
                        print(f"    Market data keys: {list(market_data.keys())}")
                        # Show all price-related fields
                        price_fields = {k: v for k, v in market_data.items() if any(term in k.lower() for term in ['price', 'bid', 'ask', 'prob'])}
                        if price_fields:
                            print(f"    Price fields in market data: {price_fields}")
                    # Try to get prices from nested market data
                    ob_yes_bid = (market_data.get("yes_bid") or market_data.get("yesBid") or 
                                 market_data.get("yes_bid_price") or market_data.get("yesBidPrice") or
                                 market_data.get("yes_bid_cents"))
                    ob_yes_ask = (market_data.get("yes_ask") or market_data.get("yesAsk") or 
                                 market_data.get("yes_ask_price") or market_data.get("yesAskPrice") or
                                 market_data.get("yes_ask_cents"))
                    if ob_yes_bid is not None and ob_yes_ask is not None:
                        orderbook_price = (ob_yes_bid + ob_yes_ask) / 2
                        if debug:
                            print(f"    ✅ Found price in nested market data: {orderbook_price} (from bid={ob_yes_bid}, ask={ob_yes_ask})")
                    elif ob_yes_bid is not None:
                        orderbook_price = ob_yes_bid
                        if debug:
                            print(f"    ✅ Found price from bid only: {orderbook_price}")
                    elif ob_yes_ask is not None:
                        orderbook_price = ob_yes_ask
                        if debug:
                            print(f"    ✅ Found price from ask only: {orderbook_price}")
                    
                    # Use orderbook price if found (it's more reliable)
                    if orderbook_price is not None:
                        yes_price = orderbook_price
                
                # If still no price, try extracting from orderbook structure
                if orderbook_price is None:
                    if debug:
                        print(f"    Trying to extract price from orderbook structure...")
                        if isinstance(orderbook, dict):
                            print(f"    Orderbook keys: {list(orderbook.keys())}")
                            # Print ALL keys and their types to see what we have
                            for key, value in orderbook.items():
                                if isinstance(value, (dict, list)):
                                    size = len(value) if isinstance(value, list) else len(value) if isinstance(value, dict) else "?"
                                    print(f"      {key}: {type(value).__name__} with {size} items")
                                    # If it's a dict, show its keys
                                    if isinstance(value, dict) and len(value) < 10:
                                        print(f"        Sub-keys: {list(value.keys())}")
                                else:
                                    print(f"      {key}: {type(value).__name__} = {value}")
                            
                            # Also check for any field that might contain price info
                            all_numeric = {k: v for k, v in orderbook.items() 
                                         if isinstance(v, (int, float)) and 0 <= v <= 100}
                            if all_numeric:
                                print(f"    Numeric fields (0-100) that might be prices: {all_numeric}")
                    
                    # Try to extract price from orderbook
                    # Common orderbook structures:
                    # - {"yes": {"bid": X, "ask": Y}, "no": {"bid": X, "ask": Y}}
                    # - {"bids": [...], "asks": [...]}
                    # - {"yes_bid": X, "yes_ask": Y, ...}
                    
                    if isinstance(orderbook, dict):
                        # Try nested structure: {"yes": {"bid": X, "ask": Y}}
                        yes_data = orderbook.get("yes", {})
                        if isinstance(yes_data, dict):
                            ob_yes_bid = yes_data.get("bid") or yes_data.get("price") or yes_data.get("bid_price") or yes_data.get("bidPrice")
                            ob_yes_ask = yes_data.get("ask") or yes_data.get("price") or yes_data.get("ask_price") or yes_data.get("askPrice")
                            
                            # Also check for cents fields
                            if ob_yes_bid is None:
                                ob_yes_bid = yes_data.get("bid_cents") or yes_data.get("bidCents")
                            if ob_yes_ask is None:
                                ob_yes_ask = yes_data.get("ask_cents") or yes_data.get("askCents")
                            
                            if ob_yes_bid is not None and ob_yes_ask is not None:
                                orderbook_price = (ob_yes_bid + ob_yes_ask) / 2
                                if debug:
                                    print(f"    ✅ Found price in orderbook yes: {orderbook_price} (from bid={ob_yes_bid}, ask={ob_yes_ask})")
                            elif ob_yes_bid is not None:
                                orderbook_price = ob_yes_bid
                                if debug:
                                    print(f"    ✅ Found price from bid only: {ob_yes_bid}")
                            elif ob_yes_ask is not None:
                                orderbook_price = ob_yes_ask
                                if debug:
                                    print(f"    ✅ Found price from ask only: {ob_yes_ask}")
                            
                            # If still no price, check for probability fields
                            if orderbook_price is None:
                                yes_prob_ob = yes_data.get("prob") or yes_data.get("probability") or yes_data.get("pct") or yes_data.get("percent")
                                if yes_prob_ob is not None:
                                    if yes_prob_ob > 1.0:
                                        orderbook_price = yes_prob_ob  # Already in cents
                                    else:
                                        orderbook_price = yes_prob_ob * 100  # Convert to cents
                                    if debug:
                                        print(f"    ✅ Found price from probability field: {orderbook_price}")
                        
                        # Use orderbook price if found
                        if orderbook_price is not None:
                            yes_price = orderbook_price
                        
                        # Try flat structure: {"yes_bid": X, "yes_ask": Y}
                        if yes_price is None:
                            ob_yes_bid = orderbook.get("yes_bid") or orderbook.get("yesBid")
                            ob_yes_ask = orderbook.get("yes_ask") or orderbook.get("yesAsk")
                            if ob_yes_bid is not None and ob_yes_ask is not None:
                                orderbook_price = (ob_yes_bid + ob_yes_ask) / 2
                                if debug:
                                    print(f"    ✅ Found price in flat orderbook: {orderbook_price} (from bid={ob_yes_bid}, ask={ob_yes_ask})")
                            elif ob_yes_bid is not None:
                                orderbook_price = ob_yes_bid
                                if debug:
                                    print(f"    ✅ Found price from bid only: {orderbook_price}")
                            elif ob_yes_ask is not None:
                                orderbook_price = ob_yes_ask
                                if debug:
                                    print(f"    ✅ Found price from ask only: {orderbook_price}")
                            
                            # Use orderbook price if found
                            if orderbook_price is not None:
                                yes_price = orderbook_price
                        
                        # Try orderbook structure: {"yes": [{"price": X, "size": Y}, ...]}
                        if yes_price is None:
                            yes_orders = orderbook.get("yes", [])
                            no_orders = orderbook.get("no", [])
                            if isinstance(yes_orders, list) and len(yes_orders) > 0:
                                # Get best bid (highest price) and best ask (lowest price)
                                bids = [o for o in yes_orders if o.get("side") == "bid" or "bid" in str(o).lower()]
                                asks = [o for o in yes_orders if o.get("side") == "ask" or "ask" in str(o).lower()]
                                if bids and asks:
                                    best_bid = max(bids, key=lambda x: x.get("price", 0)).get("price")
                                    best_ask = min(asks, key=lambda x: x.get("price", 100)).get("price")
                                if best_bid is not None and best_ask is not None:
                                    orderbook_price = (best_bid + best_ask) / 2
                                    if debug:
                                        print(f"    ✅ Found price from orderbook orders: {orderbook_price} (from bid={best_bid}, ask={best_ask})")
                                    yes_price = orderbook_price
                        
                        # Try bids/asks arrays (take best bid and best ask)
                        if yes_price is None:
                            bids = orderbook.get("bids", [])
                            asks = orderbook.get("asks", [])
                            if bids and asks:
                                # Assuming format: [{"price": X, "count": Y}, ...] or [X, Y, ...]
                                best_bid = bids[0].get("price") if isinstance(bids[0], dict) else bids[0]
                                best_ask = asks[0].get("price") if isinstance(asks[0], dict) else asks[0]
                                if best_bid is not None and best_ask is not None:
                                    orderbook_price = (best_bid + best_ask) / 2
                                    if debug:
                                        print(f"    ✅ Found price from bids/asks arrays: {orderbook_price} (from bid={best_bid}, ask={best_ask})")
                                    yes_price = orderbook_price
            except Exception as e:
                if debug:
                    print(f"    Could not fetch orderbook: {e}")
                yes_price = None
        
        # If we still don't have a price, try one more thing: check if market has a status
        # that indicates it's active but just doesn't have prices yet
        if yes_price is None:
            market_status = market.get("status", "").lower()
            if debug:
                print(f"    ❌ No price found after all attempts")
                print(f"    Market status: {market_status}")
                print(f"    Market ticker: {ticker}")
                # Show all numeric fields that might be prices
                numeric_fields = {k: v for k, v in market.items() if isinstance(v, (int, float)) and 0 <= v <= 100}
                if numeric_fields:
                    print(f"    Numeric fields that might be prices: {numeric_fields}")
                # Show ALL fields to help debug
                print(f"    All market fields: {list(market.keys())}")
                print(f"    Market object sample: {str(market)[:300]}")
            
            # If market is open/active but no price, it might just be very new or have no liquidity
            # Return None but with better error message
            if market_status in ["open", "active"]:
                if debug:
                    print(f"    ⚠️  Market is {market_status} but no prices found - may have no active bids/asks")
            return None
        
        if no_bid is not None and no_ask is not None:
            no_price = (no_bid + no_ask) / 2
        else:
            no_price = 100 - yes_price if yes_price else None
        
        # Convert price to probability
        # Kalshi prices can be in two formats:
        # 1. Cents (0-100): 65 = 65% = 0.65 probability
        # 2. Already probability (0-1): 0.65 = 65% = 0.65 probability
        
        # Validate price is reasonable before converting
        if yes_price < 0.01 or yes_price > 100:
            if debug:
                print(f"    ❌ ERROR: Invalid price value: {yes_price}")
                print(f"    Expected price in range 0.01-100 (cents) or 0.0001-1.0 (probability)")
            return None
        
        if yes_price > 1.0:
            # Price is in cents, convert to probability
            yes_prob = yes_price / 100.0
            if debug and (yes_price < 2 or yes_price > 98):
                print(f"    ⚠️  WARNING: Price seems extreme ({yes_price} cents = {yes_prob:.1%})")
                print(f"    If Kalshi shows 65% and 35%, we should see ~65 cents, not {yes_price} cents")
                print(f"    This might indicate we're reading the wrong field!")
        else:
            # Price is already a probability
            yes_prob = yes_price
            if debug and (yes_prob < 0.02 or yes_prob > 0.98):
                print(f"    ⚠️  WARNING: Probability seems extreme ({yes_prob:.1%})")
                print(f"    If Kalshi shows 65% and 35%, we should see ~0.65, not {yes_prob}")
                print(f"    This might indicate we're reading the wrong field!")
        
        no_prob = 1.0 - yes_prob
        
        # Convert to decimal odds
        yes_odds = 1.0 / yes_prob if yes_prob > 0 else None
        no_odds = 1.0 / no_prob if no_prob > 0 else None
        
        if debug:
            print(f"    Final odds: yes_price={yes_price}, yes_prob={yes_prob:.1%}, yes_odds={yes_odds}")
            print(f"    (Price format: {'cents' if yes_price > 1.0 else 'probability'})")
            if yes_prob < 0.02 or yes_prob > 0.98:
                print(f"    ⚠️  WARNING: Probability seems extreme ({yes_prob:.1%}) - might be reading wrong field")
        
        # Validate the probability makes sense
        if yes_prob < 0.01 or yes_prob > 0.99:
            if debug:
                print(f"    ❌ Invalid probability range: {yes_prob:.1%} - likely reading wrong field")
            # Don't return None, but flag it in the response
        
        return {
            "yes_price": yes_price,
            "no_price": no_price or (100 - yes_price),
            "yes_prob": yes_prob,
            "no_prob": no_prob,
            "yes_odds": yes_odds,
            "no_odds": no_odds
        }
    
    def _infer_match_parameters(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """
        Infer match parameters from market title/subtitle.
        Returns dict with surface, best_of_5, round_code, tourney_level_code.
        """
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        full_text = f"{title} {subtitle}".lower()
        
        # Default values
        params = {
            "surface": "Hard",
            "best_of_5": False,
            "round_code": 7,  # Final
            "tourney_level_code": 2  # ATP Tour
        }
        
        # Infer surface
        if any(word in full_text for word in ["clay", "roland garros", "french open"]):
            params["surface"] = "Clay"
        elif any(word in full_text for word in ["grass", "wimbledon"]):
            params["surface"] = "Grass"
        elif any(word in full_text for word in ["hard", "us open", "australian open"]):
            params["surface"] = "Hard"
        
        # Infer round - check specific patterns first
        # Priority: Check for "round of 128" or "r128" first (most specific)
        if "round of 128" in full_text or "r128" in full_text:
            params["round_code"] = 1
        elif "round of 64" in full_text or "r64" in full_text:
            params["round_code"] = 2
        elif "round of 32" in full_text or "r32" in full_text:
            params["round_code"] = 3
        elif "round of 16" in full_text or "r16" in full_text or "fourth round" in full_text:
            params["round_code"] = 4
        elif "quarterfinal" in full_text or "qf" in full_text:
            params["round_code"] = 5
        elif "semifinal" in full_text or "sf" in full_text:
            params["round_code"] = 6
        elif "final" in full_text:
            params["round_code"] = 7
        # Check qualification rounds (can be round 1, 2, or 3)
        # IMPORTANT: Check for "qualification round 1" pattern specifically
        elif "qualification" in full_text or "qualifier" in full_text or "qualifying" in full_text:
            # Look for "round 1", "round 2", "round 3" in qualification context
            # Use word boundaries to avoid matching "round 10" as "round 1"
            if re.search(r'\bround\s+1\b', full_text, re.IGNORECASE):
                params["round_code"] = 1
            elif re.search(r'\bround\s+2\b', full_text, re.IGNORECASE):
                params["round_code"] = 2
            elif re.search(r'\bround\s+3\b', full_text, re.IGNORECASE):
                params["round_code"] = 3
            else:
                # Default qualification to round 1 if not specified
                params["round_code"] = 1
        
        # Infer tournament level
        if any(word in full_text for word in ["grand slam", "wimbledon", "us open", "french open", "australian open", "roland garros"]):
            params["tourney_level_code"] = 4  # Grand Slam
            params["best_of_5"] = True
        elif "masters" in full_text or "1000" in full_text:
            params["tourney_level_code"] = 3  # Masters
        elif "challenger" in full_text:
            params["tourney_level_code"] = 1  # Challenger
        elif "futures" in full_text:
            params["tourney_level_code"] = 1  # Futures
        elif "atp" in full_text:
            # If "atp" is mentioned (e.g., "ATP Match"), assume ATP Tour (level 2)
            params["tourney_level_code"] = 2  # ATP Tour
        
        return params
    
    def analyze_market(self, market: Dict[str, Any], 
                      surface: Optional[str] = None,
                      best_of_5: Optional[bool] = None,
                      round_code: Optional[int] = None,
                      tourney_level_code: Optional[int] = None,
                      min_value: float = 0.05,
                      min_ev: float = 0.10,
                      debug: bool = False) -> Optional[Dict[str, Any]]:
        """
        Analyze a single Kalshi market and generate prediction.
        
        Args:
            market: Market dictionary from Kalshi API
            surface: Match surface (Hard, Clay, Grass)
            best_of_5: Whether best of 5 match
            round_code: Tournament round (1-7)
            tourney_level_code: Tournament level (1-4)
            
        Returns:
            Analysis dictionary with predictions and value calculations,
            or None if market cannot be analyzed
        """
        if not self.player_db or not self.predictor:
            raise ValueError("PlayerStatsDB and MatchPredictor must be initialized")
        
        # Parse player names
        players = self.parse_player_names(market)
        if not players:
            return {
                "market": market,
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "error": "Could not parse player names from market title",
                "tradable": False,
                "reason": "Market title format not recognized. Title: " + market.get("title", "N/A")
            }
        
        kalshi_p1, kalshi_p2 = players
        
        # Infer match parameters from market if not provided
        inferred_params = self._infer_match_parameters(market)
        if surface is None:
            surface = inferred_params["surface"]
        if best_of_5 is None:
            best_of_5 = inferred_params["best_of_5"]
        if round_code is None:
            round_code = inferred_params["round_code"]
        if tourney_level_code is None:
            tourney_level_code = inferred_params["tourney_level_code"]
        
        if debug:
            print(f"  Match parameters:")
            print(f"    Surface: {surface} (inferred: {inferred_params['surface']})")
            print(f"    Best of 5: {best_of_5} (inferred: {inferred_params['best_of_5']})")
            print(f"    Round code: {round_code} (inferred: {inferred_params['round_code']})")
            print(f"    Tournament level: {tourney_level_code} (inferred: {inferred_params['tourney_level_code']})")
            print(f"    Market title: '{market.get('title', 'N/A')}'")
            print(f"    Market subtitle: '{market.get('subtitle', 'N/A')}'")
        
        # Determine which player Kalshi is asking about (the "yes" side of the market)
        # Check if market title has "Will [Player] win" pattern
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        full_text = f"{title} {subtitle}".lower()
        
        kalshi_asked_player = None
        will_win_match = re.search(r"will\s+([^?]+)\s+win", full_text, re.IGNORECASE)
        if will_win_match:
            kalshi_asked_player = will_win_match.group(1).strip()
        
        # Determine if Kalshi is asking about player1 or player2
        # Compare by last name (more reliable than full name matching)
        kalshi_asked_lower = kalshi_asked_player.lower() if kalshi_asked_player else ""
        kalshi_p1_lower = kalshi_p1.lower()
        kalshi_p2_lower = kalshi_p2.lower()
        
        asked_is_p1 = False
        asked_is_p2 = False
        
        if kalshi_asked_player:
            # Check if asked player matches p1 or p2 (by last name)
            p1_last = kalshi_p1_lower.split()[-1] if kalshi_p1_lower.split() else ""
            p2_last = kalshi_p2_lower.split()[-1] if kalshi_p2_lower.split() else ""
            asked_last = kalshi_asked_lower.split()[-1] if kalshi_asked_lower.split() else ""
            
            asked_is_p1 = (asked_last == p1_last or kalshi_asked_lower == kalshi_p1_lower or 
                          kalshi_asked_lower in kalshi_p1_lower or kalshi_p1_lower in kalshi_asked_lower)
            asked_is_p2 = (asked_last == p2_last or kalshi_asked_lower == kalshi_p2_lower or 
                          kalshi_asked_lower in kalshi_p2_lower or kalshi_p2_lower in kalshi_asked_lower)
        
        if debug:
            print(f"  Parsed players from market: '{kalshi_p1}' vs '{kalshi_p2}'")
            if kalshi_asked_player:
                print(f"  Kalshi is asking about: '{kalshi_asked_player}'")
                print(f"  Matches p1 ({kalshi_p1}): {asked_is_p1}, Matches p2 ({kalshi_p2}): {asked_is_p2}")
            else:
                print(f"  Could not determine which player Kalshi is asking about from title")
        
        # Match to database - be more strict about matching
        db_p1 = self.match_player_name(kalshi_p1, self.player_db, debug=debug)
        db_p2 = self.match_player_name(kalshi_p2, self.player_db, debug=debug)
        
        # Validate matches - ensure the matched names actually correspond to the Kalshi names
        if db_p1:
            # Verify match makes sense - last name should match
            kalshi_p1_last = kalshi_p1.split()[-1].lower() if kalshi_p1.split() else ""
            db_p1_last = db_p1.split()[-1].lower() if db_p1.split() else ""
            if kalshi_p1_last and db_p1_last and kalshi_p1_last != db_p1_last:
                if debug:
                    print(f"    ⚠️  Match validation failed: '{kalshi_p1}' matched to '{db_p1}' but last names don't match")
                db_p1 = None  # Reject the match
        
        if db_p2:
            # Verify match makes sense - last name should match
            kalshi_p2_last = kalshi_p2.split()[-1].lower() if kalshi_p2.split() else ""
            db_p2_last = db_p2.split()[-1].lower() if db_p2.split() else ""
            if kalshi_p2_last and db_p2_last and kalshi_p2_last != db_p2_last:
                if debug:
                    print(f"    ⚠️  Match validation failed: '{kalshi_p2}' matched to '{db_p2}' but last names don't match")
                db_p2 = None  # Reject the match
        
        if not db_p1 or not db_p2:
            missing = []
            if not db_p1:
                missing.append(f"'{kalshi_p1}'")
            if not db_p2:
                missing.append(f"'{kalshi_p2}'")
            
            return {
                "market": market,
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "kalshi_players": (kalshi_p1, kalshi_p2),
                "matched_players": (db_p1, db_p2),
                "error": "Could not match players to database",
                "tradable": False,
                "reason": f"Could not find players in database: {', '.join(missing)} not found. Try checking if names are spelled correctly or if players are in ATP database."
            }
        
        if debug:
            print(f"  ✅ Matched: '{kalshi_p1}' → '{db_p1}', '{kalshi_p2}' → '{db_p2}'")
        
        # Get player IDs
        p1_id = self.player_db.find_player(db_p1)
        p2_id = self.player_db.find_player(db_p2)
        
        if not p1_id or not p2_id:
            return {
                "market": market,
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "kalshi_players": (kalshi_p1, kalshi_p2),
                "matched_players": (db_p1, db_p2),
                "error": "Could not find player IDs",
                "tradable": False,
                "reason": f"Matched names '{db_p1}' and '{db_p2}' but could not find player IDs in database"
            }
        
        # Get player stats
        p1_stats = self.player_db.get_player_stats(p1_id)
        p2_stats = self.player_db.get_player_stats(p2_id)
        
        if not p1_stats or not p2_stats:
            return {
                "market": market,
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "kalshi_players": (kalshi_p1, kalshi_p2),
                "matched_players": (db_p1, db_p2),
                "error": "Could not retrieve player stats",
                "tradable": False,
                "reason": f"Player IDs found but no statistics available for '{db_p1}' or '{db_p2}'"
            }
        
        # Get H2H (returns winrate difference: p1_wr - p2_wr)
        # IMPORTANT: H2H is calculated as (p1_wins / total) - (p2_wins / total)
        # So if we swap players, the sign flips: h2h(p1, p2) = -h2h(p2, p1)
        h2h_diff = self.player_db.get_h2h(p1_id, p2_id)
        
        if debug:
            print(f"  H2H record: {db_p1} vs {db_p2}")
            print(f"    H2H diff (p1-p2): {h2h_diff:.3f}")
            if h2h_diff > 0:
                print(f"    → {db_p1} has better H2H record")
            elif h2h_diff < 0:
                print(f"    → {db_p2} has better H2H record")
            else:
                print(f"    → No H2H history or tied")
        
        # Build features and predict
        # IMPORTANT: The model predicts probability that player1 (p1) wins
        # So if p1=Garin and p2=Mmoh, it predicts Garin's win probability
        # If p1=Mmoh and p2=Garin, it predicts Mmoh's win probability
        features = self.predictor.build_features(
            p1_stats, p2_stats, surface=surface,
            best_of_5=best_of_5, round_code=round_code,
            tourney_level_code=tourney_level_code,
            h2h_diff=h2h_diff
        )
        
        # Use symmetry enforcement to ensure consistent predictions
        predictions = self.predictor.predict(features, enforce_symmetry=True)
        
        if debug:
            print(f"  Model prediction parameters:")
            print(f"    Player1: {db_p1} (ID: {p1_id})")
            print(f"    Player2: {db_p2} (ID: {p2_id})")
            print(f"    Surface: {surface}")
            print(f"    Best of 5: {best_of_5}")
            print(f"    Round code: {round_code}")
            print(f"    Tournament level: {tourney_level_code}")
            print(f"    H2H diff (p1-p2): {h2h_diff:.3f}")
            print(f"    XGBoost prediction (p1 wins): {predictions.get('xgboost', 'N/A')}")
        
        # Get Kalshi odds
        kalshi_odds = self.get_market_odds(market, debug=debug)
        if not kalshi_odds:
            # Before giving up, check if market has probability fields directly
            # Sometimes Kalshi markets have probabilities but no bid/ask
            yes_prob_direct = (market.get("yes_prob") or market.get("yesProb") or 
                              market.get("yes_probability") or market.get("probability"))
            
            if yes_prob_direct is not None and isinstance(yes_prob_direct, (int, float)):
                # Convert to proper format
                if yes_prob_direct > 1.0:
                    yes_prob = yes_prob_direct / 100.0  # It's in percentage
                else:
                    yes_prob = yes_prob_direct  # Already probability
                
                if debug:
                    print(f"    ⚠️  No bid/ask prices, but found direct probability: {yes_prob:.1%}")
                
                # Create odds dict from direct probability
                kalshi_odds = {
                    "yes_price": yes_prob * 100,  # Convert to cents for consistency
                    "no_price": (1 - yes_prob) * 100,
                    "yes_prob": yes_prob,
                    "no_prob": 1 - yes_prob,
                    "yes_odds": 1.0 / yes_prob if yes_prob > 0 else None,
                    "no_odds": 1.0 / (1 - yes_prob) if (1 - yes_prob) > 0 else None
                }
            else:
                return {
                    "market": market,
                    "ticker": market.get("ticker"),
                    "title": market.get("title"),
                    "kalshi_players": (kalshi_p1, kalshi_p2),
                    "matched_players": (db_p1, db_p2),
                    "predictions": predictions,
                    "error": "Market has no valid odds",
                    "tradable": False,
                    "reason": "Market is closed or has no active bid/ask prices, and no probability fields found"
                }
        
        # Calculate value
        # Use XGBoost model only (preferred model)
        xgboost_prediction = predictions.get("xgboost")
        
        if xgboost_prediction is None:
            return {
                "market": market,
                "ticker": market.get("ticker"),
                "title": market.get("title"),
                "kalshi_players": (kalshi_p1, kalshi_p2),
                "matched_players": (db_p1, db_p2),
                "predictions": predictions,
                "error": "XGBoost model prediction not available",
                "tradable": False,
                "reason": "XGBoost model failed to generate prediction or model not loaded"
            }
        
        avg_prediction = xgboost_prediction
        
        # The model predicts probability that player1 (p1) wins
        # But we need to check which player Kalshi is asking about
        # If Kalshi is asking about player2, we need to flip the prediction
        
        if asked_is_p2:
            # Kalshi is asking about player2, so model_prob should be 1 - prediction
            # (since model predicts p1 wins, p2 wins = 1 - p1_wins)
            model_prob = 1.0 - avg_prediction
            if debug:
                print(f"  XGBoost predicts {db_p1} wins {avg_prediction:.1%}, so {db_p2} wins {model_prob:.1%}")
        elif asked_is_p1:
            # Kalshi is asking about player1, use prediction as-is
            model_prob = avg_prediction
            if debug:
                print(f"  XGBoost predicts {db_p1} wins {model_prob:.1%}")
        else:
            # Can't determine which player, default to player1 (original behavior)
            model_prob = avg_prediction
            if debug:
                print(f"  Could not determine asked player, defaulting to {db_p1} wins {model_prob:.1%} (XGBoost: {avg_prediction:.1%})")
        kalshi_prob = kalshi_odds["yes_prob"]
        
        if debug:
            print(f"  XGBoost probability: {model_prob:.1%}")
            print(f"  Kalshi probability: {kalshi_prob:.1%}")
            print(f"  Kalshi price (cents): {kalshi_odds.get('yes_price', 'N/A')}")
            if kalshi_prob < 0.02:  # Less than 2% seems wrong
                print(f"  ⚠️  WARNING: Kalshi probability seems too low ({kalshi_prob:.1%})")
                print(f"     This might indicate we're reading the wrong field or price extraction failed")
        
        value = model_prob - kalshi_prob
        
        # Calculate expected value (handle None odds)
        yes_odds = kalshi_odds.get("yes_odds")
        if yes_odds is not None and yes_odds > 0:
            expected_value = (model_prob * yes_odds) - 1.0
        else:
            # If odds are None or invalid, calculate from probability
            expected_value = (model_prob / kalshi_prob) - 1.0 if kalshi_prob > 0 else 0.0
        
        # Determine trade recommendation with explanations
        trade_side = None
        trade_value = None
        reason = []
        
        if value > 0.05:  # Model thinks higher probability than Kalshi
            trade_side = "yes"  # Buy YES (bet on player1)
            trade_value = value
            reason.append(f"Model predicts {model_prob:.1%} chance, Kalshi prices at {kalshi_prob:.1%} ({value:.1%} edge)")
            reason.append(f"Expected value: {expected_value:.1%}")
        elif value < -0.05:  # Model thinks lower probability than Kalshi
            trade_side = "no"  # Buy NO (bet against player1)
            trade_value = abs(value)
            reason.append(f"Model predicts {model_prob:.1%} chance, Kalshi prices at {kalshi_prob:.1%} ({abs(value):.1%} edge)")
            reason.append(f"Expected value: {expected_value:.1%}")
        else:
            # Not tradable - explain why
            if abs(value) < 0.02:
                reason.append(f"Model ({model_prob:.1%}) and Kalshi ({kalshi_prob:.1%}) are very close - no edge")
            elif value > 0:
                reason.append(f"Model predicts {model_prob:.1%} vs Kalshi {kalshi_prob:.1%} (+{value:.1%}), but below 5% threshold")
            else:
                reason.append(f"Model predicts {model_prob:.1%} vs Kalshi {kalshi_prob:.1%} ({value:.1%}), but below 5% threshold")
            if expected_value < min_ev:
                reason.append(f"Expected value {expected_value:.1%} below {min_ev:.1%} threshold")
            else:
                reason.append(f"Expected value: {expected_value:.1%}")
        
        # Get market volume for ranking (fetch fresh data to ensure accuracy)
        market_volume = self._get_market_volume(market, fetch_fresh=True)
        
        if debug:
            if market_volume:
                print(f"  Market volume: ${market_volume:,.0f}")
                # Also show raw values for debugging to help diagnose volume issues
                ticker = market.get("ticker")
                if ticker:
                    try:
                        client = getattr(self, 'kalshi', None)
                        if client:
                            # Extract event_ticker from market ticker
                            event_ticker = None
                            if ticker and '-' in ticker:
                                parts = ticker.rsplit('-', 1)
                                if len(parts) == 2:
                                    event_ticker = parts[0]
                            fresh = client.get_markets(event_ticker=event_ticker, limit=1) if event_ticker else None
                            if fresh and fresh.get("markets"):
                                raw_market = fresh["markets"][0]
                                print(f"    Raw volume fields from API (for debugging):")
                                for field in ["volume", "volume_dollars", "liquidity", "liquidity_dollars", 
                                            "pot", "total_volume", "total_pot", "open_interest", 
                                            "yes_volume", "no_volume"]:
                                    val = raw_market.get(field)
                                    if val is not None:
                                        print(f"      {field}: {val} ({type(val).__name__})")
                    except Exception as e:
                        print(f"    Could not fetch raw data: {e}")
            else:
                print(f"  ⚠️  Market volume: Not available")
        
        # Always print volume debug info if volume seems too high (to help diagnose)
        if market_volume and market_volume > 50000:  # If volume seems too high
            print(f"  ⚠️  WARNING: Market volume seems high (${market_volume:,.0f}). Checking raw API data...")
            ticker = market.get("ticker")
            if ticker:
                try:
                    client = getattr(self, 'kalshi', None)
                    if client:
                        # Extract event_ticker from market ticker
                        event_ticker = None
                        if ticker and '-' in ticker:
                            parts = ticker.rsplit('-', 1)
                            if len(parts) == 2:
                                event_ticker = parts[0]
                        fresh = client.get_markets(event_ticker=event_ticker, limit=1) if event_ticker else None
                        if fresh and fresh.get("markets"):
                            raw_market = fresh["markets"][0]
                            print(f"    All volume-related fields from API:")
                            for field in ["volume", "volume_dollars", "liquidity", "liquidity_dollars", 
                                        "pot", "total_volume", "total_pot", "open_interest", 
                                        "yes_volume", "no_volume", "total_yes_volume", "total_no_volume"]:
                                val = raw_market.get(field)
                                if val is not None:
                                    print(f"      {field}: {val} ({type(val).__name__})")
                except Exception as e:
                    print(f"    Could not fetch raw data: {e}")
        
        # Store raw model prediction for player1 (before adjustment)
        # This is the probability that player1 (db_p1) wins
        raw_model_prob_p1 = avg_prediction
        raw_model_prob_p2 = 1.0 - avg_prediction
        
        # Determine which player we're betting on for clearer display
        # If trade_side is "yes", we're betting on the player Kalshi is asking about
        # If trade_side is "no", we're betting against the player Kalshi is asking about
        bet_on_player = None
        if trade_side:
            if asked_is_p1:
                bet_on_player = db_p1 if trade_side == "yes" else db_p2
            elif asked_is_p2:
                bet_on_player = db_p2 if trade_side == "yes" else db_p1
            else:
                # Fallback: if we can't determine, assume trade_side "yes" means player1
                bet_on_player = db_p1 if trade_side == "yes" else db_p2
        
        return {
            "market": market,
            "ticker": market.get("ticker"),
            "title": market.get("title"),
            "kalshi_players": (kalshi_p1, kalshi_p2),
            "matched_players": (db_p1, db_p2),
            "predictions": predictions,
            "model_probability": model_prob,  # Adjusted for Kalshi's question
            "raw_model_probability_p1": raw_model_prob_p1,  # Raw: probability player1 wins
            "raw_model_probability_p2": raw_model_prob_p2,  # Raw: probability player2 wins
            "kalshi_odds": kalshi_odds,
            "kalshi_probability": kalshi_prob,
            "value": value,
            "expected_value": expected_value,
            "trade_side": trade_side,
            "trade_value": trade_value,
            "bet_on_player": bet_on_player,  # Player name we're betting on
            "tradable": trade_side is not None,
            "reason": "; ".join(reason) if reason else "No analysis available",
            "surface": surface,
            "best_of_5": best_of_5,
            "round_code": round_code,  # Add for debugging
            "tourney_level_code": tourney_level_code,  # Add for debugging
            "market_volume": market_volume  # Add volume for ranking
        }
    
    def scan_markets(self, limit: int = 500,
                    min_value: float = 0.05,
                    min_ev: float = 0.10,
                    debug: bool = False,
                    show_all: bool = False,
                    max_hours_ahead: int = 48,
                    min_volume: int = 0) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Scan all available tennis markets and identify value opportunities.
        
        Args:
            limit: Maximum number of markets to scan (increased default to 500)
            min_value: Minimum value threshold (default 5%)
            min_ev: Minimum expected value threshold (default 10%)
            debug: Print debug information
            show_all: If True, return all analyzed markets, not just tradable ones
            
        Returns:
            Tuple of (tradable_opportunities, all_analyses)
        """
        # NOTE: min_volume filtering is now done AFTER aggregation, so we pass min_volume=0 to fetch_tennis_markets
        # This ensures we use total match volume, not individual market volume
        markets = self.fetch_tennis_markets(limit=limit, debug=debug, max_hours_ahead=max_hours_ahead, min_volume=0)
        
        # Aggregate volumes by event_ticker (markets for the same match)
        # Group markets by event_ticker to sum volumes
        event_volumes = {}
        for market in markets:
            event_ticker = market.get("event_ticker")
            if event_ticker:
                volume = self._get_market_volume(market, fetch_fresh=False)  # Don't fetch fresh for all markets
                if volume:
                    if event_ticker not in event_volumes:
                        event_volumes[event_ticker] = 0
                    event_volumes[event_ticker] += volume
        
        if debug and event_volumes:
            print(f"\n📊 Match volumes (aggregated by event):")
            for event_ticker, total_vol in sorted(event_volumes.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {event_ticker}: ${total_vol:,.0f}")
        
        # Filter by total match volume AFTER aggregation
        # This ensures we use total match volume (sum of all markets for a match), not individual market volume
        if min_volume > 0:
            filtered_markets = []
            skipped_by_volume = {}  # Track which events were skipped and why
            for market in markets:
                event_ticker = market.get("event_ticker")
                if event_ticker and event_ticker in event_volumes:
                    total_match_volume = event_volumes[event_ticker]
                    if total_match_volume >= min_volume:
                        # Volume is sufficient, include this market
                        filtered_markets.append(market)
                    else:
                        # Track skipped markets for debug output
                        if event_ticker not in skipped_by_volume:
                            skipped_by_volume[event_ticker] = {
                                "volume": total_match_volume,
                                "markets": []
                            }
                        skipped_by_volume[event_ticker]["markets"].append(market)
                        # Skip this market (low total match volume)
                else:
                    # No event_ticker or not in event_volumes - include it anyway
                    # (We can't filter it by volume without event_ticker, so we allow it through)
                    filtered_markets.append(market)
            
            if debug and skipped_by_volume:
                print(f"\n⚠️  Skipped {len(skipped_by_volume)} matches (low total volume < ${min_volume:,}):")
                for event_ticker, info in sorted(skipped_by_volume.items(), key=lambda x: x[1]["volume"], reverse=True)[:5]:
                    vol_str = f"${info['volume']:,.0f}"
                    market_titles = [m.get("title", "Unknown")[:50] for m in info["markets"][:2]]  # Show first 2 markets
                    titles_str = " | ".join(market_titles)
                    print(f"  {event_ticker}: {vol_str} - {titles_str}")
            
            markets = filtered_markets
        
        tradable = []
        all_analyses = []
        
        if debug:
            print(f"\n{'=' * 70}")
            print(f"📊 MARKET DISCOVERY")
            print(f"{'=' * 70}")
            print(f"   Found: {len(markets)} tennis markets")
            if len(markets) > 0:
                print(f"   Example: {markets[0].get('title', 'Unknown')[:60]}...")
            if len(markets) < 5:
                print(f"   ⚠️  Low market count - check filters")
        
        print(f"\n   Analyzing {len(markets)} markets...", end="", flush=True)
        
        failed_analyses = []  # Track markets that failed analysis entirely
        
        # First pass: analyze all markets (don't add to tradable yet - we'll filter in second pass)
        for i, market in enumerate(markets):
            if (i + 1) % 10 == 0:
                print(f" {i + 1}/{len(markets)}", end="", flush=True)
            
            # Get total match volume (sum of all markets for this event)
            event_ticker = market.get("event_ticker")
            total_match_volume = None
            if event_ticker and event_ticker in event_volumes:
                total_match_volume = event_volumes[event_ticker]
            
            analysis = self.analyze_market(market, min_value=min_value, min_ev=min_ev, debug=debug)
            
            if analysis:
                # Override market volume with total match volume if available
                if total_match_volume is not None:
                    analysis["market_volume"] = total_match_volume
                    analysis["total_match_volume"] = total_match_volume  # Add for clarity
                    if debug:
                        individual_vol = self._get_market_volume(market, fetch_fresh=False)
                        individual_vol_str = f"${individual_vol:,.0f}" if individual_vol is not None else "N/A"
                        print(f"  Market {market.get('ticker', 'Unknown')}: Individual volume {individual_vol_str}, Total match volume ${total_match_volume:,.0f}")
                
                all_analyses.append(analysis)
            else:
                # Market failed analysis (e.g., player matching failed, no odds, etc.)
                failed_analyses.append({
                    "ticker": market.get("ticker", "Unknown"),
                    "title": market.get("title", "Unknown Market"),
                    "reason": "Analysis failed (likely player matching or odds extraction issue)"
                })
        
        print(f" Done")
        
        if debug:
            print(f"   Analyzed: {len(all_analyses)} | Failed: {len(failed_analyses)}")
        
        # Second pass: Group by event/match and select only the favored player's opportunity
        # Group analyses by event_ticker (markets for the same match)
        match_groups = {}
        for analysis in all_analyses:
            event_ticker = analysis.get("market", {}).get("event_ticker")
            if not event_ticker:
                # Try to extract from ticker: KXATPMATCH-26JAN03SWEOCO-THO -> KXATPMATCH-26JAN03SWEOCO
                ticker = analysis.get("ticker", "")
                if '-' in ticker:
                    parts = ticker.rsplit('-', 1)
                    if len(parts) == 2:
                        event_ticker = parts[0]
            
            if event_ticker:
                if event_ticker not in match_groups:
                    match_groups[event_ticker] = []
                match_groups[event_ticker].append(analysis)
        
        # For each match, determine which player the model favors and only keep that opportunity
        for event_ticker, match_analyses in match_groups.items():
            if len(match_analyses) < 2:
                # Only one market for this match, process normally
                for analysis in match_analyses:
                    if analysis.get("tradable") and analysis.get("trade_value", 0) >= min_value:
                        if analysis.get("expected_value", 0) >= min_ev:
                            tradable.append(analysis)
                continue
            
            # Multiple markets for the same match - determine which player the model favors
            # Get raw model probabilities from first analysis (they should be the same for all markets in the same match)
            raw_p1_prob = None
            raw_p2_prob = None
            matched_players = None
            
            for analysis in match_analyses:
                raw_p1_prob = analysis.get("raw_model_probability_p1")
                raw_p2_prob = analysis.get("raw_model_probability_p2")
                matched_players = analysis.get("matched_players")
                if raw_p1_prob is not None and raw_p2_prob is not None:
                    break  # Got the probabilities, exit loop
            
            # Determine which player the model predicts will win
            if raw_p1_prob is not None and raw_p2_prob is not None:
                model_favors_p1 = raw_p1_prob > raw_p2_prob
                favored_player_idx = 0 if model_favors_p1 else 1
                favored_player_name = matched_players[favored_player_idx] if matched_players else None
                
                if debug and favored_player_name:
                    print(f"\n  Match {event_ticker}: Model favors {favored_player_name} ({max(raw_p1_prob, raw_p2_prob):.1%} vs {min(raw_p1_prob, raw_p2_prob):.1%})")
                
                # Find the analysis for the favored player's market
                # We need to identify which market is asking about the favored player
                # Use the matched_players tuple to determine player order
                favored_market_analysis = None
                best_edge = -1
                
                for analysis in match_analyses:
                    matched_players_analysis = analysis.get("matched_players", ())
                    if not matched_players_analysis or len(matched_players_analysis) < 2:
                        continue
                    
                    # Get the player names from this analysis
                    p1_name = matched_players_analysis[0]
                    p2_name = matched_players_analysis[1]
                    
                    # Determine which player this market is asking about
                    # The model_prob tells us: if it's close to raw_p1_prob, it's asking about p1
                    # If it's close to raw_p2_prob, it's asking about p2
                    model_prob = analysis.get("model_probability")
                    kalshi_prob = analysis.get("kalshi_probability", 0)
                    
                    if model_prob is None or kalshi_prob is None:
                        continue
                    
                    # Determine which player this market is asking about by comparing model_prob to raw probabilities
                    # Use a larger tolerance (0.10 = 10%) to account for rounding differences
                    is_p1_market = abs(model_prob - raw_p1_prob) < abs(model_prob - raw_p2_prob)
                    
                    # This market is for the favored player if:
                    # - Model favors p1 and this is a p1 market, OR
                    # - Model favors p2 and this is a p2 market (which means it's NOT a p1 market)
                    is_favored_player_market = (model_favors_p1 and is_p1_market) or (not model_favors_p1 and not is_p1_market)
                    
                    if is_favored_player_market:
                        # Calculate edge (model_prob - kalshi_prob)
                        edge = model_prob - kalshi_prob
                        
                        # Only consider if edge > 2% (0.02)
                        if edge > 0.02:
                            if edge > best_edge:
                                best_edge = edge
                                favored_market_analysis = analysis
                
                # Only add the favored player's opportunity (if found and edge > 2%)
                if favored_market_analysis and favored_market_analysis.get("tradable"):
                    if favored_market_analysis.get("expected_value", 0) >= min_ev:
                        tradable.append(favored_market_analysis)
            else:
                # Couldn't determine favored player, process all normally (fallback)
                for analysis in match_analyses:
                    if analysis.get("tradable") and analysis.get("trade_value", 0) >= min_value:
                        if analysis.get("expected_value", 0) >= min_ev:
                            tradable.append(analysis)
        
        if debug:
            print(f"   Tradable opportunities: {len(tradable)} (after grouping by match)")
        
        # Add failed analyses to all_analyses for reporting
        if show_all:
            for failed in failed_analyses:
                all_analyses.append({
                    "ticker": failed["ticker"],
                    "title": failed["title"],
                    "tradable": False,
                    "reason": failed["reason"],
                    "value": 0,
                    "expected_value": 0,
                })
        
        # Sort tradable opportunities by market volume (descending) for more reliable odds
        # Markets with higher volume have tighter spreads and more reliable pricing
        tradable.sort(key=lambda x: x.get("market_volume") or 0, reverse=True)
        
        if show_all:
            return tradable, all_analyses
        return tradable, []


"""
Kalshi Market Analyzer - Fetches Kalshi markets, matches to players,
and generates predictions for value trading opportunities.
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from src.trading.kalshi_client import KalshiClient
from src.trading.kalshi_discovery import fetch_events, flatten_markets, filter_tennis_markets
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor


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
            "tennis", "atp", "wta", "grand slam", "wimbledon", 
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
                tennis_series = ["KXATPMATCH", "KXWTAMATCH", "KXUNITEDCUPMATCH"]
                
                all_markets_from_series = []
                for series in tennis_series:
                    try:
                        if debug:
                            print(f"   Searching series: {series}...")
                        response = self.kalshi.get_markets(
                            series_ticker=series,
                            status="open",
                            limit=min(limit, 1000)
                        )
                        series_markets = response.get("markets", [])
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
            
            # Apply discovery filtering if we have markets from event search
            # Note: Markets from event search are already filtered by keyword in the event search,
            # so we don't need to filter by keyword again - just apply volume and time filters
            if markets and not event_ticker:
                # Apply volume and time filters only (keyword already applied via event search)
                try:
                    # Filter by volume and time, but skip keyword filtering since events are already tennis-related
                    filtered = []
                    for market in markets:
                        # Check volume
                        vol = market.get("volume_dollars") or market.get("liquidity_dollars") or market.get("volume", 0)
                        try:
                            vol = float(vol) if vol else 0
                            if vol > 1000:
                                vol = vol / 100.0
                        except (ValueError, TypeError):
                            vol = 0
                        
                        if vol < min_volume:
                            continue
                        
                        # Check time (if we have close time)
                        if market.get("event_close_time"):
                            try:
                                close_time = market.get("event_close_time")
                                if isinstance(close_time, str):
                                    if 'T' in close_time:
                                        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                                    else:
                                        close_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                                        close_dt = close_dt.replace(tzinfo=timezone.utc)
                                else:
                                    close_dt = datetime.now(timezone.utc)
                                
                                if close_dt.tzinfo is None:
                                    close_dt = close_dt.replace(tzinfo=timezone.utc)
                                else:
                                    close_dt = close_dt.astimezone(timezone.utc)
                                
                                now = datetime.now(timezone.utc)
                                time_diff = (close_dt - now).total_seconds() / 3600
                                
                                if not (-2 <= time_diff <= max_hours_ahead):
                                    continue
                            except Exception:
                                pass  # If time parsing fails, include the market
                        
                        filtered.append(market)
                    
                    markets = filtered
                    if debug:
                        print(f"   ✅ After filtering (volume/time): {len(markets)} markets")
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
            # Use UTC-aware datetime for consistent comparison
            now = datetime.now(timezone.utc)
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
                    if any(kw in full_text for kw in ['tennis', 'atp', 'wta', 'united cup', 'davis cup']):
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
                    
                    # Specifically search for "zhang" in ALL markets
                    zhang_markets = [(m.get('title', 'N/A'), m.get('ticker', 'N/A'), m.get('subtitle', '')) 
                                     for m in markets if 'zhang' in (m.get('title', '') + ' ' + m.get('subtitle', '')).lower()]
                    if zhang_markets:
                        print(f"\n   🔍 Found {len(zhang_markets)} markets containing 'Zhang':")
                        for title, ticker, subtitle in zhang_markets[:10]:
                            subtitle_str = f" (subtitle: {subtitle})" if subtitle else ""
                            print(f"     - {title}{subtitle_str} (ticker: {ticker})")
                    else:
                        print(f"\n   ⚠️  No markets found containing 'Zhang' in first {len(markets)} markets!")
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
                    # Normalize to UTC-aware for comparison
                    if market_time.tzinfo is None:
                        # Naive datetime - assume UTC
                        market_time = market_time.replace(tzinfo=timezone.utc)
                    else:
                        # Already aware - convert to UTC
                        market_time = market_time.astimezone(timezone.utc)
                    
                    time_diff = (market_time - now).total_seconds() / 3600  # hours
                    
                    # Only skip if market is more than max_hours_ahead away
                    if time_diff > max_hours_ahead:
                        if debug:
                            print(f"  Skipped (too far): {market.get('title', 'N/A')} (time: {market_time.strftime('%Y-%m-%d %H:%M')}, {time_diff:.1f}h away)")
                        continue
                    
                    # Don't skip markets that are very close (even if slightly in the past)
                    # Markets might still be tradeable if they're within a few hours
                    if time_diff < -2:  # More than 2 hours in the past
                        if debug:
                            print(f"  Skipped (too far past): {market.get('title', 'N/A')} (time: {market_time.strftime('%Y-%m-%d %H:%M')}, {time_diff:.1f}h ago)")
                        continue
                    
                    # Log markets that are very close (might be starting soon)
                    if debug and -1 < time_diff < 3:  # Between 1 hour ago and 3 hours ahead
                        print(f"  ⏰ Market starting soon: {market.get('title', 'N/A')} (time: {market_time.strftime('%Y-%m-%d %H:%M')}, {time_diff:.1f}h {'ago' if time_diff < 0 else 'ahead'})")
                
                # Filter by volume if specified
                if min_volume > 0:
                    market_volume = self._get_market_volume(market)
                    if market_volume is None or market_volume < min_volume:
                        if debug:
                            vol_str = f"${market_volume:,.0f}" if market_volume else "unknown"
                            print(f"  Skipped (low volume): {market.get('title', 'N/A')} (volume: {vol_str})")
                        continue  # Skip markets below minimum volume
                
                # If we got here, it's a valid tennis market
                tennis_markets.append(market)
                parsed_count += 1
                if debug and parsed_count <= 10:
                    time_str = market_time.strftime("%Y-%m-%d %H:%M") if market_time else "N/A"
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
            
            return tennis_markets
        except Exception as e:
            print(f"Error fetching markets: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _parse_market_time(self, market: Dict[str, Any]) -> Optional[datetime]:
        """
        Parse market start time from market data.
        
        Tries various field names: expected_expiration_time, expiration_time, 
        expected_expiration, start_time, etc.
        """
        # Try various possible field names
        time_fields = [
            "expected_expiration_time",
            "expiration_time", 
            "expected_expiration",
            "start_time",
            "event_time",
            "market_time",
            "expires_at"
        ]
        
        for field in time_fields:
            time_val = market.get(field)
            if time_val:
                try:
                    # Try parsing as ISO format string
                    if isinstance(time_val, str):
                        # Handle different formats
                        if 'T' in time_val:
                            # ISO format: "2024-01-26T14:30:00Z"
                            dt = datetime.fromisoformat(time_val.replace('Z', '+00:00'))
                        else:
                            # Try other formats
                            dt = datetime.strptime(time_val, "%Y-%m-%d %H:%M:%S")
                        return dt
                    elif isinstance(time_val, (int, float)):
                        # Unix timestamp
                        return datetime.fromtimestamp(time_val)
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _get_market_volume(self, market: Dict[str, Any]) -> Optional[float]:
        """
        Get market volume/pot size from market data.
        
        Tries various field names: volume, total_volume, pot, total_pot,
        liquidity, open_interest, etc.
        
        Returns volume in dollars (cents / 100), or None if not found.
        """
        # Try various possible field names (volume might be in cents)
        volume_fields = [
            "volume",
            "total_volume",
            "pot",
            "total_pot",
            "liquidity",
            "open_interest",
            "total_liquidity",
            "market_volume"
        ]
        
        for field in volume_fields:
            volume_val = market.get(field)
            if volume_val is not None:
                try:
                    # Volume might be in cents, convert to dollars
                    if isinstance(volume_val, (int, float)):
                        # If it's a large number (> 1000), assume it's in cents
                        if volume_val > 1000:
                            return volume_val / 100.0
                        else:
                            # Otherwise assume it's already in dollars
                            return float(volume_val)
                except (ValueError, TypeError):
                    continue
        
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
        # Updated to handle hyphenated and multi-word names
        pattern1a = r"will\s+([A-Za-z\s]+?)\s+win\s+the\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)\s+vs\.?\s+([A-Za-z\-\']+(?:\s+[A-Za-z\-\']+)?)"
        match1a = re.search(pattern1a, full_text, re.IGNORECASE)
        if match1a:
            player1 = match1a.group(1).strip()
            # Extract players from "Player1 vs Player2" part
            p1_from_vs = match1a.group(2).strip()
            p2_from_vs = match1a.group(3).strip()
            # Remove any trailing info like ": Group E match"
            p2_from_vs = re.sub(r"\s*:\s*.*$", "", p2_from_vs)
            # Return the players from the "vs" part (more reliable)
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
                ["cup", "open", "atp", "wta", "championship", "masters", "grand slam"]):
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
                               any(term in p1.lower() for term in ["cup", "open", "championship", "atp", "wta", "tour"]))
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
            player1 = re.sub(r"^(united\s+cup|atp|wta|davis\s+cup)\s+", "", player1, flags=re.IGNORECASE).strip()
            player2 = re.sub(r"^(united\s+cup|atp|wta|davis\s+cup)\s+", "", player2, flags=re.IGNORECASE).strip()
            
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
    
    def analyze_market(self, market: Dict[str, Any], 
                      surface: str = "Hard",
                      best_of_5: bool = False,
                      round_code: int = 7,
                      tourney_level_code: int = 2,
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
        h2h_diff = self.player_db.get_h2h(p1_id, p2_id)
        
        # Build features and predict
        features = self.predictor.build_features(
            p1_stats, p2_stats, surface=surface,
            best_of_5=best_of_5, round_code=round_code,
            tourney_level_code=tourney_level_code,
            h2h_diff=h2h_diff
        )
        
        predictions = self.predictor.predict(features)
        
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
        
        # Get market volume for ranking
        market_volume = self._get_market_volume(market)
        
        return {
            "market": market,
            "ticker": market.get("ticker"),
            "title": market.get("title"),
            "kalshi_players": (kalshi_p1, kalshi_p2),
            "matched_players": (db_p1, db_p2),
            "predictions": predictions,
            "model_probability": model_prob,
            "kalshi_odds": kalshi_odds,
            "kalshi_probability": kalshi_prob,
            "value": value,
            "expected_value": expected_value,
            "trade_side": trade_side,
            "trade_value": trade_value,
            "tradable": trade_side is not None,
            "reason": "; ".join(reason) if reason else "No analysis available",
            "surface": surface,
            "best_of_5": best_of_5,
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
        markets = self.fetch_tennis_markets(limit=limit, debug=debug, max_hours_ahead=max_hours_ahead, min_volume=min_volume)
        tradable = []
        all_analyses = []
        
        print(f"Scanning {len(markets)} tennis markets...")
        
        for i, market in enumerate(markets):
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(markets)} markets...")
            
            analysis = self.analyze_market(market, min_value=min_value, min_ev=min_ev, debug=debug)
            
            if analysis:
                all_analyses.append(analysis)
                
                # Check if tradable
                if analysis.get("tradable") and analysis.get("trade_value", 0) >= min_value:
                    if analysis.get("expected_value", 0) >= min_ev:
                        tradable.append(analysis)
        
        print(f"Analyzed {len(all_analyses)} markets")
        print(f"Found {len(tradable)} tradable opportunities")
        
        # Sort tradable opportunities by market volume (descending) for more reliable odds
        # Markets with higher volume have tighter spreads and more reliable pricing
        tradable.sort(key=lambda x: x.get("market_volume") or 0, reverse=True)
        
        if show_all:
            return tradable, all_analyses
        return tradable, []


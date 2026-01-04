# Testing Guide for Kalshi Discovery Filtering System

This guide explains how to test the robust layered filtering system for Kalshi tennis markets.

**Note**: The system now uses direct series ticker search (KXATPMATCH, KXWTAMATCH, KXUNITEDCUPMATCH) which is much more reliable than event search.

## Quick Start

### 1. Run Unit Tests (No API Required)

Test the filtering logic without making API calls:

```bash
python3 scripts/trading/test_discovery.py
```

This will test all 6 layers of filtering:
- ✅ Layer 2: Tennis keyword detection
- ✅ Layer 3: Match structure heuristic
- ✅ Layer 4: Market structure validation
- ✅ Layer 5: Expiration window
- ✅ Layer 6: Liquidity check
- ✅ Full filter pipeline

### 2. Test with Real Kalshi API

Test the complete system with actual Kalshi markets:

```bash
python3 scripts/trading/scan_kalshi_markets.py --limit 100 --debug
```

This will:
1. Fetch events from Kalshi using `GET /v1/events?search=tennis`
2. Extract markets from events
3. Apply all 6 layers of filtering
4. Show detailed logging for each rejected market
5. Display valid tennis markets

### 3. Test with Different Parameters

```bash
# Test with higher volume requirement
python3 scripts/trading/scan_kalshi_markets.py --limit 200 --min-volume 500 --debug

# Test with shorter time window
python3 scripts/trading/scan_kalshi_markets.py --limit 100 --max-hours 24 --debug

# Test with specific event ticker
python3 scripts/trading/scan_kalshi_markets.py --event-ticker TENNIS-ATP-2024 --debug
```

## Understanding the Output

### Successful Filtering

When filtering works correctly, you'll see:

```
🔍 Fetching markets from Kalshi API...
   Trying event search API with keyword 'tennis'...
   ✅ Found 50 events via event search API
   ✅ Extracted 204 event-market pairs

🔍 Filtering 204 event-market pairs through 6 layers...
  ❌ MARKET-123: FAILED tennis_keywords - (no tennis keywords found)
  ❌ MARKET-456: FAILED match_structure_no_vs - (no 'vs' pattern)
  ❌ MARKET-789: FAILED market_structure_not_open - (market is closed)
  ✅ 15 markets passed all filters
```

### What Each Layer Checks

1. **Layer 1 (Series/Category)**: Optional - checks if `series_ticker` or `category` contains "tennis"
2. **Layer 2 (Tennis Keywords)**: Requires at least one: "tennis", "atp", "wta", "wimbledon", "us open", etc.
3. **Layer 3 (Match Structure)**: Must contain " vs " or " v. ", excludes "tournament", "season", "champion"
4. **Layer 4 (Market Structure)**: Must be `status == "open"` with both `yes_price` and `no_price`
5. **Layer 5 (Expiration)**: Must be in future, within 72 hours (configurable)
6. **Layer 6 (Liquidity)**: Must have `volume >= 200` (configurable)

## Testing Individual Components

### Test Keyword Matching

```python
from src.trading.kalshi_discovery import layer2_tennis_keywords

event = {"event_title": "ATP Tennis Match", "event_description": ""}
market = {"title": "Djokovic vs Nadal"}
result = layer2_tennis_keywords(event, market)
# Returns None if passes, or "tennis_keywords" if fails
```

### Test Match Structure

```python
from src.trading.kalshi_discovery import layer3_match_structure

event = {"event_title": "Djokovic vs Nadal"}
market = {"title": ""}
result = layer3_match_structure(event, market)
# Returns None if passes, or rejection reason if fails
```

### Test Full Filter

```python
from src.trading.kalshi_discovery import is_valid_tennis_market
from datetime import datetime, timezone, timedelta

event = {
    "event_title": "ATP Tennis: Djokovic vs Nadal",
    "event_description": "Tennis match",
    "event_close_time": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
}
market = {
    "ticker": "TENNIS-123",
    "title": "Djokovic vs Nadal",
    "status": "open",
    "yes_bid": 60,
    "no_bid": 40,
    "volume_dollars": 500
}

is_valid, reason = is_valid_tennis_market(event, market, max_hours=72, min_volume=200)
# Returns (True, None) if valid, or (False, "layer:reason") if invalid
```

## Running Unit Tests (pytest)

If you have pytest installed:

```bash
pytest tests/test_kalshi_discovery.py -v
```

Or with unittest:

```bash
python3 -m unittest tests.test_kalshi_discovery -v
```

## Expected Results

### When Tennis Markets Are Available

- You should see markets passing all 6 layers
- Markets will be sorted by soonest close time, then highest volume
- Each market will have: `event_title`, `market_ticker`, `yes_price`, `no_price`, `volume`, `event_close_time`

### When No Tennis Markets Are Available

- All markets will be rejected with specific reasons
- Common rejection reasons:
  - `tennis_keywords`: No tennis-related keywords found
  - `match_structure_no_vs`: Title doesn't contain " vs " pattern
  - `expiration_window_past`: Market already closed
  - `liquidity_too_low_X`: Volume below minimum threshold

## Troubleshooting

### No markets found

1. **Check if tennis events exist**: The event search might return non-tennis events if Kalshi's search is broad
2. **Check rejection logs**: Look at the `FAILED` messages to see why markets are being rejected
3. **Adjust filters**: Try lowering `--min-volume` or increasing `--max-hours`

### Too many markets rejected

1. **Check Layer 2**: Are tennis keywords being detected? Try adding more keywords to `TENNIS_KEYWORDS` in `kalshi_discovery.py`
2. **Check Layer 3**: Are match titles containing " vs "? Some markets might use different formats
3. **Check Layer 4**: Are markets actually open? Check `status` field

### Markets passing but not tennis

1. **Strengthen Layer 2**: Add more specific tennis keywords
2. **Strengthen Layer 3**: Add more exclusion keywords for non-match markets
3. **Check Layer 1**: Use `series_ticker` or `category` filtering if available

## Next Steps

After testing:

1. **Adjust thresholds**: Modify `min_volume` and `max_hours` based on your needs
2. **Customize keywords**: Update `TENNIS_KEYWORDS` and `EXCLUSION_KEYWORDS` in `kalshi_discovery.py`
3. **Integrate with trading**: Use filtered markets in your trading logic


"""
Unit tests for Kalshi discovery and filtering logic.
"""

import unittest
from datetime import datetime, timezone, timedelta
from src.trading.kalshi_discovery import (
    layer2_tennis_keywords,
    layer3_match_structure,
    layer4_market_structure,
    layer5_expiration_window,
    layer6_liquidity,
    is_valid_tennis_market,
    filter_tennis_markets
)


class TestTennisKeywordMatching(unittest.TestCase):
    """Test Layer 2: Tennis keyword detection."""
    
    def test_passes_with_tennis_keyword(self):
        event = {"event_title": "ATP Tennis Match", "event_description": ""}
        market = {"title": "Djokovic vs Nadal"}
        self.assertIsNone(layer2_tennis_keywords(event, market))
    
    def test_passes_with_atp_keyword(self):
        event = {"event_title": "ATP Finals", "event_description": ""}
        market = {"title": "Match"}
        self.assertIsNone(layer2_tennis_keywords(event, market))
    
    def test_passes_with_wta_keyword(self):
        event = {"event_title": "WTA Tournament", "event_description": ""}
        market = {"title": "Match"}
        self.assertIsNone(layer2_tennis_keywords(event, market))
    
    def test_fails_without_tennis_keyword(self):
        event = {"event_title": "Basketball Game", "event_description": ""}
        market = {"title": "Lakers vs Warriors"}
        self.assertEqual(layer2_tennis_keywords(event, market), "tennis_keywords")
    
    def test_passes_with_keyword_in_description(self):
        event = {"event_title": "Match", "event_description": "Tennis championship"}
        market = {"title": "Player A vs Player B"}
        self.assertIsNone(layer2_tennis_keywords(event, market))


class TestMatchStructure(unittest.TestCase):
    """Test Layer 3: Match structure heuristic."""
    
    def test_passes_with_vs(self):
        event = {"event_title": "Djokovic vs Nadal"}
        market = {"title": ""}
        self.assertIsNone(layer3_match_structure(event, market))
    
    def test_passes_with_v_dot(self):
        event = {"event_title": "Djokovic v. Nadal"}
        market = {"title": ""}
        self.assertIsNone(layer3_match_structure(event, market))
    
    def test_fails_without_vs(self):
        event = {"event_title": "Djokovic wins tournament"}
        market = {"title": ""}
        self.assertEqual(layer3_match_structure(event, market), "match_structure_no_vs")
    
    def test_fails_with_tournament_keyword(self):
        event = {"event_title": "Djokovic vs Nadal tournament"}
        market = {"title": ""}
        self.assertIsNotNone(layer3_match_structure(event, market))
    
    def test_fails_with_champion_keyword(self):
        event = {"event_title": "Djokovic vs Nadal champion"}
        market = {"title": ""}
        self.assertIsNotNone(layer3_match_structure(event, market))


class TestMarketStructure(unittest.TestCase):
    """Test Layer 4: Market structure validation."""
    
    def test_passes_with_open_status(self):
        event = {}
        market = {"status": "open", "yes_bid": 50, "no_bid": 50}
        self.assertIsNone(layer4_market_structure(event, market))
    
    def test_passes_with_active_status(self):
        event = {}
        market = {"status": "active", "yes_bid": 50, "no_bid": 50}
        self.assertIsNone(layer4_market_structure(event, market))
    
    def test_fails_with_closed_status(self):
        event = {}
        market = {"status": "closed", "yes_bid": 50, "no_bid": 50}
        self.assertEqual(layer4_market_structure(event, market), "market_structure_not_open")
    
    def test_fails_without_yes_price(self):
        event = {}
        market = {"status": "open", "no_bid": 50}
        self.assertEqual(layer4_market_structure(event, market), "market_structure_no_yes_price")
    
    def test_fails_without_no_price(self):
        event = {}
        market = {"status": "open", "yes_bid": 50}
        self.assertEqual(layer4_market_structure(event, market), "market_structure_no_no_price")


class TestExpirationWindow(unittest.TestCase):
    """Test Layer 5: Expiration window filtering."""
    
    def test_passes_within_window(self):
        future_time = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        event = {"event_close_time": future_time}
        market = {}
        self.assertIsNone(layer5_expiration_window(event, market, max_hours=72))
    
    def test_fails_too_far_future(self):
        future_time = (datetime.now(timezone.utc) + timedelta(hours=100)).isoformat()
        event = {"event_close_time": future_time}
        market = {}
        self.assertIsNotNone(layer5_expiration_window(event, market, max_hours=72))
    
    def test_fails_in_past(self):
        past_time = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        event = {"event_close_time": past_time}
        market = {}
        self.assertEqual(layer5_expiration_window(event, market, max_hours=72), "expiration_window_past")
    
    def test_passes_with_grace_period(self):
        # Within 2 hour grace period
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        event = {"event_close_time": past_time}
        market = {}
        self.assertIsNone(layer5_expiration_window(event, market, max_hours=72))


class TestLiquidity(unittest.TestCase):
    """Test Layer 6: Liquidity filtering."""
    
    def test_passes_with_sufficient_volume(self):
        event = {}
        market = {"volume_dollars": 500}
        self.assertIsNone(layer6_liquidity(event, market, min_volume=200))
    
    def test_fails_with_insufficient_volume(self):
        event = {}
        market = {"volume_dollars": 100}
        self.assertIsNotNone(layer6_liquidity(event, market, min_volume=200))
    
    def test_passes_with_volume_in_cents(self):
        event = {}
        market = {"volume": 50000}  # $500 in cents
        self.assertIsNone(layer6_liquidity(event, market, min_volume=200))
    
    def test_passes_with_liquidity_dollars(self):
        event = {}
        market = {"liquidity_dollars": 300}
        self.assertIsNone(layer6_liquidity(event, market, min_volume=200))


class TestFullFilter(unittest.TestCase):
    """Test complete filtering pipeline."""
    
    def test_valid_tennis_market_passes_all_layers(self):
        future_time = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        event = {
            "event_title": "ATP Tennis: Djokovic vs Nadal",
            "event_description": "Tennis match",
            "event_close_time": future_time,
            "category": "Sports",
            "series_ticker": "TENNIS-ATP"
        }
        market = {
            "ticker": "TENNIS-ATP-123",
            "title": "Djokovic vs Nadal",
            "status": "open",
            "yes_bid": 60,
            "no_bid": 40,
            "volume_dollars": 500
        }
        
        is_valid, reason = is_valid_tennis_market(event, market, max_hours=72, min_volume=200, log_rejections=False)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)
    
    def test_invalid_market_fails_keyword_layer(self):
        event = {
            "event_title": "Basketball Game",
            "event_description": "",
            "event_close_time": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }
        market = {
            "ticker": "BASKET-123",
            "title": "Lakers vs Warriors",
            "status": "open",
            "yes_bid": 50,
            "no_bid": 50,
            "volume_dollars": 500
        }
        
        is_valid, reason = is_valid_tennis_market(event, market, max_hours=72, min_volume=200, log_rejections=False)
        self.assertFalse(is_valid)
        self.assertIn("tennis_keywords", reason)
    
    def test_filter_tennis_markets_function(self):
        future_time = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        
        # Valid market
        event1 = {
            "event_title": "ATP Tennis: Player A vs Player B",
            "event_description": "Tennis",
            "event_close_time": future_time,
        }
        market1 = {
            "ticker": "TENNIS-1",
            "title": "Player A vs Player B",
            "status": "open",
            "yes_bid": 55,
            "no_bid": 45,
            "volume_dollars": 300
        }
        
        # Invalid market (no tennis keyword)
        event2 = {
            "event_title": "Basketball Game",
            "event_description": "",
            "event_close_time": future_time,
        }
        market2 = {
            "ticker": "BASKET-1",
            "title": "Team A vs Team B",
            "status": "open",
            "yes_bid": 50,
            "no_bid": 50,
            "volume_dollars": 500
        }
        
        pairs = [(event1, market1), (event2, market2)]
        results = filter_tennis_markets(pairs, max_hours=72, min_volume=200, log_rejections=False)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["market_ticker"], "TENNIS-1")


if __name__ == "__main__":
    unittest.main()


"""
Betting odds fetcher - connects to sports betting odds APIs.
Supports multiple providers for arbitrage and value betting opportunities.
"""

import requests
import time
from typing import Dict, Optional, List
from datetime import datetime


class OddsFetcher:
    """Fetch and parse betting odds from various APIs."""
    
    def __init__(self, api_key: Optional[str] = None, api_provider: str = "oddsapi"):
        """
        Initialize odds fetcher.
        
        Providers:
        - 'oddsapi': The Odds API (the-odds-api.com) - free tier available
        - 'sportradar': Sportradar API (requires subscription)
        """
        self.api_key = api_key
        self.api_provider = api_provider
        self.base_urls = {
            "oddsapi": "https://api.the-odds-api.com/v4",
            "sportradar": "https://api.sportradar.com/tennis"
        }
    
    def find_match_odds(self, player1_name: str, player2_name: str, 
                       sport: str = "tennis", predictions: Optional[Dict[str, float]] = None) -> Optional[Dict]:
        """
        Find betting odds for a specific match.
        
        Returns dictionary with format:
        {
            "player1": {
                "name": "...",
                "odds": 2.10,  # Decimal odds
                "implied_prob": 0.476,  # 1/odds
                "bookmakers": ["bet365", "draftkings"]
            },
            "player2": { ... },
            "bookmakers": ["bet365", "draftkings"],
            "timestamp": "..."
        }
        """
        if self.api_provider == "oddsapi":
            result = self._fetch_oddsapi(player1_name, player2_name, sport)
            # If no API key and we have predictions, generate realistic odds
            if not result and not self.api_key and predictions:
                return self._generate_odds_from_predictions(player1_name, player2_name, predictions)
            elif not result and not self.api_key:
                # Fallback to old mock odds if no predictions
                return self._get_mock_odds(player1_name, player2_name)
            return result
        elif self.api_provider == "sportradar":
            return self._fetch_sportradar(player1_name, player2_name)
        else:
            raise ValueError(f"Unknown provider: {self.api_provider}")
    
    def _fetch_oddsapi(self, player1_name: str, player2_name: str, sport: str) -> Optional[Dict]:
        """Fetch odds from The Odds API."""
        if not self.api_key:
            # Return None to trigger prediction-based odds or fallback mock odds
            return None
        
        try:
            # Search for upcoming tennis matches
            url = f"{self.base_urls['oddsapi']}/sports/{sport}/odds"
            params = {
                "apiKey": self.api_key,
                "regions": "us,us2",  # US bookmakers
                "markets": "h2h",  # Head-to-head (moneyline)
                "oddsFormat": "decimal"
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            matches = response.json()
            
            # Find matching match by player names
            for match in matches:
                home_team = match.get("home_team", "").lower()
                away_team = match.get("away_team", "").lower()
                p1_lower = player1_name.lower()
                p2_lower = player2_name.lower()
                
                # Try to match players (flexible matching)
                if ((p1_lower in home_team or home_team in p1_lower) and
                    (p2_lower in away_team or away_team in p2_lower)) or \
                   ((p2_lower in home_team or home_team in p2_lower) and
                    (p1_lower in away_team or away_team in p1_lower)):
                    
                    return self._parse_oddsapi_match(match, player1_name, player2_name)
            
            return None
        except Exception as e:
            print(f"Error fetching odds: {e}")
            return None
    
    def _parse_oddsapi_match(self, match_data: Dict, p1_name: str, p2_name: str) -> Dict:
        """Parse odds from The Odds API response."""
        bookmakers = match_data.get("bookmakers", [])
        
        # Collect all odds
        p1_odds = []
        p2_odds = []
        bookmaker_names = []
        
        for bookmaker in bookmakers:
            bookmaker_name = bookmaker.get("title", "unknown")
            bookmaker_names.append(bookmaker_name)
            
            markets = bookmaker.get("markets", [])
            for market in markets:
                if market.get("key") == "h2h":  # Head-to-head market
                    outcomes = market.get("outcomes", [])
                    for outcome in outcomes:
                        name = outcome.get("name", "").lower()
                        odds = outcome.get("price", 0)
                        
                        if p1_name.lower() in name or name in p1_name.lower():
                            p1_odds.append({"odds": odds, "bookmaker": bookmaker_name})
                        elif p2_name.lower() in name or name in p2_name.lower():
                            p2_odds.append({"odds": odds, "bookmaker": bookmaker_name})
        
        # Get best odds (highest decimal odds = best for bettor)
        best_p1 = max(p1_odds, key=lambda x: x["odds"]) if p1_odds else None
        best_p2 = max(p2_odds, key=lambda x: x["odds"]) if p2_odds else None
        
        return {
            "player1": {
                "name": p1_name,
                "odds": best_p1["odds"] if best_p1 else None,
                "implied_prob": 1 / best_p1["odds"] if best_p1 else None,
                "bookmakers": list(set([o["bookmaker"] for o in p1_odds])),
                "all_odds": p1_odds
            },
            "player2": {
                "name": p2_name,
                "odds": best_p2["odds"] if best_p2 else None,
                "implied_prob": 1 / best_p2["odds"] if best_p2 else None,
                "bookmakers": list(set([o["bookmaker"] for o in p2_odds])),
                "all_odds": p2_odds
            },
            "bookmakers": list(set(bookmaker_names)),
            "timestamp": datetime.now().isoformat()
        }
    
    def _get_mock_odds(self, player1_name: str, player2_name: str) -> Dict:
        """Return mock odds for demonstration purposes."""
        # Mock odds - in production, replace with real API calls
        # Use deterministic hash to ensure same players always get same odds
        import hashlib
        
        # Create a consistent seed from player names (sorted to ensure order independence)
        names_sorted = sorted([player1_name.lower(), player2_name.lower()])
        match_key = f"{names_sorted[0]}_{names_sorted[1]}"
        hash_value = int(hashlib.md5(match_key.encode()).hexdigest(), 16)
        
        # Use hash to generate deterministic "random" odds between 1.2 and 3.5
        # This ensures same players always get same odds
        base_odds = round(1.2 + (hash_value % 2300) / 1000, 2)  # Range: 1.2 to 3.5
        
        # Assign odds based on which player comes first alphabetically
        if player1_name.lower() == names_sorted[0]:
            p1_odds = base_odds
            p2_odds = round(1 / ((1/base_odds) + 0.05), 2)  # Add margin for bookmaker
        else:
            p2_odds = base_odds
            p1_odds = round(1 / ((1/base_odds) + 0.05), 2)  # Add margin for bookmaker
        
        return {
            "player1": {
                "name": player1_name,
                "odds": p1_odds,
                "implied_prob": round(1 / p1_odds, 4),
                "bookmakers": ["bet365", "draftkings"],
                "all_odds": [{"odds": p1_odds, "bookmaker": "bet365"}]
            },
            "player2": {
                "name": player2_name,
                "odds": p2_odds,
                "implied_prob": round(1 / p2_odds, 4),
                "bookmakers": ["bet365", "draftkings"],
                "all_odds": [{"odds": p2_odds, "bookmaker": "bet365"}]
            },
            "bookmakers": ["bet365", "draftkings"],
            "timestamp": datetime.now().isoformat(),
            "note": "Mock data - replace with real API"
        }
    
    def _generate_odds_from_predictions(self, player1_name: str, player2_name: str, 
                                       predictions: Dict[str, float]) -> Dict:
        """
        Generate realistic odds from model predictions.
        IMPORTANT: This simulates bookmaker odds by adding variance to model predictions.
        For real betting, you MUST use actual bookmaker odds from an API.
        
        This function simulates a bookmaker who:
        1. Has a similar but different opinion than the model
        2. Adds a margin (6%) for profit
        3. May slightly misprice the match (creating value opportunities)
        
        Args:
            player1_name: Name of player 1
            player2_name: Name of player 2
            predictions: Dict mapping model names to player1 win probability (0-1)
        
        Returns:
            Odds dictionary with realistic odds based on predictions
        """
        # Use Random Forest if available, otherwise average all predictions
        if "random_forest" in predictions and predictions["random_forest"] is not None:
            model_p1_prob = predictions["random_forest"]
        else:
            # Average all available predictions
            valid_probs = [p for p in predictions.values() if p is not None]
            if valid_probs:
                model_p1_prob = sum(valid_probs) / len(valid_probs)
            else:
                # Fallback to 50/50 if no predictions
                model_p1_prob = 0.5
        
        # Simulate bookmaker having slightly different opinion (add variance)
        # Bookmakers may disagree with models, creating value opportunities
        import random
        # Use deterministic hash for consistency, but create variance
        import hashlib
        hash_seed = int(hashlib.md5(f"{player1_name}_{player2_name}".encode()).hexdigest()[:8], 16)
        random.seed(hash_seed)
        
        # Bookmaker's opinion: model_prob ± 3-8% variance (simulates mispricing)
        variance = random.uniform(-0.08, 0.08)  # ±8% max difference
        bookmaker_p1_prob = model_p1_prob + variance
        
        # Clamp to reasonable range (10% to 90%)
        bookmaker_p1_prob = max(0.10, min(0.90, bookmaker_p1_prob))
        bookmaker_p2_prob = 1 - bookmaker_p1_prob
        
        # Add bookmaker margin (5-7%) to make odds realistic
        # Bookmakers add margin so they profit regardless of outcome
        margin = 0.06  # 6% margin
        
        # Calculate fair odds (before margin) based on bookmaker's opinion
        # Fair odds = 1 / probability
        p1_fair_odds = 1 / bookmaker_p1_prob if bookmaker_p1_prob > 0 else 10.0
        p2_fair_odds = 1 / bookmaker_p2_prob if bookmaker_p2_prob > 0 else 10.0
        
        # Apply margin: odds_with_margin = fair_odds / (1 - margin)
        # This increases the odds slightly, making the bookmaker's implied probability > 100%
        p1_odds = round(p1_fair_odds / (1 - margin), 2)
        p2_odds = round(p2_fair_odds / (1 - margin), 2)
        
        # Ensure odds are in reasonable range (1.01 to 50.0)
        p1_odds = max(1.01, min(p1_odds, 50.0))
        p2_odds = max(1.01, min(p2_odds, 50.0))
        
        return {
            "player1": {
                "name": player1_name,
                "odds": p1_odds,
                "implied_prob": round(1 / p1_odds, 4),
                "bookmakers": ["bet365", "draftkings"],
                "all_odds": [{"odds": p1_odds, "bookmaker": "bet365"}]
            },
            "player2": {
                "name": player2_name,
                "odds": p2_odds,
                "implied_prob": round(1 / p2_odds, 4),
                "bookmakers": ["bet365", "draftkings"],
                "all_odds": [{"odds": p2_odds, "bookmaker": "bet365"}]
            },
            "bookmakers": ["bet365", "draftkings"],
            "timestamp": datetime.now().isoformat(),
            "note": "⚠️ MOCK DATA - Generated from model predictions with simulated variance. DO NOT USE FOR REAL BETTING. Use actual bookmaker odds from API.",
            "is_mock": True
        }
    
    def _fetch_sportradar(self, player1_name: str, player2_name: str) -> Optional[Dict]:
        """Fetch odds from Sportradar API (requires subscription)."""
        # Placeholder for Sportradar implementation
        raise NotImplementedError("Sportradar integration not yet implemented")


class ValueBetCalculator:
    """Calculate value bets by comparing model predictions to betting odds."""
    
    @staticmethod
    def calculate_value(predicted_prob: float, odds: float) -> Dict:
        """
        Calculate value and expected value for a bet.
        
        Args:
            predicted_prob: Your model's predicted probability (0-1)
            odds: Decimal odds from bookmaker
        
        Returns:
            Dictionary with value metrics
        """
        implied_prob = 1 / odds
        value = predicted_prob - implied_prob  # Positive = value bet
        value_percent = value * 100
        
        # Expected Value (EV) = (Probability × Odds × Stake) - Stake
        # Simplified: EV = (predicted_prob × odds) - 1
        expected_value = (predicted_prob * odds) - 1
        expected_value_percent = expected_value * 100
        
        # Kelly Criterion: (Probability × Odds - 1) / (Odds - 1)
        # Optimal bet size as fraction of bankroll
        if odds > 1:
            kelly_fraction = (predicted_prob * odds - 1) / (odds - 1)
        else:
            kelly_fraction = 0
        
        # Clamp Kelly to reasonable range (0-0.25 = 25% max)
        kelly_fraction = max(0, min(kelly_fraction, 0.25))
        
        return {
            "value": round(value, 4),
            "value_percent": round(value_percent, 2),
            "expected_value": round(expected_value, 4),
            "expected_value_percent": round(expected_value_percent, 2),
            "kelly_fraction": round(kelly_fraction, 4),
            "kelly_percent": round(kelly_fraction * 100, 2),
            "is_value_bet": value > 0,
            "predicted_prob": round(predicted_prob, 4),
            "implied_prob": round(implied_prob, 4),
            "odds": odds
        }
    
    @staticmethod
    def calculate_best_bet(model_predictions: Dict[str, float], 
                          odds_data: Dict) -> Dict:
        """
        Compare all model predictions to odds and find best value bets.
        
        Args:
            model_predictions: Dict with model names and probabilities for player1
            odds_data: Odds data from OddsFetcher
        
        Returns:
            Analysis of value bets
        """
        p1_odds = odds_data["player1"]["odds"]
        p2_odds = odds_data["player2"]["odds"]
        
        results = {
            "player1_values": {},
            "player2_values": {},
            "recommendations": []
        }
        
        # Calculate value for each model prediction
        for model_name, p1_prob in model_predictions.items():
            if p1_prob is None:
                continue
            
            p2_prob = 1 - p1_prob
            
            # Value for betting on player 1
            p1_value = ValueBetCalculator.calculate_value(p1_prob, p1_odds)
            results["player1_values"][model_name] = p1_value
            
            # Value for betting on player 2
            p2_value = ValueBetCalculator.calculate_value(p2_prob, p2_odds)
            results["player2_values"][model_name] = p2_value
            
            # Determine recommendation
            if p1_value["is_value_bet"] and p1_value["value_percent"] > p2_value.get("value_percent", -100):
                results["recommendations"].append({
                    "model": model_name,
                    "bet_on": odds_data["player1"]["name"],
                    "odds": p1_odds,
                    "value_percent": p1_value["value_percent"],
                    "kelly_percent": p1_value["kelly_percent"],
                    "expected_value_percent": p1_value["expected_value_percent"]
                })
            elif p2_value["is_value_bet"]:
                results["recommendations"].append({
                    "model": model_name,
                    "bet_on": odds_data["player2"]["name"],
                    "odds": p2_odds,
                    "value_percent": p2_value["value_percent"],
                    "kelly_percent": p2_value["kelly_percent"],
                    "expected_value_percent": p2_value["expected_value_percent"]
                })
        
        # Sort recommendations by value
        results["recommendations"].sort(key=lambda x: x["value_percent"], reverse=True)
        
        return results


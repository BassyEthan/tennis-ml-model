#!/usr/bin/env python3
"""
Test for framing leakage - check if trade decisions are invariant to which player Kalshi asks about.

For each match:
1. Pretend Kalshi asked about the other player
2. Recompute YES/NO and EV
3. Ensure chosen trade & EV are unchanged

If the result changes, there's still framing leakage.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.trading.kalshi_client import KalshiClient, Environment
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor
from config.settings import (
    KALSHI_ACCESS_KEY, KALSHI_PRIVATE_KEY_PATH, KALSHI_PRIVATE_KEY,
    KALSHI_BASE_URL, KALSHI_USE_PRODUCTION, RAW_DATA_DIR, MODELS_DIR
)

def compute_ev_for_side(model_prob, kalshi_prob, use_yes_side=True, yes_odds=None, no_odds=None):
    """
    Compute expected value for a given side.
    
    Args:
        model_prob: Model's probability for the outcome we're betting on
        kalshi_prob: Kalshi's probability for the outcome we're betting on
        use_yes_side: If True, betting YES (outcome happens), else betting NO (outcome doesn't happen)
        yes_odds: Decimal odds for YES (return if win)
        no_odds: Decimal odds for NO (return if win)
    """
    if use_yes_side:
        # Betting YES: win if outcome happens (probability = model_prob)
        if yes_odds is not None and yes_odds > 0:
            return (model_prob * yes_odds) - 1.0
        else:
            return (model_prob / kalshi_prob) - 1.0 if kalshi_prob > 0 else 0.0
    else:
        # Betting NO: win if outcome doesn't happen (probability = 1 - model_prob)
        if no_odds is not None and no_odds > 0:
            return ((1.0 - model_prob) * no_odds) - 1.0
        else:
            no_prob = 1.0 - kalshi_prob
            return ((1.0 - model_prob) / no_prob) - 1.0 if no_prob > 0 else 0.0

def flip_market_analysis(analysis):
    """
    Flip the market to pretend Kalshi asked about the other player.
    Returns a new analysis dict with flipped perspective.
    """
    # Get raw probabilities (these don't change)
    raw_p1_prob = analysis.get("raw_model_probability_p1")
    raw_p2_prob = analysis.get("raw_model_probability_p2")
    if raw_p1_prob is None or raw_p2_prob is None:
        return None
    
    # Current analysis assumes Kalshi asked about one player
    # model_prob is the probability for the asked player
    current_model_prob = analysis.get("model_probability")
    current_kalshi_prob = analysis.get("kalshi_probability")
    
    # Determine which player was asked about
    # If model_prob is close to raw_p1_prob, they asked about p1
    # If model_prob is close to raw_p2_prob, they asked about p2
    is_p1_market = abs(current_model_prob - raw_p1_prob) < abs(current_model_prob - raw_p2_prob)
    
    # Flip: if they asked about p1, now they ask about p2 (and vice versa)
    if is_p1_market:
        # Was asking about p1, now asking about p2
        flipped_model_prob = raw_p2_prob  # Model prob for p2
        flipped_kalshi_prob = 1.0 - current_kalshi_prob  # Kalshi prob for p2
    else:
        # Was asking about p2, now asking about p1
        flipped_model_prob = raw_p1_prob  # Model prob for p1
        flipped_kalshi_prob = 1.0 - current_kalshi_prob  # Kalshi prob for p1
    
    # Get odds - when flipping, we need to flip the odds too
    # Original: YES on p1 uses yes_odds, NO on p1 uses no_odds
    # Flipped: YES on p2 should use original NO odds (since NO on p1 = YES on p2)
    # Flipped: NO on p2 should use original YES odds (since YES on p1 = NO on p2)
    kalshi_odds = analysis.get("kalshi_odds", {})
    original_yes_odds = kalshi_odds.get("yes_odds")
    original_no_odds = kalshi_odds.get("no_odds")
    
    # Flip odds: YES on flipped player = NO on original, NO on flipped = YES on original
    flipped_yes_odds = original_no_odds  # YES on p2 uses NO odds from p1 market
    flipped_no_odds = original_yes_odds  # NO on p2 uses YES odds from p1 market
    
    # Compute value and EV for flipped perspective
    flipped_value = flipped_model_prob - flipped_kalshi_prob
    
    # Determine trade side for flipped
    if flipped_value > 0.05:
        flipped_trade_side = "yes"
        # Betting YES on flipped player: use flipped YES odds (original NO odds)
        flipped_ev = compute_ev_for_side(flipped_model_prob, flipped_kalshi_prob, True, flipped_yes_odds, flipped_no_odds)
    elif flipped_value < -0.05:
        flipped_trade_side = "no"
        # Betting NO on flipped player: use flipped NO odds (original YES odds)
        flipped_ev = compute_ev_for_side(flipped_model_prob, flipped_kalshi_prob, False, flipped_yes_odds, flipped_no_odds)
    else:
        flipped_trade_side = None
        flipped_ev = compute_ev_for_side(flipped_model_prob, flipped_kalshi_prob, True, flipped_yes_odds, flipped_no_odds)
    
    return {
        "flipped_model_prob": flipped_model_prob,
        "flipped_kalshi_prob": flipped_kalshi_prob,
        "flipped_value": flipped_value,
        "flipped_trade_side": flipped_trade_side,
        "flipped_ev": flipped_ev,
        "was_p1_market": is_p1_market,
    }

def main():
    print("=" * 80)
    print("TESTING FRAMING SYMMETRY")
    print("=" * 80)
    print()
    print("For each match, we flip the question and check if trade/EV are unchanged.")
    print()
    
    # Initialize components
    print("Initializing components...")
    env = Environment.PROD if KALSHI_USE_PRODUCTION else Environment.DEMO
    client = KalshiClient(
        access_key=KALSHI_ACCESS_KEY,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        environment=env,
    )
    
    player_db = PlayerStatsDB(raw_data_dir=str(RAW_DATA_DIR))
    predictor = MatchPredictor(models_dir=str(MODELS_DIR))
    analyzer = KalshiMarketAnalyzer(
        kalshi_client=client,
        player_db=player_db,
        predictor=predictor,
    )
    
    print("Fetching markets...")
    tradable, all_analyses = analyzer.scan_markets(
        limit=200,
        min_value=0.0,
        min_ev=0.0,
        debug=False,
        show_all=True,
        max_hours_ahead=48,
        min_volume=500,
    )
    
    print(f"\nAnalyzed {len(all_analyses)} markets")
    print(f"Found {len(tradable)} tradable opportunities")
    print()
    
    # Test framing symmetry on tradable opportunities
    print("=" * 80)
    print("TESTING FRAMING SYMMETRY ON TRADABLE OPPORTUNITIES")
    print("=" * 80)
    print()
    
    symmetric = 0
    asymmetric = 0
    issues = []
    
    for i, analysis in enumerate(tradable, 1):
        if not analysis.get("tradable", False):
            continue
        
        title = analysis.get("title", "Unknown")
        players = analysis.get("matched_players", ("", ""))
        players_str = f"{players[0]} vs {players[1]}" if players[0] and players[1] else "Unknown"
        
        original_trade_side = analysis.get("trade_side", "")
        original_value = analysis.get("value", 0)
        original_ev = analysis.get("expected_value", 0)
        original_model_prob = analysis.get("model_probability", 0)
        original_kalshi_prob = analysis.get("kalshi_probability", 0)
        original_trade_value = analysis.get("trade_value", 0)
        
        # Flip the market
        flipped = flip_market_analysis(analysis)
        if flipped is None:
            continue
        
        flipped_trade_side = flipped["flipped_trade_side"]
        flipped_value = flipped["flipped_value"]
        flipped_ev = flipped["flipped_ev"]
        flipped_trade_value = abs(flipped_value) if flipped_value else 0
        
        # Check if trade side flips correctly
        # If original was YES on p1, flipped should be NO on p2 (or vice versa)
        # Actually, both should recommend the same underlying bet:
        # - YES on p1 is equivalent to NO on p2
        # - NO on p1 is equivalent to YES on p2
        
        # The trade_value should be the same (absolute value of edge)
        # The EV should be the same (same underlying bet, just framed differently)
        
        trade_value_matches = abs(original_trade_value - flipped_trade_value) < 0.001
        ev_matches = abs(original_ev - flipped_ev) < 0.01  # Allow small floating point differences
        
        # Check if we're betting on the same player (regardless of YES/NO framing)
        # Original: trade_side YES on asked_player means bet on asked_player
        # Original: trade_side NO on asked_player means bet on opponent
        # Flipped: trade_side YES on other_player means bet on other_player
        # Flipped: trade_side NO on other_player means bet on original_asked_player
        # So:
        # - Original YES on p1 = Flipped NO on p2 (both bet on p1) ✓
        # - Original NO on p1 = Flipped YES on p2 (both bet on p2) ✓
        
        trade_sides_equivalent = (
            (original_trade_side == "yes" and flipped_trade_side == "no") or
            (original_trade_side == "no" and flipped_trade_side == "yes")
        )
        
        is_symmetric = trade_value_matches and ev_matches and trade_sides_equivalent
        
        if is_symmetric:
            symmetric += 1
        else:
            asymmetric += 1
            issues.append({
                "title": title,
                "players": players_str,
                "original_side": original_trade_side,
                "flipped_side": flipped_trade_side,
                "original_trade_value": original_trade_value,
                "flipped_trade_value": flipped_trade_value,
                "original_ev": original_ev,
                "flipped_ev": flipped_ev,
                "trade_value_match": trade_value_matches,
                "ev_match": ev_matches,
                "sides_equivalent": trade_sides_equivalent,
            })
        
        # Print details
        if not is_symmetric or i <= 5:  # Always show first 5, and any issues
            print(f"[{i}/{len(tradable)}] {title[:60]}")
            print(f"  Match: {players_str}")
            print(f"  Original: {original_trade_side.upper()} | Value: {original_trade_value:.1%} | EV: {original_ev:.1%}")
            print(f"  Flipped:  {flipped_trade_side.upper() if flipped_trade_side else 'NONE'} | Value: {flipped_trade_value:.1%} | EV: {flipped_ev:.1%}")
            if not is_symmetric:
                print(f"  ❌ ASYMMETRIC: trade_value_match={trade_value_matches}, ev_match={ev_matches}, sides_equivalent={trade_sides_equivalent}")
            else:
                print(f"  ✅ SYMMETRIC")
            print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    total_tested = symmetric + asymmetric
    if total_tested > 0:
        print(f"Total tested: {total_tested}")
        print(f"  - Symmetric: {symmetric} ({symmetric/total_tested*100:.1f}%)")
        print(f"  - Asymmetric (framing leakage): {asymmetric} ({asymmetric/total_tested*100:.1f}%)")
        print()
        
        if asymmetric > 0:
            print("⚠️  FRAMING LEAKAGE DETECTED!")
            print()
            print("Issues found:")
            for issue in issues[:10]:  # Show first 10 issues
                print(f"  - {issue['title'][:50]}")
                print(f"    Original: {issue['original_side']} (value: {issue['original_trade_value']:.1%}, EV: {issue['original_ev']:.1%})")
                print(f"    Flipped:  {issue['flipped_side']} (value: {issue['flipped_trade_value']:.1%}, EV: {issue['flipped_ev']:.1%})")
                print(f"    Trade value match: {issue['trade_value_match']}, EV match: {issue['ev_match']}, Sides equivalent: {issue['sides_equivalent']}")
                print()
        else:
            print("✅ All trades are symmetric - no framing leakage detected!")
            print("   Trade decisions are invariant to which player Kalshi asks about.")
    print()

if __name__ == '__main__':
    main()


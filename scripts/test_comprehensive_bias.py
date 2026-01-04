#!/usr/bin/env python3
"""
Comprehensive test to verify the model doesn't have systematic biases.
Tests:
1. Favorite vs Underdog bias
2. YES vs NO trade side bias
3. Model prediction distribution
4. Value edge distribution
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

def main():
    print("=" * 80)
    print("COMPREHENSIVE BIAS TESTING")
    print("=" * 80)
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
    # Get a larger sample of markets
    tradable, all_analyses = analyzer.scan_markets(
        limit=200,
        min_value=0.0,  # Lower threshold to see all opportunities
        min_ev=0.0,
        debug=False,
        show_all=True,
        max_hours_ahead=48,
        min_volume=500,  # Lower volume threshold to get more samples
    )
    
    print(f"\nAnalyzed {len(all_analyses)} markets")
    print(f"Found {len(tradable)} tradable opportunities")
    print()
    
    if not tradable:
        print("❌ No tradable opportunities found. Cannot test for bias.")
        return
    
    # Test 1: Favorite vs Underdog bias
    print("=" * 80)
    print("TEST 1: FAVORITE VS UNDERDOG BIAS")
    print("=" * 80)
    print()
    
    favorite_bets = 0
    underdog_bets = 0
    yes_trades = 0
    no_trades = 0
    
    for opp in tradable:
        kalshi_prob = opp.get('kalshi_probability', 0)
        trade_side = opp.get('trade_side', '')
        
        asked_player_is_favorite = kalshi_prob > 0.5
        
        if trade_side == "yes":
            yes_trades += 1
            betting_on_favorite = asked_player_is_favorite
        elif trade_side == "no":
            no_trades += 1
            betting_on_favorite = not asked_player_is_favorite
        else:
            continue
        
        if betting_on_favorite:
            favorite_bets += 1
        else:
            underdog_bets += 1
    
    print(f"Total tradable opportunities: {len(tradable)}")
    print(f"  - Betting on favorites: {favorite_bets} ({favorite_bets/len(tradable)*100:.1f}%)")
    print(f"  - Betting on underdogs: {underdog_bets} ({underdog_bets/len(tradable)*100:.1f}%)")
    print()
    
    # Test 2: YES vs NO trade side bias
    print("=" * 80)
    print("TEST 2: YES VS NO TRADE SIDE BIAS")
    print("=" * 80)
    print()
    
    print(f"Total trades: {len(tradable)}")
    print(f"  - YES trades (bet on asked player): {yes_trades} ({yes_trades/len(tradable)*100:.1f}%)")
    print(f"  - NO trades (bet against asked player): {no_trades} ({no_trades/len(tradable)*100:.1f}%)")
    print()
    
    if yes_trades > 0 and no_trades > 0:
        print("✅ Model uses both YES and NO trades - no systematic bias.")
    elif yes_trades == len(tradable):
        print("⚠️  WARNING: Model ONLY uses YES trades - potential bias.")
    elif no_trades == len(tradable):
        print("⚠️  WARNING: Model ONLY uses NO trades - potential bias.")
    print()
    
    # Test 3: Model prediction distribution
    print("=" * 80)
    print("TEST 3: MODEL PREDICTION DISTRIBUTION")
    print("=" * 80)
    print()
    
    model_probs = [opp.get('model_probability', 0) for opp in tradable]
    kalshi_probs = [opp.get('kalshi_probability', 0) for opp in tradable]
    
    if model_probs:
        avg_model_prob = sum(model_probs) / len(model_probs)
        avg_kalshi_prob = sum(kalshi_probs) / len(kalshi_probs)
        
        print(f"Average model probability: {avg_model_prob:.1%}")
        print(f"Average Kalshi probability: {avg_kalshi_prob:.1%}")
        print(f"Difference: {avg_model_prob - avg_kalshi_prob:+.1%}")
        print()
        
        # Distribution by probability ranges
        ranges = {
            '<30%': 0,
            '30-40%': 0,
            '40-50%': 0,
            '50-60%': 0,
            '60-70%': 0,
            '>70%': 0,
        }
        
        for prob in model_probs:
            if prob < 0.3:
                ranges['<30%'] += 1
            elif prob < 0.4:
                ranges['30-40%'] += 1
            elif prob < 0.5:
                ranges['40-50%'] += 1
            elif prob < 0.6:
                ranges['50-60%'] += 1
            elif prob < 0.7:
                ranges['60-70%'] += 1
            else:
                ranges['>70%'] += 1
        
        print("Model probability distribution:")
        for range_name, count in ranges.items():
            if count > 0:
                print(f"  {range_name}: {count} ({count/len(model_probs)*100:.1f}%)")
        print()
    
    # Test 4: Value edge distribution
    print("=" * 80)
    print("TEST 4: VALUE EDGE DISTRIBUTION")
    print("=" * 80)
    print()
    
    values = [opp.get('value', 0) for opp in tradable]
    if values:
        avg_value = sum(values) / len(values)
        max_value = max(values)
        min_value = min(values)
        
        print(f"Average edge: {avg_value:+.1%}")
        print(f"Max edge: {max_value:+.1%}")
        print(f"Min edge: {min_value:+.1%}")
        print()
        
        # Count positive vs negative edges (should all be positive for tradable)
        positive_edges = sum(1 for v in values if v > 0)
        negative_edges = sum(1 for v in values if v <= 0)
        
        print(f"Positive edges: {positive_edges} ({positive_edges/len(values)*100:.1f}%)")
        print(f"Negative edges: {negative_edges} ({negative_edges/len(values)*100:.1f}%)")
        print()
    
    # Test 5: Check if model always predicts favorites
    print("=" * 80)
    print("TEST 5: MODEL PREDICTION VS KALSHI FAVORITE")
    print("=" * 80)
    print()
    
    model_agrees_with_kalshi_favorite = 0
    model_disagrees_with_kalshi_favorite = 0
    
    for opp in tradable:
        kalshi_prob = opp.get('kalshi_probability', 0)
        model_prob = opp.get('model_probability', 0)
        
        kalshi_favorite = kalshi_prob > 0.5
        model_favorite = model_prob > 0.5
        
        if kalshi_favorite == model_favorite:
            model_agrees_with_kalshi_favorite += 1
        else:
            model_disagrees_with_kalshi_favorite += 1
    
    print(f"Model agrees with Kalshi favorite: {model_agrees_with_kalshi_favorite} ({model_agrees_with_kalshi_favorite/len(tradable)*100:.1f}%)")
    print(f"Model disagrees with Kalshi favorite: {model_disagrees_with_kalshi_favorite} ({model_disagrees_with_kalshi_favorite/len(tradable)*100:.1f}%)")
    print()
    
    if model_agrees_with_kalshi_favorite / len(tradable) > 0.9:
        print("⚠️  WARNING: Model almost always agrees with Kalshi on favorites.")
        print("   This could indicate the model is just following market consensus.")
    else:
        print("✅ Model shows independent thinking - doesn't always agree with Kalshi.")
    print()
    
    # Final Summary
    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    print()
    
    issues = []
    
    if favorite_bets / len(tradable) > 0.9:
        issues.append("Model heavily biased towards favorites")
    if yes_trades == len(tradable) or no_trades == len(tradable):
        issues.append("Model only uses one trade side (YES or NO)")
    if model_agrees_with_kalshi_favorite / len(tradable) > 0.9:
        issues.append("Model almost always agrees with Kalshi favorites")
    
    if issues:
        print("⚠️  POTENTIAL ISSUES FOUND:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("✅ No significant biases detected!")
        print("   The model shows:")
        print(f"   - Balanced favorite/underdog betting ({favorite_bets/len(tradable)*100:.1f}% favorites, {underdog_bets/len(tradable)*100:.1f}% underdogs)")
        if yes_trades > 0 and no_trades > 0:
            print(f"   - Uses both YES and NO trades ({yes_trades} YES, {no_trades} NO)")
        print(f"   - Independent predictions ({model_disagrees_with_kalshi_favorite/len(tradable)*100:.1f}% disagree with Kalshi favorites)")
    
    print()

if __name__ == '__main__':
    main()


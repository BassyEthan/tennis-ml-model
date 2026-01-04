#!/usr/bin/env python3
"""
Test script to verify the model doesn't always pick favorites.
Analyzes multiple markets and checks if we're finding value on underdogs too.
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
    print("TESTING FOR FAVORITE BIAS")
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
        limit=100,
        min_value=0.0,  # Lower threshold to see all opportunities
        min_ev=0.0,
        debug=False,
        show_all=True,
        max_hours_ahead=48,
        min_volume=1000,
    )
    
    print(f"\nAnalyzed {len(all_analyses)} markets")
    print(f"Found {len(tradable)} tradable opportunities")
    print()
    
    # Analyze tradable opportunities
    if not tradable:
        print("❌ No tradable opportunities found. Cannot test for bias.")
        return
    
    print("=" * 80)
    print("ANALYZING TRADABLE OPPORTUNITIES")
    print("=" * 80)
    print()
    
    favorite_bets = 0
    underdog_bets = 0
    unclear_bets = 0
    
    favorite_details = []
    underdog_details = []
    
    for i, opp in enumerate(tradable, 1):
        kalshi_prob = opp.get('kalshi_probability', 0)
        model_prob = opp.get('model_probability', 0)
        value = opp.get('value', 0)
        trade_side = opp.get('trade_side', '')
        bet_on_player = opp.get('bet_on_player', 'Unknown')
        players = opp.get('matched_players', ('', ''))
        title = opp.get('title', 'Unknown')
        
        # Determine which player is the favorite (higher Kalshi probability)
        # If Kalshi is asking "Will Player X win" and yes_prob > 50%, Player X is the favorite
        # If Kalshi is asking "Will Player X win" and yes_prob < 50%, Player X is the underdog
        asked_player_is_favorite = kalshi_prob > 0.5
        
        # Check if we're betting on the favorite
        # If trade_side is "yes", we're betting on the asked player (YES = bet on asked player)
        # If trade_side is "no", we're betting against the asked player (NO = bet on opponent)
        if trade_side == "yes":
            betting_on_favorite = asked_player_is_favorite
        elif trade_side == "no":
            betting_on_favorite = not asked_player_is_favorite
        else:
            betting_on_favorite = None
        
        if betting_on_favorite is None:
            unclear_bets += 1
        elif betting_on_favorite:
            favorite_bets += 1
            favorite_details.append({
                'title': title,
                'players': players,
                'bet_on': bet_on_player,
                'kalshi_prob': kalshi_prob,
                'model_prob': model_prob,
                'value': value,
                'trade_side': trade_side,
            })
        else:
            # We're betting on the underdog
            underdog_bets += 1
            underdog_details.append({
                'title': title,
                'players': players,
                'bet_on': bet_on_player,
                'kalshi_prob': kalshi_prob,
                'model_prob': model_prob,
                'value': value,
                'trade_side': trade_side,
            })
        
        # Print details
        players_str = f"{players[0]} vs {players[1]}" if players[0] and players[1] else "Unknown"
        if betting_on_favorite is None:
            favorite_str = "UNCLEAR"
        elif betting_on_favorite:
            favorite_str = "FAVORITE"
        else:
            favorite_str = "UNDERDOG"
        print(f"[{i}/{len(tradable)}] {title[:60]}")
        print(f"  Match: {players_str}")
        print(f"  Betting on: {bet_on_player} ({favorite_str} - Kalshi: {kalshi_prob:.1%})")
        print(f"  Model: {model_prob:.1%} | Kalshi: {kalshi_prob:.1%} | Edge: {value:+.1%}")
        print(f"  Trade side: {trade_side}")
        print()
    
    # Summary statistics
    print("=" * 80)
    print("BIAS ANALYSIS SUMMARY")
    print("=" * 80)
    print()
    print(f"Total tradable opportunities: {len(tradable)}")
    print(f"  - Betting on favorites: {favorite_bets} ({favorite_bets/len(tradable)*100:.1f}%)")
    print(f"  - Betting on underdogs: {underdog_bets} ({underdog_bets/len(tradable)*100:.1f}%)")
    print(f"  - Unclear: {unclear_bets} ({unclear_bets/len(tradable)*100:.1f}%)")
    print()
    
    if favorite_bets > 0:
        print("FAVORITE BETS (Top 5):")
        for i, det in enumerate(favorite_details[:5], 1):
            players_str = f"{det['players'][0]} vs {det['players'][1]}" if det['players'][0] and det['players'][1] else "Unknown"
            print(f"  {i}. {det['title'][:50]}")
            print(f"     Bet on: {det['bet_on']} (Kalshi: {det['kalshi_prob']:.1%}, Model: {det['model_prob']:.1%}, Edge: {det['value']:+.1%})")
        print()
    
    if underdog_bets > 0:
        print("UNDERDOG BETS (Top 5):")
        for i, det in enumerate(underdog_details[:5], 1):
            players_str = f"{det['players'][0]} vs {det['players'][1]}" if det['players'][0] and det['players'][1] else "Unknown"
            print(f"  {i}. {det['title'][:50]}")
            print(f"     Bet on: {det['bet_on']} (Kalshi: {det['kalshi_prob']:.1%}, Model: {det['model_prob']:.1%}, Edge: {det['value']:+.1%})")
        print()
    else:
        print("⚠️  WARNING: No underdog bets found! This suggests potential bias.")
        print()
    
    # Additional analysis: Check value distribution
    print("=" * 80)
    print("VALUE DISTRIBUTION ANALYSIS")
    print("=" * 80)
    print()
    
    # Group by Kalshi probability ranges
    prob_ranges = {
        'Heavy Favorite (>70%)': [],
        'Moderate Favorite (60-70%)': [],
        'Slight Favorite (50-60%)': [],
        'Slight Underdog (40-50%)': [],
        'Moderate Underdog (30-40%)': [],
        'Heavy Underdog (<30%)': [],
    }
    
    for opp in tradable:
        kalshi_prob = opp.get('kalshi_probability', 0)
        value = opp.get('value', 0)
        
        if kalshi_prob > 0.7:
            prob_ranges['Heavy Favorite (>70%)'].append(value)
        elif kalshi_prob > 0.6:
            prob_ranges['Moderate Favorite (60-70%)'].append(value)
        elif kalshi_prob > 0.5:
            prob_ranges['Slight Favorite (50-60%)'].append(value)
        elif kalshi_prob > 0.4:
            prob_ranges['Slight Underdog (40-50%)'].append(value)
        elif kalshi_prob > 0.3:
            prob_ranges['Moderate Underdog (30-40%)'].append(value)
        else:
            prob_ranges['Heavy Underdog (<30%)'].append(value)
    
    for range_name, values in prob_ranges.items():
        if values:
            avg_value = sum(values) / len(values)
            print(f"{range_name}: {len(values)} bets, avg edge: {avg_value:+.1%}")
    
    print()
    
    # Final verdict
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    print()
    
    if underdog_bets == 0:
        print("❌ CRITICAL: Model is ONLY betting on favorites!")
        print("   This suggests a systematic bias. The model may not be finding value on underdogs.")
    elif underdog_bets < len(tradable) * 0.2:
        print("⚠️  WARNING: Model is heavily biased towards favorites.")
        print(f"   Only {underdog_bets/len(tradable)*100:.1f}% of bets are on underdogs.")
        print("   Consider reviewing the model's predictions for underdog opportunities.")
    elif favorite_bets / len(tradable) > 0.8:
        print("⚠️  CAUTION: Model shows preference for favorites ({favorite_bets/len(tradable)*100:.1f}%).")
        print("   This could be normal if favorites are genuinely undervalued, but monitor closely.")
    else:
        print("✅ Model shows balanced betting between favorites and underdogs.")
        print(f"   Favorites: {favorite_bets/len(tradable)*100:.1f}%, Underdogs: {underdog_bets/len(tradable)*100:.1f}%")
    
    print()

if __name__ == '__main__':
    main()


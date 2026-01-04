#!/usr/bin/env python3
"""
Test to see why we're not getting NO trades.
Checks all analyzed markets, not just tradable ones.
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
    print("TESTING FOR NO TRADES")
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
    # Get all markets, not just tradable
    tradable, all_analyses = analyzer.scan_markets(
        limit=200,
        min_value=0.0,  # No minimum value
        min_ev=0.0,     # No minimum EV
        debug=False,
        show_all=True,
        max_hours_ahead=48,
        min_volume=500,
    )
    
    print(f"\nAnalyzed {len(all_analyses)} markets")
    print(f"Found {len(tradable)} tradable opportunities")
    print()
    
    # Analyze all markets for NO trade opportunities
    print("=" * 80)
    print("ANALYZING ALL MARKETS FOR NO TRADE OPPORTUNITIES")
    print("=" * 80)
    print()
    
    yes_opportunities = []
    no_opportunities = []
    no_trade_opportunities = []
    
    for analysis in all_analyses:
        if not analysis.get('tradable', False):
            continue
        
        trade_side = analysis.get('trade_side', '')
        value = analysis.get('value', 0)
        model_prob = analysis.get('model_probability', 0)
        kalshi_prob = analysis.get('kalshi_probability', 0)
        title = analysis.get('title', 'Unknown')
        players = analysis.get('matched_players', ('', ''))
        
        if trade_side == 'yes':
            yes_opportunities.append({
                'title': title,
                'players': players,
                'value': value,
                'model_prob': model_prob,
                'kalshi_prob': kalshi_prob,
            })
        elif trade_side == 'no':
            no_opportunities.append({
                'title': title,
                'players': players,
                'value': abs(value),
                'model_prob': model_prob,
                'kalshi_prob': kalshi_prob,
            })
        else:
            no_trade_opportunities.append({
                'title': title,
                'players': players,
                'value': value,
                'model_prob': model_prob,
                'kalshi_prob': kalshi_prob,
                'reason': analysis.get('reason', 'Unknown'),
            })
    
    print(f"Total tradable markets: {len(yes_opportunities) + len(no_opportunities) + len(no_trade_opportunities)}")
    print(f"  - YES opportunities: {len(yes_opportunities)}")
    print(f"  - NO opportunities: {len(no_opportunities)}")
    print(f"  - No trade (filtered out): {len(no_trade_opportunities)}")
    print()
    
    if no_opportunities:
        print("NO TRADE OPPORTUNITIES FOUND:")
        for i, opp in enumerate(no_opportunities[:10], 1):
            players_str = f"{opp['players'][0]} vs {opp['players'][1]}" if opp['players'][0] and opp['players'][1] else "Unknown"
            print(f"  {i}. {opp['title'][:60]}")
            print(f"     Match: {players_str}")
            print(f"     Model: {opp['model_prob']:.1%} | Kalshi: {opp['kalshi_prob']:.1%} | Edge: {opp['value']:+.1%}")
            print()
    else:
        print("❌ NO 'NO' TRADE OPPORTUNITIES FOUND")
        print()
        print("This means the model is not finding cases where:")
        print("  - Kalshi has OVERPRICED a player (model thinks lower probability)")
        print("  - We should bet AGAINST that player (NO trade)")
        print()
        print("Possible reasons:")
        print("  1. Market conditions: Kalshi may be systematically underpricing players")
        print("  2. Model bias: Model may be too optimistic (always predicting higher probabilities)")
        print("  3. Sample size: Not enough markets analyzed")
        print()
        
        # Check value distribution
        print("VALUE DISTRIBUTION (all tradable markets):")
        all_values = [opp['value'] for opp in yes_opportunities]
        if all_values:
            negative_values = [v for v in all_values if v < 0]
            positive_values = [v for v in all_values if v > 0]
            print(f"  Positive values: {len(positive_values)}")
            print(f"  Negative values: {len(negative_values)}")
            if negative_values:
                print(f"  Most negative: {min(negative_values):.1%}")
            print()
        
        # Check if model is systematically higher than Kalshi
        print("MODEL VS KALSHI COMPARISON:")
        model_probs = [opp['model_prob'] for opp in yes_opportunities]
        kalshi_probs = [opp['kalshi_prob'] for opp in yes_opportunities]
        if model_probs and kalshi_probs:
            avg_model = sum(model_probs) / len(model_probs)
            avg_kalshi = sum(kalshi_probs) / len(kalshi_probs)
            print(f"  Average model probability: {avg_model:.1%}")
            print(f"  Average Kalshi probability: {avg_kalshi:.1%}")
            print(f"  Difference: {avg_model - avg_kalshi:+.1%}")
            
            if avg_model > avg_kalshi + 0.1:
                print()
                print("⚠️  WARNING: Model is systematically predicting higher probabilities than Kalshi.")
                print("   This could indicate model optimism bias.")
            print()
    
    # Check filtered out opportunities
    if no_trade_opportunities:
        print("=" * 80)
        print("FILTERED OUT OPPORTUNITIES (would be tradable but below thresholds)")
        print("=" * 80)
        print()
        
        no_trade_with_negative_value = [opp for opp in no_trade_opportunities if opp['value'] < -0.05]
        if no_trade_with_negative_value:
            print(f"Found {len(no_trade_with_negative_value)} opportunities with negative value (would be NO trades):")
            for i, opp in enumerate(no_trade_with_negative_value[:5], 1):
                players_str = f"{opp['players'][0]} vs {opp['players'][1]}" if opp['players'][0] and opp['players'][1] else "Unknown"
                print(f"  {i}. {opp['title'][:60]}")
                print(f"     Match: {players_str}")
                print(f"     Model: {opp['model_prob']:.1%} | Kalshi: {opp['kalshi_prob']:.1%} | Edge: {opp['value']:+.1%}")
                print(f"     Reason filtered: {opp['reason']}")
                print()
        else:
            print("No filtered opportunities with negative value (NO trades).")
            print()

if __name__ == '__main__':
    main()


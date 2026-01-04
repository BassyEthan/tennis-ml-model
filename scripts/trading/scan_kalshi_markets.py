#!/usr/bin/env python3
"""
Scan Kalshi markets for tennis matches and identify value trading opportunities.

Usage:
    python scripts/trading/scan_kalshi_markets.py [--limit 100] [--min-value 0.05] [--min-ev 0.10]
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config.settings import RAW_DATA_DIR, MODELS_DIR
from src.trading.kalshi_client import KalshiClient
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor


def main():
    parser = argparse.ArgumentParser(description="Scan Kalshi markets for value trades")
    parser.add_argument("--limit", type=int, default=5000, help="Max markets to scan (default: 5000)")
    parser.add_argument("--min-value", type=float, default=0.05, 
                       help="Minimum value threshold (default: 0.05 = 5%%)")
    parser.add_argument("--min-ev", type=float, default=0.10,
                       help="Minimum expected value threshold (default: 0.10 = 10%%)")
    parser.add_argument("--event-ticker", type=str, default=None,
                       help="Filter by event ticker")
    parser.add_argument("--debug", action="store_true",
                       help="Print debug information about market fetching")
    parser.add_argument("--show-all", action="store_true",
                       help="Show all analyzed markets, not just tradable ones")
    parser.add_argument("--max-hours", type=int, default=48,
                       help="Maximum hours ahead to include markets (default: 48)")
    parser.add_argument("--min-volume", type=int, default=0,
                       help="Minimum market volume/pot in dollars (default: 0, no filter)")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Kalshi Tennis Market Scanner")
    print("=" * 70)
    print()
    
    # Initialize components
    print("Initializing components...")
    try:
        kalshi_client = KalshiClient()
        print("✅ Kalshi client initialized")
        
        player_db = PlayerStatsDB(raw_data_dir=str(RAW_DATA_DIR))
        print("✅ Player database loaded")
        
        predictor = MatchPredictor(models_dir=str(MODELS_DIR))
        print("✅ Prediction models loaded")
        
        analyzer = KalshiMarketAnalyzer(
            kalshi_client=kalshi_client,
            player_db=player_db,
            predictor=predictor
        )
        print("✅ Market analyzer initialized")
        print()
    except Exception as e:
        print(f"❌ Error initializing: {e}")
        return 1
    
    # Scan markets
    print(f"Scanning up to {args.limit} markets...")
    print(f"Minimum value threshold: {args.min_value * 100:.1f}%")
    print(f"Minimum EV threshold: {args.min_ev * 100:.1f}%")
    print(f"Minimum volume: ${args.min_volume:,}")
    print(f"Player database contains {len(player_db.name_to_id)} players")
    print()
    
    try:
        tradable, all_analyses = analyzer.scan_markets(
            limit=args.limit,
            min_value=args.min_value,
            min_ev=args.min_ev,
            debug=args.debug,
            show_all=args.show_all,
            max_hours_ahead=args.max_hours,
            min_volume=args.min_volume
        )
        
        # Display tradable opportunities
        if tradable:
            print(f"\n{'=' * 70}")
            print(f"💰 TRADABLE OPPORTUNITIES ({len(tradable)})")
            print(f"{'=' * 70}")
            
            for i, opp in enumerate(tradable, 1):
                volume_str = f"${opp.get('market_volume', 0):,.0f}" if opp.get('market_volume') else "Unknown"
                players = opp['matched_players']
                players_str = f"{players[0]} vs {players[1]}"
                
                # Determine which player we're betting on
                bet_on_player = opp.get('bet_on_player')
                if not bet_on_player:
                    # Fallback: use trade_side to determine
                    if opp.get('trade_side') == 'yes':
                        bet_on_player = players[0]  # Default to first player
                    else:
                        bet_on_player = players[1]
                
                print(f"\n   [{i}/{len(tradable)}] {opp['title']}")
                print(f"      Match: {players_str}")
                print(f"      Edge: {opp['value']:+.1%} | EV: {opp['expected_value']:+.1%} | Volume: {volume_str}")
                print(f"      Model Probability: {opp['model_probability']:.1%} | Kalshi Probability: {opp['kalshi_probability']:.1%}")
                kalshi_odds = opp.get('kalshi_odds', {})
                yes_price = kalshi_odds.get('yes_price', 0)
                no_price = kalshi_odds.get('no_price', 0)
                if yes_price and no_price:
                    print(f"      Kalshi Odds: YES @ {yes_price:.1f}¢ | NO @ {no_price:.1f}¢")
                print(f"      🎯 BET ON: {bet_on_player} @ {yes_price:.1f}¢")
                print(f"      Ticker: {opp['ticker']}")
        else:
            print(f"\n{'=' * 70}")
            print("⚠️  NO TRADABLE OPPORTUNITIES FOUND")
            print(f"{'=' * 70}")
        
        # Display all analyzed markets if requested
        if args.show_all and all_analyses:
            print()
            print("=" * 70)
            print(f"All Analyzed Markets ({len(all_analyses)} total)")
            print("=" * 70)
            print()
            
            for i, analysis in enumerate(all_analyses, 1):
                print(f"Market #{i}: {analysis.get('title', 'N/A')}")
                print(f"  Ticker: {analysis.get('ticker', 'N/A')}")
                
                if 'matched_players' in analysis and analysis['matched_players'][0]:
                    print(f"  Players: {analysis['matched_players'][0]} vs {analysis['matched_players'][1]}")
                
                if 'error' in analysis:
                    print(f"  Status: ERROR - {analysis.get('error', 'Unknown error')}")
                    print(f"  Reason: {analysis.get('reason', 'N/A')}")
                elif 'model_probability' in analysis:
                    print(f"  Model Probability: {analysis['model_probability']:.1%}")
                    print(f"  Kalshi Probability: {analysis['kalshi_probability']:.1%}")
                    print(f"  Value: {analysis['value']:.1%}")
                    print(f"  Expected Value: {analysis['expected_value']:.1%}")
                    print(f"  Tradable: {'YES' if analysis.get('tradable') else 'NO'}")
                    print(f"  Reason: {analysis.get('reason', 'N/A')}")
                else:
                    print(f"  Status: {analysis.get('error', 'Not analyzed')}")
                    print(f"  Reason: {analysis.get('reason', 'N/A')}")
                print()
        
        return 0
        
    except Exception as e:
        print(f"❌ Error scanning markets: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())


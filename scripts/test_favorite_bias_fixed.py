#!/usr/bin/env python3
"""
Fixed bias testing script with correct favorite/underdog classification.
Tests on both all_analyses (raw model behavior) and tradable (filtered behavior).
"""

import sys
from pathlib import Path
from collections import defaultdict

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

def classify_bet(opp):
    """Classify whether bet is on favorite or underdog using correct logic."""
    p_yes = opp.get("kalshi_probability", 0.0)
    side = opp.get("trade_side", "").lower()
    
    if side == "yes":
        p_bet = p_yes
    elif side == "no":
        p_bet = 1.0 - p_yes
    else:
        p_bet = None
    
    p_fav = max(p_yes, 1.0 - p_yes)
    
    if p_bet is None:
        betting_on_favorite = None
    else:
        betting_on_favorite = (p_bet >= p_fav - 1e-9)  # float safety
    
    return p_yes, p_bet, p_fav, betting_on_favorite

def canonicalize_prob(model_prob, p_yes):
    """Canonicalize probability to favorite side."""
    # If model_prob is for asked player, canonicalize to favorite
    model_prob_fav = max(model_prob, 1.0 - model_prob)
    kalshi_prob_fav = max(p_yes, 1.0 - p_yes)
    return model_prob_fav, kalshi_prob_fav

def analyze_dataset(analyses, dataset_name):
    """Analyze a dataset (all_analyses or tradable) for bias."""
    print("=" * 80)
    print(f"ANALYZING: {dataset_name}")
    print("=" * 80)
    print()
    
    favorite_bets = 0
    underdog_bets = 0
    yes_trades = 0
    no_trades = 0
    unclear = 0
    
    model_prob_fav_diffs = []
    model_agrees_with_kalshi_fav = 0
    model_disagrees_with_kalshi_fav = 0
    
    # Probability buckets
    buckets = {
        '0.05-0.15': [],
        '0.15-0.25': [],
        '0.25-0.35': [],
        '0.35-0.45': [],
        '0.45-0.55': [],
        '0.55-0.65': [],
        '0.65-0.75': [],
        '0.75-0.85': [],
        '0.85-0.95': [],
    }
    
    for opp in analyses:
        # Only analyze tradable opportunities
        if not opp.get('tradable', False):
            continue
        
        p_yes, p_bet, p_fav, betting_on_favorite = classify_bet(opp)
        
        if betting_on_favorite is None:
            unclear += 1
            continue
        
        trade_side = opp.get('trade_side', '').lower()
        if trade_side == 'yes':
            yes_trades += 1
        elif trade_side == 'no':
            no_trades += 1
        
        if betting_on_favorite:
            favorite_bets += 1
        else:
            underdog_bets += 1
        
        # Canonicalize probabilities for comparison
        model_prob = opp.get('model_probability', 0.0)
        model_prob_fav, kalshi_prob_fav = canonicalize_prob(model_prob, p_yes)
        diff = model_prob_fav - kalshi_prob_fav
        model_prob_fav_diffs.append(diff)
        
        # Check if model agrees with Kalshi on favorite
        model_fav = model_prob > 0.5 if trade_side == 'yes' else (1.0 - model_prob) > 0.5
        kalshi_fav = p_yes > 0.5
        if (model_fav and kalshi_fav) or (not model_fav and not kalshi_fav):
            model_agrees_with_kalshi_fav += 1
        else:
            model_disagrees_with_kalshi_fav += 1
        
        # Bucket by Kalshi favorite probability
        if 0.05 <= p_fav < 0.15:
            buckets['0.05-0.15'].append(opp)
        elif 0.15 <= p_fav < 0.25:
            buckets['0.15-0.25'].append(opp)
        elif 0.25 <= p_fav < 0.35:
            buckets['0.25-0.35'].append(opp)
        elif 0.35 <= p_fav < 0.45:
            buckets['0.35-0.45'].append(opp)
        elif 0.45 <= p_fav < 0.55:
            buckets['0.45-0.55'].append(opp)
        elif 0.55 <= p_fav < 0.65:
            buckets['0.55-0.65'].append(opp)
        elif 0.65 <= p_fav < 0.75:
            buckets['0.65-0.75'].append(opp)
        elif 0.75 <= p_fav < 0.85:
            buckets['0.75-0.85'].append(opp)
        elif 0.85 <= p_fav < 0.95:
            buckets['0.85-0.95'].append(opp)
    
    total = favorite_bets + underdog_bets
    if total == 0:
        print(f"No tradable opportunities in {dataset_name}")
        return
    
    print(f"Total tradable opportunities: {total}")
    print(f"  - Betting on favorites: {favorite_bets} ({favorite_bets/total*100:.1f}%)")
    print(f"  - Betting on underdogs: {underdog_bets} ({underdog_bets/total*100:.1f}%)")
    print(f"  - Unclear: {unclear}")
    print()
    
    print(f"Trade side distribution:")
    print(f"  - YES trades: {yes_trades} ({yes_trades/total*100:.1f}%)")
    print(f"  - NO trades: {no_trades} ({no_trades/total*100:.1f}%)")
    print()
    
    if model_prob_fav_diffs:
        avg_diff = sum(model_prob_fav_diffs) / len(model_prob_fav_diffs)
        print(f"Model vs Kalshi (canonicalized to favorite side):")
        print(f"  - Average difference: {avg_diff:+.1%}")
        print(f"  - Model agrees with Kalshi favorite: {model_agrees_with_kalshi_fav} ({model_agrees_with_kalshi_fav/total*100:.1f}%)")
        print(f"  - Model disagrees with Kalshi favorite: {model_disagrees_with_kalshi_fav} ({model_disagrees_with_kalshi_fav/total*100:.1f}%)")
        print()
    
    print(f"Distribution by Kalshi favorite probability:")
    for bucket_name, bucket_opps in buckets.items():
        if bucket_opps:
            fav_count = sum(1 for opp in bucket_opps if classify_bet(opp)[3])
            print(f"  {bucket_name}: {len(bucket_opps)} total ({fav_count} favorites, {len(bucket_opps)-fav_count} underdogs)")
    print()
    
    return {
        'total': total,
        'favorites': favorite_bets,
        'underdogs': underdog_bets,
        'yes_trades': yes_trades,
        'no_trades': no_trades,
        'avg_diff': avg_diff if model_prob_fav_diffs else 0,
        'agrees': model_agrees_with_kalshi_fav,
        'disagrees': model_disagrees_with_kalshi_fav,
    }

def main():
    print("=" * 80)
    print("COMPREHENSIVE BIAS TESTING (FIXED)")
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
    # Get all markets with lower thresholds to see more opportunities
    tradable, all_analyses = analyzer.scan_markets(
        limit=1000,
        min_value=0.0,  # No minimum to see all
        min_ev=0.0,
        debug=False,
        show_all=True,
        max_hours_ahead=48,
        min_volume=500,
    )
    
    print(f"\nAnalyzed {len(all_analyses)} markets")
    print(f"Found {len(tradable)} tradable opportunities")
    print()
    
    # Analyze all_analyses (raw model behavior)
    all_results = analyze_dataset(all_analyses, "ALL ANALYZED MARKETS (Raw Model Behavior)")
    
    # Analyze tradable (filtered behavior)
    tradable_results = analyze_dataset(tradable, "TRADABLE MARKETS (After Filtering)")
    
    # Compare
    print("=" * 80)
    print("COMPARISON: Raw vs Filtered")
    print("=" * 80)
    print()
    
    if all_results and tradable_results:
        print("Favorite/Underdog distribution:")
        print(f"  All analyzed: {all_results['favorites']/all_results['total']*100:.1f}% favorites, {all_results['underdogs']/all_results['total']*100:.1f}% underdogs")
        print(f"  Tradable: {tradable_results['favorites']/tradable_results['total']*100:.1f}% favorites, {tradable_results['underdogs']/tradable_results['total']*100:.1f}% underdogs")
        print()
        
        print("YES/NO distribution:")
        print(f"  All analyzed: {all_results['yes_trades']/all_results['total']*100:.1f}% YES, {all_results['no_trades']/all_results['total']*100:.1f}% NO")
        print(f"  Tradable: {tradable_results['yes_trades']/tradable_results['total']*100:.1f}% YES, {tradable_results['no_trades']/tradable_results['total']*100:.1f}% NO")
        print()
        
        print("Model vs Kalshi (canonicalized):")
        print(f"  All analyzed: avg diff {all_results['avg_diff']:+.1%}, agrees {all_results['agrees']/all_results['total']*100:.1f}%")
        print(f"  Tradable: avg diff {tradable_results['avg_diff']:+.1%}, agrees {tradable_results['agrees']/tradable_results['total']*100:.1f}%")
        print()
    
    # Final verdict
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    print()
    
    if all_results:
        fav_pct = all_results['favorites'] / all_results['total'] * 100
        if fav_pct > 90:
            print("❌ CRITICAL: Model is heavily biased towards favorites (>90%)")
        elif fav_pct < 10:
            print("⚠️  WARNING: Model is heavily biased towards underdogs (<10%)")
        elif 40 <= fav_pct <= 60:
            print("✅ Model shows balanced favorite/underdog distribution")
        else:
            print(f"⚠️  Model shows {fav_pct:.1f}% favorite bias - monitor closely")
        print()
        
        if all_results['no_trades'] == 0:
            print("❌ CRITICAL: No NO trades found - structural asymmetry in pipeline")
            print("   This is likely caused by grouping/threshold logic filtering out NO trades")
        elif all_results['no_trades'] / all_results['total'] < 0.1:
            print("⚠️  WARNING: Very few NO trades - potential structural asymmetry")
        else:
            print("✅ Model uses both YES and NO trades")
    print()

if __name__ == '__main__':
    main()


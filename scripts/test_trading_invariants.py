"""
Script to run trading pipeline invariant tests on live data.

Usage:
    python -m scripts.test_trading_invariants
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.test_trading_invariants import run_invariant_tests_on_analyses
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.trading.kalshi_client import KalshiClient, Environment
from config.settings import KALSHI_ACCESS_KEY, KALSHI_PRIVATE_KEY_PATH


def main():
    """Run invariant tests on live Kalshi market data."""
    print("="*70)
    print("TRADING PIPELINE INVARIANT TESTS")
    print("="*70)
    print("\nRunning comprehensive correctness tests on Kalshi trading pipeline...")
    
    # Initialize Kalshi client and analyzer
    try:
        kalshi_client = KalshiClient(
            access_key=KALSHI_ACCESS_KEY,
            private_key_path=KALSHI_PRIVATE_KEY_PATH,
            environment=Environment.DEMO  # Use demo environment for testing
        )
        analyzer = KalshiMarketAnalyzer(kalshi_client)
    except Exception as e:
        print(f"❌ Failed to initialize Kalshi client: {e}")
        print("Make sure KALSHI_ACCESS_KEY and KALSHI_PRIVATE_KEY_PATH are set correctly.")
        return 1
    
    # Scan markets to get analyses
    print("\nScanning Kalshi markets...")
    try:
        tradable, all_analyses = analyzer.scan_markets(
            limit=100,  # Scan up to 100 markets
            min_value=0.05,
            min_ev=0.10,
            debug=False,
            show_all=True,  # Get all analyses, not just tradable
            max_hours_ahead=48,
            min_volume=0
        )
        
        print(f"Analyzed {len(all_analyses)} markets")
        print(f"Found {len(tradable)} tradable opportunities")
        
    except Exception as e:
        print(f"❌ Failed to scan markets: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Run invariant tests
    print("\n" + "="*70)
    print("RUNNING INVARIANT TESTS")
    print("="*70)
    
    success = run_invariant_tests_on_analyses(all_analyses, tradable, analyzer)
    
    if success:
        print("\n✅ All tests passed! Pipeline invariants are satisfied.")
        return 0
    else:
        print("\n❌ Some tests failed! Pipeline invariants are violated.")
        print("Please review the failures above and fix the issues.")
        return 1


if __name__ == "__main__":
    sys.exit(main())


#!/usr/bin/env python3
"""
Run automated trading system.
Scans Kalshi markets and places trades when model predicts 2%+ higher than Kalshi.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.trading.auto_trader import create_auto_trader


def main():
    parser = argparse.ArgumentParser(
        description="Automated trading system for Kalshi markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (simulate trades, don't place orders)
  python scripts/trading/run_auto_trader.py --dry-run
  
  # Live trading with 2% minimum value threshold
  python scripts/trading/run_auto_trader.py --min-value 0.02
  
  # More conservative: 5% minimum value threshold, smaller positions
  python scripts/trading/run_auto_trader.py --min-value 0.05 --max-size 5
  
  # Faster scanning (every 30 seconds)
  python scripts/trading/run_auto_trader.py --scan-interval 30
        """
    )
    
    parser.add_argument(
        "--min-value",
        type=float,
        default=0.02,
        help="Minimum value edge to trade (default: 0.02 = 2%%)"
    )
    
    parser.add_argument(
        "--min-ev",
        type=float,
        default=0.05,
        help="Minimum expected value to trade (default: 0.05 = 5%%)"
    )
    
    parser.add_argument(
        "--max-size",
        type=int,
        default=10,
        help="Maximum contracts per trade (default: 10)"
    )
    
    parser.add_argument(
        "--scan-interval",
        type=int,
        default=60,
        help="Seconds between market scans (default: 60)"
    )
    
    parser.add_argument(
        "--max-hours",
        type=int,
        default=48,
        help="Only trade markets closing within N hours (default: 48)"
    )
    
    parser.add_argument(
        "--min-volume",
        type=int,
        default=1000,
        help="Minimum market volume in dollars (default: 1000)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate trades without placing orders (default: True)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place real orders (overrides --dry-run)"
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and exit (don't run continuously)"
    )
    
    args = parser.parse_args()
    
    # Determine if dry run
    dry_run = not args.live if args.live else args.dry_run
    
    if not dry_run:
        print("⚠️  WARNING: LIVE TRADING MODE - Real orders will be placed!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != "yes":
            print("Exiting...")
            return
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           Automated Kalshi Trading System                    ║
╚══════════════════════════════════════════════════════════════╝

Configuration:
  Minimum value threshold: {args.min_value:.1%}
  Minimum expected value: {args.min_ev:.1%}
  Max position size: {args.max_size} contracts
  Scan interval: {args.scan_interval} seconds
  Max hours ahead: {args.max_hours} hours
  Min market volume: ${args.min_volume:,}
  Mode: {'DRY RUN (simulation)' if dry_run else 'LIVE TRADING'}
  Run mode: {'Single scan' if args.once else 'Continuous'}

Starting trader...
    """)
    
    try:
        # Create trader
        trader = create_auto_trader(
            min_value_threshold=args.min_value,
            min_ev_threshold=args.min_ev,
            max_position_size=args.max_size,
            scan_interval=args.scan_interval,
            dry_run=dry_run,
        )
        
        # Update additional settings
        trader.max_hours_ahead = args.max_hours
        trader.min_volume = args.min_volume
        
        if args.once:
            # Run single scan
            print("Running single scan...")
            trades = trader.scan_and_trade()
            
            print(f"\n✅ Scan complete!")
            print(f"Trades placed: {len(trades)}")
            
            if trades:
                print("\nTrade details:")
                for trade in trades:
                    print(f"  - {trade.get('ticker', 'Unknown')}: "
                          f"{trade.get('count', 0)} contracts")
            
            # Show summary
            summary = trader.get_trade_summary()
            print(f"\nTotal trades in session: {summary['total_trades']}")
        else:
            # Run continuously
            trader.run_continuous()
            
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


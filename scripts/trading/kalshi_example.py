#!/usr/bin/env python3
"""
Example script showing how to use the Kalshi client for trading.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.trading.kalshi_client import KalshiClient


def main():
    """Example usage of Kalshi client."""
    
    try:
        # Initialize client (reads from .env or environment variables)
        print("Initializing Kalshi client...")
        client = KalshiClient()
        print("✅ Client initialized successfully\n")
        
        # Get portfolio balance
        print("Fetching portfolio balance...")
        balance = client.get_portfolio_balance()
        print(f"Balance: ${balance.get('balance', 0) / 100:.2f}")
        print(f"Equity: ${balance.get('equity', 0) / 100:.2f}\n")
        
        # Get current positions
        print("Fetching current positions...")
        positions = client.get_positions()
        print(f"Number of positions: {len(positions.get('positions', []))}\n")
        
        # Get available markets (example: search for tennis markets)
        print("Searching for markets...")
        markets = client.get_markets(limit=10)
        print(f"Found {len(markets.get('markets', []))} markets\n")
        
        # Example: Get orderbook for a specific market
        # Uncomment and replace with actual ticker:
        # ticker = "TENNIS-MATCH-12345-YES"
        # print(f"Getting orderbook for {ticker}...")
        # orderbook = client.get_orderbook(ticker)
        # print(f"Orderbook: {orderbook}\n")
        
        # Example: Place an order (commented out for safety)
        # Uncomment and modify with actual values:
        # order = client.place_order(
        #     ticker="TENNIS-MATCH-12345-YES",
        #     side="yes",  # "yes" or "no"
        #     action="buy",  # "buy" or "sell"
        #     count=10,  # Number of contracts
        #     price=50  # Price in cents (optional for market orders)
        # )
        # print(f"Order placed: {order}")
        
        print("✅ All operations completed successfully!")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("\nPlease ensure:")
        print("1. Your Kalshi private key is in keys/kalshi_private_key.pem")
        print("2. Or set KALSHI_PRIVATE_KEY_PATH in .env")
        print("3. See docs/KALSHI_SETUP.md for setup instructions")
        
    except ValueError as e:
        print(f"❌ Error: {e}")
        print("\nPlease ensure:")
        print("1. KALSHI_ACCESS_KEY is set in .env or environment")
        print("2. Your private key file is valid")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


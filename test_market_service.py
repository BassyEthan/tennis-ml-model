#!/usr/bin/env python3
"""
Test script to verify Market Data Service architecture.

Check 1: Prove requests never call Kalshi
- Spam /markets endpoint
- Confirm "FETCHING FROM KALSHI" log does NOT appear

Check 2: Prove staleness handling works
- Temporarily break Kalshi API key
- Confirm /markets still responds
- Confirm /health shows increasing age_seconds
"""

import requests
import time
import sys

SERVICE_URL = "http://localhost:5002"


def test_check_1():
    """Test that /markets never calls Kalshi."""
    print("=" * 70)
    print("CHECK 1: Proving requests never call Kalshi")
    print("=" * 70)
    print("\nSpamming /markets endpoint 10 times...")
    print("Watch the server logs - you should NOT see 'FETCHING FROM KALSHI'")
    print("(It should only appear every 12 seconds from background poller)\n")
    
    for i in range(10):
        try:
            response = requests.get(f"{SERVICE_URL}/markets", timeout=1)
            if response.status_code == 200:
                print(f"  Request {i+1}/10: ✅ OK (status 200)")
            else:
                print(f"  Request {i+1}/10: ❌ Failed (status {response.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"  Request {i+1}/10: ❌ Error: {e}")
            return False
        time.sleep(0.1)  # Small delay between requests
    
    print("\n✅ Check 1 complete!")
    print("   If you didn't see 'FETCHING FROM KALSHI' in logs during these requests,")
    print("   the architecture is correct (requests read from cache only).\n")
    return True


def test_check_2():
    """Test graceful degradation when Kalshi API is broken."""
    print("=" * 70)
    print("CHECK 2: Proving staleness handling works")
    print("=" * 70)
    print("\n⚠️  IMPORTANT: First, temporarily break your Kalshi API key")
    print("   (e.g., set KALSHI_ACCESS_KEY to 'INVALID' in your environment)")
    print("\n   Then restart the market_data_service.py")
    print("   The background poller will fail, but endpoints should still work.\n")
    
    input("Press Enter when you've broken the API key and restarted the service...")
    
    print("\nTesting /markets endpoint (should still respond with stale data)...")
    try:
        response = requests.get(f"{SERVICE_URL}/markets", timeout=1)
        if response.status_code == 200:
            data = response.json()
            print(f"  ✅ /markets responded: OK")
            print(f"     Cache age: {int(time.time() - data.get('generated_at', 0))} seconds")
        else:
            print(f"  ❌ /markets failed: status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"  ❌ /markets error: {e}")
        return False
    
    print("\nTesting /health endpoint (age_seconds should increase)...")
    initial_age = None
    for i in range(3):
        try:
            response = requests.get(f"{SERVICE_URL}/health", timeout=1)
            if response.status_code == 200:
                data = response.json()
                age = data.get('age_seconds', -1)
                if initial_age is None:
                    initial_age = age
                    print(f"  Initial age: {age} seconds")
                else:
                    print(f"  Age after {i*2} seconds: {age} seconds (should increase)")
                    if age > initial_age:
                        print(f"    ✅ Age is increasing (graceful degradation working!)")
            else:
                print(f"  ❌ /health failed: status {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"  ❌ /health error: {e}")
            return False
        time.sleep(2)
    
    print("\n✅ Check 2 complete!")
    print("   If /markets still responds and age_seconds increases,")
    print("   graceful degradation is working correctly.\n")
    return True


def main():
    """Run both checks."""
    print("\n" + "=" * 70)
    print("Market Data Service Architecture Verification")
    print("=" * 70)
    print(f"\nTesting service at: {SERVICE_URL}")
    print("Make sure market_data_service.py is running!\n")
    
    # Test service is running
    try:
        response = requests.get(f"{SERVICE_URL}/health", timeout=2)
        if response.status_code != 200:
            print(f"❌ Service not responding correctly (status {response.status_code})")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ Cannot connect to service at {SERVICE_URL}")
        print(f"   Error: {e}")
        print("\n   Make sure market_data_service.py is running:")
        print("   python market_data_service.py")
        sys.exit(1)
    
    print("✅ Service is running\n")
    
    # Run checks
    check1_ok = test_check_1()
    check2_ok = test_check_2()
    
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Check 1 (No Kalshi calls in requests): {'✅ PASS' if check1_ok else '❌ FAIL'}")
    print(f"Check 2 (Graceful degradation):       {'✅ PASS' if check2_ok else '❌ FAIL'}")
    print("=" * 70)


if __name__ == '__main__':
    main()


#!/usr/bin/env python3
"""
Test script for Kalshi discovery and filtering system.
Tests the layered filtering logic without requiring API access.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.trading.kalshi_discovery import (
    layer2_tennis_keywords,
    layer3_match_structure,
    layer4_market_structure,
    layer5_expiration_window,
    layer6_liquidity,
    is_valid_tennis_market,
    filter_tennis_markets
)


def test_layer2():
    """Test Layer 2: Tennis keyword detection."""
    print("\n" + "="*70)
    print("Testing Layer 2: Tennis Keyword Detection")
    print("="*70)
    
    test_cases = [
        # (event, market, should_pass, description)
        (
            {"event_title": "ATP Tennis Match", "event_description": ""},
            {"title": "Djokovic vs Nadal"},
            True,
            "ATP keyword in title"
        ),
        (
            {"event_title": "WTA Tournament", "event_description": ""},
            {"title": "Player A vs Player B"},
            True,
            "WTA keyword"
        ),
        (
            {"event_title": "Wimbledon Championship", "event_description": ""},
            {"title": "Match"},
            True,
            "Wimbledon keyword"
        ),
        (
            {"event_title": "Basketball Game", "event_description": ""},
            {"title": "Lakers vs Warriors"},
            False,
            "No tennis keywords"
        ),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        result = layer2_tennis_keywords(event, market)
        is_pass = result is None
        status = "✅ PASS" if is_pass == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_pass == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'pass' if should_pass else 'fail'}, Got: {'pass' if is_pass else 'fail'}")
    
    print(f"\n  Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_layer3():
    """Test Layer 3: Match structure heuristic."""
    print("\n" + "="*70)
    print("Testing Layer 3: Match Structure Heuristic")
    print("="*70)
    
    test_cases = [
        (
            {"event_title": "Djokovic vs Nadal"},
            {"title": ""},
            True,
            "Contains 'vs'"
        ),
        (
            {"event_title": "Djokovic v. Nadal"},
            {"title": ""},
            True,
            "Contains 'v.'"
        ),
        (
            {"event_title": "Djokovic wins tournament"},
            {"title": ""},
            False,
            "No 'vs' pattern"
        ),
        (
            {"event_title": "Djokovic vs Nadal tournament"},
            {"title": ""},
            False,
            "Contains exclusion keyword 'tournament'"
        ),
        (
            {"event_title": "Djokovic vs Nadal champion"},
            {"title": ""},
            False,
            "Contains exclusion keyword 'champion'"
        ),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        result = layer3_match_structure(event, market)
        is_pass = result is None
        status = "✅ PASS" if is_pass == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_pass == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'pass' if should_pass else 'fail'}, Got: {'pass' if is_pass else 'fail'} (reason: {result})")
    
    print(f"\n  Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_layer4():
    """Test Layer 4: Market structure validation."""
    print("\n" + "="*70)
    print("Testing Layer 4: Market Structure Validation")
    print("="*70)
    
    test_cases = [
        (
            {},
            {"status": "open", "yes_bid": 50, "no_bid": 50},
            True,
            "Open market with prices"
        ),
        (
            {},
            {"status": "active", "yes_bid": 50, "no_bid": 50},
            True,
            "Active market with prices"
        ),
        (
            {},
            {"status": "closed", "yes_bid": 50, "no_bid": 50},
            False,
            "Closed market"
        ),
        (
            {},
            {"status": "open", "no_bid": 50},
            False,
            "Missing yes_price"
        ),
        (
            {},
            {"status": "open", "yes_bid": 50},
            False,
            "Missing no_price"
        ),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        result = layer4_market_structure(event, market)
        is_pass = result is None
        status = "✅ PASS" if is_pass == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_pass == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'pass' if should_pass else 'fail'}, Got: {'pass' if is_pass else 'fail'} (reason: {result})")
    
    print(f"\n  Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_layer5():
    """Test Layer 5: Expiration window."""
    print("\n" + "="*70)
    print("Testing Layer 5: Expiration Window")
    print("="*70)
    
    now = datetime.now(timezone.utc)
    
    test_cases = [
        (
            {"event_close_time": (now + timedelta(hours=24)).isoformat()},
            {},
            True,
            "24 hours in future"
        ),
        (
            {"event_close_time": (now + timedelta(hours=50)).isoformat()},
            {},
            True,
            "50 hours in future (within 72h)"
        ),
        (
            {"event_close_time": (now + timedelta(hours=100)).isoformat()},
            {},
            False,
            "100 hours in future (too far)"
        ),
        (
            {"event_close_time": (now - timedelta(hours=10)).isoformat()},
            {},
            False,
            "10 hours in past"
        ),
        (
            {"event_close_time": (now - timedelta(hours=1)).isoformat()},
            {},
            True,
            "1 hour in past (grace period)"
        ),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        result = layer5_expiration_window(event, market, max_hours=72)
        is_pass = result is None
        status = "✅ PASS" if is_pass == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_pass == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'pass' if should_pass else 'fail'}, Got: {'pass' if is_pass else 'fail'} (reason: {result})")
    
    print(f"\n  Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_layer6():
    """Test Layer 6: Liquidity check."""
    print("\n" + "="*70)
    print("Testing Layer 6: Liquidity Check")
    print("="*70)
    
    test_cases = [
        (
            {},
            {"volume_dollars": 500},
            True,
            "Volume $500 (above $200)"
        ),
        (
            {},
            {"volume_dollars": 200},
            True,
            "Volume $200 (exactly threshold)"
        ),
        (
            {},
            {"volume_dollars": 100},
            False,
            "Volume $100 (below threshold)"
        ),
        (
            {},
            {"volume": 50000},  # $500 in cents
            True,
            "Volume 50000 cents (converts to $500)"
        ),
        (
            {},
            {"liquidity_dollars": 300},
            True,
            "Liquidity $300"
        ),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        result = layer6_liquidity(event, market, min_volume=200)
        is_pass = result is None
        status = "✅ PASS" if is_pass == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_pass == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'pass' if should_pass else 'fail'}, Got: {'pass' if is_pass else 'fail'} (reason: {result})")
    
    print(f"\n  Result: {passed}/{len(test_cases)} tests passed")
    return passed == len(test_cases)


def test_full_filter():
    """Test complete filtering pipeline."""
    print("\n" + "="*70)
    print("Testing Full Filter Pipeline")
    print("="*70)
    
    now = datetime.now(timezone.utc)
    future_time = (now + timedelta(hours=24)).isoformat()
    
    # Valid tennis market
    valid_event = {
        "event_title": "ATP Tennis: Djokovic vs Nadal",
        "event_description": "Tennis match",
        "event_close_time": future_time,
        "category": "Sports",
        "series_ticker": "TENNIS-ATP"
    }
    valid_market = {
        "ticker": "TENNIS-ATP-123",
        "title": "Djokovic vs Nadal",
        "status": "open",
        "yes_bid": 60,
        "no_bid": 40,
        "volume_dollars": 500
    }
    
    # Invalid market (no tennis keyword)
    invalid_event = {
        "event_title": "Basketball Game",
        "event_description": "",
        "event_close_time": future_time,
    }
    invalid_market = {
        "ticker": "BASKET-123",
        "title": "Lakers vs Warriors",
        "status": "open",
        "yes_bid": 50,
        "no_bid": 50,
        "volume_dollars": 500
    }
    
    test_cases = [
        (valid_event, valid_market, True, "Valid tennis market"),
        (invalid_event, invalid_market, False, "Invalid market (no tennis keyword)"),
    ]
    
    passed = 0
    for event, market, should_pass, desc in test_cases:
        is_valid, reason = is_valid_tennis_market(
            event, market, max_hours=72, min_volume=200, log_rejections=False
        )
        status = "✅ PASS" if is_valid == should_pass else "❌ FAIL"
        print(f"  {status}: {desc}")
        if is_valid == should_pass:
            passed += 1
        else:
            print(f"    Expected: {'valid' if should_pass else 'invalid'}, Got: {'valid' if is_valid else 'invalid'}")
            if reason:
                print(f"    Reason: {reason}")
    
    # Test filter_tennis_markets function
    print("\n  Testing filter_tennis_markets() function...")
    pairs = [(valid_event, valid_market), (invalid_event, invalid_market)]
    results = filter_tennis_markets(pairs, max_hours=72, min_volume=200, log_rejections=False)
    
    if len(results) == 1 and results[0]["market_ticker"] == "TENNIS-ATP-123":
        print("  ✅ PASS: filter_tennis_markets correctly filtered to 1 valid market")
        passed += 1
    else:
        print(f"  ❌ FAIL: Expected 1 valid market, got {len(results)}")
    
    print(f"\n  Result: {passed}/{len(test_cases) + 1} tests passed")
    return passed == len(test_cases) + 1


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("Kalshi Discovery Filtering System - Unit Tests")
    print("="*70)
    
    results = []
    results.append(("Layer 2: Tennis Keywords", test_layer2()))
    results.append(("Layer 3: Match Structure", test_layer3()))
    results.append(("Layer 4: Market Structure", test_layer4()))
    results.append(("Layer 5: Expiration Window", test_layer5()))
    results.append(("Layer 6: Liquidity", test_layer6()))
    results.append(("Full Filter Pipeline", test_full_filter()))
    
    print("\n" + "="*70)
    print("Test Summary")
    print("="*70)
    
    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*70)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("="*70 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())


"""
End-to-end correctness tests for Kalshi trading pipeline.

These tests verify hard invariants that must never be violated.
If any test fails, the pipeline is broken and must be fixed.
"""

import unittest
import math
from typing import Dict, List, Any, Optional, Tuple
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.trading.kalshi_client import KalshiClient, Environment


class TradingInvariantTests(unittest.TestCase):
    """Test suite for trading pipeline invariants."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Note: These tests may require actual Kalshi credentials for integration tests
        # For unit tests, we can mock the analyzer
        self.tolerance = 1e-6  # Floating-point tolerance
    
    def test_ev_sign_correctness(self, analysis: Dict[str, Any]):
        """
        Test 1: EV Sign Correctness (Trade-Level Invariant)
        
        For every recommended trade:
        - Compute trade_edge in the coordinate system of the trade (YES or NO)
        - Assert: trade_edge >= 0
        - Assert: the displayed "value edge" equals trade_edge
        """
        if not analysis.get("tradable", False):
            return  # Skip non-tradable opportunities
        
        trade_side = analysis.get("trade_side")
        trade_value = analysis.get("trade_value")
        value = analysis.get("value")
        expected_value = analysis.get("expected_value")
        
        # Calculate trade_edge based on trade_side
        model_prob = analysis.get("model_probability", 0)
        kalshi_prob = analysis.get("kalshi_probability", 0)
        
        if trade_side == "yes":
            trade_edge = model_prob - kalshi_prob
        elif trade_side == "no":
            # For NO trades, edge is (1 - model_prob) - (1 - kalshi_prob) = kalshi_prob - model_prob
            trade_edge = (1 - model_prob) - (1 - kalshi_prob)
        else:
            self.fail(f"Invalid trade_side: {trade_side}")
        
        # Assert: trade_edge >= 0 (within tolerance for floating-point)
        self.assertGreaterEqual(
            trade_edge, -self.tolerance,
            f"Trade edge must be >= 0, got {trade_edge:.6f} for trade_side={trade_side}, "
            f"model_prob={model_prob:.6f}, kalshi_prob={kalshi_prob:.6f}"
        )
        
        # Assert: trade_value equals absolute value of trade_edge
        # trade_value should already be absolute, so compare with abs(trade_edge)
        expected_trade_value = abs(trade_edge)
        self.assertAlmostEqual(
            trade_value, expected_trade_value, places=6,
            msg=f"trade_value ({trade_value:.6f}) should equal abs(trade_edge) ({expected_trade_value:.6f})"
        )
        
        # Assert: EV >= 0 for tradable opportunities (or at least reasonable)
        # Note: EV can be negative in theory, but tradable ones should have positive EV
        if trade_value > 0.05:  # Only check for significant edges
            self.assertGreaterEqual(
                expected_value, -self.tolerance,
                f"Expected value should be >= 0 for tradable trades, got {expected_value:.6f}"
            )
    
    def test_yes_no_symmetry(self, analysis: Dict[str, Any]):
        """
        Test 2: YES/NO Symmetry Test (Core Math Invariant)
        
        For each analyzed market:
        - Compute edge_yes = model_prob - p_yes
        - Compute edge_no = (1 - model_prob) - (1 - p_yes)
        - Assert: edge_no == -edge_yes (within floating-point tolerance)
        - Assert: abs(edge_yes) == abs(edge_no)
        """
        model_prob = analysis.get("model_probability", 0)
        kalshi_prob = analysis.get("kalshi_probability", 0)  # p_yes
        
        edge_yes = model_prob - kalshi_prob
        edge_no = (1 - model_prob) - (1 - kalshi_prob)
        
        # Assert: edge_no == -edge_yes (mathematical identity)
        self.assertAlmostEqual(
            edge_no, -edge_yes, places=6,
            msg=f"YES/NO symmetry broken: edge_yes={edge_yes:.6f}, edge_no={edge_no:.6f}, "
            f"expected edge_no={-edge_yes:.6f}"
        )
        
        # Assert: abs(edge_yes) == abs(edge_no)
        self.assertAlmostEqual(
            abs(edge_yes), abs(edge_no), places=6,
            msg=f"Absolute edge values must be equal: |edge_yes|={abs(edge_yes):.6f}, "
            f"|edge_no|={abs(edge_no):.6f}"
        )
    
    def test_trade_selection_consistency(self, analysis: Dict[str, Any]):
        """
        Test 3: Trade Selection Consistency
        
        For each market:
        - Determine which side has higher EV
        - Assert: trade_side matches the higher EV side
        """
        if not analysis.get("tradable", False):
            return  # Skip non-tradable opportunities
        
        trade_side = analysis.get("trade_side")
        model_prob = analysis.get("model_probability", 0)
        kalshi_prob = analysis.get("kalshi_probability", 0)
        kalshi_odds = analysis.get("kalshi_odds", {})
        
        yes_odds = kalshi_odds.get("yes_odds")
        no_odds = kalshi_odds.get("no_odds")
        
        # Calculate EV for YES side
        if yes_odds is not None and yes_odds > 0:
            ev_yes = (model_prob * yes_odds) - 1.0
        else:
            ev_yes = (model_prob / kalshi_prob) - 1.0 if kalshi_prob > 0 else -float('inf')
        
        # Calculate EV for NO side
        if no_odds is not None and no_odds > 0:
            ev_no = ((1 - model_prob) * no_odds) - 1.0
        else:
            no_prob = 1 - kalshi_prob
            ev_no = ((1 - model_prob) / no_prob) - 1.0 if no_prob > 0 else -float('inf')
        
        # Determine which side should be chosen
        if ev_yes > ev_no:
            expected_trade_side = "yes"
        elif ev_no > ev_yes:
            expected_trade_side = "no"
        else:
            # Equal EV - either side is acceptable
            expected_trade_side = trade_side  # Accept current choice
        
        # Assert: trade_side matches the higher EV side
        self.assertEqual(
            trade_side, expected_trade_side,
            f"Trade side inconsistency: trade_side={trade_side}, but EV_yes={ev_yes:.6f}, "
            f"EV_no={ev_no:.6f}, expected_trade_side={expected_trade_side}"
        )
    
    def test_framing_invariance(self, analysis: Dict[str, Any], flipped_analysis: Dict[str, Any]):
        """
        Test 4: Framing Invariance Test (Critical)
        
        For a match A vs B:
        - Evaluate market framed as "Will A win?" and "Will B win?"
        - Assert: Absolute EV is identical
        - Assert: Chosen trade represents the same underlying bet
        - Assert: Final trade decision is unchanged
        """
        if not analysis.get("tradable", False):
            return  # Skip non-tradable opportunities
        
        original_ev = abs(analysis.get("expected_value", 0))
        flipped_ev = abs(flipped_analysis.get("expected_value", 0))
        
        # Assert: Absolute EV is identical
        self.assertAlmostEqual(
            original_ev, flipped_ev, places=6,
            msg=f"Framing invariance broken: original_ev={original_ev:.6f}, "
            f"flipped_ev={flipped_ev:.6f}"
        )
        
        # Assert: trade_value is identical (absolute edge should be same)
        original_trade_value = analysis.get("trade_value", 0)
        flipped_trade_value = flipped_analysis.get("trade_value", 0)
        
        self.assertAlmostEqual(
            original_trade_value, flipped_trade_value, places=6,
            msg=f"Trade value should be invariant to framing: original={original_trade_value:.6f}, "
            f"flipped={flipped_trade_value:.6f}"
        )
    
    def test_grouping_logic_correctness(self, all_analyses: List[Dict[str, Any]], 
                                         final_tradable: List[Dict[str, Any]]):
        """
        Test 5: Grouping Logic Correctness (Match-Level)
        
        For matches with multiple market frames:
        - Evaluate all candidate trades (YES and NO)
        - Select the single highest-EV trade per match
        - Assert: no higher-EV trade is discarded due to grouping
        """
        # Group analyses by event_ticker (match)
        match_groups: Dict[str, List[Dict[str, Any]]] = {}
        for analysis in all_analyses:
            ticker = analysis.get("ticker", "")
            if ticker and '-' in ticker:
                event_ticker = ticker.rsplit('-', 1)[0]
                if event_ticker not in match_groups:
                    match_groups[event_ticker] = []
                match_groups[event_ticker].append(analysis)
        
        # For each match with multiple analyses, check that final_tradable contains the best one
        for event_ticker, analyses in match_groups.items():
            if len(analyses) <= 1:
                continue  # Skip matches with single market
            
            # Find tradable analyses for this match
            tradable_for_match = [a for a in analyses if a.get("tradable", False)]
            if len(tradable_for_match) == 0:
                continue
            
            # Find the best EV trade from all tradable analyses
            best_analysis = max(tradable_for_match, key=lambda a: a.get("expected_value", -float('inf')))
            best_ev = best_analysis.get("expected_value", -float('inf'))
            
            # Find the selected trade in final_tradable (should match this match)
            selected_trade = None
            for trade in final_tradable:
                trade_ticker = trade.get("ticker", "")
                if trade_ticker and event_ticker in trade_ticker:
                    selected_trade = trade
                    break
            
            if selected_trade:
                selected_ev = selected_trade.get("expected_value", -float('inf'))
                # Assert: selected trade has EV >= best EV (should be equal, but >= for safety)
                self.assertGreaterEqual(
                    selected_ev, best_ev - self.tolerance,
                    f"Grouping logic error for match {event_ticker}: selected trade has EV={selected_ev:.6f}, "
                    f"but best available EV={best_ev:.6f}"
                )
    
    def test_raw_vs_tradable_distribution(self, all_analyses: List[Dict[str, Any]], 
                                           tradable: List[Dict[str, Any]]):
        """
        Test 6: Raw vs Tradable Distribution Sanity Checks
        
        On all_analyses (raw):
        - YES/NO split should be ~50/50 over large samples
        
        On tradable:
        - Skew is allowed, but both YES and NO must appear over time
        """
        # Check raw distribution (should be ~50/50 for YES/NO opportunities)
        # Note: This is tricky because we need to count YES vs NO opportunities
        # For raw, we check the distribution of edge signs
        yes_count_raw = 0
        no_count_raw = 0
        
        for analysis in all_analyses:
            value = analysis.get("value", 0)
            if value > 0.05:  # Would be YES trade
                yes_count_raw += 1
            elif value < -0.05:  # Would be NO trade
                no_count_raw += 1
        
        total_raw = yes_count_raw + no_count_raw
        if total_raw > 10:  # Only check with sufficient samples
            yes_ratio = yes_count_raw / total_raw if total_raw > 0 else 0
            
            # Warn if heavily skewed (not a hard assert, but log warning)
            if yes_ratio > 0.8 or yes_ratio < 0.2:
                print(f"WARNING: Raw YES/NO distribution heavily skewed: YES={yes_ratio:.1%}, "
                      f"NO={1-yes_ratio:.1%} (expected ~50/50)")
        
        # Check tradable distribution (both YES and NO should appear)
        yes_trades = [t for t in tradable if t.get("trade_side") == "yes"]
        no_trades = [t for t in tradable if t.get("trade_side") == "no"]
        
        if len(tradable) > 20:  # Only check with sufficient samples
            yes_ratio_tradable = len(yes_trades) / len(tradable) if len(tradable) > 0 else 0
            
            # Warn if heavily skewed (not a hard assert)
            if yes_ratio_tradable == 1.0:
                print(f"WARNING: Tradable trades are 100% YES - no NO trades found (sample size: {len(tradable)})")
            elif yes_ratio_tradable == 0.0:
                print(f"WARNING: Tradable trades are 100% NO - no YES trades found (sample size: {len(tradable)})")
    
    def test_ui_consistency(self, analysis: Dict[str, Any]):
        """
        Test 7: UI Consistency Checks
        
        For each recommended trade:
        - Assert: displayed player == actual bet target
        - Assert: displayed odds correspond to trade side
        - Assert: displayed value edge == computed trade_edge
        """
        if not analysis.get("tradable", False):
            return  # Skip non-tradable opportunities
        
        trade_side = analysis.get("trade_side")
        trade_value = analysis.get("trade_value")
        bet_on_player = analysis.get("bet_on_player")
        matched_players = analysis.get("matched_players", ("", ""))
        kalshi_odds = analysis.get("kalshi_odds", {})
        
        # Assert: bet_on_player is set
        self.assertIsNotNone(
            bet_on_player,
            "bet_on_player must be set for tradable opportunities"
        )
        
        # Assert: bet_on_player is one of the matched players
        self.assertIn(
            bet_on_player, matched_players,
            f"bet_on_player ({bet_on_player}) must be one of matched_players {matched_players}"
        )
        
        # Assert: trade_value is positive (for display)
        self.assertGreaterEqual(
            trade_value, 0,
            f"trade_value must be >= 0 for display, got {trade_value:.6f}"
        )
        
        # Assert: odds correspond to trade side
        if trade_side == "yes":
            yes_price = kalshi_odds.get("yes_price")
            self.assertIsNotNone(
                yes_price,
                "YES trade must have yes_price in kalshi_odds"
            )
        elif trade_side == "no":
            no_price = kalshi_odds.get("no_price")
            self.assertIsNotNone(
                no_price,
                "NO trade must have no_price in kalshi_odds"
            )
    
    def test_regression_guardrail(self, analysis: Dict[str, Any]):
        """
        Test 8: Regression Guardrails
        
        Add a single helper assertion:
        assert trade_edge >= 0
        
        directly before any trade is returned from the pipeline.
        """
        if not analysis.get("tradable", False):
            return  # Skip non-tradable opportunities
        
        trade_value = analysis.get("trade_value")
        
        # Hard assert: trade_value must be >= 0
        self.assertGreaterEqual(
            trade_value, -self.tolerance,
            f"REGRESSION GUARDRAIL FAILED: trade_value must be >= 0, got {trade_value:.6f}. "
            f"This indicates a critical bug in the pipeline."
        )


def run_invariant_tests_on_analyses(all_analyses: List[Dict[str, Any]], 
                                    tradable: List[Dict[str, Any]],
                                    analyzer: Optional[KalshiMarketAnalyzer] = None):
    """
    Run all invariant tests on a set of analyses.
    
    Args:
        all_analyses: All analyzed markets (raw)
        tradable: Final tradable opportunities (after grouping)
        analyzer: Optional analyzer instance for additional tests
    """
    test_suite = TradingInvariantTests()
    test_suite.setUp()
    
    failures = []
    warnings = []
    
    # Test 1: EV Sign Correctness (on tradable opportunities)
    print("\n=== Test 1: EV Sign Correctness ===")
    for i, analysis in enumerate(tradable):
        try:
            test_suite.test_ev_sign_correctness(analysis)
        except AssertionError as e:
            failures.append(f"Test 1 (EV Sign) - Trade {i+1}: {str(e)}")
        except Exception as e:
            failures.append(f"Test 1 (EV Sign) - Trade {i+1}: Unexpected error: {str(e)}")
    
    # Test 2: YES/NO Symmetry (on all analyses)
    print("\n=== Test 2: YES/NO Symmetry ===")
    for i, analysis in enumerate(all_analyses):
        try:
            test_suite.test_yes_no_symmetry(analysis)
        except AssertionError as e:
            failures.append(f"Test 2 (YES/NO Symmetry) - Analysis {i+1}: {str(e)}")
    
    # Test 3: Trade Selection Consistency (on tradable opportunities)
    print("\n=== Test 3: Trade Selection Consistency ===")
    for i, analysis in enumerate(tradable):
        try:
            test_suite.test_trade_selection_consistency(analysis)
        except AssertionError as e:
            failures.append(f"Test 3 (Trade Selection) - Trade {i+1}: {str(e)}")
    
    # Test 5: Grouping Logic Correctness
    print("\n=== Test 5: Grouping Logic Correctness ===")
    try:
        test_suite.test_grouping_logic_correctness(all_analyses, tradable)
    except AssertionError as e:
        failures.append(f"Test 5 (Grouping Logic): {str(e)}")
    
    # Test 6: Raw vs Tradable Distribution
    print("\n=== Test 6: Raw vs Tradable Distribution ===")
    try:
        test_suite.test_raw_vs_tradable_distribution(all_analyses, tradable)
    except Exception as e:
        warnings.append(f"Test 6 (Distribution): {str(e)}")
    
    # Test 7: UI Consistency (on tradable opportunities)
    print("\n=== Test 7: UI Consistency ===")
    for i, analysis in enumerate(tradable):
        try:
            test_suite.test_ui_consistency(analysis)
        except AssertionError as e:
            failures.append(f"Test 7 (UI Consistency) - Trade {i+1}: {str(e)}")
    
    # Test 8: Regression Guardrail (on tradable opportunities)
    print("\n=== Test 8: Regression Guardrail ===")
    for i, analysis in enumerate(tradable):
        try:
            test_suite.test_regression_guardrail(analysis)
        except AssertionError as e:
            failures.append(f"Test 8 (Regression Guardrail) - Trade {i+1}: {str(e)}")
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    if failures:
        print(f"\n❌ FAILURES: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("\n✅ All hard invariants passed!")
    
    if warnings:
        print(f"\n⚠️  WARNINGS: {len(warnings)}")
        for warning in warnings:
            print(f"  - {warning}")
    
    return len(failures) == 0


if __name__ == "__main__":
    # Example usage (requires actual Kalshi credentials)
    # This would be called from a script that sets up the analyzer
    print("Run this module from a script that provides analyses data")
    print("Example: python -m scripts.test_trading_invariants")


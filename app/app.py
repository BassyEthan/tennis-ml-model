"""
Tennis Match Prediction & Trading System
Flask web application for tennis match predictions and value betting.
"""

import os
import sys
from pathlib import Path

# Add project root to Python path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from flask import Flask, render_template, request, jsonify
import requests
from config.settings import PORT, DEBUG, HOST, MODELS_DIR, RAW_DATA_DIR
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor
from src.trading.kalshi_client import KalshiClient
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
from src.trading.auto_trader import AutoTrader

# Market Data Service URL (cached Kalshi data)
# This is the ONLY place that should call Kalshi API
MARKET_DATA_SERVICE_URL = "http://localhost:5002"

# Initialize Flask app
# Set template folder relative to project root
_project_root = Path(__file__).parent.parent
app = Flask(__name__, template_folder=str(_project_root / 'templates'))

# Global service instances (initialized on startup)
player_db = None
predictor = None
kalshi_analyzer = None
auto_trader = None


def initialize_services():
    """Initialize all services on application startup."""
    global player_db, predictor, kalshi_analyzer, auto_trader
    
    try:
        print("=" * 70)
        print("Initializing Tennis Trading System...")
        print("=" * 70)
        
        print("Loading player statistics database...")
        player_db = PlayerStatsDB(raw_data_dir=str(RAW_DATA_DIR))
        
        print("Loading prediction models...")
        predictor = MatchPredictor(models_dir=str(MODELS_DIR))
        
        print("Initializing Kalshi analyzer...")
        try:
            kalshi_client = KalshiClient()
            kalshi_analyzer = KalshiMarketAnalyzer(
                kalshi_client=kalshi_client,
                player_db=player_db,
                predictor=predictor
            )
            print("✅ Kalshi analyzer initialized")
            
            # Initialize auto trader (only if Kalshi is available)
            # Use same thresholds as /api/opportunities for consistency
            print("Initializing auto trader...")
            auto_trader = AutoTrader(
                kalshi_client=kalshi_client,
                analyzer=kalshi_analyzer,
                min_value_threshold=0.05,  # 5% edge (same as opportunities endpoint)
                min_ev_threshold=0.10,     # 10% EV (same as opportunities endpoint)
                max_hours_ahead=48,        # 2 days (same as opportunities endpoint)
                min_volume=0               # No minimum (same as opportunities endpoint default)
            )
            print("✅ Auto trader initialized")
        except Exception as e:
            print(f"⚠️  Warning: Kalshi analyzer not available: {e}")
            print("   Opportunities and trading features will be disabled")
            kalshi_analyzer = None
            auto_trader = None
        
        print("=" * 70)
        print("✅ System initialized successfully")
        print("=" * 70)
    except Exception as e:
        print(f"❌ Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        raise


# Initialize services on module import
initialize_services()


@app.route('/healthz', methods=['GET'])
def healthz():
    """Health check endpoint for deployment platforms."""
    return 'ok', 200


@app.route('/')
def index():
    """Render the main prediction interface."""
    return render_template('index.html')


@app.route('/api/players/search', methods=['GET'])
def search_players():
    """Search for players by name (autocomplete endpoint)."""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({"players": []})
    
    matches = []
    query_lower = query.lower()
    
    for db_name, player_id in player_db.name_to_id.items():
        if query_lower in db_name or db_name.startswith(query_lower):
            stats = player_db.get_player_stats(player_id)
            if stats:
                matches.append({
                    "id": player_id,
                    "name": stats["name"]
                })
    
    # Limit to top 10 matches
    return jsonify({"players": matches[:10]})


@app.route('/api/predict', methods=['POST'])
def predict():
    """Predict match outcome between two players."""
    data = request.get_json()
    
    # Extract and validate input
    player1_name = data.get('player1', '').strip()
    player2_name = data.get('player2', '').strip()
    surface = data.get('surface', 'Hard')
    round_code = int(data.get('round_code', 7))
    tourney_level = data.get('tourney_level', 'A')
    
    # Auto-determine best_of_5 based on tournament level
    if 'best_of_5' in data and isinstance(data.get('best_of_5'), bool):
        best_of_5 = data.get('best_of_5')
    else:
        best_of_5 = (tourney_level == 'G')
    
    # Map tournament level to code
    level_map = {"F": 1, "C": 1, "A": 2, "M": 3, "G": 4}
    tourney_level_code = level_map.get(tourney_level, 2)
    
    # Find players - try multiple methods with better error messages
    p1_id = player_db.find_player(player1_name)
    p2_id = player_db.find_player(player2_name)
    
    # If not found, provide helpful error with suggestions
    if not p1_id:
        # Try to find similar names
        suggestions = []
        player1_lower = player1_name.lower().strip()
        for db_name, player_id in list(player_db.name_to_id.items())[:100]:  # Check first 100 for speed
            if player1_lower[:3] in db_name or db_name[:3] in player1_lower:
                actual_name = player_db.id_to_name.get(player_id, db_name)
                if actual_name not in suggestions:
                    suggestions.append(actual_name)
        error_msg = f"Player '{player1_name}' not found"
        if suggestions:
            error_msg += f". Did you mean: {', '.join(suggestions[:5])}?"
        return jsonify({"error": error_msg}), 400
    
    if not p2_id:
        # Try to find similar names
        suggestions = []
        player2_lower = player2_name.lower().strip()
        for db_name, player_id in list(player_db.name_to_id.items())[:100]:  # Check first 100 for speed
            if player2_lower[:3] in db_name or db_name[:3] in player2_lower:
                actual_name = player_db.id_to_name.get(player_id, db_name)
                if actual_name not in suggestions:
                    suggestions.append(actual_name)
        error_msg = f"Player '{player2_name}' not found"
        if suggestions:
            error_msg += f". Did you mean: {', '.join(suggestions[:5])}?"
        return jsonify({"error": error_msg}), 400
    if p1_id == p2_id:
        return jsonify({"error": "Players must be different"}), 400
    
    # Get player statistics
    p1_stats = player_db.get_player_stats(p1_id)
    p2_stats = player_db.get_player_stats(p2_id)
    
    if not p1_stats or not p2_stats:
        return jsonify({"error": "Could not retrieve player statistics"}), 500
    
    # Get head-to-head record
    h2h_diff = player_db.get_h2h(p1_id, p2_id)
    
    # Build features and predict
    # IMPORTANT: The model predicts probability that player1 (p1) wins
    # So if p1=Mmoh and p2=Garin, it predicts Mmoh's win probability
    features_df = predictor.build_features(
        p1_stats, p2_stats,
        surface=surface,
        best_of_5=best_of_5,
        round_code=round_code,
        tourney_level_code=tourney_level_code,
        h2h_diff=h2h_diff
    )
    
    predictions = predictor.predict(features_df)
    
    # Debug: Print parameters used (can be removed in production)
    if DEBUG:
        print(f"Prediction parameters: p1={player1_name}, p2={player2_name}, surface={surface}, "
              f"round={round_code}, level={tourney_level_code}, best_of_5={best_of_5}, h2h_diff={h2h_diff:.3f}")
        print(f"XGBoost prediction (p1 wins): {predictions.get('xgboost', 'N/A')}")
    
    # Format response
    model_display_names = {
        "random_forest": "Random Forest",
        "decision_tree": "Decision Tree",
        "xgboost": "XGBoost"
    }
    
    results = {
        "player1": {
            "name": p1_stats["name"],
            "elo": round(p1_stats["elo"], 1),
            "age": p1_stats.get("age"),
            "height": p1_stats.get("height")
        },
        "player2": {
            "name": p2_stats["name"],
            "elo": round(p2_stats["elo"], 1),
            "age": p2_stats.get("age"),
            "height": p2_stats.get("height")
        },
        "predictions": {}
    }
    
    for model_name, prob in predictions.items():
        if prob is not None:
            display_name = model_display_names.get(model_name, model_name.replace("_", " ").title())
            results["predictions"][display_name] = {
                "player1_win_prob": round(prob * 100, 2),
                "player2_win_prob": round((1 - prob) * 100, 2)
            }
    
    return jsonify(results)


@app.route('/api/debug/markets', methods=['GET'])
def debug_markets():
    """Debug endpoint to check market data service response."""
    try:
        response = requests.get(f"{MARKET_DATA_SERVICE_URL}/markets", timeout=5)
        if response.status_code == 200:
            data = response.json()
            markets_dict = data.get("markets", {})
            if isinstance(markets_dict, dict):
                markets = markets_dict.get("markets", [])
            elif isinstance(markets_dict, list):
                markets = markets_dict
            else:
                markets = []
            
            return jsonify({
                "status": "ok",
                "service_response_status": response.status_code,
                "markets_count": len(markets),
                "markets_structure": type(markets_dict).__name__,
                "sample_market": markets[0] if markets else None,
                "full_response_keys": list(data.keys()) if isinstance(data, dict) else None
            })
        else:
            return jsonify({
                "status": "error",
                "service_response_status": response.status_code,
                "error": "Market data service returned non-200 status"
            }), 500
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route('/api/opportunities', methods=['GET'])
def get_opportunities():
    """Get top Kalshi trading opportunities ranked by volume and value."""
    if kalshi_analyzer is None:
        return jsonify({"error": "Kalshi analyzer not available"}), 503
    
    # Get parameters
    limit = int(request.args.get('limit', 5))  # Number of opportunities to return (default 5)
    max_markets = int(request.args.get('max_markets', 1000))  # Markets to scan
    min_value = float(request.args.get('min_value', 0.05))  # Minimum value threshold
    min_ev = float(request.args.get('min_ev', 0.10))  # Minimum EV threshold
    max_hours = int(request.args.get('max_hours', 48))  # Max hours ahead
    min_volume = int(request.args.get('min_volume', 0))  # Min market volume
    
    try:
        # Fetch markets from Market Data Service (ONLY place that calls Kalshi)
        # This decouples Kalshi API calls from request handlers
        markets = []
        try:
            response = requests.get(f"{MARKET_DATA_SERVICE_URL}/markets", timeout=5)
            if response.status_code == 200:
                markets_data = response.json()
                # Market data service returns: {"generated_at": ..., "markets": {"markets": [...], "total_count": ..., "enriched_count": ...}}
                markets_dict = markets_data.get("markets", {})
                if isinstance(markets_dict, dict):
                    markets = markets_dict.get("markets", [])
                elif isinstance(markets_dict, list):
                    markets = markets_dict
                
                import logging
                logging.info(f"Fetched {len(markets)} markets from market data service")
            else:
                import logging
                logging.error(f"Market data service returned status {response.status_code}")
        except requests.exceptions.RequestException as e:
            import logging
            logging.error(f"Market data service unavailable: {e}")
        except Exception as e:
            import logging
            logging.error(f"Error parsing market data: {e}")
        
        # Use markets from service (always pass as list, never None)
        # CRITICAL: This ensures we NEVER call Kalshi directly from the UI
        import logging
        logging.info(f"Starting scan_markets with {len(markets)} markets from service")
        
        tradable, all_analyses = kalshi_analyzer.scan_markets(
            limit=max_markets,
            min_value=min_value,
            min_ev=min_ev,
            debug=False,  # Disable debug for faster response
            show_all=False,
            max_hours_ahead=max_hours,
            min_volume=min_volume,
            markets=markets  # Always pass markets list (from service or empty)
        )
        
        logging.info(f"scan_markets returned {len(tradable)} tradable opportunities from {len(markets)} markets")
        
        if not tradable:
            logging.warning(f"No tradable opportunities found from {len(markets)} markets")
            return jsonify({
                "opportunities": [],
                "total_analyzed": len(markets),
                "total_tradable": 0
            })
        
        # Sort by market volume (descending) - top opportunities by volume
        tradable.sort(key=lambda x: x.get("market_volume") or 0, reverse=True)
        
        # Take top N (default 5)
        top_opportunities = tradable[:limit]
        
        # Format for frontend
        opportunities = []
        for opp in top_opportunities:
            # Use raw model probabilities for both players (not adjusted for Kalshi's question)
            raw_p1_prob = opp.get("raw_model_probability_p1", opp.get("model_probability", 0))
            raw_p2_prob = opp.get("raw_model_probability_p2", 1.0 - opp.get("model_probability", 0))
            
            # Get parameters used for this prediction (for debugging/consistency)
            surface = opp.get("surface", "Hard")
            round_code = opp.get("round_code", 7)
            tourney_level_code = opp.get("tourney_level_code", 2)
            best_of_5 = opp.get("best_of_5", False)
            
            kalshi_odds = opp.get("kalshi_odds", {})
            bet_on_player = opp.get("bet_on_player")
            if not bet_on_player:
                # Fallback: determine from trade_side
                matched_players = opp.get("matched_players", ("", ""))
                trade_side = opp.get("trade_side", "")
                if trade_side == "yes":
                    bet_on_player = matched_players[0] if matched_players else ""
                else:
                    bet_on_player = matched_players[1] if len(matched_players) > 1 else ""
            
            # Format match time for display
            match_time_formatted = opp.get("match_start_time_formatted", "")
            time_until_match_minutes = opp.get("time_until_match_minutes")
            time_until_match_hours = opp.get("time_until_match_hours")
            
            # Format time until match
            time_until_str = ""
            if time_until_match_minutes is not None:
                if time_until_match_minutes < 0:
                    time_until_str = f"Started {abs(int(time_until_match_minutes))} min ago"
                elif time_until_match_minutes < 60:
                    time_until_str = f"In {int(time_until_match_minutes)} min"
                elif time_until_match_hours < 24:
                    hours = int(time_until_match_hours)
                    minutes = int((time_until_match_hours - hours) * 60)
                    time_until_str = f"In {hours}h {minutes}m"
                else:
                    days = int(time_until_match_hours / 24)
                    hours = int(time_until_match_hours % 24)
                    time_until_str = f"In {days}d {hours}h"
            
            opportunities.append({
                "title": opp.get("title", "Unknown Market"),
                "ticker": opp.get("ticker", ""),
                "players": {
                    "player1": opp.get("matched_players", ("", ""))[0],
                    "player2": opp.get("matched_players", ("", ""))[1]
                },
                "model_probability_p1": round(raw_p1_prob * 100, 1),
                "model_probability_p2": round(raw_p2_prob * 100, 1),
                "kalshi_probability": round(opp.get("kalshi_probability", 0) * 100, 1),
                "model_probability": round(opp.get("model_probability", 0) * 100, 1),  # Adjusted probability
                "value": round(opp.get("value", 0) * 100, 1),
                "expected_value": round(opp.get("expected_value", 0) * 100, 1),
                "trade_side": opp.get("trade_side", ""),
                "trade_value": round(opp.get("trade_value", 0) * 100, 1),
                "kalshi_price": kalshi_odds.get("yes_price", 0),
                "kalshi_odds": {
                    "yes_price": kalshi_odds.get("yes_price", 0),
                    "no_price": kalshi_odds.get("no_price", 0)
                },
                "bet_on_player": bet_on_player,
                "market_volume": opp.get("market_volume", 0),
                "reason": opp.get("reason", ""),
                "match_start_time": opp.get("match_start_time"),
                "match_start_time_formatted": match_time_formatted,
                "time_until_match": time_until_str,
                "time_until_match_minutes": time_until_match_minutes,
                # Add parameters for debugging
                "parameters": {
                    "surface": surface,
                    "round_code": round_code,
                    "tourney_level_code": tourney_level_code,
                    "best_of_5": best_of_5
                }
            })
        
        return jsonify({
            "opportunities": opportunities,
            "total_analyzed": len(markets),
            "total_tradable": len(tradable)
        })
        
    except Exception as e:
        import logging
        import traceback
        logging.error(f"Error in get_opportunities: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@app.route('/api/trading/start', methods=['POST'])
def start_trading():
    """Start automated trading (dry-run or live mode)."""
    if auto_trader is None:
        return jsonify({"error": "Auto trader not available"}), 503
    
    data = request.get_json() or {}
    mode = data.get('mode', 'dry-run')  # 'dry-run' or 'live'
    
    if mode not in ['dry-run', 'live']:
        return jsonify({"error": "Invalid mode. Must be 'dry-run' or 'live'"}), 400
    
    try:
        import logging
        import io
        from logging import StreamHandler
        from contextlib import redirect_stdout, redirect_stderr
        
        # Create a log capturer to capture logger output
        class LogCaptureHandler(StreamHandler):
            def __init__(self):
                super().__init__()
                self.logs = []
            
            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.logs.append(msg)
                except Exception:
                    self.handleError(record)
        
        # Capture logs - auto_trader uses logger.info() for output
        log_capture = LogCaptureHandler()
        log_capture.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        log_capture.setFormatter(formatter)
        
        # Get the auto_trader's logger and add our capture handler
        # auto_trader.py uses logger = logging.getLogger(__name__), which is 'src.trading.auto_trader'
        trader_logger = logging.getLogger('src.trading.auto_trader')
        original_level = trader_logger.level  # Save original level
        original_handlers = trader_logger.handlers[:]  # Save original handlers
        trader_logger.addHandler(log_capture)
        trader_logger.setLevel(logging.INFO)
        trader_logger.propagate = False  # Prevent duplicate logs
        
        # Also capture stdout/stderr for any print statements
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        logs = []
        try:
            # Set trading mode based on request
            # Save original dry_run state to restore later
            original_dry_run = auto_trader.dry_run
            auto_trader.dry_run = (mode == 'dry-run')
            
            # Log the mode (will be captured by stdout capture)
            if mode == 'live':
                print(f"🔴 LIVE TRADING MODE: Real trades will be placed on Kalshi (1 contract per trade)")
            else:
                print(f"🧪 DRY RUN MODE: Simulating trades (no real orders will be placed)")
            
            # Run a single trading cycle (scan and trade)
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                trades_placed = auto_trader.scan_and_trade()
            
            # Restore original dry_run state
            auto_trader.dry_run = original_dry_run
            
            # Get captured logs
            captured_logs = log_capture.logs
            stdout_output = stdout_capture.getvalue()
            stderr_output = stderr_capture.getvalue()
            
            # Process captured logger output
            if captured_logs:
                for log in captured_logs:
                    if log.strip():
                        # Determine log type from content
                        log_type = "info"
                        log_text = log.strip()
                        if "✅" in log_text or "SUCCESS" in log_text.upper() or "PLACED" in log_text.upper() or "COMPLETE" in log_text.upper():
                            log_type = "success"
                        elif "⚠️" in log_text or "WARNING" in log_text.upper():
                            log_type = "warning"
                        elif "❌" in log_text or "ERROR" in log_text.upper() or "FAILED" in log_text.upper():
                            log_type = "error"
                        elif "🔨" in log_text or "TRADING PHASE" in log_text.upper() or "SCAN SUMMARY" in log_text.upper() or "TRADABLE OPPORTUNITIES" in log_text.upper():
                            log_type = "section"
                        logs.append({"message": log_text, "type": log_type})
            
            # Process stdout (for any print statements) - but exclude verbose debug prints from kalshi_analyzer
            if stdout_output:
                for line in stdout_output.strip().split('\n'):
                    if line.strip():
                        line_lower = line.strip().lower()
                        # Exclude verbose debug print statements from kalshi_analyzer.py
                        if 'parsed tennis match' in line_lower or '✓ parsed tennis match' in line_lower:
                            continue
                        if 'match volumes (aggregated by event)' in line_lower:
                            continue
                        if 'market discovery' in line_lower and 'scan summary' not in line_lower:
                            continue
                        if 'best price candidate' in line_lower:
                            continue
                        if 'kalshi probability:' in line_lower and 'model probability' not in line_lower:
                            continue  # Exclude standalone "Kalshi probability:" print statements
                        if 'xgboost probability:' in line_lower:
                            continue
                        logs.append({"message": line.strip(), "type": "info"})
            
            # Process stderr
            if stderr_output:
                for line in stderr_output.strip().split('\n'):
                    if line.strip():
                        logs.append({"message": line.strip(), "type": "error"})
            
            # Restore original state
            trader_logger.removeHandler(log_capture)
            trader_logger.handlers = original_handlers
            trader_logger.setLevel(original_level if original_level else logging.INFO)
            
        except Exception as e:
            # Restore original state even on error
            trader_logger.removeHandler(log_capture)
            trader_logger.handlers = original_handlers
            trader_logger.setLevel(original_level if original_level else logging.INFO)
            raise
        
        return jsonify({
            "status": "completed",
            "mode": mode,
            "trades_placed": trades_placed or [],
            "trades_count": len(trades_placed) if trades_placed else 0,
            "logs": logs
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "logs": [{"message": f"❌ Error: {str(e)}", "type": "error"}]
        }), 500


if __name__ == '__main__':
    print(f"\n🚀 Starting Tennis Trading System on http://{HOST}:{PORT}")
    print(f"   Environment: {'Development' if DEBUG else 'Production'}\n")
    app.run(debug=DEBUG, host=HOST, port=PORT)

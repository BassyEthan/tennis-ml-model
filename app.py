"""
Flask web application for tennis match predictions.
"""

import os
import sys
from pathlib import Path

# Find project root by walking up directory tree until we find 'src' directory
# This handles cases where app.py might be in different locations (local vs Render)
def find_project_root():
    """
    Find the project root directory by looking for 'src' subdirectory.
    Handles case where app.py might be in src/ subdirectory itself.
    """
    current_file = Path(__file__).resolve()
    
    # If app.py is inside a 'src' directory, go up one level
    parts = current_file.parts
    if 'src' in parts:
        src_idx = parts.index('src')
        # If src is not the last part, we're inside src - go up to project root
        if src_idx < len(parts) - 1:
            return Path(*parts[:src_idx + 1]).parent
    
    # Walk up the directory tree looking for a 'src' subdirectory
    for parent in [current_file.parent] + list(current_file.parents):
        src_dir = parent / 'src'
        if src_dir.exists() and src_dir.is_dir():
            return parent
    
    # Fallback: use parent of current file
    return current_file.parent

# Add project root to Python path (needed for Render.com deployment)
project_root = find_project_root()
current_dir = Path.cwd()

# Add multiple possible paths to ensure imports work
paths_to_add = [
    str(project_root),
    str(current_dir),
    str(Path(__file__).parent.absolute()),
    # Handle case where app.py might be in src/ - need parent directory
    str(Path(__file__).parent.parent.absolute()),
]

for path in paths_to_add:
    normalized_path = os.path.normpath(os.path.abspath(path))
    if normalized_path not in sys.path and os.path.exists(normalized_path):
        sys.path.insert(0, normalized_path)

# Debug: Print paths for troubleshooting (critical for Render debugging)
print("=" * 70)
print("[DEPLOYMENT DEBUG] Python Path Configuration")
print("=" * 70)
print(f"__file__ location: {__file__}")
print(f"__file__ resolved: {Path(__file__).resolve()}")
print(f"Current working directory: {current_dir}")
print(f"Project root determined: {project_root}")
print(f"Project root exists: {project_root.exists()}")
print(f"src/ in project root exists: {(project_root / 'src').exists()}")
print(f"sys.path (first 5 entries):")
for i, p in enumerate(sys.path[:5], 1):
    print(f"  {i}. {p}")
print("=" * 70)

from flask import Flask, render_template, request, jsonify
from src.web.player_stats import PlayerStatsDB
from src.web.predictor import MatchPredictor
from src.betting.odds_fetcher import OddsFetcher, ValueBetCalculator

app = Flask(__name__)

# Global instances (loaded on startup)
player_db = None
predictor = None
odds_fetcher = None


def initialize():
    """Initialize player database and predictor on startup."""
    global player_db, predictor, odds_fetcher
    
    print("Initializing player statistics database...")
    player_db = PlayerStatsDB()
    
    print("Initializing prediction models...")
    predictor = MatchPredictor()
    
    print("Initializing odds fetcher...")
    # Set API key from environment variable or use mock data
    api_key = os.environ.get("ODDS_API_KEY")
    odds_fetcher = OddsFetcher(api_key=api_key)
    if not api_key:
        print("⚠️  No ODDS_API_KEY found - using mock odds data")

# Initialize on module load
initialize()


@app.route('/')
def index():
    """Render the main prediction page."""
    return render_template('index.html')


@app.route('/api/players/search', methods=['GET'])
def search_players():
    """Search for players by name."""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({"players": []})
    
    # Find matching players
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
    matches = matches[:10]
    return jsonify({"players": matches})


@app.route('/api/predict', methods=['POST'])
def predict():
    """Predict match outcome between two players."""
    data = request.get_json()
    
    player1_name = data.get('player1', '').strip()
    player2_name = data.get('player2', '').strip()
    surface = data.get('surface', 'Hard')
    best_of_5 = data.get('best_of_5', False)
    round_code = int(data.get('round_code', 7))
    tourney_level = data.get('tourney_level', 'A')
    
    # Map tournament level to code
    level_map = {"F": 1, "C": 1, "A": 2, "M": 3, "G": 4}
    tourney_level_code = level_map.get(tourney_level, 2)
    
    # Find players
    p1_id = player_db.find_player(player1_name)
    p2_id = player_db.find_player(player2_name)
    
    if not p1_id:
        return jsonify({"error": f"Player '{player1_name}' not found"}), 400
    
    if not p2_id:
        return jsonify({"error": f"Player '{player2_name}' not found"}), 400
    
    if p1_id == p2_id:
        return jsonify({"error": "Players must be different"}), 400
    
    # Get player stats
    p1_stats = player_db.get_player_stats(p1_id)
    p2_stats = player_db.get_player_stats(p2_id)
    
    if not p1_stats or not p2_stats:
        return jsonify({"error": "Could not retrieve player statistics"}), 500
    
    # Get H2H
    h2h_diff = player_db.get_h2h(p1_id, p2_id)
    
    # Build features
    features_df = predictor.build_features(
        p1_stats, p2_stats,
        surface=surface,
        best_of_5=best_of_5,
        round_code=round_code,
        tourney_level_code=tourney_level_code,
        h2h_diff=h2h_diff
    )
    
    # Debug: print feature values to verify they're being set correctly
    print(f"Match parameters: surface={surface}, best_of_5={best_of_5}, round={round_code}, level={tourney_level_code}")
    print(f"Feature values: {features_df.iloc[0].to_dict()}")
    
    # Get predictions
    predictions = predictor.predict(features_df)
    
    # Format results
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
    
    # Convert predictions to percentages
    model_display_names = {
        "random_forest": "Random Forest",
        "decision_tree": "Decision Tree",
        "xgboost": "XGBoost"
    }
    
    for model_name, prob in predictions.items():
        if prob is not None:
            display_name = model_display_names.get(model_name, model_name.replace("_", " ").title())
            results["predictions"][display_name] = {
                "player1_win_prob": round(prob * 100, 2),
                "player2_win_prob": round((1 - prob) * 100, 2)
            }
    
    return jsonify(results)


@app.route('/api/value-bets', methods=['POST'])
def calculate_value_bets():
    """Calculate value bets by comparing predictions to odds."""
    data = request.get_json()
    
    player1_name = data.get('player1', '').strip()
    player2_name = data.get('player2', '').strip()
    
    if not player1_name or not player2_name:
        return jsonify({"error": "Both player names required"}), 400
    
    # Get predictions
    p1_id = player_db.find_player(player1_name)
    p2_id = player_db.find_player(player2_name)
    
    if not p1_id or not p2_id:
        return jsonify({"error": "Players not found"}), 400
    
    p1_stats = player_db.get_player_stats(p1_id)
    p2_stats = player_db.get_player_stats(p2_id)
    h2h_diff = player_db.get_h2h(p1_id, p2_id)
    
    # Use default match parameters for odds lookup
    features_df = predictor.build_features(
        p1_stats, p2_stats,
        surface=data.get('surface', 'Hard'),
        best_of_5=data.get('best_of_5', False),
        round_code=int(data.get('round_code', 7)),
        tourney_level_code=int(data.get('tourney_level_code', 2)),
        h2h_diff=h2h_diff
    )
    
    predictions = predictor.predict(features_df)
    
    # Convert to probabilities for value calculation
    model_probs = {}
    for model_name, prob in predictions.items():
        if prob is not None:
            model_probs[model_name] = prob
    
    # Fetch odds - pass predictions so mock odds can be generated from them
    odds_data = odds_fetcher.find_match_odds(player1_name, player2_name, predictions=model_probs)
    
    if not odds_data:
        return jsonify({"error": "Could not find odds for this match"}), 404
    
    # Check if using mock odds and warn
    is_mock_odds = odds_data.get("is_mock", False) or "Mock" in odds_data.get("note", "")
    
    # Calculate value bets
    value_analysis = ValueBetCalculator.calculate_best_bet(model_probs, odds_data)
    
    # Model name mapping
    model_names = {
        "random_forest": "Random Forest",
        "decision_tree": "Decision Tree",
        "xgboost": "XGBoost"
    }
    
    # Convert predictions to display format with percentages
    predictions_display = {}
    for model_name, prob in predictions.items():
        if prob is not None:
            display_name = model_names.get(model_name, model_name.replace("_", " ").title())
            predictions_display[display_name] = {
                "player1_win_prob": round(prob * 100, 2),
                "player2_win_prob": round((1 - prob) * 100, 2)
            }
    
    # Convert recommendations to use display names and full player names
    # Prioritize Random Forest model for profit calculations
    recommendations_with_display_names = []
    random_forest_rec = None
    
    for rec in value_analysis["recommendations"]:
        rec_copy = rec.copy()
        rec_copy["model"] = model_names.get(rec["model"], rec["model"].replace("_", " ").title())
        # Map bet_on from raw name to full stats name
        if rec["bet_on"].lower() in p1_stats["name"].lower() or p1_stats["name"].lower() in rec["bet_on"].lower():
            rec_copy["bet_on"] = p1_stats["name"]
        elif rec["bet_on"].lower() in p2_stats["name"].lower() or p2_stats["name"].lower() in rec["bet_on"].lower():
            rec_copy["bet_on"] = p2_stats["name"]
        
        # Store Random Forest recommendation separately
        if rec_copy["model"] == "Random Forest":
            random_forest_rec = rec_copy
        
        recommendations_with_display_names.append(rec_copy)
    
    # Sort to put Random Forest first
    recommendations_with_display_names.sort(key=lambda x: (x["model"] != "Random Forest", -x["value_percent"]))
    
    # Format response
    response = {
        "match": {
            "player1": {
                "name": p1_stats["name"],
                "odds": odds_data["player1"]["odds"],
                "implied_probability": round(odds_data["player1"]["implied_prob"] * 100, 2)
            },
            "player2": {
                "name": p2_stats["name"],
                "odds": odds_data["player2"]["odds"],
                "implied_probability": round(odds_data["player2"]["implied_prob"] * 100, 2)
            },
            "bookmakers": odds_data["bookmakers"]
        },
        "predictions": predictions_display,
        "value_analysis": {
            "player1_values": {},
            "player2_values": {},
            "recommendations": recommendations_with_display_names,
            "primary_model": "Random Forest",  # Indicate which model to use for main calculations
            "is_mock_odds": is_mock_odds,
            "warning": "⚠️ WARNING: Using simulated/mock odds. For real betting, use actual bookmaker odds from an API. These recommendations are for testing only!" if is_mock_odds else None
        }
    }
    
    for model_name, value_data in value_analysis["player1_values"].items():
        display_name = model_names.get(model_name, model_name)
        response["value_analysis"]["player1_values"][display_name] = {
            "value_percent": value_data["value_percent"],
            "expected_value_percent": value_data["expected_value_percent"],
            "kelly_percent": value_data["kelly_percent"],
            "is_value_bet": value_data["is_value_bet"]
        }
    
    for model_name, value_data in value_analysis["player2_values"].items():
        display_name = model_names.get(model_name, model_name)
        response["value_analysis"]["player2_values"][display_name] = {
            "value_percent": value_data["value_percent"],
            "expected_value_percent": value_data["expected_value_percent"],
            "kelly_percent": value_data["kelly_percent"],
            "is_value_bet": value_data["is_value_bet"]
        }
    
    return jsonify(response)


if __name__ == '__main__':
    # Get port from environment variable (for cloud platforms) or use 5001
    port = int(os.environ.get('PORT', 5001))
    # Debug mode only for local development
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    print("Starting Flask app...")
    print(f"Open your browser to http://localhost:{port} to use the predictor")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)


"""
Prediction utility for web app - builds feature vectors and runs predictions.
"""

import pandas as pd
from joblib import load
from pathlib import Path

# Features used by the models (must match train_common.py)
FEATURES = [
    "elo_diff", "surface_elo_diff", "age_diff", "height_diff",
    "recent_win_rate_diff", "h2h_winrate_diff",
    "is_clay", "is_grass", "is_hard", "is_indoor", "best_of_5",
    "round_code", "tourney_level_code"
]


class MatchPredictor:
    """Predict match outcomes using trained models."""
    
    def __init__(self, models_dir=None):
        if models_dir is None:
            # Try to import from config, fallback to relative path
            try:
                from config.settings import MODELS_DIR
                self.models_dir = Path(MODELS_DIR)
            except ImportError:
                # Fallback: assume we're in project root
                self.models_dir = Path(__file__).parent.parent.parent / "models"
        else:
            self.models_dir = Path(models_dir)
        
        self.models = {}
        self._load_models()
    
    def _load_models(self):
        """Load all trained models."""
        model_files = {
            "random_forest": "rf_model.pkl",
            "decision_tree": "tree_model.pkl",
            "xgboost": "xgb_model.pkl"
        }
        
        for name, filename in model_files.items():
            model_path = self.models_dir / filename
            if model_path.exists():
                print(f"Loading {name} model from {model_path}...")
                self.models[name] = load(model_path)
            else:
                print(f"Warning: {model_path} not found")
    
    def build_features(self, player1_stats, player2_stats, surface="Hard", 
                      best_of_5=False, round_code=7, tourney_level_code=2, h2h_diff=0.0):
        """
        Build feature vector for a match between two players.
        
        Args:
            player1_stats: Dictionary with player1 stats (elo, surface_elo, age, height, recent_win_rate)
            player2_stats: Dictionary with player2 stats
            surface: Match surface ("Hard", "Clay", "Grass")
            best_of_5: Whether best of 5 match
            round_code: Round code (1=R128, 7=Final)
            tourney_level_code: Tournament level (1=C/F, 2=A, 3=M, 4=G)
            h2h_diff: Head-to-head winrate difference (player1 - player2)
        """
        # Get surface-specific Elo or fallback to overall Elo
        p1_surface_elo = player1_stats.get("surface_elo", {}).get(surface)
        if p1_surface_elo is None:
            p1_surface_elo = player1_stats.get("elo", 1500.0)
        
        p2_surface_elo = player2_stats.get("surface_elo", {}).get(surface)
        if p2_surface_elo is None:
            p2_surface_elo = player2_stats.get("elo", 1500.0)
        
        # Calculate differences
        elo_diff = player1_stats.get("elo", 1500.0) - player2_stats.get("elo", 1500.0)
        surface_elo_diff = p1_surface_elo - p2_surface_elo
        age_diff = (player1_stats.get("age") or 0) - (player2_stats.get("age") or 0)
        height_diff = (player1_stats.get("height") or 0) - (player2_stats.get("height") or 0)
        recent_win_rate_diff = player1_stats.get("recent_win_rate", 0.5) - player2_stats.get("recent_win_rate", 0.5)
        
        # Surface encoding
        is_clay = 1 if surface == "Clay" else 0
        is_grass = 1 if surface == "Grass" else 0
        is_hard = 1 if surface == "Hard" else 0
        
        # Indoor encoding (default to 0/outdoor if not specified)
        is_indoor = 0  # Default to outdoor
        
        features = {
            "elo_diff": elo_diff,
            "surface_elo_diff": surface_elo_diff,
            "age_diff": age_diff,
            "height_diff": height_diff,
            "recent_win_rate_diff": recent_win_rate_diff,
            "h2h_winrate_diff": h2h_diff,
            "is_clay": is_clay,
            "is_grass": is_grass,
            "is_hard": is_hard,
            "is_indoor": is_indoor,
            "best_of_5": 1 if best_of_5 else 0,
            "round_code": round_code,
            "tourney_level_code": tourney_level_code
        }
        
        # Convert to DataFrame with features in the EXACT order expected by the model
        # This is critical because sklearn Pipelines expect features in training order
        features_df = pd.DataFrame([features])[FEATURES]
        return features_df
    
    def predict(self, features_df):
        """
        Run predictions with all loaded models.
        
        Returns:
            Dictionary with model names as keys and probability of player1 winning as values.
        """
        predictions = {}
        
        for model_name, model in self.models.items():
            try:
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(features_df)[0]
                    # Probability that player1 wins (class 1)
                    p1_win_prob = float(proba[1])
                else:
                    pred = model.predict(features_df)[0]
                    p1_win_prob = float(pred)
                
                predictions[model_name] = p1_win_prob
            except Exception as e:
                print(f"Error predicting with {model_name}: {e}")
                predictions[model_name] = None
        
        return predictions


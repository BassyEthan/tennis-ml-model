# scripts/simulate_tournament.py
import argparse
import pandas as pd
import joblib
import numpy as np
from tqdm import tqdm

MODEL_PATH = "models/xgb_model.pkl" # or xgb_model.pkl if you prefer
DRAW_PATH = "data/processed/ao_2025_draw_ids_improved.csv"

def load_model(path):
    return joblib.load(path)

def predict_winner(model, p1_features, p2_features):
    """
    Given two players' features, predict the winner.
    p1_features and p2_features must be DataFrames with the same feature structure.
    """
    X = pd.concat([p1_features, p2_features], axis=0)
    probs = model.predict_proba(X)[:, 1]  # Probability p1 wins
    return 1 if probs[0] >= 0.5 else 2, probs[0]

def run_tournament(model, draw_df):
    current_round = draw_df.copy()
    round_num = 1
    results = []

    while len(current_round) > 1:
        print(f"\n🎾 Simulating Round {round_num} ({len(current_round)} players)")
        next_round = []

        for i in tqdm(range(0, len(current_round), 2)):
            match = current_round.iloc[i:i+2]
            p1 = match.iloc[0]
            p2 = match.iloc[1]

            # Feature engineering: elo_diff etc. should be precomputed in dataset
            # But for this simulation, assume we already have `p1_id` and `p2_id`
            # Here, we just grab their IDs and simulate winner
            features = pd.DataFrame([{
                "elo_diff": 0,  # TODO: use actual Elo lookup if available
                "surface_elo_diff": 0,
                "age_diff": 0,
                "height_diff": 0,
                "recent_win_rate_diff": 0,
                "is_clay": 0,
                "is_grass": 0,
                "is_hard": 1,  # AO is hard court
                "best_of_5": 1,
                "round_code": round_num,
                "tourney_level_code": 4,
                "h2h_winrate_diff": 0
            }])

            features_dup = features.copy()  # mirror for p2

            winner_side, prob = predict_winner(model, features, features_dup)
            winner = p1 if winner_side == 1 else p2
            next_round.append(winner)
            results.append({
                "round": round_num,
                "player1": p1["player1"],
                "player2": p2["player1"],
                "winner": winner["player1"],
                "prob_p1_wins": round(prob, 3)
            })

        current_round = pd.DataFrame(next_round)
        round_num += 1

    final_winner = current_round.iloc[0]["player1"]
    print(f"\n🏆 Tournament Champion: {final_winner}")
    return pd.DataFrame(results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--draw", default=DRAW_PATH)
    parser.add_argument("--model", default=MODEL_PATH)
    args = parser.parse_args()

    model = load_model(args.model)
    draw_df = pd.read_csv(args.draw)
    results_df = run_tournament(model, draw_df)

    results_df.to_csv("outputs/ao2025_predictions.csv", index=False)
    print("\n✅ Predictions saved to outputs/ao2025_predictions.csv")

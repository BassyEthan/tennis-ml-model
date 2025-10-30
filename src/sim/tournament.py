
import argparse, pandas as pd
from joblib import load
FEATURES = ["elo_diff","surface_elo_diff","age_diff","height_diff","recent_win_rate_diff",
            "is_clay","is_grass","is_hard","best_of_5","round_code","tourney_level_code"]

def predict_match_proba(model, row):
    X = row[FEATURES].to_frame().T
    return float(model.predict_proba(X)[0,1]) if hasattr(model,"predict_proba") else float(model.predict(X)[0])

def main(bracket_csv, model_path):
    model = load(model_path)
    bracket = pd.read_csv(bracket_csv)
    winners = []
    for _, row in bracket.iterrows():
        p = predict_match_proba(model, row)
        winner = row["p1_id"] if p >= 0.5 else row["p2_id"]
        winners.append((winner, p))
    out = pd.DataFrame(winners, columns=["winner_id","p1_win_prob"])
    print(out)
    out.to_csv("reports/bracket_results.csv", index=False)
    print("✅ Saved reports/bracket_results.csv")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bracket", required=True)
    parser.add_argument("--model", default="models/rf_model.pkl")
    args = parser.parse_args()
    main(args.bracket, args.model)

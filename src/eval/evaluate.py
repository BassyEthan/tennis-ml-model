
import json, pandas as pd
from joblib import load
FEATURES = ["elo_diff","surface_elo_diff","age_diff","height_diff","recent_win_rate_diff",
            "is_clay","is_grass","is_hard","best_of_5","round_code","tourney_level_code"]
TARGET = "p1_wins"

def evaluate(model_path="models/rf_model.pkl", csv_path="data/processed/matches_model_ready.csv"):
    model = load(model_path)
    df = pd.read_csv(csv_path)
    from sklearn.metrics import accuracy_score, log_loss, roc_auc_score, classification_report, confusion_matrix
    X, y = df[FEATURES], df[TARGET].astype(int)
    y_pred = model.predict(X)
    out = {"accuracy": accuracy_score(y,y_pred),
           "report": classification_report(y,y_pred,output_dict=False),
           "confusion_matrix": confusion_matrix(y,y_pred).tolist()}
    if hasattr(model,"predict_proba"):
        proba = model.predict_proba(X)[:,1]
        out["log_loss"] = log_loss(y, proba)
        out["roc_auc"] = roc_auc_score(y, proba)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    evaluate()

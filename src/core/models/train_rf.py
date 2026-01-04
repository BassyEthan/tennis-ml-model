from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from joblib import dump
import numpy as np
from .train_common import (
    load_data,
    make_preprocessor,
    split,
    evaluate,
    print_metrics,
    print_feature_importance,
    FEATURES
)

def main():
    # 🧠 Load and split data with temporal weighting
    X, y, sample_weights = load_data("data/processed/matches_model_ready.csv")
    Xtr, Xte, ytr, yte, wtr, wte = split(X, y, sample_weights)
    
    print(f"📊 Temporal weighting applied:")
    print(f"   Recent matches (0-30 days): weight ~{np.exp(-0.693 * 15 / 365):.2f}")
    print(f"   6 months ago: weight ~{np.exp(-0.693 * 180 / 365):.2f}")
    print(f"   1 year ago: weight ~{np.exp(-0.693 * 365 / 365):.2f}")
    print(f"   2 years ago: weight ~{np.exp(-0.693 * 730 / 365):.2f}")
    print(f"   Average training weight: {wtr.mean():.3f}")
    print()

    # 🌲 Build model
    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_split=4,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1
    )

    pipe = Pipeline([("pre", make_preprocessor()), ("clf", clf)])

    # 🚀 Train with sample weights (recent matches weighted more)
    pipe.fit(Xtr, ytr, clf__sample_weight=wtr)

    # 📈 Evaluate
    results = evaluate(pipe, Xte, yte)

    # 🖨 Pretty print results
    print_metrics(results, "🌲 Random Forest Model")

    # 🌟 Feature importance
    print_feature_importance(pipe, FEATURES, top_n=10)

    # 💾 Save model
    dump(pipe, "models/rf_model.pkl")
    print("✅ models/rf_model.pkl saved")

if __name__ == "__main__":
    main()

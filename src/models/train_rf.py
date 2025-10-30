from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from joblib import dump
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
    # 🧠 Load and split data
    X, y = load_data("data/processed/matches_model_ready.csv")
    Xtr, Xte, ytr, yte = split(X, y)

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

    # 🚀 Train
    pipe.fit(Xtr, ytr)

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

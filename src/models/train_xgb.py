from xgboost import XGBClassifier
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

    # 🚀 XGBoost model
    clf = XGBClassifier(
        n_estimators=400,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1,
        tree_method="hist",
        eval_metric="logloss"
    )

    # 🧱 Build pipeline
    pipe = Pipeline([("pre", make_preprocessor()), ("clf", clf)])

    # 🚀 Train
    pipe.fit(Xtr, ytr)

    # 📈 Evaluate
    results = evaluate(pipe, Xte, yte)

    # 🖨 Pretty print
    print_metrics(results, "🚀 XGBoost Model")

    # 🌟 Show feature importances
    print_feature_importance(pipe, FEATURES, top_n=10)

    # 💾 Save model
    dump(pipe, "models/xgb_model.pkl")
    print("✅ models/xgb_model.pkl saved")

if __name__ == "__main__":
    main()

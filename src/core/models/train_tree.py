from sklearn.tree import DecisionTreeClassifier
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

    # 🌳 Build pipeline
    pipe = Pipeline([
        ("pre", make_preprocessor()),
        ("clf", DecisionTreeClassifier(max_depth=8, random_state=42))
    ])

    # 🚀 Train
    pipe.fit(Xtr, ytr)

    # 📈 Evaluate
    results = evaluate(pipe, Xte, yte)

    # 🖨 Pretty print results
    print_metrics(results, "🎾 Decision Tree Model")

    # 🌟 Feature importance
    print_feature_importance(pipe, FEATURES, top_n=10)

    # 💾 Save model
    dump(pipe, "models/tree_model.pkl")
    print("✅ models/tree_model.pkl saved")

if __name__ == "__main__":
    main()

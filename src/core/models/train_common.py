
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score, classification_report, confusion_matrix
from rich.console import Console
from rich.table import Table
import matplotlib.pyplot as plt

console = Console()

from joblib import dump
FEATURES = ["elo_diff","surface_elo_diff","age_diff","height_diff","recent_win_rate_diff",
            "h2h_winrate_diff",
            "is_clay","is_grass","is_hard","best_of_5","round_code","tourney_level_code"]
TARGET = "p1_wins"
NUMERIC = FEATURES
TEST_SIZE = 0.2
RANDOM_STATE = 42

def load_data(csv_path: str):
    df = pd.read_csv(csv_path)
    return df[FEATURES], df[TARGET].astype(int)

def make_preprocessor():
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")),("scale", StandardScaler())])
    return ColumnTransformer([("num", numeric, NUMERIC)])

def split(X,y):
    return train_test_split(X,y,test_size=TEST_SIZE,random_state=RANDOM_STATE,stratify=y)

def evaluate(model, X_test, y_test):
    y_pred = model.predict(X_test)
    # 🪄 Make report a clean string
    report_str = classification_report(y_test, y_pred)
    out = {
        "accuracy": accuracy_score(y_test, y_pred),
        "report": report_str,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist()
    }

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X_test)[:, 1]
        out["log_loss"] = log_loss(y_test, proba)
        out["roc_auc"] = roc_auc_score(y_test, proba)

    return out

def pretty_confusion_matrix(cm):
    """Return a nicely formatted confusion matrix as a rich table."""
    table = Table(title="🧭 Confusion Matrix")
    table.add_column("Actual / Pred")
    table.add_column("0", justify="center")
    table.add_column("1", justify="center")
    table.add_row("0", str(cm[0][0]), str(cm[0][1]))
    table.add_row("1", str(cm[1][0]), str(cm[1][1]))
    return table

def print_metrics(results: dict, model_name: str):
    """Pretty print model evaluation metrics with colors and icons."""
    console.print(f"\n[bold green]{model_name}[/bold green]")
    console.print(f"✅ Accuracy: [bold]{results['accuracy']:.3f}[/bold]\n")

    console.print("[bold]📊 Classification Report[/bold]:\n")
    console.print(results['report'])

    # Confusion matrix
    console.print(pretty_confusion_matrix(results['confusion_matrix']))

    # Log loss and ROC AUC if available
    if "log_loss" in results:
        console.print(f"\n🧮 Log Loss: [bold]{results['log_loss']:.3f}[/bold]")
    if "roc_auc" in results:
        console.print(f"🏆 ROC AUC: [bold]{results['roc_auc']:.3f}[/bold]")

def print_feature_importance(pipe, feature_names, top_n=None):
    """
    Display feature importances for tree-based models (Decision Tree, RF, XGB).
    Works with models inside sklearn Pipelines.
    """
    clf = pipe.named_steps['clf']

    if not hasattr(clf, "feature_importances_"):
        print("⚠️ This model does not support feature importances.")
        return

    importances = clf.feature_importances_
    feat_imp = pd.DataFrame({
        "feature": feature_names,
        "importance": importances
    }).sort_values(by="importance", ascending=False)

    # If top_n is given, show only top_n features
    if top_n:
        feat_imp = feat_imp.head(top_n)

    print("\n📊 Feature Importances:")
    print(feat_imp)

    # Optional visualization
    plt.figure(figsize=(10, 6))
    plt.barh(feat_imp['feature'], feat_imp['importance'])
    plt.gca().invert_yaxis()
    plt.title("Feature Importances")
    plt.xlabel("Importance")
    plt.tight_layout()
    plt.show()
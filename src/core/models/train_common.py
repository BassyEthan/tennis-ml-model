
import pandas as pd
import numpy as np
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
            "is_clay","is_grass","is_hard","is_indoor","best_of_5","round_code","tourney_level_code"]
TARGET = "p1_wins"
NUMERIC = FEATURES
TEST_SIZE = 0.2
RANDOM_STATE = 42

def load_data(csv_path: str, reference_date=None):
    """
    Load data and calculate temporal weights.
    
    Args:
        csv_path: Path to processed matches CSV
        reference_date: Reference date for weighting (YYYYMMDD format). 
                       If None, uses max date in dataset.
    
    Returns:
        X (features), y (target), sample_weights
    """
    df = pd.read_csv(csv_path)
    
    # Calculate temporal weights based on match date
    if "tourney_date" in df.columns:
        # Convert dates to datetime
        df["date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
        
        # Use max date as reference if not provided
        if reference_date is None:
            reference_date = df["date"].max()
        else:
            reference_date = pd.to_datetime(str(reference_date), format="%Y%m%d")
        
        # Calculate days since match (older = more days)
        df["days_ago"] = (reference_date - df["date"]).dt.days
        df["days_ago"] = df["days_ago"].fillna(365)  # Default to 1 year ago if date invalid
        
        # Exponential decay weighting: weight = exp(-decay * days_ago / 365)
        # This gives:
        # - Recent matches (0-30 days): weight ~1.0
        # - 6 months ago: weight ~0.5
        # - 1 year ago: weight ~0.25
        # - 2 years ago: weight ~0.06
        decay_rate = 0.693  # ln(2) so 1 year = 0.5 weight
        df["sample_weight"] = np.exp(-decay_rate * df["days_ago"] / 365.0)
        
        # Normalize weights so they average to 1.0 (helps with model stability)
        df["sample_weight"] = df["sample_weight"] / df["sample_weight"].mean()
        
        sample_weights = df["sample_weight"].values
    else:
        # No date column, use uniform weights
        sample_weights = np.ones(len(df))
    
    return df[FEATURES], df[TARGET].astype(int), sample_weights

def make_preprocessor():
    numeric = Pipeline([("impute", SimpleImputer(strategy="median")),("scale", StandardScaler())])
    return ColumnTransformer([("num", numeric, NUMERIC)])

def split(X, y, sample_weights=None):
    """
    Split data into train/test sets.
    
    Args:
        X: Features
        y: Target
        sample_weights: Optional sample weights
    
    Returns:
        X_train, X_test, y_train, y_test, (w_train, w_test) if weights provided
    """
    if sample_weights is not None:
        result = train_test_split(
            X, y, sample_weights,
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
            stratify=y
        )
        return result[0], result[1], result[2], result[3], result[4], result[5]
    else:
        result = train_test_split(
            X, y,
            test_size=TEST_SIZE,
            random_state=RANDOM_STATE,
            stratify=y
        )
        return result[0], result[1], result[2], result[3]

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
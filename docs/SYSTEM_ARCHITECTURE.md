# System Architecture & Data Flow

This document explains how the tennis prediction and trading system works from data ingestion to value bet calculation.

## Overview

The system follows this pipeline:
1. **Data Ingestion** → Load historical ATP match data
2. **Feature Engineering** → Calculate Elo ratings, statistics, and match features
3. **Model Training** → Train ML models on historical matches
4. **Prediction** → Use trained models to predict match outcomes
5. **Odds Fetching** → Get betting odds from APIs or generate mock odds
6. **Value Calculation** → Compare predictions to odds to find value bets

---

## 1. Data Ingestion

### Source
- **ATP Match Data**: CSV files from Jeff Sackmann's GitHub repository
- **Location**: `data/raw/atp_matches_YYYY.csv`
- **Format**: One row per match with winner/loser information

### Process
```python
# scripts/data/build_dataset.py
from src.core.data.ingest import load_matches

# Loads all atp_matches_*.csv files from data/raw/
matches = load_matches("data/raw")
```

**What it loads:**
- Match results (winner, loser, score, date)
- Tournament information (name, level, surface, round)
- Player demographics (age, height)
- Match format (best of 3 or 5)

**Output**: Raw pandas DataFrame with all historical matches

---

## 2. Feature Engineering

### Elo Rating System

The system calculates two types of Elo ratings:

#### Overall Elo
- Starts at 1500 for all players
- Updates after each match: `new_rating = old_rating + k * (actual - expected)`
- K-factor = 24 (standard for tennis)
- Expected win probability: `1 / (1 + 10^((opponent_rating - your_rating) / 400))`

#### Surface-Specific Elo
- Separate Elo ratings for Hard, Clay, and Grass
- Same update mechanism, but tracked per surface
- Accounts for player strengths on different surfaces

### Features Calculated

For each match, the system calculates:

1. **Elo Differences**
   - `elo_diff = player1_elo - player2_elo`
   - `surface_elo_diff = player1_surface_elo - player2_surface_elo`

2. **Demographics**
   - `age_diff = player1_age - player2_age`
   - `height_diff = player1_height - player2_height`

3. **Recent Form**
   - `recent_win_rate_diff = player1_recent_wr - player2_recent_wr`
   - Recent win rate = average of last 50 matches (1 = win, 0 = loss)

4. **Head-to-Head**
   - `h2h_winrate_diff = player1_h2h_wr - player2_h2h_wr`
   - Calculated from historical meetings between the two players

5. **Match Context**
   - `is_clay`, `is_grass`, `is_hard` (one-hot encoded surface)
   - `best_of_5` (1 if best of 5, 0 if best of 3)
   - `round_code` (1=R128, 2=R64, 3=R32, 4=R16, 5=QF, 6=SF, 7=Final)
   - `tourney_level_code` (1=C/F, 2=A, 3=M, 4=G)

### Feature Engineering Process

```python
# src/core/features/engineer.py

# Process matches chronologically
for each match in historical order:
    # Get current Elo ratings (before match)
    p1_elo = elo.get(winner_id)
    p2_elo = elo.get(loser_id)
    
    # Calculate differences
    elo_diff = p1_elo - p2_elo
    
    # Update Elo after match
    elo.update(winner_id, loser_id)
```

**Key Point**: Features are calculated using Elo ratings **at the time of the match**, not current ratings. This prevents data leakage.

**Dataset Mirroring**: Each match is represented twice:
- Once with player1 = winner (p1_wins = 1)
- Once with player1 = loser (p1_wins = 0, all differences flipped)

This doubles the training data and ensures the model learns from both perspectives.

---

## 3. Model Training

### Training Process

```python
# scripts/training/train_rf.py (or train_tree.py, train_xgb.py)

# Load processed dataset
X, y = load_data("data/processed/matches_model_ready.csv")
# X = features (12 features)
# y = target (p1_wins: 0 or 1)

# Split: 80% train, 20% test
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

# Preprocess: impute missing values, standardize
preprocessor = make_preprocessor()  # Median imputation + StandardScaler

# Train model
model = RandomForestClassifier(...)
pipeline = Pipeline([("preprocess", preprocessor), ("clf", model)])
pipeline.fit(X_train, y_train)

# Save model
dump(pipeline, "models/rf_model.pkl")
```

### Models Used

1. **Random Forest** (`rf_model.pkl`)
   - Ensemble of decision trees
   - Handles non-linear relationships
   - Primary model for predictions

2. **Decision Tree** (`tree_model.pkl`)
   - Single decision tree
   - Interpretable but can overfit

3. **XGBoost** (`xgb_model.pkl`)
   - Gradient boosting
   - Often highest accuracy

### Features Used (12 total)

```
1. elo_diff
2. surface_elo_diff
3. age_diff
4. height_diff
5. recent_win_rate_diff
6. h2h_winrate_diff
7. is_clay
8. is_grass
9. is_hard
10. best_of_5
11. round_code
12. tourney_level_code
```

**Target**: `p1_wins` (binary: 0 or 1)

---

## 4. Prediction Process

### When You Request a Prediction

1. **Get Player Statistics**
   ```python
   # src/api/player_stats.py
   player_db = PlayerStatsDB()
   
   # Builds database by processing all historical matches chronologically
   # Calculates current Elo, surface Elo, recent form, H2H records
   ```

2. **Build Feature Vector**
   ```python
   # src/api/predictor.py
   features = {
       "elo_diff": p1_elo - p2_elo,
       "surface_elo_diff": p1_surface_elo - p2_surface_elo,
       "age_diff": p1_age - p2_age,
       "height_diff": p1_height - p2_height,
       "recent_win_rate_diff": p1_recent_wr - p2_recent_wr,
       "h2h_winrate_diff": h2h_diff,
       "is_clay": 1 if surface == "Clay" else 0,
       "is_grass": 1 if surface == "Grass" else 0,
       "is_hard": 1 if surface == "Hard" else 0,
       "best_of_5": 1 if best_of_5 else 0,
       "round_code": round_code,
       "tourney_level_code": tourney_level_code
   }
   ```

3. **Run Models**
   ```python
   predictor = MatchPredictor()
   predictions = predictor.predict(features_df)
   
   # Returns:
   # {
   #   "random_forest": 0.65,  # 65% chance player1 wins
   #   "decision_tree": 0.62,
   #   "xgboost": 0.67
   # }
   ```

**Output**: Probability that player1 wins (0.0 to 1.0)

---

## 5. Kalshi Odds Extraction

### Kalshi Market Odds

The system extracts odds directly from Kalshi markets:

```python
# src/trading/kalshi_analyzer.py
kalshi_odds = analyzer.get_market_odds(market)
```

**Kalshi Price Format**:
- Prices are in cents (0-100) where 65 = 65% probability
- Extracted from: bid/ask prices, orderbook, or probability fields
- Converted to decimal odds: `odds = 1 / probability`

**Extraction Process**:
1. Try bid/ask prices → calculate mid price
2. Try last price fields
3. Fetch orderbook (most reliable)
4. Try probability fields directly
5. Convert to probabilities and decimal odds

**Output Format**:
```python
{
    "yes_price": 65,  # Price in cents
    "no_price": 35,
    "yes_prob": 0.65,  # Probability (0-1)
    "no_prob": 0.35,
    "yes_odds": 1.54,  # Decimal odds
    "no_odds": 2.86
}
```

---

## 6. Value Calculation (Kalshi)

### Value Formula

**Value = Your Predicted Probability - Kalshi's Implied Probability**

```python
# src/trading/kalshi_analyzer.py

model_prob = 0.60  # Your model says 60% chance
kalshi_prob = 0.55  # Kalshi prices at 55% (from market)
value = 0.60 - 0.55 = 0.05  # 5% value edge
```

**Positive value** = Your model thinks it's more likely than Kalshi's price suggests

### Expected Value (EV)

**EV = (Probability × Odds) - 1**

```python
expected_value = (0.60 × 2.20) - 1 = 0.32
expected_value_percent = 32%
```

**Interpretation**: Over many bets, you expect 32% profit on average

### Kelly Criterion

**Optimal bet size as fraction of bankroll**

```python
kelly_fraction = (predicted_prob × odds - 1) / (odds - 1)
kelly_fraction = (0.60 × 2.20 - 1) / (2.20 - 1) = 0.267
kelly_percent = 26.7%
```

**Interpretation**: Bet 26.7% of your bankroll for optimal growth (system caps at 25% for safety)

### Value Bet Decision

```python
# For each model prediction:
for model_name, p1_prob in predictions.items():
    # Calculate value for player1
    p1_value = calculate_value(p1_prob, p1_odds)
    
    # Calculate value for player2
    p2_value = calculate_value(1 - p1_prob, p2_odds)
    
    # If value > 0, it's a value bet
    if p1_value["value_percent"] > 0:
        recommend_bet_on_player1()
    elif p2_value["value_percent"] > 0:
        recommend_bet_on_player2()
```

**Recommendations** are sorted by value percentage (highest first)

---

## Complete Flow Example

### Scenario: Predicting Djokovic vs Nadal

1. **Data Lookup**
   - Load Djokovic's current Elo: 1850
   - Load Nadal's current Elo: 1820
   - Get surface Elo (Clay): Djokovic 1800, Nadal 1900
   - Get recent form: Djokovic 0.75, Nadal 0.70
   - Get H2H: Djokovic 30 wins, Nadal 29 wins → diff = 0.017

2. **Feature Building**
   ```
   elo_diff = 1850 - 1820 = 30
   surface_elo_diff = 1800 - 1900 = -100 (Nadal better on clay)
   age_diff = 36 - 37 = -1
   recent_win_rate_diff = 0.75 - 0.70 = 0.05
   h2h_winrate_diff = 0.017
   is_clay = 1, is_grass = 0, is_hard = 0
   best_of_5 = 1 (Grand Slam)
   round_code = 7 (Final)
   tourney_level_code = 4 (Grand Slam)
   ```

3. **Model Prediction**
   - Random Forest: 0.48 (48% Djokovic wins)
   - Decision Tree: 0.45
   - XGBoost: 0.47

4. **Odds Fetching**
   - Bookmaker odds: Djokovic 2.20, Nadal 1.75
   - Implied probabilities: 45.5% vs 57.1%

5. **Value Calculation**
   - Model says: 48% Djokovic wins
   - Bookmaker implies: 45.5% Djokovic wins
   - **Value = 48% - 45.5% = +2.5%** (small value bet)
   - Expected Value = (0.48 × 2.20) - 1 = +5.6%
   - Kelly = 4.2% of bankroll

6. **Recommendation**
   - Bet on Djokovic (positive value)
   - Small bet size (4.2% of bankroll)
   - Expected profit: 5.6% over time

---

## Key Design Decisions

1. **Chronological Processing**: Features calculated using only information available at match time
2. **Surface-Specific Elo**: Accounts for player strengths on different surfaces
3. **Recent Form**: Last 50 matches weighted equally (could be improved with recency weighting)
4. **Multiple Models**: Ensemble approach provides robustness
5. **Value Threshold**: Only recommend bets with positive value
6. **Kelly Criterion**: Optimal bet sizing for long-term growth

---

## Data Requirements

### To Run Predictions
- Historical match data in `data/raw/atp_matches_*.csv`
- Trained models in `models/*.pkl`

### To Get Real Odds
- Kalshi API credentials (access key and private key)
- Set `KALSHI_ACCESS_KEY` and `KALSHI_PRIVATE_KEY_PATH` environment variables

### To Trade on Kalshi
- Kalshi account with API access
- Access key and private key file
- See `docs/KALSHI_SETUP.md` for setup

---

## Model Performance

Models are evaluated on:
- **Accuracy**: Percentage of correct predictions
- **Log Loss**: Penalizes confident wrong predictions
- **ROC AUC**: Ability to distinguish winners from losers

Typical performance:
- Random Forest: ~65-70% accuracy
- XGBoost: ~66-71% accuracy
- Decision Tree: ~63-68% accuracy

**Note**: Accuracy above 50% is profitable if you can find value bets consistently.


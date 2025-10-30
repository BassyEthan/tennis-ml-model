# Tennis Match Predictor Web App

A web application that uses machine learning models to predict tennis match outcomes.

## Features

- Predict match outcomes between any two players
- View predictions from three ML models:
  - Random Forest
  - Decision Tree  
  - XGBoost
- Customize match parameters:
  - Surface (Hard, Clay, Grass)
  - Tournament level (Grand Slam, Masters, ATP Tour, etc.)
  - Round
  - Best of 3 or Best of 5 sets

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make sure you have trained models in the `models/` directory:
   - `rf_model.pkl` (Random Forest)
   - `tree_model.pkl` (Decision Tree)
   - `xgb_model.pkl` (XGBoost)

3. Make sure you have raw match data in `data/raw/`:
   - `atp_matches_*.csv` files (from Jeff Sackmann's ATP data)

## Running the App

Start the Flask server:

```bash
python app.py
```

The app will:
1. Load and process all match data to compute player statistics (this may take a few minutes on first run)
2. Load all trained ML models
3. Start the web server on `http://localhost:5000`

Open your browser and navigate to `http://localhost:5000` to use the predictor.

## Usage

1. Enter the names of two players (e.g., "Novak Djokovic", "Rafael Nadal")
2. Select match parameters (surface, tournament level, round, etc.)
3. Click "Get Predictions"
4. View predictions from all three models showing win probabilities for each player

## Notes

- The first time you run the app, it will take a few minutes to process all match data and compute player statistics
- Player name matching is flexible - you can use full names, last names, or partial matches
- Predictions are based on historical match data and player statistics


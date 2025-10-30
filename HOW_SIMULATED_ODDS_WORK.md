# How Simulated Odds Work

## Current Process (When No API Key)

When you don't have a real betting API key, the system generates **simulated odds** using this process:

### Step 1: Get Model Prediction
- Uses Random Forest model prediction for Player 1 win probability
- Example: If Random Forest says Alcaraz has 87.79% chance to win

### Step 2: Simulate Bookmaker Opinion
- Adds random variance (±8%) to simulate bookmakers disagreeing with your model
- Uses a deterministic hash based on player names (so same match = same odds)
- Example: Bookmaker thinks Alcaraz only has 79.79% (87.79% - 8%)

### Step 3: Calculate Fair Odds
- Fair odds = 1 / probability
- Example: 1 / 0.7979 = 1.253

### Step 4: Add Bookmaker Margin
- Real bookmakers add ~6% margin to ensure profit
- Formula: `odds_with_margin = fair_odds / (1 - 0.06)`
- Example: 1.253 / 0.94 = 1.333

### Step 5: Round and Limit
- Rounds to 2 decimal places
- Limits odds between 1.01 and 50.0

## Why This Matters

**⚠️ Important:** These are **simulated odds**, not real bookmaker odds!

- The variance creates artificial value opportunities for testing
- Real betting requires actual odds from a real API (bet365, draftkings, etc.)
- The system displays a warning when using simulated odds

## Example Flow

```
Your Model Predicts:
  Alcaraz: 87.79% win probability

Simulated Bookmaker Opinion (with variance):
  Alcaraz: 79.79% (8% lower - bookmaker disagrees!)
  
Fair Odds:
  Alcaraz: 1.253 (1 / 0.7979)
  Norrie: 5.034 (1 / 0.2021)

With 6% Margin:
  Alcaraz: 1.333 (1.253 / 0.94)
  Norrie: 5.355 (5.034 / 0.94)

Final Odds Displayed:
  Alcaraz: 1.33
  Norrie: 5.36
```

## For Real Betting

To use **real odds** from actual bookmakers:

1. Get API key from [The Odds API](https://the-odds-api.com/) or similar
2. Set environment variable: `export ODDS_API_KEY=your_key`
3. The system will fetch real odds and no warning will appear
4. Value calculations will compare your model to actual market odds


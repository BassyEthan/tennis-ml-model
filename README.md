# Tennis Match Prediction & Kalshi Trading System

## What It Does

This project predicts ATP tennis match outcomes and identifies value opportunities in Kalshi prediction markets.

It:

- Trains ML models on historical ATP match data
- Outputs win probabilities using Elo, recent form, and match context
- Scans live Kalshi tennis markets
- Flags trades where model probability meaningfully diverges from market pricing

The system is built to operate end-to-end: prediction → pricing → decision.

## Why I Built This

I built this to move beyond "model accuracy" and learn how predictions become trades.

Sports ML projects usually stop at classification. This one focuses on:

- Translating probabilities into market decisions
- Dealing with messy, real-world market data
- Evaluating edge, expected value, and liquidity
- Designing a system that could realistically run in production

The goal was to combine machine learning, trading logic, and deployment-ready engineering in one project.

## Getting Started

### 1. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add Data

Place ATP match CSVs in `data/raw/` (e.g. from Jeff Sackmann's ATP dataset).

### 3. Train Models

```bash
python -m scripts.data.build_dataset
python -m scripts.training.train_rf
python -m scripts.training.train_xgb
```

### 4. Run the App

```bash
python run.py
```

Visit:

- http://localhost:5001

## Notes

- Kalshi API keys are required only for live market analysis
- Secrets are managed via environment variables and git-ignored files
- Built for learning, experimentation, and real-world systems thinking

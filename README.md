# Tennis Match Prediction & Trading System

A production-ready machine learning system for predicting tennis match outcomes and identifying value betting opportunities using Kalshi prediction markets.

## Project Structure

```
tennis-ml-model/
├── app/                    # Flask web application
│   ├── app.py              # Main Flask application
│   └── wsgi.py             # WSGI entry point for production
│
├── config/                 # Configuration management
│   └── settings.py         # Centralized configuration
│
├── src/                    # Source code
│   ├── core/              # Core business logic
│   │   ├── data/          # Data ingestion and processing
│   │   ├── features/      # Feature engineering (Elo, etc.)
│   │   └── models/        # ML model training
│   ├── api/               # API layer
│   │   ├── player_stats.py
│   │   └── predictor.py
│   ├── trading/           # Trading/betting logic
│   │   ├── kalshi_client.py
│   │   ├── kalshi_analyzer.py
│   ├── evaluation/        # Model evaluation
│   └── simulation/        # Tournament simulation
│
├── scripts/               # Utility scripts
│   ├── data/              # Data processing scripts
│   ├── training/          # Model training scripts
│   ├── evaluation/        # Evaluation scripts
│   ├── simulation/        # Simulation scripts
│   └── trading/           # Trading scripts
│
├── data/                  # Data directories
│   ├── raw/               # Raw ATP match data
│   ├── processed/         # Processed datasets
│   └── interim/          # Intermediate files
│
├── models/                # Trained model artifacts (.pkl files)
├── outputs/               # Generated outputs (predictions, brackets)
├── reports/               # Analysis reports and figures
├── templates/             # HTML templates
├── keys/                  # Private keys (git-ignored)
└── docs/                  # Documentation
```

## Quick Start

### 1. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Prepare Data

Place ATP match data files in `data/raw/`:
- `atp_matches_2023.csv`
- `atp_matches_2024.csv`
- (or other years from Jeff Sackmann's ATP data)

### 3. Build Dataset

```bash
python -m scripts.data.build_dataset
```

### 4. Train Models

```bash
# Train all models
python -m scripts.training.train_rf
python -m scripts.training.train_tree
python -m scripts.training.train_xgb

# Or train individually
python -m scripts.training.train_rf
```

### 5. Run Web Application

**Option 1: Simple run script (recommended)**
```bash
python run.py
```

**Option 2: Using Python module**
```bash
python -m app.app
```

**Option 3: Direct Python**
```bash
python app/app.py
```

The application will be available at `http://localhost:5001`

## Features

### Match Prediction
- Predict match outcomes using three ML models:
  - Random Forest (primary model)
  - Decision Tree
  - XGBoost
- Customizable match parameters:
  - Surface (Hard, Clay, Grass)
  - Tournament level (Grand Slam, Masters, ATP Tour, etc.)
  - Round
  - Best of 3 or Best of 5 sets

### Value Betting
- Compare model predictions to betting odds
- Calculate value percentages and expected value
- Kelly Criterion for optimal bet sizing
- Support for multiple bookmakers

### Kalshi Trading Integration
- Direct integration with Kalshi prediction markets
- Automated order placement based on model predictions
- Portfolio management and position tracking
- See `docs/KALSHI_SETUP.md` for setup instructions

### Player Statistics
- Elo ratings (overall and surface-specific)
- Recent form (last 50 matches)
- Head-to-head records
- Player demographics (age, height)

## Configuration

Configuration is managed in `config/settings.py`. Key settings:

- **Data directories**: `RAW_DATA_DIR`, `PROCESSED_DATA_DIR`, `MODELS_DIR`
- **Flask settings**: `PORT`, `DEBUG`, `HOST`
- **API keys**: Set via environment variables or `.env` file

### Environment Variables

Create a `.env` file in the project root:

```bash
# Kalshi Trading API
KALSHI_ACCESS_KEY=your_kalshi_access_key
KALSHI_PRIVATE_KEY_PATH=keys/kalshi_private_key.txt
KALSHI_BASE_URL=https://demo-api.kalshi.co

# Flask
FLASK_ENV=development
PORT=5001
```

Or set environment variables directly:
```bash
export KALSHI_ACCESS_KEY="your_key_here"
export FLASK_ENV="production"
export PORT=5001
```

### Kalshi Setup

1. Place your Kalshi private key in `keys/kalshi_private_key.txt`
2. Set `KALSHI_ACCESS_KEY` in `.env` or environment
3. See `docs/KALSHI_SETUP.md` for detailed instructions

## Scripts

### Data Processing
```bash
python -m scripts.data.build_dataset
```

### Model Training
```bash
python -m scripts.training.train_rf
python -m scripts.training.train_tree
python -m scripts.training.train_xgb
```

### Evaluation
```bash
python -m scripts.evaluation.evaluate
```

### Tournament Simulation
```bash
python -m scripts.simulation.simulate_tournament
```

### Kalshi Trading
```bash
python -m scripts.trading.kalshi_example
```

## API Endpoints

### Health Check
```
GET /healthz
```

### Search Players
```
GET /api/players/search?q=<player_name>
```

### Predict Match
```
POST /api/predict
{
  "player1": "Novak Djokovic",
  "player2": "Rafael Nadal",
  "surface": "Hard",
  "round_code": 7,
  "tourney_level": "G"
}
```

## Deployment

### Render.com

The project is configured for Render.com deployment:

1. **Procfile** is configured for Gunicorn
2. **wsgi.py** provides the WSGI entry point
3. Set environment variables in Render dashboard:
   - `KALSHI_ACCESS_KEY` (for Kalshi trading)
   - `KALSHI_PRIVATE_KEY_PATH` (path to private key)
   - `FLASK_ENV=production`
   - `PORT` (auto-set by Render)

### Other Platforms

For other platforms (Heroku, AWS, etc.), ensure:
- `Procfile` points to `app.wsgi:application`
- Environment variables are set correctly
- Python version matches `runtime.txt`

See `docs/DEPLOYMENT_GUIDE.md` for detailed instructions.

## Documentation

See `docs/` directory for detailed documentation:
- `PROJECT_STRUCTURE.md` - Codebase organization
- `BETTING_GUIDE.md` - Value betting concepts
- `KALSHI_SETUP.md` - Kalshi integration setup
- `DEPLOYMENT_GUIDE.md` - Deployment instructions

## Development

### Project Organization

- **Core logic** in `src/core/` - reusable across scripts and web app
- **API layer** in `src/api/` - web-specific services
- **Trading logic** in `src/trading/` - betting and value calculations
- **Scripts** organized by purpose in `scripts/`

### Adding New Features

1. Core business logic → `src/core/`
2. Web API endpoints → `app/app.py`
3. Utility scripts → `scripts/`
4. Configuration → `config/settings.py`

## Security

- `.env` file is git-ignored (contains API keys)
- `keys/` directory is git-ignored (contains private keys)
- Never commit credentials to the repository
- Use environment variables in production

## License

This project is for educational and research purposes.

## Achievements

This project represents a production-ready tennis trading system with the following key accomplishments:

### Technical Achievements

- **Production-Ready Architecture**: Modular, scalable codebase following best practices with clear separation of concerns (core logic, API layer, trading logic)
- **Kalshi API Integration**: Full integration with Kalshi prediction markets including RSA-PSS request signing, authentication, and real-time market data fetching
- **Robust Market Discovery**: Multi-layered filtering system (6 layers) for reliably identifying tennis markets from Kalshi's API, handling inconsistent metadata and edge cases
- **Model Symmetry Enforcement**: Implemented symmetry enforcement to ensure consistent predictions regardless of player order, fixing inherent asymmetries in tree-based models
- **Temporal Weighting**: Advanced model training with exponential decay weighting, giving more influence to recent matches for better prediction accuracy
- **Parameter Inference**: Intelligent extraction of match parameters (surface, round, tournament level) from Kalshi market titles using pattern matching and keyword detection
- **Player Name Matching**: Fuzzy matching system for player names with validation to handle variations, nicknames, and database inconsistencies
- **Real-Time Value Calculation**: Live calculation of value bets, expected value, and trade recommendations based on model predictions vs. Kalshi market prices

### Machine Learning Achievements

- **Multiple Model Ensemble**: Three trained models (XGBoost, Random Forest, Decision Tree) with ~65-71% accuracy on historical ATP match data
- **Feature Engineering**: Comprehensive feature set including Elo ratings (overall and surface-specific), head-to-head records, recent form, and match context
- **Chronological Data Processing**: Features calculated using only information available at match time, preventing data leakage
- **Model Performance**: Achieved prediction accuracy significantly above baseline (50%), enabling profitable value betting strategies

### System Capabilities

- **Live Trading Opportunities**: Real-time scanning of Kalshi markets, ranking opportunities by market volume and value edge
- **Web-Based Interface**: Modern Flask web application with interactive UI for match predictions and trading opportunities
- **Automated Market Analysis**: Automated parsing of market titles, player matching, and value calculation for hundreds of markets simultaneously
- **Secure Credential Management**: Environment-based configuration with git-ignored sensitive files, following security best practices
- **Production Deployment Ready**: Configured for deployment on Render.com and other platforms with WSGI support

### Data & Integration

- **Historical Data Processing**: Processes multiple years of ATP match data (2023, 2024, 2025) with support for indoor/outdoor classification
- **Kalshi Market Integration**: Direct connection to Kalshi's production and demo APIs with proper error handling and rate limiting
- **Market Volume Ranking**: Prioritizes high-volume markets for more reliable odds and better liquidity
- **Comprehensive Documentation**: Extensive documentation covering setup, architecture, deployment, and usage

## Acknowledgments

- ATP match data from [Jeff Sackmann's GitHub](https://github.com/JeffSackmann/tennis_atp)
- ML models trained on historical ATP match data

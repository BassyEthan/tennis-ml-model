# Project Structure Documentation

This document describes the reorganized project structure for the Tennis Trading System.

## Directory Organization

### `/app/` - Web Application
- `app.py` - Main Flask application with all API endpoints
- `wsgi.py` - WSGI entry point for production deployment (Gunicorn, etc.)

### `/config/` - Configuration
- `settings.py` - Centralized configuration management
  - Data directories
  - Model paths
  - Flask settings
  - API keys (from environment variables)

### `/src/` - Source Code

#### `/src/core/` - Core Business Logic
- **`data/`** - Data ingestion and processing
  - `ingest.py` - Load ATP match data from CSV files
- **`features/`** - Feature engineering
  - `elo.py` - Elo rating system implementation
  - `engineer.py` - Build feature vectors from match data
- **`models/`** - Machine learning models
  - `train_common.py` - Shared training utilities
  - `train_rf.py` - Random Forest model training
  - `train_tree.py` - Decision Tree model training
  - `train_xgb.py` - XGBoost model training

#### `/src/api/` - API Layer
- `player_stats.py` - Player statistics database and lookup
- `predictor.py` - Match prediction service

#### `/src/trading/` - Trading & Betting Logic
- `kalshi_client.py` - Kalshi API client for market data and trading
  - `KalshiBaseClient` - Base client with authentication
  - `KalshiHttpClient` - HTTP API methods
  - `KalshiClient` - Backward-compatible wrapper
- `kalshi_analyzer.py` - Analyze Kalshi markets for value opportunities
  - `KalshiMarketAnalyzer` - Market analysis and value calculation

#### `/src/evaluation/` - Model Evaluation
- `evaluate.py` - Model evaluation utilities

#### `/src/simulation/` - Tournament Simulation
- `tournament.py` - Simulate tournament brackets

### `/scripts/` - Utility Scripts

Scripts are organized by purpose:

- **`data/`** - Data processing
  - `build_dataset.py` - Build model-ready dataset from raw data
- **`training/`** - Model training
  - `train_rf.py` - Train Random Forest model
  - `train_tree.py` - Train Decision Tree model
  - `train_xgb.py` - Train XGBoost model
- **`evaluation/`** - Model evaluation
  - `evaluate.py` - Evaluate trained models
- **`simulation/`** - Tournament simulation
  - `simulate_tournament.py` - Simulate tournament brackets
  - `plot_bracket.py` - Visualize tournament brackets
  - `sample_bracket.csv` - Sample bracket data

### `/data/` - Data Directories
- `raw/` - Raw ATP match data (CSV files)
- `processed/` - Processed datasets ready for model training
- `interim/` - Intermediate processing files

### `/models/` - Trained Models
- `rf_model.pkl` - Random Forest model
- `tree_model.pkl` - Decision Tree model
- `xgb_model.pkl` - XGBoost model

### `/outputs/` - Generated Outputs
- Predictions, brackets, visualizations

### `/reports/` - Analysis Reports
- `figures/` - Generated charts and visualizations

### `/templates/` - HTML Templates
- `index.html` - Main web interface

### `/keys/` - Private Keys (Git-ignored)
- `kalshi_private_key.pem` - Kalshi private key (not in repo)
- `README.md` - Setup instructions

### `/docs/` - Documentation
- All markdown documentation files consolidated here

## Import Structure

### From Application Code
```python
from config.settings import MODELS_DIR, RAW_DATA_DIR
from src.core.data.ingest import load_matches
from src.core.features.elo import Elo, SurfaceElo
from src.api.player_stats import PlayerStatsDB
from src.api.predictor import MatchPredictor
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
```

### From Scripts
```python
from src.core.data.ingest import load_matches
from src.core.features.engineer import build_match_dataset
from src.core.models.train_rf import main
from src.evaluation.evaluate import evaluate
```

## Key Design Decisions

1. **Separation of Concerns**
   - Core logic separated from API layer
   - Trading logic isolated in its own module
   - Configuration centralized

2. **Script Organization**
   - Scripts grouped by purpose (data, training, evaluation, simulation)
   - Makes it easy to find and run specific tasks

3. **Clear Module Names**
   - `betting/` → `trading/` (more professional)
   - `web/` → `api/` (clearer purpose)
   - `eval/` → `evaluation/` (full word)

4. **Configuration Management**
   - All paths and settings in `config/settings.py`
   - Environment variables for sensitive data
   - Easy to change for different environments

5. **Deployment Ready**
   - Clean WSGI entry point
   - Proper Procfile configuration
   - Environment-based settings

## Migration Notes

If you have existing code that imports from the old structure:

**Old imports:**
```python
from src.data.ingest import load_matches
from src.features.elo import Elo
from src.web.player_stats import PlayerStatsDB
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
```

**New imports:**
```python
from src.core.data.ingest import load_matches
from src.core.features.elo import Elo
from src.api.player_stats import PlayerStatsDB
from src.trading.kalshi_analyzer import KalshiMarketAnalyzer
```

## Running the System

### Development
```bash
python -m app.app
```

### Production (Gunicorn)
```bash
gunicorn app.wsgi:application
```

### Scripts
```bash
python -m scripts.data.build_dataset
python -m scripts.training.train_rf
python -m scripts.evaluation.evaluate
```


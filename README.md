# Tennis Match Prediction & Trading System

A production-ready machine learning system for predicting tennis match outcomes and identifying value betting opportunities.

## 🏗️ Project Structure

```
tennis-ml-model/
├── app/                    # Flask web application
│   ├── app.py              # Main Flask application
│   └── wsgi.py             # WSGI entry point for production
│
├── config/                 # Configuration management
│   ├── __init__.py
│   └── settings.py        # Centralized configuration
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
│   │   └── odds_fetcher.py
│   ├── evaluation/        # Model evaluation
│   └── simulation/        # Tournament simulation
│
├── scripts/               # Utility scripts
│   ├── data/              # Data processing scripts
│   ├── training/          # Model training scripts
│   ├── evaluation/         # Evaluation scripts
│   └── simulation/        # Simulation scripts
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
├── docs/                  # Documentation
│
├── requirements.txt       # Python dependencies
├── runtime.txt            # Python version
├── Procfile               # Deployment configuration
└── render.yaml            # Render.com configuration
```

## 🚀 Quick Start

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

## 📊 Features

### Match Prediction
- Predict match outcomes using three ML models:
  - **Random Forest** (primary model)
  - **Decision Tree**
  - **XGBoost**
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

### Player Statistics
- Elo ratings (overall and surface-specific)
- Recent form (last 50 matches)
- Head-to-head records
- Player demographics (age, height)

## 🔧 Configuration

Configuration is managed in `config/settings.py`. Key settings:

- **Data directories**: `RAW_DATA_DIR`, `PROCESSED_DATA_DIR`, `MODELS_DIR`
- **Flask settings**: `PORT`, `DEBUG`, `HOST`
- **API keys**: Set via environment variables or `.env` file

### Environment Variables

Create a `.env` file in the project root (see `.env.example` for template):

```bash
# Kalshi Trading API
KALSHI_ACCESS_KEY=your_kalshi_access_key
KALSHI_PRIVATE_KEY_PATH=keys/kalshi_private_key.pem
KALSHI_BASE_URL=https://demo-api.kalshi.co

# Other APIs
ODDS_API_KEY=your_odds_api_key

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

1. Place your Kalshi private key in `keys/kalshi_private_key.pem`
2. Set `KALSHI_ACCESS_KEY` in `.env` or environment
3. See `docs/KALSHI_SETUP.md` for detailed instructions

## 📝 Scripts

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

## 🌐 API Endpoints

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

### Calculate Value Bets
```
POST /api/value-bets
{
  "player1": "Novak Djokovic",
  "player2": "Rafael Nadal",
  "surface": "Hard",
  "round_code": 7,
  "tourney_level": "G"
}
```

## 🚢 Deployment

### Render.com

The project is configured for Render.com deployment:

1. **Procfile** is configured for Gunicorn
2. **wsgi.py** provides the WSGI entry point
3. Set environment variables in Render dashboard:
   - `ODDS_API_KEY` (optional, for real odds)
   - `FLASK_ENV=production`
   - `PORT` (auto-set by Render)

### Other Platforms

For other platforms (Heroku, AWS, etc.), ensure:
- `Procfile` points to `app.wsgi:application`
- Environment variables are set correctly
- Python version matches `runtime.txt`

## 📚 Documentation

See `docs/` directory for detailed documentation:
- `BETTING_GUIDE.md` - Value betting guide
- `DEPLOYMENT_GUIDE.md` - Deployment instructions
- `WEBAPP_README.md` - Web application usage
- And more...

## 🧪 Development

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

## 📄 License

This project is for educational and research purposes.

## 🙏 Acknowledgments

- ATP match data from [Jeff Sackmann's GitHub](https://github.com/JeffSackmann/tennis_atp)
- ML models trained on historical ATP match data


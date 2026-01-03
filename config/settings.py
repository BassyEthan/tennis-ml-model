"""
Configuration settings for the tennis trading system.
Environment variables override defaults.
"""
import os
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use environment variables only

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INTERIM_DATA_DIR = DATA_DIR / "interim"

# Model directory
MODELS_DIR = PROJECT_ROOT / "models"

# Output directory
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Flask configuration
FLASK_ENV = os.environ.get("FLASK_ENV", "development")
DEBUG = FLASK_ENV != "production"
PORT = int(os.environ.get("PORT", 5001))
HOST = os.environ.get("HOST", "0.0.0.0")

# API Keys
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
ODDS_API_PROVIDER = os.environ.get("ODDS_API_PROVIDER", "oddsapi")

# Kalshi API Configuration
KALSHI_ACCESS_KEY = os.environ.get("KALSHI_ACCESS_KEY")
# Can be either a file path OR the private key content as a string
KALSHI_PRIVATE_KEY = os.environ.get("KALSHI_PRIVATE_KEY")  # Private key as string
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", str(PROJECT_ROOT / "keys" / "kalshi_private_key.pem"))
KALSHI_BASE_URL = os.environ.get("KALSHI_BASE_URL", "https://demo-api.kalshi.co")  # Use "https://api.kalshi.com" for production
KALSHI_USE_PRODUCTION = os.environ.get("KALSHI_USE_PRODUCTION", "false").lower() == "true"

# If using production, override base URL
if KALSHI_USE_PRODUCTION:
    KALSHI_BASE_URL = "https://api.kalshi.com"

# Keys directory (for storing private keys securely)
KEYS_DIR = PROJECT_ROOT / "keys"

# Model files
MODEL_FILES = {
    "random_forest": "rf_model.pkl",
    "decision_tree": "tree_model.pkl",
    "xgboost": "xgb_model.pkl"
}


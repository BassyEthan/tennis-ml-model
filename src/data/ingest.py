
import pandas as pd
import glob
from pathlib import Path

def load_matches(raw_dir: str) -> pd.DataFrame:
    # Look for Jeff Sackmann files in data/raw/
    files = sorted(glob.glob(str(Path(raw_dir) / "atp_matches_*.csv")))
    if not files:
        raise FileNotFoundError("No atp_matches_*.csv files found in data/raw/.")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    return df

def load_players(raw_dir: str) -> pd.DataFrame:
    p = Path(raw_dir) / "atp_players.csv"
    if not p.exists():
        # Optional — only used for enrichment later
        return pd.DataFrame()
    return pd.read_csv(p)

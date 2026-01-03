
# Build model-ready dataset
from src.core.data.ingest import load_matches, load_players
from src.core.features.engineer import build_match_dataset

RAW = "data/raw"
OUT = "data/processed/matches_model_ready.csv"

def main():
    matches = load_matches(RAW)
    model_df = build_match_dataset(matches)
    model_df.to_csv(OUT, index=False)
    print(f"✅ Wrote {OUT} with shape {model_df.shape}")

if __name__ == "__main__":
    main()

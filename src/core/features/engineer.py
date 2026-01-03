import pandas as pd
import numpy as np
from tqdm import tqdm
from .elo import Elo, SurfaceElo

def _normalize_surface(s):
    """Normalize surface strings to Hard, Clay, or Grass."""
    if pd.isna(s):
        return "Hard"
    s = str(s).strip().capitalize()
    if s.startswith("H"): return "Hard"
    if s.startswith("C"): return "Clay"
    if s.startswith("G"): return "Grass"
    return "Hard"

def build_match_dataset(df_matches: pd.DataFrame) -> pd.DataFrame:
    # Keep only relevant columns
    keep = [
        "tourney_id", "tourney_name", "tourney_date", "tourney_level", "surface",
        "round", "best_of", "winner_id", "winner_name", "winner_age", "winner_ht",
        "loser_id", "loser_name", "loser_age", "loser_ht"
    ]
    df = df_matches[keep].copy()
    df["surface"] = df["surface"].map(_normalize_surface)
    df["best_of_5"] = (df["best_of"] == 5).astype(int)

    # Round & level encoding
    round_map = {"R128": 1, "R64": 2, "R32": 3, "R16": 4, "QF": 5, "SF": 6, "F": 7, "RR": 3, "BR": 7}
    level_map = {"G": 4, "M": 3, "A": 2, "C": 1, "F": 1}
    df["round_code"] = df["round"].map(round_map).fillna(3).astype(int)
    df["tourney_level_code"] = df["tourney_level"].map(level_map).fillna(2).astype(int)

    # Elo trackers
    elo = Elo(base=1500, k=24)
    selo = SurfaceElo(base=1500, k=24)

    # Head-to-head tracker
    h2h = {}

    cols = {
        "p1_id": [], "p2_id": [],
        "p1_elo": [], "p2_elo": [],
        "p1_surface_elo": [], "p2_surface_elo": [],
        "h2h_winrate_diff": []
    }

    last_matches = {}
    pbar = tqdm(total=len(df), desc="Engineering features")

    for _, row in df.iterrows():
        s = row["surface"]
        w = int(row["winner_id"]); l = int(row["loser_id"])

        # Get ELO values
        w_elo = elo.get(w); l_elo = elo.get(l)
        w_selo = selo.get(s, w); l_selo = selo.get(s, l)

        # Head-to-head winrate
        key = tuple(sorted((w, l)))
        if key not in h2h:
            h2h[key] = {w: 0, l: 0}
        total_meetings = h2h[key][w] + h2h[key][l]

        if total_meetings == 0:
            h2h_diff = 0.0
        else:
            wr_w = h2h[key][w] / total_meetings
            wr_l = h2h[key][l] / total_meetings
            h2h_diff = wr_w - wr_l

        # Store row
        cols["p1_id"].append(w)
        cols["p2_id"].append(l)
        cols["p1_elo"].append(w_elo)
        cols["p2_elo"].append(l_elo)
        cols["p1_surface_elo"].append(w_selo)
        cols["p2_surface_elo"].append(l_selo)
        cols["h2h_winrate_diff"].append(h2h_diff)

        # Update Elo and Head-to-Head
        elo.update(w, l)
        selo.update(s, w, l)
        h2h[key][w] += 1

        # Update recent form
        for pid, won in [(w, 1), (l, 0)]:
            arr = last_matches.get(pid, [])
            arr.append(won)
            if len(arr) > 50:
                arr.pop(0)
            last_matches[pid] = arr

        pbar.update(1)
    pbar.close()

    # Merge feature columns
    df = df.assign(**cols)

    def recent_wr(pid):
        arr = last_matches.get(pid, [])
        return float(np.mean(arr)) if arr else 0.5

    df["p1_recent_wr"] = df["p1_id"].map(recent_wr)
    df["p2_recent_wr"] = df["p2_id"].map(recent_wr)

    # Derived features
    df["elo_diff"] = df["p1_elo"] - df["p2_elo"]
    df["surface_elo_diff"] = df["p1_surface_elo"] - df["p2_surface_elo"]
    df["age_diff"] = df["winner_age"].fillna(0) - df["loser_age"].fillna(0)
    df["height_diff"] = df["winner_ht"].fillna(0) - df["loser_ht"].fillna(0)
    df["recent_win_rate_diff"] = df["p1_recent_wr"] - df["p2_recent_wr"]

    df["is_clay"] = (df["surface"] == "Clay").astype(int)
    df["is_grass"] = (df["surface"] == "Grass").astype(int)
    df["is_hard"] = (df["surface"] == "Hard").astype(int)

    # Winner rows
    df["p1_wins"] = 1

    # Final column selection
    final = [
        "p1_id", "p2_id", "p1_wins", "elo_diff", "surface_elo_diff", "age_diff",
        "height_diff", "recent_win_rate_diff", "h2h_winrate_diff",
        "is_clay", "is_grass", "is_hard", "best_of_5", "round_code",
        "tourney_level_code", "tourney_id", "tourney_name", "tourney_date",
        "surface", "round"
    ]

    df = df[final]

    # ===============================
    # 🪞 MIRROR DATASET (add losing side)
    # ===============================
    mirrored = df.copy()
    mirrored["p1_id"], mirrored["p2_id"] = df["p2_id"], df["p1_id"]

    # Flip sign for all difference features
    mirrored["elo_diff"] = -df["elo_diff"]
    mirrored["surface_elo_diff"] = -df["surface_elo_diff"]
    mirrored["age_diff"] = -df["age_diff"]
    mirrored["height_diff"] = -df["height_diff"]
    mirrored["recent_win_rate_diff"] = -df["recent_win_rate_diff"]
    mirrored["h2h_winrate_diff"] = -df["h2h_winrate_diff"]

    mirrored["p1_wins"] = 0

    # Combine original + mirrored
    df = pd.concat([df, mirrored], ignore_index=True)

    return df

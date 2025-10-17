
import pandas as pd
import numpy as np
from tqdm import tqdm
from .elo import Elo, SurfaceElo

def _normalize_surface(s):
    if pd.isna(s):
        return "Hard"
    s = str(s).strip().capitalize()
    if s.startswith("H"): return "Hard"
    if s.startswith("C"): return "Clay"
    if s.startswith("G"): return "Grass"
    return "Hard"

def build_match_dataset(df_matches: pd.DataFrame) -> pd.DataFrame:
    keep = ["tourney_id","tourney_name","tourney_date","tourney_level","surface",
            "round","best_of","winner_id","winner_name","winner_age","winner_ht",
            "loser_id","loser_name","loser_age","loser_ht"]
    df = df_matches[keep].copy()
    df["surface"] = df["surface"].map(_normalize_surface)
    df["best_of_5"] = (df["best_of"]==5).astype(int)
    round_map = {"R128":1,"R64":2,"R32":3,"R16":4,"QF":5,"SF":6,"F":7,"RR":3,"BR":7}
    level_map = {"G":4,"M":3,"A":2,"C":1,"F":1}
    df["round_code"] = df["round"].map(round_map).fillna(3).astype(int)
    df["tourney_level_code"] = df["tourney_level"].map(level_map).fillna(2).astype(int)

    elo = Elo(base=1500, k=24)
    selo = SurfaceElo(base=1500, k=24)

    cols = {"p1_id":[],"p2_id":[],"p1_elo":[],"p2_elo":[],"p1_surface_elo":[],"p2_surface_elo":[]}
    last_matches = {}

    pbar = tqdm(total=len(df), desc="Engineering features")
    for _, row in df.iterrows():
        s = row["surface"]
        w = int(row["winner_id"]); l = int(row["loser_id"])
        w_elo = elo.get(w); l_elo = elo.get(l)
        w_selo = selo.get(s, w); l_selo = selo.get(s, l)
        cols["p1_id"].append(w); cols["p2_id"].append(l)
        cols["p1_elo"].append(w_elo); cols["p2_elo"].append(l_elo)
        cols["p1_surface_elo"].append(w_selo); cols["p2_surface_elo"].append(l_selo)

        # update elo tables
        elo.update(w, l); selo.update(s, w, l)

        # recent form
        for pid, won in [(w,1),(l,0)]:
            arr = last_matches.get(pid, [])
            arr.append(won)
            if len(arr)>50: arr.pop(0)
            last_matches[pid]=arr
        pbar.update(1)
    pbar.close()

    df = df.assign(**cols)
    def recent_wr(pid): 
        arr = last_matches.get(pid, [])
        return float(np.mean(arr)) if arr else 0.5
    df["p1_recent_wr"] = df["p1_id"].map(recent_wr)
    df["p2_recent_wr"] = df["p2_id"].map(recent_wr)

    df["elo_diff"] = df["p1_elo"] - df["p2_elo"]
    df["surface_elo_diff"] = df["p1_surface_elo"] - df["p2_surface_elo"]
    df["age_diff"] = df["winner_age"].fillna(0) - df["loser_age"].fillna(0)
    df["height_diff"] = df["winner_ht"].fillna(0) - df["loser_ht"].fillna(0)
    df["recent_win_rate_diff"] = df["p1_recent_wr"] - df["p2_recent_wr"]

    df["is_clay"] = (df["surface"]=="Clay").astype(int)
    df["is_grass"] = (df["surface"]=="Grass").astype(int)
    df["is_hard"] = (df["surface"]=="Hard").astype(int)

    df["p1_wins"] = 1  # by construction we set p1 as the winner row
    final = ["p1_id","p2_id","p1_wins","elo_diff","surface_elo_diff","age_diff","height_diff",
             "recent_win_rate_diff","is_clay","is_grass","is_hard","best_of_5","round_code",
             "tourney_level_code","tourney_id","tourney_name","tourney_date","surface","round"]
    return df[final]

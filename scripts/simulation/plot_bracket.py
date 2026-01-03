# scripts/plot_bracket.py
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# ------- style knobs -------
COL_W         = 3.2    # horizontal width per round
ROW_GAP       = 1.1    # vertical gap between first-round matches
TXT           = 9      # base font size
LINE_COLOR    = "#c7c7c7"
WINNER_COLOR  = "#111111"
LOSER_COLOR   = "#8c8c8c"
CHAMP_COLOR   = "#DAA520"
LINE_W        = 1.2
LEFT_PAD      = 0.8
RIGHT_PAD     = 3.5    # room for champion label on the right
TOP_PAD       = 1.2
BOT_PAD       = 0.8

def _round_name(r, n_rounds):
    names = {5:"Quarterfinals", 6:"Semifinals", 7:"Final"}
    # fallbacks for 64/128 draws
    if r == n_rounds: return "Final"
    if r == n_rounds-1: return "Semifinals"
    if r == n_rounds-2: return "Quarterfinals"
    return f"Round {r}"

def draw_bracket(pred_csv: str, out_file: str = "outputs/ao2025_bracket.png"):
    df = pd.read_csv(pred_csv)

    # required columns
    if "round" not in df.columns or "winner" not in df.columns:
        raise ValueError("CSV must have at least columns: round, winner. (loser, prob are optional)")
    if "loser" not in df.columns:
        df["loser"] = ""
    # create a match index within each round if not present
    if "match_idx" not in df.columns:
        df["match_idx"] = df.groupby("round").cumcount()

    rounds = sorted(df["round"].unique())
    n_rounds = len(rounds)
    first_round = rounds[0]
    last_round  = rounds[-1]

    # how many matches in round 1 -> determines height
    n_first = df[df["round"] == first_round].shape[0]
    # y for round 1: evenly spaced rows
    y_r1 = [BOT_PAD + i*ROW_GAP for i in range(n_first)]

    # compute (x,y) positions for every match as {(r, i): (x,y)}
    pos = {}
    # round 1 positions
    for i, y in enumerate(y_r1):
        pos[(first_round, i)] = (LEFT_PAD, y)

    # higher rounds: set y as average of the two children below
    for r in rounds[1:]:
        n_matches = df[df["round"] == r].shape[0]
        for i in range(n_matches):
            # children in previous round are (2*i) and (2*i+1)
            y1 = pos[(r-1, 2*i)][1]
            y2 = pos[(r-1, 2*i+1)][1]
            y  = 0.5*(y1 + y2)
            x  = LEFT_PAD + (r-1)*COL_W
            pos[(r, i)] = (x, y)

    # figure size from geometry
    height_units = y_r1[-1] + BOT_PAD + TOP_PAD
    width_units  = LEFT_PAD + (n_rounds-1)*COL_W + RIGHT_PAD
    fig_w = max(12, width_units)     # sensible minimums
    fig_h = max(6, height_units/1.2)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    ax.set_xlim(0, width_units)
    ax.set_ylim(0, height_units)

    # draw round labels
    for r in rounds:
        x, _ = pos[(r, 0)]
        ax.text(x + COL_W*0.45, height_units - TOP_PAD*0.7,
                _round_name(r, n_rounds),
                ha="center", va="bottom",
                fontsize=TXT+2, weight="bold", color="#333333")

    # draw matches
    for r in rounds:
        r_df = df[df["round"] == r].sort_values("match_idx").reset_index(drop=True)
        for _, row in r_df.iterrows():
            i   = int(row["match_idx"])
            x,y = pos[(r, i)]

            # names
            ax.text(x, y+0.22, str(row["winner"]), ha="left", va="center",
                    fontsize=TXT, color=WINNER_COLOR, weight="bold")
            if isinstance(row["loser"], str) and row["loser"].strip():
                ax.text(x, y-0.22, str(row["loser"]), ha="left", va="center",
                        fontsize=TXT-1, color=LOSER_COLOR)

            # classic bracket connectors: ─┐ then vertical, then ─ to parent
            if r < last_round:
                # short horizontal from names to vertical spine
                x1 = x + 1.4
                ax.add_line(Line2D([x+0.9, x1], [y, y], color=LINE_COLOR, lw=LINE_W))
                # vertical spine for the pair
                # it spans between child A (i) and child B (i^1) only once (for i even)
                if i % 2 == 0:
                    y_low  = y
                    y_high = pos[(r, i+1)][1]
                    ax.add_line(Line2D([x1, x1], [y_low, y_high], color=LINE_COLOR, lw=LINE_W))
                # horizontal to parent (center of spine goes to parent)
                parent_i = i//2
                xp, yp   = pos[(r+1, parent_i)]
                ax.add_line(Line2D([x1, xp-0.6], [ (y + pos[(r, i ^ 1)][1])/2 , (y + pos[(r, i ^ 1)][1])/2 ],
                                   color=LINE_COLOR, lw=LINE_W))

    # champion
    champ_row = df[df["round"] == last_round].iloc[0]
    champ_x, champ_y = pos[(last_round, int(champ_row["match_idx"]))]
    ax.text(champ_x + 1.0, champ_y, f"🏆 {champ_row['winner']}",
            fontsize=TXT+4, color=CHAMP_COLOR, ha="left", va="center", weight="bold")

    # gentle margins so nothing clips even with long names
    ax.margins(x=0.02, y=0.03)
    plt.tight_layout()
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    print(f"✅ Bracket saved to {out_file}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pred_csv", required=True, help="CSV with columns: round, winner, (optional) loser, (optional) match_idx")
    p.add_argument("--out", default="outputs/ao2025_bracket.png")
    args = p.parse_args()
    draw_bracket(args.pred_csv, args.out)

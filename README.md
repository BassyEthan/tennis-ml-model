# ✅ Tennis ML — Perfect Starter

This repo is **ready**. It includes a correct `data/raw/` directory (with a `.gitkeep` so it always appears). 
Drop Jeff Sackmann ATP CSVs into `data/raw/` and run the scripts.

## Folder Tree
```
tennis-ml-perfect-starter/
├─ data/
│  ├─ raw/           # <-- put atp_matches_YYYY.csv here
│  ├─ interim/
│  └─ processed/
├─ models/
├─ reports/
│  └─ figures/
├─ scripts/
│  ├─ build_dataset.py
│  ├─ train_tree.py
│  ├─ train_rf.py
│  ├─ train_xgb.py
│  ├─ evaluate.py
│  └─ simulate_tournament.py
├─ src/
│  ├─ data/ingest.py
│  ├─ features/elo.py
│  ├─ features/engineer.py
│  ├─ models/train_common.py
│  ├─ models/train_tree.py
│  ├─ models/train_rf.py
│  ├─ models/train_xgb.py
│  ├─ eval/evaluate.py
│  └─ sim/tournament.py
├─ requirements.txt
└─ README.md
```

## Quickstart
```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python3 -m pip install -r requirements.txt

# Put files into data/raw/ before this step:
#   - atp_matches_2023.csv (and/or other years)
#   - atp_players.csv (optional)

python3 -m scripts.build_dataset
python3 -m scripts.train_rf
python3 -m scripts.evaluate
```

If Python can’t find modules, run from the project root with `-m`, as shown above.

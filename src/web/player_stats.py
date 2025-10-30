"""
Player statistics lookup utility for web predictions.
Builds player database from match history and provides stats lookup.
"""

import pandas as pd
import numpy as np
from collections import defaultdict
from src.data.ingest import load_matches
from src.features.elo import Elo, SurfaceElo
from pathlib import Path


class PlayerStatsDB:
    """Database of player statistics computed from match history."""
    
    def __init__(self, raw_data_dir="data/raw"):
        self.raw_data_dir = raw_data_dir
        self.name_to_id = {}
        self.id_to_name = {}
        self.player_stats = {}
        self._build_database()
    
    def _build_database(self):
        """Build player statistics from raw match data."""
        print("Loading match data...")
        matches = load_matches(self.raw_data_dir)
        matches = matches.sort_values("tourney_date")
        
        # Build name to ID mapping (use most recent ID for each name)
        print("Building player name mapping...")
        for _, row in matches.iterrows():
            winner_name = str(row.get("winner_name", "")).strip()
            winner_id = row.get("winner_id")
            loser_name = str(row.get("loser_name", "")).strip()
            loser_id = row.get("loser_id")
            
            if winner_name and pd.notna(winner_id):
                self.name_to_id[winner_name.lower()] = int(winner_id)
                self.id_to_name[int(winner_id)] = winner_name
            
            if loser_name and pd.notna(loser_id):
                self.name_to_id[loser_name.lower()] = int(loser_id)
                self.id_to_name[int(loser_id)] = loser_name
        
        # Initialize Elo systems
        elo = Elo(base=1500, k=24)
        selo = SurfaceElo(base=1500, k=24)
        
        # Track recent matches for win rate
        last_matches = defaultdict(list)
        
        # Head-to-head tracker
        h2h_matches = defaultdict(lambda: defaultdict(int))
        
        # Process matches chronologically to build stats
        print("Computing player statistics...")
        matches["surface"] = matches["surface"].fillna("Hard").astype(str).str.capitalize()
        matches["surface"] = matches["surface"].apply(self._normalize_surface)
        
        for _, row in matches.iterrows():
            surface = row["surface"]
            winner_id = int(row["winner_id"])
            loser_id = int(row["loser_id"])
            winner_age = row.get("winner_age")
            loser_age = row.get("loser_age")
            winner_ht = row.get("winner_ht")
            loser_ht = row.get("loser_ht")
            
            # Update Elo
            elo.update(winner_id, loser_id)
            selo.update(surface, winner_id, loser_id)
            
            # Update recent matches (keep last 50)
            last_matches[winner_id].append(1)
            last_matches[loser_id].append(0)
            if len(last_matches[winner_id]) > 50:
                last_matches[winner_id].pop(0)
            if len(last_matches[loser_id]) > 50:
                last_matches[loser_id].pop(0)
            
            # Update H2H
            key = tuple(sorted([winner_id, loser_id]))
            h2h_matches[key][winner_id] += 1
            
            # Store latest stats for each player
            winner_elo = elo.get(winner_id)
            loser_elo = elo.get(loser_id)
            winner_selo = selo.get(surface, winner_id)
            loser_selo = selo.get(surface, loser_id)
            
            # Update player stats (keep most recent)
            if winner_id not in self.player_stats:
                self.player_stats[winner_id] = {
                    "elo": winner_elo,
                    "surface_elo": {},
                    "age": winner_age if pd.notna(winner_age) else None,
                    "height": winner_ht if pd.notna(winner_ht) else None,
                    "recent_win_rate": 0.5,
                    "name": self.id_to_name.get(winner_id, "Unknown")
                }
            
            # Update stats (keep most recent values)
            self.player_stats[winner_id]["elo"] = winner_elo
            self.player_stats[winner_id]["surface_elo"][surface] = winner_selo
            if pd.notna(winner_age):
                self.player_stats[winner_id]["age"] = winner_age
            if pd.notna(winner_ht):
                self.player_stats[winner_id]["height"] = winner_ht
            self.player_stats[winner_id]["recent_win_rate"] = np.mean(last_matches[winner_id]) if last_matches[winner_id] else 0.5
            
            if loser_id not in self.player_stats:
                self.player_stats[loser_id] = {
                    "elo": loser_elo,
                    "surface_elo": {},
                    "age": loser_age if pd.notna(loser_age) else None,
                    "height": loser_ht if pd.notna(loser_ht) else None,
                    "recent_win_rate": 0.5,
                    "name": self.id_to_name.get(loser_id, "Unknown")
                }
            
            self.player_stats[loser_id]["elo"] = loser_elo
            self.player_stats[loser_id]["surface_elo"][surface] = loser_selo
            if pd.notna(loser_age):
                self.player_stats[loser_id]["age"] = loser_age
            if pd.notna(loser_ht):
                self.player_stats[loser_id]["height"] = loser_ht
            self.player_stats[loser_id]["recent_win_rate"] = np.mean(last_matches[loser_id]) if last_matches[loser_id] else 0.5
        
        # Store H2H data
        self.h2h_matches = h2h_matches
        
        print(f"Loaded stats for {len(self.player_stats)} players")
    
    def _normalize_surface(self, s):
        """Normalize surface strings to Hard, Clay, or Grass."""
        if pd.isna(s):
            return "Hard"
        s = str(s).strip().capitalize()
        if s.startswith("H"):
            return "Hard"
        if s.startswith("C"):
            return "Clay"
        if s.startswith("G"):
            return "Grass"
        return "Hard"
    
    def find_player(self, name):
        """Find player ID by name (case-insensitive, partial match)."""
        name_lower = name.lower().strip()
        
        # Exact match
        if name_lower in self.name_to_id:
            return self.name_to_id[name_lower]
        
        # Partial match
        for db_name, player_id in self.name_to_id.items():
            if name_lower in db_name or db_name in name_lower:
                return player_id
        
        # Try matching last name only
        name_parts = name_lower.split()
        if len(name_parts) >= 2:
            last_name = name_parts[-1]
            for db_name, player_id in self.name_to_id.items():
                if db_name.endswith(last_name) or last_name in db_name:
                    return player_id
        
        return None
    
    def get_player_stats(self, player_id):
        """Get statistics for a player."""
        if player_id not in self.player_stats:
            return None
        return self.player_stats[player_id]
    
    def get_h2h(self, player1_id, player2_id):
        """Get head-to-head win rate difference for two players."""
        key = tuple(sorted([player1_id, player2_id]))
        if key not in self.h2h_matches:
            return 0.0
        
        p1_wins = self.h2h_matches[key].get(player1_id, 0)
        p2_wins = self.h2h_matches[key].get(player2_id, 0)
        total = p1_wins + p2_wins
        
        if total == 0:
            return 0.0
        
        p1_wr = p1_wins / total
        p2_wr = p2_wins / total
        return p1_wr - p2_wr
    
    def get_surface_elo(self, player_id, surface="Hard"):
        """Get surface-specific Elo for a player."""
        if player_id not in self.player_stats:
            return 1500.0
        
        surface = self._normalize_surface(surface)
        surface_elos = self.player_stats[player_id].get("surface_elo", {})
        
        # Get specific surface, or average, or overall Elo
        if surface in surface_elos:
            return surface_elos[surface]
        elif surface_elos:
            return np.mean(list(surface_elos.values()))
        else:
            return self.player_stats[player_id].get("elo", 1500.0)


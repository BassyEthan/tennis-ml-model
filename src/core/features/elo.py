
from collections import defaultdict

class Elo:
    def __init__(self, base=1500.0, k=24.0):
        self.base = base
        self.k = k
        self.rating = defaultdict(lambda: base)

    def expected(self, ra, rb):
        return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

    def update(self, winner, loser):
        ra = self.rating[winner]
        rb = self.rating[loser]
        ea = self.expected(ra, rb)
        self.rating[winner] = ra + self.k * (1 - ea)
        self.rating[loser]  = rb + self.k * (0 - (1 - ea))

    def get(self, player_id):
        return float(self.rating[player_id])

class SurfaceElo:
    SURFACES = ("Hard", "Clay", "Grass")
    def __init__(self, base=1500.0, k=24.0):
        self.tables = {s: Elo(base=base, k=k) for s in self.SURFACES}
    def update(self, surface, winner, loser):
        surf = surface if surface in self.tables else "Hard"
        self.tables[surf].update(winner, loser)
    def get(self, surface, player_id):
        surf = surface if surface in self.tables else "Hard"
        return self.tables[surf].get(player_id)

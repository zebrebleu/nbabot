"""
Réglages du module TENNIS (ATP + WTA). Tous les seuils des filtres sont ici.
Les clés API et chemins communs restent dans config.py.
"""
from __future__ import annotations

import config

TOURS = ("atp", "wta")

# ---------------------------------------------------------------------------
# Matchs analysés et cotes
# ---------------------------------------------------------------------------
LOOKAHEAD_HOURS = 30            # matchs qui commencent dans les 30 prochaines heures
MAX_TOURNAMENTS = 6             # garde-fou quota : 1 crédit The Odds API par tournoi et par passage
REFERENCE_BOOKMAKER = config.REFERENCE_BOOKMAKER   # unibet_fr
ODDS_MIN = 1.25
ODDS_MAX = 1.80
LINE_RISE_MAX_ABS = 0.06        # hausse de cote du favori jugée anormale
LINE_RISE_MAX_PCT = 0.04

# Pari tennis (séparé du pari NBA) : 1 ou 2 matchs, cote totale max
BET_MAX_LEGS = 2
BET_MAX_ODDS = 1.80
BET_MIN_ODDS = 1.25

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
# Fatigue : match "long" joué juste avant
FATIGUE_WINDOW_HOURS = 30
LONG_MATCH_BO3 = {"sets": 3, "games": 30}   # 3 sets, ou 30 jeux et plus
LONG_MATCH_BO5 = {"sets": 5, "games": 45}   # 5 sets, ou 45 jeux et plus

# Abandon ou forfait récent (signe de blessure)
RETIREMENT_DAYS = 21

# Forme récente (10 derniers matchs, toutes surfaces)
FORM_GAMES = 10
FORM_MIN_GAMES = 5              # en dessous : alerte "peu de matchs" (pas de rejet)
FORM_MIN_RATE = 0.60            # 6 victoires sur 10 minimum

# Forme sur la surface du tournoi (saison en cours + saison passée si chargée)
SURFACE_MIN_GAMES = 5
SURFACE_MIN_RATE = 0.55

# Dynamique croisée
DOG_HOT_LAST = 5                # 5 derniers matchs de l'outsider...
DOG_HOT_RATE = 0.80             # ...avec 80 % de victoires (4/5)
FAV_DOUBT_RATE = 0.50           # favori à 50 % ou moins sur ses 10 derniers

# Classement : le favori ne doit pas être nettement moins bien classé que l'outsider
RANK_TOLERANCE = 10             # places

# Confrontations directes (sur la saison en cours + les 3 précédentes : config.HISTORY_SEASONS)
H2H_MIN_MEETINGS = 2

# Forme sur la surface : calculée sur la saison en cours + les 3 précédentes

# ---------------------------------------------------------------------------
# Surfaces : mots-clés dans le nom du tournoi (le reste = dur)
# ---------------------------------------------------------------------------
SURFACE_KEYWORDS = {
    "terre battue": [
        "french open", "roland", "madrid", "rome", "italian", "internazionali", "monte",
        "barcelona", "hamburg", "charleston", "bastad", "gstaad", "kitzbuhel", "umag",
        "rio", "buenos aires", "santiago", "estoril", "munich", "lyon", "geneva",
        "marrakech", "houston", "palermo", "prague", "rabat", "bogota", "strasbourg",
        "parma", "bucharest", "lausanne", "budapest", "iasi", "porsche", "stuttgart open wta",
    ],
    "gazon": [
        "wimbledon", "halle", "queen", "hertogenbosch", "eastbourne", "mallorca",
        "berlin", "bad homburg", "nottingham", "birmingham", "newport", "boss open",
    ],
}
GRAND_SLAM_KEYWORDS = ["australian open", "aus open", "french open", "roland", "wimbledon", "us open"]

ESPN_CACHE_HOURS = 6            # l'historique complet de la saison est lourd (~20 Mo par circuit)

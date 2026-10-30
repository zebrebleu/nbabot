"""
Configuration centrale : clés API, seuils des filtres, listes manuelles.

Tous les seuils des filtres stricts sont ici, pour pouvoir les ajuster
sans toucher à la logique.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:  # python-dotenv est optionnel : on peut aussi exporter la variable à la main
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
ODDS_HISTORY_FILE = DATA_DIR / "odds_history.json"
REPORTS_DIR = BASE_DIR / "reports"

DISPLAY_TZ = "Europe/Paris"

# ---------------------------------------------------------------------------
# Sources de données
# ---------------------------------------------------------------------------
# The Odds API (https://the-odds-api.com) : cotes Moneyline, aucune connexion à Unibet.
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
REFERENCE_BOOKMAKER = "unibet_fr"   # cote de référence (celle que tu joueras)
SHARP_BOOKMAKER = "pinnacle"        # référence "marché" pour estimer la probabilité réelle
# 10 bookmakers max = 1 seul crédit API par appel (marché h2h).
ODDS_BOOKMAKERS = ["unibet_fr", "winamax_fr", "betclic_fr", "parionssport_fr", "pinnacle"]

ODDS_CACHE_MINUTES = 15
ESPN_CACHE_MINUTES = 60
INJURIES_CACHE_MINUTES = 15


# Surnoms valides des 30 franchises (clé utilisée partout dans le projet)
NBA_TEAM_KEYS = {
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "mavericks", "nuggets",
    "pistons", "warriors", "rockets", "pacers", "clippers", "lakers", "grizzlies", "heat",
    "bucks", "timberwolves", "pelicans", "knicks", "thunder", "magic", "76ers", "suns",
    "blazers", "kings", "spurs", "raptors", "jazz", "wizards",
}

# ---------------------------------------------------------------------------
# 1. Filtre de cote
# ---------------------------------------------------------------------------
ODDS_MIN = 1.25               # cote individuelle minimale d'un favori retenu
ODDS_MAX = 1.80               # cote individuelle maximale (un pari simple peut aller jusqu'à 1.80)
LINE_RISE_MAX_ABS = 0.06       # ex. 1.30 -> 1.36 = rejet
LINE_RISE_MAX_PCT = 0.04       # ou +4 %
LINE_MIN_OBSERVATION_MINUTES = 60
LINE_REQUIRE_HISTORY = False   # True = rejeter tant qu'on n'a pas d'historique de cote

# ---------------------------------------------------------------------------
# 2. Calendrier & fatigue
# ---------------------------------------------------------------------------
B2B_MAX_GAP_HOURS = 30
TRAP_GAME_WINDOW_HOURS = 48
ROAD_TRIP_MAX_CONSECUTIVE = 2   # 3e match consécutif à l'extérieur = rejet

# Contenders : top N du classement officiel une fois que les équipes ont assez de matchs...
CONTENDERS_TOP_N = 6
CONTENDERS_MIN_GAMES = 15
# ...sinon, cette liste statique (cadors habituels des deux conférences).
# Basée sur la hiérarchie de la saison 2025-26 : À AJUSTER selon ton avis.
CONTENDERS_FALLBACK = {
    # Conférence Ouest
    "thunder", "nuggets", "rockets", "spurs", "timberwolves",
    # Conférence Est
    "cavaliers", "knicks", "pistons",
}

# ---------------------------------------------------------------------------
# 3. Forme & dynamique — seuils selon la période de la saison
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeasonThresholds:
    label: str
    L10_MIN_GAMES: int            # matchs joués requis pour la dynamique croisée
    VENUE_FORM_GAMES: int         # derniers matchs au même lieu (domicile / extérieur)
    VENUE_FORM_MIN_WIN_RATE: float
    INSUFFICIENT_DATA: str        # "reject" (strict) ou "warn" (validé avec alerte)

    def venue_min_wins(self, n_games: int) -> int:
        return math.ceil(self.VENUE_FORM_MIN_WIN_RATE * n_games - 1e-9)


NORMAL_SEASON = SeasonThresholds(
    label="saison régulière",
    L10_MIN_GAMES=10,
    VENUE_FORM_GAMES=5,
    VENUE_FORM_MIN_WIN_RATE=0.6,      # 3/5
    INSUFFICIENT_DATA="reject",
)

EARLY_SEASON = SeasonThresholds(
    label="début de saison (seuils assouplis)",
    L10_MIN_GAMES=5,
    VENUE_FORM_GAMES=3,
    VENUE_FORM_MIN_WIN_RATE=0.6,      # 2/3
    # "reject" : une équipe sous ces minimums reste rejetée.
    # "warn"   : elle passe ce filtre, avec une alerte "à vérifier" dans le rapport
    #            (sauf si le peu de matchs joués est déjà négatif : là, rejet).
    INSUFFICIENT_DATA="warn",
)

# Matchs joués minimum par équipe (SEASON_MIN_GAMES, 0 = aucun contrôle).
#  - Pendant le début de saison (voir EARLY_SEASON_MODE) avec EARLY_SEASON_ALLOW_BETS = True :
#    le match reste jouable, avec une alerte et une confiance plafonnée à « Prudente ».
#  - Le reste de la saison (ou EARLY_SEASON_ALLOW_BETS = False) : aucun pronostic sur le match.
SEASON_MIN_GAMES = 10
EARLY_SEASON_ALLOW_BETS = True
GAMES_PER_WEEK = 3.5            # rythme moyen d'une équipe NBA (pour estimer la reprise)

# "auto" = début de saison du 1er octobre au EARLY_SEASON_END inclus ; "on" / "off" = forcé
EARLY_SEASON_MODE = "auto"
EARLY_SEASON_END = (11, 30)           # (mois, jour)


def season_thresholds(when: datetime) -> SeasonThresholds:
    if EARLY_SEASON_MODE == "on":
        return EARLY_SEASON
    if EARLY_SEASON_MODE == "off":
        return NORMAL_SEASON
    in_early = (10, 1) <= (when.month, when.day) <= EARLY_SEASON_END
    return EARLY_SEASON if in_early else NORMAL_SEASON


L10_GAMES = 10                  # taille de la fenêtre de forme récente
# Seuils exprimés en taux pour rester valables quel que soit le nombre de matchs
DOG_HOT_MIN_RATE = 0.7          # outsider "en feu" : >= 70 % de victoires (7/10, 4/5)
FAV_DOUBT_MAX_RATE = 0.5        # favori "qui doute" : <= 50 % (5/10, 2/5)
DOG_HOT_STREAK = 4

# ---------------------------------------------------------------------------
# 4. Effectif & contexte
# ---------------------------------------------------------------------------
# Joueurs clés par équipe : 1er nom = franchise player, suivants = titulaires majeurs.
# Clé = surnom de la franchise (voir NBA_TEAM_KEYS). Noms tels qu'écrits par ESPN
# (accents et majuscules ignorés). EXEMPLES À VÉRIFIER : transferts et blessures longues
# changent vite. Une équipe absente (ou avec une liste vide) passe en règle de secours.
KEY_PLAYERS: dict[str, list[str]] = {
    "thunder":      ["Shai Gilgeous-Alexander", "Jalen Williams", "Chet Holmgren"],
    "nuggets":      ["Nikola Jokic", "Jamal Murray"],
    "spurs":        ["Victor Wembanyama", "De'Aaron Fox"],
    "lakers":       ["Luka Doncic", "Austin Reaves"],
    "timberwolves": ["Anthony Edwards", "Julius Randle"],
    "knicks":       ["Jalen Brunson", "Karl-Anthony Towns"],
    "cavaliers":    ["Donovan Mitchell", "Evan Mobley"],
    "pistons":      ["Cade Cunningham", "Jalen Duren"],
    # "celtics":    ["...", "..."],
}
BLOCKING_STATUSES = {"out", "doubtful", "questionable", "day-to-day", "game-time decision", "gtd"}
KEY_STARTERS_MAX_ABSENT = 1     # 2 titulaires majeurs absents/incertains = rejet
GENERIC_MAX_ABSENT = 3          # règle de secours : 3 absents/incertains = rejet

TANKING_MONTHS = {3, 4}
TANKING_BOTTOM_N = 8

# ---------------------------------------------------------------------------
# Pari proposé : 1 match (simple) ou 2 matchs (combiné), cote totale plafonnée
# ---------------------------------------------------------------------------
BET_MAX_LEGS = 2              # 1 ou 2 matchs maximum
BET_MAX_ODDS = 2.00           # cote totale maximale du pari proposé (simple ou combiné)
BET_MIN_ODDS = 1.25           # cote totale minimale (ex. 1.50 pour écarter les simples trop bas)
# Le bot choisit l'option (simple ou combiné) qui maximise :
#   valeur attendue estimée (proba. marché x cote) + BET_QUALITY_WEIGHT x qualité des filtres
BET_QUALITY_WEIGHT = 0.10
MARKET_MARGIN = 0.045         # marge bookmaker retirée quand aucune cote de référence n'existe

# ---------------------------------------------------------------------------
# Mise conseillée (NBA et tennis) : part de la mise de base selon la confiance.
# Combiné : on prend la confiance la plus basse de ses matchs.
# ---------------------------------------------------------------------------
BASE_STAKE = 100              # €
STAKE_SHARE = {"Élevée": 0.40, "Moyenne": 0.25, "Prudente": 0.15}   # 40 € / 25 € / 15 €

# ---------------------------------------------------------------------------
# Historique : nombre de saisons passées chargées en plus de la saison en cours
# ---------------------------------------------------------------------------
HISTORY_SEASONS = 3
LONG_CACHE_DIR = DATA_DIR / "cache_long"    # saisons terminées (conservé entre deux passages GitHub)

# Adresse du site (utilisée dans les questions envoyées à Claude)
SITE_URL = "https://zebrebleu.github.io/nbabot/"


def validate() -> list[str]:
    """Repère les fautes de frappe dans les listes manuelles (sans bloquer le script)."""
    problems = []
    for key in CONTENDERS_FALLBACK - NBA_TEAM_KEYS:
        problems.append(f"CONTENDERS_FALLBACK : équipe inconnue '{key}'")
    for key, players in KEY_PLAYERS.items():
        if key not in NBA_TEAM_KEYS:
            problems.append(f"KEY_PLAYERS : équipe inconnue '{key}' (ignorée)")
        elif not isinstance(players, (list, tuple)) or not all(isinstance(p, str) for p in players):
            problems.append(f"KEY_PLAYERS['{key}'] doit être une liste de noms (règle de secours appliquée)")
    for p in problems:
        log.warning(p)
    return problems

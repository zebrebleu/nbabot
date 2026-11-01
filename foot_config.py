"""
Réglages du module FOOT (Ligue 1, Liga, Premier League, Serie A, Bundesliga).
Pari étudié : victoire du favori (marché 1N2 « Résultat du match » sur Unibet).
"""
from __future__ import annotations

import config

# Championnat : (clé The Odds API, code ESPN, nom affiché)
LEAGUES = {
    "fra": ("soccer_france_ligue_one", "fra.1", "Ligue 1"),
    "esp": ("soccer_spain_la_liga", "esp.1", "Liga"),
    "eng": ("soccer_epl", "eng.1", "Premier League"),
    "ita": ("soccer_italy_serie_a", "ita.1", "Serie A"),
    "ger": ("soccer_germany_bundesliga", "ger.1", "Bundesliga"),
}
# Autres compétitions lues pour la fatigue et les matchs « pièges » (codes ESPN)
OTHER_COMPETITIONS = {
    "uefa.champions": "Ligue des champions", "uefa.europa": "Ligue Europa",
    "uefa.europa.conf": "Ligue Conférence", "fra.coupe_de_france": "Coupe de France",
    "esp.copa_del_rey": "Coupe du Roi", "eng.fa": "FA Cup", "eng.league_cup": "Carabao Cup",
    "ita.coppa_italia": "Coupe d'Italie", "ger.dfb_pokal": "Coupe d'Allemagne",
}

ANALYSIS_HOURS = 36             # matchs analysés : coup d'envoi dans les 36 prochaines heures
ODDS_WINDOW_HOURS = 60          # cotes lues jusqu'à 60 h avant (suivi des hausses d'un jour à l'autre)
REFERENCE_BOOKMAKER = config.REFERENCE_BOOKMAKER

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
ODDS_MIN = 1.25
ODDS_MAX = 1.80
LINE_RISE_MAX_ABS = 0.06
LINE_RISE_MAX_PCT = 0.04

# Anti-nul
DRAW_MAX_PROB = 0.27            # nul estimé par le marché (marge retirée) au-dessus = match trop équilibré
DRAW_RATE_GAMES = 10            # fréquence des nuls sur les 10 derniers matchs de championnat
DRAW_RATE_BOTH = 0.40           # les deux équipes à 40 % de nuls ou plus = rejet
DRAW_RATE_ONE = 0.50            # ou une seule à 50 % et plus

# Fatigue et calendrier (toutes compétitions)
REST_MIN_HOURS = 68             # moins de ~3 jours depuis le dernier match = fatigue
TRAP_WINDOW_HOURS = 80          # match de Coupe d'Europe dans les ~3 jours suivants = risque de rotation

# Forme (points par match, victoire 3 / nul 1)
FORM_GAMES = 5
FORM_MIN_GAMES = 3
FORM_MIN_PPG = 1.6              # ex. 8 points sur 15
VENUE_MIN_PPG = 1.4             # sur les 5 derniers à domicile / à l'extérieur
DOG_HOT_PPG = 2.2               # outsider « en feu » : 11 points sur 15 et plus

# Classement : le favori ne doit pas être nettement moins bien classé
RANK_TOLERANCE = 6

# Face-à-face (saison en cours + 3 précédentes)
H2H_MIN_MEETINGS = 3

# Pari foot : simple + combiné, mêmes limites que les autres sports
BET_MAX_LEGS = 2
BET_MIN_ODDS = config.BET_MIN_ODDS
BET_MAX_ODDS = config.BET_MAX_ODDS

# Noms d'équipes : The Odds API -> nom ESPN, quand le rapprochement automatique échoue
ALIASES = {
    "inter milan": "internazionale", "paris saint germain": "paris saint-germain",
    "olympique lyonnais": "lyon", "olympique marseille": "marseille",
    "wolverhampton wanderers": "wolverhampton", "tottenham hotspur": "tottenham",
    "brighton and hove albion": "brighton", "athletic bilbao": "athletic club",
    "borussia monchengladbach": "monchengladbach", "bayer leverkusen": "leverkusen",
}

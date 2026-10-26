"""
Données FICTIVES pour tester toute la chaîne sans clé API ni réseau.
Chaque match est construit pour déclencher (ou non) un filtre précis.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import Injury, Matchup, OddsQuote, Slate, TeamContext, TeamGame


def _team(key: str, name: str, results: str, venues: str, commence: datetime, *,
          last_game_hours_ago: float = 48, spacing_hours: float = 48,
          today_home: bool, future: list[tuple[str, float]] | None = None,
          injuries: list[Injury] | None = None) -> TeamContext:
    """results/venues : du plus ancien au plus récent ('W'/'L', 'H'/'A')."""
    n = len(results)
    games = []
    for i, (r, v) in enumerate(zip(results, venues)):
        margin = 4 + (i * 5 + len(key)) % 11          # écarts fictifs mais variés
        pts = 108 + (i * 7 + len(name)) % 14
        pf, pa = (pts, pts - margin) if r == "W" else (pts - margin, pts)
        games.append(TeamGame(
            commence - timedelta(hours=last_game_hours_ago + (n - 1 - i) * spacing_hours),
            "adversaire", v == "H", True, r == "W", pf, pa))
    games.append(TeamGame(commence, "adversaire du jour", today_home, False))
    for opp, hours_after in future or []:
        games.append(TeamGame(commence + timedelta(hours=hours_after), opp, True, False))
    games.sort(key=lambda g: g.date)
    wins = results.count("W")
    return TeamContext(key, name, schedule=games, injuries=injuries or [],
                       wins=wins, losses=n - wins)


def build_demo_slate() -> Slate:
    now = datetime.now(timezone.utc)
    c = now + timedelta(hours=8)
    opened = now - timedelta(hours=6)
    good_dog = "LLWLLWLLLW"
    dog_venues = "AHAHAHAHAH"

    def mk(i, home, away, uh, ua, oh, oa, ref=None):
        return Matchup(f"demo{i}", c, home, away,
                       OddsQuote(uh, ua, "unibet_fr"), ref,
                       OddsQuote(oh, oa, "unibet_fr"), opened, 3)

    m = [
        # 1. Valide
        mk(1, _team("celtics", "Boston Celtics", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True,
                    future=[("hornets", 48)]),
              _team("wizards", "Washington Wizards", good_dog, dog_venues, c, today_home=False),
           1.32, 3.40, 1.33, 3.30, OddsQuote(1.30, 3.75, "pinnacle")),
        # 2. Valide
        mk(2, _team("nuggets", "Denver Nuggets", "WLWWWLWWLW", "HHAHAHHAHH", c, today_home=True),
              _team("jazz", "Utah Jazz", "LWLLWLLWLL", dog_venues, c, today_home=False,
                    last_game_hours_ago=24),
           1.38, 3.05, 1.40, 2.95, OddsQuote(1.36, 3.30, "pinnacle")),
        # 3. Rejet : back-to-back à l'extérieur
        mk(3, _team("hornets", "Charlotte Hornets", good_dog, dog_venues, c, today_home=True),
              _team("thunder", "Oklahoma City Thunder", "WWWWLWWWWW", "HAHAHAHAHH", c,
                    today_home=False, last_game_hours_ago=24),
           3.60, 1.30, 3.50, 1.31),
        # 4. Rejet : trap game (Cavaliers dans 26 h)
        mk(4, _team("knicks", "New York Knicks", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True,
                    future=[("cavaliers", 26)]),
              _team("pistons", "Detroit Pistons", good_dog, dog_venues, c, today_home=False),
           1.35, 3.20, 1.35, 3.20),
        # 5. Rejet : outsider en feu, favori qui doute
        mk(5, _team("lakers", "Los Angeles Lakers", "WLLWLLWWLL", "HHHAHHAHHH", c, today_home=True),
              _team("kings", "Sacramento Kings", "WWLWWWWWLW", dog_venues, c, today_home=False),
           1.40, 2.95, 1.42, 2.85),
        # 6. Rejet : franchise player Out
        mk(6, _team("bucks", "Milwaukee Bucks", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True,
                    injuries=[Injury("Franchise Demo", "Out", "Genou")]),
              _team("nets", "Brooklyn Nets", good_dog, dog_venues, c, today_home=False),
           1.28, 3.80, 1.27, 3.90),
        # 7. Rejet : cote hors fourchette
        mk(7, _team("heat", "Miami Heat", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True),
              _team("bulls", "Chicago Bulls", "WLWLWLWLWL", dog_venues, c, today_home=False),
           1.60, 2.35, 1.62, 2.30),
        # 8. Rejet : hausse anormale de cote (1.27 -> 1.36)
        mk(8, _team("suns", "Phoenix Suns", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True),
              _team("spurs", "San Antonio Spurs", good_dog, dog_venues, c, today_home=False),
           1.36, 3.15, 1.27, 3.90),
        # 9. Valide, avec un absent à vérifier (pas de joueurs clés configurés)
        mk(9, _team("cavaliers", "Cleveland Cavaliers", "WWWLWWLWWW", "HAHAHHAHAH", c, today_home=True,
                    injuries=[Injury("Remplaçant Demo", "Day-To-Day", "Cheville")]),
              _team("raptors", "Toronto Raptors", good_dog, dog_venues, c, today_home=False),
           1.44, 2.85, 1.45, 2.80, OddsQuote(1.41, 3.10, "pinnacle")),
        # 10. Rejet : règle de secours infirmerie (3 absents, équipe non configurée)
        mk(10, _team("hawks", "Atlanta Hawks", "WWLWWWLWWW", "HAHAHHAHAH", c, today_home=True,
                     injuries=[Injury("Joueur A Demo", "Out"), Injury("Joueur B Demo", "Questionable"),
                               Injury("Joueur C Demo", "Day-To-Day")]),
               _team("pelicans", "New Orleans Pelicans", good_dog, dog_venues, c, today_home=False),
            1.33, 3.35, 1.34, 3.30),
        # 11. Début de saison : seulement 5 matchs joués (3 à domicile, 3 victoires)
        mk(11, _team("magic", "Orlando Magic", "WWLWW", "HAHHA", c, today_home=True),
               _team("grizzlies", "Memphis Grizzlies", "LWLLW", "AHAHA", c, today_home=False),
            1.42, 2.90, 1.43, 2.85, OddsQuote(1.39, 3.20, "pinnacle")),
    ]

    teams = sorted({t.key: t for mu in m for t in (mu.home, mu.away)}.values(),
                   key=lambda t: t.win_pct, reverse=True)
    for rank, t in enumerate(teams, 1):
        t.league_rank = rank

    return Slate(
        matchups=m,
        contenders={"thunder", "nuggets", "cavaliers", "knicks", "celtics", "rockets"},
        contenders_source="liste de démo",
        generated_at=now,
        key_players={"bucks": ["Franchise Demo", "Titulaire Demo"]},
        source_label="DONNÉES FICTIVES (--demo)",
    )

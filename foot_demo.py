"""Données FICTIVES (clubs et championnats inventés) pour tester le module foot sans clé ni réseau."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from foot_fetcher import FGame, FootMatch, FootSlate, FTeam, Quote3
from models import OddsQuote


def _team(tid: str, name: str, form: str, rank: int, *, home_form: str = "", last_days: float = 6,
          europe_before: float | None = None, europe_after: float | None = None, t0=None) -> FTeam:
    """form : résultats du plus ancien au plus récent (V/N/D), 10 matchs de championnat."""
    t = FTeam(tid, name, "demo.1", rank=rank, points=40 - rank * 2, played=10)
    for i, r in enumerate(form):
        gf, ga = {"V": (2, 0), "N": (1, 1), "D": (0, 1)}[r]
        home = (home_form[i] == "H") if home_form else i % 2 == 0
        t.games.append(FGame(t0 - timedelta(days=last_days + (len(form) - 1 - i) * 7), "x", "Adversaire Démo",
                             home, gf, ga, "Championnat"))
    t.calendar = list(t.games[-3:])
    if europe_before is not None:
        t.calendar.append(FGame(t0 - timedelta(days=europe_before), "e", "Club Européen", True, 1, 0, "Ligue des champions"))
    if europe_after is not None:
        t.calendar.append(FGame(t0 + timedelta(days=europe_after), "e", "Club Européen", False, None, None,
                                "Ligue des champions", completed=False))
    t.calendar.sort(key=lambda g: g.date)
    return t


def build_demo_slate() -> FootSlate:
    now = datetime.now(timezone.utc)
    t0 = now + timedelta(hours=6)

    def m(i, h, a, q, ref=None, lg="Démo Ligue A"):
        x = FootMatch(f"f{i}", t0 + timedelta(hours=i), h, a, q, ref, "demo.1", lg)
        x.opening, x.observed_since, x.n_observations = OddsQuote(q.home, q.away, "unibet_fr") if q else None, now - timedelta(hours=20), 2
        return x

    T = dict(t0=t0)
    ma = [
        m(1, _team("1", "Olympique Démo", "VVNVVVDVVV", 1, **T), _team("2", "Racing Exemple", "DNDVDNDDVD", 15, **T),
          Quote3(1.35, 5.20, 8.00, "unibet_fr"), Quote3(1.33, 5.60, 9.50, "pinnacle")),
        m(2, _team("3", "Sporting Fictif", "VVDVVNVVDV", 3, **T), _team("4", "Union Test", "NDNVNNDVNN", 11, **T),
          Quote3(1.60, 3.70, 5.50, "unibet_fr"), Quote3(1.58, 3.60, 6.20, "pinnacle")),          # nul trop probable
        m(3, _team("5", "Athletic Démo", "VVVNVVVDVV", 2, europe_before=2, **T), _team("6", "Stade Exemple", "DDVNDDNVDD", 17, **T),
          Quote3(1.40, 4.60, 7.00, "unibet_fr")),                                                   # fatigue
        m(4, _team("7", "Real Fictif", "VVVVNVVVDV", 1, europe_after=2.5, **T), _team("8", "Club Test", "DNDDVDNDDV", 18, **T),
          Quote3(1.30, 5.40, 9.00, "unibet_fr")),                                                   # match piège
        m(5, _team("9", "Inter Démo", "VVNVVVVNVV", 4, **T), _team("10", "Etoile Exemple", "NDDVDDNDVD", 14, **T),
          Quote3(1.15, 7.50, 15.0, "unibet_fr"), lg="Démo Ligue B"),                                # cote trop basse
        m(6, _team("11", "Dynamo Fictif", "VDVVNVVVDV", 5, **T), _team("12", "Vaillante Test", "DDNDVDDNDV", 16, **T),
          Quote3(1.42, 4.80, 6.80, "unibet_fr"), Quote3(1.40, 4.90, 7.60, "pinnacle"), lg="Démo Ligue B"),
        m(7, _team("13", "Borussia Démo", "VNVVDVVNVV", 6, **T), _team("14", "Hertha Exemple", "DVDNDDVDND", 13, **T),
          None, lg="Démo Ligue B"),                                                                  # pas de cote
    ]
    # Face-à-face sur les saisons passées pour un match
    h, a = ma[0].home, ma[0].away
    for s in (2025, 2024, 2023):
        h.past[s] = [FGame(datetime(s, 11, 1, tzinfo=timezone.utc), a.id, a.name, True, 3, 1),
                     FGame(datetime(s + 1, 3, 1, tzinfo=timezone.utc), a.id, a.name, False, 1, 1)]
    return FootSlate(ma, now, ["Démo Ligue A", "Démo Ligue B"], source_label="DONNÉES FICTIVES (--demo)")

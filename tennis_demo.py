"""Données FICTIVES (joueurs et tournoi inventés) pour tester le module tennis sans clé ni réseau."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import OddsQuote
from tennis_fetcher import Player, PlayerMatch, TennisMatch, TennisSlate


def _player(key: str, name: str, results: str, rank: int, *, surface: str = "dur",
            last_hours: float = 50, last_long: bool = False, retired_days: float | None = None,
            vs: dict | None = None) -> Player:
    now = datetime.now(timezone.utc)
    p = Player(key, name, "atp", rank=rank)
    n = len(results)
    for i, r in enumerate(results):
        when = now - timedelta(hours=last_hours + (n - 1 - i) * 60)
        long_ = last_long and i == n - 1
        p.matches.append(PlayerMatch(when, "Démo Open", surface, f"Tour {i + 1}", "adversaire demo",
                                     "Adversaire Démo", r == "W", 3 if long_ else 2, 33 if long_ else 20, 3))
    if retired_days is not None:
        p.matches.append(PlayerMatch(now - timedelta(days=retired_days), "Démo Cup", surface, "1er tour",
                                     "adversaire demo", "Adversaire Démo", False, 1, 5, 3, retired=True))
    for opp_key, (opp_name, wins) in (vs or {}).items():
        for j, w in enumerate(wins):
            p.matches.append(PlayerMatch(now - timedelta(days=90 + j * 30), "Démo Classic", surface,
                                         "Finale", opp_key, opp_name, w == "W", 3, 28, 3))
    p.matches.sort(key=lambda m: m.date)
    return p


def build_demo_slate() -> TennisSlate:
    now = datetime.now(timezone.utc)
    t0 = now + timedelta(hours=5)

    def match(i, a, b, oa, ob, ref=None, open_=None, tour="Démo Masters 1000"):
        m = TennisMatch(f"t{i}", t0 + timedelta(hours=i), a, b, OddsQuote(oa, ob, "unibet_fr"), ref,
                        tour, "atp", "dur", 3)
        m.opening = open_ or OddsQuote(oa, ob, "unibet_fr")
        m.observed_since, m.n_observations = now - timedelta(hours=8), 2
        return m

    alpha = _player("alpha demo", "Alpha Démo", "WWWLWWWWLW", 4)
    beta = _player("beta demo", "Beta Exemple", "LWLLWLWLLW", 38)
    gamma = _player("gamma demo", "Gamma Fictif", "WWLWWWLWWW", 9)
    delta = _player("delta demo", "Delta Test", "LWWLLWLWLL", 61)
    eps = _player("eps demo", "Epsilon Démo", "WWWWLWWLWW", 12, last_hours=14, last_long=True)
    zeta = _player("zeta demo", "Zeta Exemple", "WLWLWLWLWL", 45)
    eta = _player("eta demo", "Eta Fictif", "WWWLWWWLWW", 7, retired_days=6)
    theta = _player("theta demo", "Theta Test", "LWLWLLWLWL", 52)
    iota = _player("iota demo", "Iota Démo", "WLWWLWLWWL", 15, vs={"kappa demo": ("Kappa Exemple", "LLW")})
    kappa = _player("kappa demo", "Kappa Exemple", "LWLWWLWLWL", 33)
    lam = _player("lambda demo", "Lambda Fictif", "WWLWWW", 20)
    mu = _player("mu demo", "Mu Test", "LWLLWL", 70)

    ms = [
        match(1, alpha, beta, 1.30, 3.60, OddsQuote(1.28, 4.00, "pinnacle")),
        match(2, gamma, delta, 1.40, 2.95, OddsQuote(1.37, 3.30, "pinnacle")),
        match(3, eps, zeta, 1.35, 3.20),                         # fatigue : match long il y a 19 h
        match(4, eta, theta, 1.28, 3.80),                        # abandon il y a 6 jours
        match(5, iota, kappa, 1.45, 2.80),                       # l'outsider mène les face-à-face
        match(6, lam, mu, 1.15, 5.50, tour="Démo Open WTA 500"),  # cote trop basse
    ]
    ms.append(TennisMatch("t7", t0 + timedelta(hours=8), _player("nu demo", "Nu Démo", "WW", 25),
                          _player("xi demo", "Xi Exemple", "LW", 40), None, None,
                          "Démo Open WTA 500", "wta", "dur", 3))
    return TennisSlate(ms, now, ["Démo Masters 1000", "Démo Open WTA 500"],
                       source_label="DONNÉES FICTIVES (--demo)")

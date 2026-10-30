"""
Filtres stricts TENNIS. Le pari étudié est toujours le favori Unibet (cote la plus basse).
Un match n'est retenu que si tous les filtres sont validés ; une donnée insuffisante
donne une alerte (validé, confiance plafonnée), jamais une validation silencieuse.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import tennis_config as tc
from models import Evaluation, FilterResult
from tennis_fetcher import Player, PlayerMatch, TennisMatch


def _rate(ms: list[PlayerMatch]) -> float:
    return sum(m.won for m in ms) / len(ms) if ms else 0.0


def _rec(ms: list[PlayerMatch]) -> str:
    w = sum(m.won for m in ms)
    return f"{w}V-{len(ms) - w}D"


def _hours(d: timedelta) -> float:
    return d.total_seconds() / 3600


def last_n(p: Player, t: datetime, n: int) -> list[PlayerMatch]:
    return p.before(t)[-n:]


def is_long(m: PlayerMatch) -> bool:
    th = tc.LONG_MATCH_BO5 if m.best_of == 5 else tc.LONG_MATCH_BO3
    return m.sets >= th["sets"] or m.games >= th["games"]


# ---------------------------------------------------------------------------
def f_odds(e: Evaluation) -> FilterResult:
    ok = tc.ODDS_MIN <= e.odds <= tc.ODDS_MAX
    return FilterResult("Cote", ok, f"Cote Unibet {e.odds:.2f} {'dans' if ok else 'hors de'} la fourchette "
                                    f"{tc.ODDS_MIN:.2f}–{tc.ODDS_MAX:.2f}")


def f_line(e: Evaluation, now: datetime) -> FilterResult:
    m = e.matchup
    if m.opening is None:
        return FilterResult("Mouvement de cote", True, "Pas encore d'historique de cote", warning=True)
    open_pick = m.opening.home if e.pick_is_home else m.opening.away
    open_other = m.opening.away if e.pick_is_home else m.opening.home
    e.metrics["opening_odds"] = open_pick
    if open_pick > open_other:
        return FilterResult("Mouvement de cote", False, f"Le favori a changé (était à {open_pick:.2f})")
    rise = e.odds - open_pick
    if rise >= tc.LINE_RISE_MAX_ABS or rise / open_pick >= tc.LINE_RISE_MAX_PCT:
        return FilterResult("Mouvement de cote", False,
                            f"Hausse anormale : {open_pick:.2f} → {e.odds:.2f} (+{rise / open_pick:.1%})")
    if _hours(now - m.observed_since) < 1:
        return FilterResult("Mouvement de cote", True, "1re observation de la cote : mouvement non vérifiable",
                            warning=True)
    return FilterResult("Mouvement de cote", True, f"Cote {'en baisse' if rise < 0 else 'stable'} : "
                                                   f"{open_pick:.2f} → {e.odds:.2f}")


def f_fatigue(e: Evaluation) -> FilterResult:
    t = e.matchup.commence_time
    prev = e.pick.before(t)
    if not prev:
        return FilterResult("Fatigue", True, "Aucun match récent connu")
    last = prev[-1]
    gap = _hours(t - last.date)
    e.metrics["rest_hours"] = gap
    if gap <= tc.FATIGUE_WINDOW_HOURS and is_long(last):
        return FilterResult("Fatigue", False, f"Match long il y a {gap:.0f} h : {last.sets} sets, {last.games} jeux "
                                              f"contre {last.opponent_name}")
    if gap <= tc.FATIGUE_WINDOW_HOURS:
        return FilterResult("Fatigue", True, f"A joué il y a {gap:.0f} h, mais un match court "
                                             f"({last.sets} sets, {last.games} jeux)")
    return FilterResult("Fatigue", True, f"Reposé : dernier match il y a {gap / 24:.1f} jour(s)")


def f_retirement(e: Evaluation) -> FilterResult:
    t = e.matchup.commence_time
    recent = [m for m in e.pick.before(t) if _hours(t - m.date) <= tc.RETIREMENT_DAYS * 24 and m.retired]
    if recent:
        m = recent[-1]
        return FilterResult("Abandon récent", False, f"Abandon ou forfait le {m.date:%d/%m} contre "
                                                     f"{m.opponent_name} ({m.tournament})")
    return FilterResult("Abandon récent", True, f"Aucun abandon ni forfait depuis {tc.RETIREMENT_DAYS} jours")


def f_form(e: Evaluation) -> FilterResult:
    ms = last_n(e.pick, e.matchup.commence_time, tc.FORM_GAMES)
    e.metrics["pick_form"] = _rate(ms)
    if len(ms) < tc.FORM_MIN_GAMES:
        return FilterResult("Forme récente", True, f"Peu de matchs connus ({len(ms)}) : forme non vérifiable",
                            warning=True)
    ok = _rate(ms) >= tc.FORM_MIN_RATE
    return FilterResult("Forme récente", ok, f"{_rec(ms)} sur ses {len(ms)} derniers matchs")


def f_surface(e: Evaluation) -> FilterResult:
    s = e.matchup.surface
    ms = [m for m in e.pick.before(e.matchup.commence_time) if m.surface == s]
    e.metrics["pick_surface"] = _rate(ms) if ms else 0.5
    if len(ms) < tc.SURFACE_MIN_GAMES:
        return FilterResult("Surface", True, f"Peu de matchs sur {s} ({len(ms)}) : à vérifier", warning=True)
    ok = _rate(ms) >= tc.SURFACE_MIN_RATE
    return FilterResult("Surface", ok, f"{_rec(ms)} sur {s} depuis {ms[0].date.year} ({_rate(ms):.0%})")


def f_dynamics(e: Evaluation) -> FilterResult:
    t = e.matchup.commence_time
    p10, o10 = last_n(e.pick, t, tc.FORM_GAMES), last_n(e.opponent, t, tc.FORM_GAMES)
    o5 = o10[-tc.DOG_HOT_LAST:]
    e.metrics["opp_form"] = _rate(o10)
    summary = f"{e.pick.name} {_rec(p10)} vs {e.opponent.name} {_rec(o10)}"
    if len(o5) >= tc.DOG_HOT_LAST and p10 and _rate(o5) >= tc.DOG_HOT_RATE and _rate(p10) <= tc.FAV_DOUBT_RATE:
        return FilterResult("Dynamique croisée", False, f"Outsider en feu, favori qui doute : {summary}")
    if len(p10) >= tc.FORM_MIN_GAMES and len(o10) >= tc.FORM_MIN_GAMES and _rate(o10) > _rate(p10):
        return FilterResult("Dynamique croisée", False, f"L'outsider est en meilleure forme : {summary}")
    if len(p10) < tc.FORM_MIN_GAMES or len(o10) < tc.FORM_MIN_GAMES:
        return FilterResult("Dynamique croisée", True, f"Peu de matchs pour comparer — {summary}", warning=True)
    return FilterResult("Dynamique croisée", True, summary)


def f_ranking(e: Evaluation) -> FilterResult:
    rp, ro = e.pick.rank, e.opponent.rank
    if rp is None or ro is None:
        return FilterResult("Classement", True, "Classement indisponible pour au moins un joueur", warning=True)
    o = lambda r: f"{r}{'er' if r == 1 else 'e'}"
    if rp - ro > tc.RANK_TOLERANCE:
        return FilterResult("Classement", False, f"Le favori est {o(rp)}, l'outsider {o(ro)} : "
                                                 "le classement contredit la cote")
    return FilterResult("Classement", True, f"{e.pick.name} {o(rp)} mondial, {e.opponent.name} {o(ro)}")


def f_h2h(e: Evaluation) -> FilterResult:
    meet = [m for m in e.pick.before(e.matchup.commence_time) if m.opponent == e.opponent.key]
    if not meet:
        return FilterResult("Confrontations", True, "Aucune confrontation récente connue")
    w = sum(m.won for m in meet)
    txt = f"{w}-{len(meet) - w} en faveur de {e.pick.name if w >= len(meet) - w else e.opponent.name}"
    if len(meet) >= tc.H2H_MIN_MEETINGS and len(meet) - w > w:
        return FilterResult("Confrontations", False, f"L'outsider mène les confrontations : {txt}")
    if not meet[-1].won:
        return FilterResult("Confrontations", True, f"A perdu la dernière confrontation ({txt})", warning=True)
    return FilterResult("Confrontations", True, txt)


FILTERS: list[Callable] = [f_odds, f_line, f_fatigue, f_retirement, f_form, f_surface,
                           f_dynamics, f_ranking, f_h2h]


def evaluate(m: TennisMatch, now: datetime) -> Evaluation:
    if m.unibet is None:
        return Evaluation(m, None, None, True, 0.0,
                          [FilterResult("Cote", False, "Cote Unibet pas encore publiée pour ce match")])
    p1_fav = m.unibet.home <= m.unibet.away
    e = Evaluation(m, m.home if p1_fav else m.away, m.away if p1_fav else m.home, p1_fav,
                   m.unibet.home if p1_fav else m.unibet.away)
    for f in FILTERS:
        try:
            e.results.append(f(e, now) if f is f_line else f(e))
        except Exception as exc:          # une donnée manquante ne valide jamais un match
            e.results.append(FilterResult(f.__name__.removeprefix("f_"), False, f"Erreur de données : {exc}"))
    # Score de qualité et probabilité "marché"
    if m.reference:
        ph, pa = 1 / m.reference.home, 1 / m.reference.away
        e.metrics["fair_prob"] = (ph if p1_fav else pa) / (ph + pa)
        e.metrics["edge"] = e.metrics["fair_prob"] - 1 / e.odds
    edge = max(-0.1, min(0.1, e.metrics.get("edge", 0.0))) * 10
    e.score = (0.4 * (e.metrics.get("pick_form", 0.5) - e.metrics.get("opp_form", 0.5))
               + 0.3 * e.metrics.get("pick_surface", 0.5) + 0.3 * edge)
    return e


def evaluate_all(matches: list[TennisMatch], now: datetime) -> list[Evaluation]:
    return [evaluate(m, now) for m in matches]

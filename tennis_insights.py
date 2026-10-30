"""Analyse détaillée d'un match de tennis validé, et choix du pari tennis."""
from __future__ import annotations

import math
from itertools import combinations
from typing import Optional

import tennis_config as tc
from analyzer import Bet
from insights import Insight, leg_probability
from models import Evaluation
from tennis_filters import _rate, _rec, is_long, last_n


def _streak(ms) -> str:
    if not ms:
        return "aucun match"
    last, n = ms[-1].won, 0
    for m in reversed(ms):
        if m.won != last:
            break
        n += 1
    return f"{n} {'victoire' if last else 'défaite'}{'s' if n > 1 else ''} de suite"


def _by_year(p, t, surface: str) -> str:
    """Bilan par année (toutes surfaces, et sur la surface du match) pour les années passées."""
    out = []
    for y in range(t.year - 1, t.year - 4, -1):
        ms = [x for x in p.matches if x.date.year == y]
        if not ms:
            continue
        sm = [x for x in ms if x.surface == surface]
        out.append(f"{y} {_rec(ms)}" + (f" ({surface} {_rec(sm)})" if sm else ""))
    return " · ".join(out) or "pas de données"


def _rank(p) -> str:
    if not p.rank:
        return "classement n.d."
    return f"{p.rank}{'er' if p.rank == 1 else 'e'} mondial"


def _in_tournament(p, m) -> list:
    return [x for x in p.before(m.commence_time) if x.tournament and _same_event(x.tournament, m.tournament)]


def _same_event(a: str, b: str) -> bool:
    from tennis_fetcher import norm_name
    wa = set(norm_name(a).split()) - {"atp", "wta", "open", "masters", "the", "de", "tennis"}
    wb = set(norm_name(b).split()) - {"atp", "wta", "open", "masters", "the", "de", "tennis"}
    return bool(wa & wb)


def build_insight(e: Evaluation) -> Insight:
    m, pick, opp = e.matchup, e.pick, e.opponent
    t = m.commence_time
    p10, o10 = last_n(pick, t, tc.FORM_GAMES), last_n(opp, t, tc.FORM_GAMES)
    ps = [x for x in pick.before(t) if x.surface == m.surface]
    os_ = [x for x in opp.before(t) if x.surface == m.surface]
    pt, ot = _in_tournament(pick, m), _in_tournament(opp, m)
    h2h = [x for x in pick.before(t) if x.opponent == opp.key]
    prob = leg_probability(e)
    implied = 1 / e.odds

    def last_match(p):
        prev = p.before(t)
        if not prev:
            return "aucun match récent connu"
        x = prev[-1]
        h = (t - x.date).total_seconds() / 3600
        when = f"il y a {h:.0f} h" if h < 48 else f"il y a {h / 24:.0f} jours"
        return f"{when} : {'victoire' if x.won else 'défaite'} contre {x.opponent_name} ({x.sets} sets, {x.games} jeux)"

    def path(ms):
        if not ms:
            return "premier match dans le tournoi"
        return ", ".join(f"{x.round or 'tour'} : {'V' if x.won else 'D'} vs {x.opponent_name} ({x.sets} sets)"
                         for x in ms)

    sections = [
        ("Classement", [f"{pick.name} : {_rank(pick)}", f"{opp.name} : {_rank(opp)}"]),
        (f"Forme récente ({tc.FORM_GAMES} derniers matchs)", [
            f"{pick.name} : {_rec(p10)}, {_streak(p10)}" if p10 else f"{pick.name} : pas de match connu",
            f"{opp.name} : {_rec(o10)}, {_streak(o10)}" if o10 else f"{opp.name} : pas de match connu"]),
        (f"Sur {m.surface}", [f"{pick.name} : {_rec(ps)}" + (f" ({_rate(ps):.0%})" if ps else ""),
                              f"{opp.name} : {_rec(os_)}" + (f" ({_rate(os_):.0%})" if os_ else "")]),
        (f"Parcours à {m.tournament}", [f"{pick.name} : {path(pt)}", f"{opp.name} : {path(ot)}"]),
        ("Dernier match", [f"{pick.name} : {last_match(pick)}", f"{opp.name} : {last_match(opp)}"]),
        (f"Confrontations depuis {t.year - 3}", [
            (f"{pick.name} {sum(x.won for x in h2h)}V-{len(h2h) - sum(x.won for x in h2h)}D · derniers : "
             + ", ".join(f"{x.date:%m/%Y} {x.tournament} ({'V' if x.won else 'D'})" for x in h2h[-4:]))
            if h2h else "Aucune confrontation sur les 3 dernières saisons"]),
        ("Saisons précédentes", [f"{pick.name} : {_by_year(pick, t, m.surface)}",
                                 f"{opp.name} : {_by_year(opp, t, m.surface)}"]),
    ]
    market = [f"Cote Unibet {e.odds:.2f} → probabilité implicite {implied:.0%}"]
    if m.reference:
        ref = m.reference.home if e.pick_is_home else m.reference.away
        market.append(f"Référence marché ({m.reference.bookmaker}) {ref:.2f} → probabilité estimée {prob:.0%}")
    if "opening_odds" in e.metrics:
        market.append(f"Évolution Unibet : {e.metrics['opening_odds']:.2f} → {e.odds:.2f}")
    sections.append(("Lecture du marché", market))

    strengths, risks = [], []
    if p10 and o10 and _rate(p10) - _rate(o10) >= 0.3:
        strengths.append(f"Nette différence de forme : {_rec(p10)} contre {_rec(o10)}")
    if len(ps) >= tc.SURFACE_MIN_GAMES and _rate(ps) >= 0.7:
        strengths.append(f"Très à l'aise sur {m.surface} : {_rec(ps)}")
    if pick.rank and opp.rank and opp.rank - pick.rank >= 20:
        strengths.append(f"Gros écart de classement : {pick.rank}e contre {opp.rank}e")
    oprev = opp.before(t)
    if oprev and (t - oprev[-1].date).total_seconds() / 3600 <= tc.FATIGUE_WINDOW_HOURS and is_long(oprev[-1]):
        strengths.append(f"{opp.name} sort d'un match long ({oprev[-1].sets} sets, {oprev[-1].games} jeux)")
    if h2h and sum(x.won for x in h2h) > len(h2h) / 2:
        strengths.append(f"Mène les confrontations : {sum(x.won for x in h2h)}-{len(h2h) - sum(x.won for x in h2h)}")
    if prob - implied >= 0.01:
        strengths.append(f"Unibet paie mieux que le marché ({prob:.0%} estimé contre {implied:.0%})")

    for r in e.warnings:
        risks.append(f"{r.name} : {r.reason}")
    if e.odds >= 1.60:
        risks.append(f"Cote de {e.odds:.2f} : favori moins net, une défaite est plausible")
    if m.best_of == 3:
        risks.append("Match en 2 sets gagnants : plus de place pour une surprise qu'en 5 sets")
    if prob - implied <= -0.03:
        risks.append(f"Cote Unibet en dessous du marché ({implied:.0%} contre {prob:.0%})")

    if prob >= 0.72 and e.score >= 0.30 and len(risks) <= 1:
        confidence = "Élevée"
    elif prob >= 0.60 and len(risks) <= 3:
        confidence = "Moyenne"
    else:
        confidence = "Prudente"
    if any(r.name in ("Forme récente", "Surface", "Dynamique croisée") for r in e.warnings):
        confidence = "Prudente"      # données trop maigres : jamais plus que prudente

    summary = (f"{pick.name} ({_rank(pick)}) est favori face à {opp.name} ({_rank(opp)}) "
               f"à {m.tournament}, sur {m.surface}.")
    if strengths:
        summary += f" Principal atout : {strengths[0][0].lower() + strengths[0][1:]}."
    summary += f" Probabilité de victoire estimée : {prob:.0%}."
    return Insight(summary, sections, strengths, risks, confidence, prob)


def best_bet(candidates: list[Evaluation]):
    """Les deux propositions tennis : meilleur pari simple + meilleur combiné (Proposals)."""
    from analyzer import proposals_from, rank_options
    return proposals_from(rank_options(candidates, tc.BET_MAX_LEGS, tc.BET_MIN_ODDS, tc.BET_MAX_ODDS, 0.10))

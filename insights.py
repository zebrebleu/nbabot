"""
Analyse détaillée d'un match validé : chiffres clés des deux équipes, atouts,
points de vigilance et niveau de confiance. Utilisé par le rapport texte et le site.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import config
from models import Evaluation, TeamContext, TeamGame


@dataclass
class Insight:
    summary: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: str = "Moyenne"
    win_prob: float = 0.0


# ---------------------------------------------------------------------------
# Petits calculs
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _record(games: list[TeamGame]) -> str:
    w = sum(1 for g in games if g.won)
    return f"{w}V-{len(games) - w}D"


def _avg_diff(games: list[TeamGame]) -> Optional[float]:
    vals = [g.points_for - g.points_against for g in games
            if g.points_for is not None and g.points_against is not None]
    return sum(vals) / len(vals) if vals else None


def _streak(games: list[TeamGame]) -> str:
    if not games:
        return "aucun match"
    last = games[-1].won
    n = 0
    for g in reversed(games):
        if g.won != last:
            break
        n += 1
    word = "victoire" if last else "défaite"
    return f"{n} {word}{'s' if n > 1 else ''} de suite"


def _rank(team: TeamContext) -> str:
    return f"{team.league_rank}e NBA" if team.league_rank else "rang n.d."


def _rest_hours(team: TeamContext, t) -> Optional[float]:
    prev = team.previous_game(t)
    return (t - prev.date).total_seconds() / 3600 if prev else None


def _rest_label(hours: Optional[float]) -> str:
    if hours is None:
        return "pas de match récent"
    if hours <= config.B2B_MAX_GAP_HOURS:
        return "back-to-back (a joué la veille)"
    return f"{hours / 24:.0f} jour(s) de repos"


def _absents(team: TeamContext) -> list[str]:
    return [f"{i.player} ({i.status})" for i in team.injuries
            if _norm(i.status) in config.BLOCKING_STATUSES]


def _key_absent(team: TeamContext, key_players: dict) -> Optional[str]:
    keys = [_norm(p) for p in (key_players.get(team.key) or []) if isinstance(p, str)]
    for i in team.injuries:
        if _norm(i.player) in keys and _norm(i.status) in config.BLOCKING_STATUSES:
            return f"{i.player} ({i.status})"
    return None


def _fmt_diff(x: Optional[float]) -> str:
    return "n.d." if x is None else f"{x:+.1f} pts/match"


def leg_probability(e: Evaluation) -> float:
    """Proba. de victoire estimée : cote de référence sans marge, sinon cote Unibet corrigée."""
    if "fair_prob" in e.metrics:
        return e.metrics["fair_prob"]
    return min(0.99, (1 / e.odds) / (1 + config.MARKET_MARGIN))


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------
def build_insight(e: Evaluation, key_players: Optional[dict] = None) -> Insight:
    key_players = key_players if key_players is not None else config.KEY_PLAYERS
    m, pick, opp = e.matchup, e.pick, e.opponent
    t = m.commence_time
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    lieu_opp = "à l'extérieur" if e.pick_is_home else "à domicile"

    p_all, o_all = pick.completed_before(t), opp.completed_before(t)
    p10, o10 = p_all[-config.L10_GAMES:], o_all[-config.L10_GAMES:]
    p_venue = [g for g in p_all if g.is_home == e.pick_is_home]
    o_venue = [g for g in o_all if g.is_home != e.pick_is_home]
    p_diff, o_diff = _avg_diff(p10), _avg_diff(o10)
    p_rest, o_rest = _rest_hours(pick, t), _rest_hours(opp, t)
    p_abs, o_abs = _absents(pick), _absents(opp)
    h2h = [g for g in p_all if g.opponent == opp.key]
    prob = leg_probability(e)
    implied = 1 / e.odds

    sections: list[tuple[str, list[str]]] = [
        ("Bilan de la saison", [
            f"{pick.name} : {_record(p_all)} ({_rank(pick)}) · {lieu} {_record(p_venue)}",
            f"{opp.name} : {_record(o_all)} ({_rank(opp)}) · {lieu_opp} {_record(o_venue)}",
        ]),
        (f"Forme récente ({config.L10_GAMES} derniers matchs)", [
            f"{pick.name} : {_record(p10)}, {_streak(p10)}, écart moyen {_fmt_diff(p_diff)}",
            f"{opp.name} : {_record(o10)}, {_streak(o10)}, écart moyen {_fmt_diff(o_diff)}",
        ]),
        ("Repos et calendrier", [
            f"{pick.name} : {_rest_label(p_rest)}",
            f"{opp.name} : {_rest_label(o_rest)}",
        ]),
        ("Effectifs", [
            f"{pick.name} : " + (", ".join(p_abs) if p_abs else "aucun absent ni incertain"),
            f"{opp.name} : " + (", ".join(o_abs) if o_abs else "aucun absent ni incertain"),
        ]),
        ("Confrontations cette saison", [
            ", ".join(f"{'victoire' if g.won else 'défaite'} {int(g.points_for)}-{int(g.points_against)}"
                      if g.points_for is not None else ("victoire" if g.won else "défaite") for g in h2h)
            if h2h else "Première confrontation de la saison",
        ]),
    ]

    market = [f"Cote Unibet {e.odds:.2f} → probabilité implicite {implied:.0%}"]
    if m.reference:
        ref = m.reference.home if e.pick_is_home else m.reference.away
        market.append(f"Référence marché ({m.reference.bookmaker}) {ref:.2f} → "
                      f"probabilité réelle estimée {prob:.0%} (marge retirée)")
    else:
        market.append(f"Pas de cote de référence : probabilité estimée {prob:.0%} (marge retirée)")
    if "opening_odds" in e.metrics:
        market.append(f"Évolution Unibet : {e.metrics['opening_odds']:.2f} → {e.odds:.2f}")
    sections.append(("Lecture du marché", market))

    # --- Atouts ---------------------------------------------------------------
    strengths, risks = [], []
    if p10 and o10:
        gap = sum(g.won for g in p10) / len(p10) - sum(g.won for g in o10) / len(o10)
        if gap >= 0.3:
            strengths.append(f"Nette différence de forme : {_record(p10)} contre {_record(o10)}")
    if p_diff is not None and o_diff is not None and p_diff - o_diff >= 8:
        strengths.append(f"Écart de niveau marqué : {_fmt_diff(p_diff)} contre {_fmt_diff(o_diff)}")
    if p_venue and sum(g.won for g in p_venue) / len(p_venue) >= 0.7:
        strengths.append(f"Solide {lieu} : {_record(p_venue)} cette saison")
    if o_rest is not None and o_rest <= config.B2B_MAX_GAP_HOURS and (p_rest is None or p_rest > config.B2B_MAX_GAP_HOURS):
        strengths.append(f"{opp.name} joue en back-to-back, {pick.name} est reposé")
    opp_key = _key_absent(opp, key_players)
    if opp_key:
        strengths.append(f"Joueur clé adverse touché : {opp_key}")
    elif len(o_abs) >= 2:
        strengths.append(f"{opp.name} diminué : {len(o_abs)} absents ou incertains")
    if prob - implied >= 0.01:
        strengths.append(f"Unibet paie mieux que le marché ({prob:.0%} estimé contre {implied:.0%} implicite)")
    if h2h and all(g.won for g in h2h):
        strengths.append(f"A déjà battu {opp.name} cette saison")

    # --- Points de vigilance --------------------------------------------------
    for r in e.warnings:
        risks.append(f"{r.name} : {r.reason}")
    if p_rest is not None and o_rest is not None and o_rest - p_rest >= 24:
        risks.append(f"{opp.name} a eu plus de repos ({_rest_label(o_rest)} contre {_rest_label(p_rest)})")
    if p_diff is not None and p_diff < 3:
        risks.append(f"Écart moyen de {pick.name} faible ({_fmt_diff(p_diff)}) : victoires souvent serrées")
    if len(p_all) < 10:
        risks.append(f"Échantillon réduit : seulement {len(p_all)} matchs joués cette saison")
    if h2h and not any(g.won for g in h2h):
        risks.append(f"A perdu contre {opp.name} cette saison")
    if e.odds >= 1.60:
        risks.append(f"Cote de {e.odds:.2f} : favori moins net, une défaite est plausible")
    if prob - implied <= -0.03:
        risks.append(f"Cote Unibet en dessous du marché ({implied:.0%} implicite contre {prob:.0%} estimé)")

    # --- Confiance -------------------------------------------------------------
    if prob >= 0.72 and e.score >= 0.30 and len(risks) <= 1:
        confidence = "Élevée"
    elif prob >= 0.60 and e.score >= 0.15 and len(risks) <= 3:
        confidence = "Moyenne"
    else:
        confidence = "Prudente"

    # --- Résumé ----------------------------------------------------------------
    summary = f"{pick.name} ({_record(p_all)}) est favori {lieu} face à {opp.name} ({_record(o_all)})."
    if strengths:
        summary += f" Principal atout : {strengths[0][0].lower() + strengths[0][1:]}."
    if risks:
        summary += f" À surveiller : {len(risks)} point(s) de vigilance."
    summary += f" Probabilité de victoire estimée : {prob:.0%}."

    return Insight(summary, sections, strengths, risks, confidence, prob)

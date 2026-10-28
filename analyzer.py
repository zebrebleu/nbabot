"""
Synthèse : score des matchs validés, choix du meilleur pari (1 ou 2 matchs,
cote totale <= BET_MAX_ODDS), rapport texte détaillé.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import config
from insights import Insight, build_insight, leg_probability
from models import Evaluation, OddsQuote, Slate

TZ = ZoneInfo(config.DISPLAY_TZ)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
LINE = "═" * 72
SUB = "─" * 72


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fair_probability(ref: OddsQuote, home: bool) -> float:
    """Probabilité sans marge (no-vig) issue de la cote de référence marché."""
    ph, pa = 1 / ref.home, 1 / ref.away
    return (ph if home else pa) / (ph + pa)


def score_evaluation(e: Evaluation) -> float:
    """Score de qualité (≈ -0.5 à 1) : forme relative, forme dom./ext., repos, value vs marché."""
    m = e.metrics
    form_diff = (m.get("pick_l10_wins", 0) - m.get("opp_l10_wins", 0)) / 10
    venue = m.get("venue_wins", 0) / max(m.get("venue_games", 1), 1)
    rest = min(m.get("rest_hours") or 72, 72)
    opp_rest = min(m.get("opp_rest_hours") or 72, 72)
    rest_adv = _clamp((rest - opp_rest) / 48)

    edge = 0.0
    if e.matchup.reference:
        fair = fair_probability(e.matchup.reference, e.pick_is_home)
        edge = fair - 1 / e.odds
        m.update(fair_prob=fair, edge=edge)
    e.score = 0.35 * form_diff + 0.25 * venue + 0.15 * rest_adv + 0.25 * _clamp(edge * 10)
    return e.score


# ---------------------------------------------------------------------------
# Choix du pari
# ---------------------------------------------------------------------------
@dataclass
class Bet:
    legs: list[Evaluation]
    total: float
    prob: float          # probabilité estimée que tout le pari passe
    value: float

    @property
    def kind(self) -> str:
        return "Pari simple" if len(self.legs) == 1 else f"Combiné de {len(self.legs)} matchs"

    @property
    def expected_return(self) -> float:
        return self.prob * self.total


def best_bet(candidates: list[Evaluation]) -> tuple[Optional[Bet], list[Bet]]:
    """Meilleure option parmi les simples et combinés autorisés. Renvoie (meilleur, toutes options)."""
    options: list[Bet] = []
    for size in range(1, config.BET_MAX_LEGS + 1):
        for legs in combinations(candidates, size):
            total = math.prod(e.odds for e in legs)
            if not config.BET_MIN_ODDS <= total <= config.BET_MAX_ODDS:
                continue
            prob = math.prod(leg_probability(e) for e in legs)
            quality = sum(e.score for e in legs) / len(legs)
            value = prob * total + config.BET_QUALITY_WEIGHT * quality
            options.append(Bet(list(legs), total, prob, value))
    options.sort(key=lambda b: b.value, reverse=True)
    return (options[0] if options else None), options


def select(evaluations: list[Evaluation]):
    """Renvoie (validés triés par qualité, rejetés, meilleur pari ou None)."""
    passed = [e for e in evaluations if e.passed]
    rejected = [e for e in evaluations if not e.passed]
    for e in passed:
        score_evaluation(e)
    passed.sort(key=lambda e: e.score, reverse=True)
    bet, _ = best_bet(passed)
    return passed, rejected, bet


def no_bet_reason(passed: list[Evaluation]) -> str:
    if not passed:
        return "Aucun match ne passe tous les filtres : on ne force pas."
    return (f"{len(passed)} match(s) valide(s), mais aucune option entre "
            f"{config.BET_MIN_ODDS:.2f} et {config.BET_MAX_ODDS:.2f} de cote totale.")


# ---------------------------------------------------------------------------
# Rapport texte
# ---------------------------------------------------------------------------
def _fmt_dt(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{JOURS[local.weekday()]} {local.day:02d}/{local.month:02d} à {local:%H:%M}"


def _fmt_day(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{JOURS[local.weekday()]} {local.day} {MOIS[local.month - 1]} {local.year}"


def slate_day(slate: Slate):
    """Date américaine des matchs (déduite si absente)."""
    if slate.slate_date:
        return slate.slate_date
    first = min((m.commence_time for m in slate.matchups), default=slate.generated_at)
    return first.astimezone(ZoneInfo("America/New_York")).date()


def night_label(slate: Slate) -> str:
    """'nuit du mercredi 28 au jeudi 29 octobre' : les matchs du jour J américain
    se jouent dans la nuit du J au J+1 en France."""
    from datetime import timedelta
    d = slate_day(slate)
    n = d + timedelta(days=1)
    first = f"{JOURS[d.weekday()]} {d.day}" + ("" if d.month == n.month else f" {MOIS[d.month - 1]}")
    return f"nuit du {first} au {JOURS[n.weekday()]} {n.day} {MOIS[n.month - 1]}"


def _phase_line(when: datetime) -> str:
    th = config.season_thresholds(when)
    data = "rejet" if th.INSUFFICIENT_DATA == "reject" else "alerte"
    return (f" Période : {th.label} · forme dom./ext. sur {th.VENUE_FORM_GAMES} matchs · "
            f"dynamique dès {th.L10_MIN_GAMES} matchs · données insuffisantes = {data}")


def _pick_block(i: int, e: Evaluation, ins: Insight) -> list[str]:
    m = e.matchup
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    lines = [
        f" {i}) {m.label}  —  {_fmt_dt(m.commence_time)} (heure de Paris)",
        f"    PARI : {e.pick.name} vainqueur ({lieu}) — cote Unibet {e.odds:.2f} — confiance {ins.confidence}",
        "",
        f"    En bref : {ins.summary}",
        "",
    ]
    for title, rows in ins.sections:
        lines.append(f"    {title}")
        lines += [f"      · {r}" for r in rows]
    if ins.strengths:
        lines.append("    Atouts")
        lines += [f"      + {s}" for s in ins.strengths]
    if ins.risks:
        lines.append("    Points de vigilance")
        lines += [f"      ! {r}" for r in ins.risks]
    lines.append("    Filtres validés")
    for r in e.results:
        lines.append(f"      ✓ {r.name:<18} {r.reason}")
    return lines


def build_report(slate: Slate, evaluations: list[Evaluation], show_rejected: bool = False) -> str:
    passed, rejected, bet = select(evaluations)
    kp = slate.key_players

    out = [
        LINE,
        f" ASSISTANT PARIS NBA — matchs de la {night_label(slate)}",
        f" Généré le {_fmt_dt(slate.generated_at)} (Paris) · Source : {slate.source_label}",
        f" Contenders : {slate.contenders_source}",
        _phase_line(slate.generated_at),
        LINE,
        f" Matchs analysés : {len(evaluations)} · Validés par tous les filtres : {len(passed)} "
        f"· Rejetés : {len(rejected)}",
        "",
    ]

    if bet:
        out += [f" {bet.kind.upper()} — COTE TOTALE {bet.total:.2f} (max {config.BET_MAX_ODDS:.2f})",
                f" Probabilité estimée que le pari passe : {bet.prob:.0%}", SUB]
        for i, e in enumerate(bet.legs, 1):
            out += _pick_block(i, e, build_insight(e, kp)) + [""]
        others = [e for e in passed if e not in bet.legs]
        if others:
            out.append(" Autres matchs validés (non retenus) :")
            for e in others:
                out.append(f"   • {e.pick.name} {e.odds:.2f} ({e.matchup.label}) — "
                           f"proba. estimée {leg_probability(e):.0%}")
            out.append("")
    else:
        out += [" AUCUN PARI AUJOURD'HUI", SUB, f" {no_bet_reason(passed)}", ""]
        for i, e in enumerate(passed, 1):
            out += _pick_block(i, e, build_insight(e, kp)) + [""]

    out += [
        " CHECKLIST AVANT DE JOUER SUR UNIBET",
        SUB,
        f"   □ La cote totale affichée ne dépasse pas {config.BET_MAX_ODDS:.2f}",
        "   □ Le marché est bien « Face à face / Vainqueur du match » prolongations incluses",
        "   □ Rapport de blessures officiel NBA revérifié ~30 min avant le coup d'envoi",
        "   □ Aucune annonce de repos (load management) entre-temps",
        "",
    ]

    if rejected:
        out += [" MATCHS REJETÉS", SUB]
        for e in rejected:
            first = e.rejections[0]
            pick = f"{e.pick.name} {e.odds:.2f}" if e.pick else "—"
            out.append(f"   ✗ {e.matchup.label} [{pick}] → {first.name} : {first.reason}")
            if show_rejected:
                for r in e.rejections[1:]:
                    out.append(f"       ✗ {r.name} : {r.reason}")
        out.append("")

    out += [
        LINE,
        " Outil d'aide à la décision : aucun filtre ne garantit un résultat.",
        " Mise fixe et raisonnable. Joueurs Info Service : 09 74 75 13 13.",
        LINE,
    ]
    return "\n".join(out)


def save_report(text: str, generated_at: datetime, directory: Path = config.REPORTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rapport_{generated_at.astimezone(TZ):%Y-%m-%d_%H%M}.txt"
    path.write_text(text, encoding="utf-8")
    return path

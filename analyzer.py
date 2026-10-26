"""
Synthèse : score des matchs validés, choix du meilleur combiné, rapport texte.
"""
from __future__ import annotations

import math
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import config
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
    """Score indicatif (≈ -0.5 à 1) : forme relative, forme dom./ext., repos, value vs marché."""
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


def best_combo(candidates: list[Evaluation]) -> Optional[tuple[list[Evaluation], float]]:
    best, best_val = None, -math.inf
    for combo in combinations(candidates, config.COMBO_SIZE):
        total = math.prod(e.odds for e in combo)
        if not config.COMBO_MIN <= total <= config.COMBO_MAX:
            continue
        value = sum(e.score for e in combo) - 2 * abs(total - config.COMBO_TARGET)
        if value > best_val:
            best, best_val = (list(combo), total), value
    return best


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------
def _fmt_dt(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{JOURS[local.weekday()]} {local.day:02d}/{local.month:02d} à {local:%H:%M}"


def _fmt_day(dt: datetime) -> str:
    local = dt.astimezone(TZ)
    return f"{JOURS[local.weekday()]} {local.day} {MOIS[local.month - 1]} {local.year}"


def _phase_line(when: datetime) -> str:
    th = config.season_thresholds(when)
    data = "rejet" if th.INSUFFICIENT_DATA == "reject" else "alerte"
    return (f" Période : {th.label} · forme dom./ext. sur {th.VENUE_FORM_GAMES} matchs · "
            f"dynamique dès {th.L10_MIN_GAMES} matchs · données insuffisantes = {data}")


def _pick_block(i: int, e: Evaluation) -> list[str]:
    m = e.matchup
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    lines = [
        f" {i}) {m.label}  —  {_fmt_dt(m.commence_time)} (heure de Paris)",
        f"    PARI : {e.pick.name} vainqueur ({lieu}) — face-à-face / Moneyline",
    ]
    extra = []
    if "opening_odds" in e.metrics:
        extra.append(f"1re obs. {e.metrics['opening_odds']:.2f}")
    if m.reference:
        ref_odds = m.reference.home if e.pick_is_home else m.reference.away
        extra.append(f"marché ({m.reference.bookmaker}) {ref_odds:.2f}")
    if "fair_prob" in e.metrics:
        extra.append(f"proba. estimée {e.metrics['fair_prob']:.0%}")
    lines.append(f"    Cote Unibet : {e.odds:.2f}" + (f"   ({' · '.join(extra)})" if extra else ""))
    lines.append("    Pourquoi :")
    for r in e.results:
        lines.append(f"      ✓ {r.name:<18} {r.reason}")
    if e.warnings:
        lines.append("    À vérifier :")
        for r in e.warnings:
            lines.append(f"      ! {r.name} — {r.reason}")
    lines.append(f"    Score interne : {e.score:+.2f}")
    return lines


def select(evaluations: list[Evaluation]):
    """Score les matchs validés et choisit le combiné. Renvoie (validés triés, rejetés, combo)."""
    passed = [e for e in evaluations if e.passed]
    rejected = [e for e in evaluations if not e.passed]
    for e in passed:
        score_evaluation(e)
    passed.sort(key=lambda e: e.score, reverse=True)
    return passed, rejected, best_combo(passed)


def build_report(slate: Slate, evaluations: list[Evaluation], show_rejected: bool = False) -> str:
    passed, rejected, combo = select(evaluations)

    out = [
        LINE,
        f" ASSISTANT PARIS NBA — {_fmt_day(slate.generated_at)}",
        f" Généré à {slate.generated_at.astimezone(TZ):%H:%M} (Paris) · Source : {slate.source_label}",
        f" Contenders : {slate.contenders_source}",
        _phase_line(slate.generated_at),
        LINE,
        f" Matchs analysés : {len(evaluations)} · Validés par tous les filtres : {len(passed)} "
        f"· Rejetés : {len(rejected)}",
        "",
    ]

    if combo:
        picks, total = combo
        out += [f" COMBINÉ PROPOSÉ ({len(picks)} matchs) — COTE TOTALE : {total:.2f}", SUB]
        for i, e in enumerate(picks, 1):
            out += _pick_block(i, e) + [""]
        others = [e for e in passed if e not in picks]
        if others:
            out.append(" Autres matchs validés (alternatives) :")
            for e in others:
                out.append(f"   • {e.pick.name} {e.odds:.2f} ({e.matchup.label}) — score {e.score:+.2f}")
            out.append("")
    else:
        out += [" AUCUN COMBINÉ AUJOURD'HUI", SUB]
        if len(passed) < config.COMBO_SIZE:
            out.append(f" Seulement {len(passed)} match(s) passe(nt) tous les filtres : on ne force pas.")
        else:
            out.append(f" Aucune combinaison ne tombe entre {config.COMBO_MIN:.2f} et {config.COMBO_MAX:.2f}.")
        for i, e in enumerate(passed, 1):
            out += _pick_block(i, e) + [""]
        out.append("")

    out += [
        " CHECKLIST AVANT DE JOUER SUR UNIBET",
        SUB,
        f"   □ La cote Unibet affichée est toujours entre {config.ODDS_MIN:.2f} et {config.ODDS_MAX:.2f}",
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

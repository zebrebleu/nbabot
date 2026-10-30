"""
Explications en langage simple + fiches de match pour le chatbot (Claude).

  plain_lines(...)  -> 3 à 4 phrases « En clair » affichées sur les pages
  brief(...)        -> fiche courte d'un match (envoyée à Claude dans la question)
  claude_url(...)   -> lien https://claude.ai/new?q=… qui ouvre Claude avec la question pré-remplie
"""
from __future__ import annotations

from urllib.parse import quote
from zoneinfo import ZoneInfo

import config
from staking import stake_for

TZ = ZoneInfo(config.DISPLAY_TZ)
MAX_PROMPT = 2400        # caractères avant encodage : au-delà, certains navigateurs refusent le lien

# Alertes trop techniques pour le résumé « En clair » (elles restent dans le détail)
_TECH = ("1re observation", "Pas encore d'historique", "Classement indisponible", "2 sets gagnants",
         "règle de secours", "Peu de matchs pour comparer")

INTRO = ("Tu es mon assistant pour analyser des paris sportifs (je parie sur Unibet, mise de base "
         f"{config.BASE_STAKE} €). Voici la fiche préparée par mon bot. Réponds en français, simplement, "
         "sans jargon, et rappelle les risques. Si c'est utile, cherche sur le web les dernières infos "
         "(blessures, forfaits, compositions).")


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def _clean_risks(risks: list[str]) -> list[str]:
    return [r for r in risks if not any(t in r for t in _TECH)]


def plain_lines(e, ins, stake: int | None = None) -> list[str]:
    """Phrases simples : quoi jouer, pourquoi, le risque, combien miser."""
    p = ins.win_prob
    stake = stake if stake is not None else stake_for(ins.confidence)
    lines = [f"On joue {e.pick.name} à {e.odds:.2f}. Le bot estime ses chances à {p:.0%}, "
             f"soit environ {round(p * 10)} victoires sur 10 dans ce genre de match."]
    if ins.strengths:
        why = " ; ".join(_lower_first(s) for s in ins.strengths[:3])
        lines.append(f"Pourquoi : {why}.")
    risks = _clean_risks(ins.risks)
    lines.append(f"Attention : {_lower_first(risks[0])}." if risks else
                 "Attention : pas d'alerte particulière, mais aucun match n'est gagné d'avance.")
    lines.append(f"Mise conseillée : {stake} € (confiance {ins.confidence.lower()}, "
                 f"sur une base de {config.BASE_STAKE} €).")
    return lines


def _when(e) -> str:
    return f"{e.matchup.commence_time.astimezone(TZ):%d/%m à %H:%M} (heure de Paris)"


def _odds_line(e, sport: str) -> str:
    m = e.matchup
    if m.unibet is None:
        return "Cotes Unibet : pas encore publiées."
    if sport == "nba":
        return f"Cotes Unibet : {m.away.name} {m.unibet.away:.2f}, {m.home.name} {m.unibet.home:.2f}."
    return f"Cotes Unibet : {m.home.name} {m.unibet.home:.2f}, {m.away.name} {m.unibet.away:.2f}."


def _title(e, sport: str) -> str:
    m = e.matchup
    if sport == "nba":
        return f"Match NBA : {m.away.name} (extérieur) contre {m.home.name} (domicile), le {_when(e)}."
    return f"Match de tennis ({m.tournament}, {m.surface}) : {m.home.name} contre {m.away.name}, le {_when(e)}."


def brief(e, sport: str, ins=None, verdict: str = "", reason: str = "", stake: int | None = None) -> str:
    """Fiche courte d'un match pour Claude (≈ 1 500 caractères maximum)."""
    parts = [_title(e, sport), _odds_line(e, sport)]
    if ins is not None:
        st = stake if stake is not None else stake_for(ins.confidence)
        parts.append(f"Avis du bot : {verdict or 'validé'} — {e.pick.name} gagne, confiance {ins.confidence.lower()}, "
                     f"chances estimées {ins.win_prob:.0%}, mise conseillée {st} €.")
        if ins.strengths:
            parts.append("Atouts : " + " ; ".join(ins.strengths[:4]) + ".")
        risks = _clean_risks(ins.risks)
        if risks:
            parts.append("Points de vigilance : " + " ; ".join(risks[:3]) + ".")
        # Chiffres : les plus utiles d'abord (forme, historique), puis le reste si la place le permet
        prio = ("Forme", "Face-à-face", "Confrontations", "Saisons précédentes", "Bilan", "Sur ",
                "Classement", "Repos", "Dernier", "Effectifs", "Parcours", "Lecture")
        ordered = sorted(ins.sections, key=lambda s: next((i for i, p in enumerate(prio) if s[0].startswith(p)), 99))
        for title, rows in ordered:
            parts.append(f"{title} : " + " / ".join(rows))
    else:
        parts.append(f"Avis du bot : {verdict or 'écarté'}" + (f" — {reason}" if reason else "") + ".")
    site = f"Analyse complète sur mon site : {config.SITE_URL}"
    text, out = "", []
    for p in parts:                       # on coupe proprement si la fiche est trop longue
        if len(text) + len(p) > 1500 - len(site):
            break
        out.append(p)
        text = "\n".join(out)
    return "\n".join(out + [site])


def prompt(brief_text: str, question: str) -> str:
    q = f"{INTRO}\n\n{brief_text}\n\nMa question : {question}"
    return q if len(q) <= MAX_PROMPT else q[:MAX_PROMPT - 1] + "…"


def claude_url(brief_text: str, question: str = "Explique-moi ce match simplement : "
                                                  "faut-il le jouer, et combien miser ?") -> str:
    return "https://claude.ai/new?q=" + quote(prompt(brief_text, question), safe="")

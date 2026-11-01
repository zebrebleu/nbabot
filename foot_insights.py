"""Analyse détaillée d'un match de foot validé, et choix des paris foot (simple + combiné)."""
from __future__ import annotations

from datetime import timedelta

import foot_config as fc
from foot_fetcher import no_vig, season_label
from foot_filters import form_str, h2h_games, ppg, rec
from insights import Insight, leg_probability
from models import Evaluation


def _rank(t) -> str:
    if not t.rank:
        return "classement n.d."
    pts = f", {t.points} pts" if t.points is not None else ""
    return f"{t.rank}{'er' if t.rank == 1 else 'e'}{pts}"


def _goals(gs) -> str:
    gf = sum(g.gf or 0 for g in gs)
    ga = sum(g.ga or 0 for g in gs)
    return f"{gf} buts marqués, {ga} encaissés" if gs else "n.d."


def _season(t, s) -> str:
    gs = t.past.get(s, [])
    return f"{season_label(s)} {rec(gs)} ({sum(g.points for g in gs)} pts)" if gs else ""


def build_insight(e: Evaluation) -> Insight:
    m, pick, opp = e.matchup, e.pick, e.opponent
    t = m.commence_time
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    lieu_o = "à l'extérieur" if e.pick_is_home else "à domicile"
    p5, o5 = pick.before(t)[-fc.FORM_GAMES:], opp.before(t)[-fc.FORM_GAMES:]
    p10, o10 = pick.before(t)[-10:], opp.before(t)[-10:]
    pv = [g for g in pick.before(t) if g.is_home == e.pick_is_home][-5:]
    ov = [g for g in opp.before(t) if g.is_home != e.pick_is_home][-5:]
    h2h = h2h_games(pick, opp, t)
    q = m.reference or m.unibet
    ph, pdraw, pa = no_vig(q)
    prob = leg_probability(e)
    implied = 1 / e.odds

    def cal(tm):
        prev = [g for g in tm.calendar if g.date < t - timedelta(hours=2)]
        nxt = [g for g in tm.calendar if g.date > t + timedelta(hours=2)]
        a = (f"dernier match il y a {(t - prev[-1].date).days} j ({prev[-1].competition})" if prev
             else "pas de match récent connu")
        b = f" · prochain : {nxt[0].competition} le {nxt[0].date:%d/%m}" if nxt else ""
        return a + b

    seasons = sorted(set(pick.past) | set(opp.past), reverse=True)
    sections = [
        ("Classement", [f"{pick.name} : {_rank(pick)}", f"{opp.name} : {_rank(opp)}"]),
        ("Forme (5 derniers matchs)", [f"{pick.name} : {form_str(p5)} ({ppg(p5):.1f} pt/match)",
                                       f"{opp.name} : {form_str(o5)} ({ppg(o5):.1f} pt/match)"]),
        ("Domicile / extérieur", [f"{pick.name} {lieu} : {form_str(pv)}", f"{opp.name} {lieu_o} : {form_str(ov)}"]),
        ("Buts (10 derniers)", [f"{pick.name} : {_goals(p10)}", f"{opp.name} : {_goals(o10)}"]),
        ("Calendrier", [f"{pick.name} : {cal(pick)}", f"{opp.name} : {cal(opp)}"]),
        (f"Face-à-face depuis {season_label(min(seasons)) if seasons else '—'}",
         [f"{pick.name} {rec(h2h)}" + (" · derniers : " + ", ".join(
             f"{g.date:%m/%Y} {g.gf}-{g.ga}" for g in h2h[-4:]) if h2h else "") if h2h
          else "Aucune confrontation sur les 3 dernières saisons"]),
        ("Saisons précédentes", [f"{pick.name} : " + (" · ".join(x for x in (_season(pick, s) for s in seasons) if x) or "n.d."),
                                 f"{opp.name} : " + (" · ".join(x for x in (_season(opp, s) for s in seasons) if x) or "n.d.")]),
        ("Lecture du marché", [f"Cotes Unibet : 1 = {m.unibet.home:.2f} · N = {m.unibet.draw:.2f} · 2 = {m.unibet.away:.2f}",
                               f"Probabilités estimées (marge retirée) : {pick.name} {prob:.0%}, nul {pdraw:.0%}, "
                               f"{opp.name} {(pa if e.pick_is_home else ph):.0%}"]
         + ([f"Évolution Unibet : {e.metrics['opening_odds']:.2f} → {e.odds:.2f}"] if "opening_odds" in e.metrics else [])),
    ]

    strengths, risks = [], []
    if p5 and o5 and ppg(p5) - ppg(o5) >= 1.0:
        strengths.append(f"Nette différence de forme : {form_str(p5)} contre {form_str(o5)}")
    if pv and ppg(pv) >= 2.4:
        strengths.append(f"Très solide {lieu} : {form_str(pv)}")
    if pick.rank and opp.rank and opp.rank - pick.rank >= 8:
        strengths.append(f"Gros écart au classement : {pick.rank}e contre {opp.rank}e")
    if p10 and o10:
        dp = sum((g.gf or 0) - (g.ga or 0) for g in p10) / len(p10)
        do = sum((g.gf or 0) - (g.ga or 0) for g in o10) / len(o10)
        if dp - do >= 1.0:
            strengths.append(f"Écart de niveau : {dp:+.1f} but/match contre {do:+.1f}")
    if len(h2h) >= 3 and sum(g.result == "V" for g in h2h) / len(h2h) >= 0.6:
        strengths.append(f"Domine les face-à-face : {rec(h2h)}")
    if pdraw <= 0.20:
        strengths.append(f"Peu de risque de nul selon le marché ({pdraw:.0%})")
    if prob - implied >= 0.01:
        strengths.append(f"Unibet paie mieux que le marché ({prob:.0%} estimé contre {implied:.0%})")

    for r in e.warnings:
        risks.append(f"{r.name} : {r.reason}")
    risks.append(f"Au foot, le nul fait perdre ce pari : environ {pdraw:.0%} de risque de nul")
    if e.odds >= 1.60:
        risks.append(f"Cote de {e.odds:.2f} : favori moins net, une défaite est plausible")
    if prob - implied <= -0.03:
        risks.append(f"Cote Unibet en dessous du marché ({implied:.0%} implicite contre {prob:.0%} estimé)")
    risks.append("Compositions et blessures : à vérifier avant le match (bouton « Demander à Claude »)")

    n_alert = len(risks) - 2          # le nul et les compositions sont toujours rappelés
    if prob >= 0.70 and pdraw <= 0.21 and e.score >= 0.25 and n_alert <= 0:
        confidence = "Élevée"
    elif prob >= 0.58 and n_alert <= 2:
        confidence = "Moyenne"
    else:
        confidence = "Prudente"

    summary = (f"{pick.name} ({_rank(pick)}) est favori {lieu} face à {opp.name} ({_rank(opp)}) en "
               f"{m.league_name}. Probabilité de victoire estimée : {prob:.0%}, nul {pdraw:.0%}.")
    return Insight(summary, sections, strengths, risks, confidence, prob)


def best_bet(candidates: list[Evaluation]):
    from analyzer import proposals_from, rank_options
    return proposals_from(rank_options(candidates, fc.BET_MAX_LEGS, fc.BET_MIN_ODDS, fc.BET_MAX_ODDS, 0.10))

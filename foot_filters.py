"""
Filtres stricts FOOT. Le pari étudié est la victoire du favori Unibet (cote 1 ou 2 la plus basse).
Un match n'est retenu que si tous les filtres passent ; une donnée insuffisante donne une alerte.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import foot_config as fc
from foot_fetcher import FGame, FootMatch, FTeam, no_vig
from models import Evaluation, FilterResult


def ppg(gs: list[FGame]) -> float:
    return sum(g.points for g in gs) / len(gs) if gs else 0.0


def form_str(gs: list[FGame]) -> str:
    return "".join(g.result for g in gs) or "—"


def rec(gs: list[FGame]) -> str:
    v, n = sum(g.result == "V" for g in gs), sum(g.result == "N" for g in gs)
    return f"{v}V-{n}N-{len(gs) - v - n}D"


def _h(d: timedelta) -> float:
    return d.total_seconds() / 3600


def h2h_games(pick: FTeam, opp: FTeam, t: datetime) -> list[FGame]:
    gs = [g for s in sorted(pick.past) for g in pick.past[s] if g.opponent == opp.id] + \
         [g for g in pick.before(t) if g.opponent == opp.id]
    return sorted(gs, key=lambda g: g.date)


# ---------------------------------------------------------------------------
def f_odds(e: Evaluation, now) -> FilterResult:
    ok = fc.ODDS_MIN <= e.odds <= fc.ODDS_MAX
    return FilterResult("Cote", ok, f"Cote Unibet {e.odds:.2f} {'dans' if ok else 'hors de'} la fourchette "
                                    f"{fc.ODDS_MIN:.2f}–{fc.ODDS_MAX:.2f}")


def f_line(e: Evaluation, now) -> FilterResult:
    m = e.matchup
    if m.opening is None:
        return FilterResult("Mouvement de cote", True, "Pas encore d'historique de cote", warning=True)
    op = m.opening.home if e.pick_is_home else m.opening.away
    e.metrics["opening_odds"] = op
    rise = e.odds - op
    if rise >= fc.LINE_RISE_MAX_ABS or rise / op >= fc.LINE_RISE_MAX_PCT:
        return FilterResult("Mouvement de cote", False, f"Hausse anormale : {op:.2f} → {e.odds:.2f} (+{rise / op:.1%})")
    if _h(now - m.observed_since) < 1:
        return FilterResult("Mouvement de cote", True, "1re observation de la cote : mouvement non vérifiable",
                            warning=True)
    return FilterResult("Mouvement de cote", True, f"Cote {'en baisse' if rise < 0 else 'stable'} : {op:.2f} → {e.odds:.2f}")


def f_draw(e: Evaluation, now) -> FilterResult:
    """Anti-nul : marché qui croit au nul, ou deux équipes qui font souvent match nul."""
    m = e.matchup
    q = m.reference or m.unibet
    _, pd, _ = no_vig(q)
    e.metrics["draw_prob"] = pd
    t = m.commence_time
    rp = [g for g in e.pick.before(t)][-fc.DRAW_RATE_GAMES:]
    ro = [g for g in e.opponent.before(t)][-fc.DRAW_RATE_GAMES:]
    dp = sum(g.result == "N" for g in rp) / len(rp) if rp else 0
    do = sum(g.result == "N" for g in ro) / len(ro) if ro else 0
    e.metrics.update(draw_rate_pick=dp, draw_rate_opp=do)
    if pd > fc.DRAW_MAX_PROB:
        return FilterResult("Risque de nul", False, f"Le marché donne {pd:.0%} de chances au nul "
                                                    f"(cote du nul {q.draw:.2f}) : match trop équilibré")
    if (dp >= fc.DRAW_RATE_BOTH and do >= fc.DRAW_RATE_BOTH) or max(dp, do) >= fc.DRAW_RATE_ONE:
        return FilterResult("Risque de nul", False, f"Équipes qui font souvent match nul : {dp:.0%} et {do:.0%} "
                                                    f"de nuls sur leurs {fc.DRAW_RATE_GAMES} derniers matchs")
    return FilterResult("Risque de nul", True, f"Nul estimé à {pd:.0%} ; nuls récents {dp:.0%} et {do:.0%}")


def f_fatigue(e: Evaluation, now) -> FilterResult:
    t = e.matchup.commence_time
    prev = [g for g in e.pick.calendar if g.date < t - timedelta(hours=2)]
    if not prev:
        return FilterResult("Fatigue", True, "Pas de match récent connu")
    last = prev[-1]
    gap = _h(t - last.date)
    e.metrics["rest_hours"] = gap
    if gap < fc.REST_MIN_HOURS:
        return FilterResult("Fatigue", False, f"A joué il y a {gap:.0f} h ({last.competition} contre {last.opponent_name})")
    return FilterResult("Fatigue", True, f"{gap / 24:.1f} jours de repos depuis {last.competition}")


def f_trap(e: Evaluation, now) -> FilterResult:
    """Match « piège » : Coupe d'Europe juste après, contre un adversaire de championnat plus faible."""
    t = e.matchup.commence_time
    nxt = [g for g in e.pick.calendar if t + timedelta(hours=2) < g.date <= t + timedelta(hours=fc.TRAP_WINDOW_HOURS)
           and g.competition.startswith(("Ligue des", "Ligue Europa", "Ligue Conf"))]
    if nxt:
        g = nxt[0]
        weaker = (e.pick.rank or 99) < (e.opponent.rank or 99)
        if weaker:
            return FilterResult("Match piège", False, f"{g.competition} contre {g.opponent_name} dans "
                                                      f"{_h(g.date - t):.0f} h : risque de rotation")
        return FilterResult("Match piège", True, f"{g.competition} dans {_h(g.date - t):.0f} h, mais l'adversaire "
                                                 "du jour est d'un bon niveau", warning=True)
    return FilterResult("Match piège", True, "Pas de Coupe d'Europe dans les 3 jours suivants")


def f_form(e: Evaluation, now) -> FilterResult:
    t = e.matchup.commence_time
    last = e.pick.before(t)[-fc.FORM_GAMES:]
    venue = [g for g in e.pick.before(t) if g.is_home == e.pick_is_home][-fc.FORM_GAMES:]
    e.metrics.update(pick_ppg=ppg(last), venue_ppg=ppg(venue))
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    if len(last) < fc.FORM_MIN_GAMES:
        return FilterResult("Forme", True, f"Peu de matchs connus ({len(last)})", warning=True)
    if ppg(last) < fc.FORM_MIN_PPG:
        return FilterResult("Forme", False, f"{form_str(last)} sur les {len(last)} derniers "
                                            f"({ppg(last):.1f} point par match)")
    if len(venue) >= fc.FORM_MIN_GAMES and ppg(venue) < fc.VENUE_MIN_PPG:
        return FilterResult("Forme", False, f"Fragile {lieu} : {form_str(venue)} ({ppg(venue):.1f} pt/match)")
    return FilterResult("Forme", True, f"{form_str(last)} sur les {len(last)} derniers ({ppg(last):.1f} pt/match)"
                                       + (f", {lieu} {form_str(venue)}" if venue else ""))


def f_dynamics(e: Evaluation, now) -> FilterResult:
    t = e.matchup.commence_time
    p, o = e.pick.before(t)[-fc.FORM_GAMES:], e.opponent.before(t)[-fc.FORM_GAMES:]
    e.metrics["opp_ppg"] = ppg(o)
    s = f"{e.pick.name} {form_str(p)} vs {e.opponent.name} {form_str(o)}"
    if len(o) >= fc.FORM_MIN_GAMES and ppg(o) >= fc.DOG_HOT_PPG and ppg(p) < ppg(o):
        return FilterResult("Dynamique croisée", False, f"Outsider en feu : {s}")
    if len(p) >= fc.FORM_MIN_GAMES and len(o) >= fc.FORM_MIN_GAMES and ppg(o) > ppg(p) + 0.3:
        return FilterResult("Dynamique croisée", False, f"L'outsider est en meilleure forme : {s}")
    return FilterResult("Dynamique croisée", True, s)


def f_rank(e: Evaluation, now) -> FilterResult:
    rp, ro = e.pick.rank, e.opponent.rank
    if not rp or not ro:
        return FilterResult("Classement", True, "Classement indisponible", warning=True)
    o = lambda r: f"{r}{'er' if r == 1 else 'e'}"
    if rp - ro > fc.RANK_TOLERANCE:
        return FilterResult("Classement", False, f"Le favori est {o(rp)}, l'adversaire {o(ro)} : le classement contredit la cote")
    return FilterResult("Classement", True, f"{e.pick.name} {o(rp)}, {e.opponent.name} {o(ro)}")


def f_h2h(e: Evaluation, now) -> FilterResult:
    gs = h2h_games(e.pick, e.opponent, e.matchup.commence_time)
    if not gs:
        return FilterResult("Face-à-face", True, "Aucune confrontation sur les 3 dernières saisons")
    v, d = sum(g.result == "V" for g in gs), sum(g.result == "D" for g in gs)
    txt = f"{rec(gs)} depuis {gs[0].date.year}"
    if len(gs) >= fc.H2H_MIN_MEETINGS and d > v:
        return FilterResult("Face-à-face", False, f"L'adversaire domine les face-à-face : {txt}")
    if gs[-1].result == "D":
        return FilterResult("Face-à-face", True, f"A perdu la dernière confrontation ({txt})", warning=True)
    return FilterResult("Face-à-face", True, txt)


FILTERS: list[Callable] = [f_odds, f_line, f_draw, f_fatigue, f_trap, f_form, f_dynamics, f_rank, f_h2h]


def evaluate(m: FootMatch, now: datetime) -> Evaluation:
    if m.state != "pre":
        return Evaluation(m, None, None, True, 0.0, [FilterResult("Statut", False, "Match commencé")])
    if m.unibet is None:
        return Evaluation(m, None, None, True, 0.0,
                          [FilterResult("Cote", False, "Cote Unibet pas encore publiée pour ce match")])
    home_fav = m.unibet.home <= m.unibet.away
    e = Evaluation(m, m.home if home_fav else m.away, m.away if home_fav else m.home, home_fav,
                   m.unibet.home if home_fav else m.unibet.away)
    for f in FILTERS:
        try:
            e.results.append(f(e, now))
        except Exception as exc:          # une donnée manquante ne valide jamais un match
            e.results.append(FilterResult(f.__name__.removeprefix("f_"), False, f"Erreur de données : {exc}"))
    q = m.reference or m.unibet
    ph, pdraw, pa = no_vig(q)
    e.metrics["fair_prob"] = ph if home_fav else pa
    e.metrics["edge"] = e.metrics["fair_prob"] - 1 / e.odds
    edge = max(-0.1, min(0.1, e.metrics["edge"])) * 10
    e.score = (0.4 * (e.metrics.get("pick_ppg", 1.5) - e.metrics.get("opp_ppg", 1.5)) / 3
               + 0.3 * (1 - pdraw * 3) + 0.3 * edge)
    return e


def evaluate_all(matches: list[FootMatch], now: datetime) -> list[Evaluation]:
    return [evaluate(m, now) for m in matches]

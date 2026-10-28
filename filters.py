"""
Filtres stricts. Chaque filtre renvoie un FilterResult (validé / rejeté + raison factuelle).

Un match n'est retenu que si TOUS les filtres sont validés. Tous les filtres sont
exécutés même après un rejet, pour que le rapport puisse expliquer chaque cause.
Le pari étudié est toujours le favori Unibet (cote la plus basse).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import config
from models import Evaluation, FilterResult, Matchup


@dataclass
class FilterContext:
    contenders: set[str]
    contenders_source: str = ""
    key_players: dict[str, list[str]] = field(default_factory=lambda: dict(config.KEY_PLAYERS))
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_teams: int = 30
    thresholds: Optional[config.SeasonThresholds] = None   # None = déduit de la date

    def __post_init__(self) -> None:
        if self.thresholds is None:
            self.thresholds = config.season_thresholds(self.now)


def _insufficient(name: str, reason: str, ctx: FilterContext) -> FilterResult:
    """Données trop maigres : rejet strict, ou validation avec alerte selon la période."""
    if ctx.thresholds.INSUFFICIENT_DATA == "warn":
        return FilterResult(name, True, f"{reason} — toléré en {ctx.thresholds.label}", warning=True)
    return FilterResult(name, False, reason)


def _key_players_for(team_key: str, ctx: FilterContext) -> list[str]:
    """Liste des joueurs clés, ou [] si l'équipe n'est pas (ou mal) renseignée."""
    players = ctx.key_players.get(team_key) if isinstance(ctx.key_players, dict) else None
    if not isinstance(players, (list, tuple)):
        return []
    return [p for p in players if isinstance(p, str) and p.strip()]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower().strip()


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


# ---------------------------------------------------------------------------
# 1. Cotes
# ---------------------------------------------------------------------------
def f_odds_range(e: Evaluation, ctx: FilterContext) -> FilterResult:
    ok = config.ODDS_MIN <= e.odds <= config.ODDS_MAX
    where = "dans" if ok else "hors de"
    return FilterResult("Cote", ok,
                        f"Cote Unibet {e.odds:.2f} {where} la fourchette {config.ODDS_MIN:.2f}–{config.ODDS_MAX:.2f}")


def f_line_movement(e: Evaluation, ctx: FilterContext) -> FilterResult:
    m = e.matchup
    name = "Mouvement de cote"
    if m.opening is None or m.observed_since is None:
        return FilterResult(name, not config.LINE_REQUIRE_HISTORY, "Aucun historique de cote", warning=True)

    open_pick = m.opening.home if e.pick_is_home else m.opening.away
    open_other = m.opening.away if e.pick_is_home else m.opening.home
    if open_pick > open_other:
        return FilterResult(name, False,
                            f"Le favori a changé depuis la 1re observation (était à {open_pick:.2f})")

    rise = e.odds - open_pick
    pct = rise / open_pick
    e.metrics["opening_odds"] = open_pick
    if rise >= config.LINE_RISE_MAX_ABS or pct >= config.LINE_RISE_MAX_PCT:
        return FilterResult(name, False,
                            f"Hausse anormale de la cote du favori : {open_pick:.2f} → {e.odds:.2f} (+{pct:.1%})")

    observed_min = _hours(ctx.now - m.observed_since) * 60
    if observed_min < config.LINE_MIN_OBSERVATION_MINUTES:
        ok = not config.LINE_REQUIRE_HISTORY
        return FilterResult(name, ok,
                            f"1re observation il y a {observed_min:.0f} min : mouvement non vérifiable, "
                            "relance le script plus près du match", warning=True)

    trend = "en baisse" if rise < 0 else "stable"
    return FilterResult(name, True,
                        f"Cote {trend} sur {observed_min / 60:.1f} h : {open_pick:.2f} → {e.odds:.2f}")


def f_season_start(e: Evaluation, ctx: FilterContext) -> FilterResult:
    """Blocage de début de saison : chaque équipe doit avoir joué SEASON_MIN_GAMES matchs."""
    need = config.SEASON_MIN_GAMES
    t = e.matchup.commence_time
    gp, go = len(e.pick.completed_before(t)), len(e.opponent.completed_before(t))
    e.metrics.update(games_pick=gp, games_opp=go)
    if need and min(gp, go) < need:
        detail = (f"{e.pick.name} : {gp} match(s) joué(s), {e.opponent.name} : {go} "
                  f"({need} requis pour chaque équipe)")
        if config.EARLY_SEASON_ALLOW_BETS and ctx.thresholds is config.EARLY_SEASON:
            return FilterResult("Début de saison", True,
                                f"Peu de matchs joués, analyse moins fiable — {detail}", warning=True)
        return FilterResult("Début de saison", False, detail)
    return FilterResult("Début de saison", True,
                        f"Assez de recul : {gp} et {go} matchs joués" if need else "Blocage désactivé")


# ---------------------------------------------------------------------------
# 2. Calendrier & fatigue
# ---------------------------------------------------------------------------
def f_back_to_back(e: Evaluation, ctx: FilterContext) -> FilterResult:
    t = e.matchup.commence_time
    opp_prev = e.opponent.previous_game(t)
    e.metrics["opp_rest_hours"] = _hours(t - opp_prev.date) if opp_prev else None

    prev = e.pick.previous_game(t)
    if prev is None:
        e.metrics["rest_hours"] = None
        return FilterResult("Back-to-back", True, "Aucun match joué juste avant")
    gap = _hours(t - prev.date)
    e.metrics["rest_hours"] = gap
    if gap <= config.B2B_MAX_GAP_HOURS:
        if not e.pick_is_home:
            return FilterResult("Back-to-back", False,
                                f"2e match en ~24 h ET à l'extérieur (veille vs {prev.opponent.title()})")
        return FilterResult("Back-to-back", True,
                            "Back-to-back mais à domicile (toléré) — fatigue possible", warning=True)
    return FilterResult("Back-to-back", True, f"Pas de B2B : {gap / 24:.1f} jour(s) depuis le dernier match")


def f_trap_game(e: Evaluation, ctx: FilterContext) -> FilterResult:
    t = e.matchup.commence_time
    nxt = e.pick.next_game(t)
    if nxt and _hours(nxt.date - t) <= config.TRAP_GAME_WINDOW_HOURS \
            and nxt.opponent in ctx.contenders and e.opponent.key not in ctx.contenders:
        return FilterResult("Trap game", False,
                            f"Choc contre {nxt.opponent.title()} (contender) dans {_hours(nxt.date - t):.0f} h")
    detail = f"prochain match vs {nxt.opponent.title()}" if nxt else "pas de match proche"
    return FilterResult("Trap game", True, f"Pas de piège de calendrier ({detail})")


def f_road_trip(e: Evaluation, ctx: FilterContext) -> FilterResult:
    if e.pick_is_home:
        return FilterResult("Road trip", True, "Joue à domicile")
    streak = 1  # le match du jour
    for g in reversed(e.pick.games_before(e.matchup.commence_time)):
        if g.is_home:
            break
        streak += 1
    if streak > config.ROAD_TRIP_MAX_CONSECUTIVE:
        return FilterResult("Road trip", False, f"{streak}e match consécutif à l'extérieur")
    return FilterResult("Road trip", True, f"{streak}e match consécutif à l'extérieur seulement")


# ---------------------------------------------------------------------------
# 3. Forme & dynamique
# ---------------------------------------------------------------------------
def f_venue_form(e: Evaluation, ctx: FilterContext) -> FilterResult:
    th = ctx.thresholds
    name = "Forme dom./ext."
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    games = [g for g in e.pick.completed_before(e.matchup.commence_time) if g.is_home == e.pick_is_home]
    games = games[-th.VENUE_FORM_GAMES:]
    wins = sum(1 for g in games if g.won)
    if games:
        e.metrics.update(venue_wins=wins, venue_games=len(games))

    if len(games) < th.VENUE_FORM_GAMES:
        reason = (f"Données insuffisantes : {len(games)} match(s) {lieu} cette saison "
                  f"({th.VENUE_FORM_GAMES} requis)")
        # Même toléré, un bilan déjà négatif sur le peu de matchs joués reste un rejet
        if games and wins < th.venue_min_wins(len(games)):
            return FilterResult(name, False, f"{reason}, et bilan {wins}V-{len(games) - wins}D")
        return _insufficient(name, reason, ctx)

    need = th.venue_min_wins(len(games))
    ok = wins >= need
    return FilterResult(name, ok,
                        f"{wins}V-{len(games) - wins}D sur ses {len(games)} derniers {lieu} ({need} V requises)")


def _win_streak(games) -> int:
    n = 0
    for g in reversed(games):
        if not g.won:
            break
        n += 1
    return n


def f_cross_dynamics(e: Evaluation, ctx: FilterContext) -> FilterResult:
    t = e.matchup.commence_time
    name = "Dynamique croisée"
    th = ctx.thresholds
    pl = e.pick.completed_before(t)[-config.L10_GAMES:]
    ol = e.opponent.completed_before(t)[-config.L10_GAMES:]
    pw, ow = sum(1 for g in pl if g.won), sum(1 for g in ol if g.won)
    p_rate = pw / len(pl) if pl else 0.0
    o_rate = ow / len(ol) if ol else 0.0
    # Le score compare des taux (fenêtres de tailles différentes en début de saison)
    e.metrics.update(pick_l10_wins=p_rate * 10, opp_l10_wins=o_rate * 10, l10_n=len(pl))
    summary = (f"{e.pick.name} {pw}-{len(pl) - pw} vs {e.opponent.name} {ow}-{len(ol) - ow} "
               f"sur les {max(len(pl), len(ol))} derniers")

    # Ces deux règles s'appliquent même avec peu de matchs : un signal négatif suffit à rejeter
    if pl and ol and o_rate >= config.DOG_HOT_MIN_RATE and p_rate <= config.FAV_DOUBT_MAX_RATE:
        return FilterResult(name, False, f"Outsider en feu, favori qui doute : {summary}")
    if pl and ol and o_rate > p_rate:
        return FilterResult(name, False, f"L'outsider est en meilleure forme : {summary}")

    opp_streak = _win_streak(ol)
    pick_losses_3 = sum(1 for g in pl[-3:] if not g.won)
    if opp_streak >= config.DOG_HOT_STREAK and pick_losses_3 >= 2:
        return FilterResult(name, False,
                            f"Outsider sur {opp_streak} victoires de suite, favori {pick_losses_3} défaites sur 3")

    if len(pl) < th.L10_MIN_GAMES or len(ol) < th.L10_MIN_GAMES:
        return _insufficient(name, f"Données insuffisantes : {len(pl)} et {len(ol)} matchs joués "
                                   f"({th.L10_MIN_GAMES} requis) — {summary}", ctx)
    return FilterResult(name, True, summary)


# ---------------------------------------------------------------------------
# 4. Effectif & contexte
# ---------------------------------------------------------------------------
def f_injuries(e: Evaluation, ctx: FilterContext) -> FilterResult:
    blocking = [i for i in e.pick.injuries if _norm(i.status) in config.BLOCKING_STATUSES]
    listed = ", ".join(f"{i.player} ({i.status})" for i in blocking) or "aucun"
    keys = _key_players_for(e.pick.key, ctx)

    if keys:
        key_norm = [_norm(p) for p in keys]
        absent_keys = [i for i in blocking if _norm(i.player) in key_norm]
        if any(_norm(i.player) == key_norm[0] for i in absent_keys):
            star = next(i for i in absent_keys if _norm(i.player) == key_norm[0])
            return FilterResult("Infirmerie", False, f"Franchise player {star.player} : {star.status}")
        if len(absent_keys) > config.KEY_STARTERS_MAX_ABSENT:
            names = ", ".join(f"{i.player} ({i.status})" for i in absent_keys)
            return FilterResult("Infirmerie", False, f"Plusieurs titulaires majeurs touchés : {names}")
        return FilterResult("Infirmerie", True,
                            f"Joueurs clés disponibles ({keys[0]} OK). Absents/incertains : {listed}")

    # Règle de secours : équipe absente de KEY_PLAYERS (ou liste vide / mal formée)
    fallback = f"règle de secours ({e.pick.name} absente de KEY_PLAYERS)"
    if len(blocking) >= config.GENERIC_MAX_ABSENT:
        return FilterResult("Infirmerie", False,
                            f"{len(blocking)} joueurs absents/incertains, seuil de {config.GENERIC_MAX_ABSENT} "
                            f"atteint — {fallback} : {listed}")
    if blocking:
        return FilterResult("Infirmerie", True,
                            f"{len(blocking)} absent(s)/incertain(s) < {config.GENERIC_MAX_ABSENT} — {fallback} : "
                            f"{listed}. Vérifie qu'aucun n'est un titulaire", warning=True)
    return FilterResult("Infirmerie", True, f"Aucun absent ni incertain — {fallback}")


def f_anti_tanking(e: Evaluation, ctx: FilterContext) -> FilterResult:
    if e.matchup.commence_time.month not in config.TANKING_MONTHS:
        return FilterResult("Anti-tanking", True, "Hors période de fin de saison")
    limit = ctx.total_teams - config.TANKING_BOTTOM_N
    bottom = [t.name for t in (e.pick, e.opponent) if t.league_rank and t.league_rank > limit]
    if bottom:
        return FilterResult("Anti-tanking", False,
                            f"Fin de saison avec équipe(s) en fin de peloton : {', '.join(bottom)}")
    return FilterResult("Anti-tanking", True, "Aucune équipe en fin de peloton")


FILTERS: list[Callable[[Evaluation, FilterContext], FilterResult]] = [
    f_season_start,
    f_odds_range,
    f_line_movement,
    f_back_to_back,
    f_trap_game,
    f_road_trip,
    f_venue_form,
    f_cross_dynamics,
    f_injuries,
    f_anti_tanking,
]


def evaluate(m: Matchup, ctx: FilterContext) -> Evaluation:
    if m.state != "pre":
        label = "Match en cours" if m.state == "in" else "Match terminé"
        return Evaluation(m, None, None, True, 0.0, [FilterResult("Statut", False, label)])
    if m.unibet is None:
        return Evaluation(m, None, None, True, 0.0,
                          [FilterResult("Cote", False, "Cote Unibet pas encore publiée pour ce match")])
    pick_is_home = m.unibet.home <= m.unibet.away
    e = Evaluation(
        matchup=m,
        pick=m.home if pick_is_home else m.away,
        opponent=m.away if pick_is_home else m.home,
        pick_is_home=pick_is_home,
        odds=m.unibet.home if pick_is_home else m.unibet.away,
    )
    for f in FILTERS:
        try:
            e.results.append(f(e, ctx))
        except Exception as exc:  # une donnée manquante ne doit jamais valider un match
            e.results.append(FilterResult(f.__name__.removeprefix("f_"), False, f"Erreur de données : {exc}"))
    return e


def evaluate_all(matchups: list[Matchup], ctx: FilterContext) -> list[Evaluation]:
    return [evaluate(m, ctx) for m in matchups]

"""
Foot : récupération des données — aucune connexion au site d'un bookmaker.

  * The Odds API : liste des matchs à venir (gratuite), puis cotes 1N2 d'un championnat
    seulement s'il a un match dans les 60 h (1 crédit par championnat et par passage).
  * API publique ESPN : calendrier et résultats des 5 championnats, classements, résultats
    des 3 saisons passées, matchs de Coupe d'Europe et de coupes nationales (fatigue, rotation).

data/foot_diag.json résume ce qui a été lu à chaque passage.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

import config
import foot_config as fc
from data_fetcher import CachedHttp, OddsHistory, _iter_lists, _score, parse_dt
from models import OddsQuote

log = logging.getLogger(__name__)

ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer"
HISTORY_FILE = config.DATA_DIR / "foot_odds_history.json"
DIAG_FILE = config.DATA_DIR / "foot_diag.json"
DRAW = "Match nul"


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
@dataclass
class Quote3:
    home: float
    draw: float
    away: float
    bookmaker: str
    last_update: str = ""


@dataclass
class FGame:
    date: datetime
    opponent: str               # id ESPN de l'adversaire
    opponent_name: str
    is_home: bool
    gf: Optional[int]           # buts marqués
    ga: Optional[int]           # buts encaissés
    competition: str = ""
    completed: bool = True

    @property
    def result(self) -> str:    # V / N / D
        if self.gf is None or self.ga is None:
            return "?"
        return "V" if self.gf > self.ga else "N" if self.gf == self.ga else "D"

    @property
    def points(self) -> int:
        return {"V": 3, "N": 1}.get(self.result, 0)

    @property
    def won(self) -> bool:      # compatibilité avec le reste du bot
        return self.result == "V"


@dataclass
class FTeam:
    id: str
    name: str
    league: str
    short: str = ""
    rank: Optional[int] = None
    points: Optional[int] = None
    played: Optional[int] = None
    goal_diff: Optional[int] = None
    games: list[FGame] = field(default_factory=list)       # championnat, saison en cours, terminés
    calendar: list[FGame] = field(default_factory=list)    # toutes compétitions autour de la date (passés et à venir)
    past: dict = field(default_factory=dict)               # {saison: [FGame]} (championnat)

    @property
    def key(self) -> str:
        return self.id

    def before(self, t: datetime) -> list[FGame]:
        return [g for g in self.games if g.date < t - timedelta(hours=1)]


@dataclass
class FootMatch:
    event_id: str
    commence_time: datetime
    home: FTeam
    away: FTeam
    unibet: Optional[Quote3]
    reference: Optional[Quote3]
    league: str
    league_name: str
    opening: Optional[OddsQuote] = None
    observed_since: Optional[datetime] = None
    n_observations: int = 0
    state: str = "pre"
    status_detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.home.name} – {self.away.name}"

    @property
    def tournament(self) -> str:            # nom commun avec le tennis (affichage, ticket)
        return self.league_name


@dataclass
class FootSlate:
    matches: list[FootMatch]
    generated_at: datetime
    leagues: list[str]
    source_label: str = "The Odds API + ESPN"
    diag: dict = field(default_factory=dict)
    teams: dict = field(default_factory=dict)
    last_bet: Optional[dict] = None
    results: list = field(default_factory=list)      # matchs des 5 derniers jours (pour le résultat des paris)


# ---------------------------------------------------------------------------
# Noms d'équipes
# ---------------------------------------------------------------------------
_STOP = {"fc", "cf", "ac", "as", "sc", "afc", "rc", "ss", "ssc", "us", "og", "ogc", "sv", "vfb", "vfl",
         "fsv", "tsg", "de", "la", "le", "club", "calcio", "and", "the", "1", "04", "05", "1899", "1900",
         "1907", "1909", "1913", "cd", "ud", "sd", "rcd", "ca", "losc", "stade", "hotspur"}


def norm_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s.replace("-", " "))
    s = " ".join(s.split())
    return fc.ALIASES.get(s, s)


def _tokens(name: str) -> set[str]:
    return {t for t in norm_team(name).replace("-", " ").split() if t not in _STOP}


def name_score(a: str, names: list[str]) -> float:
    """Ressemblance (0 à 1) entre un nom The Odds API et les noms ESPN d'une équipe."""
    ta, best = _tokens(a), 0.0
    if not ta:
        return 0.0
    for n in names:
        tb = _tokens(n)
        if not tb:
            continue
        if norm_team(a) == norm_team(n):
            return 1.0
        inter = len(ta & tb)
        best = max(best, inter / len(ta | tb), 0.9 * inter / min(len(ta), len(tb)) if inter else 0)
    return best


def _season_now(now: datetime) -> int:
    """Saison ESPN en cours (année de début) : novembre 2026 -> 2026 (saison 2026-27)."""
    return now.year if now.month >= 7 else now.year - 1


def season_label(season: int) -> str:
    return f"{season}-{str(season + 1)[-2:]}"


# ---------------------------------------------------------------------------
# ESPN
# ---------------------------------------------------------------------------
def _parse_events(data: dict, competition: str) -> list[dict]:
    out = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in sides or "away" not in sides:
            continue
        st = (ev.get("status") or comp.get("status") or {}).get("type", {})
        when = ev.get("date") or comp.get("date")
        if not when:
            continue
        h, a = sides["home"], sides["away"]
        out.append({
            "id": str(ev.get("id", "")), "date": parse_dt(when), "competition": competition,
            "state": st.get("state", "pre"), "completed": bool(st.get("completed")),
            "detail": st.get("shortDetail", ""),
            "home_id": str(h.get("team", {}).get("id", h.get("id", ""))),
            "home": h.get("team", {}).get("displayName", ""),
            "away_id": str(a.get("team", {}).get("id", a.get("id", ""))),
            "away": a.get("team", {}).get("displayName", ""),
            "home_score": _score(h), "away_score": _score(a),
        })
    return out


def _games_for(events: list[dict], team_id: str) -> list[FGame]:
    out = []
    for e in events:
        if team_id not in (e["home_id"], e["away_id"]):
            continue
        home = e["home_id"] == team_id
        gf, ga = (e["home_score"], e["away_score"]) if home else (e["away_score"], e["home_score"])
        done = e["completed"] or e["state"] == "post"
        out.append(FGame(e["date"], e["away_id"] if home else e["home_id"], e["away"] if home else e["home"],
                         home, int(gf) if done and gf is not None else None,
                         int(ga) if done and ga is not None else None, e["competition"], done))
    out.sort(key=lambda g: g.date)
    return out


class ESPNSoccer:
    def __init__(self, http: CachedHttp):
        self.http = http

    def teams(self, lg: str) -> dict[str, dict]:
        data = self.http.get_json(f"{ESPN_SITE}/{lg}/teams", ttl_minutes=24 * 60)
        out = {}
        for item in _iter_lists(data, "teams"):
            t = item.get("team", item)
            if t.get("id") and t.get("displayName"):
                out[str(t["id"])] = {"name": t["displayName"], "short": t.get("shortDisplayName", ""),
                                     "names": [t.get(k, "") for k in ("displayName", "shortDisplayName", "name",
                                                                      "location", "nickname") if t.get(k)]}
        return out

    def standings(self, lg: str) -> dict[str, dict]:
        data = self.http.get_json(f"{ESPN_STANDINGS}/{lg}/standings", ttl_minutes=6 * 60)
        rows = {}
        for entry in _iter_lists(data, "entries"):
            team = entry.get("team", {})
            stats = {(s.get("name") or s.get("type") or ""): s.get("value") for s in entry.get("stats", [])}
            if team.get("id"):
                rows[str(team["id"])] = {"points": stats.get("points"), "played": stats.get("gamesPlayed"),
                                         "gd": stats.get("pointDifferential"), "rank": stats.get("rank")}
        # Rang : celui d'ESPN, sinon calculé (points puis différence de buts)
        if rows and not all(r["rank"] for r in rows.values()):
            order = sorted(rows, key=lambda k: (rows[k]["points"] or 0, rows[k]["gd"] or 0), reverse=True)
            for i, k in enumerate(order, 1):
                rows[k]["rank"] = i
        return rows

    def scoreboard(self, code: str, start: datetime, end: datetime, label: str, ttl: float = 30) -> list[dict]:
        rng = f"{start:%Y%m%d}-{end:%Y%m%d}"
        data = self.http.get_json(f"{ESPN_SITE}/{code}/scoreboard", params={"dates": rng, "limit": 300},
                                  ttl_minutes=ttl)
        return _parse_events(data, label)

    def team_season(self, lg: str, team_id: str, season: int, past: bool) -> list[dict]:
        data = self.http.get_json(f"{ESPN_SITE}/{lg}/teams/{team_id}/schedule", params={"season": season},
                                  ttl_minutes=30 * 24 * 60 if past else 6 * 60, long_term=past)
        return _parse_events(data, "championnat")


# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------
def _quotes(ev: dict) -> dict[str, Quote3]:
    h, a = ev.get("home_team"), ev.get("away_team")
    out = {}
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            p = {o["name"]: float(o["price"]) for o in mk.get("outcomes", [])}
            d = p.get("Draw") or p.get("draw")
            if h in p and a in p and d:
                out[bk["key"]] = Quote3(p[h], d, p[a], bk["key"], bk.get("last_update", ""))
    return out


def no_vig(q: Quote3) -> tuple[float, float, float]:
    """Probabilités 1 / N / 2 sans la marge du bookmaker."""
    inv = [1 / q.home, 1 / q.draw, 1 / q.away]
    s = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
class FootFetcher:
    def __init__(self, api_key: str = config.ODDS_API_KEY):
        self.api_key = api_key
        self.http = CachedHttp(config.CACHE_DIR)
        self.espn = ESPNSoccer(self.http)
        self.history = OddsHistory(HISTORY_FILE)

    def _odds_events(self, sport_key: str, now: datetime) -> list[dict]:
        """Cotes d'un championnat, seulement s'il a un match dans la fenêtre (liste des matchs gratuite)."""
        events = self.http.get_json(f"{ODDS_BASE}/{sport_key}/events", params={"apiKey": self.api_key},
                                    ttl_minutes=60, cache_key_params={"k": sport_key})
        horizon = now + timedelta(hours=fc.ODDS_WINDOW_HOURS)
        if not any(now < parse_dt(e["commence_time"]) <= horizon for e in events):
            return []
        params = {"apiKey": self.api_key, "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso",
                  "bookmakers": ",".join(config.ODDS_BOOKMAKERS)}
        return self.http.get_json(f"{ODDS_BASE}/{sport_key}/odds", params=params,
                                  ttl_minutes=config.ODDS_CACHE_MINUTES,
                                  cache_key_params={k: v for k, v in params.items() if k != "apiKey"})

    def load_slate(self) -> FootSlate:
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=fc.ANALYSIS_HOURS)
        win_start, win_end = now - timedelta(days=5), now + timedelta(days=4)
        cur = _season_now(now)
        diag: dict = {"generated_at": now.isoformat(), "leagues": {}, "credits_used": 0, "unmatched": []}

        # Toutes compétitions autour de la date (fatigue / rotation)
        around: list[dict] = []
        for code, label in fc.OTHER_COMPETITIONS.items():
            try:
                around += self.espn.scoreboard(code, win_start, win_end, label, ttl=60)
            except requests.RequestException:
                pass

        teams: dict[str, FTeam] = {}
        matches: list[FootMatch] = []
        leagues_with_games = []
        for lg_key, (odds_key, code, lg_name) in fc.LEAGUES.items():
            d = {"matchs_espn": 0, "cotes": 0, "rapprochés": 0}
            diag["leagues"][lg_name] = d
            try:
                fixtures = self.espn.scoreboard(code, win_start, win_end, lg_name)
                around += fixtures
                upcoming = [f for f in fixtures if f["state"] == "pre" and now < f["date"] <= horizon]
                d["matchs_espn"] = len(upcoming)
                if not upcoming:
                    continue
                team_info = self.espn.teams(code)
                table = self.espn.standings(code)
                odds = self._odds_events(odds_key, now)
                if odds:
                    diag["credits_used"] += 1
                d["cotes"] = len(odds)
            except requests.RequestException as exc:
                log.warning("%s indisponible : %s", lg_name, exc)
                continue
            leagues_with_games.append(lg_name)

            def team(tid: str, fallback: str) -> FTeam:
                if tid not in teams:
                    info, row = team_info.get(tid, {"name": fallback, "short": "", "names": [fallback]}), table.get(tid, {})
                    t = FTeam(tid, info["name"], code, info.get("short", ""),
                              int(row["rank"]) if row.get("rank") else None,
                              int(row["points"]) if row.get("points") is not None else None,
                              int(row["played"]) if row.get("played") is not None else None,
                              int(row["gd"]) if row.get("gd") is not None else None)
                    try:
                        t.games = [g for g in _games_for(self.espn.team_season(code, tid, cur, False), tid)
                                   if g.completed and g.gf is not None]
                    except requests.RequestException:
                        pass
                    for s in range(cur - 1, cur - 1 - config.HISTORY_SEASONS, -1):
                        try:
                            gs = [g for g in _games_for(self.espn.team_season(code, tid, s, True), tid)
                                  if g.completed and g.gf is not None]
                            if gs:
                                t.past[s] = gs
                        except requests.RequestException:
                            pass
                    teams[tid] = t
                return teams[tid]

            for f in upcoming:
                h, a = team(f["home_id"], f["home"]), team(f["away_id"], f["away"])
                names_h = team_info.get(h.id, {}).get("names", [h.name])
                names_a = team_info.get(a.id, {}).get("names", [a.name])
                best, best_s = None, 0.0
                for ev in odds:
                    if abs((parse_dt(ev["commence_time"]) - f["date"]).total_seconds()) > 4 * 3600:
                        continue
                    s = name_score(ev["home_team"], names_h) + name_score(ev["away_team"], names_a)
                    if s > best_s:
                        best, best_s = ev, s
                unibet = ref = None
                eid = f"espn-{f['id']}"
                m = FootMatch(eid, f["date"], h, a, None, None, code, lg_name)
                if best is not None and best_s >= 0.9:
                    d["rapprochés"] += 1
                    q = _quotes(best)
                    unibet = q.get(fc.REFERENCE_BOOKMAKER)
                    ref = q.get(config.SHARP_BOOKMAKER)
                    if ref is None:
                        others = [x for k, x in q.items() if k != fc.REFERENCE_BOOKMAKER]
                        if others:
                            ref = Quote3(statistics.median(x.home for x in others),
                                         statistics.median(x.draw for x in others),
                                         statistics.median(x.away for x in others), "médiane")
                    m.event_id, m.unibet, m.reference = best["id"], unibet, ref
                    if unibet:
                        m.opening, m.observed_since, m.n_observations = self.history.record(
                            best["id"], OddsQuote(unibet.home, unibet.away, "unibet_fr"), now)
                elif odds:
                    diag["unmatched"].append(f"{f['home']} – {f['away']}")
                matches.append(m)

        # Calendrier toutes compétitions de chaque équipe analysée (dédoublonné)
        seen = set()
        uniq = []
        for e in around:
            k = (e["home_id"], e["away_id"], e["date"].date())
            if k not in seen:
                seen.add(k)
                uniq.append(e)
        for t in teams.values():
            t.calendar = _games_for(uniq, t.id)

        self.history.purge(now)
        self.history.save()
        diag["matches"] = len(matches)
        try:
            DIAG_FILE.parent.mkdir(parents=True, exist_ok=True)
            DIAG_FILE.write_text(json.dumps(diag, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        matches.sort(key=lambda m: m.commence_time)
        return FootSlate(matches, now, leagues_with_games, diag=diag, teams=teams, results=uniq)

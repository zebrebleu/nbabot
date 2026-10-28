"""
Récupération des données — aucune connexion au site d'un bookmaker.

Sources :
  * The Odds API (clé gratuite) : cotes Moneyline (h2h) d'Unibet FR + Pinnacle + books FR.
  * API publique (non officielle) d'ESPN : équipes, classement, calendrier, blessures.

Les réponses sont mises en cache sur disque pour ménager les quotas.
Un historique local des cotes (data/odds_history.json) permet de détecter
les hausses anormales entre deux exécutions du script.
"""
from __future__ import annotations

import hashlib
import json
import logging
import statistics
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

import requests

import config
from models import Injury, Matchup, OddsQuote, Slate, TeamContext, TeamGame

log = logging.getLogger(__name__)

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
US_EASTERN = ZoneInfo("America/New_York")   # le calendrier NBA est daté à l'heure de New York


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def team_key(name: str) -> str:
    """'LA Clippers' / 'Los Angeles Clippers' -> 'clippers'.
    Les surnoms NBA sont tous uniques : c'est la clé de jointure entre les API."""
    return name.strip().split()[-1].lower() if name else ""


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iter_lists(obj: Any, key: str) -> Iterator[dict]:
    """Parcourt récursivement un JSON et renvoie les éléments des listes nommées `key`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, list):
                yield from (x for x in v if isinstance(x, dict))
            else:
                yield from _iter_lists(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_lists(v, key)


def _score(competitor: dict) -> Optional[float]:
    s = competitor.get("score")
    if isinstance(s, dict):
        s = s.get("value", s.get("displayValue"))
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class CachedHttp:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "nba-betting-assistant/0.1 (usage personnel)"
        self.last_headers: Any = {}

    def get_json(self, url: str, params: Optional[dict] = None, ttl_minutes: float = 60,
                 cache_key_params: Optional[dict] = None) -> Any:
        key_params = cache_key_params if cache_key_params is not None else (params or {})
        key = hashlib.sha1((url + json.dumps(key_params, sort_keys=True)).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if ttl_minutes > 0 and path.exists() and time.time() - path.stat().st_mtime < ttl_minutes * 60:
            return json.loads(path.read_text(encoding="utf-8"))

        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        self.last_headers = resp.headers
        data = resp.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        return data


# ---------------------------------------------------------------------------
# ESPN : équipes, classement, calendrier, blessures
# ---------------------------------------------------------------------------
class ESPNClient:
    def __init__(self, http: CachedHttp):
        self.http = http

    def teams(self) -> dict[str, dict]:
        data = self.http.get_json(f"{ESPN_SITE}/teams", ttl_minutes=24 * 60)
        out: dict[str, dict] = {}
        for item in _iter_lists(data, "teams"):
            t = item.get("team", item)
            if t.get("displayName") and t.get("id"):
                out[team_key(t["displayName"])] = {
                    "id": str(t["id"]),
                    "abbr": t.get("abbreviation", ""),
                    "name": t["displayName"],
                    "color": t.get("color", ""),
                }
        return out

    def scoreboard(self, day: date) -> list[dict]:
        """Tous les matchs d'une date du calendrier NBA (date de New York)."""
        data = self.http.get_json(f"{ESPN_SITE}/scoreboard",
                                  params={"dates": day.strftime("%Y%m%d"), "limit": 50}, ttl_minutes=10)
        games = []
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            if "home" not in sides or "away" not in sides:
                continue
            status = (ev.get("status") or comp.get("status") or {}).get("type", {})
            games.append({
                "id": str(ev.get("id", "")),
                "date": parse_dt(ev.get("date") or comp.get("date")),
                "home": sides["home"].get("team", {}).get("displayName", ""),
                "away": sides["away"].get("team", {}).get("displayName", ""),
                "state": status.get("state", "pre"),
                "detail": status.get("shortDetail", ""),
                "home_score": _score(sides["home"]),
                "away_score": _score(sides["away"]),
            })
        games.sort(key=lambda g: g["date"])
        return games

    def next_slate(self, start: date, max_days: int = 10) -> tuple[date, list[dict]]:
        """Première date (à partir de `start`) qui a encore au moins un match à venir."""
        for i in range(max_days + 1):
            day = start + timedelta(days=i)
            games = self.scoreboard(day)
            if any(g["state"] == "pre" for g in games):
                return day, games
        return start, self.scoreboard(start)

    def standings(self) -> dict[str, tuple[int, int]]:
        data = self.http.get_json(ESPN_STANDINGS, ttl_minutes=config.ESPN_CACHE_MINUTES)
        out: dict[str, tuple[int, int]] = {}
        for entry in _iter_lists(data, "entries"):
            team = entry.get("team", {})
            stats = {s.get("name") or s.get("type"): s.get("value") for s in entry.get("stats", [])}
            if team.get("displayName") and stats.get("wins") is not None:
                out[team_key(team["displayName"])] = (int(stats["wins"]), int(stats.get("losses") or 0))
        return out

    def injuries(self) -> dict[str, list[Injury]]:
        data = self.http.get_json(f"{ESPN_SITE}/injuries", ttl_minutes=config.INJURIES_CACHE_MINUTES)
        out: dict[str, list[Injury]] = {}
        for block in data.get("injuries", []):
            name = block.get("displayName") or block.get("team", {}).get("displayName", "")
            if not name:
                continue
            items = []
            for inj in block.get("injuries", []):
                status = inj.get("status")
                if isinstance(status, dict):
                    status = status.get("name") or status.get("description")
                if not status:
                    status = inj.get("type", {}).get("description", "")
                items.append(Injury(
                    player=inj.get("athlete", {}).get("displayName", "?"),
                    status=str(status),
                    detail=inj.get("shortComment", ""),
                ))
            out[team_key(name)] = items
        return out

    def team_schedule(self, team_id: str) -> list[TeamGame]:
        data = self.http.get_json(f"{ESPN_SITE}/teams/{team_id}/schedule",
                                  params={"seasontype": 2}, ttl_minutes=config.ESPN_CACHE_MINUTES)
        games: list[TeamGame] = []
        for ev in data.get("events", []):
            comps = ev.get("competitions") or []
            if not comps:
                continue
            comp = comps[0]
            me = opp = None
            for c in comp.get("competitors", []):
                cid = str(c.get("id") or c.get("team", {}).get("id"))
                if cid == str(team_id):
                    me = c
                else:
                    opp = c
            if not me or not opp:
                continue
            completed = bool(comp.get("status", {}).get("type", {}).get("completed"))
            s_me, s_opp = (_score(me), _score(opp)) if completed else (None, None)
            won = me.get("winner") if completed else None
            if completed and won is None:
                won = s_me > s_opp if s_me is not None and s_opp is not None else None
            games.append(TeamGame(
                date=parse_dt(ev.get("date") or comp.get("date")),
                opponent=team_key(opp.get("team", {}).get("displayName", "")),
                is_home=me.get("homeAway") == "home",
                completed=completed,
                won=won,
                points_for=s_me,
                points_against=s_opp,
            ))
        games.sort(key=lambda g: g.date)
        return games


# ---------------------------------------------------------------------------
# The Odds API : cotes Moneyline
# ---------------------------------------------------------------------------
@dataclass
class OddsEvent:
    event_id: str
    commence_time: datetime
    home_team: str
    away_team: str
    quotes: dict[str, OddsQuote]


class OddsClient:
    def __init__(self, http: CachedHttp, api_key: str):
        self.http = http
        self.api_key = api_key

    def fetch(self) -> list[OddsEvent]:
        params = {
            "apiKey": self.api_key,
            "markets": "h2h",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "bookmakers": ",".join(config.ODDS_BOOKMAKERS),
        }
        cache_params = {k: v for k, v in params.items() if k != "apiKey"}
        data = self.http.get_json(ODDS_API_URL, params=params,
                                  ttl_minutes=config.ODDS_CACHE_MINUTES, cache_key_params=cache_params)
        remaining = self.http.last_headers.get("x-requests-remaining") if self.http.last_headers else None
        if remaining is not None:
            log.info("The Odds API — crédits restants : %s", remaining)

        events: list[OddsEvent] = []
        for ev in data:
            home, away = ev["home_team"], ev["away_team"]
            quotes: dict[str, OddsQuote] = {}
            for bk in ev.get("bookmakers", []):
                for mk in bk.get("markets", []):
                    if mk.get("key") != "h2h":
                        continue
                    prices = {o["name"]: float(o["price"]) for o in mk.get("outcomes", [])}
                    if home in prices and away in prices:
                        quotes[bk["key"]] = OddsQuote(prices[home], prices[away], bk["key"], bk.get("last_update", ""))
            events.append(OddsEvent(ev["id"], parse_dt(ev["commence_time"]), home, away, quotes))
        return events


class OddsHistory:
    """Mémorise la 1re cote Unibet vue pour chaque match (détection des hausses)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError:
            log.warning("Historique des cotes illisible, réinitialisé.")
            self.data = {}

    def record(self, event_id: str, quote: OddsQuote, now: datetime) -> tuple[OddsQuote, datetime, int]:
        entry = self.data.setdefault(event_id, {
            "first_seen": now.isoformat(),
            "opening": [quote.home, quote.away],
            "snapshots": [],
        })
        snaps = entry["snapshots"]
        if not snaps or snaps[-1][1:] != [quote.home, quote.away]:
            snaps.append([now.isoformat(), quote.home, quote.away])
            del snaps[:-50]
        opening = OddsQuote(entry["opening"][0], entry["opening"][1], quote.bookmaker)
        return opening, parse_dt(entry["first_seen"]), len(snaps)

    def purge(self, now: datetime, days: int = 4) -> None:
        limit = now - timedelta(days=days)
        self.data = {k: v for k, v in self.data.items() if parse_dt(v["first_seen"]) > limit}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def _median_quote(quotes: list[OddsQuote]) -> Optional[OddsQuote]:
    if not quotes:
        return None
    return OddsQuote(statistics.median(q.home for q in quotes),
                     statistics.median(q.away for q in quotes), "médiane")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
class DataFetcher:
    def __init__(self, api_key: str = config.ODDS_API_KEY):
        self.http = CachedHttp(config.CACHE_DIR)
        self.espn = ESPNClient(self.http)
        self.odds = OddsClient(self.http, api_key)
        self.history = OddsHistory(config.ODDS_HISTORY_FILE)

    def load_slate(self, target: Optional[date] = None) -> Slate:
        """Charge la prochaine nuit NBA (ou la date `target`) : tous les matchs du calendrier,
        avec les cotes quand elles existent."""
        now = datetime.now(timezone.utc)
        if target:
            day, games = target, self.espn.scoreboard(target)
        else:
            day, games = self.espn.next_slate(now.astimezone(US_EASTERN).date())
        log.info("Nuit NBA du %s : %d match(s) au calendrier", day, len(games))

        odds_by_teams: dict[tuple[str, str], list[OddsEvent]] = {}
        if any(g["state"] == "pre" for g in games):
            for ev in self.odds.fetch():
                odds_by_teams.setdefault((team_key(ev.home_team), team_key(ev.away_team)), []).append(ev)

        teams = self.espn.teams()
        standings = self.espn.standings()
        injuries = self.espn.injuries()
        ranks = self._ranks(standings)

        contexts: dict[str, TeamContext] = {}

        def context(key: str) -> TeamContext:
            if key not in contexts:
                info = teams[key]
                w, l = standings.get(key, (0, 0))
                contexts[key] = TeamContext(
                    key=key, name=info["name"], abbr=info["abbr"], espn_id=info["id"],
                    color=info.get("color", ""),
                    schedule=self.espn.team_schedule(info["id"]),
                    injuries=injuries.get(key, []),
                    wins=w, losses=l, league_rank=ranks.get(key),
                )
            return contexts[key]

        matchups: list[Matchup] = []
        for g in games:
            hk, ak = team_key(g["home"]), team_key(g["away"])
            if hk not in teams or ak not in teams:
                log.warning("Équipe non reconnue côté ESPN : %s / %s", g["away"], g["home"])
                continue
            try:
                home_ctx, away_ctx = context(hk), context(ak)
            except requests.RequestException as exc:
                log.warning("Calendrier ESPN indisponible pour %s @ %s : %s", g["away"], g["home"], exc)
                continue

            # Cotes du même match (mêmes équipes, coup d'envoi à moins de 12 h près)
            ev = next((e for e in odds_by_teams.get((hk, ak), [])
                       if abs((e.commence_time - g["date"]).total_seconds()) < 12 * 3600), None)
            unibet = reference = opening = observed_since = None
            n_obs = 0
            if ev and g["state"] == "pre":
                unibet = ev.quotes.get(config.REFERENCE_BOOKMAKER)
                reference = ev.quotes.get(config.SHARP_BOOKMAKER) or _median_quote(
                    [q for k, q in ev.quotes.items() if k != config.REFERENCE_BOOKMAKER])
                if unibet:
                    opening, observed_since, n_obs = self.history.record(ev.event_id, unibet, now)

            matchups.append(Matchup(
                ev.event_id if ev else f"espn-{g['id']}", g["date"], home_ctx, away_ctx,
                unibet, reference, opening, observed_since, n_obs,
                state=g["state"], status_detail=g["detail"],
                home_score=g["home_score"], away_score=g["away_score"],
            ))

        self.history.purge(now)
        self.history.save()
        contenders, source = self._contenders(standings, ranks)
        return Slate(matchups, contenders, source, now, slate_date=day)

    @staticmethod
    def _ranks(standings: dict[str, tuple[int, int]]) -> dict[str, int]:
        def pct(wl: tuple[int, int]) -> float:
            return wl[0] / (wl[0] + wl[1]) if sum(wl) else 0.0
        ordered = sorted(standings, key=lambda k: (pct(standings[k]), standings[k][0]), reverse=True)
        return {k: i + 1 for i, k in enumerate(ordered)}

    @staticmethod
    def _contenders(standings: dict[str, tuple[int, int]], ranks: dict[str, int]) -> tuple[set[str], str]:
        played = [w + l for w, l in standings.values()]
        if played and statistics.median(played) >= config.CONTENDERS_MIN_GAMES:
            top = {k for k, r in ranks.items() if r <= config.CONTENDERS_TOP_N}
            return top, f"top {config.CONTENDERS_TOP_N} du classement actuel"
        return set(config.CONTENDERS_FALLBACK), "liste manuelle (début de saison, classement pas encore fiable)"

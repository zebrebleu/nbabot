"""
Tennis : récupération des données — aucune connexion au site d'un bookmaker.

  * The Odds API : liste des tournois en cours (gratuit), puis cotes Moneyline
    de chaque tournoi (1 crédit par tournoi).
  * API publique ESPN : tous les matchs de la saison ATP / WTA (forme, surface,
    fatigue, abandons, confrontations) et classements.

Les joueurs sont rapprochés entre les deux sources par leur nom.
Un fichier data/tennis_diag.json résume ce qui a été lu, pour vérifier le bon
fonctionnement après un passage sur GitHub.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

import config
import tennis_config as tc
from data_fetcher import CachedHttp, OddsHistory, parse_dt
from models import OddsQuote

log = logging.getLogger(__name__)

ODDS_BASE = "https://api.the-odds-api.com/v4/sports"
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/tennis"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/tennis/leagues"
RANKING_IDS = {"atp": 1, "wta": 2}
HISTORY_FILE = config.DATA_DIR / "tennis_odds_history.json"
DIAG_FILE = config.DATA_DIR / "tennis_diag.json"


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
@dataclass
class PlayerMatch:
    date: datetime
    tournament: str
    surface: str
    round: str
    opponent: str               # clé normalisée de l'adversaire
    opponent_name: str
    won: bool
    sets: int
    games: int
    best_of: int
    retired: bool = False       # ce joueur a abandonné ou déclaré forfait
    opp_retired: bool = False


@dataclass
class Player:
    key: str
    name: str
    tour: str
    espn_id: str = ""
    rank: Optional[int] = None
    matches: list[PlayerMatch] = field(default_factory=list)   # triés par date
    ids: set = field(default_factory=set)                      # tous les identifiants ESPN connus

    def before(self, t: datetime, margin_hours: float = 1.0) -> list[PlayerMatch]:
        limit = t - timedelta(hours=margin_hours)
        return [m for m in self.matches if m.date < limit]


@dataclass
class TennisMatch:
    """Match à venir. Champs nommés comme models.Matchup pour réutiliser l'analyse commune.
    home = joueur 1 de The Odds API, away = joueur 2 (pas de notion de domicile au tennis)."""
    event_id: str
    commence_time: datetime
    home: Player
    away: Player
    unibet: Optional[OddsQuote]
    reference: Optional[OddsQuote]
    tournament: str
    tour: str
    surface: str
    best_of: int
    opening: Optional[OddsQuote] = None
    observed_since: Optional[datetime] = None
    n_observations: int = 0
    state: str = "pre"
    status_detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.home.name} – {self.away.name}"


@dataclass
class TennisSlate:
    matches: list[TennisMatch]
    generated_at: datetime
    tournaments: list[str]
    next_tournament: Optional[str] = None
    source_label: str = "The Odds API + ESPN"
    diag: dict = field(default_factory=dict)
    players: dict = field(default_factory=dict)          # historique complet (pour lire les résultats)
    last_bet: Optional[dict] = None                      # résultat du dernier pari proposé


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("-", " ")
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(s.split())


def surface_of(tournament: str) -> str:
    t = norm_name(tournament)
    for surface, words in tc.SURFACE_KEYWORDS.items():
        if any(norm_name(w) in t for w in words):
            return surface
    return "dur"


def is_slam(tournament: str) -> bool:
    t = norm_name(tournament)
    return any(norm_name(w) in t for w in tc.GRAND_SLAM_KEYWORDS)


def _num(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _athlete_id(athlete: dict) -> str:
    if athlete.get("id"):
        return str(athlete["id"])
    m = re.search(r"athletes/(\d+)", json.dumps(athlete))
    return m.group(1) if m else ""


def _athlete_ids(athlete: dict) -> set[str]:
    """Tous les identifiants ESPN repérables dans un objet joueur (id, uid, liens)."""
    raw = json.dumps(athlete)
    ids = set(re.findall(r"athletes/(\d+)", raw)) | set(re.findall(r"/id/(\d+)", raw)) \
        | set(re.findall(r"a:(\d+)", raw))
    for k in ("id", "guid"):
        if athlete.get(k):
            ids.add(str(athlete[k]))
    return ids


# ---------------------------------------------------------------------------
# ESPN : historique de la saison et classements
# ---------------------------------------------------------------------------
def parse_season(data: dict, tour: str, players: dict[str, Player], seen: Optional[set] = None) -> int:
    """Ajoute à `players` tous les matchs de simple terminés. Renvoie le nombre de matchs lus.
    `seen` évite de compter deux fois un match qu'ESPN répète."""
    seen = seen if seen is not None else set()
    count = 0
    for ev in data.get("events", []):
        tname = ev.get("name") or ev.get("shortName") or ""
        surface, slam = surface_of(tname), is_slam(tname)
        for grp in ev.get("groupings", []):
            g = grp.get("grouping", {})
            gname = f"{g.get('displayName', '')} {g.get('slug', '')}".lower()
            if "single" not in gname:
                continue
            # Les tournois mixtes (Grands Chelems, 1000) mélangent les tableaux dans les deux flux
            g_tour = "wta" if ("women" in gname or "ladies" in gname) else ("atp" if "men" in gname else tour)
            for comp in grp.get("competitions", []):
                cs = comp.get("competitors", [])
                if len(cs) != 2 or any(c.get("type", "athlete") != "athlete" for c in cs):
                    continue
                st = comp.get("status", {}).get("type", {})
                if not (st.get("completed") or st.get("state") == "post"):
                    continue
                winners = [bool(c.get("winner")) for c in cs]
                if winners.count(True) != 1:
                    continue
                text = " ".join([st.get("name", ""), st.get("detail", ""), st.get("shortDetail", "")]
                                + [n.get("text", "") for n in comp.get("notes", [])]).lower()
                abandon = any(w in text for w in ("retired", " ret", "ret.", "walkover", "w/o", "default"))
                when = comp.get("date") or comp.get("startDate") or ev.get("date")
                if not when:
                    continue
                date = parse_dt(when)
                sets = max(len(c.get("linescores", [])) for c in cs)
                games = sum(_num(s.get("value")) for c in cs for s in c.get("linescores", []))
                best_of = 5 if (slam and g_tour == "atp") else 3
                rnd = comp.get("round", {}).get("displayName", "") if isinstance(comp.get("round"), dict) else ""
                athletes = [c.get("athlete", {}) for c in cs]
                names = [a.get("displayName") or a.get("fullName") or "" for a in athletes]
                if not all(names):
                    continue
                dedup = (g_tour, date.date().isoformat(), *sorted(norm_name(n) for n in names))
                if (comp.get("id") and ("id", str(comp["id"])) in seen) or dedup in seen:
                    continue
                seen.add(dedup)
                if comp.get("id"):
                    seen.add(("id", str(comp["id"])))
                for i in (0, 1):
                    me, opp = i, 1 - i
                    key = norm_name(names[me])
                    p = players.setdefault(key, Player(key, names[me], g_tour))
                    p.espn_id = p.espn_id or _athlete_id(athletes[me])
                    p.ids |= _athlete_ids(athletes[me])
                    p.matches.append(PlayerMatch(
                        date=date, tournament=tname, surface=surface, round=rnd,
                        opponent=norm_name(names[opp]), opponent_name=names[opp],
                        won=winners[me], sets=sets, games=games, best_of=best_of,
                        retired=abandon and not winners[me], opp_retired=abandon and winners[me],
                    ))
                count += 1
    return count


def next_event(data: dict, now: datetime) -> Optional[tuple[datetime, str]]:
    best = None
    for ev in data.get("events", []):
        if not ev.get("date"):
            continue
        d = parse_dt(ev["date"])
        if d > now and (best is None or d < best[0]):
            best = (d, ev.get("name") or ev.get("shortName") or "")
    return best


class ESPNTennis:
    def __init__(self, http: CachedHttp):
        self.http = http

    def season(self, tour: str, year: int) -> dict:
        """Tous les matchs d'une année. Une année terminée ne change plus : cache longue durée."""
        past = year < datetime.now(timezone.utc).year
        return self.http.get_json(f"{ESPN_SITE}/{tour}/scoreboard", params={"dates": str(year)},
                                  ttl_minutes=60 * 24 * 60 if past else tc.ESPN_CACHE_HOURS * 60,
                                  long_term=past)

    def rankings(self, tour: str, now: datetime) -> list[dict]:
        """[{rank, ids, ref, name}] — la liste du classement officiel (150 premiers environ)."""
        year, week = now.year, now.isocalendar()[1]
        for back in range(4):
            url = (f"{ESPN_CORE}/{tour}/seasons/{year}/types/2/weeks/{max(1, week - back)}"
                   f"/rankings/{RANKING_IDS[tour]}")
            try:
                data = self.http.get_json(url, ttl_minutes=12 * 60)
            except requests.RequestException:
                continue
            out = []
            for r in data.get("ranks", []):
                a = r.get("athlete") if isinstance(r.get("athlete"), dict) else {}
                if r.get("current"):
                    out.append({"rank": _num(r["current"]), "ids": _athlete_ids(a), "ref": a.get("$ref", ""),
                                "name": a.get("displayName") or a.get("fullName") or ""})
            if out:
                return out
        return []

    def athlete_name(self, ref: str) -> str:
        """Nom d'un joueur à partir de son lien ESPN (mis en cache 7 jours)."""
        try:
            data = self.http.get_json(ref.replace("http://", "https://"), ttl_minutes=7 * 24 * 60)
        except (requests.RequestException, ValueError):
            return ""
        return data.get("displayName") or data.get("fullName") or ""


def apply_rankings(ranks: list[dict], players: dict[str, "Player"], tour: str,
                   espn: Optional[ESPNTennis] = None) -> tuple[int, str]:
    """Rattache le classement aux joueurs : par identifiant, sinon par nom. Renvoie (nb, méthode)."""
    by_id = {}
    for p in players.values():          # identifiants ESPN uniques : pas de filtre par circuit
        for i in p.ids | ({p.espn_id} if p.espn_id else set()):
            by_id[i] = p
    n = 0
    for r in ranks:
        p = next((by_id[i] for i in r["ids"] if i in by_id), None)
        if p:
            p.rank, n = r["rank"], n + 1
    if n >= min(10, len(ranks)) or espn is None:
        return n, "identifiants"
    # Les identifiants ne concordent pas : on récupère le nom de chaque classé (une fois par semaine)
    n = 0
    for r in ranks:
        name = r["name"] or (espn.athlete_name(r["ref"]) if r["ref"] else "")
        p = find_player(name, {k: v for k, v in players.items() if v.tour == tour}) if name else None
        if p:
            p.rank, n = r["rank"], n + 1
    return n, "noms"


# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------
def active_tennis_sports(http: CachedHttp, api_key: str) -> list[dict]:
    """Tournois ATP/WTA en cours (cet appel ne consomme pas de crédit)."""
    sports = http.get_json(ODDS_BASE, params={"apiKey": api_key}, ttl_minutes=60, cache_key_params={})
    keep = [s for s in sports if s.get("active") and str(s.get("key", "")).startswith(("tennis_atp", "tennis_wta"))]
    keep.sort(key=lambda s: (not s["key"].startswith("tennis_atp"), s["key"]))
    return keep[:tc.MAX_TOURNAMENTS]


def tournament_odds(http: CachedHttp, api_key: str, sport_key: str) -> list[dict]:
    params = {"apiKey": api_key, "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso",
              "bookmakers": ",".join(config.ODDS_BOOKMAKERS)}
    return http.get_json(f"{ODDS_BASE}/{sport_key}/odds", params=params,
                         ttl_minutes=config.ODDS_CACHE_MINUTES,
                         cache_key_params={k: v for k, v in params.items() if k != "apiKey"})


def _quotes(ev: dict) -> dict[str, OddsQuote]:
    p1, p2 = ev.get("home_team"), ev.get("away_team")
    out = {}
    for bk in ev.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            prices = {o["name"]: float(o["price"]) for o in mk.get("outcomes", [])}
            if p1 in prices and p2 in prices:
                out[bk["key"]] = OddsQuote(prices[p1], prices[p2], bk["key"], bk.get("last_update", ""))
    return out


def find_player(name: str, players: dict[str, Player]) -> Optional[Player]:
    key = norm_name(name)
    if key in players:
        return players[key]
    toks = key.split()
    if not toks:
        return None
    last, first = toks[-1], toks[0][0]
    same_last = [p for k, p in players.items() if k.split() and k.split()[-1] == last]
    initial = [p for p in same_last if p.key[0] == first]
    if len(initial) == 1:
        return initial[0]
    if len(same_last) == 1:
        return same_last[0]
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
class TennisFetcher:
    def __init__(self, api_key: str = config.ODDS_API_KEY):
        self.api_key = api_key
        self.http = CachedHttp(config.CACHE_DIR)
        self.espn = ESPNTennis(self.http)
        self.history = OddsHistory(HISTORY_FILE)

    def load_slate(self) -> TennisSlate:
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=tc.LOOKAHEAD_HOURS)
        diag: dict = {"generated_at": now.isoformat(), "espn_matches": {}, "rankings": {}}

        sports = active_tennis_sports(self.http, self.api_key)
        diag["tournaments"] = [s["key"] for s in sports]

        players: dict[str, Player] = {}
        years = [now.year - i for i in range(config.HISTORY_SEASONS + 1)]     # saison en cours + 3 précédentes
        diag["years"] = years
        next_info = None
        seen: set = set()
        diag["ranking_match"] = {}
        diag["samples"] = {}
        for tour in tc.TOURS:
            n = 0
            for y in years:
                try:
                    data = self.espn.season(tour, y)
                except requests.RequestException as exc:
                    log.warning("Saison ESPN %s %s indisponible : %s", tour, y, exc)
                    continue
                n += parse_season(data, tour, players, seen)
                if y == now.year:
                    cand = next_event(data, now)
                    if cand and (next_info is None or cand[0] < next_info[0]):
                        next_info = cand
            diag["espn_matches"][tour] = n
            ranks = self.espn.rankings(tour, now)
            diag["rankings"][tour] = len(ranks)
            matched, how = apply_rankings(ranks, players, tour, self.espn)
            diag["ranking_match"][tour] = {"rattachés": matched, "méthode": how}
            some = [p for p in players.values() if p.tour == tour][:2]
            diag["samples"][tour] = {"joueurs": [{"nom": p.name, "ids": sorted(p.ids)[:5]} for p in some],
                                     "classement": [{"rang": r["rank"], "ids": sorted(r["ids"])[:5],
                                                     "ref": r["ref"][:120]} for r in ranks[:2]]}
        for p in players.values():
            p.matches.sort(key=lambda m: m.date)
        diag["players"] = len(players)
        diag["ranked_players"] = sum(1 for p in players.values() if p.rank)

        matches: list[TennisMatch] = []
        unmatched: list[str] = []
        diag["odds_events"] = 0
        for sport in sports:
            try:
                events = tournament_odds(self.http, self.api_key, sport["key"])
            except requests.RequestException as exc:
                log.warning("Cotes indisponibles pour %s : %s", sport["key"], exc)
                continue
            tname = sport.get("title") or sport["key"]
            tour = "wta" if sport["key"].startswith("tennis_wta") else "atp"
            for ev in events:
                diag["odds_events"] += 1
                start = parse_dt(ev["commence_time"])
                if not now < start <= horizon:
                    continue
                pl = []
                for nm in (ev["home_team"], ev["away_team"]):
                    p = find_player(nm, players)
                    if p is None:
                        unmatched.append(nm)
                        p = Player(norm_name(nm), nm, tour)      # joueur sans historique : filtres prudents
                    pl.append(p)
                q = _quotes(ev)
                unibet = q.get(tc.REFERENCE_BOOKMAKER)
                ref = q.get(config.SHARP_BOOKMAKER)
                if ref is None:
                    others = [x for k, x in q.items() if k != tc.REFERENCE_BOOKMAKER]
                    if others:
                        ref = OddsQuote(statistics.median(x.home for x in others),
                                        statistics.median(x.away for x in others), "médiane")
                m = TennisMatch(ev["id"], start, pl[0], pl[1], unibet, ref, tname, tour,
                                surface_of(tname), 5 if (is_slam(tname) and tour == "atp") else 3)
                if unibet:
                    m.opening, m.observed_since, m.n_observations = self.history.record(ev["id"], unibet, now)
                matches.append(m)
        self.history.purge(now)
        self.history.save()

        diag["upcoming_matches"] = len(matches)
        diag["unmatched_names"] = sorted(set(unmatched))[:50]
        try:
            DIAG_FILE.parent.mkdir(parents=True, exist_ok=True)
            DIAG_FILE.write_text(json.dumps(diag, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

        matches.sort(key=lambda m: m.commence_time)
        nxt = f"{next_info[1]} (à partir du {next_info[0]:%d/%m})" if next_info else None
        return TennisSlate(matches, now, [s.get("title") or s["key"] for s in sports], nxt, diag=diag,
                           players=players)

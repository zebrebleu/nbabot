"""Structures de données partagées entre les modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class TeamGame:
    """Un match du calendrier, vu du côté d'une équipe."""
    date: datetime              # coup d'envoi, UTC
    opponent: str               # clé de l'adversaire (ex. "celtics")
    is_home: bool
    completed: bool
    won: Optional[bool] = None


@dataclass
class Injury:
    player: str
    status: str                 # "Out", "Day-To-Day", "Questionable"...
    detail: str = ""


@dataclass
class TeamContext:
    key: str                    # surnom normalisé, ex. "celtics"
    name: str                   # "Boston Celtics"
    abbr: str = ""
    espn_id: str = ""
    schedule: list[TeamGame] = field(default_factory=list)   # trié par date
    injuries: list[Injury] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    league_rank: Optional[int] = None                         # 1 = meilleur bilan NBA

    @property
    def win_pct(self) -> float:
        n = self.wins + self.losses
        return self.wins / n if n else 0.0

    def games_before(self, t: datetime, margin_hours: float = 1.0) -> list[TeamGame]:
        limit = t - timedelta(hours=margin_hours)
        return [g for g in self.schedule if g.date < limit]

    def completed_before(self, t: datetime) -> list[TeamGame]:
        return [g for g in self.games_before(t) if g.completed and g.won is not None]

    def previous_game(self, t: datetime) -> Optional[TeamGame]:
        past = self.games_before(t)
        return past[-1] if past else None

    def next_game(self, t: datetime, margin_hours: float = 1.0) -> Optional[TeamGame]:
        limit = t + timedelta(hours=margin_hours)
        return next((g for g in self.schedule if g.date > limit), None)


@dataclass
class OddsQuote:
    home: float
    away: float
    bookmaker: str
    last_update: str = ""


@dataclass
class Matchup:
    event_id: str
    commence_time: datetime     # UTC
    home: TeamContext
    away: TeamContext
    unibet: Optional[OddsQuote]
    reference: Optional[OddsQuote]          # Pinnacle ou médiane des autres books
    opening: Optional[OddsQuote] = None     # 1re cote Unibet observée par le script
    observed_since: Optional[datetime] = None
    n_observations: int = 0

    @property
    def label(self) -> str:
        return f"{self.away.name} @ {self.home.name}"


@dataclass
class Slate:
    """Tout ce dont les filtres ont besoin pour une journée."""
    matchups: list[Matchup]
    contenders: set[str]
    contenders_source: str
    generated_at: datetime
    key_players: Optional[dict[str, list[str]]] = None   # surcharge (mode démo)
    source_label: str = "The Odds API + ESPN"


@dataclass
class FilterResult:
    name: str
    passed: bool
    reason: str
    warning: bool = False       # validé mais à vérifier manuellement


@dataclass
class Evaluation:
    matchup: Matchup
    pick: Optional[TeamContext]
    opponent: Optional[TeamContext]
    pick_is_home: bool
    odds: float
    results: list[FilterResult] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    score: float = 0.0

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def warnings(self) -> list[FilterResult]:
        return [r for r in self.results if r.passed and r.warning]

    @property
    def rejections(self) -> list[FilterResult]:
        return [r for r in self.results if not r.passed]

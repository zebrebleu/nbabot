"""
Lancement de l'analyse TENNIS (appelé par main.py --sport tennis).

Verrou : dès qu'un match du pari proposé a commencé, ce pari est conservé
(data/tennis_bet.json) jusqu'à la fin de ses matchs, pour ne pas changer de pronostic en cours de route.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config
import tennis_config as tc
from analyzer import TZ, _fmt_dt
from insights import leg_probability
from tennis_filters import evaluate_all
from tennis_insights import best_bet, build_insight

LOCK_FILE = config.DATA_DIR / "tennis_bet.json"
LOCK_HOURS = 20


def _load_lock(now: datetime) -> Optional[dict]:
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(lock["created"])
    except (OSError, ValueError, KeyError):
        return None
    if now - created > timedelta(hours=LOCK_HOURS):
        return None
    starts = [datetime.fromisoformat(l["commence"]) for l in lock["legs"]]
    return lock if any(s <= now for s in starts) else None


def _save_lock(bet, now: datetime) -> None:
    if bet is None:
        LOCK_FILE.unlink(missing_ok=True)
        return
    lock = {
        "created": now.isoformat(),
        "created_label": _fmt_dt(now),
        "kind": bet.kind, "total": round(bet.total, 2), "prob": round(bet.prob, 3),
        "legs": [{"event_id": e.matchup.event_id, "pick": e.pick.name, "opponent": e.opponent.name,
                  "odds": e.odds, "tournament": e.matchup.tournament,
                  "commence": e.matchup.commence_time.isoformat(),
                  "time": f"{e.matchup.commence_time.astimezone(TZ):%d/%m %H:%M}"} for e in bet.legs],
    }
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(lock, indent=1, ensure_ascii=False), encoding="utf-8")


def _print(slate, evaluations, bet, locked) -> None:
    print("═" * 72)
    print(f" ASSISTANT PARIS TENNIS — {_fmt_dt(slate.generated_at)} (Paris)")
    print(f" Tournois : {', '.join(slate.tournaments) or 'aucun'}")
    print("═" * 72)
    if locked:
        print(f" PARI EN COURS (verrouillé) : {locked['kind']} — cote {locked['total']:.2f}")
        for l in locked["legs"]:
            print(f"   • {l['pick']} gagne contre {l['opponent']} ({l['tournament']}, {l['time']}) — {l['odds']:.2f}")
    elif bet:
        print(f" {bet.kind.upper()} — COTE TOTALE {bet.total:.2f} · chances estimées {bet.prob:.0%}")
        for e in bet.legs:
            ins = build_insight(e)
            print(f"   • {e.pick.name} gagne contre {e.opponent.name} ({e.matchup.tournament}) — {e.odds:.2f}"
                  f" — confiance {ins.confidence}")
            print(f"     {ins.summary}")
            for s in ins.strengths:
                print(f"       + {s}")
            for r in ins.risks:
                print(f"       ! {r}")
    else:
        print(" Aucun pari tennis : aucun match ne passe tous les contrôles.")
    print("─" * 72)
    for e in evaluations:
        if e.passed:
            status = f"VALIDÉ  {e.pick.name} {e.odds:.2f} ({leg_probability(e):.0%})"
        else:
            r = e.rejections[0]
            status = f"ÉCARTÉ  {r.name} : {r.reason}"
        print(f" {e.matchup.commence_time.astimezone(TZ):%d/%m %H:%M}  {e.matchup.label}  →  {status}")
    print("═" * 72)


def run(demo: bool = False, html_dir: Optional[str] = None) -> int:
    if demo:
        from tennis_demo import build_demo_slate
        slate = build_demo_slate()
    else:
        if not config.ODDS_API_KEY:
            print("ODDS_API_KEY manquante.")
            return 1
        import requests
        from tennis_fetcher import TennisFetcher
        try:
            slate = TennisFetcher().load_slate()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            print(f"Tennis : erreur HTTP {code} ({'quota épuisé ?' if code == 429 else 'voir le message'}) : {exc}")
            return 2
        except requests.RequestException as exc:
            print(f"Tennis : erreur réseau : {exc}")
            return 2

    now = slate.generated_at
    evaluations = evaluate_all(slate.matches, now)
    locked = None if demo else _load_lock(now)
    bet = None
    if not locked:
        bet = best_bet([e for e in evaluations if e.passed])
        if not demo:
            _save_lock(bet, now)
    _print(slate, evaluations, bet, locked)

    if html_dir:
        from tennis_web import write_site
        page = write_site(slate, evaluations, bet, locked, Path(html_dir))
        print(f"Page tennis générée : {page}")
    return 0

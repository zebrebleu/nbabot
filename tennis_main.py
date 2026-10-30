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
LOCK_HOURS = 48                 # garde-fou : un verrou n'est jamais gardé plus longtemps
MATCH_HOURS = {3: 3.5, 5: 5.5}  # durée max d'un match (2 ou 3 sets gagnants) si le résultat n'est pas encore connu


def _read_lock(now: datetime) -> Optional[dict]:
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(lock["created"])
    except (OSError, ValueError, KeyError):
        return None
    return lock if now - created <= timedelta(hours=LOCK_HOURS) else None


def leg_result(leg: dict, players: dict) -> Optional[bool]:
    """Résultat d'un match du pari d'après l'historique ESPN : True gagné, False perdu, None inconnu."""
    from tennis_fetcher import find_player, norm_name
    p = find_player(leg["pick"], players) if players else None
    if p is None:
        return None
    start = datetime.fromisoformat(leg["commence"])
    opp = norm_name(leg["opponent"])
    for m in reversed(p.matches):
        if m.date >= start - timedelta(hours=8) and (m.opponent == opp or m.opponent.split()[-1:] == opp.split()[-1:]):
            return m.won
    return None


def lock_state(lock: Optional[dict], players: dict, now: datetime) -> tuple[str, list]:
    """('none' | 'pending' | 'live' | 'finished', résultats des matchs)."""
    if not lock:
        return "none", []
    results = [leg_result(l, players) for l in lock["legs"]]
    starts = [datetime.fromisoformat(l["commence"]) for l in lock["legs"]]
    if not any(s <= now for s in starts):
        return "pending", results
    done = [r is not None or now > s + timedelta(hours=MATCH_HOURS.get(l.get("best_of", 3), 3.5))
            for r, s, l in zip(results, starts, lock["legs"])]
    return ("finished" if all(done) else "live"), results


def _save_last(lock: dict, results: list, html_dir: Optional[str]) -> Optional[dict]:
    """Garde le résultat du dernier pari proposé (affiché sur la page tennis)."""
    status = ("gagné" if all(r is True for r in results) else
              "perdu" if any(r is False for r in results) else "résultat non disponible")
    last = {"created_label": lock.get("created_label", ""), "kind": lock["kind"], "total": lock["total"],
            "legs": [dict(l, result=r) for l, r in zip(lock["legs"], results)], "status": status}
    if html_dir:
        path = Path(html_dir) / "data" / "tennis_last_bet.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(last, indent=1, ensure_ascii=False), encoding="utf-8")
    return last


def _read_last(html_dir: Optional[str]) -> Optional[dict]:
    if not html_dir:
        return None
    try:
        return json.loads((Path(html_dir) / "data" / "tennis_last_bet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_lock(bet, now: datetime) -> None:
    if bet is None:
        LOCK_FILE.unlink(missing_ok=True)
        return
    lock = {
        "created": now.isoformat(),
        "created_label": _fmt_dt(now),
        "kind": bet.kind, "total": round(bet.total, 2), "prob": round(bet.prob, 3),
        "legs": [{"event_id": e.matchup.event_id, "pick": e.pick.name, "opponent": e.opponent.name,
                  "odds": e.odds, "tournament": e.matchup.tournament, "best_of": e.matchup.best_of,
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
    locked, bet = None, None
    slate.last_bet = _read_last(html_dir)
    if not demo:
        lock = _read_lock(now)
        state, results = lock_state(lock, slate.players, now)
        if state == "live":                       # un match du pari est en cours : on n'y touche pas
            locked = lock
        elif state == "finished":                 # matchs terminés : on garde le résultat, on libère
            slate.last_bet = _save_last(lock, results, html_dir)
            print(f"Dernier pari tennis : {slate.last_bet['status']}")
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

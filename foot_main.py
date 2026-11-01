"""
Lancement de l'analyse FOOT (appelé par main.py --sport foot).

Comme pour le tennis : dès qu'un match des paris proposés a commencé, les paris sont conservés
(data/foot_bet.json) jusqu'à la fin de leurs matchs ; ensuite leur résultat est affiché.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config
from analyzer import TZ, _fmt_dt
from foot_filters import evaluate_all
from foot_insights import best_bet, build_insight
from insights import leg_probability
from tennis_main import _all_legs

LOCK_FILE = config.DATA_DIR / "foot_bet.json"
LAST_FILE = "foot_last_bet.json"
LOCK_HOURS = 60
MATCH_HOURS = 2.5


def _read_lock(now: datetime) -> Optional[dict]:
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(lock["created"])
    except (OSError, ValueError, KeyError):
        return None
    return lock if now - created <= timedelta(hours=LOCK_HOURS) else None


def leg_result(leg: dict, results: list) -> Optional[bool]:
    """True si le favori joué a gagné, False sinon (nul ou défaite), None si pas encore connu."""
    start = datetime.fromisoformat(leg["commence"])
    for r in results:
        ids = {r["home_id"], r["away_id"]}
        if {leg.get("pick_id"), leg.get("opp_id")} != ids or abs((r["date"] - start).total_seconds()) > 6 * 3600:
            continue
        if not (r["completed"] or r["state"] == "post") or r["home_score"] is None:
            return None
        mine, theirs = ((r["home_score"], r["away_score"]) if r["home_id"] == leg["pick_id"]
                        else (r["away_score"], r["home_score"]))
        return mine > theirs
    return None


def lock_state(lock: Optional[dict], results: list, now: datetime) -> tuple[str, dict]:
    if not lock or not lock.get("bets"):
        return "none", {}
    legs = _all_legs(lock)
    res = {(l["pick"], l["commence"]): leg_result(l, results) for l in legs}
    starts = [datetime.fromisoformat(l["commence"]) for l in legs]
    if not any(s <= now for s in starts):
        return "pending", res
    done = [res[(l["pick"], l["commence"])] is not None or now > s + timedelta(hours=MATCH_HOURS)
            for l, s in zip(legs, starts)]
    return ("finished" if all(done) else "live"), res


def _save_lock(props, now: datetime) -> None:
    from staking import bet_stake
    if not props:
        LOCK_FILE.unlink(missing_ok=True)
        return
    bets = []
    for option, b in (("Option 1 · Pari simple", props.single), ("Option 2 · Combiné", props.combo)):
        if not b:
            continue
        stake, _ = bet_stake([build_insight(e).confidence for e in b.legs])
        bets.append({"option": option, "kind": b.kind, "total": round(b.total, 2), "stake": stake,
                     "legs": [{"event_id": e.matchup.event_id, "pick": e.pick.name, "opponent": e.opponent.name,
                               "pick_id": e.pick.id, "opp_id": e.opponent.id, "odds": e.odds,
                               "tournament": e.matchup.league_name, "commence": e.matchup.commence_time.isoformat(),
                               "time": f"{e.matchup.commence_time.astimezone(TZ):%d/%m %H:%M}"} for e in b.legs]})
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({"created": now.isoformat(), "created_label": _fmt_dt(now), "bets": bets},
                                    indent=1, ensure_ascii=False), encoding="utf-8")


def _save_last(lock: dict, res: dict, html_dir: Optional[str]) -> dict:
    bets = []
    for b in lock.get("bets", []):
        rs = [res.get((l["pick"], l["commence"])) for l in b["legs"]]
        status = ("gagné" if all(r is True for r in rs) else
                  "perdu" if any(r is False for r in rs) else "résultat non disponible")
        bets.append({"option": b.get("option", ""), "kind": b["kind"], "total": b["total"],
                     "legs": [dict(l, result=r) for l, r in zip(b["legs"], rs)], "status": status})
    last = {"created_label": lock.get("created_label", ""), "bets": bets}
    if html_dir:
        p = Path(html_dir) / "data" / LAST_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(last, indent=1, ensure_ascii=False), encoding="utf-8")
    return last


def _read_last(html_dir: Optional[str]) -> Optional[dict]:
    try:
        return json.loads((Path(html_dir) / "data" / LAST_FILE).read_text(encoding="utf-8")) if html_dir else None
    except (OSError, ValueError):
        return None


def _print(slate, evaluations, props, locked) -> None:
    print("═" * 72)
    print(f" ASSISTANT PARIS FOOT — {_fmt_dt(slate.generated_at)} (Paris)")
    print(f" Championnats avec des matchs : {', '.join(slate.leagues) or 'aucun'}")
    print("═" * 72)
    if locked:
        for b in locked["bets"]:
            print(f" EN COURS · {b.get('option', '')} : {b['kind']} — cote {b['total']:.2f}")
    elif props:
        from staking import bet_stake
        for n, b in enumerate(props.bets, 1):
            stake, conf = bet_stake([build_insight(e).confidence for e in b.legs])
            print(f" OPTION {n} · {b.kind.upper()} — COTE {b.total:.2f} · chances {b.prob:.0%} · mise {stake} € ({conf.lower()})")
            for e in b.legs:
                print(f"   • {e.pick.name} gagne contre {e.opponent.name} ({e.matchup.league_name}) — {e.odds:.2f}")
        if not props.combo:
            print(" Pas de combiné possible sous la cote maximale.")
    else:
        print(" Aucun pari foot : aucun match ne passe tous les contrôles.")
    print("─" * 72)
    for e in evaluations:
        st = (f"VALIDÉ  {e.pick.name} {e.odds:.2f} ({leg_probability(e):.0%})" if e.passed
              else f"ÉCARTÉ  {e.rejections[0].name} : {e.rejections[0].reason}")
        print(f" {e.matchup.commence_time.astimezone(TZ):%d/%m %H:%M}  {e.matchup.label}  →  {st}")
    print("═" * 72)


def run(demo: bool = False, html_dir: Optional[str] = None) -> int:
    if demo:
        from foot_demo import build_demo_slate
        slate = build_demo_slate()
    else:
        if not config.ODDS_API_KEY:
            print("ODDS_API_KEY manquante.")
            return 1
        import requests
        from foot_fetcher import FootFetcher
        try:
            slate = FootFetcher().load_slate()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            print(f"Foot : erreur HTTP {code} ({'quota épuisé ?' if code == 429 else 'voir le message'}) : {exc}")
            return 2
        except requests.RequestException as exc:
            print(f"Foot : erreur réseau : {exc}")
            return 2

    now = slate.generated_at
    evaluations = evaluate_all(slate.matches, now)
    locked, props = None, None
    slate.last_bet = _read_last(html_dir)
    if not demo:
        lock = _read_lock(now)
        state, res = lock_state(lock, slate.results, now)
        if state == "live":
            locked = lock
        elif state == "finished":
            slate.last_bet = _save_last(lock, res, html_dir)
    if not locked:
        props = best_bet([e for e in evaluations if e.passed])
        if not demo:
            _save_lock(props, now)
    _print(slate, evaluations, props, locked)

    if html_dir:
        from foot_web import write_site
        print(f"Page foot générée : {write_site(slate, evaluations, props, locked, Path(html_dir))}")
    return 0

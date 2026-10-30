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
    if "bets" not in lock and "legs" in lock:          # ancien format : un seul pari
        lock["bets"] = [{"option": "Pari", "kind": lock.get("kind", "Pari"), "total": lock.get("total", 0),
                         "legs": lock["legs"]}]
    return lock if now - created <= timedelta(hours=LOCK_HOURS) else None


def _all_legs(lock: dict) -> list[dict]:
    seen, out = set(), []
    for b in lock.get("bets", []):
        for l in b["legs"]:
            k = (l["pick"], l["commence"])
            if k not in seen:
                seen.add(k)
                out.append(l)
    return out


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


def lock_state(lock: Optional[dict], players: dict, now: datetime) -> tuple[str, dict]:
    """('none' | 'pending' | 'live' | 'finished', {(joueur, début): résultat}) sur tous les matchs des paris."""
    if not lock or not lock.get("bets"):
        return "none", {}
    legs = _all_legs(lock)
    results = {(l["pick"], l["commence"]): leg_result(l, players) for l in legs}
    starts = [datetime.fromisoformat(l["commence"]) for l in legs]
    if not any(s <= now for s in starts):
        return "pending", results
    done = [results[(l["pick"], l["commence"])] is not None
            or now > s + timedelta(hours=MATCH_HOURS.get(l.get("best_of", 3), 3.5)) for l, s in zip(legs, starts)]
    return ("finished" if all(done) else "live"), results


def _save_last(lock: dict, results: dict, html_dir: Optional[str]) -> Optional[dict]:
    """Garde le résultat des derniers paris proposés (affichés sur la page tennis)."""
    bets = []
    for b in lock.get("bets", []):
        rs = [results.get((l["pick"], l["commence"])) for l in b["legs"]]
        status = ("gagné" if all(r is True for r in rs) else
                  "perdu" if any(r is False for r in rs) else "résultat non disponible")
        bets.append({"option": b.get("option", ""), "kind": b["kind"], "total": b["total"],
                     "legs": [dict(l, result=r) for l, r in zip(b["legs"], rs)], "status": status})
    last = {"created_label": lock.get("created_label", ""), "bets": bets,
            "status": " / ".join(f"{b['kind'].lower()} {b['status']}" for b in bets)}
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
        bets.append({"option": option, "kind": b.kind, "total": round(b.total, 2), "prob": round(b.prob, 3),
                     "stake": stake,
                     "legs": [{"event_id": e.matchup.event_id, "pick": e.pick.name, "opponent": e.opponent.name,
                               "odds": e.odds, "tournament": e.matchup.tournament, "best_of": e.matchup.best_of,
                               "commence": e.matchup.commence_time.isoformat(),
                               "time": f"{e.matchup.commence_time.astimezone(TZ):%d/%m %H:%M}"} for e in b.legs]})
    lock = {"created": now.isoformat(), "created_label": _fmt_dt(now), "bets": bets}
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(lock, indent=1, ensure_ascii=False), encoding="utf-8")


def _print(slate, evaluations, bet, locked) -> None:
    print("═" * 72)
    print(f" ASSISTANT PARIS TENNIS — {_fmt_dt(slate.generated_at)} (Paris)")
    print(f" Tournois : {', '.join(slate.tournaments) or 'aucun'}")
    print("═" * 72)
    if locked:
        for b in locked["bets"]:
            print(f" EN COURS (verrouillé) · {b.get('option', '')} : {b['kind']} — cote {b['total']:.2f}")
            for l in b["legs"]:
                print(f"   • {l['pick']} gagne contre {l['opponent']} ({l['tournament']}, {l['time']}) — {l['odds']:.2f}")
    elif bet:
        from staking import bet_stake
        for n, b in enumerate(bet.bets, 1):
            stake, conf = bet_stake([build_insight(e).confidence for e in b.legs])
            print(f" OPTION {n} · {b.kind.upper()} — COTE {b.total:.2f} · chances {b.prob:.0%} · mise {stake} € ({conf.lower()})")
            for e in b.legs:
                ins = build_insight(e)
                print(f"   • {e.pick.name} gagne contre {e.opponent.name} ({e.matchup.tournament}) — {e.odds:.2f}")
                for s in ins.strengths[:3]:
                    print(f"       + {s}")
        if not bet.combo:
            print(" Pas de combiné possible sous la cote maximale.")
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

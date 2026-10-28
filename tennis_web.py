"""
Page Tennis du site :  docs/tennis.html  +  docs/tennis/AAAA-MM-JJ.html (une par jour).
Même design que la page NBA (web_report.CSS).
"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import tennis_config as tc
from analyzer import JOURS, MOIS, TZ, _fmt_dt
from insights import leg_probability
from models import Evaluation
from tennis_insights import build_insight
from web_report import CSS, FONTS, _e, _meter, _money, _time, nav_tabs

TENNIS_CSS = """
.tourn{font:700 16px/1.2 var(--num);letter-spacing:.02em;margin:18px 0 2px;color:var(--accent)}
.tourn:first-child{margin-top:0}.tourn span{font:500 12px Inter,sans-serif;color:var(--muted);margin-left:6px}
.rk{color:var(--muted);font-size:12px;margin-left:4px}
"""


def _initials(name: str) -> str:
    parts = [p for p in name.replace("-", " ").split() if p]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else name[:2].upper()


def _badge(player, small: bool = False) -> str:
    h = int(hashlib.md5(player.key.encode()).hexdigest()[:2], 16) * 360 // 256
    return (f'<span class="badge{" sm" if small else ""}" style="background:hsl({h} 45% 36%);color:#fff">'
            f'{_e(_initials(player.name))}</span>')


def _rk(p) -> str:
    return f'<span class="rk">{p.rank}{"er" if p.rank == 1 else "e"}</span>' if p.rank else ""


def plain_reason(e: Evaluation) -> tuple[str, str]:
    r = e.rejections[0]
    if r.name == "Cote":
        if e.pick is None:
            return "Pas encore de cote Unibet", "Unibet n'a pas encore ouvert les paris sur ce match."
        if e.odds < tc.ODDS_MIN:
            return "Cote trop basse", f"Favori à {e.odds:.2f} : le gain serait trop faible pour le risque."
        return "Favori pas assez net", f"Cote de {e.odds:.2f}, au-dessus de la limite de {tc.ODDS_MAX:.2f}."
    return {
        "Mouvement de cote": ("La cote du favori monte", r.reason),
        "Fatigue": ("Fatigue", r.reason),
        "Abandon récent": ("Blessure possible", r.reason),
        "Forme récente": ("Forme insuffisante", r.reason),
        "Surface": ("Pas à l'aise sur la surface", r.reason),
        "Dynamique croisée": ("L'outsider est en forme", r.reason),
        "Classement": ("Classement incohérent", r.reason),
        "Confrontations": ("L'outsider mène les face-à-face", r.reason),
    }.get(r.name, (r.name, r.reason))


# ---------------------------------------------------------------------------
def _verdict(bet, locked: Optional[dict], passed, rejected, slate) -> str:
    if locked:
        legs = "".join(f"""<div class="leg"><div class="who"><b>{_e(l['pick'])} gagne</b>
<span>contre {_e(l['opponent'])} · {_e(l['tournament'])} · {_e(l['time'])}</span></div>
<span class="pill">{l['odds']:.2f}</span></div>""" for l in locked["legs"])
        return f"""<div class="card verdict go"><span class="chip info">PARI EN COURS</span>
<h3>{_e(locked['kind'])} · cote {locked['total']:.2f}</h3>
<p class="why">Ce pari a été proposé le {_e(locked['created_label'])} et un de ses matchs a commencé :
il est conservé tel quel. Un nouveau pari sera proposé au prochain passage après la fin des matchs.</p>{legs}</div>"""
    if not slate.tournaments:
        nxt = f" Prochain tournoi : <b>{_e(slate.next_tournament)}</b>." if slate.next_tournament else \
              " La saison reprend début janvier (Brisbane, Auckland, puis l'Open d'Australie)."
        return f"""<div class="card verdict none"><span class="chip off">PAS DE TOURNOI</span>
<h3>Aucun tournoi couvert en ce moment</h3>
<p class="why">Les cotes ne sont disponibles que pour les Grands Chelems, les tournois 1000 et 500
ATP/WTA.{nxt}</p></div>"""
    if not bet:
        counts = Counter(plain_reason(e)[0] for e in rejected)
        rows = "".join(f"<li><b>{n} match{'s' if n > 1 else ''}</b> : {_e(t.lower())}</li>"
                       for t, n in counts.most_common())
        return f"""<div class="card verdict none"><span class="chip off">PAS DE PARI</span>
<h3>Pas de pari tennis pour l'instant</h3>
<p class="why">Aucun match ne passe tous les contrôles (ou aucune combinaison ne tient sous
{tc.BET_MAX_ODDS:.2f}). Ne pas parier fait aussi partie de la stratégie.</p>
{f'<p class="lbl">Pourquoi les matchs ont été écartés</p><ul class="reasons risk">{rows}</ul>' if rows else ''}</div>"""
    legs = "".join(f"""<div class="leg">{_badge(e.pick)}<div class="who"><b>{_e(e.pick.name)} gagne</b>
<span>contre {_e(e.opponent.name)} · {_e(e.matchup.tournament)} · {_time(e.matchup.commence_time)}</span></div>
<span class="pill">{e.odds:.2f}</span></div>""" for e in bet.legs)
    return f"""<div class="card verdict go"><span class="chip go">● À JOUER SUR UNIBET</span>
<h3>{_e(bet.kind)}</h3>
<div class="stats"><div class="stat big"><span>Cote totale</span><b>{bet.total:.2f}</b></div>
<div class="stat"><span>Chances estimées</span><b>{bet.prob:.0%}</b></div>
<div class="stat"><span>Pour 10 € misés</span><b>{_money(10 * bet.total)}</b></div></div>{legs}</div>"""


def _analysis_card(e: Evaluation, opened: bool = True) -> str:
    ins = build_insight(e)
    m = e.matchup
    plus = "".join(f"<li>{_e(s)}</li>" for s in ins.strengths) or "<li>Tous les contrôles sont validés.</li>"
    risk = "".join(f"<li>{_e(r)}</li>" for r in ins.risks)
    grid = "".join(f"<div><h4>{_e(t)}</h4><ul>{''.join(f'<li>{_e(x)}</li>' for x in rows)}</ul></div>"
                   for t, rows in ins.sections)
    ctrl = "".join(f"<li><b>{_e(r.name)}</b> — {_e(r.reason)}</li>" for r in e.results)
    body = f"""<p class="why">{_e(ins.summary)}</p>
<p class="lbl">Ce qui joue pour lui</p><ul class="reasons plus">{plus}</ul>
{f'<p class="lbl">À surveiller</p><ul class="reasons risk">{risk}</ul>' if risk else ''}
<details><summary>Tous les chiffres du match</summary><div class="grid">{grid}</div></details>
<details><summary>Contrôles de sécurité ({len(e.results)}/{len(e.results)} validés)</summary>
<ul class="reasons ctrl">{ctrl}</ul></details>"""
    if not opened:
        body = f"<details><summary>Voir l'analyse</summary>{body}</details>"
    return f"""<div class="card"><div class="head">{_badge(e.pick)}<div class="who">
<h3>{_e(e.pick.name)} gagne · {e.odds:.2f}</h3>
<p>contre {_e(e.opponent.name)} · {_e(m.tournament)} ({_e(m.surface)}) · {_time(m.commence_time)}</p>
<p>Confiance : <b>{_e(ins.confidence)}</b>{_meter(ins.confidence)} · chances estimées {ins.win_prob:.0%}</p>
</div></div>{body}</div>"""


def _row(e: Evaluation, legs) -> str:
    m = e.matchup
    fav1 = m.unibet.home <= m.unibet.away if m.unibet else None

    def line(p, first: bool) -> str:
        odds = (m.unibet.home if first else m.unibet.away) if m.unibet else None
        fav = " fav" if fav1 is not None and fav1 == first else ""
        return (f'<div class="team{fav}">{_badge(p, small=True)}<span class="nm">{_e(p.name)}{_rk(p)}</span>'
                f'<span class="od">{f"{odds:.2f}" if odds else "—"}</span></div>')

    if e in legs:
        chip, why = '<span class="chip go">À JOUER</span>', f"<b>{_e(e.pick.name)} gagne</b> — voir l'analyse plus haut."
    elif e.passed:
        chip = '<span class="chip info">VALIDÉ</span>'
        why = (f"<b>{_e(e.pick.name)} gagne ({e.odds:.2f})</b> passe tous les contrôles, mais n'est pas "
               f"dans le meilleur pari ({leg_probability(e):.0%} de chances estimées).")
    else:
        title, detail = plain_reason(e)
        cls, label = ("off", "EN ATTENTE") if e.pick is None else ("no", "ÉCARTÉ")
        chip, why = f'<span class="chip {cls}">{label}</span>', f"<b>{_e(title)}</b> — {_e(detail)}"
    return f"""<div class="game"><div class="time">{_time(m.commence_time)}<small>Paris</small></div>
<div class="teams">{line(m.home, True)}{line(m.away, False)}</div>
<div class="status">{chip}</div><div class="reason">{why}</div></div>"""


LEGEND = """<details><summary>Comment lire cette page</summary>
<ul class="legend">
<li><span class="chip go">À JOUER</span><span>Le pari tennis proposé : 1 ou 2 matchs, cote totale de {mx} au maximum.</span></li>
<li><span class="chip info">VALIDÉ</span><span>Passe tous les contrôles mais n'a pas été retenu dans le pari.</span></li>
<li><span class="chip no">ÉCARTÉ</span><span>Au moins un contrôle a échoué : la raison est écrite en dessous.</span></li>
<li><span class="chip off">EN ATTENTE</span><span>Unibet n'a pas encore publié de cote.</span></li></ul>
<p class="lbl">Les contrôles appliqués au favori</p>
<ul class="reasons ctrl">
<li><b>Cote</b> — entre {lo} et {hi}, et pas de hausse suspecte.</li>
<li><b>Fatigue</b> — pas de match long (3 sets, ou 5 sets en Grand Chelem) dans les {fw} h précédentes.</li>
<li><b>Abandon récent</b> — pas d'abandon ni de forfait depuis {rd} jours (signe de blessure).</li>
<li><b>Forme</b> — au moins {fr:.0%} de victoires sur les 10 derniers matchs.</li>
<li><b>Surface</b> — au moins {sr:.0%} de victoires sur la surface du tournoi.</li>
<li><b>Dynamique</b> — l'outsider n'est pas en meilleure forme que le favori.</li>
<li><b>Classement</b> — le favori n'est pas nettement moins bien classé que l'outsider.</li>
<li><b>Confrontations</b> — l'outsider ne mène pas les face-à-face.</li>
</ul><p class="sub">Peu de matchs connus pour un joueur = alerte et confiance « Prudente ».</p></details>"""


def _day_label(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def build_html(slate, evaluations, bet, locked, archive_days: list[str], root: str = "") -> str:
    passed = sorted([e for e in evaluations if e.passed], key=lambda e: e.score, reverse=True)
    rejected = [e for e in evaluations if not e.passed]
    legs = bet.legs if bet else []
    today = slate.generated_at.astimezone(TZ).date()

    analysis = ""
    if legs:
        analysis = ("<h2>Pourquoi ce choix</h2><p class='h2sub'>L'analyse détaillée de chaque match du pari.</p>"
                    + "".join(_analysis_card(e) for e in legs))
    others = [e for e in passed if e not in legs]
    if others:
        analysis += ("<h2>Validés mais non retenus</h2><p class='h2sub'>Alternatives si une cote change.</p>"
                     + "".join(_analysis_card(e, opened=False) for e in others))

    by_t: dict[str, list[Evaluation]] = {}
    for e in sorted(evaluations, key=lambda e: e.matchup.commence_time):
        by_t.setdefault(e.matchup.tournament, []).append(e)
    games = "".join(
        f'<div class="tourn">{_e(t)}<span>{_e(es[0].matchup.surface)} · '
        f'{"5 sets" if es[0].matchup.best_of == 5 else "2 sets gagnants"}</span></div>'
        + "".join(_row(e, legs) for e in es) for t, es in by_t.items()
    ) or "<p class='sub'>Aucun match avec cote dans les prochaines heures.</p>"
    n_pending = sum(1 for e in evaluations if e.pick is None)

    archives = "".join(
        f'<a class="{"cur" if d == today.isoformat() else ""}" href="{root}tennis/{_e(d)}.html">'
        f'{_e(_day_label(date.fromisoformat(d)).capitalize())}</a>' for d in archive_days[:14])
    tourn = ", ".join(slate.tournaments) or "aucun"
    legend = LEGEND.format(mx=f"{tc.BET_MAX_ODDS:.2f}", lo=f"{tc.ODDS_MIN:.2f}", hi=f"{tc.ODDS_MAX:.2f}",
                           fw=tc.FATIGUE_WINDOW_HOURS, rd=tc.RETIREMENT_DAYS,
                           fr=tc.FORM_MIN_RATE, sr=tc.SURFACE_MIN_RATE)
    from tracker_web import TRACKER_CSS, picker_html, ticket_html     # « Ajouter à mes paris »
    picker = picker_html("tennis", evaluations, legs) if root == "" else ""
    ticket = ticket_html(root) if root == "" else ""

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pronostic Tennis</title>{FONTS}<style>{CSS}{TENNIS_CSS}{TRACKER_CSS}</style></head><body><main>
{nav_tabs("tennis", root)}
<header class="top"><div class="kicker">Pronostic tennis · ATP + WTA</div>
<h1>Tennis — {_e(_day_label(today).capitalize())}</h1>
<p class="sub">Analyse du {_e(_fmt_dt(slate.generated_at))} (Paris) · matchs des {tc.LOOKAHEAD_HOURS} prochaines heures
· tournois : {_e(tourn)}</p>
<div class="counts"><div class="count"><b>{len(evaluations)}</b><span>matchs avec cote</span></div>
<div class="count go"><b>{len(passed)}</b><span>passent les contrôles</span></div>
<div class="count no"><b>{len(rejected) - n_pending}</b><span>écartés{f' · {n_pending} en attente' if n_pending else ''}</span></div></div>
</header>
<h2>Le pari tennis</h2>{_verdict(bet, locked, passed, [e for e in rejected if e.pick is not None], slate)}
{analysis}
<h2>Programme</h2><p class="h2sub">Cotes Unibet de chaque joueur · le favori est en gras · classement en gris.</p>
<div class="card">{games}{legend}</div>
<h2>Avant de valider sur Unibet</h2><div class="card"><ul class="check">
<li>La cote totale affichée sur Unibet ne dépasse pas {tc.BET_MAX_ODDS:.2f}</li>
<li>Pari « Vainqueur du match » (en cas d'abandon, vérifie la règle Unibet)</li>
<li>Pas de forfait annoncé juste avant le match</li>
<li>Heure de passage confirmée (au tennis, les matchs « à suivre » peuvent glisser)</li></ul></div>
<h2>Jours précédents</h2><div class="archives"><a href="{root}tennis.html">Aujourd'hui</a>{archives}</div>
{picker}{ticket}
<footer>Outil d'aide à la décision : aucune analyse ne garantit un résultat. Joue une mise fixe et raisonnable.<br>
Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé). Source : {_e(slate.source_label)}.</footer>
</main></body></html>"""


def write_site(slate, evaluations, bet, locked, out_dir: Path) -> Path:
    day = slate.generated_at.astimezone(TZ).date().isoformat()
    arch = out_dir / "tennis"
    arch.mkdir(parents=True, exist_ok=True)
    days = sorted({p.stem for p in arch.glob("*.html")} | {day}, reverse=True)
    (arch / f"{day}.html").write_text(build_html(slate, evaluations, bet, locked, days, root="../"), encoding="utf-8")
    page = out_dir / "tennis.html"
    page.write_text(build_html(slate, evaluations, bet, locked, days), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    from tracker_web import write_assets                 # onglet « Mes paris » + paris.js
    write_assets(out_dir)
    return page

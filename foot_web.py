"""
Page Foot du site :  docs/foot.html  +  docs/foot/AAAA-MM-JJ.html (une par jour).
Même design que les pages NBA et Tennis.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

import foot_config as fc
from analyzer import JOURS, MOIS, TZ, _fmt_dt
from foot_insights import build_insight
from insights import leg_probability
from models import Evaluation
from web_report import CSS, FONTS, _e, _time, nav_tabs

FOOT_CSS = """
.tourn{font:700 16px/1.2 var(--num);letter-spacing:.02em;margin:18px 0 2px;color:var(--accent)}
.tourn:first-child{margin-top:0}
.rk{color:var(--muted);font-size:12px;margin-left:4px}
.draw{font-size:12px;color:var(--muted);padding:1px 0 2px 44px}
"""


def _badge(team, small: bool = False) -> str:
    h = int(hashlib.md5(team.key.encode()).hexdigest()[:2], 16) * 360 // 256
    words = [w for w in (team.short or team.name).replace("-", " ").split() if w]
    txt = (words[0][:3] if len(words) == 1 else "".join(w[0] for w in words[:3])).upper()
    return (f'<span class="badge{" sm" if small else ""}" style="background:hsl({h} 50% 34%);color:#fff">'
            f'{_e(txt)}</span>')


def plain_reason(e: Evaluation) -> tuple[str, str]:
    r = e.rejections[0]
    if r.name == "Statut":
        return r.reason, ""
    if r.name == "Cote":
        if e.pick is None:
            return "Pas encore de cote Unibet", "Unibet n'a pas encore ouvert les paris sur ce match."
        if e.odds < fc.ODDS_MIN:
            return "Cote trop basse", f"Favori à {e.odds:.2f} : le gain serait trop faible pour le risque."
        return "Favori pas assez net", f"Cote de {e.odds:.2f}, au-dessus de la limite de {fc.ODDS_MAX:.2f}."
    return {
        "Mouvement de cote": ("La cote du favori monte", r.reason),
        "Risque de nul": ("Risque de match nul", r.reason),
        "Fatigue": ("Fatigue", r.reason),
        "Match piège": ("Match piège avant la Coupe d'Europe", r.reason),
        "Forme": ("Forme insuffisante", r.reason),
        "Dynamique croisée": ("L'adversaire est en forme", r.reason),
        "Classement": ("Classement incohérent", r.reason),
        "Face-à-face": ("L'adversaire domine les face-à-face", r.reason),
    }.get(r.name, (r.name, r.reason))


def _verdict(props, locked: Optional[dict], passed, rejected, slate) -> str:
    if locked:
        out = []
        for b in locked.get("bets", []):
            legs = "".join(f"""<div class="leg"><div class="who"><b>{_e(l['pick'])} gagne</b>
<span>contre {_e(l['opponent'])} · {_e(l['tournament'])} · {_e(l['time'])}</span></div>
<span class="pill">{l['odds']:.2f}</span></div>""" for l in b["legs"])
            stake = f" · mise conseillée {b['stake']} €" if b.get("stake") else ""
            out.append(f"""<div class="card verdict go"><span class="chip info">EN COURS · {_e(b.get('option', '').upper())}</span>
<h3>{_e(b['kind'])} · cote {b['total']:.2f}{stake}</h3>{legs}</div>""")
        return (f"""<p class="why">Ces paris ont été proposés le {_e(locked['created_label'])} et un de leurs matchs
a commencé : ils sont conservés jusqu'à la fin des matchs.</p>""" + "".join(out))
    if not slate.matches:
        return """<div class="card verdict none"><span class="chip off">PAS DE MATCH</span>
<h3>Pas de match de championnat dans les 36 prochaines heures</h3>
<p class="why">Trêve internationale ou milieu de semaine sans championnat. Le bot reprendra dès les prochains matchs.</p></div>"""
    if not props:
        counts = Counter(plain_reason(e)[0] for e in rejected)
        rows = "".join(f"<li><b>{n} match{'s' if n > 1 else ''}</b> : {_e(t.lower())}</li>"
                       for t, n in counts.most_common())
        return f"""<div class="card verdict none"><span class="chip off">PAS DE PARI</span>
<h3>Pas de pari foot pour l'instant</h3>
<p class="why">Aucun match ne passe tous les contrôles. Ne pas parier fait aussi partie de la stratégie.</p>
{f'<p class="lbl">Pourquoi les matchs ont été écartés</p><ul class="reasons risk">{rows}</ul>' if rows else ''}</div>"""
    from web_report import proposals_html
    return proposals_html(props, "foot", build_insight, passed, fc.BET_MAX_ODDS)


def _analysis_card(e: Evaluation, opened: bool = True, verdict: str = "Validé") -> str:
    from web_report import analysis_card
    m = e.matchup
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    sub = f"contre {_e(e.opponent.name)} · {_e(m.league_name)} · {_time(m.commence_time)} · {lieu}"
    return analysis_card(e, build_insight(e), "foot", sub, _badge(e.pick), verdict, opened)


def _row(e: Evaluation, legs) -> str:
    from explain import claude_url
    from tracker_web import claude_button
    from web_report import row_brief
    m = e.matchup
    ask = ""
    if m.unibet is not None:
        ask = " " + claude_button(claude_url(row_brief(e, "foot", legs, build_insight),
                                             "Que penses-tu de ce match ? Explique simplement."),
                                  "Demander à Claude", small=True)
    fav_home = m.unibet.home <= m.unibet.away if m.unibet else None

    def line(t, home: bool) -> str:
        odds = (m.unibet.home if home else m.unibet.away) if m.unibet else None
        fav = " fav" if fav_home is not None and fav_home == home else ""
        rk = f'<span class="rk">{t.rank}{"er" if t.rank == 1 else "e"}</span>' if t.rank else ""
        return (f'<div class="team{fav}">{_badge(t, small=True)}<span class="nm">{_e(t.name)}{rk}'
                f'{" <em>dom.</em>" if home else ""}</span><span class="od">{f"{odds:.2f}" if odds else "—"}</span></div>')

    draw = f'<div class="draw">Match nul : {m.unibet.draw:.2f}</div>' if m.unibet else ""
    if e in legs:
        chip, why = '<span class="chip go">À JOUER</span>', f"<b>{_e(e.pick.name)} gagne</b> — voir l'analyse plus haut."
    elif e.passed:
        chip = '<span class="chip info">VALIDÉ</span>'
        why = (f"<b>{_e(e.pick.name)} gagne ({e.odds:.2f})</b> passe tous les contrôles, mais n'est pas "
               f"dans les paris proposés ({leg_probability(e):.0%} de chances estimées).")
    else:
        title, detail = plain_reason(e)
        cls, label = ("off", "EN ATTENTE") if e.pick is None else ("no", "ÉCARTÉ")
        chip, why = f'<span class="chip {cls}">{label}</span>', f"<b>{_e(title)}</b> — {_e(detail)}"
    return f"""<div class="game"><div class="time">{_time(m.commence_time)}<small>Paris</small></div>
<div class="teams">{line(m.home, True)}{draw}{line(m.away, False)}</div>
<div class="status">{chip}</div><div class="reason">{why}{ask}</div></div>"""


def _last_bet(last: Optional[dict]) -> str:
    from tennis_web import _last_bet as tennis_last
    return tennis_last(last)


LEGEND = """<details><summary>Comment lire cette page</summary>
<ul class="legend">
<li><span class="chip go">À JOUER</span><span>Les paris foot proposés : un pari simple et un combiné, cote totale de {mx} au maximum.</span></li>
<li><span class="chip info">VALIDÉ</span><span>Passe tous les contrôles mais n'est pas dans les paris proposés.</span></li>
<li><span class="chip no">ÉCARTÉ</span><span>Au moins un contrôle a échoué : la raison est écrite en dessous.</span></li>
<li><span class="chip off">EN ATTENTE</span><span>Unibet n'a pas encore publié de cote.</span></li></ul>
<p class="lbl">Le pari étudié</p>
<p class="sub">Toujours la <b>victoire du favori</b> (pari « 1 » ou « 2 » sur Unibet). Au foot, un match nul fait perdre ce pari :
c'est pour ça que le bot écarte les matchs où le nul est probable.</p>
<p class="lbl">Les contrôles appliqués au favori</p>
<ul class="reasons ctrl">
<li><b>Cote</b> — entre {lo} et {hi}, et pas de hausse suspecte.</li>
<li><b>Risque de nul</b> — le marché ne donne pas plus de {dp:.0%} au nul, et les équipes ne font pas souvent match nul.</li>
<li><b>Fatigue</b> — pas de match (championnat, coupe, Europe) dans les 3 jours précédents.</li>
<li><b>Match piège</b> — pas de Coupe d'Europe juste après contre un adversaire de championnat plus faible.</li>
<li><b>Forme</b> — au moins {fp} point par match sur les 5 derniers, et correct à domicile / à l'extérieur.</li>
<li><b>Dynamique</b> — l'adversaire n'est pas en meilleure forme.</li>
<li><b>Classement</b> — le favori n'est pas nettement moins bien classé.</li>
<li><b>Face-à-face</b> — l'adversaire ne domine pas les confrontations des 3 dernières saisons.</li>
</ul><p class="sub">Les blessures et suspensions ne sont pas dans les données : vérifie-les (ou demande à Claude) avant de jouer.</p></details>"""


def _day_label(d: date) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def build_html(slate, evaluations, props, locked, archive_days: list[str], root: str = "") -> str:
    passed = sorted([e for e in evaluations if e.passed], key=lambda e: e.score, reverse=True)
    rejected = [e for e in evaluations if not e.passed]
    legs = props.legs if props else []
    today = slate.generated_at.astimezone(TZ).date()

    analysis = ""
    if legs:
        analysis = ("<h2>Pourquoi ce choix</h2><p class='h2sub'>L'explication en clair de chaque match proposé.</p>"
                    + "".join(_analysis_card(e, verdict="À jouer") for e in legs))
    others = [e for e in passed if e not in legs]
    if others:
        analysis += ("<h2>Validés mais non retenus</h2><p class='h2sub'>Alternatives si une cote change.</p>"
                     + "".join(_analysis_card(e, opened=False) for e in others))

    by_l: dict[str, list[Evaluation]] = {}
    for e in sorted(evaluations, key=lambda e: e.matchup.commence_time):
        by_l.setdefault(e.matchup.league_name, []).append(e)
    games = "".join(f'<div class="tourn">{_e(l)}</div>' + "".join(_row(e, legs) for e in es)
                    for l, es in by_l.items()) or "<p class='sub'>Aucun match dans les 36 prochaines heures.</p>"
    n_pending = sum(1 for e in evaluations if e.pick is None)

    from staking import stake_for
    from tracker_web import TRACKER_CSS, picker_html, ticket_html
    stakes = {f"foot:{e.matchup.event_id}": stake_for(build_insight(e).confidence) for e in passed}
    picker = picker_html("foot", evaluations, legs, stakes) if root == "" else ""
    ticket = ticket_html(root) if root == "" else ""
    archives = "".join(
        f'<a class="{"cur" if d == today.isoformat() else ""}" href="{root}foot/{_e(d)}.html">'
        f'{_e(_day_label(date.fromisoformat(d)).capitalize())}</a>' for d in archive_days[:14])
    legend = LEGEND.format(mx=f"{fc.BET_MAX_ODDS:.2f}", lo=f"{fc.ODDS_MIN:.2f}", hi=f"{fc.ODDS_MAX:.2f}",
                           dp=fc.DRAW_MAX_PROB, fp=fc.FORM_MIN_PPG)
    leagues = ", ".join(slate.leagues) or "aucun match"

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pronostic Foot</title>{FONTS}<style>{CSS}{FOOT_CSS}{TRACKER_CSS}</style></head><body><main>
{nav_tabs("foot", root)}
<header class="top"><div class="kicker">Pronostic foot · 5 grands championnats</div>
<h1>Foot — {_e(_day_label(today).capitalize())}</h1>
<p class="sub">Analyse du {_e(_fmt_dt(slate.generated_at))} (Paris) · matchs des {fc.ANALYSIS_HOURS} prochaines heures
· {_e(leagues)}</p>
<div class="counts"><div class="count"><b>{len(evaluations)}</b><span>matchs à venir</span></div>
<div class="count go"><b>{len(passed)}</b><span>passent les contrôles</span></div>
<div class="count no"><b>{len(rejected) - n_pending}</b><span>écartés{f' · {n_pending} en attente' if n_pending else ''}</span></div></div>
</header>
<h2>Les paris foot</h2><p class="h2sub">Deux options : un pari simple, plus sûr, et un combiné,
qui rapporte plus mais demande que les deux matchs passent.</p>
{_verdict(props, locked, passed, [e for e in rejected if e.pick is not None], slate)}
{_last_bet(getattr(slate, "last_bet", None)) if not locked else ""}
{analysis}
<h2>Programme</h2><p class="h2sub">Cotes Unibet 1 / N / 2 · le favori est en gras · classement en gris.</p>
<div class="card">{games}{legend}</div>
<h2>Avant de valider sur Unibet</h2><div class="card"><ul class="check">
<li>Pari « Résultat du match » (1N2) sur le favori, cote totale de {fc.BET_MAX_ODDS:.2f} au maximum</li>
<li>Compositions officielles vérifiées (environ 1 h avant le match)</li>
<li>Pas de blessure ni de suspension d'un joueur clé du favori</li>
<li>Rappel : un match nul fait perdre ce pari</li></ul></div>
<h2>Jours précédents</h2><div class="archives"><a href="{root}foot.html">Aujourd'hui</a>{archives}</div>
{picker}{ticket}
<footer>Outil d'aide à la décision : aucune analyse ne garantit un résultat. Joue une mise fixe et raisonnable.<br>
Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé). Source : {_e(slate.source_label)}.</footer>
</main></body></html>"""


def write_site(slate, evaluations, props, locked, out_dir: Path) -> Path:
    day = slate.generated_at.astimezone(TZ).date().isoformat()
    arch = out_dir / "foot"
    arch.mkdir(parents=True, exist_ok=True)
    days = sorted({p.stem for p in arch.glob("*.html")} | {day}, reverse=True)
    (arch / f"{day}.html").write_text(build_html(slate, evaluations, props, locked, days, root="../"), encoding="utf-8")
    page = out_dir / "foot.html"
    page.write_text(build_html(slate, evaluations, props, locked, days), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    from tracker_web import write_assets, write_digest
    from web_report import row_brief, row_line
    legs = props.legs if props else []
    items = []
    for e in evaluations:
        m = e.matchup
        verdict = "À jouer" if e in legs else ("Validé" if e.passed else ("En attente" if e.pick is None else "Écarté"))
        items.append({"id": f"foot:{m.event_id}", "sport": "foot", "label": m.label, "competition": m.league_name,
                      "time": m.commence_time.isoformat(), "verdict": verdict,
                      "line": f"{row_line(e, 'foot', legs)} [{m.league_name}]",
                      "brief": row_brief(e, "foot", legs, build_insight)})
    write_digest("foot", items, out_dir, slate.generated_at)
    write_assets(out_dir)
    return page

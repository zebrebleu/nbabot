"""
Génère le site statique (une page par jour + archives) à partir de l'analyse du bot.

    docs/index.html                 -> dernière analyse
    docs/archive/AAAA-MM-JJ.html    -> une page par jour
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import config
from analyzer import TZ, _fmt_day, no_bet_reason, select
from insights import build_insight
from models import Evaluation, Slate

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1b1d21;--muted:#6b6f76;--line:#e4e2dc;
--ok:#1f7a4d;--ok-bg:#e6f3ec;--ko:#b3261e;--ko-bg:#fbeaea;--warn:#8a5a00;--warn-bg:#fdf3dc;--accent:#c8102e}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--card:#1c1e22;--ink:#ececec;--muted:#9a9ea6;
--line:#2c2f35;--ok:#5fd09a;--ok-bg:#16301f;--ko:#ff8a80;--ko-bg:#3a1a1a;--warn:#f0c060;--warn-bg:#3a2d10;--accent:#ff5470}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:20px 16px 48px}
header h1{font-size:22px;margin:0 0 4px}header p{margin:0;color:var(--muted);font-size:13px}
h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:28px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px}
.combo{border:2px solid var(--accent)}
.total{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.total b{font-size:34px;color:var(--accent);font-variant-numeric:tabular-nums}
.pick h3{margin:0;font-size:17px}.meta{color:var(--muted);font-size:13px}
.odds{float:right;font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
ul{margin:8px 0 0;padding-left:0;list-style:none}li{padding:3px 0;font-size:14px}
li .n{display:inline-block;min-width:160px;font-weight:600}
.ok::before{content:"✓ ";color:var(--ok);font-weight:700}
.wa{background:var(--warn-bg);color:var(--warn);border-radius:6px;padding:4px 8px;margin-top:4px}
.empty{background:var(--warn-bg);color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}td{overflow-wrap:break-word}
details{margin-top:8px}summary{cursor:pointer;font-size:14px;font-weight:600;color:var(--muted)}td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:600}
.tag.v{background:var(--ok-bg);color:var(--ok)}.tag.r{background:var(--ko-bg);color:var(--ko)}
.tag.m{background:var(--warn-bg);color:var(--warn)}
.total small{color:var(--muted);font-size:13px}
.sum{margin:10px 0 4px;font-size:15px}
.sec h4{margin:12px 0 0;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.sec ul{margin-top:4px}.plus::before{content:"+ ";color:var(--ok);font-weight:700}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 20px}
@media (max-width:600px){.grid{grid-template-columns:1fr}}
.why{color:var(--muted);font-size:13px;display:block;margin-top:2px}
.check li::before{content:"☐ ";color:var(--muted)}
nav a{color:var(--ink);margin-right:12px;font-size:14px}
footer{color:var(--muted);font-size:12px;margin-top:32px}
@media (max-width:600px){.hide-sm{display:none}li .n{min-width:0;margin-right:6px}
main{padding:16px 12px 40px}
table,tbody,tr,td{display:block}thead{display:none}
tr{position:relative;padding:10px 0 10px 52px;border-bottom:1px solid var(--line)}tr:last-child{border:0}
td{border:0;padding:1px 0}td.t{position:absolute;left:0;top:10px;font-weight:600}
td.mt br{display:none}td.mt{font-weight:600}
td[data-l]::before{content:attr(data-l);color:var(--muted)}}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _time(dt: datetime) -> str:
    return f"{dt.astimezone(TZ):%H:%M}"


CONF_CLASS = {"Élevée": "v", "Moyenne": "m", "Prudente": "r"}


def _pick_card(e: Evaluation, key_players, detailed: bool = True) -> str:
    m = e.matchup
    ins = build_insight(e, key_players)
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
    reasons = "".join(f'<li class="ok"><span class="n">{_e(r.name)}</span>{_e(r.reason)}</li>'
                      for r in e.results)
    sections = "".join(
        f'<div class="sec"><h4>{_e(title)}</h4><ul>{"".join(f"<li>{_e(r)}</li>" for r in rows)}</ul></div>'
        for title, rows in ins.sections)
    strengths = "".join(f'<li class="plus">{_e(s)}</li>' for s in ins.strengths)
    risks = "".join(f'<li class="wa">⚠ {_e(r)}</li>' for r in ins.risks)
    blocks = ""
    if strengths:
        blocks += f'<div class="sec"><h4>Atouts</h4><ul>{strengths}</ul></div>'
    if risks:
        blocks += f'<div class="sec"><h4>Points de vigilance</h4><ul>{risks}</ul></div>'
    body = f"""<p class="sum">{_e(ins.summary)}</p>{blocks}
<details><summary>Analyse complète</summary><div class="grid">{sections}</div></details>
<details><summary>Filtres validés ({len(e.results)})</summary><ul>{reasons}</ul></details>"""
    if not detailed:
        body = f"<details><summary>Voir l'analyse</summary>{body}</details>"
    return f"""<div class="card pick">
<span class="odds">{e.odds:.2f}</span>
<h3>{_e(e.pick.name)} vainqueur</h3>
<div class="meta">{_e(m.label)} · {_time(m.commence_time)} (Paris) · {lieu}</div>
<div class="meta">Confiance <span class="tag {CONF_CLASS.get(ins.confidence, 'm')}">{_e(ins.confidence)}</span>
· proba. estimée {ins.win_prob:.0%}</div>
{body}</div>"""


def _row(e: Evaluation) -> str:
    m = e.matchup
    uni = f"{m.unibet.away:.2f} / {m.unibet.home:.2f}" if m.unibet else "—"
    ref = f"{m.reference.away:.2f} / {m.reference.home:.2f}" if m.reference else "—"
    if e.passed:
        status = f'<span class="tag v">Validé</span><span class="why">{_e(e.pick.name)} {e.odds:.2f}</span>'
    else:
        r = e.rejections[0]
        status = f'<span class="tag r">Rejeté</span><span class="why">{_e(r.name)} : {_e(r.reason)}</span>'
    return (f"<tr><td class='num t'>{_time(m.commence_time)}</td>"
            f"<td class='mt'>{_e(m.away.name)} <br>@ {_e(m.home.name)}</td>"
            f"<td class='num' data-l='Unibet ext. / dom. : '>{uni}</td>"
            f"<td class='num hide-sm'>{ref}</td><td>{status}</td></tr>")


def build_html(slate: Slate, evaluations: list[Evaluation], archive_links: list[str], root: str = "") -> str:
    passed, rejected, bet = select(evaluations)
    th = config.season_thresholds(slate.generated_at)
    gen = slate.generated_at.astimezone(TZ)
    kp = slate.key_players

    if bet:
        combo_html = (f'<div class="card combo"><div class="total"><span>{_e(bet.kind)} proposé<br>'
                      f'<small>Probabilité estimée que le pari passe : {bet.prob:.0%}</small></span>'
                      f'<b>{bet.total:.2f}</b></div></div>'
                      + "".join(_pick_card(e, kp) for e in bet.legs))
        others = [e for e in passed if e not in bet.legs]
    else:
        combo_html = (f'<div class="card empty"><b>Aucun pari aujourd\'hui.</b> '
                      f'{_e(no_bet_reason(passed))}</div>')
        others = passed

    alt_html = ""
    if others:
        alt_html = "<h2>Autres matchs validés</h2>" + "".join(_pick_card(e, kp, detailed=False) for e in others)

    rows = "".join(_row(e) for e in sorted(evaluations, key=lambda e: e.matchup.commence_time))
    table = (f"<h2>Toutes les cotes du jour ({len(evaluations)} matchs)</h2><div class='card'>"
             "<table><thead><tr><th>Heure</th><th>Match</th><th>Unibet ext. / dom.</th>"
             "<th class='hide-sm'>Marché</th><th>Analyse</th></tr></thead>"
             f"<tbody>{rows or '<tr><td colspan=5>Aucun match</td></tr>'}</tbody></table></div>")

    nav = "".join(f'<a href="{root}archive/{_e(a)}.html">{_e(a)}</a>' for a in archive_links[:14])
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analyse NBA du jour</title><style>{CSS}</style></head><body><main>
<header><h1>Analyse NBA — {_e(_fmt_day(slate.generated_at))}</h1>
<p>Mis à jour à {gen:%H:%M} (Paris) · {_e(slate.source_label)} · {_e(th.label)}</p>
<p>{len(evaluations)} matchs analysés · {len(passed)} validés · {len(rejected)} rejetés</p></header>
<h2>Sélection</h2>{combo_html}{alt_html}{table}
<h2>Avant de jouer sur Unibet</h2><div class="card"><ul class="check">
<li>La cote totale affichée ne dépasse pas {config.BET_MAX_ODDS:.2f}</li>
<li>Marché « Face à face », prolongations incluses</li>
<li>Rapport de blessures NBA revérifié ~30 min avant le match</li>
<li>Aucune annonce de repos de dernière minute</li></ul></div>
<h2>Jours précédents</h2><nav><a href="{root}index.html">Dernière analyse</a>{nav}</nav>
<footer>Outil d'aide à la décision : aucun filtre ne garantit un résultat. Mise fixe et raisonnable.
Joueurs Info Service : 09 74 75 13 13.</footer>
</main></body></html>"""


def write_site(slate: Slate, evaluations: list[Evaluation], out_dir: Path) -> Path:
    archive_dir = out_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    day = slate.generated_at.astimezone(TZ).strftime("%Y-%m-%d")
    days = sorted({p.stem for p in archive_dir.glob("*.html")} | {day}, reverse=True)

    (archive_dir / f"{day}.html").write_text(build_html(slate, evaluations, days, root="../"), encoding="utf-8")
    index = out_dir / "index.html"
    index.write_text(build_html(slate, evaluations, days), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return index

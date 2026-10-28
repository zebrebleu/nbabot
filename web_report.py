"""
Génère le site statique à partir de l'analyse du bot.

    docs/index.html                 -> prochaine nuit NBA (dernière analyse)
    docs/archive/AAAA-MM-JJ.html    -> une page par nuit (date américaine des matchs)
"""
from __future__ import annotations

import hashlib
import html
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import config
from analyzer import JOURS, TZ, _fmt_dt, night_label, no_bet_reason, select, slate_day
from insights import build_insight, leg_probability
from models import Evaluation, Slate, TeamContext

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700'
         '&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">')

CSS = """
:root{--bg:#f3f1ec;--card:#fff;--ink:#16181d;--muted:#646a73;--line:#e2ded5;--soft:#f7f5f0;
--go:#13795b;--go-bg:#e3f4ec;--info:#1d5fbf;--info-bg:#e4eefb;--no:#b3261e;--no-bg:#fbe9e7;
--warn:#8a5300;--warn-bg:#fdf1d8;--off:#6b7079;--off-bg:#eceae5;--accent:#e8590c;
--num:"Barlow Condensed",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#101216;--card:#1a1d22;--ink:#eceef1;
--muted:#9aa1ab;--line:#2b2f36;--soft:#20242a;--go:#4cd19a;--go-bg:#123326;--info:#7fb0ff;--info-bg:#15263f;
--no:#ff8f85;--no-bg:#3a1916;--warn:#f2bf5e;--warn-bg:#382a10;--off:#9aa1ab;--off-bg:#262a30;--accent:#ff7a33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:880px;margin:0 auto;padding:0 16px 56px}
a{color:inherit}
.top{padding:28px 0 18px}
.kicker{font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
h1{font:700 34px/1.05 var(--num);margin:6px 0 6px;letter-spacing:.01em}
.sub{color:var(--muted);font-size:13px;margin:0}
.counts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px}
.count{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.count b{display:block;font:700 28px/1 var(--num)}.count span{font-size:12px;color:var(--muted)}
.count.go b{color:var(--go)}.count.no b{color:var(--no)}
h2{font:700 22px/1.1 var(--num);margin:34px 0 4px;letter-spacing:.01em}
.h2sub{color:var(--muted);font-size:13px;margin:0 0 12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:12px}
.verdict.go{border:2px solid var(--go)}
.verdict.none{border:2px dashed var(--line)}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 10px;
font-size:12px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.chip.go{background:var(--go-bg);color:var(--go)}.chip.info{background:var(--info-bg);color:var(--info)}
.chip.no{background:var(--no-bg);color:var(--no)}.chip.off{background:var(--off-bg);color:var(--off)}
.chip.warn{background:var(--warn-bg);color:var(--warn)}
.verdict h3{font:700 26px/1.1 var(--num);margin:10px 0 14px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.stat{background:var(--soft);border-radius:12px;padding:10px 12px}
.stat span{display:block;font-size:12px;color:var(--muted)}
.stat b{font:700 30px/1.1 var(--num)}.stat.big b{color:var(--go)}
.leg{display:flex;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
.leg .who{flex:1;min-width:0}.leg .who b{display:block;font-size:16px}
.leg .who span{color:var(--muted);font-size:13px}
.pill{font:700 22px/1 var(--num);background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.badge{flex:none;width:44px;height:44px;border-radius:12px;display:grid;place-items:center;
font:700 15px/1 var(--num);letter-spacing:.03em}
.badge.sm{width:34px;height:34px;border-radius:9px;font-size:13px}
.why{font-size:15px;margin:4px 0 0}
.reasons{margin:14px 0 0;padding:0;list-style:none}
.reasons li{padding:4px 0 4px 24px;position:relative;font-size:14px}
.reasons li::before{position:absolute;left:0;top:4px;font-weight:700}
.reasons.plus li::before{content:"✓";color:var(--go)}
.reasons.risk li::before{content:"!";color:var(--warn);left:6px}
.reasons.ctrl li::before{content:"✓";color:var(--go)}
.reasons.ctrl b{font-weight:600}
.lbl{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:16px 0 0}
.head{display:flex;align-items:flex-start;gap:12px}.head .who{flex:1}
.head h3{margin:0;font-size:18px}.head p{margin:2px 0 0;color:var(--muted);font-size:13px}
.meter{display:inline-flex;gap:3px;vertical-align:middle;margin-left:4px}
.meter i{width:14px;height:6px;border-radius:3px;background:var(--line)}.meter i.on{background:var(--go)}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-weight:600;font-size:14px;color:var(--info);list-style:none}
summary::-webkit-details-marker{display:none}summary::before{content:"▸ ";}
details[open] summary::before{content:"▾ "}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px}
.grid h4{margin:12px 0 2px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.grid ul{margin:0;padding-left:16px;font-size:14px}
.game{display:grid;grid-template-columns:54px 1fr auto;gap:4px 12px;padding:14px 0;border-top:1px solid var(--line)}
.game:first-child{border-top:0;padding-top:0}
.time{font:700 20px/1.2 var(--num)}.time small{display:block;font:500 11px Inter,sans-serif;color:var(--muted)}
.teams{min-width:0}
.team{display:flex;align-items:center;gap:10px;padding:3px 0}
.team .nm{flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.team .nm em{font-style:normal;color:var(--muted);font-size:12px}
.team .od{font:700 18px/1 var(--num);min-width:40px;text-align:right;color:var(--muted)}
.team.fav .nm{font-weight:600}.team.fav .od{color:var(--ink)}
.status{text-align:right}
.reason{grid-column:2/4;font-size:13px;color:var(--muted);margin-top:2px}
.reason b{color:var(--ink);font-weight:600}
.legend{display:grid;gap:10px;margin:12px 0 0;padding:0;list-style:none}
.legend li{display:flex;gap:10px;align-items:flex-start;font-size:14px}
.legend .chip{min-width:92px;justify-content:center}
.check{margin:0;padding:0;list-style:none}.check li{padding:5px 0 5px 28px;position:relative}
.check li::before{content:"";position:absolute;left:0;top:7px;width:16px;height:16px;border:2px solid var(--muted);border-radius:4px}
.archives{display:flex;flex-wrap:wrap;gap:8px}
.archives a{text-decoration:none;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px}
.archives a.cur{border-color:var(--accent);color:var(--accent);font-weight:600}
footer{color:var(--muted);font-size:12px;margin-top:36px;line-height:1.6}
@media (max-width:600px){h1{font-size:28px}.stats{grid-template-columns:1fr 1fr}.stat.big{grid-column:1/3}
.grid{grid-template-columns:1fr}.game{grid-template-columns:52px 1fr;gap:4px 8px}.status{grid-column:2;text-align:left}
.time{font-size:18px}.team .nm{white-space:normal}
.reason{grid-column:2}.counts b{font-size:24px}}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _e(x) -> str:
    return html.escape(str(x))


def _time(dt: datetime) -> str:
    return f"{dt.astimezone(TZ):%H:%M}"


def _money(x: float) -> str:
    return f"{x:.2f}".replace(".", ",") + " €"


def _abbr(team: TeamContext) -> str:
    return (team.abbr or team.key[:3]).upper()


def _badge(team: TeamContext, small: bool = False) -> str:
    color = (team.color or "").lstrip("#")
    if len(color) != 6:
        h = int(hashlib.md5(team.key.encode()).hexdigest()[:2], 16) * 360 // 256
        style = f"background:hsl({h} 55% 38%);color:#fff"
    else:
        r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
        fg = "#111" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "#fff"
        style = f"background:#{color};color:{fg}"
    return f'<span class="badge{" sm" if small else ""}" style="{style}">{_e(_abbr(team))}</span>'


def _meter(conf: str) -> str:
    n = {"Élevée": 3, "Moyenne": 2}.get(conf, 1)
    return '<span class="meter">' + "".join(f'<i class="{"on" if i < n else ""}"></i>' for i in range(3)) + "</span>"


def plain_reason(e: Evaluation) -> tuple[str, str]:
    """Raison d'un rejet en langage simple : (titre court, détail)."""
    r = e.rejections[0]
    txt = r.reason
    insufficient = "insuffisantes" in txt
    if r.name == "Statut":
        return txt, "L'analyse a été faite avant le coup d'envoi."
    if r.name == "Début de saison":
        return "Pause début de saison", f"Pas de pronostic avant {config.SEASON_MIN_GAMES} matchs joués. {txt}."
    if r.name == "Cote":
        if e.pick is None:
            return "Pas encore de cote Unibet", "Unibet n'a pas encore ouvert les paris sur ce match."
        if e.odds < config.ODDS_MIN:
            return "Cote trop basse", f"Favori à {e.odds:.2f} : le gain serait trop faible pour le risque."
        return "Favori pas assez net", f"Cote de {e.odds:.2f}, au-dessus de la limite de {config.ODDS_MAX:.2f}."
    if insufficient:
        return "Pas assez de matchs joués", "Trop tôt dans la saison pour juger la forme. " + txt
    return {
        "Mouvement de cote": ("La cote du favori monte", "Le marché commence à douter. " + txt),
        "Back-to-back": ("Fatigue", "Deuxième match en 24 h, à l'extérieur. " + txt),
        "Trap game": ("Match piège", "Le favori a un gros choc juste après et risque de se ménager. " + txt),
        "Road trip": ("Trop de déplacements", txt),
        "Forme dom./ext.": ("Forme insuffisante", txt),
        "Dynamique croisée": ("L'outsider est en forme", txt),
        "Infirmerie": ("Blessure importante", txt),
        "Anti-tanking": ("Fin de saison à risque", "Équipe du bas de classement, cadres souvent au repos. " + txt),
    }.get(r.name, (r.name, txt))


# ---------------------------------------------------------------------------
# Blocs
# ---------------------------------------------------------------------------
def season_pause(evaluations: list[Evaluation], now: datetime):
    """Si tous les matchs analysables sont bloqués par le début de saison :
    (matchs joués min, max, date estimée de reprise). Sinon None."""
    need = config.SEASON_MIN_GAMES
    analysable = [e for e in evaluations if e.pick is not None]
    if not need or not analysable or not all(
            e.rejections and e.rejections[0].name == "Début de saison" for e in analysable):
        return None
    played = [e.metrics.get(k, 0) for e in analysable for k in ("games_pick", "games_opp")]
    lo, hi = min(played), max(played)
    typical = sorted(played)[len(played) // 2]
    days = max(0.0, (need - typical) / config.GAMES_PER_WEEK * 7)
    from datetime import timedelta
    return lo, hi, (now + timedelta(days=days)).astimezone(TZ).date()


def _verdict(bet, passed: list[Evaluation], rejected: list[Evaluation], pause=None) -> str:
    if not bet and pause:
        lo, hi, eta = pause
        from analyzer import MOIS
        return f"""<div class="card verdict none"><span class="chip warn">PAUSE DÉBUT DE SAISON</span>
<h3>Pas de pronostic pour l'instant</h3>
<p class="why">En début de saison, les équipes n'ont pas encore assez joué pour que les bilans
soient fiables. Le bot attend que <b>chaque équipe ait joué {config.SEASON_MIN_GAMES} matchs</b>
avant de proposer un pari.</p>
<div class="stats"><div class="stat"><span>Matchs joués par les équipes de la nuit</span><b>{lo} à {hi}</b></div>
<div class="stat"><span>Requis</span><b>{config.SEASON_MIN_GAMES}</b></div>
<div class="stat big"><span>Reprise estimée</span><b>vers le {eta.day} {MOIS[eta.month - 1]}</b></div></div>
<p class="sub">Les matchs restent affichés ci-dessous avec leurs cotes, pour suivre la saison.</p></div>"""
    if not bet:
        counts = Counter(plain_reason(e)[0] for e in rejected)
        rows = "".join(f"<li><b>{n} match{'s' if n > 1 else ''}</b> : {_e(t.lower())}</li>"
                       for t, n in counts.most_common())
        detail = (f'<p class="lbl">Pourquoi les matchs ont été écartés</p><ul class="reasons risk">{rows}</ul>'
                  if rows else "")
        return f"""<div class="card verdict none"><span class="chip off">PAS DE PARI</span>
<h3>Ce soir, on ne joue pas</h3>
<p class="why">{_e(no_bet_reason(passed))} Ne pas parier fait aussi partie de la stratégie :
le bot ne propose un match que s'il passe tous les contrôles.</p>{detail}</div>"""

    legs = ""
    for e in bet.legs:
        lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
        legs += f"""<div class="leg">{_badge(e.pick)}<div class="who"><b>{_e(e.pick.name)} gagne</b>
<span>contre {_e(e.opponent.name)} · {_time(e.matchup.commence_time)} · {lieu}</span></div>
<span class="pill">{e.odds:.2f}</span></div>"""
    early = any(r.name == "Début de saison" for e in bet.legs for r in e.warnings)
    note = ("""<p class="why" style="margin:0 0 14px"><span class="chip warn">DÉBUT DE SAISON</span>
Les équipes ont encore peu joué : ce pari repose surtout sur les cotes du marché.
Confiance plafonnée à « Prudente », mise réduite conseillée.</p>""" if early else "")
    return f"""<div class="card verdict go"><span class="chip go">● À JOUER SUR UNIBET</span>
<h3>{_e(bet.kind)}</h3>{note}
<div class="stats"><div class="stat big"><span>Cote totale</span><b>{bet.total:.2f}</b></div>
<div class="stat"><span>Chances estimées</span><b>{bet.prob:.0%}</b></div>
<div class="stat"><span>Pour 10 € misés</span><b>{_money(10 * bet.total)}</b></div></div>
{legs}</div>"""


def _analysis_card(e: Evaluation, key_players, opened: bool = True) -> str:
    ins = build_insight(e, key_players)
    lieu = "à domicile" if e.pick_is_home else "à l'extérieur"
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
<p>contre {_e(e.opponent.name)} · {_time(e.matchup.commence_time)} · {lieu}</p>
<p>Confiance : <b>{_e(ins.confidence)}</b>{_meter(ins.confidence)} · chances estimées {ins.win_prob:.0%}</p>
</div></div>{body}</div>"""


def _game_row(e: Evaluation, bet_legs: list[Evaluation]) -> str:
    m = e.matchup
    fav_home = m.unibet.home <= m.unibet.away if m.unibet else None

    def team_line(team: TeamContext, home: bool) -> str:
        odds = (m.unibet.home if home else m.unibet.away) if m.unibet else None
        score = m.home_score if home else m.away_score
        right = (f"{score:.0f}" if m.state != "pre" and score is not None
                 else (f"{odds:.2f}" if odds else "—"))
        fav = " fav" if fav_home is not None and fav_home == home else ""
        tag = " <em>dom.</em>" if home else ""
        return (f'<div class="team{fav}">{_badge(team, small=True)}'
                f'<span class="nm">{_e(team.name)}{tag}</span><span class="od">{right}</span></div>')

    if e in bet_legs:
        chip, reason = '<span class="chip go">À JOUER</span>', f"<b>{_e(e.pick.name)} gagne</b> — voir l'analyse plus haut."
    elif e.passed:
        chip = '<span class="chip info">VALIDÉ</span>'
        reason = (f"<b>{_e(e.pick.name)} gagne ({e.odds:.2f})</b> passe tous les contrôles, "
                  f"mais n'est pas dans le meilleur pari ({leg_probability(e):.0%} de chances estimées).")
    elif m.state != "pre":
        title, _ = plain_reason(e)
        chip, reason = f'<span class="chip off">{_e(title.upper())}</span>', _e(m.status_detail or "")
    else:
        title, detail = plain_reason(e)
        if e.pick is None:
            cls, label = "off", "EN ATTENTE"
        elif e.rejections[0].name == "Début de saison":
            cls, label = "warn", "EN PAUSE"
        else:
            cls, label = "no", "ÉCARTÉ"
        chip, reason = f'<span class="chip {cls}">{label}</span>', f"<b>{_e(title)}</b> — {_e(detail)}"

    return f"""<div class="game"><div class="time">{_time(m.commence_time)}<small>Paris</small></div>
<div class="teams">{team_line(m.away, False)}{team_line(m.home, True)}</div>
<div class="status">{chip}</div><div class="reason">{reason}</div></div>"""


LEGEND = """<details><summary>Comment lire cette page</summary>
<ul class="legend">
<li><span class="chip go">À JOUER</span><span>Le pari proposé ce soir : 1 ou 2 matchs, cote totale de 1,80 au maximum.</span></li>
<li><span class="chip info">VALIDÉ</span><span>Le match passe tous les contrôles mais n'a pas été retenu dans le pari.</span></li>
<li><span class="chip no">ÉCARTÉ</span><span>Au moins un contrôle a échoué : la raison est écrite en dessous.</span></li>
<li><span class="chip warn">EN PAUSE</span><span>Une des deux équipes a joué moins de {n} matchs (hors début de saison) : pas de pronostic.</span></li>
<li><span class="chip off">EN ATTENTE</span><span>Unibet n'a pas encore publié de cote : le match sera analysé au prochain passage.</span></li>
</ul>
<p class="lbl">Les contrôles appliqués au favori</p>
<ul class="reasons ctrl">
<li><b>Début de saison</b> — en octobre-novembre, un pari reste possible avec peu de matchs joués
(alerte + confiance « Prudente ») ; ensuite, {n} matchs minimum par équipe.</li>
<li><b>Cote</b> — entre {lo} et {hi}, et pas de hausse suspecte avant le match.</li>
<li><b>Fatigue</b> — pas de 2e match en 24 h à l'extérieur, pas de 3e match d'affilée en déplacement.</li>
<li><b>Match piège</b> — pas de gros choc prévu dans les 48 h qui suivent.</li>
<li><b>Forme</b> — bon bilan récent à domicile ou à l'extérieur, outsider pas en meilleure forme.</li>
<li><b>Blessures</b> — star et titulaires majeurs disponibles.</li>
<li><b>Fin de saison</b> — pas d'équipe du bas de tableau en mars ou avril.</li>
</ul></details>"""


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def _archive_label(stem: str) -> str:
    try:
        d = date.fromisoformat(stem)
    except ValueError:
        return stem
    return f"Nuit du {JOURS[d.weekday()][:3]}. {d.day:02d}/{d.month:02d}"


def build_html(slate: Slate, evaluations: list[Evaluation], archive_days: list[str], root: str = "") -> str:
    passed, rejected, bet = select(evaluations)
    kp = slate.key_players
    current = slate_day(slate).isoformat()
    legs = bet.legs if bet else []

    analysis = ""
    if legs:
        analysis = ("<h2>Pourquoi ce choix</h2><p class='h2sub'>L'analyse détaillée de chaque match du pari.</p>"
                    + "".join(_analysis_card(e, kp) for e in legs))
    others = [e for e in passed if e not in legs]
    if others:
        analysis += ("<h2>Validés mais non retenus</h2><p class='h2sub'>Alternatives possibles si une cote "
                     "change ou si une info de dernière minute tombe.</p>"
                     + "".join(_analysis_card(e, kp, opened=False) for e in others))

    ordered = sorted(evaluations, key=lambda e: e.matchup.commence_time)
    games = "".join(_game_row(e, legs) for e in ordered) or "<p class='sub'>Aucun match au calendrier.</p>"
    n_pending = sum(1 for e in evaluations if e.pick is None and e.matchup.state == "pre")

    archives = "".join(
        f'<a class="{"cur" if d == current else ""}" href="{root}archive/{_e(d)}.html">{_e(_archive_label(d))}</a>'
        for d in archive_days[:14])

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pronostic NBA</title>{FONTS}<style>{CSS}</style></head><body><main>
<header class="top"><div class="kicker">Pronostic NBA · aide à la décision</div>
<h1>{_e(night_label(slate)[0].upper() + night_label(slate)[1:])}</h1>
<p class="sub">Analyse du {_e(_fmt_dt(slate.generated_at))} (Paris) · heures des matchs à l'heure de Paris</p>
<div class="counts"><div class="count"><b>{len(evaluations)}</b><span>matchs au programme</span></div>
<div class="count go"><b>{len(passed)}</b><span>passent les contrôles</span></div>
<div class="count no"><b>{len(rejected) - n_pending}</b><span>écartés{f' · {n_pending} en attente' if n_pending else ''}</span></div></div>
</header>
<h2>Le pari du soir</h2>{_verdict(bet, passed, [e for e in rejected if e.matchup.state == 'pre'],
                                   season_pause(evaluations, slate.generated_at))}
{analysis}
<h2>Programme de la nuit</h2><p class="h2sub">Cotes Unibet de chaque équipe · le favori est en gras.</p>
<div class="card">{games}{LEGEND.format(lo=f"{config.ODDS_MIN:.2f}", hi=f"{config.ODDS_MAX:.2f}", n=config.SEASON_MIN_GAMES)}</div>
<h2>Avant de valider sur Unibet</h2><div class="card"><ul class="check">
<li>La cote totale affichée sur Unibet ne dépasse pas {config.BET_MAX_ODDS:.2f}</li>
<li>Pari « Face à face » (vainqueur du match, prolongations incluses)</li>
<li>Blessures revérifiées environ 30 minutes avant le match</li>
<li>Pas d'annonce de repos de dernière minute pour les joueurs clés</li></ul></div>
<h2>Nuits précédentes</h2><div class="archives"><a href="{root}index.html">Prochaine nuit</a>{archives}</div>
<footer>Outil d'aide à la décision : aucune analyse ne garantit un résultat. Joue une mise fixe et raisonnable.<br>
Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé). Source : {_e(slate.source_label)}.</footer>
</main></body></html>"""


def archive_path(out_dir: Path, slate: Slate) -> Path:
    return out_dir / "archive" / f"{slate_day(slate).isoformat()}.html"


def write_site(slate: Slate, evaluations: list[Evaluation], out_dir: Path) -> Path:
    page = archive_path(out_dir, slate)
    page.parent.mkdir(parents=True, exist_ok=True)
    days = sorted({p.stem for p in page.parent.glob("*.html")} | {page.stem}, reverse=True)

    page.write_text(build_html(slate, evaluations, days, root="../"), encoding="utf-8")
    index = out_dir / "index.html"
    index.write_text(build_html(slate, evaluations, days), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return index

"""
Suivi des paris (stocké dans le navigateur, localStorage) :

  * en bas des pages NBA et Tennis : section « Ajouter à mes paris » — on clique sur les
    équipes/joueurs joués, un ticket se remplit (il suit d'une page à l'autre), on valide avec la mise ;
  * onglet « Mes paris » (docs/mes-paris.html) : tableau, statuts, bilan, ajout manuel, export/import.

Le code JavaScript commun est écrit dans docs/paris.js.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def leg_dict(sport: str, e) -> dict:
    """Sélection au format du ticket (mêmes champs que les boutons du sélecteur)."""
    m = e.matchup
    return {"id": f"{sport}:{m.event_id}", "sport": sport,
            "competition": getattr(m, "tournament", None) or "NBA",
            "time": m.commence_time.isoformat(), "pick": e.pick.name, "opponent": e.opponent.name,
            "odds": round(e.odds, 2)}


def ticket_button(sport: str, legs, stake: int) -> str:
    import json
    data = _e(json.dumps([leg_dict(sport, e) for e in legs], ensure_ascii=False))
    return (f'<button type="button" class="btn main" data-addbet="{data}" data-stake="{stake}">'
            f'Mettre ce pari dans mon ticket ({stake} €)</button>')


def claude_button(url: str, label: str = "Discuter de ce match avec Claude", small: bool = False) -> str:
    cls = "ask small" if small else "btn ask"
    return f'<a class="{cls}" href="{_e(url)}" target="_blank" rel="noopener">{_e(label)} ↗</a>'


def clair_box(lines: list[str]) -> str:
    return ('<div class="clair"><p class="lbl">En clair</p><ul>'
            + "".join(f"<li>{_e(l)}</li>" for l in lines) + "</ul></div>")


def write_digest(sport: str, items: list[dict], out_dir: Path, generated_at: datetime) -> None:
    """Fiches des matchs pour l'onglet Chatbot (docs/data/<sport>_digest.json)."""
    import json
    path = out_dir / "data" / f"{sport}_digest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": generated_at.isoformat(), "matches": items},
                               ensure_ascii=False, indent=1), encoding="utf-8")


def picks_items(sport: str, evaluations, legs) -> list[dict]:
    """Matchs à venir avec cote Unibet, prêts à être sélectionnés."""
    items = []
    for e in sorted(evaluations, key=lambda e: e.matchup.commence_time):
        m = e.matchup
        if m.unibet is None or getattr(m, "state", "pre") != "pre":
            continue
        a, b = (m.away, m.home) if sport == "nba" else (m.home, m.away)
        oa, ob = (m.unibet.away, m.unibet.home) if sport == "nba" else (m.unibet.home, m.unibet.away)
        items.append({
            "id": f"{sport}:{m.event_id}", "sport": sport,
            "competition": getattr(m, "tournament", None) or "NBA",
            "time": m.commence_time,
            "sides": [(a.name, round(oa, 2)), (b.name, round(ob, 2))],
            "pick": e.pick.name if e.pick else None,
            "verdict": "À jouer" if e in legs else ("Validé" if e.passed else "Écarté"),
        })
    return items


def picker_html(sport: str, evaluations, legs, stakes: dict | None = None) -> str:
    """Section « Ajouter à mes paris » en bas d'une page de sport.
    `stakes` : {id: mise conseillée} pour les favoris validés (pré-affichée dans le ticket)."""
    stakes = stakes or {}
    items = picks_items(sport, evaluations, legs)
    chips = {"À jouer": '<span class="chip go">À JOUER</span>', "Validé": '<span class="chip info">VALIDÉ</span>',
             "Écarté": '<span class="chip off">ÉCARTÉ</span>'}
    rows, group = [], None
    for it in items:
        g = "NBA" if sport == "nba" else it["competition"]
        if g != group:
            rows.append(f'<div class="pickgrp">{_e(g)}</div>')
            group = g
        t = it["time"].astimezone(TZ)
        btns = []
        for i, (name, odds) in enumerate(it["sides"]):
            opp = it["sides"][1 - i][0]
            st = stakes.get(it["id"]) if name == it["pick"] else None
            stake_attr = f' data-stake="{st}"' if st else ""
            btns.append(
                f'<button type="button" class="side{" fav" if name == it["pick"] else ""}" '
                f'data-id="{_e(it["id"])}" data-sport="{sport}" data-comp="{_e(it["competition"])}" '
                f'data-time="{_e(it["time"].isoformat())}" data-pick="{_e(name)}" data-opp="{_e(opp)}" '
                f'data-odds="{odds}"{stake_attr} aria-pressed="false"><span>{_e(name)}</span><b>{odds:.2f}</b></button>')
        rows.append(f'<div class="pm"><div class="meta"><span>{t:%d/%m %H:%M}</span>{chips[it["verdict"]]}</div>'
                    f'<div class="sides">{"".join(btns)}</div></div>')
    body = "".join(rows) or '<p class="empty">Aucun match avec cote à venir pour le moment.</p>'
    return f"""<h2 id="ajouter">Ajouter à mes paris</h2>
<p class="h2sub">Clique sur l'équipe ou le joueur que tu as joué. Ton ticket apparaît en bas de l'écran
(il reste rempli si tu changes d'onglet, pour faire un combiné NBA + tennis).</p>
<div class="card" id="picker">{body}</div>"""


def ticket_html(root: str = "") -> str:
    """Ticket flottant (présent sur toutes les pages)."""
    return f"""<div class="card slip" id="slip" data-paris="{root}mes-paris.html" hidden>
<div class="slip-head"><span class="chip go">TON TICKET</span> <b id="slipKind"></b>
<button class="btn ghost small" id="clearSel" type="button">Vider</button></div>
<ul class="legs" id="slipLegs"></ul>
<div class="row">
<div><span class="sub">Cote totale</span><div class="tot" id="slipTotal">—</div></div>
<label>Mise (€)<input id="stake" inputmode="decimal" placeholder="ex. 20"></label>
<label>Date<input id="date" type="date"></label>
<div><span class="sub">Gain possible</span><div class="tot" id="slipGain">—</div></div>
</div>
<div class="tools"><button class="btn main" id="addBet" type="button" disabled>Enregistrer dans mes paris</button>
<a class="btn ghost" href="{root}mes-paris.html">Voir mes paris</a></div></div>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<script src="{root}paris.js"></script>"""


TRACKER_CSS = """
.pickgrp{font:700 16px/1.2 var(--num);letter-spacing:.02em;color:var(--accent);margin:16px 0 6px}
.pickgrp:first-child{margin-top:0}
.pm{padding:10px 0;border-top:1px solid var(--line)}.pickgrp+.pm{border-top:0}
.pm .meta{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);margin-bottom:6px}
.sides{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.side{font:inherit;text-align:left;cursor:pointer;border:1.5px solid var(--line);background:var(--soft);
color:var(--ink);border-radius:10px;padding:9px 11px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.side b{font:700 18px/1 var(--num)}.side span{font-size:14px;overflow-wrap:anywhere}
.side:hover{border-color:var(--muted)}
.side.on{border-color:var(--go);background:var(--go-bg)}.side.on b{color:var(--go)}
.side.fav span{font-weight:600}
.slip{position:sticky;bottom:12px;z-index:5;border:2px solid var(--go);box-shadow:0 8px 30px rgba(0,0,0,.18);margin-top:16px}
.slip-head{display:flex;align-items:center;gap:8px}.slip-head .btn{margin-left:auto}
.slip .row{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
.slip label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted);flex:1;min-width:120px}
input,select{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px}
input:focus,select:focus,button:focus-visible,a.btn:focus-visible{outline:2px solid var(--info);outline-offset:1px}
.btn{font:600 14px Inter,sans-serif;cursor:pointer;border-radius:10px;padding:10px 14px;border:1px solid var(--line);
background:var(--card);color:var(--ink);text-decoration:none;display:inline-block}
.btn.main{background:var(--go);border-color:var(--go);color:#fff}.btn.main:disabled{opacity:.45;cursor:not-allowed}
.btn.ghost{background:none}.btn.small{padding:5px 10px;font-size:13px}
.legs{margin:8px 0 10px;padding:0;list-style:none;font-size:14px}
.legs li{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:3px 0}
.legs li .x{border:0;background:none;color:var(--muted);cursor:pointer;font-size:15px;padding:2px 6px}
.tot{font:700 26px/1 var(--num)}
.bets{width:100%;border-collapse:collapse;font-size:14px}
.bets th,.bets td{text-align:left;padding:10px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.bets th{font-size:12px;color:var(--muted);font-weight:600}
.bets td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.pos{color:var(--go);font-weight:700}.neg{color:var(--no);font-weight:700}
.sel{font-size:13px}.sel div{padding:1px 0}
.empty{color:var(--muted);font-size:14px;padding:6px 0}
.tools{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.note{font-size:12px;color:var(--muted);margin-top:10px}
.mrow{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
.mrow label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted);flex:1;min-width:110px}
.mrow label.w{flex:2;min-width:180px}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);
padding:10px 16px;border-radius:10px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
.toast.show{opacity:1;pointer-events:auto}.toast a,.toast button{color:inherit}
.clair{background:var(--soft);border-radius:12px;padding:12px 14px;margin:12px 0 4px}
.clair .lbl{margin:0 0 4px}.clair ul{margin:0;padding-left:18px}.clair li{padding:3px 0;font-size:15px}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.btn.ask{border-color:var(--info);color:var(--info)}
a.ask.small{font-size:12px;font-weight:600;color:var(--info);text-decoration:none;white-space:nowrap}
.stats.four{grid-template-columns:repeat(4,1fr)}
@media (max-width:600px){.stats.four{grid-template-columns:1fr 1fr}.stats.four .stat.big{grid-column:auto}}
@media (max-width:600px){.sides{grid-template-columns:1fr}
.bets thead{display:none}.bets,.bets tbody,.bets tr,.bets td{display:block}
.bets tr{border-bottom:1px solid var(--line);padding:10px 0}.bets td{border:0;padding:2px 0}
.bets td[data-l]::before{content:attr(data-l);color:var(--muted);font-size:12px;margin-right:6px}}
"""

JS = r"""(function () {
const BETS = 'mes_paris_v1', TICKET = 'ticket_v1';
const $ = s => document.querySelector(s);
const fmt = x => (Math.round(x * 100) / 100).toFixed(2).replace('.', ',');
const eur = x => fmt(x) + ' €';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = v => parseFloat(String(v || '').replace(',', '.'));
const read = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k) || 'null'); return Array.isArray(v) ? v : d; } catch (e) { return d; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); return true; }
  catch (e) { toast("Impossible d'enregistrer dans ce navigateur (navigation privée ?)"); return false; } };
const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); };
const totalOf = legs => Math.round(legs.reduce((p, l) => p * l.odds, 1) * 100) / 100;   // arrondi comme Unibet

let toastTimer;
function toast(html) {
  const t = $('#toast'); if (!t) return;
  t.innerHTML = html; t.classList.add('show'); clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 5000);
}

/* ---------- Ticket (pages NBA, Tennis et Mes paris) ---------- */
function ticket() { return read(TICKET, []); }
function setTicket(l) { write(TICKET, l); renderTicket(); markPicker(); }

function markPicker() {
  const legs = ticket();
  document.querySelectorAll('#picker .side').forEach(b => {
    const on = legs.some(l => l.id === b.dataset.id && l.pick === b.dataset.pick);
    b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  });
}

function renderTicket() {
  const slip = $('#slip'); if (!slip) return;
  const legs = ticket();
  slip.hidden = !legs.length;
  if (!legs.length) return;
  $('#slipKind').textContent = legs.length === 1 ? 'Pari simple' : `Combiné de ${legs.length} matchs`;
  $('#slipLegs').innerHTML = legs.map((l, i) => `<li><span><b>${esc(l.pick)}</b> <span class="sub">vs ${esc(l.opponent)}${l.sport === 'tennis' ? ' · tennis' : l.sport === 'nba' ? ' · NBA' : ''}</span></span>
    <span><b>${fmt(l.odds)}</b><button class="x" type="button" data-rm="${i}" aria-label="Retirer">✕</button></span></li>`).join('');
  $('#slipLegs').querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { const l = ticket(); l.splice(+b.dataset.rm, 1); setTicket(l); });
  const total = totalOf(legs);
  $('#slipTotal').textContent = fmt(total);
  const rec = legs.every(l => l.stake) ? Math.min(...legs.map(l => l.stake)) : null;   // confiance la plus basse
  $('#stake').placeholder = rec ? `conseillé : ${rec} €` : 'ex. 20';
  const st = num($('#stake').value);
  $('#slipGain').textContent = st > 0 ? eur(st * total) : '—';
  $('#addBet').disabled = !(st > 0);
}

function initPicker() {
  document.querySelectorAll('#picker .side').forEach(b => b.addEventListener('click', () => {
    let legs = ticket();
    const same = legs.find(l => l.id === b.dataset.id);
    legs = legs.filter(l => l.id !== b.dataset.id);
    if (!same || same.pick !== b.dataset.pick)
      legs.push({id: b.dataset.id, sport: b.dataset.sport, competition: b.dataset.comp, time: b.dataset.time,
                 pick: b.dataset.pick, opponent: b.dataset.opp, odds: num(b.dataset.odds),
                 stake: b.dataset.stake ? +b.dataset.stake : null});
    setTicket(legs);
  }));
  // « Mettre ce pari dans mon ticket » : pari proposé par le bot, avec sa mise conseillée
  document.querySelectorAll('[data-addbet]').forEach(b => b.addEventListener('click', () => {
    let add = []; try { add = JSON.parse(b.dataset.addbet); } catch (e) { return; }
    const st = +b.dataset.stake || null;
    const legs = ticket().filter(l => !add.some(a => a.id === l.id)).concat(add.map(a => ({...a, stake: st})));
    setTicket(legs);
    if (st && $('#stake')) { $('#stake').value = String(st); renderTicket(); }
    const slip = $('#slip'); if (slip) slip.scrollIntoView({behavior: 'smooth', block: 'end'});
    toast('Pari ajouté au ticket : vérifie la mise puis enregistre-le');
  }));
}

/* ---------- Paris enregistrés ---------- */
function bets() { return read(BETS, []); }
function addBet(legs, stake, date) {
  const list = bets();
  list.unshift({id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), date, created: new Date().toISOString(),
                legs, total: totalOf(legs), stake, status: 'en_cours'});
  return write(BETS, list);
}

const STATUS = {en_cours: 'En cours', gagne: 'Gagné', perdu: 'Perdu', rembourse: 'Remboursé'};
const result = b => b.status === 'gagne' ? b.stake * b.total - b.stake : b.status === 'perdu' ? -b.stake : 0;
let lastRemoved = null;

function renderBets() {
  const body = $('#betsBody'); if (!body) return;
  const list = bets();
  body.innerHTML = !list.length ? '<tr><td colspan="7" class="empty">Aucun pari enregistré. Sélectionne tes matchs en bas des pages NBA ou Tennis.</td></tr>'
    : list.map(b => {
      const r = result(b), cls = r > 0 ? 'pos' : r < 0 ? 'neg' : '';
      const d = b.date ? b.date.split('-').reverse().join('/') : '';
      return `<tr><td class="n" data-l="Date">${esc(d)}</td>
        <td class="sel" data-l="Sélection">${b.legs.map(l => `<div><b>${esc(l.pick)}</b> <span class="sub">${l.opponent ? 'vs ' + esc(l.opponent) + ' · ' : ''}${fmt(l.odds)}</span></div>`).join('')}</td>
        <td class="n" data-l="Cote">${fmt(b.total)}</td><td class="n" data-l="Mise">${eur(b.stake)}</td>
        <td class="n" data-l="Gain possible">${eur(b.stake * b.total)}</td>
        <td data-l="Statut"><select data-id="${b.id}" aria-label="Statut du pari">${Object.entries(STATUS).map(([k, v]) => `<option value="${k}"${b.status === k ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
        <td class="n" data-l="Résultat"><span class="${cls}">${b.status === 'en_cours' ? '—' : (r > 0 ? '+' : '') + eur(r)}</span>
          <button class="btn ghost small" type="button" data-del="${b.id}" aria-label="Supprimer ce pari">✕</button></td></tr>`;
    }).join('');
  body.querySelectorAll('select').forEach(s => s.onchange = () => {
    const l = bets(), b = l.find(x => x.id === s.dataset.id); if (b) { b.status = s.value; write(BETS, l); renderBets(); }
  });
  body.querySelectorAll('[data-del]').forEach(btn => btn.onclick = () => {
    const l = bets(), i = l.findIndex(x => x.id === btn.dataset.del); if (i < 0) return;
    lastRemoved = {bet: l.splice(i, 1)[0], index: i}; write(BETS, l); renderBets();
    toast('Pari supprimé <button class="btn small" id="undo" type="button" style="margin-left:8px">Annuler</button>');
    $('#undo').onclick = () => { if (lastRemoved) { const l2 = bets(); l2.splice(lastRemoved.index, 0, lastRemoved.bet); lastRemoved = null; write(BETS, l2); renderBets(); } $('#toast').classList.remove('show'); };
  });
  renderStats(list);
}

function renderStats(list) {
  const done = list.filter(b => b.status === 'gagne' || b.status === 'perdu');
  const staked = list.reduce((s, b) => s + (b.status === 'rembourse' ? 0 : b.stake), 0);
  const net = list.reduce((s, b) => s + result(b), 0);
  const doneStake = done.reduce((s, b) => s + b.stake, 0);
  $('#sCount').textContent = list.length;
  $('#sPending').textContent = list.filter(b => b.status === 'en_cours').length;
  $('#sStake').textContent = eur(staked);
  const n = $('#sNet'); n.textContent = (net > 0 ? '+' : '') + eur(net); n.className = net > 0 ? 'pos' : net < 0 ? 'neg' : '';
  $('#sRate').textContent = done.length ? Math.round(100 * done.filter(b => b.status === 'gagne').length / done.length) + ' %' : '—';
  $('#sRoi').textContent = doneStake ? (net >= 0 ? '+' : '') + fmt(100 * net / doneStake) + ' %' : '—';
}

function initTracker() {
  if (!$('#betsBody')) return;
  $('#mDate').value = today();
  $('#manual').addEventListener('submit', ev => {
    ev.preventDefault();
    const pick = $('#mPick').value.trim(), odds = num($('#mOdds').value), st = num($('#mStake').value);
    if (!pick || !(odds > 1) || !(st > 0)) { toast('Renseigne la sélection, une cote supérieure à 1 et une mise'); return; }
    if (addBet([{sport: 'autre', competition: '', time: '', pick, opponent: $('#mOpp').value.trim(), odds}], st, $('#mDate').value || today())) toast('Pari ajouté');
    ev.target.reset(); $('#mDate').value = today(); renderBets();
  });
  $('#export').onclick = () => {
    const blob = new Blob([JSON.stringify({version: 1, exported: new Date().toISOString(), bets: bets()}, null, 1)], {type: 'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `mes-paris-${today()}.json`;
    document.body.appendChild(a); a.click(); a.remove(); toast('Sauvegarde téléchargée');
  };
  $('#importBtn').onclick = () => $('#importFile').click();
  $('#importFile').onchange = e => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const j = JSON.parse(r.result), list = Array.isArray(j) ? j : j.bets; if (!Array.isArray(list)) throw 0;
        const cur = bets(), known = new Set(cur.map(b => b.id)); let n = 0;
        for (const b of list) if (b && b.id && Array.isArray(b.legs) && !known.has(b.id)) { cur.push(b); n++; }
        cur.sort((a, b) => (b.date || '').localeCompare(a.date || '')); write(BETS, cur); renderBets(); toast(`${n} pari(s) importé(s)`);
      } catch (err) { toast('Fichier non reconnu'); }
    };
    r.readAsText(f); e.target.value = '';
  };
  renderBets();
}

document.addEventListener('DOMContentLoaded', () => {
  if ($('#date')) $('#date').value = today();
  if ($('#stake')) $('#stake').addEventListener('input', renderTicket);
  if ($('#clearSel')) $('#clearSel').onclick = () => setTicket([]);
  if ($('#addBet')) $('#addBet').onclick = () => {
    const st = num($('#stake').value), legs = ticket();
    if (!(st > 0) || !legs.length) return;
    if (addBet(legs, st, $('#date').value || today())) {
      $('#stake').value = ''; setTicket([]); renderBets();
      toast(`Pari enregistré · <a href="${$('#slip').dataset.paris || 'mes-paris.html'}">voir mes paris</a>`);
    }
  };
  initPicker(); markPicker(); renderTicket(); initTracker();
  window.addEventListener('storage', () => { markPicker(); renderTicket(); renderBets(); });   // autre onglet ouvert
});
})();
"""


def build_tracker_html() -> str:
    from web_report import CSS, FONTS, nav_tabs
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mes paris</title>{FONTS}<style>{CSS}{TRACKER_CSS}</style></head><body><main>
{nav_tabs("paris")}
<header class="top"><div class="kicker">Suivi personnel</div><h1>Mes paris</h1>
<p class="sub">Pour ajouter un pari : sélectionne tes matchs en bas des pages
<a href="index.html#ajouter">NBA</a> ou <a href="tennis.html#ajouter">Tennis</a>, puis indique ta mise.</p>
<div class="counts">
<div class="count"><b id="sCount">0</b><span>paris · <span id="sPending">0</span> en cours</span></div>
<div class="count"><b id="sNet">0,00 €</b><span>bénéfice net · misé <span id="sStake">0,00 €</span></span></div>
<div class="count"><b id="sRate">—</b><span>réussite · rentabilité <span id="sRoi">—</span></span></div></div>
</header>

<h2>Mon tableau</h2><p class="h2sub">Mets à jour le statut après le match : le bilan se calcule tout seul.</p>
<div class="card"><table class="bets"><thead><tr><th>Date</th><th>Sélection</th><th>Cote</th><th>Mise</th>
<th>Gain possible</th><th>Statut</th><th>Résultat</th></tr></thead><tbody id="betsBody"></tbody></table>
<div class="tools"><button class="btn" id="export" type="button">Exporter (sauvegarde)</button>
<button class="btn" id="importBtn" type="button">Importer</button>
<input type="file" id="importFile" accept="application/json,.json" hidden></div>
<p class="note">Tes paris sont enregistrés dans <b>ce navigateur</b> uniquement. Exporte-les de temps en temps,
et utilise « Importer » pour les retrouver sur un autre appareil.</p></div>

<h2>Ajouter un pari à la main</h2><p class="h2sub">Pour un match qui n'est pas proposé sur les pages NBA ou Tennis.</p>
<form class="card" id="manual"><div class="mrow">
<label class="w">Sélection (gagnant joué)<input id="mPick" placeholder="ex. Lorenzo Musetti"></label>
<label class="w">Contre (facultatif)<input id="mOpp"></label>
<label>Cote<input id="mOdds" inputmode="decimal" placeholder="1,61"></label>
<label>Mise (€)<input id="mStake" inputmode="decimal" placeholder="20"></label>
<label>Date<input id="mDate" type="date"></label>
<button class="btn main" type="submit">Ajouter</button></div></form>
{ticket_html()}
<footer>Suivi personnel, sans lien avec Unibet. Joue une mise fixe et raisonnable.<br>
Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé).</footer>
</main></body></html>"""


CHAT_CSS = """
.topic{width:100%}
textarea{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px 12px;width:100%;min-height:96px;resize:vertical}
textarea:focus{outline:2px solid var(--info);outline-offset:1px}
.sugg{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.sugg button{font:500 13px Inter,sans-serif;cursor:pointer;border:1px solid var(--line);background:var(--soft);
color:var(--ink);border-radius:999px;padding:6px 11px}
.sugg button:hover{border-color:var(--info);color:var(--info)}
pre.brief{white-space:pre-wrap;font:13px/1.5 Inter,sans-serif;color:var(--muted);background:var(--soft);
border-radius:10px;padding:10px 12px;margin:8px 0 0;max-height:280px;overflow:auto}
.count-chars{font-size:12px;color:var(--muted);margin-top:6px}
"""

CHAT_JS = r"""(function () {
const $ = s => document.querySelector(s);
const INTRO = %INTRO%, SITE = %SITE%, MAX = %MAX%;
const fmt = x => (Math.round(x * 100) / 100).toFixed(2).replace('.', ',');
let data = {nba: [], tennis: []};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function load() {
  for (const s of ['nba', 'tennis']) {
    try { const r = await fetch(`data/${s}_digest.json?t=${Date.now()}`); if (r.ok) data[s] = (await r.json()).matches || []; } catch (e) {}
  }
  const now = Date.now() - 3 * 3600e3;
  for (const s of ['nba', 'tennis']) data[s] = data[s].filter(m => new Date(m.time).getTime() > now);
  const sel = $('#topic');
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  const hh = iso => new Date(iso).toLocaleString('fr-FR', {weekday: 'short', hour: '2-digit', minute: '2-digit'});
  let html = '<optgroup label="Vue d\'ensemble">' + opt('free', 'Question libre (sans match précis)');
  if (data.nba.length) html += opt('all:nba', `Toute la nuit NBA (${data.nba.length} matchs)`);
  if (data.tennis.length) html += opt('all:tennis', `Tout le tennis à venir (${data.tennis.length} matchs)`);
  html += opt('mybets', 'Mes paris (mon bilan)') + '</optgroup>';
  const order = {'À jouer': 0, 'Validé': 1, 'Écarté': 2, 'En attente': 3};
  for (const [s, label] of [['nba', 'NBA'], ['tennis', 'Tennis']]) {
    if (!data[s].length) continue;
    const list = [...data[s]].sort((a, b) => (order[a.verdict] - order[b.verdict]) || a.time.localeCompare(b.time));
    html += `<optgroup label="${label}">` + list.map(m => opt(m.id, `${m.verdict === 'À jouer' ? '★ ' : ''}${m.label} · ${hh(m.time)} · ${m.verdict}`)).join('') + '</optgroup>';
  }
  sel.innerHTML = html;
  const best = [...data.nba, ...data.tennis].find(m => m.verdict === 'À jouer');
  const wanted = new URLSearchParams(location.search).get('match');
  sel.value = wanted && [...sel.options].some(o => o.value === wanted) ? wanted : (best ? best.id : 'free');
  update();
}

function myBets() {
  let bets = []; try { bets = JSON.parse(localStorage.getItem('mes_paris_v1') || '[]'); } catch (e) {}
  if (!Array.isArray(bets) || !bets.length) return "Je n'ai encore enregistré aucun pari.";
  const st = {en_cours: 'en cours', gagne: 'gagné', perdu: 'perdu', rembourse: 'remboursé'};
  const net = bets.reduce((s, b) => s + (b.status === 'gagne' ? b.stake * b.total - b.stake : b.status === 'perdu' ? -b.stake : 0), 0);
  const lines = bets.slice(0, 15).map(b => `${(b.date || '').split('-').reverse().join('/')} : ${b.legs.map(l => `${l.pick} ${fmt(l.odds)}`).join(' + ')} · cote ${fmt(b.total)} · mise ${fmt(b.stake)} € · ${st[b.status] || b.status}`);
  return `Mes paris enregistrés (${bets.length} au total, bénéfice net ${fmt(net)} €, ${bets.filter(b => b.status === 'gagne').length} gagnés, ${bets.filter(b => b.status === 'perdu').length} perdus) :\n` + lines.join('\n');
}

function context() {
  const v = $('#topic').value;
  if (v === 'free') return `Les analyses du jour de mon bot sont sur ${SITE}`;
  if (v === 'mybets') return myBets();
  if (v.startsWith('all:')) {
    const s = v.slice(4), list = data[s];
    const head = s === 'nba' ? 'Résumé de la nuit NBA selon mon bot (heures de Paris) :' : 'Résumé des matchs de tennis à venir selon mon bot (heures de Paris) :';
    let txt = head + '\n' + list.map(m => m.line).join('\n') + `\nAnalyses détaillées : ${SITE}`;
    return txt.length > 1600 ? txt.slice(0, 1597) + '…' : txt;
  }
  const m = [...data.nba, ...data.tennis].find(x => x.id === v);
  return m ? m.brief : '';
}

function buildPrompt() {
  const q = $('#question').value.trim() || $('#question').placeholder;
  let p = `${INTRO}\n\n${context()}\n\nMa question : ${q}`;
  if (p.length > MAX) p = p.slice(0, MAX - 1) + '…';
  return p;
}

function update() {
  $('#brief').textContent = context();
  const p = buildPrompt();
  $('#chars').textContent = `${p.length} caractères envoyés à Claude`;
}

document.addEventListener('DOMContentLoaded', () => {
  $('#topic').addEventListener('change', update);
  $('#question').addEventListener('input', update);
  document.querySelectorAll('.sugg button').forEach(b => b.onclick = () => { $('#question').value = b.textContent; update(); $('#question').focus(); });
  $('#ask').onclick = () => window.open('https://claude.ai/new?q=' + encodeURIComponent(buildPrompt()), '_blank', 'noopener');
  $('#copy').onclick = async () => {
    const t = $('#copyMsg');
    try { await navigator.clipboard.writeText(buildPrompt()); t.textContent = 'Question copiée : colle-la dans Claude.'; }
    catch (e) { t.textContent = 'Copie impossible ici : sélectionne le texte ci-dessus à la main.'; }
  };
  load();
});
})();
"""


def build_chat_html() -> str:
    import json
    import config
    from explain import INTRO, MAX_PROMPT
    from web_report import CSS, FONTS, nav_tabs
    js = (CHAT_JS.replace("%INTRO%", json.dumps(INTRO, ensure_ascii=False))
          .replace("%SITE%", json.dumps(config.SITE_URL)).replace("%MAX%", str(MAX_PROMPT)))
    sugg = ["Faut-il jouer ce match, et combien miser ?", "Quel est le vrai risque sur ce pari ?",
            "Y a-t-il des blessures ou des forfaits de dernière minute ?",
            "Explique-moi les cotes simplement", "Quel est le meilleur pari de la soirée ?",
            "Analyse mon bilan : est-ce que je mise trop ?"]
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chatbot paris</title>{FONTS}<style>{CSS}{TRACKER_CSS}{CHAT_CSS}</style></head><body><main>
{nav_tabs("chat")}
<header class="top"><div class="kicker">Chatbot · avec Claude</div><h1>Pose tes questions</h1>
<p class="sub">Choisis un match ou la soirée, écris ta question : Claude s'ouvre dans un nouvel onglet avec
l'analyse du bot déjà jointe. Il peut aussi chercher les dernières infos sur le web.</p></header>

<h2>1. De quoi veux-tu parler ?</h2>
<div class="card"><select id="topic" class="topic" aria-label="Sujet"><option>Chargement…</option></select>
<details><summary>Ce qui sera envoyé à Claude</summary><pre class="brief" id="brief"></pre></details></div>

<h2>2. Ta question</h2>
<div class="card"><textarea id="question" placeholder="{_e(sugg[0])}" aria-label="Ta question"></textarea>
<div class="sugg">{''.join(f'<button type="button">{_e(s)}</button>' for s in sugg)}</div>
<div class="actions"><button class="btn main" id="ask" type="button">Demander à Claude ↗</button>
<button class="btn" id="copy" type="button">Copier la question</button></div>
<p class="count-chars" id="chars"></p><p class="note" id="copyMsg"></p>
<p class="note">Il faut être connecté à ton compte Claude. Si la question n'est pas envoyée toute seule,
appuie sur Entrée dans Claude. Claude donne des explications, pas de garantie : garde des mises raisonnables.</p></div>
<footer>Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé).</footer>
</main><script>{js}</script></body></html>"""


def write_assets(out_dir: Path) -> None:
    """Écrit docs/paris.js, docs/mes-paris.html et docs/discuter.html."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "paris.js").write_text(JS, encoding="utf-8")
    (out_dir / "mes-paris.html").write_text(build_tracker_html(), encoding="utf-8")
    (out_dir / "discuter.html").write_text(build_chat_html(), encoding="utf-8")

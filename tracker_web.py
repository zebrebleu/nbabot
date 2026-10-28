"""
Onglet « Mes paris » : docs/mes-paris.html + docs/data/{nba,tennis}_picks.json.

Les matchs du moment sont exportés en JSON à chaque passage du bot ; la page les lit,
te laisse cliquer sur les équipes/joueurs joués, puis enregistre le pari dans ton navigateur
(localStorage), avec export/import pour sauvegarder ou changer d'appareil.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from web_report import CSS, FONTS, nav_tabs


def _verdict(e, legs) -> str:
    if e in legs:
        return "À jouer"
    return "Validé" if e.passed else "Écarté"


def export_picks(sport: str, evaluations, legs, out_dir: Path, generated_at: datetime) -> Path:
    """Écrit la liste des matchs avec cote Unibet (pour l'onglet Mes paris)."""
    items = []
    for e in evaluations:
        m = e.matchup
        if m.unibet is None or getattr(m, "state", "pre") != "pre":
            continue
        comp = getattr(m, "tournament", None) or "NBA"
        a, b = (m.away, m.home) if sport == "nba" else (m.home, m.away)
        oa, ob = (m.unibet.away, m.unibet.home) if sport == "nba" else (m.unibet.home, m.unibet.away)
        items.append({
            "id": f"{sport}:{m.event_id}",
            "sport": sport,
            "competition": comp,
            "time": m.commence_time.isoformat(),
            "label": f"{a.name} @ {b.name}" if sport == "nba" else f"{a.name} – {b.name}",
            "sides": [{"name": a.name, "odds": round(oa, 2)}, {"name": b.name, "odds": round(ob, 2)}],
            "pick": e.pick.name if e.pick else None,
            "verdict": _verdict(e, legs),
        })
    path = out_dir / "data" / f"{sport}_picks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": generated_at.isoformat(), "matches": items},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


TRACKER_CSS = """
.pickgrp{font:700 16px/1.2 var(--num);letter-spacing:.02em;color:var(--accent);margin:16px 0 6px}
.pickgrp:first-child{margin-top:0}
.pm{padding:10px 0;border-top:1px solid var(--line)}.pm:first-of-type{border-top:0}
.pm .meta{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted);margin-bottom:6px}
.sides{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.side{font:inherit;text-align:left;cursor:pointer;border:1.5px solid var(--line);background:var(--soft);
color:var(--ink);border-radius:10px;padding:9px 11px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.side b{font:700 18px/1 var(--num)}.side span{font-size:14px;overflow-wrap:anywhere}
.side:hover{border-color:var(--muted)}
.side.on{border-color:var(--go);background:var(--go-bg)}.side.on b{color:var(--go)}
.side.fav span{font-weight:600}
.slip{position:sticky;bottom:12px;z-index:5;border:2px solid var(--go);box-shadow:0 8px 30px rgba(0,0,0,.18)}
.slip .row{display:flex;flex-wrap:wrap;gap:10px;align-items:end}
.slip label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted);flex:1;min-width:120px}
input,select{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 10px}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--info);outline-offset:1px}
.btn{font:600 14px Inter,sans-serif;cursor:pointer;border-radius:10px;padding:10px 14px;border:1px solid var(--line);
background:var(--card);color:var(--ink)}
.btn.main{background:var(--go);border-color:var(--go);color:#fff}.btn.main:disabled{opacity:.45;cursor:not-allowed}
.btn.ghost{background:none}.btn.small{padding:6px 10px;font-size:13px}
.legs{margin:8px 0 10px;padding:0;list-style:none;font-size:14px}
.legs li{display:flex;justify-content:space-between;gap:8px;padding:3px 0}
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
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--ink);color:var(--bg);
padding:10px 16px;border-radius:10px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
.toast.show{opacity:1}
@media (max-width:600px){.sides{grid-template-columns:1fr}
.bets thead{display:none}.bets,.bets tbody,.bets tr,.bets td{display:block}
.bets tr{border-bottom:1px solid var(--line);padding:10px 0}.bets td{border:0;padding:2px 0}
.bets td[data-l]::before{content:attr(data-l);color:var(--muted);font-size:12px;margin-right:6px}}
"""

JS = r"""
const KEY = 'mes_paris_v1';
const $ = s => document.querySelector(s);
const fmt = x => (Math.round(x * 100) / 100).toFixed(2).replace('.', ',');
const eur = x => fmt(x) + ' €';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let bets = [], matches = [], sel = {};

function load() {
  try { bets = JSON.parse(localStorage.getItem(KEY) || '[]'); if (!Array.isArray(bets)) bets = []; }
  catch (e) { bets = []; }
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(bets)); return true; }
  catch (e) { toast("Impossible d'enregistrer dans ce navigateur (mode privé ?). Pense à exporter."); return false; }
}
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2600); }
function today() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
function hhmm(iso) { try { return new Date(iso).toLocaleString('fr-FR', {weekday:'short', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}); } catch (e) { return ''; } }

async function loadMatches() {
  const out = [];
  for (const s of ['nba', 'tennis']) {
    try {
      const r = await fetch(`data/${s}_picks.json?t=${Date.now()}`);
      if (r.ok) { const j = await r.json(); out.push(...(j.matches || [])); }
    } catch (e) {}
  }
  const now = Date.now() - 3 * 3600e3;
  matches = out.filter(m => new Date(m.time).getTime() > now).sort((a, b) => a.time.localeCompare(b.time));
  renderMatches();
}

function chipFor(v) {
  return v === 'À jouer' ? '<span class="chip go">À JOUER</span>' : v === 'Validé' ? '<span class="chip info">VALIDÉ</span>' : '<span class="chip off">ÉCARTÉ</span>';
}

function renderMatches() {
  const box = $('#matches');
  if (!matches.length) { box.innerHTML = '<p class="empty">Aucun match avec cote en ce moment. Utilise l\'ajout manuel plus bas.</p>'; return; }
  const groups = {};
  for (const m of matches) { const g = m.sport === 'nba' ? 'NBA' : m.competition; (groups[g] = groups[g] || []).push(m); }
  box.innerHTML = Object.entries(groups).map(([g, ms]) => `<div class="pickgrp">${esc(g)}</div>` + ms.map(m => `
    <div class="pm"><div class="meta"><span>${esc(hhmm(m.time))}</span>${chipFor(m.verdict)}</div>
    <div class="sides">${m.sides.map((s, i) => `<button type="button" class="side${s.name === m.pick ? ' fav' : ''}${sel[m.id] === i ? ' on' : ''}"
      data-id="${esc(m.id)}" data-i="${i}" aria-pressed="${sel[m.id] === i}"><span>${esc(s.name)}</span><b>${fmt(s.odds)}</b></button>`).join('')}</div></div>`).join('')).join('');
  box.querySelectorAll('.side').forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.id, i = +b.dataset.i;
    if (sel[id] === i) delete sel[id]; else sel[id] = i;
    renderMatches(); renderSlip();
  }));
}

function slipLegs() {
  return Object.entries(sel).map(([id, i]) => {
    const m = matches.find(x => x.id === id); if (!m) return null;
    const s = m.sides[i], o = m.sides[1 - i];
    return {sport: m.sport, competition: m.competition, time: m.time, pick: s.name, opponent: o.name, odds: s.odds};
  }).filter(Boolean);
}

function renderSlip() {
  const legs = slipLegs(), slip = $('#slip');
  slip.hidden = !legs.length;
  if (!legs.length) return;
  const total = Math.round(legs.reduce((p, l) => p * l.odds, 1) * 100) / 100;   // arrondi comme Unibet
  $('#slipKind').textContent = legs.length === 1 ? 'Pari simple' : `Combiné de ${legs.length} matchs`;
  $('#slipLegs').innerHTML = legs.map(l => `<li><span>${esc(l.pick)} <span class="sub">vs ${esc(l.opponent)}</span></span><b>${fmt(l.odds)}</b></li>`).join('');
  $('#slipTotal').textContent = fmt(total);
  const st = parseFloat(($('#stake').value || '').replace(',', '.'));
  $('#slipGain').textContent = st > 0 ? eur(st * total) : '—';
  $('#addBet').disabled = !(st > 0);
}

function addBet(legs, stake, date) {
  const total = legs.reduce((p, l) => p * l.odds, 1);
  bets.unshift({id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), date, created: new Date().toISOString(),
                legs, total: Math.round(total * 100) / 100, stake, status: 'en_cours'});
  if (save()) toast('Pari ajouté à ton suivi');
  renderBets();
}

const STATUS = {en_cours: 'En cours', gagne: 'Gagné', perdu: 'Perdu', rembourse: 'Remboursé'};
function result(b) {
  if (b.status === 'gagne') return b.stake * b.total - b.stake;
  if (b.status === 'perdu') return -b.stake;
  return 0;
}

function renderBets() {
  const body = $('#betsBody');
  if (!bets.length) { body.innerHTML = '<tr><td colspan="7" class="empty">Aucun pari enregistré pour l\'instant.</td></tr>'; }
  else body.innerHTML = bets.map(b => {
    const r = result(b), cls = r > 0 ? 'pos' : r < 0 ? 'neg' : '';
    const d = b.date ? b.date.split('-').reverse().join('/') : '';
    return `<tr>
      <td class="n" data-l="Date">${esc(d)}</td>
      <td class="sel" data-l="Sélection">${b.legs.map(l => `<div><b>${esc(l.pick)}</b> <span class="sub">${l.opponent ? 'vs ' + esc(l.opponent) + ' · ' : ''}${fmt(l.odds)}</span></div>`).join('')}</td>
      <td class="n" data-l="Cote">${fmt(b.total)}</td>
      <td class="n" data-l="Mise">${eur(b.stake)}</td>
      <td class="n" data-l="Gain possible">${eur(b.stake * b.total)}</td>
      <td data-l="Statut"><select data-id="${b.id}" aria-label="Statut du pari">${Object.entries(STATUS).map(([k, v]) => `<option value="${k}"${b.status === k ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
      <td class="n" data-l="Résultat"><span class="${cls}">${b.status === 'en_cours' ? '—' : (r > 0 ? '+' : '') + eur(r)}</span>
        <button class="btn ghost small" data-del="${b.id}" aria-label="Supprimer ce pari">✕</button></td></tr>`;
  }).join('');
  body.querySelectorAll('select').forEach(s => s.addEventListener('change', () => {
    const b = bets.find(x => x.id === s.dataset.id); if (b) { b.status = s.value; save(); renderBets(); }
  }));
  body.querySelectorAll('[data-del]').forEach(btn => btn.addEventListener('click', () => {
    const i = bets.findIndex(x => x.id === btn.dataset.del); if (i < 0) return;
    const [removed] = bets.splice(i, 1); save(); renderBets();
    lastRemoved = {bet: removed, index: i}; toastUndo('Pari supprimé');
  }));
  renderStats();
}
let lastRemoved = null;
function toastUndo(msg) {
  const t = $('#toast'); t.innerHTML = `${esc(msg)} <button class="btn small" id="undo" style="margin-left:8px">Annuler</button>`;
  t.classList.add('show'); t.style.pointerEvents = 'auto';
  $('#undo').onclick = () => { if (lastRemoved) { bets.splice(lastRemoved.index, 0, lastRemoved.bet); lastRemoved = null; save(); renderBets(); } t.classList.remove('show'); };
  setTimeout(() => { t.classList.remove('show'); t.style.pointerEvents = 'none'; }, 5000);
}

function renderStats() {
  const done = bets.filter(b => b.status === 'gagne' || b.status === 'perdu');
  const staked = bets.reduce((s, b) => s + (b.status === 'rembourse' ? 0 : b.stake), 0);
  const net = bets.reduce((s, b) => s + result(b), 0);
  const won = done.filter(b => b.status === 'gagne').length;
  const doneStake = done.reduce((s, b) => s + b.stake, 0);
  $('#sCount').textContent = bets.length;
  $('#sStake').textContent = eur(staked);
  const n = $('#sNet'); n.textContent = (net > 0 ? '+' : '') + eur(net); n.className = net > 0 ? 'pos' : net < 0 ? 'neg' : '';
  $('#sRate').textContent = done.length ? Math.round(100 * won / done.length) + ' %' : '—';
  $('#sRoi').textContent = doneStake ? (net >= 0 ? '+' : '') + fmt(100 * net / doneStake) + ' %' : '—';
  $('#sPending').textContent = bets.filter(b => b.status === 'en_cours').length;
}

function exportBets() {
  const blob = new Blob([JSON.stringify({version: 1, exported: new Date().toISOString(), bets}, null, 1)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `mes-paris-${today()}.json`;
  document.body.appendChild(a); a.click(); a.remove(); toast('Sauvegarde téléchargée');
}
function importBets(file) {
  const r = new FileReader();
  r.onload = () => {
    try {
      const j = JSON.parse(r.result), list = Array.isArray(j) ? j : j.bets;
      if (!Array.isArray(list)) throw 0;
      const known = new Set(bets.map(b => b.id)); let n = 0;
      for (const b of list) if (b && b.id && Array.isArray(b.legs) && !known.has(b.id)) { bets.push(b); n++; }
      bets.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
      save(); renderBets(); toast(`${n} pari(s) importé(s)`);
    } catch (e) { toast('Fichier non reconnu'); }
  };
  r.readAsText(file);
}

document.addEventListener('DOMContentLoaded', () => {
  load();
  $('#date').value = today(); $('#mDate').value = today();
  $('#stake').addEventListener('input', renderSlip);
  $('#addBet').addEventListener('click', () => {
    const st = parseFloat(($('#stake').value || '').replace(',', '.')); const legs = slipLegs();
    if (!(st > 0) || !legs.length) return;
    addBet(legs, st, $('#date').value || today()); sel = {}; $('#stake').value = ''; renderMatches(); renderSlip();
  });
  $('#clearSel').addEventListener('click', () => { sel = {}; renderMatches(); renderSlip(); });
  $('#manual').addEventListener('submit', ev => {
    ev.preventDefault();
    const pick = $('#mPick').value.trim(), odds = parseFloat($('#mOdds').value.replace(',', '.')),
          st = parseFloat($('#mStake').value.replace(',', '.'));
    if (!pick || !(odds > 1) || !(st > 0)) { toast('Renseigne la sélection, une cote > 1 et une mise'); return; }
    addBet([{sport: 'autre', competition: '', time: '', pick, opponent: $('#mOpp').value.trim(), odds}], st, $('#mDate').value || today());
    ev.target.reset(); $('#mDate').value = today();
  });
  $('#export').addEventListener('click', exportBets);
  $('#importBtn').addEventListener('click', () => $('#importFile').click());
  $('#importFile').addEventListener('change', e => { if (e.target.files[0]) importBets(e.target.files[0]); e.target.value = ''; });
  renderBets(); loadMatches();
});
"""


def build_html(root: str = "") -> str:
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mes paris</title>{FONTS}<style>{CSS}{TRACKER_CSS}</style></head><body><main>
{nav_tabs("paris", root)}
<header class="top"><div class="kicker">Suivi personnel</div><h1>Mes paris</h1>
<p class="sub">Clique sur les équipes ou joueurs que tu as joués, indique ta mise : le pari s'ajoute à ton tableau.</p>
<div class="counts">
<div class="count"><b id="sCount">0</b><span>paris · <span id="sPending">0</span> en cours</span></div>
<div class="count"><b id="sNet">0,00 €</b><span>bénéfice net · misé <span id="sStake">0,00 €</span></span></div>
<div class="count"><b id="sRate">—</b><span>réussite · rentabilité <span id="sRoi">—</span></span></div></div>
</header>

<h2>1. Choisis tes matchs</h2><p class="h2sub">Matchs du moment avec leur cote Unibet (NBA et tennis). Un clic = sélectionné.</p>
<div class="card" id="matches"><p class="empty">Chargement des matchs…</p></div>

<div class="card slip" id="slip" hidden>
<span class="chip go">TON TICKET</span> <b id="slipKind"></b>
<ul class="legs" id="slipLegs"></ul>
<div class="row">
<div><span class="sub">Cote totale</span><div class="tot" id="slipTotal">—</div></div>
<label>Mise (€)<input id="stake" inputmode="decimal" placeholder="ex. 20"></label>
<label>Date<input id="date" type="date"></label>
<div><span class="sub">Gain possible</span><div class="tot" id="slipGain">—</div></div>
</div>
<div class="tools"><button class="btn main" id="addBet" disabled>Ajouter le pari</button>
<button class="btn ghost" id="clearSel">Effacer la sélection</button></div></div>

<h2>2. Mon tableau</h2><p class="h2sub">Mets à jour le statut après le match : le bilan se calcule tout seul.</p>
<div class="card"><table class="bets"><thead><tr><th>Date</th><th>Sélection</th><th>Cote</th><th>Mise</th>
<th>Gain possible</th><th>Statut</th><th>Résultat</th></tr></thead><tbody id="betsBody"></tbody></table>
<div class="tools"><button class="btn" id="export">Exporter (sauvegarde)</button>
<button class="btn" id="importBtn">Importer</button><input type="file" id="importFile" accept="application/json,.json" hidden></div>
<p class="note">Tes paris sont enregistrés dans <b>ce navigateur</b> uniquement. Exporte-les de temps en temps,
et utilise « Importer » pour les retrouver sur un autre appareil.</p></div>

<h2>Ajouter un pari à la main</h2><p class="h2sub">Pour un match qui n'est pas dans la liste.</p>
<form class="card" id="manual"><div class="slip-row row" style="display:flex;flex-wrap:wrap;gap:10px;align-items:end">
<label style="flex:2;min-width:180px;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)">Sélection (gagnant joué)<input id="mPick" placeholder="ex. Lorenzo Musetti + Rafael Jodar"></label>
<label style="flex:2;min-width:160px;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)">Contre (facultatif)<input id="mOpp"></label>
<label style="flex:1;min-width:90px;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)">Cote<input id="mOdds" inputmode="decimal" placeholder="1,61"></label>
<label style="flex:1;min-width:90px;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)">Mise (€)<input id="mStake" inputmode="decimal" placeholder="20"></label>
<label style="flex:1;min-width:140px;display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)">Date<input id="mDate" type="date"></label>
<button class="btn main" type="submit">Ajouter</button></div></form>

<footer>Suivi personnel, sans lien avec Unibet. Joue une mise fixe et raisonnable.<br>
Joueurs Info Service : 09 74 75 13 13 (appel non surtaxé).</footer>
</main><div class="toast" id="toast" role="status" aria-live="polite"></div>
<script>{JS}</script></body></html>"""


def write_page(out_dir: Path) -> Path:
    page = out_dir / "mes-paris.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(build_html(), encoding="utf-8")
    return page

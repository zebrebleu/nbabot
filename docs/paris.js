(function () {
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

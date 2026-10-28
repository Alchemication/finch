// finch annotation page. Talks only to the local server that served it.
// Amounts arrive as integer minor units (for sorting and bar widths) and as
// text formatted by the server; this page never adds money up itself.

const TOKEN = document.querySelector('meta[name="finch-token"]').content;
const $ = (sel) => document.querySelector(sel);

const CHANNELS = {
  card: 'card', atm: 'cash', direct_debit: 'direct debit',
  transfer_out: 'transfer out', transfer_in: 'transfer in', fee: 'bank fee', other: 'other',
};
const SPEND_EXCLUDED = ['transfer-', 'income-'];
const isSpending = (slug) => !SPEND_EXCLUDED.some((p) => slug.startsWith(p));

const ui = {
  data: null,
  labels: {},          // slug → label
  view: 'review',
  focus: 0,
  selected: new Set(),
  search: '',
  category: '',
  sort: 'money',
  year: null,
  shown: [],
  drawerKey: null,
};

// ---- server --------------------------------------------------------------

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: { 'X-Finch-Token': TOKEN, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

async function load() {
  ui.data = await api('/api/state');
  ui.labels = Object.fromEntries(ui.data.categories.map((c) => [c.slug, c.label]));
  ui.labels.unclassified = 'Unclassified';
  if (!ui.year) ui.year = ui.data.years[ui.data.years.length - 1].label;
  renderAll();
}

// ---- helpers -------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

let toastTimer;
function toast(message, error = false) {
  const t = $('#toast');
  t.textContent = message;
  t.className = error ? 'toast error' : 'toast';
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, error ? 6000 : 2600);
}

const catLabel = (slug) => (slug === 'none' ? 'No category' : ui.labels[slug] || slug);

// ---- list ----------------------------------------------------------------

function inView(p) {
  if (ui.view === 'review') return !!p.proposal;
  if (ui.view === 'unclassified') return p.category === 'unclassified' && !p.proposal;
  return true;
}

function visiblePayees() {
  const q = ui.search.trim().toLowerCase();
  let list = ui.data.payees.filter(inView);
  if (ui.category) {
    list = list.filter((p) => (p.proposal ? p.proposal.category : p.category) === ui.category);
  }
  if (q) list = list.filter((p) => p.name.toLowerCase().includes(q) || p.key.toLowerCase().includes(q));
  const by = {
    money: (a, b) => b.moved_minor - a.moved_minor,
    recent: (a, b) => (b.last || '').localeCompare(a.last || ''),
    payments: (a, b) => b.payments - a.payments,
    name: (a, b) => a.name.localeCompare(b.name),
  }[ui.sort];
  return list.sort(by);
}

function categoryCell(p) {
  if (p.proposal) {
    const pr = p.proposal;
    return el('div', { class: 'cat' },
      el('span', { class: 'proposal', title: pr.note || '' },
        el('span', { class: 'label' }, catLabel(pr.category)),
        el('span', { class: `conf ${pr.confidence}` }, pr.confidence),
        el('button', { class: 'accept', title: 'Accept (a)', onclick: (e) => { e.stopPropagation(); accept([p.key]); } }, '✓'),
        el('button', { class: 'change', title: 'Choose another (c)', onclick: (e) => { e.stopPropagation(); choose(p, e.currentTarget); } }, '✎'),
      ));
  }
  let cls = 'cat-btn';
  let text = catLabel(p.category);
  let title = 'Choose a category (c)';
  if (p.decided) cls += ' decided';
  else if (p.category !== 'unclassified') { cls += ' by-channel'; title = 'Set by the payment type; choose to override'; }
  else { cls += ' unset'; text = 'Choose…'; }
  if (p.decided === 'none') { cls = 'cat-btn'; text = 'No category'; }
  return el('div', { class: 'cat' },
    el('button', { class: cls, title, onclick: (e) => { e.stopPropagation(); choose(p, e.currentTarget); } }, text));
}

function rowFor(p, index) {
  const checked = ui.selected.has(p.key);
  return el('li', {
    class: `row${index === ui.focus ? ' focused' : ''}`,
    'data-key': p.key,
    onclick: () => { ui.focus = index; markFocus(); },
  },
    el('span', { class: 'c-check' },
      el('input', { type: 'checkbox', checked, 'aria-label': `Select ${p.name}`, onclick: (e) => { e.stopPropagation(); toggleSelect(p.key); } })),
    el('div', { class: 'payee', onclick: () => openDrawer(p.key) },
      el('div', { class: 'payee-name', title: p.name }, p.name || p.key),
      el('div', { class: 'payee-meta' },
        el('span', { class: 'chip' }, CHANNELS[p.channel] || p.channel),
        p.mixed ? el('span', { class: 'chip mixed', title: 'Some payments are labelled differently' }, 'mixed') : null,
        p.proposal && p.proposal.note ? el('span', { class: 'note-hint' }, p.proposal.note) : null)),
    el('span', { class: 'c-num' }, p.payments),
    el('span', { class: 'c-num out' }, p.out.minor ? p.out.text : el('span', { class: 'muted' }, '—')),
    el('span', { class: 'c-num in' }, p.in.minor ? p.in.text : el('span', { class: 'muted' }, '—')),
    el('span', { class: 'c-date' }, p.last || ''),
    categoryCell(p),
  );
}

function renderList() {
  ui.shown = visiblePayees();
  if (ui.focus >= ui.shown.length) ui.focus = Math.max(0, ui.shown.length - 1);
  const rows = $('#rows');
  rows.replaceChildren(...ui.shown.map(rowFor));
  const empty = $('#empty');
  rows.hidden = ui.shown.length === 0;
  $('.list-head').hidden = ui.shown.length === 0;
  empty.hidden = ui.shown.length !== 0;
  if (!ui.shown.length) {
    empty.replaceChildren(
      el('strong', {}, ui.view === 'review' ? 'Nothing waiting for review' : 'Nothing here'),
      ui.view === 'review' ? 'Every proposal has been decided. Check the Unclassified tab for the rest.' : 'Try another filter.');
  }
  const highShown = ui.view === 'review' && ui.shown.some((p) => p.proposal && p.proposal.confidence === 'high');
  $('#accept-high').hidden = !highShown;
  $('#accept-selected').hidden = ui.selected.size === 0;
  $('#accept-selected').textContent = `Accept selected (${ui.selected.size})`;
  $('#select-all').checked = ui.shown.length > 0 && ui.shown.every((p) => ui.selected.has(p.key));
}

function markFocus(scroll = false) {
  document.querySelectorAll('.row').forEach((r, i) => r.classList.toggle('focused', i === ui.focus));
  if (scroll) {
    const row = document.querySelectorAll('.row')[ui.focus];
    if (row) row.scrollIntoView({ block: 'nearest' });
  }
}

function toggleSelect(key) {
  if (ui.selected.has(key)) ui.selected.delete(key); else ui.selected.add(key);
  renderList();
}

// ---- header, tabs --------------------------------------------------------

function renderHeader() {
  const d = ui.data;
  const c = d.coverage;
  $('#range').textContent = `${d.from} → ${d.to}`;
  $('#meter-fill').style.width = `${c.classified_permille / 10}%`;
  $('#coverage-text').replaceChildren(
    el('strong', {}, `${(c.classified_permille / 10).toFixed(1)}%`), ' of money out has a category · ',
    el('span', { class: 'amber' }, c.unclassified.text), ' unclassified · ',
    el('strong', {}, c.proposals), ' to review');
  const counts = { review: 0, unclassified: 0, all: d.payees.length };
  for (const p of d.payees) {
    if (p.proposal) counts.review++;
    else if (p.category === 'unclassified') counts.unclassified++;
  }
  for (const [k, v] of Object.entries(counts)) $(`#count-${k}`).textContent = v;
  const sel = $('#filter-category');
  if (sel.options.length === 1) {
    for (const c2 of d.categories) sel.append(el('option', { value: c2.slug }, c2.label));
    sel.append(el('option', { value: 'unclassified' }, 'Unclassified'));
  }
}

function setView(view) {
  ui.view = view;
  ui.focus = 0;
  ui.selected.clear();
  document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.view === view)));
  $('#list-view').hidden = view === 'insights';
  $('#insights-view').hidden = view !== 'insights';
  if (!ui.data) return;
  if (view === 'insights') renderInsights(); else renderList();
  try { localStorage.setItem('finch.view', view); } catch { /* storage may be blocked */ }
  history.replaceState(null, '', `${location.pathname}${location.search}#${view}`);
}

function renderAll() {
  renderHeader();
  if (ui.view === 'insights') renderInsights(); else renderList();
  if (ui.drawerKey) openDrawer(ui.drawerKey, true);
}

// ---- actions -------------------------------------------------------------

async function run(work, message) {
  try {
    await work();
    toast(message);
    await load();
  } catch (err) {
    toast(err.message, true);
  }
}

function fadeOut(keys) {
  if (ui.view === 'all') return;
  document.querySelectorAll('.row').forEach((r) => { if (keys.includes(r.dataset.key)) r.classList.add('leaving'); });
}

function accept(keys) {
  if (!keys.length) return;
  fadeOut(keys);
  keys.forEach((k) => ui.selected.delete(k));
  const one = ui.data.payees.find((p) => p.key === keys[0]);
  const message = keys.length === 1 && one
    ? `${one.name} → ${catLabel(one.proposal.category)}`
    : `Accepted ${keys.length} payees`;
  run(() => api('/api/confirm', { keys }), message);
}

function decide(p, slug) {
  fadeOut([p.key]);
  run(() => api('/api/decide', { key: p.key, category: slug }), `${p.name} → ${catLabel(slug)}`);
}

// ---- category picker -----------------------------------------------------

const picker = { onPick: null, items: [], active: 0 };

function choose(p, anchor) {
  openPicker(anchor, p.proposal ? p.proposal.category : p.category, (slug) => decide(p, slug));
}

function openPicker(anchor, current, onPick) {
  picker.onPick = onPick;
  const box = $('#picker');
  box.hidden = false;
  const r = anchor.getBoundingClientRect();
  const top = Math.min(r.bottom + 6, window.innerHeight - 420);
  box.style.top = `${Math.max(8, top)}px`;
  box.style.left = `${Math.min(r.left, window.innerWidth - 300)}px`;
  const input = $('#picker-input');
  input.value = '';
  renderPicker(current);
  input.focus();
}

function renderPicker(current) {
  const q = $('#picker-input').value.trim().toLowerCase();
  const all = [...ui.data.categories, { slug: 'none', label: 'No category (keep unclassified)' }];
  picker.items = all.filter((c) => !q || c.label.toLowerCase().includes(q) || c.slug.includes(q));
  if (current !== undefined) {
    const i = picker.items.findIndex((c) => c.slug === current);
    picker.active = i >= 0 ? i : 0;
  }
  picker.active = Math.min(picker.active, Math.max(0, picker.items.length - 1));
  $('#picker-list').replaceChildren(...picker.items.map((c, i) => el('li', {
    class: `${i === picker.active ? 'active' : ''}${c.slug === 'none' ? ' none' : ''}`,
    role: 'option',
    onmousedown: (e) => { e.preventDefault(); pick(c.slug); },
  }, el('span', {}, c.label), c.slug === 'none' ? null : el('span', { class: 'slug' }, c.slug))));
  const active = $('#picker-list').children[picker.active];
  if (active) active.scrollIntoView({ block: 'nearest' });
}

function pick(slug) {
  closePicker();
  if (picker.onPick) picker.onPick(slug);
}

function closePicker() {
  $('#picker').hidden = true;
}

$('#picker-input').addEventListener('input', () => { picker.active = 0; renderPicker(); });
$('#picker-input').addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { picker.active = Math.min(picker.active + 1, picker.items.length - 1); renderPicker(); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { picker.active = Math.max(picker.active - 1, 0); renderPicker(); e.preventDefault(); }
  else if (e.key === 'Enter') { const item = picker.items[picker.active]; if (item) pick(item.slug); e.preventDefault(); }
  else if (e.key === 'Escape') { closePicker(); e.preventDefault(); e.stopPropagation(); }
});
$('#picker-input').addEventListener('blur', () => setTimeout(closePicker, 120));

// ---- drawer --------------------------------------------------------------

async function openDrawer(key, refresh = false) {
  const p = ui.data.payees.find((x) => x.key === key);
  if (!p) { closeDrawer(); return; }
  ui.drawerKey = key;
  $('#drawer').hidden = false;
  $('#scrim').hidden = false;
  $('#drawer-name').textContent = p.name || p.key;
  $('#drawer-sub').textContent = `${p.payments} payments · ${p.out.text} out${p.in.minor ? ` · ${p.in.text} in` : ''} · ${p.first} to ${p.last} · key ${p.key}`;
  const shown = p.proposal ? p.proposal.category : p.category;
  $('#drawer-picker').replaceChildren(el('button', {
    class: `cat-btn${p.decided ? ' decided' : shown === 'unclassified' ? ' unset' : ''}`,
    onclick: (e) => openPicker(e.currentTarget, shown, (slug) => decide(p, slug)),
  }, shown === 'unclassified' ? 'Choose…' : catLabel(shown) + (p.proposal ? ' (proposed)' : '')));
  if (!refresh) $('#drawer-tx').replaceChildren(el('li', {}, el('span', { class: 'muted' }, 'Loading…')));
  try {
    const { transactions } = await api(`/api/payee?key=${encodeURIComponent(key)}`);
    $('#drawer-tx').replaceChildren(...transactions.map((t) => txRow(t)));
  } catch (err) {
    toast(err.message, true);
  }
}

function txRow(t) {
  const badge = { label: 'label', rule: 'payee', channel: 'type', none: '' }[t.basis];
  const note = el('input', {
    type: 'text', value: t.note || '', placeholder: 'What was it? (saved with a label)',
    onkeydown: (e) => { if (e.key === 'Enter') e.currentTarget.blur(); },
    onchange: (e) => saveLabel(t, t.category === 'unclassified' ? null : t.category, e.currentTarget.value),
  });
  return el('li', {},
    el('span', { class: 'date' }, t.date),
    el('span', { class: 'text', title: t.text }, t.text, t.foreign ? el('span', { class: 'muted' }, ` · ${t.foreign}`) : null),
    el('span', { class: `amt${t.amount.minor > 0 ? ' in' : ''}` }, t.amount.text),
    el('div', { class: 'controls' },
      el('button', {
        class: `cat-btn${t.basis === 'label' ? ' decided' : t.category === 'unclassified' ? ' unset' : ' by-channel'}`,
        title: 'Label this payment only',
        onclick: (e) => openPicker(e.currentTarget, t.category, (slug) => saveLabel(t, slug, note.value)),
      }, t.category === 'unclassified' ? 'Label…' : catLabel(t.category)),
      badge ? el('span', { class: `badge ${t.basis}` }, badge) : null,
      note));
}

function saveLabel(t, slug, note) {
  if (!slug) { toast('Choose a category for this payment first, then add the note.', true); return; }
  run(() => api('/api/label', { ids: [t.id], category: slug, note: note || null }),
    `Payment of ${t.amount.text} on ${t.date} → ${catLabel(slug)}`);
}

function closeDrawer() {
  ui.drawerKey = null;
  $('#drawer').hidden = true;
  $('#scrim').hidden = true;
}

$('#drawer-close').addEventListener('click', closeDrawer);
$('#scrim').addEventListener('click', closeDrawer);

// ---- insights ------------------------------------------------------------

function spark(slug) {
  const values = ui.data.months.map((m) => {
    const t = m.totals.find((x) => x.category === slug);
    if (!t) return 0;
    return slug === 'unclassified' ? t.out.minor : Math.max(0, t.net_out.minor);
  });
  const max = Math.max(...values, 1);
  const w = 170; const h = 28; const step = values.length > 1 ? w / (values.length - 1) : w;
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`).join(' ');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'spark');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', points);
  svg.append(line);
  const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
  title.textContent = `${ui.data.months[0].label} to ${ui.data.months[ui.data.months.length - 1].label}`;
  svg.append(title);
  return svg;
}

function renderInsights() {
  const d = ui.data;
  const period = d.years.find((y) => y.label === ui.year) || d.years[d.years.length - 1];
  $('#year-seg').replaceChildren(...d.years.map((y) => el('button', {
    'aria-pressed': String(y.label === period.label),
    onclick: () => { ui.year = y.label; renderInsights(); },
  }, y.label)));
  $('#year-note').textContent = period.partial
    ? `Partial year: ${period.from} to ${period.to} (${period.days} days)`
    : `${period.from} to ${period.to}`;

  const topLabel = period.top ? catLabel(period.top.category) : '—';
  $('#cards').replaceChildren(
    el('div', { class: 'card' }, el('div', { class: 'k' }, 'Spent'), el('div', { class: 'v' }, period.spend.text),
      el('div', { class: 's' }, `about ${period.spend_per_month.text} a month`)),
    el('div', { class: 'card amber' }, el('div', { class: 'k' }, 'Not yet named'), el('div', { class: 'v' }, period.unclassified_out.text),
      el('div', { class: 's' }, 'counted as spending until named')),
    el('div', { class: 'card' }, el('div', { class: 'k' }, 'Biggest category'), el('div', { class: 'v' }, topLabel),
      el('div', { class: 's' }, period.top ? period.top.net_out.text : '')),
    el('div', { class: 'card' }, el('div', { class: 'k' }, 'Money in'), el('div', { class: 'v' }, period.money_in.text),
      el('div', { class: 's' }, 'salary, refunds, transfers')),
  );

  const amount = (t) => (t.category === 'unclassified' ? t.out : t.net_out);
  const spendItems = period.totals.filter((t) => isSpending(t.category)).sort((a, b) => amount(b).minor - amount(a).minor);
  const otherItems = period.totals.filter((t) => !isSpending(t.category)).sort((a, b) => Math.abs(b.net_out.minor) - Math.abs(a.net_out.minor));
  const spendMax = Math.max(...spendItems.map((t) => amount(t).minor), 1);
  const otherMax = Math.max(...otherItems.map((t) => Math.abs(t.net_out.minor)), 1);

  // Widths go through the CSSOM: the page's CSP forbids inline style attributes.
  const track = (pct) => {
    const fill = el('div', { class: 'fill' });
    fill.style.width = `${pct}%`;
    return el('div', { class: 'track' }, fill);
  };
  const bar = (t, max, total) => {
    const a = amount(t);
    const pct = total ? Math.round((a.minor / total) * 100) : 0;
    return el('li', {
      class: `bar${t.category === 'unclassified' ? ' unclassified' : ''}${a.minor < 0 ? ' negative' : ''}`,
      title: `${t.payments} payments · ${t.out.text} out · ${t.in.text} in`,
      onclick: () => {
        ui.category = t.category; $('#filter-category').value = t.category;
        setView(t.category === 'unclassified' ? 'unclassified' : 'all');
      },
    },
      el('span', { class: 'lbl' }, catLabel(t.category)),
      track(Math.min(100, (Math.abs(a.minor) / max) * 100)),
      el('span', { class: 'amt' }, a.text),
      el('span', { class: 'pct' }, total && a.minor > 0 ? `${pct}%` : ''),
      spark(t.category));
  };
  $('#bars-spend').replaceChildren(...spendItems.map((t) => bar(t, spendMax, period.spend.minor)));
  $('#bars-other').replaceChildren(...otherItems.map((t) => bar(t, otherMax, 0)));
  $('#bars-other').hidden = otherItems.length === 0;
  $('#other-title').hidden = otherItems.length === 0;
}

// ---- wiring --------------------------------------------------------------

document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => setView(t.dataset.view)));
$('#search').addEventListener('input', (e) => { ui.search = e.target.value; ui.focus = 0; renderList(); });
$('#filter-category').addEventListener('change', (e) => { ui.category = e.target.value; ui.focus = 0; renderList(); });
$('#sort').addEventListener('change', (e) => { ui.sort = e.target.value; renderList(); });
$('#select-all').addEventListener('change', (e) => {
  for (const p of ui.shown) { if (e.target.checked) ui.selected.add(p.key); else ui.selected.delete(p.key); }
  renderList();
});
$('#accept-selected').addEventListener('click', () => {
  const keys = ui.shown.filter((p) => ui.selected.has(p.key) && p.proposal).map((p) => p.key);
  if (!keys.length) { toast('None of the selected payees has a proposal to accept.', true); return; }
  accept(keys);
});
$('#accept-high').addEventListener('click', () => {
  const keys = ui.shown.filter((p) => p.proposal && p.proposal.confidence === 'high').map((p) => p.key);
  accept(keys);
});
$('#help-toggle').addEventListener('click', () => { $('#help').hidden = !$('#help').hidden; });

document.addEventListener('keydown', (e) => {
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === 'Escape') {
    if (!$('#picker').hidden) closePicker();
    else if (!$('#help').hidden) $('#help').hidden = true;
    else if (ui.drawerKey) closeDrawer();
    else if (typing) document.activeElement.blur();
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === '?') { $('#help').hidden = !$('#help').hidden; return; }
  if (['1', '2', '3', '4'].includes(e.key)) { setView(['review', 'unclassified', 'all', 'insights'][Number(e.key) - 1]); return; }
  if (ui.view === 'insights' || ui.drawerKey) return;
  const p = ui.shown[ui.focus];
  switch (e.key) {
    case 'j': case 'ArrowDown': ui.focus = Math.min(ui.focus + 1, ui.shown.length - 1); markFocus(true); e.preventDefault(); break;
    case 'k': case 'ArrowUp': ui.focus = Math.max(ui.focus - 1, 0); markFocus(true); e.preventDefault(); break;
    case '/': $('#search').focus(); e.preventDefault(); break;
    case 'a': if (p && p.proposal) accept([p.key]); break;
    case 'n': if (p) decide(p, 'none'); break;
    case 'x': if (p) toggleSelect(p.key); break;
    case 'c': {
      const row = document.querySelectorAll('.row')[ui.focus];
      if (p && row) choose(p, row.querySelector('.cat-btn, .change'));
      e.preventDefault();
      break;
    }
    case 'o': case 'Enter': if (p) openDrawer(p.key); break;
    default: break;
  }
});

const VIEWS = ['review', 'unclassified', 'all', 'insights'];
const fromHash = location.hash.slice(1);
if (VIEWS.includes(fromHash)) ui.view = fromHash;
else {
  try { ui.view = localStorage.getItem('finch.view') || 'review'; } catch { ui.view = 'review'; }
  if (!VIEWS.includes(ui.view)) ui.view = 'review';
}
setView(ui.view);
load().then(() => setView(ui.view)).catch((err) => toast(err.message, true));

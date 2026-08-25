/* Sentinel console. One SSE stream in, two panels out. */

const $ = (id) => document.getElementById(id);
let STATE = null, CFG = null, tableView = false, openCell = null, prevAlert = new Set();

/* ---------- deviation scale ------------------------------------------------
   Diverging: red arm = below baseline, neutral = within noise, one blue step
   above. Colour encodes deviation, never the raw rate -- a 94% cell can be
   perfectly healthy at 3am and a fire at 2pm, and only deviation knows which. */
const SCALE = [
  { max: -6,       bg: '#c22f2f', ink: '#fff', label: 'Severe' },
  { max: -4,       bg: '#a53230', ink: '#fff', label: '' },
  { max: -3,       bg: '#7d332e', ink: '#f6e6e4', label: '' },
  { max: -2,       bg: '#4a2f2b', ink: '#e8ddda', label: 'Drifting' },
  { max:  2,       bg: '#242423', ink: '#c3c2b7', label: 'Normal' },
  { max:  Infinity,bg: '#1e3a5c', ink: '#cfe0f2', label: 'Above' },
];
const band = (z) => SCALE.find((s) => z < s.max) || SCALE[SCALE.length - 1];

const pct = (v, d = 1) => (v == null ? '—' : (v * 100).toFixed(d) + '%');
const num = (v) => (v == null ? '—' : v.toLocaleString('en-IN'));
const hhmm = (iso) => new Date(iso).toLocaleTimeString('en-IN',
  { hour: '2-digit', minute: '2-digit', hour12: false });

/* ---------- KPI strip ---------- */
function renderKpis(k) {
  const delta = (k.success_rate - k.expected_rate).toFixed(2);
  const good = delta >= -0.25;
  const saved = k.mttd_minutes != null
    ? Math.max(0, k.manual_mttd_minutes - k.mttd_minutes).toFixed(0) : null;
  const cards = [
    { label: 'Live success rate', value: k.success_rate.toFixed(2), unit: '%',
      note: `<b class="${good ? 'up' : 'down'}">${delta > 0 ? '+' : ''}${delta}pp</b> vs baseline for this hour` },
    { label: 'Throughput', value: num(k.tpm), unit: 'txn/min',
      note: `across ${k.slices_watched} monitored slices` },
    { label: 'Open incidents', value: k.open_incidents, unit: '',
      note: k.open_incidents ? 'agent is mitigating' : 'all rails within baseline' },
    { label: 'Mean time to detect', value: k.mttd_minutes == null ? '—' : k.mttd_minutes,
      unit: k.mttd_minutes == null ? '' : 'min',
      note: k.mttd_minutes == null ? 'no detections this session'
        : `<b class="up">${saved} min faster</b> than a ~${k.manual_mttd_minutes} min human rota` },
    { label: 'Failures prevented', value: num(k.failures_avoided), unit: 'txn',
      note: 'conservative, counted only while incidents were open' },
    { label: 'Autonomous actions', value: k.autonomous_actions, unit: '',
      note: 'routing changes applied without a human, all reversible' },
  ];
  $('kpis').innerHTML = cards.map((c) => `
    <div class="kpi">
      <div class="label">${c.label}</div>
      <div class="value mono">${c.value}<span class="unit">${c.unit}</span></div>
      <div class="note">${c.note}</div>
    </div>`).join('');
}

/* ---------- heatmap ---------- */
function sparkPath(series, w, h) {
  const pts = series.filter((v) => v != null);
  if (pts.length < 2) return '';
  const lo = Math.min(...pts), hi = Math.max(...pts);
  const span = Math.max(hi - lo, 0.01);
  return pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * w;
    const y = h - ((v - lo) / span) * h;
    return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

function renderGrid(s) {
  if (tableView) return renderTable(s);
  const byKey = {};
  s.grid.forEach((c) => { byKey[c.bank + '|' + c.method] = c; });
  const head = `<tr><th class="rowh"></th>${s.methods.map((m) =>
    `<th>${m}</th>`).join('')}</tr>`;
  const rows = s.banks.map((b) => `
    <tr><th class="rowh">${b}</th>${s.methods.map((m) => {
      const c = byKey[b + '|' + m];
      const bnd = band(c.z);
      const alerting = c.z <= -3.5;
      const key = b + '|' + m;
      const fresh = alerting && !prevAlert.has(key);
      const flag = (s.incident_slices || {})[b + '/' + m];
      const dv = c.drop_pp == null ? '' :
        (c.drop_pp > 0 ? `−${c.drop_pp.toFixed(1)}pp` : `+${Math.abs(c.drop_pp).toFixed(1)}pp`);
      return `<td style="padding:0">
        <div class="cell${fresh ? ' alert' : ''}${flag ? ' flagged' : ''}${
            flag && flag.status === 'mitigating' ? ' mitigating' : ''}" tabindex="0" role="button"
             data-bank="${b}" data-method="${m}"
             style="background:${bnd.bg};color:${bnd.ink}"
             aria-label="${b} ${m}, ${pct(c.p)}, ${dv} versus baseline">
          ${alerting || flag ? '<span class="flag" aria-hidden="true">▼</span>' : ''}
          ${flag ? `<span class="inc-id">${flag.id}</span>` : ''}
          <div class="rate">${c.p == null ? '—' : (c.p * 100).toFixed(1)}</div>
          <div class="delta">${dv}</div>
          <svg class="spark" viewBox="0 0 100 16" preserveAspectRatio="none" aria-hidden="true">
            <path d="${sparkPath(c.spark, 100, 16)}" fill="none"
                  stroke="${bnd.ink}" stroke-opacity=".5" stroke-width="1.4"
                  vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
          </svg>
        </div></td>`;
    }).join('')}</tr>`).join('');
  $('hmwrap').innerHTML = `<table class="hm"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  prevAlert = new Set(s.grid.filter((c) => c.z <= -3.5).map((c) => c.bank + '|' + c.method));
  bindCells();
}

function renderTable(s) {
  const rows = [...s.grid].sort((a, b) => a.z - b.z).map((c) => `
    <tr><td class="name">${c.bank}</td><td class="name">${c.method}</td>
      <td>${pct(c.p)}</td><td>${pct(c.p0)}</td>
      <td style="color:${c.z <= -3.5 ? '#f08a8a' : 'var(--ink-2)'}">${c.z.toFixed(2)}</td>
      <td>${num(c.n)}</td><td class="name">${c.top_error || '—'}</td></tr>`).join('');
  $('hmwrap').innerHTML = `<table class="grid-table">
    <thead><tr><th>Issuer</th><th>Method</th><th>Success</th><th>Expected</th>
      <th>Deviation (z)</th><th>Volume (3 min)</th><th>Top decline code</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderLegend() {
  const steps = [
    ['#c22f2f', '≤ −6'], ['#a53230', '−6'], ['#7d332e', '−4'],
    ['#4a2f2b', '−3'], ['#242423', '−2 … 2'], ['#1e3a5c', '> 2'],
  ];
  $('legend').innerHTML = `
    <span class="lbl">Deviation from baseline (σ)</span>
    <span class="scale">${steps.map(([c, l]) =>
      `<span style="display:flex;flex-direction:column;align-items:center;gap:3px">
         <span class="swatch" style="background:${c}"></span>
         <span class="lbl" style="font-size:9.5px;font-family:var(--mono)">${l}</span>
       </span>`).join('')}</span>
    <span class="lbl">worse ⟵&nbsp;&nbsp;⟶ better</span>
    <span class="lbl" style="margin-left:auto">▼ flagged by the agent · colour encodes
      deviation, never the raw rate</span>`;
}

function bindCells() {
  document.querySelectorAll('.cell').forEach((el) => {
    el.addEventListener('click', () => openDrawer(el.dataset.bank, el.dataset.method));
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
    });
    el.addEventListener('mousemove', (e) => showTip(e, el));
    el.addEventListener('mouseleave', hideTip);
  });
}

/* ---------- tooltip ---------- */
function showTip(e, el) {
  const c = STATE.grid.find((g) => g.bank === el.dataset.bank && g.method === el.dataset.method);
  if (!c) return;
  const t = $('tip');
  t.innerHTML = `<b>${c.bank} · ${c.method}</b><br>
    Success ${pct(c.p)} · expected ${pct(c.p0)}<br>
    Deviation <b>z = ${c.z.toFixed(2)}</b> · ${num(c.n)} txn in 3 min<br>
    ${c.excess_failures ? `<b>${num(c.excess_failures)}</b> failures above normal<br>` : ''}
    <span style="color:var(--muted)">Top decline: ${c.top_error || '—'} · click to drill in</span>`;
  t.classList.add('on');
  const r = t.getBoundingClientRect();
  t.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 12) + 'px';
  t.style.top = Math.min(e.clientY + 14, innerHeight - r.height - 12) + 'px';
}
const hideTip = () => $('tip').classList.remove('on');

/* ---------- activity ---------- */
function renderActivity(items) {
  $('activity').innerHTML = items.map((a) => `
    <div class="act">
      <span class="ts">${hhmm(a.ts)}</span>
      <span class="tag ${a.kind}">${a.kind}</span>
      <span class="txt">${a.text}</span>
    </div>`).join('') || '<div class="empty">Warming up…</div>';
}

/* ---------- incident feed ---------- */
function renderFeed(incidents) {
  if (!incidents.length) {
    $('feed').innerHTML = `<div class="empty">No incidents.<br>
      The agent is watching ${STATE.kpis.slices_watched} slices and will speak
      only when something deviates from its own baseline.</div>`;
    return;
  }
  $('feed').innerHTML = incidents.map((i) => {
    const n = i.narrative || {};
    const resolved = i.status === 'resolved';
    const sev = resolved ? 'resolved' : i.severity;
    const icon = { critical: '●', serious: '●', warning: '●', resolved: '✓' }[sev];
    const body = n.summary
      ? `<p>${n.summary}</p>`
      : `<p class="thinking">Diagnosing<i></i><i></i><i></i></p>`;
    const rec = n.recommendation ? `<div class="rec">
        <span class="k">${i.mitigation ? 'Action taken' : 'Recommended'}</span>
        <span>${i.mitigation
          ? `Rerouted ${i.mitigation.method} off ${i.mitigation.moved_off} → ${i.mitigation.moved_to.join(', ')} (3% canary retained)`
          : n.recommendation}</span></div>` : '';
    const extra = i.affected && i.affected.length > 1
      ? `<span class="chip status">${i.affected.length} slices</span>` : '';
    return `<article class="inc ${resolved ? 'resolved' : i.severity}" data-inc="${i.id}"
              data-bank="${i.bank}" data-method="${i.method}">
      <div class="row1">
        <span class="chip ${sev}">${icon} ${resolved ? 'Resolved' : i.severity}</span>
        <span class="chip status">${i.status}</span>${extra}
        <span class="id">${i.id}</span>
        <span class="when">${hhmm(i.opened_at)}${i.detection_latency_min != null
          ? ` · detected in ${i.detection_latency_min} min` : ''}</span>
      </div>
      <h3>${n.headline || `${i.bank} ${i.method} deviating from baseline`}</h3>
      ${body}${rec}
    </article>`;
  }).join('');
  document.querySelectorAll('.inc').forEach((el) =>
    el.addEventListener('click', () => openDrawer(el.dataset.bank, el.dataset.method)));
}

/* ---------- drawer ---------- */
async function openDrawer(bank, method) {
  openCell = { bank, method };
  $('scrim').classList.add('on');
  $('drawer').classList.add('on');
  $('drawer').setAttribute('aria-hidden', 'false');
  $('dtitle').innerHTML = `<h2 style="font-size:16px">${bank} · ${method}</h2>
    <div style="color:var(--muted);font-size:12px">Loading slice detail…</div>`;
  $('dbody').innerHTML = '';
  await refreshDrawer();
}
function closeDrawer() {
  openCell = null;
  $('scrim').classList.remove('on');
  $('drawer').classList.remove('on');
  $('drawer').setAttribute('aria-hidden', 'true');
}

async function refreshDrawer() {
  if (!openCell) return;
  const { bank, method } = openCell;
  const d = await (await fetch(`/api/cell/${bank}/${method}`)).json();
  const ev = d.evidence, st = d.state, inc = d.incident;
  const bnd = band(st.z);
  $('dtitle').innerHTML = `
    <h2 style="font-size:16px;letter-spacing:-.01em">${bank} · ${method}</h2>
    <div class="bigstat">
      <span class="n" style="color:${st.z <= -3.5 ? '#f08a8a' : 'var(--ink)'}">${pct(st.p)}</span>
      <span class="vs">vs <b class="mono">${pct(st.p0)}</b> expected ·
        z = <b class="mono">${st.z.toFixed(2)}</b> · ${num(st.n)} txn in 3 min</span>
    </div>`;

  const rails = ev.rails || [];
  const maxShare = Math.max(0.001, ...rails.map((r) => r.share_of_drop));
  const railBars = rails.map((r) => `
    <div class="bar">
      <span class="nm">${r.psp}</span>
      <span class="track"><span class="fill" style="width:${Math.max(1.5, r.share_of_drop / maxShare * 100).toFixed(1)}%;background:${
        r.share_of_drop >= 0.5 ? '#c22f2f' : 'rgba(57,135,229,.5)'}"></span></span>
      <span class="pct">${(r.share_of_drop * 100).toFixed(0)}%</span>
    </div>
    <div style="font-size:11.5px;color:var(--muted);margin:-2px 0 9px 114px">
      ${pct(r.p)} vs ${pct(r.p0)} expected · z ${r.z ?? '—'} · top code ${r.top_error || '—'}
    </div>`).join('');

  const alts = (ev.healthy_alternatives || []).map((a) =>
    `${a.psp} at ${pct(a.success_rate)}`).join(' · ') || 'none available';

  const n = inc?.narrative || {};
  $('dbody').innerHTML = `
    <div class="sec">
      <h4>Success rate vs learned baseline — last 90 minutes</h4>
      ${lineChart(d.series, st.p0)}
    </div>

    <div class="sec">
      <h4>Which rail explains the drop</h4>
      ${rails.length ? railBars : '<div class="note">This slice is within baseline.</div>'}
    </div>

    <div class="sec">
      <h4>Classification</h4>
      <div class="kv">
        <span class="k">Scope</span><span class="v">${d.scope_label}</span>
        <span class="k">Dominant decline code</span><span class="v">${ev.dominant_error_code || '—'}</span>
        <span class="k">Excess failures</span><span class="v">${ev.failed_txns_above_normal_per_min}/min</span>
        <span class="k">Same rail, other issuers</span><span class="v">${(ev.same_rail_also_degraded_for || []).join(', ') || 'none'}</span>
        <span class="k">Same issuer, other methods</span><span class="v">${(ev.same_issuer_also_degraded_on || []).map((x) => x.method).join(', ') || 'none'}</span>
        <span class="k">Healthy alternatives</span><span class="v">${alts}</span>
        <span class="k">Routing can mitigate</span><span class="v">${ev.reroutable ? 'yes' : 'no'}</span>
      </div>
    </div>

    ${n.summary ? `<div class="sec"><h4>Agent diagnosis${n.source
      ? ` <span style="text-transform:none;letter-spacing:0;color:var(--axis)">· ${n.source}</span>` : ''}</h4>
      <div class="note">${n.summary}</div></div>` : ''}

    ${n.merchant_note ? `<div class="sec"><h4>Draft merchant communication</h4>
      <div class="note" style="border-left:2px solid var(--series-1)">${n.merchant_note}</div></div>` : ''}

    ${inc ? `<div class="sec"><h4>Incident timeline — ${inc.id}</h4>
      <ul class="tl">${inc.timeline.map((t) => `<li><span class="ts">${hhmm(t.ts)}</span>
        <span><b style="color:var(--ink-2);text-transform:uppercase;font-size:10.5px;letter-spacing:.06em">${t.kind}</b><br>${t.text}</span></li>`).join('')}</ul>
      ${!inc.mitigation && ev.reroutable ? `<div style="margin-top:12px">
        <button class="btn primary" id="approve" data-id="${inc.id}">Approve reroute now</button></div>` : ''}
      </div>` : ''}`;

  const ap = $('approve');
  if (ap) ap.addEventListener('click', async () => {
    ap.disabled = true; ap.textContent = 'Applying…';
    await fetch('/api/incident/approve', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ incident_id: ap.dataset.id }),
    });
    refreshDrawer();
  });
}

/* Two series -> legend is present, and the baseline is also dashed, so identity
   never rests on colour alone. */
function lineChart(series, p0) {
  const W = 500, H = 150, PAD = { t: 14, r: 12, b: 22, l: 42 };
  const pts = series.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return '<div class="note">Not enough history yet.</div>';
  const vals = pts.map(([, v]) => v).concat(p0 ? [p0] : []);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.25, 0.015);
  lo = Math.max(0, lo - pad); hi = Math.min(1, hi + pad);
  const x = (i) => PAD.l + (i / (series.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const path = pts.map(([i, v], k) => `${k ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const ticks = [lo, (lo + hi) / 2, hi];
  const last = pts[pts.length - 1];
  return `
  <svg viewBox="0 0 ${W} ${H}" width="100%" role="img"
       aria-label="Observed success rate against learned baseline over the last 90 minutes">
    ${ticks.map((t) => `
      <line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(t)}" y2="${y(t)}" stroke="#2c2c2a" stroke-width="1"/>
      <text x="${PAD.l - 7}" y="${y(t) + 3.5}" text-anchor="end" fill="#898781"
            font-size="10" font-family="ui-monospace,monospace">${(t * 100).toFixed(0)}%</text>`).join('')}
    ${p0 ? `<line x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(p0)}" y2="${y(p0)}"
        stroke="#898781" stroke-width="2" stroke-dasharray="5 4"/>` : ''}
    <path d="${path}" fill="none" stroke="#3987e5" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(last[0])}" cy="${y(last[1])}" r="4" fill="#3987e5"
            stroke="#141413" stroke-width="2"/>
    <text x="${W - PAD.r}" y="${H - 6}" text-anchor="end" fill="#898781" font-size="10">now</text>
    <text x="${PAD.l}" y="${H - 6}" fill="#898781" font-size="10">−90 min</text>
  </svg>
  <div style="display:flex;gap:16px;font-size:11.5px;color:var(--muted);margin-top:2px">
    <span><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="#3987e5" stroke-width="2"/></svg>
      Observed</span>
    <span><svg width="18" height="8"><line x1="0" y1="4" x2="18" y2="4" stroke="#898781" stroke-width="2" stroke-dasharray="5 4"/></svg>
      Learned baseline for this hour</span>
  </div>`;
}

/* ---------- fault injector ---------- */
function initInjector(cfg) {
  const meth = $('f-method'), bank = $('f-bank'), psp = $('f-psp');
  meth.innerHTML = cfg.methods.map((m) => `<option>${m}</option>`).join('');
  bank.innerHTML = cfg.banks.map((b) => `<option>${b}</option>`).join('');
  const fillPsp = () => {
    psp.innerHTML = cfg.psps_by_method[meth.value].map((p) => `<option>${p}</option>`).join('');
  };
  meth.value = 'CARD'; bank.value = 'HDFC'; fillPsp();
  meth.addEventListener('change', fillPsp);
  const scope = $('f-scope');
  scope.addEventListener('change', () => {
    $('pspfield').style.display = scope.value === 'psp' ? '' : 'none';
  });
  $('f-sev').addEventListener('input', (e) => { $('sevout').textContent = e.target.value + '%'; });
  $('demobtn').addEventListener('click', () => {
    const p = $('demopanel'), on = p.classList.toggle('on');
    $('demobtn').setAttribute('aria-expanded', on);
  });
  $('f-go').addEventListener('click', () => fetch('/api/inject', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      scope: scope.value, bank: bank.value, method: meth.value,
      psp: scope.value === 'psp' ? psp.value : null,
      severity: Number($('f-sev').value) / 100,
    }),
  }));
  $('f-rand').addEventListener('click', () => fetch('/api/inject/random', { method: 'POST' }));
  $('f-clear').addEventListener('click', () => fetch('/api/clear', { method: 'POST' }));
  $('modelhint').textContent = cfg.llm
    ? `Diagnosis written by ${cfg.model}` : 'Diagnosis: deterministic fallback (no API key set)';
}

/* ---------- wiring ---------- */
function render(s) {
  STATE = s;
  const t = new Date(s.sim_time);
  $('clock').textContent = t.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
  $('date').textContent = t.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' });
  const mitigating = s.incidents.some((i) => i.status === 'mitigating');
  $('livetext').textContent = mitigating ? 'Mitigating'
    : s.kpis.open_incidents ? 'Investigating' : 'Watching';
  renderKpis(s.kpis);
  renderGrid(s);
  renderActivity(s.activity);
  renderFeed(s.incidents);
}

let drawerTick = 0;
function connect() {
  const es = new EventSource('/api/stream');
  es.onmessage = (e) => {
    render(JSON.parse(e.data));
    if (openCell && ++drawerTick % 3 === 0) refreshDrawer();
  };
  es.onerror = () => { es.close(); setTimeout(connect, 1500); };
}

$('tableToggle').addEventListener('click', (e) => {
  tableView = !tableView;
  e.target.setAttribute('aria-pressed', tableView);
  e.target.textContent = tableView ? 'Heatmap view' : 'Table view';
  if (STATE) renderGrid(STATE);
});
$('dclose').addEventListener('click', closeDrawer);
$('scrim').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
document.addEventListener('click', (e) => {
  if (!e.target.closest('.demo')) {
    $('demopanel').classList.remove('on');
    $('demobtn').setAttribute('aria-expanded', 'false');
  }
});

(async () => {
  CFG = await (await fetch('/api/config')).json();
  initInjector(CFG);
  renderLegend();
  connect();
})();

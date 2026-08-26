"use strict";

/* The console. One loop: read a case, check the evidence, decide.
 *
 * Two rules from the design work are enforced here rather than left to taste:
 * the narrative comes first and the graph is collapsed by default (analysts
 * think in stories, and a network diagram is a supporting exhibit), and every
 * claim expands to the raw transactions behind it -- trust in an automated case
 * comes from one-click verifiability. */

let state = { lane: null, cases: [], selected: null, detail: null,
              dropped: new Set(), openedAt: 0 };

const $ = (id) => document.getElementById(id);
const fmt = (n) => n.toLocaleString(undefined, { maximumFractionDigits: 0 });

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("on");
  setTimeout(() => t.classList.remove("on"), 2200);
}

/* ---------------- queue ---------------- */

async function loadQueue() {
  const q = state.lane ? `?lane=${state.lane}` : "";
  const data = await (await fetch(`/api/queue${q}`)).json();
  state.cases = data.cases;
  renderLanes(data);
  renderRows();
  loadStats();
}

function renderLanes(data) {
  const total = data.total_pending;
  const lanes = [["", "All", total]].concat(
    Object.entries(data.lanes).map(([k, v]) => [k, k.replace("_", " "), v]));
  $("lanes").innerHTML = lanes.map(([key, label, n]) =>
    `<button class="lane" data-lane="${key}"
       aria-pressed="${(state.lane || "") === key}">
       <b>${n}</b>${label}</button>`).join("");
  document.querySelectorAll(".lane").forEach((el) =>
    el.onclick = () => { state.lane = el.dataset.lane || null; loadQueue(); });
}

function renderRows() {
  if (!state.cases.length) {
    $("rows").innerHTML = `<div class="empty">Queue is clear.</div>`;
    return;
  }
  $("rows").innerHTML = state.cases.map((c) => `
    <div class="row" data-id="${c.id}" aria-selected="${state.selected === c.id}">
      <div class="row-id">${c.id}</div>
      <div class="row-score">${c.score.toFixed(3)}</div>
      <div class="row-sub">
        <span class="tag ${c.typology}">${c.typology}</span>
        ${c.lane === "control" ? '<span class="tag control">control</span>' : ""}
        ${c.headline}
      </div>
    </div>`).join("");
  document.querySelectorAll(".row").forEach((el) =>
    el.onclick = () => selectCase(el.dataset.id));
}

async function loadStats() {
  const s = await (await fetch("/api/stats")).json();
  $("kpis").innerHTML = [
    ["Pending", fmt(s.pending)],
    ["Disposed", fmt(s.labelled)],
    ["Confirm rate", (s.confirm_rate * 100).toFixed(1) + "%"],
    ["Accounts / decision", s.accounts_per_decision],
  ].map(([k, v]) => `<div class="kpi"><b>${v}</b><span>${k}</span></div>`).join("");
}

/* ---------------- case ---------------- */

async function selectCase(id) {
  state.selected = id;
  state.dropped = new Set();
  state.openedAt = Date.now();
  renderRows();
  state.detail = await (await fetch(`/api/case/${id}`)).json();
  renderCase();
}

function narrative(d) {
  const f = d.case.features;
  const parts = [];
  parts.push(`<b>${d.case.members.length} accounts</b> across
    <b>${f.n_banks}</b> bank${f.n_banks === 1 ? "" : "s"}`);
  if (f.n_countries > 1) parts.push(`and <b>${f.n_countries}</b> countries`);
  let s = parts.join(" ") + ". ";

  if (f.has_temporal_cycle) {
    s += `Value returns to its origin along a <b>cycle of length
      ${f.shortest_temporal_cycle}</b>, and the timestamps allow it — this is a
      loop money could actually have travelled, not three unrelated payments
      that happen to form a triangle. `;
  } else if (f.has_cycle) {
    s += `A cycle exists structurally but the timestamps do <b>not</b> permit
      value to travel it, so it is discounted. `;
  }
  if (f.conservation >= 0.7) {
    s += `<b>${(f.conservation * 100).toFixed(0)}%</b> of the value entering the
      cluster leaves it again — money passes through rather than accumulating. `;
  }
  if (f.stack_score >= 0.5) {
    s += `The flow is <b>layered across three levels</b>
      (${f.n_senders} → ${f.n_mules} → ${f.n_receivers}), which is what a stack
      structure looks like: extra hops exist to break the audit trail. `;
  } else if (f.bipartite_score >= 0.5) {
    s += `Sources feed sinks <b>directly across two layers</b> with no
      intermediary. `;
  }
  if (f.fast_passthrough_ratio > 0) {
    s += `<b>${(f.fast_passthrough_ratio * 100).toFixed(0)}%</b> of members
      forwarded most of what they received within 48 hours. `;
  }
  return s;
}

function graphSvg(d) {
  /* Only the ring itself, deterministically laid out by role. A force-directed
   * hairball is worse than a good table; this places senders left, mules
   * centre, receivers right so the shape is readable at a glance. */
  const cols = { sender: 0, mule: 1, receiver: 2 };
  const buckets = [[], [], []];
  d.members.forEach((m) => buckets[cols[m.role]].push(m.key));
  const W = 640, H = Math.max(180, Math.max(...buckets.map((b) => b.length)) * 34 + 40);
  const pos = {};
  buckets.forEach((b, ci) => b.forEach((k, i) => {
    pos[k] = { x: 90 + ci * 230, y: 30 + (H - 60) * ((i + 0.5) / b.length) };
  }));
  const edges = d.case.subgraph.map(([s, t, n, amt]) => {
    const a = pos[s], b = pos[t];
    if (!a || !b) return "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
      stroke="currentColor" stroke-width="1" opacity=".45"
      marker-end="url(#ar)"><title>${s} → ${t} · ${n} txn</title></line>`;
  }).join("");
  const nodes = d.members.map((m) => {
    const p = pos[m.key];
    if (!p) return "";
    const fill = state.dropped.has(m.key) ? "var(--muted)"
      : m.confidence >= 0.85 ? "var(--accent)"
      : m.confidence >= 0.5 ? "var(--warn)" : "var(--muted)";
    return `<g><circle cx="${p.x}" cy="${p.y}" r="7" fill="${fill}"/>
      <text x="${p.x + 12}" y="${p.y + 4}" fill="var(--ink-2)"
        font-family="IBM Plex Mono, monospace" font-size="10"
        >${m.key.length > 16 ? m.key.slice(0, 16) + "…" : m.key}</text>
      <title>${m.key} · ${m.role}</title></g>`;
  }).join("");
  return `<svg class="graph" viewBox="0 0 ${W} ${H}" role="img"
    aria-label="Money flow between the accounts in this case, senders on the left,
    pass-through accounts in the middle, receivers on the right">
    <defs><marker id="ar" viewBox="0 0 10 10" refX="16" refY="5"
      markerWidth="5" markerHeight="5" orient="auto-start-reverse">
      <polygon points="0,1 9,5 0,9" fill="currentColor" opacity=".6"/></marker></defs>
    <text x="90" y="14" fill="var(--muted)" font-family="IBM Plex Mono, monospace"
      font-size="9">SENDERS</text>
    <text x="320" y="14" fill="var(--muted)" font-family="IBM Plex Mono, monospace"
      font-size="9">PASS-THROUGH</text>
    <text x="550" y="14" fill="var(--muted)" font-family="IBM Plex Mono, monospace"
      font-size="9">RECEIVERS</text>
    ${edges}${nodes}</svg>`;
}

function txTable(d) {
  return `<div class="scroll"><table class="tx">
    <thead><tr><th>From</th><th>To</th><th>Txns</th><th>Amount</th></tr></thead>
    <tbody>${d.case.subgraph.map(([s, t, n, a]) =>
      `<tr><td>${s}</td><td>${t}</td><td>${n}</td>
       <td>${a.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td></tr>`
    ).join("")}</tbody></table></div>`;
}

function renderCase() {
  const d = state.detail;
  if (!d) return;
  const c = d.case;
  const disposed = c.disposition.verdict !== "pending";

  $("case").innerHTML = `
    <div class="case-hd">
      <div class="case-id">${c.id}</div>
      <div class="case-sub">
        <span class="tag ${d.typology}">${d.typology}</span>
        ${d.headline} · opened ${c.opened_at.slice(0, 16).replace("T", " ")}
        ${c.absorbed ? ` · corroborated by ${c.absorbed} overlapping views` : ""}
        ${c.lane === "control" ? " · control sample" : ""}
      </div>
      <div class="acts">
        <button class="confirm" id="bConfirm" ${disposed ? "disabled" : ""}>
          Confirm${state.dropped.size ? " (partial)" : ""}</button>
        <button class="dismiss" id="bDismiss" ${disposed ? "disabled" : ""}>Dismiss</button>
        <button class="more" id="bMore" ${disposed ? "disabled" : ""}>Need more</button>
        ${disposed ? `<span class="mono" style="align-self:center;color:var(--muted)">
          disposed: ${c.disposition.verdict}</span>` : ""}
      </div>
    </div>

    <div class="sec">
      <h3>Why this fired</h3>
      <p class="narr">${narrative(d)}</p>
    </div>

    <div class="sec">
      <h3>Evidence — every row is backed by a computed feature</h3>
      ${d.evidence.map((e) => `
        <div class="ev">
          <div class="ev-n">${e.name}</div>
          <div class="ev-d">${e.detail || ""}</div>
          <div class="ev-v">${e.value}</div>
        </div>`).join("") || '<div class="ev-d">No structural evidence.</div>'}
      <details style="margin-top:12px">
        <summary>▸ show the ${c.subgraph.length} underlying transactions</summary>
        ${txTable(d)}
      </details>
    </div>

    <div class="sec">
      <h3>Members — drop any that do not belong</h3>
      ${d.members.map((m) => `
        <div class="mem ${state.dropped.has(m.key) ? "dropped" : ""}">
          <span class="mem-k">${m.key}</span>
          <span class="mem-r">${m.role} · in ${m.in} / out ${m.out}</span>
          <span class="conf ${m.confidence < 0.5 ? "low" : ""}">
            ${m.confidence.toFixed(2)}</span>
          <button class="drop" data-key="${m.key}" ${disposed ? "disabled" : ""}>
            ${state.dropped.has(m.key) ? "restore" : "drop"}</button>
        </div>`).join("")}
    </div>

    <div class="sec">
      <h3>Flow</h3>
      ${graphSvg(d)}
    </div>

    <div class="sec">
      <h3>Timeline — immutable</h3>
      ${c.timeline.map((t) => `<div class="ev-d mono">${t.kind} · ${t.text}</div>`).join("")}
    </div>`;

  document.querySelectorAll(".drop").forEach((el) => el.onclick = () => {
    const k = el.dataset.key;
    state.dropped.has(k) ? state.dropped.delete(k) : state.dropped.add(k);
    renderCase();
  });
  $("bConfirm").onclick = () => dispose(
    state.dropped.size ? "confirmed_partial" : "confirmed_ring",
    state.dropped.size ? "subset_confirmed" : "layering");
  $("bDismiss").onclick = () => dispose("not_a_ring", "coincidental_structure");
  $("bMore").onclick = () => dispose("insufficient_evidence", "needs_more_time");
}

async function dispose(verdict, reason) {
  const id = state.selected;
  const seconds = (Date.now() - state.openedAt) / 1000;
  const res = await fetch(`/api/case/${id}/verdict`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ verdict, reason, dropped: [...state.dropped], seconds }),
  });
  if (!res.ok) { toast("Could not record that verdict."); return; }
  const truth = state.detail.case.truth_rings || [];
  toast(`${id}: ${verdict.replace("_", " ")} · ${seconds.toFixed(0)}s` +
        (truth.length ? `  (ground truth: ${truth.join(", ")})` : "  (no ring here)"));
  state.selected = null;
  state.detail = null;
  $("case").innerHTML = `<div class="empty">Select a case from the queue.</div>`;
  loadQueue();
}

/* keyboard: disposition must cost seconds, not a form */
document.addEventListener("keydown", (e) => {
  if (!state.detail || e.target.tagName === "INPUT") return;
  if (e.key === "c") $("bConfirm")?.click();
  if (e.key === "d") $("bDismiss")?.click();
  if (e.key === "m") $("bMore")?.click();
});

loadQueue();

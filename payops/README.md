# Sentinel — Autonomous Payment Ops Analyst

A dashboard waits for a human to look at it. Sentinel looks for them.

Sentinel watches every payment slice continuously, learns what each one *should*
be doing at this hour on this weekday, and speaks only when something deviates —
then diagnoses the cause, reroutes traffic away from the broken rail, and writes
the incident note and the merchant comms itself.

**The framing that matters:** this does not replace a payment ops analyst. No
gateway staffs a war room with a senior analyst on every shift, and 03:00 on a
Sunday is exactly when a bank rail quietly degrades and nobody notices for forty
minutes. Sentinel covers a seat that was never filled.

---

## The loop

| Stage | What happens | Where |
|---|---|---|
| **Watch** | Streaming success rates sliced by issuer × method × rail, 32 slices over 8 rails | `sim.py`, `baseline.py` |
| **Detect** | Deviation from each slice's *own* learned baseline for this hour and weekday — not a static threshold | `baseline.py` |
| **Diagnose** | Deterministic contribution analysis isolates the responsible dimension; Claude writes it up | `diagnose.py` |
| **Act** | Reroutes traffic off the degraded rail, opens the incident, drafts merchant comms | `agent.py` |

### Why baselines and not thresholds

HDFC UPI at 94% on a Tuesday morning is fine. The same 94% at 14:00 is a fire.
A static rule cannot tell those apart, so teams set it loose enough to never fire
and the degradation goes unnoticed.

Sentinel keeps an EWMA of success rate per slice keyed by `(weekday, hour)`,
warm-started from 14 days of history at boot and updated continuously — but only
from windows it did *not* flag, so an outage never gets absorbed into "normal".
Each slice also tracks the EWMA of its own squared residuals, so a naturally
noisy slice earns a wider tolerance instead of paging someone every evening.

Detection is a z-score against that baseline, with the variance being the sum of
binomial sampling error and the slice's own historical wobble:

```
z = (p_observed − p_expected) / sqrt( p(1−p)/n  +  σ²_baseline )
```

An incident opens only when `z ≤ −4` **and** the absolute drop clears 1.5pp
**and** the breach is sustained across two consecutive windows. In a quiet
system the loudest slice sits around |z| = 1.4 — there are no false pages.

### Why the diagnosis is two stages

Attribution is arithmetic, so it is done in code: excess failures are computed
per rail, the shares are ranked, the same rail is checked against other issuers
and the same issuer against other methods, and the decline-code mix is compared
to normal. Only then does Claude get involved, and only to turn that finished
evidence into prose. The model never invents a number, and if the API is
unreachable a deterministic narrator takes over so the demo cannot break.

The classification that matters operationally is **rail-side vs issuer-side**:

- *Rail-side* — the excess failures concentrate on one PSP/acquirer, and the
  decline codes skew to `ACQUIRER_ERROR` / `PSP_TIMEOUT`. Routing can fix this.
- *Issuer-side* — the failures follow the issuer across every rail carrying its
  traffic, dominated by `ISSUER_TIMEOUT`. Routing cannot fix this, and an agent
  that reroutes anyway would just thrash live traffic. Sentinel says so and
  recommends retry policy plus merchant comms instead.

### The action, and its guardrails

When the fault is rail-side and a healthy alternative exists, Sentinel rewrites
the routing weights itself — but leaves **3% of traffic on the degraded rail as
a health canary**, which is how it discovers, with no human involved, that the
rail has recovered and the original split can be restored. Every change is
logged with its before/after weights and is reversible. Below the severity
threshold it stages the reroute and waits for a click instead.

### One incident, not thirty alerts

A rail-wide fault degrades several issuer cells at once. Sentinel correlates
them by signature — same rail, same method, same dominant decline code — and
folds them into one incident rather than paging once per cell. Alert fatigue is
the failure mode of ops tooling, and the interface is built around avoiding it:
two panels, not thirty widgets.

---

## Running it

```bash
# Windows
run.bat

# macOS / Linux
./run.sh
```

Then open <http://127.0.0.1:8000>.

Optionally copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` — Claude
then writes the incident summaries and merchant notes. Without it everything
still runs; the narration is just templated.

`PAYOPS_TICK_SECONDS` controls the clock: one simulated minute per tick, 1.4
seconds per tick by default. Lower it to compress an entire incident arc into a
few seconds, raise it to have room to narrate.

---

## The 90-second demo

1. **Open on a quiet system.** 32 slices, all within baseline, one line in the
   activity log every ten minutes. *"It is watching and it has nothing to say.
   That restraint is the product."*
2. **Fault injector → rail degradation, HDFC / CARD / ICICI-ACQ, 55%.** Say what
   you injected before it appears.
3. **Watch the cell go red** while its neighbours stay flat. *"Nothing about the
   overall success rate would have caught this — it moved less than a point."*
4. **Read the incident as it writes itself:** the drop, the 95% attribution to
   one acquirer, the `ACQUIRER_ERROR` skew, detected in ~3 minutes against a
   ~30-minute human rota.
5. **Watch it act.** Routing shifts off ICICI-ACQ, 3% canary retained, and the
   cell walks back to baseline on screen.
6. **Now inject an issuer-side fault** (SBI / UPI). Open the drill-down: the
   excess failures are spread evenly across all three PSPs. *"Same detector,
   opposite conclusion — and it refuses to reroute, because rerouting would not
   help. Knowing when not to act is the hard part of autonomy."*
7. **Close on the drill-down:** learned baseline vs observed, rail contribution,
   classification, the drafted merchant note, and the full audit timeline.

---

## Design notes

The console is deliberately two panels. Cell colour encodes **deviation**, never
the raw success rate, because raw rates are not comparable across rails — cards
live in the high 80s, wallets in the high 90s, and colouring by rate would paint
the card column permanently amber. Colour is never the only channel: every cell
carries its numeric delta, flagged cells carry a `▼` and the incident id, and a
table view gives the same data as sortable text.

---

## What is real and what is simulated

**Simulated:** the transaction stream. Volume follows an Indian intraday curve
with a weekday multiplier, per-slice success rates and decline-code mixes are
drawn from realistic distributions, and injected faults ramp in over two minutes
rather than appearing instantly.

**Real:** everything downstream of the stream. The baseline learner, the
detector, the contribution analysis, the correlation logic, the routing engine
and the canary-based recovery all operate on the stream exactly as they would on
production data.

**To point it at production**, replace `Simulator.step()` with a reader over the
real transaction topic emitting the same `MinuteRow` shape, and replace
`Simulator.set_routing()` with a call to the live routing service. Nothing else
in the detection or diagnosis path changes.

## Layout

```
backend/
  config.py      dimensions, health model, seasonality, detection tuning
  sim.py         synthetic stream + routing engine + injectable outages
  baseline.py    EWMA baselines, rolling windows, z-score detector
  diagnose.py    contribution analysis + Claude narration (+ fallback)
  agent.py       incident lifecycle, reroute action, canary recovery
  app.py         FastAPI: SSE stream and control endpoints
frontend/
  index.html     the console
  app.js         rendering, heatmap, drill-down, fault injector
```

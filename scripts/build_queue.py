"""Generate a live queue of PENDING cases for the console.

Unlike the phase 4 evaluation, no simulated analyst runs here -- the cases are
left undisposed so a human can actually work them. Ground-truth ring membership
is attached to each case for the demo's "was that right?" reveal, and is never
shown to the scorer.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.cases.manager import CaseManager
from sentinel.cases.store import CaseStore
from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 12
CAPACITY = 12

stream = Stream(ROOT / "data" / "stream")
registry = AccountRegistry.load(DATASET.accounts(ROOT))
graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)
store = CaseStore(ROOT / "data" / "queue")
mgr = CaseManager(store, stream=stream, capacity=CAPACITY, control_fraction=0.08)

runs = 0
for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
    graph.add_batch(b)
    if i % EVERY or graph.now < WINDOW_MINUTES // 2:
        continue
    m = ((stream.ts >= graph.now - graph.window) & (stream.ts < graph.now)
         & (stream.ring >= 0))
    rings = defaultdict(set)
    for a, c, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        rings[int(r)].update((int(a), int(c)))
    cands = gen.generate(b)
    if not cands:
        continue
    runs += 1
    for cand, lane in mgr.select(cands):
        case = mgr.open_case(cand, lane, graph)
        nodes = set(cand.nodes)
        for r, acc in rings.items():
            if len(acc) >= 3 and len(nodes & acc) / len(acc) >= 0.5 \
                    and len(nodes & acc) / len(nodes | acc) >= 0.3:
                case.truth_rings.append(stream.ring_name(r))
    print(f"  cycle {runs:>3} -> {len(store.all()):>4} cases", flush=True)

print(f"\n{len(store.all())} pending cases written to data/queue")
print(f"with ground truth attached: "
      f"{sum(1 for c in store.all() if c.truth_rings)}")

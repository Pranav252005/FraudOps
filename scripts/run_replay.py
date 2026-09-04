"""Phase 1 smoke run: replay the whole stream through the windowed graph."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sentinel.data.datasets import active_stream_dir
from sentinel.stream.replay import Stream
from sentinel.graph.window import WindowedGraph

TICK = 60
WINDOW = 72 * 60

s = Stream(active_stream_dir(Path(__file__).resolve().parent.parent))
g = WindowedGraph(window_minutes=WINDOW)
print(f"stream: {s.meta['n_edges']:,} edges, {s.meta['n_nodes']:,} nodes")
print(f"span  : {s.when(s.t_min)}  ->  {s.when(s.t_max)}  ({s.n_ticks(TICK)} ticks of {TICK}min)")
print(f"window: {WINDOW//60}h\n")

t0 = time.time(); peak = 0; total = 0
print(f"{'tick':>5} {'sim time':<17}{'edges/tick':>11}{'pairs':>10}{'nodes':>9}{'ring edges':>12}")
for i, b in enumerate(s.ticks(TICK)):
    g.add_batch(b)
    total += len(b)
    peak = max(peak, len(g))
    if i % 48 == 0 or i == s.n_ticks(TICK) - 1:
        rings = int((b.ring >= 0).sum())
        print(f"{i:>5} {str(s.when(b.t_start)):<17}{len(b):>11,}{len(g):>10,}{g.n_nodes:>9,}{rings:>12}")

el = time.time() - t0
st = g.stats()
print(f"\nreplayed {total:,} edges in {el:.1f}s  ({total/el:,.0f} edges/s)")
print(f"peak window size : {peak:,} pairs")
print(f"final window     : {st['pairs']:,} pairs / {st['nodes']:,} nodes")
print(f"added {st['added']:,}  expired {st['expired']:,}  "
      f"(retained {st['added']-st['expired']:,})")

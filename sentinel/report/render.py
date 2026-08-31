"""Phase 4.2 -- render a template against the metrics file, or fail loudly.

The placeholder grammar, deliberately small:

    {{metric:supervised_p_at_10}}          the value,      0.2111
    {{ci:supervised_p_at_10}}              the interval,   [0.1111, 0.3167]
    {{metric_ci:supervised_p_at_10}}       both,           0.2111 [0.1111, 0.3167]
    {{baseline:supervised_p_at_10}}        the size baseline
    {{n:supervised_p_at_10}}               the unit count
    {{signed:supervised_over_blend_delta_at_10}}   +0.0222
    {{ratio:seeding_prize_blend_ratio_at_10}}      2.18x
    {{count:n_held_out_cycles}}            an exact count, not an estimate

Rendering FAILS -- it does not warn, and it does not leave the placeholder in
place -- when the id is absent, when a required field on it is null, or when a
`{{...}}` that looks like a placeholder uses an unknown verb. A README that
renders with a hole in it is worse than one that does not render, because the
hole ships.

WHY THERE IS NO `{{raw:...}}` ESCAPE HATCH. Every verb above emits the number
together with the context that number needs, or emits a count that has no
interval by nature. A verb that emitted a bare p@k would let a writer bypass
rule 2 while still passing the literal scan, which would make the scan worse
than useless -- it would certify the file as clean.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sentinel.report.metric import Metric, MetricContractError
from sentinel.report.store import read

PLACEHOLDER = re.compile(r"\{\{\s*(?P<verb>[a-z_]+)\s*:\s*(?P<id>[A-Za-z0-9_.]+)\s*\}\}")

# Anything that looks like a placeholder but is not one. Caught separately so a
# typo in a verb is an error rather than silently surviving into the output.
SUSPECT = re.compile(r"\{\{[^}]*\}\}")


class RenderError(RuntimeError):
    """The template referenced something the metrics file cannot supply."""


def _fmt(x: float, places: int = 4) -> str:
    return f"{x:.{places}f}"


def _require(m: Metric, field: str, verb: str) -> object:
    v = getattr(m, field, None)
    if v is None:
        raise RenderError(
            f"{{{{{verb}:{m.id}}}}} needs `{field}`, which is null on that "
            f"metric. The fix is to measure it, not to drop the placeholder.")
    return v


def render_text(template: str, metrics: dict[str, Metric],
                counts: dict | None = None) -> str:
    counts = counts or {}

    def sub(match: re.Match) -> str:
        verb, mid = match.group("verb"), match.group("id")

        if verb in ("count", "count_pct"):
            if mid not in counts:
                raise RenderError(
                    f"{{{{{verb}:{mid}}}}} is not in the metrics file's "
                    f"`counts`. Known: {sorted(counts)}")
            v = counts[mid]
            if verb == "count_pct":
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise RenderError(
                        f"{{{{count_pct:{mid}}}}} needs a number, got {v!r}")
                return f"{v * 100:.1f}%"
            return f"{v:,}" if isinstance(v, int) else str(v)

        if mid not in metrics:
            raise RenderError(
                f"{{{{{verb}:{mid}}}}} refers to a metric that does not "
                f"exist. Run scripts/collect_metrics.py, or fix the id. "
                f"Known ids: {sorted(metrics)[:6]}...")
        m = metrics[mid]

        if verb == "metric":
            return _fmt(m.value)
        if verb == "signed":
            return f"{m.value:+.4f}"
        if verb == "ratio":
            return f"{m.value:.2f}x"
        if verb == "pct":
            return f"{m.value * 100:.1f}%"
        if verb == "ci":
            return f"[{_fmt(m.ci_lower)}, {_fmt(m.ci_upper)}]"
        if verb == "ci_signed":
            # Deltas read wrong without signs: "[0.1235, 0.2676]" and
            # "[-0.0032, 0.0135]" look like the same kind of interval until
            # you notice the minus, which is the one thing a reader must not
            # have to notice.
            return f"[{m.ci_lower:+.4f}, {m.ci_upper:+.4f}]"
        if verb == "metric_ci":
            return f"{_fmt(m.value)} [{_fmt(m.ci_lower)}, {_fmt(m.ci_upper)}]"
        if verb == "signed_ci":
            return (f"{m.value:+.4f} "
                    f"[{m.ci_lower:+.4f}, {m.ci_upper:+.4f}]")
        if verb == "ratio_ci":
            return (f"{m.value:.2f}x [{m.ci_lower:.2f}x, {m.ci_upper:.2f}x]")
        if verb == "baseline":
            return _fmt(float(_require(m, "size_baseline", verb)))
        if verb == "n":
            return str(m.n_units)
        if verb == "k":
            return str(_require(m, "k", verb))
        if verb == "prevalence":
            return f"{float(_require(m, 'prevalence', verb)):.6f}"
        raise RenderError(
            f"unknown placeholder verb {verb!r} in {{{{{verb}:{mid}}}}}. "
            f"Known verbs: metric, signed, ratio, ci, metric_ci, signed_ci, "
            f"ratio_ci, baseline, n, k, pct, prevalence, count, count_pct.")

    out = PLACEHOLDER.sub(sub, template)

    leftovers = [s for s in SUSPECT.findall(out)]
    if leftovers:
        raise RenderError(
            f"{len(leftovers)} placeholder-shaped strings survived rendering, "
            f"which means they did not match the grammar: {leftovers[:4]}. A "
            f"README that renders with a hole in it ships the hole.")
    return out


def render_file(template_path: Path, metrics_path: Path,
                out_path: Path) -> Path:
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics = read(metrics_path)
    text = render_text(template_path.read_text(encoding="utf-8"),
                       metrics, payload.get("counts", {}))
    banner = (f"<!-- GENERATED FROM {template_path.name} by "
              f"sentinel/report/render.py. DO NOT EDIT THIS FILE. -->\n"
              f"<!-- metrics: {metrics_path.name} @ commit "
              f"{payload.get('commit', 'unknown')[:7]}, "
              f"generated {payload.get('generated_at', 'unknown')} -->\n")
    out_path.write_text(banner + text, encoding="utf-8")
    return out_path


__all__ = ["PLACEHOLDER", "RenderError", "render_file", "render_text"]

"""The metrics file: one place a reported number can come from.

Phase 4 of the uplift plan turns README into a template rendered from this
file. The point of that is not tidiness -- it is that a number currently lives
in 1,699 places across README and docs (docs/inventory/metric_literals.csv), so
it can be wrong in 1,699 places, and `0.2778` alone appears 40 times.

Enforcement is in the WRITER, not in the caller and not in review. `write()`
takes `Metric` objects, and a `Metric` cannot exist without its baseline,
prevalence, interval, clustering and conditioning (see metric.py). So the
constraint "a number without its context cannot be published" is not a rule
somebody follows; it is a type that cannot be constructed otherwise.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from sentinel.report.metric import Metric, MetricContractError

SCHEMA_VERSION = 1


def _commit() -> str:
    """The commit these numbers were measured at, or an honest admission.

    Returns the literal string "unknown" rather than guessing or omitting the
    field. Phase 4.3 requires historical literals to carry the commit they
    were measured at; a marker that says "unknown" is auditable, and a missing
    marker is not.
    """
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def write(path: Path, metrics: list[Metric], *, generated_by: str) -> Path:
    """Write `metrics` to `path` as the single source of truth.

    `generated_by` names the script that measured these numbers. It is
    required and unvalidated: required because a metrics file whose producer
    is unknown cannot be regenerated or checked, unvalidated because the only
    honest check is running the thing.
    """
    if not generated_by:
        raise MetricContractError(
            "generated_by is required: a metrics file that does not say what "
            "produced it cannot be regenerated, and a number that cannot be "
            "regenerated cannot be defended.")
    ids = [m.id for m in metrics]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise MetricContractError(
            f"duplicate metric ids {dupes}: a template placeholder would "
            f"resolve to whichever came last, silently.")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": generated_by,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": _commit(),
        "metrics": {m.id: m.to_dict() for m in metrics},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read(path: Path) -> dict[str, Metric]:
    """Load a metrics file back into `Metric` objects.

    Round-tripping through the constructor is deliberate: a file hand-edited
    into an invalid state fails here rather than rendering into a document.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise MetricContractError(
            f"{path}: schema_version {payload.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION}")
    out: dict[str, Metric] = {}
    for mid, d in payload["metrics"].items():
        d = dict(d)
        d.pop("id", None)
        notes = d.pop("notes", None)
        out[mid] = Metric(id=mid, notes=tuple(notes) if notes else (), **d)
    return out

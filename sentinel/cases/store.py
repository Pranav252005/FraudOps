"""Append-only case store — the label corpus, and the audit artifact.

Append-only JSONL rather than a mutable table, for two reasons that happen to
coincide. The retention and reporting obligations a payment aggregator operates
under want an immutable record of what was flagged, when, and on what evidence;
and a training corpus wants exactly the same thing, because a record that can be
edited in place cannot be trusted as a point-in-time observation.

Dispositions are appended as separate events rather than written back into the
case row. The case as first written is never modified.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from sentinel.cases.case import Case, Disposition, Verdict, validate_reason


class CaseStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.cases_file = self.path / "cases.jsonl"
        self.events_file = self.path / "events.jsonl"
        self._cases: dict[str, Case] = {}
        self._counter = 0

    # -- write ---------------------------------------------------------------

    def next_id(self) -> str:
        self._counter += 1
        return f"CASE-{self._counter:05d}"

    def open(self, case: Case) -> Case:
        """Persist a case exactly as it was scored."""
        if case.id in self._cases:
            raise ValueError(f"duplicate case id {case.id}")
        self._cases[case.id] = case
        with self.cases_file.open("a", encoding="utf-8") as fh:
            fh.write(case.to_json() + "\n")
        return case

    def dispose(self, case_id: str, verdict: Verdict, reason: str = "",
                note: str = "", analyst: str = "", at: str = "",
                confirmed_members: list[str] | None = None,
                dropped_members: list[str] | None = None,
                seconds: float | None = None) -> Case:
        case = self._cases.get(case_id)
        if case is None:
            raise KeyError(case_id)
        if reason and not validate_reason(verdict, reason):
            raise ValueError(f"reason {reason!r} is not valid for {verdict.value}")

        case.disposition = Disposition(
            verdict=verdict, reason=reason, note=note, analyst=analyst, at=at,
            confirmed_members=confirmed_members or [],
            dropped_members=dropped_members or [],
            seconds_to_decide=seconds,
        )
        case.log(at, "disposition", f"{verdict.value}"
                                    + (f" ({reason})" if reason else ""))
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"case": case_id,
                                 **case.disposition.to_dict()},
                                separators=(",", ":")) + "\n")
        return case

    # -- read ----------------------------------------------------------------

    def get(self, case_id: str) -> Case | None:
        return self._cases.get(case_id)

    def all(self) -> list[Case]:
        return list(self._cases.values())

    def pending(self, lane=None) -> list[Case]:
        out = [c for c in self._cases.values()
               if not c.disposition.verdict.is_resolved]
        if lane is not None:
            out = [c for c in out if c.lane == lane]
        return sorted(out, key=lambda c: -c.score)

    def labelled(self) -> list[Case]:
        return [c for c in self._cases.values()
                if c.disposition.verdict.is_resolved]

    def load(self) -> "CaseStore":
        """Rebuild in-memory state from disk, replaying dispositions in order."""
        self._cases.clear()
        if self.cases_file.exists():
            for line in self.cases_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    c = Case.from_dict(json.loads(line))
                    self._cases[c.id] = c
                    n = int(c.id.rsplit("-", 1)[-1])
                    self._counter = max(self._counter, n)
        if self.events_file.exists():
            for line in self.events_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                e = json.loads(line)
                c = self._cases.get(e.get("case"))
                if c is None:
                    continue
                c.disposition = Disposition(
                    verdict=Verdict(e["verdict"]), reason=e.get("reason", ""),
                    note=e.get("note", ""), at=e.get("at", ""),
                    analyst=e.get("analyst", ""),
                    confirmed_members=e.get("confirmed_members", []),
                    dropped_members=e.get("dropped_members", []),
                    seconds_to_decide=e.get("seconds_to_decide"),
                )
        return self

    # -- reporting -----------------------------------------------------------

    def stats(self) -> dict:
        verdicts = Counter(c.disposition.verdict.value for c in self._cases.values())
        lanes = Counter(c.lane.value for c in self._cases.values())
        done = self.labelled()
        confirm_rate = (sum(1 for c in done if c.disposition.verdict.is_positive)
                        / len(done)) if done else 0.0
        return {
            "cases": len(self._cases),
            "labelled": len(done),
            "verdicts": dict(verdicts),
            "lanes": dict(lanes),
            # If this approaches 1.0 the tool is being trusted blindly rather
            # than used. It is instrumented for exactly that reason.
            "confirm_rate": confirm_rate,
            "detector_versions": dict(Counter(c.detector_version
                                              for c in self._cases.values())),
        }

    def training_rows(self) -> list[dict]:
        """Point-in-time features paired with the human label.

        This is the whole reason the case layer exists: it is the corpus the v2
        re-ranker trains on. Cases still pending are excluded, and features are
        taken exactly as snapshotted at alert time.
        """
        rows = []
        for c in self.labelled():
            rows.append({
                "case": c.id,
                "t": c.opened_t,
                "lane": c.lane.value,
                "detector_version": c.detector_version,
                "label": int(c.disposition.verdict.is_positive),
                "verdict": c.disposition.verdict.value,
                **{f"f_{k}": v for k, v in c.features.items()
                   if isinstance(v, (int, float, bool))},
            })
        return rows

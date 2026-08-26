"""Append-only log of escalation recommendations and human decisions.

Same shape as `sentinel.cases.store.CaseStore` and for the same reason: the
recommendation, the decision, and the execution are each a fact about what
happened and when, and an audit trail that can be edited in place is not an
audit trail. Every recommendation, decision, and execution is appended as a
JSON line rather than mutated into an existing row.
"""
from __future__ import annotations

import json
from pathlib import Path

from sentinel.escalation import Action, DecisionStatus, Recommendation


class RecommendationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.file = self.path / "recommendations.jsonl"
        self._by_id: dict[str, Recommendation] = {}
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"REC-{self._counter:05d}"

    def add(self, rec: Recommendation) -> str:
        rec_id = self.next_id()
        self._by_id[rec_id] = rec
        self._append({"event": "recommend", "id": rec_id, **rec.to_dict()})
        return rec_id

    def update(self, rec_id: str, event: str) -> None:
        rec = self.get(rec_id)
        if rec is None:
            raise KeyError(rec_id)
        self._append({"event": event, "id": rec_id, **rec.to_dict()})

    def _append(self, row: dict) -> None:
        with self.file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    def get(self, rec_id: str) -> Recommendation | None:
        return self._by_id.get(rec_id)

    def all(self) -> list[tuple[str, Recommendation]]:
        return sorted(self._by_id.items())

    def for_case(self, case_id: str) -> list[tuple[str, Recommendation]]:
        return [(i, r) for i, r in self.all() if r.case_id == case_id]

    def load(self) -> "RecommendationStore":
        """Rebuild in-memory state by replaying every event in order."""
        self._by_id.clear()
        self._counter = 0
        if not self.file.exists():
            return self
        for line in self.file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rec_id = row["id"]
            n = int(rec_id.rsplit("-", 1)[-1])
            self._counter = max(self._counter, n)
            rec = Recommendation(
                case_id=row["case_id"], action=Action(row["action"]),
                evidence_ids=row["evidence_ids"], rationale=row["rationale"],
                recommended_at=row["recommended_at"],
                status=DecisionStatus(row["status"]),
                decided_by=row.get("decided_by", ""),
                decided_at=row.get("decided_at", ""),
                decision_note=row.get("decision_note", ""),
                executed=row.get("executed", False),
                executed_at=row.get("executed_at", ""),
            )
            self._by_id[rec_id] = rec
        return self

"""The reportable number for the LLM path: what was drafted, and what was stopped.

This exists because "we added an LLM and put a guardrail on it" is an
assertion, and this project's standing rule is that an assertion without a
measurement is a claim about intent. The ledger turns the guardrail into a
count: N drafts attempted, M rejected for an uncited or invented claim, and
how many of those reached a filing (which must be zero, and there is a test
that says so).

Outcomes are a closed set. `llm_rejected_*` are the two interesting ones --
they are the verifier doing the job it was written for, against text it did
not generate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Narrative reached filing, drafted by the model and passed verification.
LLM_FILED = "llm_filed"
# Model drafted, verifier rejected: a fact-bearing sentence with no citation.
LLM_REJECTED_UNCITED = "llm_rejected_uncited"
# Model drafted, verifier rejected: cited an id absent from the case file.
LLM_REJECTED_UNVERIFIABLE = "llm_rejected_unverifiable"
# No draft obtained -- no key configured, timeout, 4xx, 5xx, malformed body.
LLM_UNAVAILABLE = "llm_unavailable"
# Template path used and filed. Also the outcome after any of the above.
TEMPLATE_FILED = "template_filed"

OUTCOMES = (LLM_FILED, LLM_REJECTED_UNCITED, LLM_REJECTED_UNVERIFIABLE,
            LLM_UNAVAILABLE, TEMPLATE_FILED)


@dataclass
class DraftLedger:
    """Append-only tally of drafting outcomes.

    `path`, when given, receives one JSON object per recorded outcome. It is
    append-only for the same reason the case store is: a metric you can
    rewrite is a metric you can talk yourself into.
    """
    counts: dict = field(default_factory=lambda: {o: 0 for o in OUTCOMES})
    path: Path | None = None

    def record(self, outcome: str, *, case_id: str = "", detail: str = "",
               model: str = "") -> None:
        if outcome not in self.counts:
            raise ValueError(f"unknown drafting outcome: {outcome!r}")
        self.counts[outcome] += 1
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(),
               "case_id": case_id, "outcome": outcome, "detail": detail,
               "model": model}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    @property
    def attempted(self) -> int:
        """Drafts where a model actually returned text. Excludes
        `llm_unavailable`, because a call that never happened is not a draft
        the verifier declined to pass -- conflating the two would flatter the
        rejection rate."""
        return (self.counts[LLM_FILED] + self.counts[LLM_REJECTED_UNCITED]
                + self.counts[LLM_REJECTED_UNVERIFIABLE])

    @property
    def rejected(self) -> int:
        return (self.counts[LLM_REJECTED_UNCITED]
                + self.counts[LLM_REJECTED_UNVERIFIABLE])

    @property
    def rejection_rate(self) -> float | None:
        """None, not zero, when nothing was drafted. A rate over an empty
        denominator reported as 0.0 reads as "the model never erred"."""
        return self.rejected / self.attempted if self.attempted else None

    def to_dict(self) -> dict:
        return {"counts": dict(self.counts), "attempted": self.attempted,
                "rejected": self.rejected,
                "rejection_rate": self.rejection_rate}

    def summary(self) -> str:
        rate = self.rejection_rate
        rate_text = "n/a (no drafts attempted)" if rate is None else f"{rate:.1%}"
        return (f"{self.attempted} drafted, {self.rejected} rejected before "
                f"filing ({rate_text}), "
                f"{self.counts[LLM_UNAVAILABLE]} unavailable, "
                f"{self.counts[TEMPLATE_FILED]} filed from template")

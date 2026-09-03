"""The citation verifier: the load-bearing check for the STR narrative.

Every factual sentence in a generated narrative must carry at least one inline
citation of the form `[ID]`, where `ID` is a transaction id (`TXN-########`),
an account key, or the case id -- something present in the case file's own
evidence (`CaseFile.valid_citation_ids()`). If a claim carries a citation to an
id that does not exist in the case file, or carries a fact-shaped claim with
no citation at all, that is a hard failure, never a warning: a wrong or
invented fact in a suspicious-activity filing is a bigger liability than a
missed filing, and this check is what stands between a plausible-sounding
hallucinated fact and a filed report if narrative drafting is ever routed
through an LLM.

SCOPE, AND THE LIMIT IS EXACT. This verifier answers two questions: is there a
citation on every fact-shaped sentence, and does each cited id exist in the
case file. It **does not check that the cited id supports the claim.** A
sentence asserting the wrong amount, the wrong direction, the wrong date or the
wrong role, carrying a citation to a real transaction, passes. So does a claim
about the law propped up by a transaction id.

That is a demonstrated hole, not a suspected one:
`tests/test_citation_adversarial.py` asserts seven such narratives PASS, with
positive controls proving the two implemented checks still fire on the same
fixture -- so the hole is exactly attribution and not something wider. It was
predicted before it was measured, in `prereg/citation_recall.md`.

Closing it needs claim-tuple verification: parse (subject, amount, direction,
timestamp) out of each sentence and check the tuple against the cited record.
That is a real piece of work and is NOT done. Until it is, "every sentence is
verified" means "every sentence is sourced", which is weaker, and the
difference is the difference between a citation and a fact-check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[([A-Za-z0-9:_\-]+)\]")

# A sentence with none of these tokens is scene-setting or connective prose
# ("This report is filed to summarise suspicious activity.") and does not
# assert anything that needs its own source. Anything else -- a number, a
# date, an account, an amount, a named structural pattern -- is a claim about
# the world and must be sourced.
FACT_SIGNAL = re.compile(
    r"\d"
    r"|account|txn|transaction|wire|transfer|deposit|withdraw|amount|bank"
    r"|rs\.|inr|usd|\$"
    r"|cycle|pass-through|passthrough|typology|fan-|scatter|gather|stack|bipartite",
    re.IGNORECASE)


@dataclass
class VerificationResult:
    ok: bool
    uncited_sentences: list[str] = field(default_factory=list)
    unverifiable_citations: list[str] = field(default_factory=list)
    cited_ids: set = field(default_factory=set)

    @property
    def failures(self) -> list[str]:
        out = [f"uncited claim: {s!r}" for s in self.uncited_sentences]
        out += [f"unverifiable citation: {c!r}" for c in self.unverifiable_citations]
        return out

    def to_dict(self) -> dict:
        return {"ok": self.ok, "uncited_sentences": self.uncited_sentences,
                "unverifiable_citations": self.unverifiable_citations,
                "cited_ids": sorted(self.cited_ids), "failures": self.failures}


def split_sentences(text: str) -> list[str]:
    """Deliberately simple. The narrative is generated in short declarative
    sentences by construction (FinCEN's own SAR narrative guidance asks for
    exactly that), so a period/newline splitter is sufficient and does not
    need an NLP dependency to be reliable here."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def verify(narrative: str, valid_ids: set[str]) -> VerificationResult:
    """Check every sentence in `narrative` against `valid_ids`.

    Returns a result rather than raising, so a caller can decide whether to
    hard-fail (the narrative generator's own contract) or just inspect
    failures (tests). `sentinel.narrative.str_narrative.generate_and_verify`
    is the entry point that enforces the hard-failure contract.
    """
    result = VerificationResult(ok=True)
    for sentence in split_sentences(narrative):
        cites = CITATION.findall(sentence)
        if FACT_SIGNAL.search(sentence) and not cites:
            result.uncited_sentences.append(sentence)
            result.ok = False
        for c in cites:
            result.cited_ids.add(c)
            if c not in valid_ids:
                result.unverifiable_citations.append(c)
                result.ok = False
    return result


class NarrativeVerificationError(ValueError):
    def __init__(self, result: VerificationResult):
        self.result = result
        super().__init__("narrative failed citation verification: "
                         + "; ".join(result.failures))

"""Routing narrative drafting through an LLM, under the existing citation contract.

The template generator (`sentinel.narrative.str_narrative`) produces text whose
every sentence carries its citation *by construction*, which means the citation
verifier has nothing to reject there. That is a good property for a filed
artifact and a poor one for demonstrating that the verifier works: a check that
can never fail is not evidence of anything.

An LLM draft can fail it. So this module exists to give the verifier something
real to do, and the reportable number is the rejection rate -- how many drafts
carried an uncited claim or cited an id that does not exist in the case file,
and were therefore stopped before filing.

Two design choices are load-bearing:

**The prompt is given the allowed citation ids explicitly.** Not to make
hallucination impossible -- it does not -- but so that a rejection means the
model ignored an enumerated constraint, rather than that it was never told
what the valid ids were. A verifier that mostly catches the prompt's own
omissions measures the prompt, not the model.

**The case facts are rendered from the `CaseFile` only.** No graph access, no
stream re-read, nothing that is not already in the auditable artifact. If a
fact is not in the case file it cannot be cited, so it must not be in the
prompt either.
"""
from __future__ import annotations

from dataclasses import dataclass

from sentinel.cases.evidence import CaseFile, REGULATORY_CITATIONS
from sentinel.llm import client as llm_client

# How many transactions to enumerate in the prompt. A large case file would
# otherwise dominate the context and cost, and the narrative's job is to
# characterise the pattern, not to transcribe the ledger. The cap is applied
# to the prompt only -- `valid_citation_ids()` still admits every transaction,
# so a model that cites one outside this sample is not penalised for it.
MAX_TRANSACTIONS_IN_PROMPT = 40

SYSTEM_PROMPT = """\
You draft suspicious-activity report narratives for a financial-crime \
investigation team. You are drafting for a human reviewer who will check your \
work before anything is filed.

Structure the narrative using the FinCEN five-W convention, in this order, \
each as its own paragraph beginning with the label:

WHO:, WHAT:, WHEN:, WHERE:, WHY:, HOW:, CONCLUSION:

Absolute rules, in order of importance:

1. Every sentence that asserts a fact -- any number, date, amount, account, \
transaction, or named structural pattern -- MUST carry at least one inline \
citation in square brackets, for example [TXN-00012345] or [CASE-0007].
2. You may ONLY cite ids from the ALLOWED CITATION IDS list given to you. \
Never invent an id. Never cite an id that is not on that list, even if it \
looks plausible or follows the same format.
3. Never assert a fact that is not present in the CASE EVIDENCE below. If \
something is not stated there, do not state it. Do not estimate, infer a \
motive, or characterise the account holders.
4. Claims about law or regulation must cite the relevant instrument from the \
allowed list rather than a transaction id.
5. Write plainly. No preamble, no closing pleasantries, no markdown headers, \
no bullet points. Prose paragraphs only.

A narrative containing an uncited fact or an invented citation is rejected \
outright and never filed, so precision matters more than completeness.\
"""


@dataclass
class Draft:
    """One LLM drafting attempt, before verification."""
    text: str | None
    failure: str | None
    detail: str = ""
    model: str = ""

    @property
    def ok(self) -> bool:
        return self.text is not None and self.failure is None


def _members_block(case_file: CaseFile) -> str:
    lines = []
    for m in case_file.members:
        lines.append(f"  - account {m.account} | role {m.role} | "
                     f"in-degree {m.in_degree} | out-degree {m.out_degree}")
    return "\n".join(lines) if lines else "  (none recorded)"


def _transactions_block(case_file: CaseFile) -> str:
    txns = case_file.transactions[:MAX_TRANSACTIONS_IN_PROMPT]
    lines = []
    for t in txns:
        lines.append(f"  - {t.txn_id} | {t.ts} | {t.src} -> {t.dst} | "
                     f"{t.currency} {t.amount:,.2f}")
    if not lines:
        return "  (none recorded)"
    omitted = len(case_file.transactions) - len(txns)
    if omitted > 0:
        lines.append(f"  ... and {omitted} further transaction(s) in this "
                     f"case, not enumerated here.")
    return "\n".join(lines)


def _features_block(case_file: CaseFile) -> str:
    snapshot = case_file.feature_snapshot or {}
    if not snapshot:
        return "  (none recorded)"
    lines = []
    for key in sorted(snapshot):
        value = snapshot[key]
        if isinstance(value, float):
            value = f"{value:.4f}"
        lines.append(f"  - {key}: {value}")
    return "\n".join(lines)


def build_prompt(case_file: CaseFile) -> tuple[str, str]:
    """Return (system, user). Rendered from the case file alone."""
    allowed = sorted(case_file.valid_citation_ids())
    regulatory = sorted(REGULATORY_CITATIONS)

    user = f"""\
CASE EVIDENCE

Case id: {case_file.case_id}
Detected typology: {case_file.typology}
Typology evidence: {', '.join(case_file.typology_evidence) or '(none recorded)'}

Accounts under investigation:
{_members_block(case_file)}

Transactions:
{_transactions_block(case_file)}

Computed features at detection time:
{_features_block(case_file)}

ALLOWED CITATION IDS ({len(allowed)} total). Cite only from this list:
{chr(10).join('  ' + i for i in allowed)}

Of those, these are regulatory instruments and must be used for any claim \
about law rather than about this case's transactions:
{chr(10).join('  ' + i for i in regulatory)}

Draft the narrative now."""
    return SYSTEM_PROMPT, user


def draft(case_file: CaseFile, *, complete=llm_client.complete) -> Draft:
    """Attempt one LLM draft. Never raises; a failure is a returned reason.

    `complete` is injected so the whole path is testable without a key.
    """
    system, user = build_prompt(case_file)
    completion = complete(system, user)
    if not completion.ok:
        return Draft(text=None, failure=completion.failure,
                     detail=completion.detail, model=completion.model)
    return Draft(text=completion.text.strip(), failure=None,
                 model=completion.model)

"""STR / SAR-shaped narrative generation from a case file.

Structure follows FinCEN's own published guidance -- "Guidance on Preparing A
Complete & Sufficient Suspicious Activity Report Narrative" (FinCEN, November
2003) -- which is the most detailed *public* narrative-writing standard
available for this kind of filing: the five W's (who, what, when, where, why)
plus how (modus operandi), organised as an introduction, a body and a
conclusion. FIU-IND's own STR format is filed electronically through FINGate
2.0 in Account/Transaction Reporting Format (ARF/TRF) XML with a free-text
"grounds for suspicion" field and a 7-working-day filing clock from the date
suspicion is formed -- the same substantive "why is this suspicious, with
evidence" requirement, but with no published prose template of its own. So
the FinCEN structure is used here as the narrative template, and FIU-IND's
own field/timeline requirements are layered on top rather than invented.

This generator is template-based, not an LLM call, specifically so every
sentence it produces already carries its citation by construction -- the
citation verifier (`sentinel.narrative.citation`) should never actually have
anything to reject here. If narrative drafting is ever routed through an LLM
instead, the contract does not change: `generate_and_verify` still runs the
same verifier over the LLM's output, and a failed verification is a hard
stop, never a warning that gets filed anyway.
"""
from __future__ import annotations

from sentinel.cases.evidence import (REG_PMLA_MOR_2005, REG_RBI_PA_2025,
                                     ROLE_PASS_THROUGH, CaseFile)
from sentinel.narrative.citation import (NarrativeVerificationError,
                                         VerificationResult, verify)

# The seven-working-day clock derives from the PML (Maintenance of Records)
# Rules, 2005, NOT from the RBI PA Directions 2025 -- and its primary text has
# not been checked in this repo. See sentinel/compliance/fiu_ind.py. Hedged
# wording is deliberate: a filing deadline stated flatly and wrongly inside a
# compliance artifact is precisely the plausible-looking error this project
# keeps a bug catalogue for.
FILING_CLOCK_NOTE = (
    "Filing timeline: the applicable STR filing clock, understood to be seven "
    "working days from the date suspicion is formed "
    f"[{REG_PMLA_MOR_2005}], should be confirmed against the current Rules "
    f"before this report is filed [{REG_PMLA_MOR_2005}]."
)


def _fmt_amount(amount: float, currency: str = "USD") -> str:
    return f"{currency} {amount:,.2f}"


def _who(cf: CaseFile) -> str:
    lines = [f"WHO: {len(cf.members)} account(s) are involved in this "
             f"suspected {cf.typology.lower()} pattern [{cf.case_id}]."]
    for m in cf.members:
        cite = " ".join(f"[{e}]" for e in m.evidence[:3]) or f"[{m.account}]"
        lines.append(
            f"Account {m.account} acted as {m.role.replace('_', ' ').lower()}, "
            f"with {m.in_degree} inbound and {m.out_degree} outbound transfer(s) "
            f"inside the flagged window {cite}."
        )
    return "\n".join(lines)


def _what(cf: CaseFile) -> str:
    if not cf.transactions:
        return f"WHAT: no transactions were recorded in case file [{cf.case_id}]."
    total = sum(t.amount for t in cf.transactions)
    currency = cf.transactions[0].currency
    head_cites = " ".join(f"[{t.txn_id}]" for t in cf.transactions[:5])
    lines = [f"WHAT: {len(cf.transactions)} transaction(s) totalling "
             f"{_fmt_amount(total, currency)} moved between the accounts "
             f"above {head_cites}."]
    for t in cf.transactions[:20]:
        lines.append(
            f"On {t.ts}, {_fmt_amount(t.amount, t.currency)} moved from "
            f"account {t.src} to account {t.dst} via "
            f"{t.channel or 'an unspecified channel'} [{t.txn_id}]."
        )
    if len(cf.transactions) > 20:
        lines.append(
            f"An additional {len(cf.transactions) - 20} transaction(s) are "
            f"recorded in the case file and available on request [{cf.case_id}]."
        )
    return "\n".join(lines)


def _when(cf: CaseFile) -> str:
    if not cf.transactions:
        return f"WHEN: no transactions were recorded in the case window [{cf.case_id}]."
    ordered = sorted(cf.transactions, key=lambda t: t.ts)
    first_txn, last_txn = ordered[0], ordered[-1]
    return (
        f"WHEN: the earliest transaction in this pattern occurred at "
        f"{first_txn.ts} [{first_txn.txn_id}] and the latest at "
        f"{last_txn.ts} [{last_txn.txn_id}]. {FILING_CLOCK_NOTE}"
    )


def _where(cf: CaseFile) -> str:
    if not cf.members:
        return f"WHERE: no accounts were recorded in case file [{cf.case_id}]."
    banks = sorted({m.account.split(":", 1)[0] for m in cf.members})
    cites = " ".join(f"[{m.account}]" for m in cf.members)
    return (f"WHERE: the accounts sit at bank identifier(s) "
            f"{', '.join(banks)} {cites}.")


def _why(cf: CaseFile) -> str:
    return (f"WHY: this activity is classified {cf.typology} based on "
            + "; ".join(cf.typology_evidence) + f" [{cf.case_id}].")


def _how(cf: CaseFile) -> str:
    pass_through = [m for m in cf.members if m.role == ROLE_PASS_THROUGH]
    cites = " ".join(f"[{m.account}]" for m in pass_through) or f"[{cf.case_id}]"
    return (
        f"HOW: {len(pass_through)} of {len(cf.members)} account(s) received "
        f"and forwarded funds within the observation window {cites}, "
        f"consistent with a {cf.typology.lower()} layering structure."
    )


def _conclusion(cf: CaseFile) -> str:
    return (
        f"This report and its supporting transaction ledger are retained in "
        f"case file {cf.case_id} for the purpose of {cf.purpose.replace('_', ' ')} "
        f"[{cf.case_id}]. "
        f"The filing obligation arises under RBI Master Direction on Regulation "
        f"of Payment Aggregator, Chapter IV paragraph 13(i), which directs a "
        f"non-bank PA to register with FIU-IND and meet its reporting "
        f"requirements [{REG_RBI_PA_2025}]."
    )


def generate(case_file: CaseFile) -> str:
    """Produce the narrative text. Every generated sentence carries a
    citation by construction; see the module docstring for why."""
    sections = [_who(case_file), _what(case_file), _when(case_file),
                _where(case_file), _why(case_file), _how(case_file),
                _conclusion(case_file)]
    return "\n\n".join(sections)


def generate_and_verify(case_file: CaseFile) -> tuple[str, VerificationResult]:
    """Generate the narrative and enforce the citation contract.

    Raises `NarrativeVerificationError` on any uncited or unverifiable claim
    rather than returning a narrative that failed verification -- the
    contract this module exists to hold, whether the text came from this
    template or, in a future version, an LLM.
    """
    narrative = generate(case_file)
    result = verify(narrative, case_file.valid_citation_ids())
    if not result.ok:
        raise NarrativeVerificationError(result)
    return narrative, result

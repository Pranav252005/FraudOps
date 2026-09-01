"""Two audiences, one evidence base, the same citation contract.

`case_narrative` is written for the reviewer working the case: every
application, every shared value, what it links to, and what is being asked of
them. `merchant_brief` is written for a merchant's compliance team looking at a
queue: how many applications were flagged, on what kind of evidence, and what
the recommended action is.

Both are template-generated so that citations exist by construction, both are
verified by `sentinel.narrative.citation.verify` against the case file's own
ids, and a verification failure raises rather than warns -- the same contract
`sentinel/narrative/str_narrative.py` holds itself to, for the same reason.

**Neither will state a probability.** The natural merchant sentence is "these
seven are part of a known cluster, confidence 0.85". No such number has been
calibrated for this domain, and inventing one in front of a decline decision is
the exact failure standing rule 1 exists to prevent. The brief says what was
observed and what is recommended; it does not say how likely it is to be right.

The merchant brief also refuses to describe a flagged applicant as fraudulent.
Its subject is *shared structure between applications*, which is what was
actually observed; whether that structure is a synthetic-identity ring or a
family is what the recommended review is for.
"""
from __future__ import annotations

from sentinel.cases.identity_case import (ACTION_MANUAL_REVIEW,
                                          ACTION_MONITOR,
                                          ACTION_REQUEST_STEP_UP_KYC,
                                          IdentityCaseFile)
from sentinel.narrative.citation import NarrativeVerificationError, verify

ACTION_PROSE = {
    ACTION_MONITOR: "monitor; no additional documentation is requested",
    ACTION_MANUAL_REVIEW: "route to manual review",
    ACTION_REQUEST_STEP_UP_KYC: "request additional KYC documentation before "
                                 "approval",
}


def _who(cf: IdentityCaseFile) -> str:
    lines = [f"WHO: {len(cf.applications)} application(s) are linked in this "
             f"group [{cf.case_id}]."]
    lines.append(f"The review started from application {cf.seed_ref}, which "
                 f"an outside signal flagged [{cf.seed_ref}].")
    for a in cf.applications:
        attrs = ", ".join(a.shared_attributes) or "no attribute"
        lines.append(
            f"Application {a.app_ref} shares {attrs} with "
            f"{a.shared_with} other application(s) in this group [{a.app_ref}].")
    return "\n".join(lines)


def _what(cf: IdentityCaseFile) -> str:
    rare = [l for l in cf.links if not l.is_shared_infrastructure]
    infra = [l for l in cf.links if l.is_shared_infrastructure]
    lines = [f"WHAT: {len(cf.links)} shared attribute value(s) link these "
             f"applications [{cf.case_id}]."]
    for l in rare:
        lines.append(
            f"A shared {l.attribute} links {len(l.members)} of them and is held "
            f"by {l.population_count} application(s) across the whole queue "
            f"[{l.link_ref}].")
    for l in infra:
        lines.append(
            f"A shared {l.attribute} links {len(l.members)} of them but is held "
            f"by {l.population_count} application(s) across the queue, which is "
            f"shared infrastructure rather than evidence about these "
            f"applicants [{l.link_ref}].")
    if not rare:
        lines.append(
            f"No link in this group is specific to these applicants; every "
            f"shared value is common across the queue [{cf.case_id}].")
    return "\n".join(lines)


def _when(cf: IdentityCaseFile) -> str:
    days = sorted(a.ts_day for a in cf.applications)
    first = min(cf.applications, key=lambda a: a.ts_day)
    last = max(cf.applications, key=lambda a: a.ts_day)
    return (f"WHEN: these applications arrived between day {days[0]} "
            f"[{first.app_ref}] and day {days[-1]} [{last.app_ref}], a spread "
            f"of {days[-1] - days[0]} day(s) [{cf.case_id}].")


def _why(cf: IdentityCaseFile) -> str:
    lines = [
        f"WHY: applications that share identity attributes with each other, "
        f"where those attributes are rare across the queue, are reviewed "
        f"together because attribute reuse is how one operator submits several "
        f"applications [{cf.case_id}].",
        f"This case file states what is shared and does not estimate how likely "
        f"the group is to be fraudulent; no calibrated probability exists for "
        f"this population [{cf.case_id}].",
        f"{cf.reach_note} [{cf.case_id}]",
    ]
    return "\n".join(lines)


def _action(cf: IdentityCaseFile) -> str:
    return (f"RECOMMENDED ACTION: {ACTION_PROSE[cf.recommendation]} "
            f"[{cf.case_id}].")


def case_narrative(cf: IdentityCaseFile) -> str:
    return "\n\n".join([_who(cf), _what(cf), _when(cf), _why(cf), _action(cf)])


def case_narrative_verified(cf: IdentityCaseFile) -> tuple[str, dict]:
    """Generate and verify. Raises on failure, because this is the template
    path: every sentence carries its citation by construction, so a failure is
    a bug in this file rather than a bad draft."""
    text = case_narrative(cf)
    result = verify(text, cf.valid_citation_ids())
    if not result.ok:
        raise NarrativeVerificationError(
            f"identity case narrative failed verification: {result.failures}")
    return text, result.to_dict()


# -- merchant-facing --------------------------------------------------------

def merchant_brief(case_files: list) -> str:
    """One page for a merchant's compliance team, over a queue of case files.

    Every number is counted from the case files passed in. Nothing here is a
    literal, and there is no field a caller could use to inject one.
    """
    if not case_files:
        return ("QUEUE REVIEW: no application groups were flagged in this "
                "queue.")

    n_apps = sum(len(cf.applications) for cf in case_files)
    by_action = {a: [cf for cf in case_files if cf.recommendation == a]
                 for a in (ACTION_REQUEST_STEP_UP_KYC, ACTION_MANUAL_REVIEW,
                            ACTION_MONITOR)}
    rare_attrs = sorted({l.attribute for cf in case_files for l in cf.links
                         if not l.is_shared_infrastructure})
    largest = max(case_files, key=lambda cf: len(cf.applications))
    refs = " ".join(f"[{cf.case_id}]" for cf in case_files[:5])

    lines = [
        f"QUEUE REVIEW: {len(case_files)} group(s) of linked applications were "
        f"flagged, covering {n_apps} application(s) {refs}.",
        f"The largest group contains {len(largest.applications)} application(s) "
        f"[{largest.case_id}].",
    ]
    if rare_attrs:
        lines.append(
            f"The attributes shared within these groups, excluding values "
            f"common across the queue, are: {', '.join(rare_attrs)} "
            f"{refs}.")
    for action, group in by_action.items():
        if group:
            lines.append(
                f"{len(group)} group(s) are recommended to "
                f"{ACTION_PROSE[action]} "
                f"{' '.join(f'[{cf.case_id}]' for cf in group[:5])}.")
    lines.append(
        "No likelihood is quoted for any group. Shared attributes are what was "
        "observed; whether a group is a synthetic-identity ring or a household "
        "sharing an address is what the recommended review establishes "
        f"{refs}.")
    return "\n".join(lines)


def merchant_brief_verified(case_files: list) -> tuple[str, dict]:
    text = merchant_brief(case_files)
    valid = set()
    for cf in case_files:
        valid |= cf.valid_citation_ids()
    result = verify(text, valid)
    if not result.ok:
        raise NarrativeVerificationError(
            f"merchant brief failed verification: {result.failures}")
    return text, result.to_dict()

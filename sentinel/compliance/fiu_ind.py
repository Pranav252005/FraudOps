"""Why an STR is the right output artifact for an Indian payment aggregator.

Everything quoted below is transcribed from the **primary text** of the
Master Direction itself, not from commentary:

    Reserve Bank of India
    RBI/DPSS/2025-26/141
    CO.DPSS.POLC.No.S-633/02-14-008/2025-26
    September 15, 2025
    "Master Direction on Regulation of Payment Aggregator (PA)"
    Chapter IV -- KYC and Due Diligence, Paragraph 13 ("Due Diligence by PA")

This Master Direction supersedes the 2020/2021 Guidelines on Regulation of
Payment Aggregators and Payment Gateways (DPSS.CO.PD.No.1810/02.14.008/
2019-20 dated March 17, 2020 and CO.DPSS.POLC.No.S33/02-14-008/2020-2021
dated March 31, 2021) and the 2023 PA-Cross Border directions
(CO.DPSS.POLC.No.S-786/02-14-008/2023-24 dated October 31, 2023).

The load-bearing clause for this project -- Paragraph 13(i), verbatim:

    "Non-bank PA shall register itself with the Financial Intelligence
    Unit-India (FIU-IND) in compliance with MD on KYC and meet the reporting
    requirements listed therein."

That is the whole argument for why this system's terminal artifact is a
filing-shaped STR narrative rather than a score: a non-bank payment
aggregator is not merely permitted to report suspicion to FIU-IND, it is
directed to register with FIU-IND and meet its reporting requirements. The
detector exists to get an analyst to that filing faster and with the evidence
already assembled.

Two supporting clauses, also verbatim:

    13(a): "A PA shall undertake customer due diligence (CDD) of its
    merchants in accordance with MD on KYC."

    13(j): "A PA, including an existing PA whose application is pending with
    Reserve Bank of India for authorisation, shall ensure that merchants
    onboarded till December 31, 2025, comply with the above due diligence
    requirements within one year from the date of this MD. From January 1,
    2026, merchants should be onboarded in accordance with due diligence
    requirements prescribed in this MD."

13(j) is why the merchant-account mule vector is live *now* rather than
hypothetical: the re-onboarding deadline has passed, so every PA in India is
currently carrying merchants it has had to re-diligence, and the ones that
fail that diligence are exactly the accounts this system is looking for.

--- What is NOT verified against primary text ---

The **seven-working-day STR filing clock** asserted in
`sentinel/narrative/str_narrative.py` (`FILING_CLOCK_NOTE`) does **not**
come from this Master Direction. It derives from the Prevention of
Money-Laundering (Maintenance of Records) Rules, 2005 -- and the primary text
of those Rules has NOT been pulled and checked in this repo. Treat that
number as unverified until someone reads Rule 8 of the PML (Maintenance of
Records) Rules directly. It is flagged here rather than quietly asserted,
because a filing deadline that is wrong in a compliance-facing artifact is
exactly the class of plausible-looking error this project keeps a bug
catalogue for.
"""
from __future__ import annotations

# Primary-source citation, carried as data so a case file or STR export can
# name the authority it is being produced under rather than hard-coding a
# regulator's name in a string somewhere in the UI.
PA_DIRECTIONS_2025 = {
    "issuer": "Reserve Bank of India",
    "reference": "RBI/DPSS/2025-26/141",
    "circular_no": "CO.DPSS.POLC.No.S-633/02-14-008/2025-26",
    "dated": "2025-09-15",
    "title": "Master Direction on Regulation of Payment Aggregator (PA)",
    "chapter": "Chapter IV -- KYC and Due Diligence",
    "verified_against_primary_text": True,
}

# Paragraph 13(i), quoted verbatim from the Master Direction.
FIU_IND_REGISTRATION_CLAUSE = (
    "Non-bank PA shall register itself with the Financial Intelligence "
    "Unit-India (FIU-IND) in compliance with MD on KYC and meet the "
    "reporting requirements listed therein."
)
FIU_IND_REGISTRATION_PARA = "13(i)"

# Paragraph 13(a), quoted verbatim.
CDD_CLAUSE = (
    "A PA shall undertake customer due diligence (CDD) of its merchants in "
    "accordance with MD on KYC."
)
CDD_PARA = "13(a)"

# The STR filing clock. Sourced to the PML (Maintenance of Records) Rules,
# 2005 -- NOT to the PA Directions above, and NOT verified against the Rules'
# own primary text in this repo. See the module docstring.
STR_FILING_DAYS = 7
STR_FILING_BASIS = "PML (Maintenance of Records) Rules, 2005"
STR_FILING_VERIFIED = False


def authority_note() -> str:
    """One line naming the authority an STR produced here is filed under."""
    d = PA_DIRECTIONS_2025
    return (f"{d['issuer']} {d['reference']} ({d['circular_no']}), "
            f"{d['title']}, {d['chapter']}, para {FIU_IND_REGISTRATION_PARA}, "
            f"dated {d['dated']}.")

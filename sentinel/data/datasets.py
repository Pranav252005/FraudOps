"""Which AMLworld split is in play, and which of its constants were measured.

THE PROBLEM THIS SOLVES IS NOT FILE PATHS. Swapping `HI-Small` for `LI-Small`
in a few `open()` calls takes ten minutes and produces a plausible wrong answer,
because several constants in `sentinel/config.py` are not settings -- they are
MEASUREMENTS OF HI-Small, and their own comments say so:

    EVAL_END_DAY = 10                 "363 of 370 rings begin inside it"
    STRUCTURAL_RECALL_CEILING = 0.733 "266 of the 363 evaluable rings"
    EXCLUDED_FEATURES = {"channel"}   "86.6% of laundering rows are ACH
                                       against an 11.8% base rate"

`EVAL_END_DAY` is the leak boundary. It exists because HI-Small's last eight
days carry 715 edges of which 652 are laundering, so evaluating across them
would make "timestamp after day 10" a near-perfect classifier. That is a fact
about HI-Small's generator run. Carrying the number 10 onto a different split
either leaks (if the new split's tail turns bad earlier) or silently discards
good data (if it turns bad later). Nothing would crash. Every downstream
interval would simply be wrong, and this repository's whole bug catalogue is
made of exactly that shape.

SO A SPLIT WITHOUT ITS OWN DERIVED CONSTANTS IS REFUSED RATHER THAN DEFAULTED.
`LI-Small` and `HI-Medium` are registered here because the files are on disk and
their ring counts are read from them, but their `eval_end_day` and
`structural_recall_ceiling` are `None`. Asking for one raises, with the command
that would derive it. A loud stop beats a quiet reuse of another dataset's
boundary.

Run `python scripts/derive_dataset_constants.py <split>` to produce them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class DatasetNotDerived(RuntimeError):
    """A constant was requested for a split it has never been measured on."""


@dataclass(frozen=True)
class Dataset:
    """One AMLworld split, and how much of it has been characterised.

    `eval_end_day` and `structural_recall_ceiling` are deliberately optional.
    A dataset whose leak boundary nobody has derived is a dataset this codebase
    must refuse to evaluate on, not one it should guess for.
    """

    name: str
    corpus_key: str
    #: Labelled ring blocks in the Patterns file. Counted from the file, not
    #: typed -- see `count_rings`.
    eval_end_day: int | None = None
    structural_recall_ceiling: float | None = None
    #: Where the two constants above came from. Empty when they are None.
    provenance: str = ""

    # --- file layout --------------------------------------------------------
    # Every split follows the same three-file naming pattern, verified against
    # the files actually on disk for HI-Small, LI-Small and HI-Medium.

    def trans(self, root: Path) -> Path:
        return root / "data" / "amlworld" / f"{self.name}_Trans.csv"

    def accounts(self, root: Path) -> Path:
        return root / "data" / "amlworld" / f"{self.name}_accounts.csv"

    def patterns(self, root: Path) -> Path:
        return root / "data" / "amlworld" / f"{self.name}_Patterns.txt"

    def stream_dir(self, root: Path) -> Path:
        """Where this split's compiled stream lives.

        HI-Small keeps the bare `data/stream` it has always used, so every
        committed result and the existing 57 MB compilation stay valid without
        a rebuild. Every other split gets its own directory.

        THIS EXISTS BECAUSE THE PATH WAS HARDCODED IN 27 FILES while the INPUT
        already honoured SENTINEL_DATASET. Compiling a second split would have
        overwritten the first in place, and every eval would then have read
        HI-Medium's edges while reporting them under HI-Small's name -- no
        crash, just a different dataset behind the same numbers. That is the
        exact failure this module exists to refuse, one layer down.
        """
        name = "stream" if self.name == DEFAULT else f"stream-{self.name}"
        return root / "data" / name

    def result_path(self, root: Path, filename: str) -> Path:
        """Where a result JSON for this split belongs.

        Same hazard as `stream_dir`, one layer further out: every eval script
        writes a hardcoded `data/<name>.json`, so running one under a second
        split would overwrite the first split's committed result in place and
        report HI-Medium's numbers under HI-Small's filename.

        HI-Small keeps the bare filename so every committed result stays where
        it is; other splits get a suffixed one.
        """
        if self.name == DEFAULT:
            return root / "data" / filename
        stem, _, ext = filename.rpartition(".")
        return root / "data" / f"{stem}-{self.name}.{ext}"

    def present(self, root: Path) -> bool:
        return all(p.is_file() for p in
                   (self.trans(root), self.accounts(root), self.patterns(root)))

    # --- the refusing accessors --------------------------------------------

    def require_eval_end_day(self) -> int:
        if self.eval_end_day is None:
            raise DatasetNotDerived(self._underived("eval_end_day"))
        return self.eval_end_day

    def require_structural_recall_ceiling(self) -> float:
        if self.structural_recall_ceiling is None:
            raise DatasetNotDerived(
                self._underived("structural_recall_ceiling"))
        return self.structural_recall_ceiling

    def _underived(self, const: str) -> str:
        return (
            f"{const} has never been measured on {self.name}. It is a "
            f"MEASUREMENT of a particular generator run, not a setting: "
            f"EVAL_END_DAY is the leak boundary and the structural ceiling is "
            f"a ring-size count. Reusing HI-Small's value here would not "
            f"crash -- it would silently leak or silently discard data, and "
            f"every interval downstream would be wrong.\n"
            f"    Derive it:  python scripts/derive_dataset_constants.py "
            f"{self.name}\n"
            f"then record the result in sentinel/data/datasets.py with its "
            f"provenance.")


# HI-Small is the only split whose constants are derived, and they were derived
# in Phase 0 of this project. The provenance string is the justification that
# already lives in sentinel/config.py, kept beside the numbers it explains.
HI_SMALL = Dataset(
    name="HI-Small",
    corpus_key="amlworld-hi-small",
    eval_end_day=10,
    structural_recall_ceiling=0.733,
    provenance=(
        "Phase 0, docs/PHASE0-FINDINGS.md. Days 0-9 carry 99.98% of edges; "
        "days 10-17 carry 715 edges of which 652 are laundering, so evaluating "
        "past day 10 would make the timestamp a near-perfect classifier. 363 "
        "of 370 rings begin inside the boundary, and 266 of those 363 have "
        "more than two accounts visible in-window, which is the ceiling. "
        "RE-DERIVED 2026-09-05 and reproduces exactly, once 'visible "
        "in-window' is read as 'on edges before the boundary' -- counting "
        "every account of the ring instead gives 282 and was what made this "
        "look unreconstructible for a day."),
)

# Registered, present on disk, and NOT characterised. The ring counts differ by
# more than an order of magnitude across these three, which is the whole reason
# the second one is worth having and the reason none of them may borrow the
# first one's boundary.
# Derived 2026-09-05 by `scripts/derive_dataset_constants.py` under the rule
# fixed in prereg/dataset_constants.md BEFORE either split was scanned. The
# leak-boundary rule was validated first against HI-Small, which it reproduces
# exactly: day 10, a 715-edge tail carrying 652 laundering edges.
#
# ALL THREE CEILINGS ARE NOW ONE QUANTITY, and it is Phase 0's.
# An earlier revision of this comment said HI-Small's 0.733 "cannot be
# re-derived from its own recorded provenance" and that a cross-split
# comparison was therefore invalid. **That was wrong, and the error was in the
# derivation, not the constant.** "More than two accounts visible in-window"
# means accounts on edges BEFORE the boundary, not every account the ring ever
# touches. Read that way it reproduces 266/363 = 0.733 exactly -- and does so
# whether or not self-loops are dropped and whether accounts are keyed by
# (bank, account) or bare id, so the truncation is the whole of it.
# `scripts/derive_dataset_constants.py --check` now asserts the ceiling as well
# as the boundary. LI-Small and HI-Medium below were re-derived under the
# corrected reading and MOVED: 0.810 -> 0.802 and 0.758 -> 0.720.
LI_SMALL = Dataset(
    name="LI-Small",
    corpus_key="amlworld-li-small",
    eval_end_day=10,
    structural_recall_ceiling=0.802,
    provenance=(
        "Derived 2026-09-05, prereg/dataset_constants.md. 6,924,049 edges "
        "(self-loops excluded) over days 0-16, base rate 0.000582. The tail "
        "from day 10 holds 148 edges at a 0.9054 laundering rate, 1555x the "
        "base rate, so the boundary is day 10. 116 of 117 rings begin inside "
        "it and 93 of those have more than two accounts VISIBLE IN-WINDOW, i.e. "
        "on edges before the boundary. Ceiling corrected 2026-09-05 from "
        "0.810, which counted every account of the ring; see D1."),
)

# HI-Medium's boundary is day 16, NOT day 10. This is the concrete
# demonstration of why this module refuses to default: carrying HI-Small's 10
# onto HI-Medium would have silently discarded days 10-15 -- six days of good
# data -- and nothing would have crashed.
HI_MEDIUM = Dataset(
    name="HI-Medium",
    corpus_key="amlworld-hi-medium",
    eval_end_day=16,
    structural_recall_ceiling=0.720,
    provenance=(
        "Derived 2026-09-05, prereg/dataset_constants.md. 31,898,238 edges "
        "(self-loops excluded) over days 0-27, base rate 0.001198. The tail "
        "from day 16 holds 4,503 edges at a 0.9043 laundering rate, 755x the "
        "base rate, so the boundary is day 16 -- six days later than "
        "HI-Small's. 2,721 of 2,756 rings begin inside it and 1,958 of those "
        "have more than two accounts VISIBLE IN-WINDOW, i.e. on edges before "
        "the boundary. Ceiling corrected 2026-09-05 from 0.758, which counted "
        "every account of the ring; see D1."),
)

REGISTRY = {d.name: d for d in (HI_SMALL, LI_SMALL, HI_MEDIUM)}

DEFAULT = HI_SMALL.name

#: Environment variable selecting the split. Deliberately an env var rather
#: than a CLI flag on each script: the choice has to reach `sentinel/config.py`
#: at import time, and a flag threaded through a dozen entry points is a flag
#: one of them will forget.
ENV_VAR = "SENTINEL_DATASET"


def active(env: dict | None = None) -> Dataset:
    """The split this process is running against."""
    env = os.environ if env is None else env
    name = env.get(ENV_VAR, DEFAULT)
    if name not in REGISTRY:
        raise KeyError(
            f"{ENV_VAR}={name!r} is not a known AMLworld split. "
            f"Known: {sorted(REGISTRY)}. Download one with "
            f"scripts/download_amlworld.bat, then register it in "
            f"sentinel/data/datasets.py.")
    return REGISTRY[name]


def active_stream_dir(root: Path, env: dict | None = None) -> Path:
    """The compiled-stream directory for the split this process is running as.

    A single call every entry point can use, so no script has to remember to
    thread the dataset through to its own path.
    """
    return active(env).stream_dir(root)


def active_result_path(root: Path, filename: str, env: dict | None = None) -> Path:
    """Result path for the split this process is running as."""
    return active(env).result_path(root, filename)


def count_rings(dataset: Dataset, root: Path) -> int:
    """Labelled ring blocks in the split's Patterns file.

    Counted from the file rather than stored as a literal, so it cannot drift
    from the data the way a typed constant can (standing rule 1). Cheap: the
    Patterns files are kilobytes to a few megabytes, never the multi-gigabyte
    transaction CSV.
    """
    path = dataset.patterns(root)
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is missing. Fetch it with "
            f"scripts/download_amlworld.bat {dataset.name}")
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("BEGIN"):
                n += 1
    return n

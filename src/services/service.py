"""AgentCore Platform v1.0"""

# Domain service: the caller-context contract and the process-type catalogue for
# the shift handover report. Nodes and the HTTP adapter both read this module so
# there is exactly one definition of what a caller may send and what each
# process type renders as.
#
# The contract is deliberately narrow: the only caller-settable field is an
# inert identifier drawn from a closed set. Unknown keys are DROPPED rather than
# ignored — an ignored key still travels into the invocation context, and any
# value that reaches a node result is scanned by the framework's output gate, so
# an unvalidated field can fail the whole run at the first node.

from __future__ import annotations

import math
from typing import Any, Dict, Final, FrozenSet, List, Tuple

# The closed set of process types this template renders. Values are inert
# identifiers: lowercase ASCII words, never free text from the caller.
PROCESS_TYPES: Final[FrozenSet[str]] = frozenset({"discrete", "process", "semiconductor"})
DEFAULT_PROCESS_TYPE: Final[str] = "discrete"

# Report headers per process type. The process type selects the report heading
# and its production-mode label; it does not add or remove report sections.
REPORT_HEADERS: Final[Dict[str, str]] = {
    "discrete": "製造シフト引継ぎレポート（離散生産）",
    "process": "製造シフト引継ぎレポート（プロセス生産）",
    "semiconductor": "製造シフト引継ぎレポート（半導体製造）",
}

# Every key a caller may set. Anything else is dropped at the boundary.
CALLER_CONTEXT_FIELDS: Final[FrozenSet[str]] = frozenset({"process_type"})

# Structural caps on the raw shift log text.
MIN_SHIFT_LOG_CHARS: Final[int] = 10
MAX_SHIFT_LOG_CHARS: Final[int] = 60_000
MAX_SHIFT_LOG_LINES: Final[int] = 2_000

# Per-section entry caps, so a hostile log cannot make the report unbounded.
MAX_ENTRIES_PER_SECTION: Final[int] = 200

# Bounds for every caller-controlled number parsed out of the shift log. A KPI
# figure outside this range, or a non-finite one, is not a plausible shift
# reading; accepting it would let `inf` compare its way to "target achieved".
MAX_KPI_MAGNITUDE: Final[float] = 1e12


def report_header(process_type: str) -> str:
    """Report heading for a process type; unknown values fall back to the default."""
    return REPORT_HEADERS.get(process_type, REPORT_HEADERS[DEFAULT_PROCESS_TYPE])


def normalize_caller_context(raw: Any) -> Tuple[Dict[str, str], List[str]]:
    """Reduce a caller-supplied mapping to the declared, validated context.

    Returns ``(validated, rejected)``. ``validated`` holds only declared keys
    whose values passed validation. ``rejected`` names the fields that failed —
    field NAMES only, never the offending values, which are caller data and must
    not be echoed back into an error path.

    Unknown keys are dropped silently: they are not part of the contract, and
    carrying them forward is what turns an unrecognised field into a run-ending
    failure deeper in the pipeline.
    """
    validated: Dict[str, str] = {}
    rejected: List[str] = []
    if not isinstance(raw, dict):
        return validated, rejected

    for key in sorted(CALLER_CONTEXT_FIELDS):
        if key not in raw:
            continue
        value = raw[key]
        if key == "process_type":
            if isinstance(value, str) and value.lower() in PROCESS_TYPES:
                validated[key] = value.lower()
            else:
                rejected.append(key)
    return validated, rejected


def finite_in_range(value: Any, *, limit: float = MAX_KPI_MAGNITUDE) -> float | None:
    """Parse a caller-controlled number, failing CLOSED on anything unusable.

    Rejects booleans, non-numeric text, NaN and the infinities, and magnitudes
    beyond ``limit``. Non-finite values matter here because they parse cleanly
    and then compare False against every threshold — an achievement test against
    NaN silently reports "not achieved" for every KPI, and a value that overflows
    to infinity reports the opposite. Returns ``None`` when the value cannot be
    used, so the caller drops the row rather than acting on a number it cannot
    trust.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        candidate = value.replace(",", "").strip()
        if not candidate:
            return None
        try:
            parsed = float(candidate)
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        parsed = float(value)
    else:
        return None
    if not math.isfinite(parsed):
        return None
    if abs(parsed) > limit:
        return None
    return parsed

# AgentCore Platform v1.0 - MFG-C2-024
# Inner domain node: extract KPI actual vs target pairs from the shift log.
# required_trust_level = ANONYMOUS. The outer graph passes its invocation context
# into the subgraph unchanged, so an inner gate stricter than the outer entry
# gate would deny the very caller the outer gate just admitted; the entry check
# belongs on the outer pre_process node, which holds it.

import json
import re
from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import MAX_ENTRIES_PER_SECTION, finite_in_range

# Shift logs write the actual/target pair in several house styles. All three
# forms below appear in real handover sheets; the label may carry the colon or
# the figures may, and the pair may be written bare after a known metric name.
_KPI_PATTERNS: List[re.Pattern[str]] = [
    # 生産数: 実績 450 / 目標 500
    re.compile(r"([^\n]{2,30})[:\uff1a]\s*実績[:\uff1a]?\s*([\d,.]+)\s*[/\uff0f]\s*目標[:\uff1a]?\s*([\d,.]+)"),
    # 生産数 実績: 450 / 目標: 500
    re.compile(r"([^\n:\uff1a]{2,30}?)\s*実績[:\uff1a]\s*([\d,.]+)\s*[/\uff0f]\s*目標[:\uff1a]\s*([\d,.]+)"),
    # Output: Actual 450 / Target 500   (and "Output Actual: 450 / Target: 500")
    re.compile(
        r"([^\n]{2,30})[:\uff1a]\s*Actual[:\uff1a]?\s*([\d,.]+)\s*[/]\s*Target[:\uff1a]?\s*([\d,.]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([^\n:\uff1a]{2,30}?)\s*Actual[:\uff1a]\s*([\d,.]+)\s*[/]\s*Target[:\uff1a]\s*([\d,.]+)",
        re.IGNORECASE,
    ),
    # 生産数 450/500
    re.compile(r"(生産数|稼働率|不良率|歩留まり|Yield|OEE)\s+([\d,.]+)[/\uff0f]([\d,.]+)", re.IGNORECASE),
]


def _extract_kpis(text: str) -> List[Dict[str, object]]:
    """Extract actual/target KPI pairs, dropping any figure that is not usable.

    Both figures come from caller-supplied text, so both go through the bounded
    finite parser before any arithmetic. A run of digits long enough to overflow
    to infinity would otherwise pass float() and then compare greater than every
    target — reporting a missed KPI as achieved. A row whose figures cannot be
    trusted is dropped and counted, never rendered with a guessed value.
    """
    kpis: List[Dict[str, object]] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(kpis) >= MAX_ENTRIES_PER_SECTION:
            break
        for pattern in _KPI_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            name = match.group(1).strip(" \t:：-・")
            if not name or name in seen:
                break
            actual = finite_in_range(match.group(2))
            target = finite_in_range(match.group(3))
            if actual is None or target is None:
                break
            seen.add(name)
            gap = actual - target
            gap_pct = round((gap / target) * 100, 1) if target != 0 else 0.0
            kpis.append(
                {
                    "kpi": name,
                    "actual": actual,
                    "target": target,
                    "gap": round(gap, 2),
                    "gap_pct": gap_pct,
                    "achieved": actual >= target,
                }
            )
            break
    return kpis


class KPISummarizeNode(FunctionNode):
    """Summarize KPI actual vs target from shift log text."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        validated_input = state.get("validated_input") or state.get("user_input", "")
        if not validated_input:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["KPISummarizeNode: no validated input"],
            }
        kpis = _extract_kpis(validated_input)
        achieved = sum(1 for k in kpis if k.get("achieved"))
        emit_trace_event(
            "kpi_summarized",
            {"kpi_count": len(kpis), "achieved_count": achieved},
            state,
        )
        return {
            "kpi_summary": json.dumps(kpis, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }

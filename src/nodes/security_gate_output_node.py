# AgentCore Platform v1.0 - MFG-C2-024
# Outer post_process output gate: the last check before the handover report
# reaches the caller. required_trust_level = ANONYMOUS.
#
# Two independent layers, each with its own audit event:
#
#   1. Credential scan — the framework's own detector plus the operational
#      secret shapes that turn up in maintenance notes (`password=`, `api_key=`).
#      The framework detector is called rather than approximated: a value the
#      framework catches and this node misses would be returned inside this
#      node's own delta, the framework's output check would raise on it, and the
#      wrapper would discard this node's delta — withholding included. A narrower
#      local pattern set is therefore a way around the withholding, not a
#      smaller version of it.
#
#   2. Report completeness — every CRITICAL incident the pipeline recorded must
#      appear in the rendered report, marked non-suppressible. Suppressing a
#      critical event from a handover report is the failure this template exists
#      to prevent (ISO 9001 section 8.5.1 / JISHA), so the boundary enforces it
#      instead of trusting the renderer to have done it.
#
# On a violation the node returns an error status AND blanks every field that
# carries report text, then puts a fixed notice in the caller-facing slot. Both
# halves are required: the envelope the framework builds is
# `formatted_output or result`, so returning an error while leaving `result`
# populated ships the ungated report anyway, and a falsy notice re-opens the same
# fallback. The notice is a constant — nothing is read back out of the state
# that was just blanked.
#
# The gate helper is a module-level function rather than an instance method so
# it can be exercised on its own, with no node instance and no state.

import json
import re
from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security.credential_detector import detect_credentials
from shared.utils.audit_logger import emit_trace_event
from src.services.failure_message import EMPTY_INPUT, INPUT_REJECTED, INVALID_VALUE, TOO_LONG

# Closed set of violation labels. A violation names its class — never the text
# that matched, which is the very content being withheld.
VIOLATION_CREDENTIAL = "credential_pattern"
VIOLATION_CRITICAL_OMITTED = "critical_incident_omitted"

WITHHELD_NOTICE = (
    "レポートは出力検査により保留されました。"
    "Report withheld by the output check. No content is released; "
    "review the shift log and re-submit."
)

# Operational secret shapes the framework detector does not cover. Kept as an
# addition to it, never as a replacement.
_LOCAL_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?i)password\s*[:=]\s*\S+"),
    re.compile(r"(?i)api[_\-]?key\s*[:=]\s*\S+"),
    re.compile(r"(?i)secret\s*[:=]\s*\S+"),
    re.compile(r"(?i)token\s*[:=]\s*\S+"),
]

# Fields that can carry report text out of this graph. The gate blanks all of
# them together; the inventory is asserted in the test suite so a new
# output-bearing field cannot quietly join the state without joining this list.
OUTPUT_BEARING_FIELDS = (
    "result",
    "formatted_output",
    "parsed_shift_data",
    "kpi_summary",
    "incident_report",
)


def _security_gate_output(output: str) -> List[str]:
    """Credential scan over the rendered report; empty list means clean."""
    if not output:
        return []
    if detect_credentials(output) or any(p.search(output) for p in _LOCAL_PATTERNS):
        return [VIOLATION_CREDENTIAL]
    return []


def _missing_critical_incidents(output: str, incident_report: str) -> bool:
    """True when a recorded CRITICAL incident is absent from the rendered report."""
    if not incident_report:
        return False
    try:
        incidents: List[Dict[str, Any]] = json.loads(incident_report)
    except (json.JSONDecodeError, TypeError):
        # An unreadable incident record cannot be shown to be represented in the
        # report, so it is treated as a violation rather than as an absence.
        return True
    if not isinstance(incidents, list):
        return True
    for incident in incidents:
        if not isinstance(incident, dict) or incident.get("severity") != "CRITICAL":
            continue
        description = str(incident.get("description", ""))
        if description and description not in output:
            return True
        if "NON-SUPPRESSIBLE" not in output:
            return True
    return False


def _cleared_output_state() -> Dict[str, str]:
    """Blank every output-bearing field so nothing survives into the envelope."""
    return {field: "" for field in OUTPUT_BEARING_FIELDS}


# Reason code -> the sentence the caller reads. A code with no entry falls
# back to the generic one rather than leaking the code itself.
_DEGRADED_MESSAGES = {
    "EMPTY_INPUT": EMPTY_INPUT,
    "QUESTION_TOO_LONG": TOO_LONG,
    "INVALID_REQUEST": INVALID_VALUE,
}


class SecurityGateOutputNode(FunctionNode):
    """Output gate: credential scan and critical-incident completeness."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        # A run declined upstream has nothing to format. Render the reason as
        # the caller-facing body and carry the marker onward.
        marker = state.get("error_code")
        if marker:
            message = _DEGRADED_MESSAGES.get(marker, INPUT_REJECTED)
            emit_trace_event("post_process_degraded", {"reason": marker}, state)
            return {
                "status": AgentStatus.SUCCESS.value,
                "error_code": marker,
                "formatted_output": message,
                "result": message,
            }
        result = state.get("result") or ""
        violations = _security_gate_output(result)
        if _missing_critical_incidents(result, state.get("incident_report") or ""):
            violations.append(VIOLATION_CRITICAL_OMITTED)

        if violations:
            emit_trace_event(
                "security_gate_output_violation",
                {"violations": violations, "output_length": len(result)},
                state,
            )
            return {
                **_cleared_output_state(),
                "formatted_output": WITHHELD_NOTICE,
                "status": AgentStatus.ERROR.value,
                "error_log": ["SecurityGateOutputNode: report withheld -- " + ", ".join(violations)],
            }

        emit_trace_event(
            "security_gate_output_passed",
            {"output_length": len(result)},
            state,
        )
        return {"formatted_output": result, "status": AgentStatus.SUCCESS.value}

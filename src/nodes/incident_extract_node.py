# AgentCore Platform v1.0 - MFG-C2-024
# Inner domain node: extract incidents from the shift log.
# CRITICAL incidents are non-suppressible (ISO 9001 section 8.5.1 / JISHA).
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

from src.services.service import MAX_ENTRIES_PER_SECTION

_SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_INCIDENT_RE = re.compile(
    r"(?:異常|インシデント|Incident|障害|不良|エラー|Error|Fault|故障|事故|Alarm)",
    re.IGNORECASE,
)
_ROOT_CAUSE_RE = re.compile(r"(?:原因|Cause|Root|原因調査)", re.IGNORECASE)


def _classify_severity(text: str) -> str:
    t = text.upper()
    if any(k in t for k in ["CRITICAL", "重大", "致命", "停止", "STOP", "緊急"]):
        return "CRITICAL"
    if any(k in t for k in ["HIGH", "高", "URGENT", "要緊急対応"]):
        return "HIGH"
    if any(k in t for k in ["MEDIUM", "中", "WARN", "警告"]):
        return "MEDIUM"
    return "LOW"


def _extract_incidents(text: str) -> List[Dict[str, Any]]:
    lines = text.split("\n")
    incidents: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        ls = line.strip()
        if not ls or not _INCIDENT_RE.search(ls):
            continue
        if len(incidents) >= MAX_ENTRIES_PER_SECTION:
            break
        sev = _classify_severity(ls)
        root_cause = "調査中 (under investigation)"
        for next_line in lines[i + 1 : i + 4]:
            ns = next_line.strip()
            if ns and _ROOT_CAUSE_RE.search(ns):
                root_cause = ns
                break
        incidents.append(
            {
                "severity": sev,
                "description": ls,
                "root_cause": root_cause,
                "suppressible": sev != "CRITICAL",
            }
        )
    incidents.sort(key=lambda x: _SEVERITY_RANK.get(x["severity"], 0), reverse=True)
    return incidents


class IncidentExtractNode(FunctionNode):
    """Extract incidents; CRITICAL severity is non-suppressible per ISO 9001 8.5.1."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        validated_input = state.get("validated_input") or state.get("user_input", "")
        if not validated_input:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["IncidentExtractNode: no validated input"],
            }
        incidents = _extract_incidents(validated_input)
        critical = sum(1 for inc in incidents if inc["severity"] == "CRITICAL")
        emit_trace_event(
            "incidents_extracted",
            {"total": len(incidents), "critical_count": critical},
            state,
        )
        return {
            "incident_report": json.dumps(incidents, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }

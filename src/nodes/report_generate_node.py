# AgentCore Platform v1.0 - MFG-C2-024
# Inner domain node: compose the shift handover report for the caller's process
# type (discrete / process / semiconductor).
# required_trust_level = ANONYMOUS. The outer graph passes its invocation context
# into the subgraph unchanged, so an inner gate stricter than the outer entry
# gate would deny the very caller the outer gate just admitted; the entry check
# belongs on the outer pre_process node, which holds it.
#
# The process type is read from `validated_context`, which the outer graph seeds
# into this subgraph's initial state. It is deliberately NOT read from
# `input_context`: that key exists in the inner state schema but the framework
# never populates it for a subgraph, so a reader there compares against an empty
# mapping on every real invocation and silently renders the default heading.

import json
from typing import Any, ClassVar, Dict, List

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.service import DEFAULT_PROCESS_TYPE, report_header


def _fmt_parsed(parsed: Dict[str, Any]) -> str:
    rows: List[str] = ["## シフト基本情報"]
    if parsed.get("equipment_ids"):
        rows.append(f"- 設備: {', '.join(str(e) for e in parsed['equipment_ids'])}")
    if parsed.get("shift_period"):
        rows.append(f"- シフト: {parsed['shift_period']}")
    if parsed.get("operator"):
        rows.append(f"- 担当者: {parsed['operator']}")
    if parsed.get("equipment_alerts"):
        rows.append(f"\n### 設備アラート ({len(parsed['equipment_alerts'])}件)")
        for alert in parsed["equipment_alerts"]:
            rows.append(f"  - {alert}")
    if parsed.get("open_items"):
        rows.append(f"\n### 申し送り事項 ({len(parsed['open_items'])}件)")
        for item in parsed["open_items"]:
            rows.append(f"  - {item}")
    return "\n".join(rows)


def _fmt_kpi(kpis: List[Dict[str, Any]]) -> str:
    if not kpis:
        return "## KPIサマリー\nKPIデータなし"
    rows = [
        "## KPIサマリー",
        "| KPI | 実績 | 目標 | 差異 | 達成 |",
        "|-----|------|------|------|------|",
    ]
    for k in kpis:
        mark = "o" if k.get("achieved") else "x"
        gap_str = f"{k.get('gap', 0):+.2f} ({k.get('gap_pct', 0):+.1f}%)"
        rows.append(
            f"| {k.get('kpi', '-')} | {k.get('actual', '-')} " f"| {k.get('target', '-')} | {gap_str} | {mark} |"
        )
    return "\n".join(rows)


def _fmt_incidents(incidents: List[Dict[str, Any]]) -> str:
    if not incidents:
        return "## インシデント\nインシデントなし"
    rows = ["## インシデント（重要度順）"]
    for inc in incidents:
        sup_note = "" if inc.get("suppressible") else " [必須記載/NON-SUPPRESSIBLE]"
        rows.append(
            f"- [{inc.get('severity', '?')}]{sup_note} "
            f"{inc.get('description', '')}\n"
            f"  暫定原因: {inc.get('root_cause', '調査中')}"
        )
    return "\n".join(rows)


def _build_report(
    process_type: str,
    parsed: Dict[str, Any],
    kpis: List[Dict[str, Any]],
    incidents: List[Dict[str, Any]],
) -> str:
    return "\n\n".join(
        [
            f"# {report_header(process_type)}",
            _fmt_parsed(parsed),
            _fmt_kpi(kpis),
            _fmt_incidents(incidents),
        ]
    )


class ReportGenerateNode(FunctionNode):
    """Generate the structured shift handover report for the caller's process type."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        try:
            context: Dict[str, Any] = json.loads(state.get("validated_context") or "{}")
            kpis: List[Dict[str, Any]] = json.loads(state.get("kpi_summary") or "[]")
            incidents: List[Dict[str, Any]] = json.loads(state.get("incident_report") or "[]")
            parsed: Dict[str, Any] = json.loads(state.get("parsed_shift_data") or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"ReportGenerateNode: parse error -- {exc}"],
            }
        process_type = context.get("process_type") or DEFAULT_PROCESS_TYPE
        report = _build_report(process_type, parsed, kpis, incidents)
        emit_trace_event(
            "report_generated",
            {
                "process_type": process_type,
                "kpi_count": len(kpis),
                "incident_count": len(incidents),
                "report_length": len(report),
            },
            state,
        )
        return {"result": report, "status": AgentStatus.SUCCESS.value}

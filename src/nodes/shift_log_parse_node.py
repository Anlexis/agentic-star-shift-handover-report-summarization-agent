# AgentCore Platform v1.0 - MFG-C2-024
# Inner domain node: parse structured elements from Japanese shift log text.
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


def _parse_shift_log(text: str) -> Dict[str, Any]:
    lines = text.strip().split("\n")
    equipment_ids: List[str] = []
    equipment_alerts: List[str] = []
    open_items: List[str] = []
    parsed: Dict[str, Any] = {
        "equipment_ids": equipment_ids,
        "shift_period": "",
        "operator": "",
        "equipment_alerts": equipment_alerts,
        "open_items": open_items,
        "raw_line_count": len(lines),
    }
    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        eq = re.search(r"(?:設備(?:ID)?|Equipment|Machine)\s*[:=]\s*([\w\-]+)", ls, re.IGNORECASE)
        if eq and eq.group(1) not in equipment_ids and len(equipment_ids) < MAX_ENTRIES_PER_SECTION:
            equipment_ids.append(eq.group(1))
        if not parsed["shift_period"]:
            sm = re.search(r"(?:シフト|Shift)\s*[:]\s*(.+)", ls, re.IGNORECASE)
            if sm:
                parsed["shift_period"] = sm.group(1).strip()
        if not parsed["operator"]:
            om = re.search(r"(?:担当者?|Operator)\s*[:]\s*(.+)", ls, re.IGNORECASE)
            if om:
                parsed["operator"] = om.group(1).strip()
        if (
            re.search(r"(?:警告|アラート|ALERT|WARNING)", ls, re.IGNORECASE)
            and len(equipment_alerts) < MAX_ENTRIES_PER_SECTION
        ):
            equipment_alerts.append(ls)
        if (
            re.search(r"(?:申し送り|次シフト|引継ぎ事項|TODO|要対応|OPEN)", ls, re.IGNORECASE)
            and len(open_items) < MAX_ENTRIES_PER_SECTION
        ):
            open_items.append(ls)
    return parsed


class ShiftLogParseNode(FunctionNode):
    """Parse structured elements from Japanese manufacturing shift log text."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        validated_input = state.get("validated_input") or state.get("user_input", "")
        if not validated_input:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ShiftLogParseNode: no validated input"],
            }
        parsed = _parse_shift_log(validated_input)
        emit_trace_event(
            "shift_log_parsed",
            {
                "equipment_count": len(parsed.get("equipment_ids", [])),
                "alert_count": len(parsed.get("equipment_alerts", [])),
                "open_item_count": len(parsed.get("open_items", [])),
            },
            state,
        )
        return {
            "parsed_shift_data": json.dumps(parsed, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }

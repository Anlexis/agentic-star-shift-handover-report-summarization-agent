# AgentCore Platform v1.0 - MFG-C2-024
# Flat TypedDict. Dict/list fields are stored as Optional[str] JSON so state
# stays serialization-safe across the graph boundary.

from typing import Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """MFG-C2-024 state: manufacturing shift handover report summarization.

    Inherits from AgentState: user_input, validated_input, result,
    formatted_output, status, error_log, node_history, trace_id,
    correlation_id, session_id, input_context, enriched_context.

    Domain fields (JSON-encoded strings):
      validated_context: the validated caller context (process_type)
      parsed_shift_data: structured elements extracted from the shift log
      kpi_summary:       KPI actual vs target list
      incident_report:   incidents with severity and root cause
    """

    validated_context: Optional[str]  # JSON: {"process_type": "discrete"}
    parsed_shift_data: Optional[str]  # JSON: {equipment_ids, shift_period, ...}
    kpi_summary: Optional[str]  # JSON: [{kpi, actual, target, gap, gap_pct}]
    incident_report: Optional[str]  # JSON: [{severity, description, root_cause}]
    error_code: Optional[str]

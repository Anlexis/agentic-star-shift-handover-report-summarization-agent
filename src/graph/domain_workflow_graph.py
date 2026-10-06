# AgentCore Platform v1.0 - MFG-C2-024
# Inner domain workflow graph: ShiftHandoverDomainGraph(BaseGraph)
# Called by ShiftHandoverWorkflowGraphNode.get_subgraph() in graph.py.
# Pipeline: START -> shift_log_parse -> kpi_summarize ->
#           incident_extract -> report_generate -> END

import json
from typing import Any, Dict

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.graph.context_bridge import get_caller_context
from src.nodes.incident_extract_node import IncidentExtractNode
from src.nodes.kpi_summarize_node import KPISummarizeNode
from src.nodes.report_generate_node import ReportGenerateNode
from src.nodes.shift_log_parse_node import ShiftLogParseNode
from src.schemas.state import State


class ShiftHandoverDomainGraph(BaseGraph):
    """Inner domain workflow: parse -> KPI -> incident -> report.

    All inner nodes run at ANONYMOUS: the outer invocation context is passed in
    unchanged, so a stricter inner gate would refuse the caller the outer entry
    gate already admitted.

    get_output() shapes the result for merge_output() in the outer GraphNode —
    including the incident record, which the outer output gate needs and cannot
    otherwise see.
    """

    @property
    def name(self) -> str:
        return "shift_handover_domain_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        pass

    def _extra_initial_state(self) -> Dict[str, Any]:
        # The framework builds this subgraph's initial state from the user input
        # string alone; it does not forward the outer state's invocation context.
        # The validated caller context is seeded here, from the value the outer
        # GraphNode stashed just before this invoke.
        return {"validated_context": json.dumps(get_caller_context(), ensure_ascii=False, sort_keys=True)}

    def register_nodes(self) -> None:
        # No super() -- BaseGraph.register_nodes() is abstract.
        self._nodes["shift_log_parse"] = ShiftLogParseNode()
        self._nodes["kpi_summarize"] = KPISummarizeNode()
        self._nodes["incident_extract"] = IncidentExtractNode()
        self._nodes["report_generate"] = ReportGenerateNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "shift_log_parse")
        self._sg.add_edge("shift_log_parse", "kpi_summarize")
        self._sg.add_edge("kpi_summarize", "incident_extract")
        self._sg.add_edge("incident_extract", "report_generate")
        self._sg.add_edge("report_generate", END)

    def route(self, state: AgentState) -> str:
        return END if state.get("status") == AgentStatus.ERROR.value else "report_generate"

    def get_output(self, state: AgentState) -> Dict[str, Any]:
        return {
            # the reason must leave the subgraph or the outer graph cannot report it
            "error_code": state.get("error_code"),
            "output": state.get("result"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "incident_report": state.get("incident_report"),
        }

# AgentCore Platform v1.0 - MFG-C2-024
# Cat 2 outer graph: ManufacturingShiftHandoverAgent(AgentBaseGraph)
#
# Outer backbone (fixed 5-node, do NOT override add_edges()):
#   START -> initialize -> pre_process -> main -> post_process -> finalize -> END
#
# Inner domain (ShiftHandoverDomainGraph via ShiftHandoverWorkflowGraphNode):
#   START -> shift_log_parse -> kpi_summarize -> incident_extract
#         -> report_generate -> END
#
# Trust levels:
#   pre_process  (ValidateInputNode):         VERIFIED_EXTERNAL
#   inner nodes  (ShiftHandoverDomainGraph):  ANONYMOUS
#   post_process (SecurityGateOutputNode):    ANONYMOUS
#
# The inner nodes sit at ANONYMOUS on purpose: the framework hands the outer
# invocation context to the subgraph unchanged, so an inner gate stricter than
# the outer entry gate would refuse the caller the outer gate has already
# admitted. The entry decision is made once, at pre_process.

import json
from typing import Any, ClassVar, Dict

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.graph.context_bridge import set_caller_context
from src.nodes.security_gate_output_node import SecurityGateOutputNode
from src.nodes.validate_input_node import ValidateInputNode
from src.schemas.state import State


class ShiftHandoverWorkflowGraphNode(GraphNode):
    """GraphNode wrapper: delegates the main slot to ShiftHandoverDomainGraph."""

    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import ShiftHandoverDomainGraph

        return ShiftHandoverDomainGraph()

    def execute(self, state: AgentState) -> dict[str, Any]:
        """Skip the inner graph when the request was already found unacceptable.

        A request declined by pre_process has no validated input to act on, so
        running the inner graph would only produce a second, vaguer reason for
        the same rejection - and overwrite the specific one already settled.
        """
        marker = state.get("error_code")
        if marker:
            return {"status": AgentStatus.SUCCESS.value, "error_code": marker}
        result: dict[str, Any] = super().execute(state)
        return result

    def extract_input(self, state: AgentState) -> str:
        # Runs immediately before the subgraph invoke, and is the only hook that
        # sees outer state at that moment — so the validated caller context is
        # stashed here for the subgraph's initial state to pick up. The framework
        # forwards the user input string and nothing else.
        set_caller_context(_load_validated_context(state))
        return str(state.get("validated_input") or state.get("user_input") or "")

    def merge_output(self, state: AgentState, sub_result: Dict[str, Any]) -> Dict[str, Any]:
        # The report is surfaced only when the inner pipeline succeeded. On any
        # other inner status the report is left unset: the envelope the framework
        # builds falls back to `result`, so carrying a partial inner answer up
        # here would publish it under an error status without the output gate
        # ever seeing it.
        status = sub_result.get("status")
        succeeded = status in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
        # Outer reason wins: a reason settled before the inner run is the real
        # one, and a plain sub_result.get() would erase it.
        marker = state.get("error_code") or sub_result.get("error_code", "")
        merged: Dict[str, Any] = {"status": status, "error_code": marker}
        if succeeded:
            merged["result"] = sub_result.get("output")
            # The output gate reads the incident record to check that no
            # CRITICAL incident was dropped from the rendered report. It runs in
            # the OUTER graph, so the record has to be carried across this
            # boundary explicitly — a gate layer reading an inner-only key from
            # outer state compares against nothing on every real invocation.
            merged["incident_report"] = sub_result.get("incident_report")
        return merged


def _load_validated_context(state: AgentState) -> Dict[str, str]:
    raw = state.get("validated_context") or "{}"
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}


class ManufacturingShiftHandoverAgent(AgentBaseGraph):
    """MFG-C2-024 manufacturing shift handover report summarization agent.

    Cat 2 nested:
      pre_process:  ValidateInputNode (VERIFIED_EXTERNAL entry gate)
      main:         ShiftHandoverWorkflowGraphNode -> ShiftHandoverDomainGraph
      post_process: SecurityGateOutputNode (output gate)

    CRITICAL incidents are non-suppressible (ISO 9001 section 8.5.1 / JISHA).
    Domain dict/list fields travel through state as JSON strings.
    """

    @property
    def name(self) -> str:
        return "MFG-C2-024"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = ValidateInputNode()
        self._nodes["main"] = ShiftHandoverWorkflowGraphNode()
        self._nodes["post_process"] = SecurityGateOutputNode()

    # add_edges() NOT overridden -- backbone wiring is the framework's job.

# PB-6: Full backbone invoke-order for MFG-C2-024
# Verifies ManufacturingShiftHandoverAgent runs all 5 backbone slots in order
# on a SUCCESS-yielding payload.
# Uses a real external caller (caller_trust_level=VERIFIED_EXTERNAL) so the invoke
# exercises the true external path: the outer context is passed into the subgraph
# unchanged, so the inner domain nodes must admit VERIFIED_EXTERNAL (they declare
# ANONYMOUS). An INTERNAL inner gate would deny here and skip post_process.


_MAIN_SLOT_NODE = "ShiftHandoverWorkflowGraphNode"

# SUCCESS-yielding shift-handover payload (>= 10 chars, process_type defaults to discrete)
_VALID_PAYLOAD = (
    "シフト: 日勤 09:00-17:00\n"
    "担当者: 山田太郎\n"
    "設備ID: LINE-A01\n"
    "生産数 実績: 450 / 目標: 500\n"
    "引継ぎ事項: 次シフトで品質確認を実施すること\n"
)


class TestBackboneInvokeOrder:
    """PB-6: backbone runs initialize -> pre_process -> main -> post_process -> finalize."""

    def test_success_invoke_runs_all_backbone_nodes(self):
        from src.graph.graph import ManufacturingShiftHandoverAgent
        from framework.schemas.invocation_context import InvocationContext
        from framework.schemas.trust_level import TrustLevel
        from framework.schemas.agent_status import AgentStatus

        agent = ManufacturingShiftHandoverAgent()
        agent.compile()
        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke(_VALID_PAYLOAD, ctx=ctx)

        assert result.get("status") == AgentStatus.SUCCESS.value, (
            f"Expected AgentStatus.SUCCESS.value, got {result.get('status')}. " f"error_log: {result.get('error_log')}"
        )

        node_history = result.get("node_history", [])
        assert node_history, "node_history is empty -- no backbone nodes ran"

        def _cls_name(n):
            if isinstance(n, str):
                return n
            if isinstance(n, type):
                return n.__name__
            return type(n).__name__

        history_names = [_cls_name(n) for n in node_history]

        expected_backbone = [
            "InitializeNode",
            "ValidateInputNode",
            _MAIN_SLOT_NODE,
            "SecurityGateOutputNode",
            "FinalizeNode",
        ]

        for node_name in expected_backbone:
            assert node_name in history_names, (
                f"Expected backbone node {node_name!r} in node_history.\n" f"Got: {history_names}"
            )

        idxs = []
        for node_name in expected_backbone:
            first_occurrence = next((i for i, n in enumerate(history_names) if n == node_name), None)
            assert first_occurrence is not None
            idxs.append(first_occurrence)

        assert idxs == sorted(idxs), f"Backbone out of order.\nExpected: {expected_backbone}\nGot: {history_names}"

# MFG-C2-024 -- the output boundary.
#
# Two properties are checked here that a status assertion alone would miss:
#
#   * the gate's detector is not narrower than the framework's, and
#   * on a violation the gate BLANKS the output-bearing fields rather than
#     merely returning an error status.
#
# The second matters because the envelope the framework builds is
# `formatted_output or result`: an error status with `result` left in place
# ships the ungated report anyway, and a falsy notice re-opens the same
# fallback. Presence AND emptiness are both asserted — LangGraph merges partial
# deltas, so a key simply left out of the delta leaves the OLD value in state,
# and `assert not result.get(field)` would pass on a gate that clears nothing.

import json

import pytest
from framework.schemas.agent_status import AgentStatus
from framework.security.credential_detector import detect_credentials

from src.nodes.security_gate_output_node import (
    OUTPUT_BEARING_FIELDS,
    VIOLATION_CREDENTIAL,
    VIOLATION_CRITICAL_OMITTED,
    WITHHELD_NOTICE,
    SecurityGateOutputNode,
    _security_gate_output,
)

CLEAN_REPORT = "# 製造シフト引継ぎレポート（離散生産）\n\n## シフト基本情報\n- 設備: LINE-A01"

# Synthetic samples, one per framework pattern. The connection string is
# assembled from parts so the file carries no literal credential URL.
_SYNTHETIC_DB_URI = "postgresql" + "://" + "opsuser" + ":" + "sample-pass" + "@10.2.3.4:5432/inspect"

FRAMEWORK_KNOWN = [
    "AKIAIOSFODNN7EXAMPLE",
    "sk_live_" + "51H8xKlMnOpQrStUvWxYz0123",
    "sk-abcdefghijklmnopqrstuvwxyz0123",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijkl",
    "Bearer abcdefghij0123456789KLMNOP",
    _SYNTHETIC_DB_URI,
]

DOMAIN_ONLY = [
    "password=Str0ngPassw0rd!23",
    "api_key = ABC-123-DEF",
    "secret: hunter2",
    "token=abc123",
]


@pytest.fixture(autouse=True)
def _patch_emit(monkeypatch):
    monkeypatch.setattr("src.nodes.security_gate_output_node.emit_trace_event", lambda *a, **k: None)


@pytest.fixture()
def node():
    return SecurityGateOutputNode()


class TestDetectorParity:
    """The gate's coverage is a superset of the framework's, never a subset."""

    @pytest.mark.parametrize("secret", FRAMEWORK_KNOWN)
    def test_every_framework_known_shape_is_caught(self, secret):
        assert detect_credentials(secret), "test sample is not framework-known"
        assert _security_gate_output(f"{CLEAN_REPORT}\n- 備考: {secret}") == [VIOLATION_CREDENTIAL]

    @pytest.mark.parametrize("secret", DOMAIN_ONLY)
    def test_operational_secret_shapes_are_caught_too(self, secret):
        assert _security_gate_output(f"{CLEAN_REPORT}\n- 備考: {secret}") == [VIOLATION_CREDENTIAL]

    def test_ordinary_report_text_is_clean(self):
        assert _security_gate_output(CLEAN_REPORT) == []

    def test_gate_helper_is_a_plain_function(self):
        import inspect

        assert callable(_security_gate_output)
        assert not inspect.ismethod(_security_gate_output)

    def test_no_extra_gate_hook_overrides_on_class(self):
        # __dict__ checks only this class's own definitions; hasattr() would
        # wrongly flag the hooks FunctionNode itself defines for subclasses.
        assert "_extra_security_gate_input" not in SecurityGateOutputNode.__dict__
        assert "_extra_security_gate_output" not in SecurityGateOutputNode.__dict__


class TestContainment:
    def _violating_state(self):
        return {
            "result": f"{CLEAN_REPORT}\n- 備考: password=Str0ngPassw0rd!23",
            "parsed_shift_data": json.dumps({"operator": "山田太郎"}),
            "kpi_summary": json.dumps([{"kpi": "生産数", "actual": 450.0}]),
            "incident_report": json.dumps([]),
        }

    def test_violation_returns_error(self, node):
        result = node.execute(self._violating_state())
        assert result["status"] == AgentStatus.ERROR.value

    @pytest.mark.parametrize("field", [f for f in OUTPUT_BEARING_FIELDS if f != "formatted_output"])
    def test_every_output_bearing_field_is_present_and_blank(self, node, field):
        result = node.execute(self._violating_state())
        assert field in result, f"{field} absent from the delta — the old value survives the merge"
        assert result[field] == "", f"{field} was not blanked"

    def test_the_notice_is_truthy(self, node):
        result = node.execute(self._violating_state())
        assert result["formatted_output"] == WITHHELD_NOTICE
        assert result["formatted_output"], "a falsy notice re-opens the `or result` fallback"

    def test_the_notice_carries_nothing_read_back_out_of_state(self, node):
        state = self._violating_state()
        result = node.execute(state)
        notice = result["formatted_output"]
        assert "山田太郎" not in notice
        assert "450" not in notice
        assert "Str0ngPassw0rd" not in notice

    def test_the_reason_names_the_class_not_the_value(self, node):
        result = node.execute(self._violating_state())
        joined = " ".join(result["error_log"])
        assert VIOLATION_CREDENTIAL in joined
        assert "Str0ngPassw0rd" not in joined
        assert "/" not in joined, "no source path should reach the reason channel"

    def test_the_cleared_set_covers_every_output_bearing_state_field(self):
        """A new report-carrying field cannot quietly avoid the cleared set."""
        from framework.schemas.agent_state import AgentState

        from src.schemas.state import State

        inherited = set(getattr(AgentState, "__annotations__", {}))
        # `validated_context` holds the caller's process type — an inert
        # identifier from a closed set, carrying no report text — so it is
        # deliberately outside the cleared set. Every other domain field is
        # report-bearing and must be in it.
        # `error_code` is the reason marker for a declined run, not report text:
        # it must survive the clearing, or the caller is left with an empty body
        # and no reason.
        domain_fields = set(getattr(State, "__annotations__", {})) - inherited - {"validated_context", "error_code"}
        assert domain_fields, "the state module declares no domain fields — check the import"
        assert domain_fields <= set(
            OUTPUT_BEARING_FIELDS
        ), f"state fields missing from the cleared set: {domain_fields - set(OUTPUT_BEARING_FIELDS)}"


class TestCriticalIncidentCompleteness:
    """A recorded CRITICAL incident must survive into the rendered report."""

    def test_report_carrying_the_critical_incident_passes(self, node):
        incidents = [
            {
                "severity": "CRITICAL",
                "description": "重大インシデント: ライン停止",
                "root_cause": "過負荷",
                "suppressible": False,
            }
        ]
        report = f"{CLEAN_REPORT}\n- [CRITICAL] [必須記載/NON-SUPPRESSIBLE] 重大インシデント: ライン停止"
        result = node.execute({"result": report, "incident_report": json.dumps(incidents)})
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["formatted_output"] == report

    def test_report_that_dropped_the_critical_incident_is_withheld(self, node):
        incidents = [
            {
                "severity": "CRITICAL",
                "description": "重大インシデント: ライン停止",
                "root_cause": "過負荷",
                "suppressible": False,
            }
        ]
        result = node.execute({"result": CLEAN_REPORT, "incident_report": json.dumps(incidents)})
        assert result["status"] == AgentStatus.ERROR.value
        assert VIOLATION_CRITICAL_OMITTED in " ".join(result["error_log"])
        assert result["result"] == ""

    def test_unreadable_incident_record_fails_closed(self, node):
        result = node.execute({"result": CLEAN_REPORT, "incident_report": "not-json"})
        assert result["status"] == AgentStatus.ERROR.value

    def test_no_incidents_recorded_passes(self, node):
        result = node.execute({"result": CLEAN_REPORT, "incident_report": "[]"})
        assert result["status"] == AgentStatus.SUCCESS.value


class TestInnerFailureIsNotSurfaced:
    """merge_output surfaces the report only when the inner pipeline succeeded.

    Unit-level only, and deliberately so: in the pipeline as it stands the report
    is written by the last inner node, so no reachable data path produces a
    non-success inner result that already carries one. The guard is there because
    the envelope falls back to `result` on any status — a later inner node, or a
    framework refusal after the report exists, would otherwise publish a partial
    answer under an error status without the output gate seeing it.
    """

    def _merge(self, status):
        from src.graph.graph import ShiftHandoverWorkflowGraphNode

        return ShiftHandoverWorkflowGraphNode().merge_output(
            {}, {"status": status, "output": CLEAN_REPORT, "incident_report": "[]"}
        )

    def test_success_surfaces_the_report(self):
        merged = self._merge(AgentStatus.SUCCESS.value)
        assert merged["result"] == CLEAN_REPORT
        assert merged["incident_report"] == "[]"

    @pytest.mark.parametrize("status", ["error", "timeout", "cancelled", None])
    def test_non_success_surfaces_nothing(self, status):
        merged = self._merge(status)
        assert "result" not in merged, "a partial inner answer reached outer state"
        assert "incident_report" not in merged


class TestCleanPath:
    """Control: a refuse-everything gate must not be able to pass this file."""

    def test_clean_report_is_released_unchanged(self, node):
        result = node.execute({"result": CLEAN_REPORT, "incident_report": "[]"})
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["formatted_output"] == CLEAN_REPORT

    def test_empty_result_passes(self, node):
        result = node.execute({"result": ""})
        assert result["status"] == AgentStatus.SUCCESS.value

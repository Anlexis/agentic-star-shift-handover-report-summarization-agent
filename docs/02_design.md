# docs/02_design.md -- MFG-C2-024 Manufacturing Shift Handover Report Summarization Agent

## Template Metadata

| Field | Value |
|---|---|
| Template ID | MFG-C2-024 |
| Category | Cat 2 |
| Industry | MFG (Manufacturing) |
| L1 Base (framework base class) | `AgentBaseGraph` (outer) + `BaseGraph` (inner) — direct framework inheritance |
| Agent Class | ManufacturingShiftHandoverAgent |

## Architecture Overview

### Nested Cat 2 pattern

- **Outer graph** (`src/graph/graph.py`): `ManufacturingShiftHandoverAgent(AgentBaseGraph)`
  Fixed 5-node backbone with `ShiftHandoverWorkflowGraphNode` (a `GraphNode` subclass) in the
  `main` slot.
- **Inner graph** (`src/graph/domain_workflow_graph.py`): `ShiftHandoverDomainGraph(BaseGraph)`
  Four-step linear domain pipeline.

### Pipeline

**Outer backbone (fixed -- do not override `add_edges()`):**
```
START -> initialize -> pre_process -> main -> post_process -> finalize -> END
```

**Inner domain workflow (inside the `main` slot):**
```
START -> shift_log_parse -> kpi_summarize -> incident_extract -> report_generate -> END
```

### Node configuration

| Slot | Node Class | Trust Level | Responsibility |
|------|-----------|-------------|----------------|
| pre_process | ValidateInputNode | VERIFIED_EXTERNAL | Bounds, injection screen, caller-context contract |
| main (GraphNode) | ShiftHandoverWorkflowGraphNode | -- | Delegates to ShiftHandoverDomainGraph |
| inner: shift_log_parse | ShiftLogParseNode | ANONYMOUS | Equipment IDs, shift period, alerts, open items |
| inner: kpi_summarize | KPISummarizeNode | ANONYMOUS | KPI actual vs target extraction |
| inner: incident_extract | IncidentExtractNode | ANONYMOUS | Incidents; CRITICAL non-suppressible |
| inner: report_generate | ReportGenerateNode | ANONYMOUS | Report for the caller's process type |
| post_process | SecurityGateOutputNode | ANONYMOUS | Credential scan + report completeness |

The entry decision is made once, at `pre_process`. The framework hands the outer invocation
context to the subgraph unchanged, so an inner gate stricter than the outer entry gate would
refuse the caller the outer gate has already admitted — a request that succeeds in unit tests
built on an internal context and fails for every real caller.

### Caller context across the graph boundary

The framework invokes the subgraph with the user input string alone; it does not forward the outer
state's invocation context. `src/graph/context_bridge.py` carries the *validated* context across:
`extract_input` stashes it immediately before the subgraph invoke, and the inner graph's
`_extra_initial_state()` seeds it into the subgraph's initial state. Every caller field an inner
node reads has to travel that way — a field left behind is not a compile error and not a test
failure; the inner node reads a key absent from its own state and degrades to a default while the
run reports success.

## State design (`State(AgentState)` -- flat TypedDict)

| Field | Type | Description |
|-------|------|-------------|
| user_input | Optional[str] | Raw shift log text (AgentState) |
| input_context | Optional[dict] | Caller-supplied context at the outer graph (AgentState) |
| validated_input | Optional[str] | Bounded, screened shift log text (AgentState) |
| validated_context | Optional[str] | JSON: the validated caller context (`process_type`) |
| parsed_shift_data | Optional[str] | JSON: {equipment_ids, shift_period, operator, ...} |
| kpi_summary | Optional[str] | JSON: [{kpi, actual, target, gap, gap_pct, achieved}] |
| incident_report | Optional[str] | JSON: [{severity, description, root_cause, suppressible}] |
| result | Optional[str] | Rendered handover report (AgentState) |
| formatted_output | Optional[str] | Caller-facing report, or the withheld notice (AgentState) |

Dict and list fields are stored as JSON strings so state stays serialization-safe across the
graph boundary.

## Input contract

`/invoke` accepts the shift log text, an optional session id, and an optional `input_context`
carrying exactly one field:

| Key | Values | Default |
|-----|--------|---------|
| process_type | discrete / process / semiconductor | discrete |

Undeclared keys are **dropped** at the adapter rather than ignored. Ignoring is not stripping: an
ignored key stays in the invocation context, reaches the first node's result, and is scanned by
the framework's output check — so an unvalidated field can end the run before any template code
executes. The adapter also refuses a credential-shaped value on a declared field with a 400 naming
the field, since the request cannot succeed either way and an opaque first-node error tells the
caller nothing.

`ValidateInputNode` then enforces, on the node that owns the contract:

- length and line-count bounds on the shift log;
- an injection screen covering chat-template control markers as a class (`<|...|>`, `[INST]`,
  `<<SYS>>`) and directive phrases in English and Japanese, evaluated on the raw text **and** on
  its markup-stripped twin, over context values **and** context keys;
- the closed-set check on `process_type`.

Refusals name the class and the field. A rejected value is caller data and is never echoed back.

### Declining a request without terminating the run

Two outcomes, chosen by what the caller can do about the request:

- **A value the caller can correct** — no text, text past the size bounds, a declared context field
  carrying a value outside its closed set. The run **completes**, carrying a reason code
  (`EMPTY_INPUT`, `QUESTION_TOO_LONG`, `INVALID_REQUEST`) through state. `SecurityGateOutputNode`
  turns that code into the fixed caller-facing sentence held in `src/services/failure_message.py`
  and puts it in the caller-facing slot; `ShiftHandoverWorkflowGraphNode` skips the inner graph so
  the settled reason is not overwritten by a vaguer second one. Terminating instead would end the
  calling surface's turn and surface only an exception type, leaving the reason reachable solely
  from the audit trail — the caller could not correct the value and send the request again on the
  same conversation.
- **A refusal the agent owns** — a prompt-injection payload in the shift log text or in the caller
  context, an output-gate violation, an inner node whose upstream invariant did not hold. These
  **terminate** with an error status. Rewording the request is not a route past them, so presenting
  them as correctable would be a false statement about the agent's behaviour.

The branch is chosen at the call site, by the reason code the rejection carries, not by inspecting
the refusal label — so a new refusal defaults to terminating rather than to completing.

The reason code is an internal state field. It is not published in the response envelope: the
caller reads the sentence, not the code.

## Output boundary

`SecurityGateOutputNode` runs two independent layers, each with its own audit event:

- **Credential scan** — the framework's own `detect_credentials()` plus the operational secret
  shapes that turn up in maintenance notes (`password=`, `api_key=`). The framework detector is
  called rather than approximated: a value the framework catches and this node misses would sit in
  this node's own returned delta, the framework's check would raise on it, and the wrapper would
  discard the delta — the withholding included.
- **Report completeness** — every CRITICAL incident the pipeline recorded must appear in the
  rendered report, marked non-suppressible. The incident record is carried from the inner graph
  through `merge_output` explicitly, because this gate runs in the outer graph and a layer reading
  an inner-only key from outer state compares against nothing on every real invocation.

On a violation the node returns an error status **and** blanks every output-bearing field, then
puts a fixed notice in the caller-facing slot. Both halves are required: the envelope the
framework builds is `formatted_output or result`, so an error status with `result` still populated
ships the ungated report, and a falsy notice re-opens the same fallback. The notice is a constant —
nothing is read back out of the state that was just blanked.

`merge_output` surfaces the report only on a successful inner result, so a partial inner answer
cannot reach the envelope under an error status without the gate seeing it.

## Precision grid

This template renders no monetary aggregates: its figures are production counts, rates and
percentages taken from the caller's own log, and its identifiers are equipment codes. The
round-to-the-nearest-1,000 output grid used by financial templates is therefore not applicable
here, and applying it would corrupt equipment codes and KPI figures rather than protect anything.
The invariant this boundary enforces instead is the completeness rule above.

## Runtime configuration

`config/config.yaml` holds the runtime parameters and is read by the HTTP adapter at start-up,
which passes it to the graph constructor. `max_retry` is consumed by the backbone's retry route
and validated at compile; `timeout_s` is the deadline the adapter applies to one report
generation. A declared value out of range fails at compile rather than degrading to a default.

## Design decision record

| Decision | Chosen | Rationale |
|----------|--------|----------|
| Framework base | AgentBaseGraph + BaseGraph | Nested Cat 2 pipeline |
| Domain fields | JSON strings | Serialization-safe state |
| Inner trust level | ANONYMOUS | Outer context is passed in unchanged; a stricter inner gate denies the admitted caller |
| Caller context | ContextVar bridge | The framework does not forward the invocation context into a subgraph |
| CRITICAL incidents | suppressible=False, enforced at the output gate | ISO 9001 section 8.5.1 / JISHA |
| Output gate helper | Module-level function | Exercisable with no node instance and no state |
| Caller numerics | Bounded finite parser | Non-finite values parse cleanly and then compare False against every target |
| Entry authorization | Bearer credential, no anonymous path | The entry gate requires VERIFIED_EXTERNAL; admitting anonymously only defers the refusal |

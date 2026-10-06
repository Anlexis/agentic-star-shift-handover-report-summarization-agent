# docs/03_test_spec.md -- MFG-C2-024 Manufacturing Shift Handover Report Summarization Agent

## Overview

148 tests across four groups. The split matters more than the count: node-level tests state what
each node computes, and end-to-end tests state what the deployed application actually does. Three
of this template's properties — that the caller's process type reaches the inner graph, that the
deployed entry point can satisfy its own entry gate, and that a withheld report does not travel
inside the error envelope — cannot be observed at node level at all, because they live in the
wiring rather than in any one node.

| Module | Tests | Scope |
|---|---|---|
| `tests/unit/test_agent.py` | 33 | Each domain node in isolation |
| `tests/unit/test_input_contract.py` | 42 | The caller-input contract on the node that owns it |
| `tests/unit/test_output_gate.py` | 33 | The output boundary: detection, withholding, completeness |
| `tests/integration/test_invoke_endpoint.py` | 33 | End-to-end through the real ASGI entry point |
| `tests/proof_of_boundary/*` | 5 | Backbone order, import isolation, state safety, interrupt contract |
| `tests/unit/test_framework_compliance_tc06_tc07.py` | 2 | Framework gate-hook contract |

Two proof-of-boundary tests skip when `config/config.yaml` does not enable the human-in-the-loop
path; that is the shipped configuration.

## Unit tests -- domain nodes (`tests/unit/test_agent.py`)

### ValidateInputNode

| Scenario | Expected |
|---|---|
| Valid shift log, `process_type=discrete` | SUCCESS; validated context serialized |
| Empty input | Run completes carrying `EMPTY_INPUT`; no `validated_input` |
| Text shorter than the minimum | Run completes carrying `INVALID_REQUEST`; no `validated_input` |
| Unknown `process_type` | Run completes carrying `INVALID_REQUEST`, naming the field, never the value |
| Each of the three declared process types | SUCCESS, context carries the value |
| No context supplied | SUCCESS, empty validated context |

Each of the three declined cases is a value the caller can correct, so the assertion is a
completed run carrying the reason code — not a terminated one. Asserting a terminal status here
would pass on an agent that ends the caller's turn on a typo. The injection screen is the
opposite case and is asserted as terminal; it is covered in the input-contract module below.

### ShiftLogParseNode

| Scenario | Expected |
|---|---|
| Equipment ID / shift period / operator lines | Each parsed into its field |
| Handover line | Captured as an open item |
| More entries than the per-section cap | Truncated at the cap |
| Empty state | ERROR |

### KPISummarizeNode

| Scenario | Expected |
|---|---|
| Each of the four house styles for an actual/target pair | One KPI row with gap and gap percentage |
| No KPI in the text | Empty list, SUCCESS |
| Figure that overflows to infinity | Row dropped, not reported as achieved |
| Figure beyond the magnitude bound | Row dropped |
| Empty state | ERROR |

### IncidentExtractNode

| Scenario | Expected |
|---|---|
| Incident line | Incident recorded with severity and provisional cause |
| CRITICAL severity | `suppressible` is False (ISO 9001 section 8.5.1) |
| LOW / MEDIUM severity | `suppressible` is True |
| No incidents | Empty list, SUCCESS |
| Empty state | ERROR |

### ReportGenerateNode

| Scenario | Expected |
|---|---|
| Each process type in the validated context | The matching report heading |
| No validated context | The default heading |
| KPI rows supplied | KPI table rendered |
| Unparseable domain field | ERROR |

The fixtures here supply `validated_context` — the key the outer graph actually seeds into this
subgraph. A fixture supplying `input_context` would exercise a state shape the pipeline never
builds, and would keep passing on a node whose caller setting is ignored in production.

## Unit tests -- input contract (`tests/unit/test_input_contract.py`)

`execute()` is called directly, with no framework wrapper in front, so these tests state that the
template refuses these payloads rather than that some gate somewhere did.

| Group | Scenarios |
|---|---|
| Injection screen, refused — terminal | `<\|im_start\|>`, `[INST]`, `<<SYS>>`, `<</SYS>>`, an English override phrase, a markup-split directive, a Japanese override phrase, a role-reassignment phrase |
| Injection screen, unaffected | Ordinary handover prose, an angle-bracketed operator note, prose containing "system" and "ignore" in their normal senses |
| Context screening | Values, **keys**, and nested structures screened depth-first |
| Structural bounds | Oversize text and excess line count decline the run, which completes carrying `QUESTION_TOO_LONG` and no `validated_input` |
| Context contract | Undeclared keys dropped; a declared key with a bad value rejected by name; a non-mapping context ignored |
| Finite-number rule | Sixteen unusable values per field (NaN, the infinities, booleans, non-numeric text, over-magnitude) all rejected; usable values parse |

## Unit tests -- output boundary (`tests/unit/test_output_gate.py`)

| Group | Scenarios |
|---|---|
| Detector parity | Every framework credential pattern is caught, and the operational secret shapes as well; ordinary report text is clean |
| Withholding | Every output-bearing field is **present in the returned delta and blank**; the notice is truthy; the notice carries nothing read back out of the blanked state; the reason names the class, never the matched value or a source path |
| Cleared-set inventory | Every report-bearing state field is in the cleared set, so a new field cannot quietly avoid it |
| Completeness | A report carrying its CRITICAL incident passes; one that dropped it is withheld; an unreadable incident record fails closed |
| Inner-failure path | `merge_output` surfaces the report only on a successful inner result |
| Clean-path control | A clean report is released unchanged, so a refuse-everything gate cannot pass this file |

Presence **and** emptiness are both asserted. Partial state deltas are merged, so a key simply
left out of the delta leaves the old value in state — an assertion that only checks falsiness
passes on a gate that clears nothing.

## End-to-end (`tests/integration/test_invoke_endpoint.py`)

Every case goes through the real FastAPI application, the real compiled graph and the real bearer
auth path.

| Group | Scenarios |
|---|---|
| Entry authorization | Authenticated request produces a report; missing and wrong credentials are refused; the internal runner credential is accepted; unconfigured auth fails closed |
| Caller context | Each process type selects its heading, and the three headings differ; absent context degrades to the default; undeclared keys are dropped; an invalid process type declines the request — the run completes, the caller-facing body is the reason sentence and no report is produced; a credential-shaped context value is refused by field name while ordinary domain values on the same field pass |
| Real output from caller data | KPI figures come from the submitted log; a log without KPIs says so rather than inventing one; a CRITICAL incident is rendered non-suppressible |
| Envelope containment | No credential, no report fragment, no traceback and no source path in the error envelope; the envelope carries the withheld notice; the block is shown to have happened at the gate rather than upstream; the same request without the credential still returns its report |
| Runtime configuration | The declared values are the ones in force; the declared deadline is the one applied; an out-of-range declared value fails at compile; a request past the deadline returns a timeout |
| Injection through the public path | Four attack forms terminate the run and produce no report |
| Reference payload | `deploy/invoke_payload.json` is the same body the backbone test drives, and it produces a report |

## Proof-of-boundary tests

| Test | Assertion |
|---|---|
| `test_pb_invoke_order.py` | The backbone runs initialize -> pre_process -> main -> post_process -> finalize in order, driven at the trust level a real external caller carries |
| `test_import_isolation.py` | No direct platform-SDK imports in `src/` |
| `test_state_safety.py` | No credential-named fields and no prohibited types in `State` |
| `test_pb7_hitl_interrupt_propagation.py` | The interrupt contract, when the runtime configuration enables it |

## Coverage target

80%+ line coverage across `src/`.

# Shift Handover Report Summarization Agent

AI agent for summarizing manufacturing shift handover reports, built with Agentic Star.

> **Category**: Cat 2 (domain-specific manufacturing pipeline)
> **Industry**: Manufacturing
> **Template ID**: MFG-C2-024

## Overview

Turns a raw manufacturing shift log into a structured handover report for the incoming shift.

A shift log arrives as free text — Japanese or English, written by whoever was on the line. The
agent reads it and produces four sections: the shift's basic facts (equipment, period, operator),
the equipment alerts and open items carried forward, a KPI table pairing each recorded actual
against its target with the gap in absolute and percentage terms, and the shift's incidents sorted
by severity with a provisional cause for each.

The report is rendered for one of three production modes — discrete, process, or semiconductor —
selected per request by the caller.

Two rules hold at the boundaries. Incidents classified CRITICAL are non-suppressible: the output
check refuses to release a report that recorded one and then failed to carry it, rather than
letting a quiet omission through (ISO 9001 section 8.5.1 / JISHA). And every figure taken out of
the caller's text goes through a bounded numeric parser before any comparison, because a value
that parses but is not finite compares False against every target and would silently report a
missed KPI as achieved.

Typical users are line supervisors and production managers who currently reconcile handover sheets
by hand at every shift change.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >= 3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent fails at graph
compile / start-up preflight rather than starting in a partially working state. This is
intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Invoking

The entry point requires a bearer credential. Set `INVOKE_AUTH_TOKEN` (external callers) and,
optionally, `STG_INTERNAL_RUNNER_TOKEN` (an internal runner) before start-up; with neither set the
endpoint refuses every request rather than admitting callers the pipeline's entry gate will reject.

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Authorization: Bearer $INVOKE_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input": "シフト: 日勤\n設備ID: LINE-A01\n生産数 実績: 450 / 目標: 500\n",
       "input_context": {"process_type": "discrete"}}'
```

`input_context` accepts one field, `process_type`, drawn from `discrete` / `process` /
`semiconductor`. Any other key is dropped at the boundary.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent manifest and runtime parameters
docs/         design and operational documentation
```

See `docs/` for the design and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the shift-log grammars in `src/nodes/` with the ones your plants actually write.
3. Extend the process-type catalogue in `src/services/service.py`.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.

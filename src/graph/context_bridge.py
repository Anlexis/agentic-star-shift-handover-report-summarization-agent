"""AgentCore Platform v1.0"""

# src/graph/context_bridge.py — carries the caller's validated context across the
# outer -> inner graph boundary.
#
# Why this exists: the framework's GraphNode invokes the inner graph as
# `subgraph.invoke(user_input, ...)` and does NOT forward the outer state's
# input_context. Without a bridge the inner report node reads `input_context`
# from its own state, finds an empty mapping on every real invocation, and
# silently falls back to the default process type — while unit tests that hand
# the node a populated mapping keep passing.
#
#   ShiftHandoverWorkflowGraphNode.extract_input(state)
#       [runs BEFORE subgraph.invoke]  -> set_caller_context(...)
#   ShiftHandoverDomainGraph._extra_initial_state()
#       [runs INSIDE subgraph.invoke]  -> seeds the stashed context
#
# EVERY validated caller field an inner node reads has to travel here. A field
# left behind is not a compile error and not a test failure: the inner node
# reads a key absent from its own state, degrades to a default, and the caller's
# setting is ignored while the run reports success.
#
# What crosses is the VALIDATED context the outer pre_process node produced —
# never the raw caller mapping. Caller data is bounded exactly once, upstream.
#
# A ContextVar keeps the hand-off correct per thread and per task, so concurrent
# invocations in one process cannot see each other's caller data.

from contextvars import ContextVar
from typing import Dict, Optional

_CALLER_CONTEXT: ContextVar[Optional[Dict[str, str]]] = ContextVar("mfg_c2_024_caller_context", default=None)


def set_caller_context(context: Optional[Dict[str, str]]) -> None:
    """Stash the validated caller context for the imminent inner-graph invoke."""
    _CALLER_CONTEXT.set(dict(context) if context else {})


def get_caller_context() -> Dict[str, str]:
    """Read (without consuming) the stashed context; empty when none was set."""
    return dict(_CALLER_CONTEXT.get() or {})


def clear_caller_context() -> None:
    """Drop the stashed context. Used by tests to assert the absent-data path."""
    _CALLER_CONTEXT.set(None)

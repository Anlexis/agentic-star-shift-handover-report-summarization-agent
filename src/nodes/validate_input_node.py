# AgentCore Platform v1.0 - MFG-C2-024
# Outer pre_process input gate: bound the shift log text, screen it for
# prompt-injection payloads, and reduce the caller context to the declared,
# validated contract. required_trust_level = VERIFIED_EXTERNAL.
#
# The template owns these guarantees rather than leaning on the framework's
# input gate. The framework's screen recognises `<|...|>` and `[INST]` markers
# and a set of override phrases; it scores `<<SYS>>` and markup-split text as
# clean, so an unguarded template forwards both to the answer path. Everything
# below is checked here, on the node that owns the caller contract, so a direct
# execute() call refuses the same payloads an end-to-end call does.

import json
import re
import unicodedata
from typing import Any, ClassVar, Dict, List, Tuple

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.failure_message import INPUT_REJECTED
from src.services.progress import emit_progress

from src.services.service import (
    DEFAULT_PROCESS_TYPE,
    MAX_SHIFT_LOG_CHARS,
    MAX_SHIFT_LOG_LINES,
    MIN_SHIFT_LOG_CHARS,
    normalize_caller_context,
)

# Chat-template control markers, screened as a CLASS rather than as individual
# strings: any `<|...|>` token, the llama instruction wrapper, and the llama
# system wrapper. A payload that opens a system turn does not need a recognisable
# English phrase after it to be an attack.
_CONTROL_TOKEN_RES: List[re.Pattern[str]] = [
    re.compile(r"<\|[^|>\n]{0,64}\|>"),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
    re.compile(r"<</?SYS>>", re.IGNORECASE),
]

# Directive phrases, anchored on the whole phrase so ordinary text containing
# "ignore" or "system" is unaffected. Japanese forms are included because the
# shift logs this template reads are written in Japanese.
_OVERRIDE_RES: List[re.Pattern[str]] = [
    re.compile(
        r"\b(?:ignore|disregard|forget|override)\s+(?:any\s+|all\s+)?(?:of\s+)?(?:the\s+|your\s+)?"
        r"(?:previous|prior|above|preceding|earlier|foregoing)\s+"
        r"(?:instruction|instructions|rule|rules|prompt|prompts|direction|directions)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:reveal|print|show|dump|output)\s+(?:the\s+|your\s+)?system\s+prompt\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+(?:a|an)\s+\w+", re.IGNORECASE),
    re.compile(r"(?:これまで|それまで|以前|上記|前)の?(?:指示|命令|規則|ルール)[^\n]{0,8}(?:無視|忘れ)"),
    re.compile(r"システムプロンプト[^\n]{0,8}(?:出力|表示|開示)"),
]

_MARKUP_RE = re.compile(r"<[^<>\n]{1,48}>")
_ZERO_WIDTH_RE = re.compile(r"[​-‏‪-‮⁠﻿]")

# Closed-set refusal labels. A refusal names the class it matched and the field
# it matched in — never the matched text, which is caller data.
_REASON_TEXT_MISSING = "shift_log_missing"
_REASON_TEXT_TOO_SHORT = "shift_log_too_short"
_REASON_TEXT_TOO_LARGE = "shift_log_too_large"
_REASON_INJECTION = "injection_pattern"
_REASON_CONTEXT_FIELD = "context_field_invalid"


def _normalized_views(text: str) -> Tuple[str, str]:
    """Return the raw text and its markup-stripped, width-normalised twin.

    Both views are screened. The raw view catches control markers before a strip
    could remove them; the stripped view catches directives that were split by
    inline markup (`ig<b>nore</b> all previous instructions`) and reassemble into
    a plain directive once the tags are gone. Screening only one of the two
    turns a detectable attack into an undetectable one.
    """
    raw = _ZERO_WIDTH_RE.sub("", text)
    stripped = _MARKUP_RE.sub("", unicodedata.normalize("NFKC", raw))
    return raw, stripped


def screen_for_injection(text: str) -> bool:
    """True when the text carries a control marker or an override directive."""
    if not text:
        return False
    for view in _normalized_views(text):
        for pattern in _CONTROL_TOKEN_RES:
            if pattern.search(view):
                return True
        for pattern in _OVERRIDE_RES:
            if pattern.search(view):
                return True
    return False


def screen_context_for_injection(raw_context: Any) -> List[str]:
    """Screen a caller mapping depth-first, KEYS included.

    Field names are caller data too: a mapping keyed by a directive is as much an
    injection channel as one valued by it, and a key never reaches a value scan.
    Returns the locations that matched, as `key` / `key (name)` labels — never
    the matched text.
    """
    hits: List[str] = []
    if not isinstance(raw_context, dict):
        return hits
    for key in sorted(raw_context, key=str):
        label = key if isinstance(key, str) and key.isidentifier() else "field"
        if isinstance(key, str) and screen_for_injection(key):
            hits.append(f"{label} (name)")
        value = raw_context[key]
        if isinstance(value, str) and screen_for_injection(value):
            hits.append(label)
        elif isinstance(value, (dict, list, tuple)):
            nested = value if isinstance(value, dict) else dict(enumerate(value))
            if screen_context_for_injection(nested):
                hits.append(label)
    return hits


class ValidateInputNode(FunctionNode):
    """Outer input gate: bounds, injection screen, caller-context contract."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _reject(
        self, state: Dict[str, Any], reason: str, detail: str = "", code: str = "INVALID_REQUEST"
    ) -> Dict[str, Any]:
        """Stop the request here. Messages name FIELDS, never values.

        Two ways to stop, and the caller can act on only one of them. A value
        the caller can correct completes the run carrying ``code``, so the
        reason reaches the caller and a corrected request can be sent on the
        same conversation. Content the agent refuses outright passes ``code=""``
        and terminates, so a refusal is never presented as something a reworded
        request would get past.

        The branch is chosen by the call site through ``code``, never by
        reading *reason*: the injection screens pass ``code=""``.
        """
        emit_trace_event("validate_input_rejected", {"reason": reason}, state)
        message = f"ValidateInputNode: request rejected ({reason}"
        if detail:
            message += f"; field: {detail}"
        message += ")"
        if code:
            # A value the caller can correct: the run COMPLETES carrying the
            # reason so the request can be sent again on the same conversation.
            emit_progress(INPUT_REJECTED)
            return {"status": AgentStatus.SUCCESS.value, "error_code": code, "error_log": [message]}
        return {"status": AgentStatus.ERROR.value, "error_log": [message]}

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        user_input = state.get("user_input") or ""
        raw_context = state.get("input_context") or {}

        if not isinstance(user_input, str) or not user_input.strip():
            return self._reject(state, _REASON_TEXT_MISSING, code="EMPTY_INPUT")

        text = user_input.strip()
        if len(text) < MIN_SHIFT_LOG_CHARS:
            return self._reject(state, _REASON_TEXT_TOO_SHORT)
        if len(text) > MAX_SHIFT_LOG_CHARS or text.count("\n") + 1 > MAX_SHIFT_LOG_LINES:
            return self._reject(state, _REASON_TEXT_TOO_LARGE, code="QUESTION_TOO_LONG")

        # Terminal: a refusal, not a correctable value. Rewording the request
        # must not be presented as a route past it.
        if screen_for_injection(text):
            return self._reject(state, _REASON_INJECTION, "input", code="")
        context_hits = screen_context_for_injection(raw_context)
        if context_hits:
            return self._reject(state, _REASON_INJECTION, ", ".join(context_hits), code="")

        validated_context, rejected_fields = normalize_caller_context(raw_context)
        if rejected_fields:
            return self._reject(state, _REASON_CONTEXT_FIELD, ", ".join(rejected_fields))

        process_type = validated_context.get("process_type", DEFAULT_PROCESS_TYPE)
        emit_trace_event(
            "validate_input_passed",
            {"process_type": process_type, "text_length": len(text)},
            state,
        )
        return {
            "validated_input": text,
            "validated_context": json.dumps(validated_context, ensure_ascii=False, sort_keys=True),
            "status": AgentStatus.SUCCESS.value,
        }

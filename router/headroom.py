from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal
import logging
import os

import tokenizer

logger = logging.getLogger("router.headroom")

try:
    from headroom import compress as _headroom_compress  # type: ignore
except Exception:  # pragma: no cover - optional dependency in dev/test environments
    _headroom_compress = None


TrimStrategy = Literal["drop_oldest_then_summarize", "summarize_history", "drop_oldest"]


@dataclass
class HeadroomPolicy:
    model: str
    max_num_ctx: int
    reserved_output_tokens: int
    safety_headroom_tokens: int
    trim_strategy: TrimStrategy


@dataclass
class HeadroomCheckResult:
    rejected: bool
    trimmed: bool
    messages: List[Dict[str, Any]]
    prompt_tokens: int
    usable_prompt_budget: int
    trim_reason: str | None = None
    error_response: Dict[str, Any] | None = None


def resolve_headroom(model_name: str, policy_entry: Dict[str, Any]) -> HeadroomPolicy:
    options = policy_entry.get("options") or {}
    max_num_ctx = int(options.get("num_ctx", 65536))
    reserved_output_tokens = int(policy_entry.get("reserved_output_tokens", 2048))
    safety_headroom_tokens = int(policy_entry.get("safety_headroom_tokens", 2048))
    trim_strategy = str(policy_entry.get("trim_strategy", "drop_oldest"))
    if trim_strategy not in {
        "drop_oldest_then_summarize",
        "summarize_history",
        "drop_oldest",
    }:
        trim_strategy = "drop_oldest"
    return HeadroomPolicy(
        model=model_name,
        max_num_ctx=max_num_ctx,
        reserved_output_tokens=reserved_output_tokens,
        safety_headroom_tokens=safety_headroom_tokens,
        trim_strategy=trim_strategy,
    )


def calculate_usable_prompt(policy: HeadroomPolicy) -> int:
    return max(0, policy.max_num_ctx - policy.reserved_output_tokens - policy.safety_headroom_tokens)


def _token_count(messages: List[Dict[str, Any]], model: str) -> int:
    return int(tokenizer.count_prompt_tokens(messages, model))


def _normalize_headroom_output(compressed: Any, original: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(compressed, list):
        return compressed
    if isinstance(compressed, dict):
        maybe_messages = compressed.get("messages")
        if isinstance(maybe_messages, list):
            return maybe_messages
    logger.warning("router.headroom: unexpected headroom output type %s; using original messages", type(compressed).__name__)
    return original


def _compress_via_headroom(messages: List[Dict[str, Any]], model_name: str) -> List[Dict[str, Any]]:
    if os.getenv("HEADROOM_ENABLED", "1").lower() in {"0", "false", "off", "no"}:
        return messages
    if _headroom_compress is None:
        logger.info("router.headroom: headroom-ai not installed; skipping compression")
        return messages

    try:
        compressed = _headroom_compress(messages, model=model_name)
        return _normalize_headroom_output(compressed, messages)
    except TypeError:
        # Older API variants may not accept model kwarg.
        compressed = _headroom_compress(messages)
        return _normalize_headroom_output(compressed, messages)
    except Exception as exc:
        logger.warning("router.headroom: compression failed, continuing without compression: %s", exc)
        return messages


def check_and_trim(
    messages: List[Dict[str, Any]],
    model_name: str,
    policy_entry: Dict[str, Any],
) -> HeadroomCheckResult:
    policy = resolve_headroom(model_name, policy_entry)
    budget = calculate_usable_prompt(policy)
    initial_tokens = _token_count(messages, model_name)
    if initial_tokens <= budget:
        return HeadroomCheckResult(
            rejected=False,
            trimmed=False,
            messages=messages,
            prompt_tokens=initial_tokens,
            usable_prompt_budget=budget,
        )

    # Delegate compression/compaction to the upstream Headroom project.
    trimmed_messages = _compress_via_headroom(messages, model_name)
    final_tokens = _token_count(trimmed_messages, model_name)
    if final_tokens <= budget:
        return HeadroomCheckResult(
            rejected=False,
            trimmed=True,
            messages=trimmed_messages,
            prompt_tokens=final_tokens,
            usable_prompt_budget=budget,
            trim_reason="history_over_budget",
        )

    over_by = max(0, final_tokens - budget)
    return HeadroomCheckResult(
        rejected=True,
        trimmed=(trimmed_messages != messages),
        messages=trimmed_messages,
        prompt_tokens=final_tokens,
        usable_prompt_budget=budget,
        trim_reason="cannot_fit_after_trim",
        error_response={
            "error": {
                "type": "context_length_exceeded",
                "message": "Request exceeds safe proxy budget after trimming",
                "details": {
                    "model": model_name,
                    "max_num_ctx": policy.max_num_ctx,
                    "reserved_output_tokens": policy.reserved_output_tokens,
                    "safety_headroom_tokens": policy.safety_headroom_tokens,
                    "usable_prompt_budget": budget,
                    "final_prompt_tokens": final_tokens,
                    "over_by_tokens": over_by,
                },
            }
        },
    )

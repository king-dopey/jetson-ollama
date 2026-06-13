import asyncio
import logging
import json
import os
import time
import uuid
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from contextlib import asynccontextmanager

from policy import load_think_policy_config, parse_think_override, should_enable_think

logger = logging.getLogger("router")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
POLICY_FILE = os.getenv("MODEL_POLICY_FILE", "/app/model_policy.yml")
DEFAULT_MODEL = os.getenv("MODEL_DEFAULT", "qwen3.6:35b-a3b")
DEFAULT_KEEP_ALIVE = os.getenv("KEEP_ALIVE_DEFAULT", "-1")

def _translate_tool_calls(ollama_tool_calls):
    """Convert Ollama-shape tool_calls to OpenAI-shape.

    Ollama: [{"function": {"name": "...", "arguments": {...dict...}}}]
    OpenAI: [{"id": "...", "type": "function",
              "function": {"name": "...", "arguments": "<json string>"}}]
    """
    if not ollama_tool_calls:
        return None
    out = []
    for tc in ollama_tool_calls:
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, (dict, list)):
            args_str = json.dumps(args)
        elif args is None:
            args_str = "{}"
        else:
            args_str = str(args)
        out.append({
            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": fn.get("name", ""),
                "arguments": args_str,
            },
        })
    return out


def _streaming_tool_call_deltas(ollama_tool_calls):
    """OpenAI streaming requires each tool_call entry in a delta to carry an
    `index`. Ollama emits the whole tool_calls array in a single chunk, so we
    emit them all in one delta with sequential indices."""
    translated = _translate_tool_calls(ollama_tool_calls)
    if not translated:
        return None
    for i, tc in enumerate(translated):
        tc["index"] = i
    return translated


def _parse_scalar(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


# Options the router will inject from policy. num_ctx is the only one where
# the policy unconditionally wins; the rest are defaults that client requests
# may override.
POLICY_LOCKED_OPTIONS = {"num_ctx"}


def _load_policy() -> dict[str, dict[str, Any]]:
    if os.path.exists(POLICY_FILE):
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f) or {}
        models = parsed.get("models", [])
        if isinstance(models, list):
            table: dict[str, dict[str, Any]] = {}
            for item in models:
                model_name = item.get("model")
                if not model_name:
                    continue
                keep_alive = _parse_scalar(item.get("keep_alive"))
                think = item.get("think")
                options = item.get("options") or {}
                if not isinstance(options, dict):
                    logger.warning("policy: ignoring non-dict options for %s", model_name)
                    options = {}
                table[model_name] = {
                    "keep_alive": keep_alive,
                    "think": bool(think) if think is not None else True,
                    "options": {k: _parse_scalar(v) for k, v in options.items()},
                    "warmup": bool(item.get("warmup", False)),
                }
            if table:
                return table
    # Fallback (env-driven) — unchanged shape plus empty options.
    return {
        DEFAULT_MODEL: {
            "keep_alive": _parse_scalar(DEFAULT_KEEP_ALIVE),
            "think": True,
            "options": {},
            "warmup": False,
        },
    }


MODEL_POLICY = _load_policy()
THINK_POLICY_CONFIG = load_think_policy_config()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    targets = [(m, e) for m, e in MODEL_POLICY.items() if e.get("warmup")]
    if targets:
        # Sequential — parallel warmup of two 30B models will thrash the GPU.
        for model, entry in targets:
            await _warmup_model(model, entry)
    else:
        logger.info("warmup: no models flagged warmup: true; skipping")

    yield

    # --- shutdown ---
    # Nothing to clean up today. If you later add an httpx.AsyncClient or a
    # background task, close/cancel it here.

async def _warmup_model(model: str, entry: dict[str, Any]) -> None:
    """Send a tiny generation so Ollama loads the model at the policy num_ctx
    and pins it according to keep_alive."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "stream": False,
        "keep_alive": entry.get("keep_alive", -1),
        "think": False,
        "options": {**(entry.get("options") or {}), "num_predict": 1},
    }
    try:
        timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            r.raise_for_status()
        logger.info(
            "warmup: %s loaded at num_ctx=%s keep_alive=%s",
            model,
            (entry.get("options") or {}).get("num_ctx"),
            entry.get("keep_alive"),
        )
    except Exception as exc:
        logger.warning("warmup: %s failed: %s", model, exc)

app = FastAPI(title="Ollama OpenAI Router", lifespan=lifespan, version="0.1.0")

# Roles Ollama accepts. Anything else gets dropped with a warning.
_ALLOWED_ROLES = {"system", "user", "assistant", "tool"}

_ALLOWED_ROLES = {"system", "user", "assistant", "tool"}


def _content_part_to_text(part: Any) -> str:
    """Extract plain text from a single content part, regardless of shape."""
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return str(part)
    if isinstance(part.get("text"), str):
        return part["text"]
    if isinstance(part.get("content"), str):
        return part["content"]
    if isinstance(part.get("content"), list):
        return "".join(_content_part_to_text(p) for p in part["content"])
    return ""


def _coerce_tool_arguments(args: Any) -> dict:
    """Ollama expects tool_call.function.arguments as a dict."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        if not args.strip():
            return {}
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            logger.warning("router: tool arguments not valid JSON: %r", args[:200])
            return {}
    return {}


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate incoming messages (OpenAI-shape or Anthropic-shape content
    blocks as emitted by Zoo Code / Roo Code) into the shape Ollama's
    /api/chat expects:
      - content is always a string
      - assistant tool calls are at top level as `tool_calls`
      - tool results are separate messages with role="tool" and tool_call_id
    """
    out: list[dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        if role not in _ALLOWED_ROLES:
            logger.warning("router: dropping message with unsupported role=%s", role)
            continue

        content = msg.get("content")

        # Case 1: content is a list of Anthropic/OpenAI content blocks.
        if isinstance(content, list):
            text_chunks: list[str] = []
            extracted_tool_calls: list[dict] = []   # assistant tool_use blocks
            extracted_tool_results: list[dict] = [] # user tool_result blocks

            for part in content:
                if not isinstance(part, dict):
                    text_chunks.append(str(part))
                    continue

                ptype = part.get("type")

                if ptype == "tool_use":
                    # Anthropic-style assistant tool call.
                    extracted_tool_calls.append({
                        "id": part.get("id"),
                        "type": "function",
                        "function": {
                            "name": part.get("name", ""),
                            "arguments": _coerce_tool_arguments(part.get("input")),
                        },
                    })
                elif ptype == "tool_result":
                    # Anthropic-style tool result. Must become its own
                    # role="tool" message paired by tool_call_id.
                    tr_content = part.get("content", "")
                    if isinstance(tr_content, list):
                        tr_content = "".join(_content_part_to_text(p) for p in tr_content)
                    elif not isinstance(tr_content, str):
                        try:
                            tr_content = json.dumps(tr_content)
                        except (TypeError, ValueError):
                            tr_content = str(tr_content)
                    extracted_tool_results.append({
                        "role": "tool",
                        "tool_call_id": part.get("tool_use_id") or part.get("tool_call_id"),
                        "content": tr_content,
                    })
                else:
                    # text / input_text / unknown — treat as plain text.
                    text_chunks.append(_content_part_to_text(part))

            # Tool results must come *before* the user's text in the message
            # stream so they pair correctly with the prior assistant's
            # tool_calls. Emit them first.
            out.extend(extracted_tool_results)

            text_content = "".join(text_chunks)

            if role == "assistant":
                norm: dict[str, Any] = {"role": "assistant", "content": text_content}
                if extracted_tool_calls:
                    norm["tool_calls"] = extracted_tool_calls
                # Always emit assistant turns (even empty-content with
                # tool_calls) so the model sees its own prior actions.
                if text_content or extracted_tool_calls:
                    out.append(norm)
            else:
                # user/system: only emit if there's residual text after
                # tool_results have been split out.
                if text_content:
                    out.append({"role": role, "content": text_content})
            continue

        # Case 2: content is a string (or missing). OpenAI-shape path.
        norm = {"role": role, "content": "" if content is None else str(content)}

        if msg.get("name") is not None:
            norm["name"] = msg["name"]
        if msg.get("tool_call_id") is not None:
            norm["tool_call_id"] = msg["tool_call_id"]
        if msg.get("images") is not None:
            norm["images"] = msg["images"]

        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            converted = []
            for tc in msg["tool_calls"]:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                converted.append({
                    "id": tc.get("id"),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": _coerce_tool_arguments(fn.get("arguments")),
                    },
                })
            if converted:
                norm["tool_calls"] = converted

        out.append(norm)

    return out


def _build_ollama_payload(body: dict[str, Any], think: bool) -> dict[str, Any]:
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="'model' is required")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty array")

    logger.info(
        "router: inbound model=%s tools=%s tool_choice=%s msgs=%d",
        model,
        "yes" if body.get("tools") else "no",
        body.get("tool_choice"),
        len(messages or []),
    )

    policy_entry = MODEL_POLICY.get(model, {})
    policy_options: dict[str, Any] = dict(policy_entry.get("options") or {})

    keep_alive = body.get("keep_alive")
    if keep_alive is None:
        keep_alive = policy_entry.get("keep_alive", os.getenv("OLLAMA_KEEP_ALIVE", "10m"))

    # 1) Start with policy defaults (so num_ctx, num_batch, etc. are always present).
    options: dict[str, Any] = dict(policy_options)

    # 2) Layer OpenAI-style scalar passthroughs on top — these are client intent.
    passthrough = {
        "temperature": "temperature",
        "top_p": "top_p",
        "top_k": "top_k",
        "presence_penalty": "presence_penalty",
        "frequency_penalty": "frequency_penalty",
        "repeat_penalty": "repeat_penalty",
        "seed": "seed",
    }
    for src, dst in passthrough.items():
        if src in body and body[src] is not None:
            options[dst] = body[src]
    if body.get("max_tokens") is not None:
        options["num_predict"] = body["max_tokens"]
    if body.get("stop") is not None:
        options["stop"] = body["stop"]

    # 3) Layer the explicit Ollama-style options block from the client on top,
    #    but re-assert policy-locked keys (num_ctx) so a misconfigured client
    #    cannot force an Ollama reload at a different context size.
    client_options = body.get("options")
    if client_options is not None:
        if not isinstance(client_options, dict):
            raise HTTPException(status_code=400, detail="'options' must be an object")
        for k, v in client_options.items():
            if k in POLICY_LOCKED_OPTIONS and k in policy_options:
                if v != policy_options[k]:
                    logger.info(
                        "router: overriding client %s=%s with policy %s=%s for %s",
                        k, v, k, policy_options[k], model,
                    )
                continue  # policy wins
            options[k] = v

    # 4) Re-assert locked keys one more time in case step 2 clobbered them
    #    (it doesn't today, but cheap insurance).
    for k in POLICY_LOCKED_OPTIONS:
        if k in policy_options:
            options[k] = policy_options[k]

    payload = {
        "model": model,
        "messages": _normalize_messages(messages),
        "stream": bool(body.get("stream", False)),
        "keep_alive": keep_alive,
        "think": think,
    }

    logger.info(
        "router: normalized msgs=%s",
        [
            {"role": m["role"],
            "tc": len(m.get("tool_calls", []) or []),
            "tci": m.get("tool_call_id"),
            "clen": len(m.get("content") or "")}
            for m in payload["messages"]
        ],
    )

    char_total = sum(
        len(m.get("content") or "")
        + sum(len(json.dumps(tc.get("function", {}).get("arguments") or {}))
            for tc in (m.get("tool_calls") or []))
        for m in payload["messages"]
    )
    approx_tokens = char_total // 4
    policy_ctx = (MODEL_POLICY.get(payload["model"], {}).get("options") or {}).get("num_ctx")
    logger.info(
        "router: outbound model=%s approx_tokens=%d policy_num_ctx=%s headroom=%s",
        payload["model"], approx_tokens, policy_ctx,
        (policy_ctx - approx_tokens) if policy_ctx else "unknown",
    )
    logger.info(
        "router: payload stream=%s num_predict=%s tool_choice=%s",
        payload.get("stream"),
        (payload.get("options") or {}).get("num_predict"),
        payload.get("tool_choice"),
    )
    if policy_ctx and approx_tokens > policy_ctx * 0.9:
        logger.warning(
            "router: payload approaches num_ctx (%d / %d). Truncation likely.",
            approx_tokens, policy_ctx,
        )
        raise HTTPException(
            status_code=413,
            detail=f"Request approx {approx_tokens} tokens exceeds policy num_ctx {policy_ctx} for {payload['model']}. "
                f"Reduce history, condense context, or switch to a model with larger num_ctx.",
        )

    # Exsure tools are forwarded
    if body.get("tools") is not None:
        payload["tools"] = body["tools"]
    if body.get("tool_choice") is not None:
        payload["tool_choice"] = body["tool_choice"]

    if options:
        payload["options"] = options
    if body.get("format") is not None:
        payload["format"] = body["format"]
    return payload

async def _ollama_post(path: str, payload: dict, stream: bool = False,):
    """POST to Ollama with timeouts appropriate for local LLM generation.

    Non-streaming chat completions on a 30B model can take minutes; the
    httpx default of 5s is far too short.
    """
    timeout = httpx.Timeout(
        connect=10.0,
        read=600.0,      # 10 min: covers prefill + full num_predict generation
        write=30.0,
        pool=30.0,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{OLLAMA_BASE_URL}{path}", json=payload)
        return response


@app.get("/healthz")
async def healthz() -> JSONResponse:
    try:
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/version")
            resp.raise_for_status()
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=503)


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    items = []
    now = int(time.time())
    for model in MODEL_POLICY.keys():
        items.append(
            {
                "id": model,
                "object": "model",
                "created": now,
                "owned_by": "ollama",
            }
        )
    return JSONResponse({"object": "list", "data": items})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    try:
        think_override = parse_think_override(request.headers.get("X-Ollama-Think"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    model_name = body.get("model")
    model_default_think = MODEL_POLICY.get(model_name, {}).get("think", True)
    think = should_enable_think(
        body=body,
        override=think_override,
        config=THINK_POLICY_CONFIG,
        default_think=model_default_think,
    )
    payload = _build_ollama_payload(body, think=think)
    stream = payload.get("stream", False)

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = payload["model"]

    if stream:
        async def event_stream():
            # Opening role chunk so clients see structure immediately.
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(first_chunk)}\n\n"

            # Single queue feeds the generator. Heartbeat task pushes
            # keepalive comments; reader task pushes real SSE frames.
            queue: asyncio.Queue = asyncio.Queue()
            SENTINEL = object()

            async def heartbeat():
                """Emit an SSE comment every 15s while the upstream is
                producing nothing, so clients and intermediate proxies
                don't treat the silent prefill window as a dead
                connection."""
                try:
                    while True:
                        await asyncio.sleep(15)
                        await queue.put(": keepalive\n\n")
                except asyncio.CancelledError:
                    pass

            async def reader():
                """Stream Ollama's /api/chat response and translate each
                chunk into an OpenAI-shape SSE frame."""
                try:
                    timeout = httpx.Timeout(
                        connect=10.0, read=600.0, write=30.0, pool=30.0
                    )
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream(
                            "POST",
                            f"{OLLAMA_BASE_URL}/api/chat",
                            json=payload,
                        ) as resp:
                            if resp.status_code >= 400:
                                error_text = (await resp.aread()).decode(
                                    "utf-8", errors="ignore"
                                )
                                logger.error(
                                    "ollama upstream error %s: %s",
                                    resp.status_code,
                                    error_text[:500],
                                )
                                err_chunk = {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": created,
                                    "model": model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": "error",
                                    }],
                                    "error": {
                                        "message": error_text or f"upstream status {resp.status_code}",
                                        "type": "upstream_error",
                                        "code": resp.status_code,
                                    },
                                }
                                await queue.put(
                                    f"data: {json.dumps(err_chunk)}\n\n"
                                )
                                return

                            saw_tool_calls = False
                            async for line in resp.aiter_lines():
                                if not line.strip():
                                    continue
                                data = json.loads(line)
                                message = data.get("message") or {}

                                # Tool-call delta translation.
                                tc_deltas = _streaming_tool_call_deltas(
                                    message.get("tool_calls")
                                )
                                if tc_deltas:
                                    saw_tool_calls = True
                                    tc_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"tool_calls": tc_deltas},
                                            "finish_reason": None,
                                        }],
                                    }
                                    await queue.put(
                                        f"data: {json.dumps(tc_chunk)}\n\n"
                                    )

                                # Plain content delta.
                                token = message.get("content", "")
                                if token:
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": token},
                                            "finish_reason": None,
                                        }],
                                    }
                                    await queue.put(
                                        f"data: {json.dumps(chunk)}\n\n"
                                    )

                                if data.get("done"):
                                    if saw_tool_calls:
                                        finish_reason = "tool_calls"
                                    else:
                                        dr = data.get("done_reason")
                                        finish_reason = (
                                            dr if dr in ("stop", "length", "content_filter")
                                            else "stop"
                                        )
                                    end_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {},
                                            "finish_reason": finish_reason,
                                        }],
                                    }
                                    await queue.put(
                                        f"data: {json.dumps(end_chunk)}\n\n"
                                    )
                                    break
                except Exception as exc:
                    logger.exception("router: reader task failed: %s", exc)
                    err_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "error",
                        }],
                        "error": {
                            "message": str(exc),
                            "type": "router_error",
                        },
                    }
                    await queue.put(f"data: {json.dumps(err_chunk)}\n\n")
                finally:
                    await queue.put(SENTINEL)

            hb_task = asyncio.create_task(heartbeat())
            rd_task = asyncio.create_task(reader())
            try:
                while True:
                    item = await queue.get()
                    if item is SENTINEL:
                        break
                    yield item
            finally:
                hb_task.cancel()
                if not rd_task.done():
                    rd_task.cancel()
                for t in (hb_task, rd_task):
                    try:
                        await t
                    except:
                        pass
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    response = await _ollama_post("/api/chat", payload, stream=False)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    result = response.json()
    ollama_message = result.get("message") or {}
    content = ollama_message.get("content", "") or ""
    tool_calls = _translate_tool_calls(ollama_message.get("tool_calls"))

    assistant_message = {"role": "assistant", "content": content}
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls

    if tool_calls:
        finish_reason = "tool_calls"
    else:
        done_reason = result.get("done_reason")
        finish_reason = done_reason if done_reason in ("stop", "length", "content_filter") else "stop"

    prompt_tokens = result.get("prompt_eval_count", 0)
    completion_tokens = result.get("eval_count", 0)

    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": assistant_message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    )


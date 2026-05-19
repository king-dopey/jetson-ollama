import json
import os
import time
import uuid
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Ollama OpenAI Router", version="0.1.0")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
POLICY_FILE = os.getenv("MODEL_POLICY_FILE", "/app/model_policy.yml")
DEFAULT_MODEL = os.getenv("MODEL_DEFAULT", "qwen3.6:35b-a3b")
CODER_MODEL = os.getenv("MODEL_CODER", "qwen2.5-coder:32b-instruct")
DEFAULT_KEEP_ALIVE = os.getenv("KEEP_ALIVE_DEFAULT", "-1")
CODER_KEEP_ALIVE = os.getenv("KEEP_ALIVE_CODER", "0")


def _load_policy() -> dict[str, Any]:
    if os.path.exists(POLICY_FILE):
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f) or {}
            models = parsed.get("models", [])
            if isinstance(models, list):
                table = {}
                for item in models:
                    model_name = item.get("model")
                    keep_alive = item.get("keep_alive")
                    if model_name:
                        table[model_name] = keep_alive
                if table:
                    return table

    return {
        DEFAULT_MODEL: int(DEFAULT_KEEP_ALIVE) if str(DEFAULT_KEEP_ALIVE).lstrip("-").isdigit() else DEFAULT_KEEP_ALIVE,
        CODER_MODEL: int(CODER_KEEP_ALIVE) if str(CODER_KEEP_ALIVE).lstrip("-").isdigit() else CODER_KEEP_ALIVE,
    }


MODEL_KEEP_ALIVE = _load_policy()


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        normalized.append({"role": role, "content": str(content)})
    return normalized


def _build_ollama_payload(body: dict[str, Any]) -> dict[str, Any]:
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="'model' is required")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty array")

    keep_alive = body.get("keep_alive")
    if keep_alive is None:
        keep_alive = MODEL_KEEP_ALIVE.get(model, os.getenv("OLLAMA_KEEP_ALIVE", "10m"))

    options = {}
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

    payload = {
        "model": model,
        "messages": _normalize_messages(messages),
        "stream": bool(body.get("stream", False)),
        "keep_alive": keep_alive,
    }

    if options:
        payload["options"] = options

    return payload


async def _ollama_post(path: str, payload: dict[str, Any], stream: bool = False):
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if stream:
            return client.stream("POST", f"{OLLAMA_BASE_URL}{path}", json=payload)
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
    for model in MODEL_KEEP_ALIVE.keys():
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
    payload = _build_ollama_payload(body)
    stream = payload.get("stream", False)

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = payload["model"]

    if stream:
        async def event_stream():
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(first_chunk)}\n\n"

            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=30.0)) as client:
                async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
                    if resp.status_code >= 400:
                        error_text = await resp.aread()
                        raise HTTPException(status_code=resp.status_code, detail=error_text.decode("utf-8", errors="ignore"))

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("done"):
                            end_chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            }
                            yield f"data: {json.dumps(end_chunk)}\n\n"
                            break

                        token = data.get("message", {}).get("content", "")
                        if token:
                            chunk = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created,
                                "model": model,
                                "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                            }
                            yield f"data: {json.dumps(chunk)}\n\n"

            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    response = await _ollama_post("/api/chat", payload, stream=False)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    result = response.json()
    content = result.get("message", {}).get("content", "")

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
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    )

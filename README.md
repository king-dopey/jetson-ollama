# Jetson AGX Orin LLM Serving Node (Ollama + Optional OpenAI Router)

This repository runs only the LLM serving node for LAN access by LibreChat (hosted elsewhere).

## Files

- `docker-compose.yml`: Ollama service plus optional `fastapi-router` profile.
- `router/model_policy.yml`: model to `keep_alive` defaults.
- `.env.example`: environment values for ports and model behavior.

## Network and Security Notes

- Exposed ports intentionally bind on all interfaces for LAN use:
  - `0.0.0.0:11434` (Ollama API)
  - `0.0.0.0:4000` (OpenAI-compatible router, only when profile `proxy` is enabled)
- Restrict access at host firewall/router ACLs to trusted LAN clients.

## Start Services

```bash
cp .env.example .env

docker compose up -d
# Optional OpenAI-compatible single endpoint for LibreChat:
docker compose --profile proxy up -d --build
```

## Pull Models (on Ollama)

```bash
curl -sS http://127.0.0.1:11434/api/pull -d '{"model":"qwen3.6:35b-a3b"}'
curl -sS http://127.0.0.1:11434/api/pull -d '{"model":"qwen2.5-coder:32b-instruct"}'
```

## Test Models API

Using optional router endpoint (`/v1`):

```bash
curl -sS http://127.0.0.1:4000/v1/models | jq .
```

Directly on Ollama tags endpoint:

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

## Chat Completion Tests

### Default/general model (stays warm)

`keep_alive: -1` is set by router policy for this model by default.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "messages": [{"role": "user", "content": "Give me a one-line summary of Jetson Orin."}]
  }' | jq .
```

### Coding model (cold/evicted)

`keep_alive: 0` is set by router policy for this model by default.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-coder:32b-instruct",
    "messages": [{"role": "user", "content": "Write a Python function to reverse a linked list."}]
  }' | jq .
```

### Override keep_alive per request (explicit caller control)

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-coder:32b-instruct",
    "keep_alive": "2m",
    "messages": [{"role": "user", "content": "Stay loaded briefly."}]
  }' | jq .
```

## Direct Ollama OpenAI-Compatible Path

If LibreChat can call Ollama directly, set base URL to `http://ORIN_IP:11434/v1`.

Per-request keep_alive can be set in payload if your client supports sending it.

## LibreChat Configuration

- Base URL (recommended with policy routing): `http://ORIN_IP:4000/v1`
- Model IDs:
  - `qwen3.6:35b-a3b`
  - `qwen2.5-coder:32b-instruct`
- Set LibreChat default model to `qwen3.6:35b-a3b`.

## Jetson Runtime Notes

- Jetson AI Lab recommends vLLM + AWQ/NVFP4 for top Qwen3.6 throughput on Orin/Thor.
- This stack intentionally uses Ollama for automatic model residency control (`keep_alive` + `OLLAMA_MAX_LOADED_MODELS=1`).
- `qwen2.5-coder` is supported by Ollama even if not currently listed in Jetson AI Lab model cards.
- If you switch to NVIDIA's vLLM command for Qwen3.6, use a separate endpoint (typically `:8000`) and keep this Ollama stack for two-model hot/cold policy behavior.

## Memory Behavior Summary

- `OLLAMA_MAX_LOADED_MODELS=1` ensures only one model remains loaded at a time.
- Router policy defaults:
  - `qwen3.6:35b-a3b` -> `keep_alive=-1` (stay loaded)
  - `qwen2.5-coder:32b-instruct` -> `keep_alive=0` (unload after request)
- Global fallback default on Ollama: `OLLAMA_KEEP_ALIVE=10m`.

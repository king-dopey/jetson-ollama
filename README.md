# Jetson AGX Orin LLM Serving Node (Ollama + Optional OpenAI Router)

This repository runs only the LLM serving node for LAN access by LibreChat (hosted elsewhere).

This node is single-tenant by design: do not run any other GPU workload or heavyweight CPU workload here. Extra containers, dev tools, or interactive sessions that touch the GPU break the two-warm memory budget.

## Files

- `docker-compose.yml`: Ollama service plus optional `fastapi-router` profile.
- `router/model_policy.yml`: per-model `keep_alive` and default `think` policy.
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
# Optional verifier pull helper:
docker compose --profile verifier up ollama-pull-verifier
```

`docker compose up -d` also runs a one-shot `ollama-warmup` container that preloads the two warm models so `/api/ps` shows them resident without a manual warm call. The warmup logic now lives in `scripts/warmup.sh`; you can customize the script directly if needed. Override the model list with `WARMUP_MODELS` in `.env` using the `model@num_ctx` form, for example `WARMUP_MODELS="qwen3-coder:30b@16384 qwen3.6:35b-a3b@32768"`. Entries without `@num_ctx` fall back to `WARMUP_DEFAULT_NUM_CTX` (default `16384`). You can rerun warmup independently with `docker compose run --rm ollama-warmup`.

Troubleshooting: If you previously saw `WARN[0000] The "..." variable is not set` from `docker compose`, it was caused by unescaped shell variables in inline compose commands. The warmup logic now lives in `scripts/warmup.sh`.

### Warmup pull failures

The warmup container now pulls models with streaming `POST /api/pull` and only treats the pull as successful when the stream emits `"status":"success"`. It retries pull+registration checks up to `PULL_MAX_RETRIES` times (default `3`) with exponential full-jitter backoff from `PULL_BACKOFF_SEC` (default `10`). A model is warmed only after `/api/tags` confirms it is registered locally.

For each model in `WARMUP_MODELS`, warmup emits a reload notice when it finds a resident model at the wrong context length, then emits one final status line and includes that final status in the summary block:

| Status | Meaning |
| --- | --- |
| `reloading` | Informational line emitted before warmup unloads a resident model whose `/api/ps` `context_length` does not match the requested `num_ctx`. |
| `already-warm` | Model is already resident in `/api/ps` at the requested `context_length`, so warmup skips it. |
| `pulled-warmed` | Model was missing, pull succeeded, warm call succeeded, and `/api/ps` confirms residency at the requested `context_length`. |
| `already-pulled-warmed` | Model was already present in `/api/tags`, warm call succeeded, and `/api/ps` confirms residency at the requested `context_length`. |
| `pull-failed` | Streaming pull never reached `{"status":"success"}` after retries. |
| `post-pull-missing` | Pull reported success but `/api/tags` still did not list the model. |
| `warm-failed` | `/api/generate` returned non-2xx. |
| `not-resident` | Warm call returned 2xx, but post-warm `/api/ps` polling did not confirm residency with a live `expires_at`. |
| `wrong-ctx` | Model became resident, but `/api/ps` still reported a different `context_length` after the post-warm poll. |

`not-resident` means the warm call itself succeeded but Ollama did not keep the model loaded. The most common causes are:

- `OLLAMA_MAX_LOADED_MODELS` budget is already exhausted by another resident model.
- A previous request with `keep_alive: 0` evicted the model.

`wrong-ctx` means the model is resident but not at the requested `num_ctx`. Warmup now auto-reloads any resident model it finds at the wrong context before warming it again. Operators can confirm the fix by checking `/api/ps` and verifying `context_length` is `16384` for `qwen3-coder:30b` and `32768` for `qwen3.6:35b-a3b`, not `262144`.

Manual recovery:

```bash
docker compose run --rm ollama-warmup
curl -sS http://127.0.0.1:11434/api/ps | jq .
```

If warmup still fails for one model, run:

```bash
docker compose exec ollama ollama pull qwen3-coder:30b
docker compose run --rm ollama-warmup
```

Intermittent warmup pull failures are usually network or registry-side timeouts, not invalid tags. Validated tags currently in use are `qwen3-coder:30b`, `qwen3.6:35b-a3b`, and `nemotron-cascade-2:30b`.

## Models

The Orin 64 GB node is sized to keep two MoE models warm by default while leaving headroom for KV cache, the router, and the OS.

| Model ID | Purpose | Default keep_alive | Default think | Supported `num_ctx` ceiling | Notes |
| --- | --- | --- | --- | --- | --- |
| `qwen3-coder:30b` | Strict-JSON and structured-output workloads for boundary selection and cue-ID extraction. | `-1` | `false` | `16384` | Do not raise above `32768` unless you first evict the other warm model. |
| `qwen3.6:35b-a3b` | Narrative summarization workloads. | `-1` | `true` | `32768` | Hybrid attention keeps KV usage comparatively small. |
| `nemotron-cascade-2:30b` | Optional reasoning verifier for ambiguous structured answers. | `10m` | `true` | `16384` | Only resident while actively in use; expect one warm-model eviction when it loads. |
| `qwen2.5-coder:32b-instruct` | Ad-hoc LibreChat coding use. | `0` | `true` | Operator-managed | Remains cold by default and should not be counted in the two-warm residency plan. |

### Budget Math

The two-warm plan is only valid at Q4_K_M with `q8_0` KV cache and `OLLAMA_NUM_PARALLEL=1`:

WARNING: If a model is loaded without an explicit `num_ctx`, Ollama will use its native context length (256K+ for these models), which inflates the resident footprint to about 33 GB per model and breaks the two-warm budget. Always set `num_ctx` per call or rely on the warmup container.

| Component | Expected residency |
| --- | --- |
| `qwen3-coder:30b` weights | ~18-19 GB |
| `qwen3.6:35b-a3b` weights | ~22-24 GB |
| KV cache (`16K` detect, `32K` summary) | ~3-5 GB combined |
| CUDA + Ollama runtime | ~2-3 GB |
| OS + Docker + router + misc | ~3-5 GB |
| Resident total | ~49-56 GB |
| Headroom on 64 GB | ~8-15 GB |

## Operator Host Setup

Apply these host-level settings before you rely on the two-warm plan.

### Disable JetPack zram

Ubuntu for Jetson commonly enables `nvzramconfig.service`, which creates a zram swap device around half of system RAM. That is acceptable for bursty workloads, but it is hostile to resident LLM weights on unified memory because the kernel will start compressing and faulting model pages instead of leaving them GPU-accessible, which causes major latency spikes and intermittent upstream `500` errors under pressure.

Check the exact unit name on this JetPack build before changing it:

```bash
systemctl list-unit-files | grep -i zram
```

Disable it persistently on the host:

```bash
sudo systemctl disable --now nvzramconfig.service
sudo swapoff -a
# Optionally remove the unit file or mask it:
sudo systemctl mask nvzramconfig.service
```

Verify that swap is gone:

```bash
swapon --show
free -h
```

Do not attempt to manage zram from inside the container.

### Lock Jetson power and clocks

```bash
sudo nvpmodel -m 0
sudo jetson_clocks
```

If the packaged `jetson_clocks` unit exists, enable it at boot:

```bash
sudo systemctl enable jetson_clocks
```

If that unit is not present on this JetPack version, create a simple oneshot service using the path reported by `command -v jetson_clocks`:

```ini
# /etc/systemd/system/jetson-clocks.service
[Unit]
Description=Lock Jetson clocks to maximum
After=multi-user.target

[Service]
Type=oneshot
ExecStart=<output of command -v jetson_clocks>
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jetson-clocks.service
```

Verify the power model and clocks:

```bash
sudo nvpmodel -q
sudo jetson_clocks --show
```

### Kernel VM tunables for LLM residency

Create a sysctl drop-in on the host:

```conf
# /etc/sysctl.d/90-llm.conf
vm.swappiness = 10
vm.overcommit_memory = 1
```

- `vm.swappiness = 10`: strongly prefer keeping resident model pages in RAM instead of swapping under moderate pressure.
- `vm.overcommit_memory = 1`: allow the allocator to reserve memory for large model loads without conservative overcommit rejections.

Apply the settings:

```bash
sudo sysctl --system
```

## Operator Setup

Pull the required models on the Orin after Ollama is up:

```bash
ollama pull qwen3-coder:30b
ollama pull qwen3.6:35b-a3b
ollama pull qwen2.5-coder:32b-instruct
# Optional verifier:
ollama pull nemotron-cascade-2:30b
```

If you want Compose to trigger the optional verifier pull after Ollama becomes healthy, run:

```bash
docker compose --profile verifier up ollama-pull-verifier
```

The warmup container is designed for the documented two-model budget and should normally use:

```bash
WARMUP_MODELS="qwen3-coder:30b@16384 qwen3.6:35b-a3b@32768"
```

Use `WARMUP_DEFAULT_NUM_CTX=16384` when you want a shared fallback for entries that omit `@num_ctx`.

## Ollama Runtime Defaults

The `.env.example` file now carries the Jetson-oriented defaults for this two-warm-model plan:

| Env var | Default | What it does |
| --- | --- | --- |
| `OLLAMA_KEEP_ALIVE` | `10m` | Global fallback residency when the request and per-model policy do not set `keep_alive`. |
| `OLLAMA_CONTEXT_LENGTH` | `16384` | Default context length applied to any model load that does not specify `num_ctx` (for example LibreChat or ad-hoc `curl`). Warm pipeline models override this per call. |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Allows `qwen3-coder:30b` and `qwen3.6:35b-a3b` to stay loaded together. |
| `OLLAMA_NUM_PARALLEL` | `1` | Serializes generation to preserve memory headroom on the 64 GB unified pool. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enables flash attention for lower memory pressure and better Jetson throughput. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Uses a higher-quality KV cache format for long-context requests. |
| `WARMUP_DEFAULT_NUM_CTX` | `16384` | Fallback `num_ctx` used by `scripts/warmup.sh` when a `WARMUP_MODELS` entry omits `@num_ctx`. |
| `PULL_MAX_RETRIES` | `3` | Warmup pull+registration retry limit per model in `scripts/warmup.sh`. |
| `PULL_BACKOFF_SEC` | `10` | Warmup base backoff seconds for exponential full-jitter pull retries. |

The Ollama image tag is left unpinned (`ollama/ollama:latest`) per operator preference. Operators who require reproducible deployments may pin a tag here; whichever tag is used must support arm64 flash attention on Jetson for `OLLAMA_FLASH_ATTENTION=1` to take effect.

After the stack starts, confirm model state and flash-attention startup behavior:

```bash
curl -sS http://127.0.0.1:11434/api/ps | jq '.models[] | {name, size_vram, context_length}'
docker compose logs ollama | grep -i 'flash attention'
```

Expect both warm models to be present, `context_length` to be `16384` for `qwen3-coder:30b` and `32768` for `qwen3.6:35b-a3b`, and combined `size_vram` to stay well under about 48 GB.

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

## Think Control Policy (Proxy -> Ollama)

LibreChat cannot directly set Ollama's `think` flag for each turn in this setup, so the proxy injects `think` in the Ollama `/api/chat` payload.

Policy defaults:

- Per-model defaults come from `router/model_policy.yml`.
- `qwen3-coder:30b` defaults to `think=false`.
- `qwen3.6:35b-a3b`, `nemotron-cascade-2:30b`, and `qwen2.5-coder:32b-instruct` default to `think=true`.
- `think=false` for web/browse/search-style tool flows (for example `web_search`, `browser`, `http_get`, `fetch`, `scrape`).
- `think=true` for non-web tools such as `file_search` and `openweather` unless summarization/size heuristics trigger `think=false`.
- `think=false` when message content is very large (`DISABLE_THINK_CHAR_THRESHOLD`) and for summary-like last-user turns over recent tool-heavy or long context.

Manual override header:

- `X-Ollama-Think: true`
- `X-Ollama-Think: false`

If the override header is present, it takes precedence over policy.

The router forwards the following request fields unchanged to Ollama's `/api/chat` endpoint when clients send them:

- `options` such as `num_ctx`, `num_predict`, `cache_type_k`, `cache_type_v`, and `num_keep`
- `format` including JSON schema structured-output payloads
- `keep_alive`
- `X-Ollama-Think`

Example A: automatic `think=false` from web-search style tool call.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "messages": [
      {"role": "user", "content": "Use web search and summarize key takeaways."}
    ],
    "tools": [
      {"type": "function", "function": {"name": "web_search", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
    ]
  }' | jq .
```

Example B: same request but force `think=true` with header override.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Ollama-Think: true' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "messages": [
      {"role": "user", "content": "Use web search and summarize key takeaways."}
    ],
    "tools": [
      {"type": "function", "function": {"name": "web_search", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
    ]
  }' | jq .
```

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

### Structured-output model (stays warm, default think=false)

`keep_alive: -1` and `think: false` are set by router policy for this model by default.

Warning: raising `num_ctx` beyond the ceiling listed above will exceed the unified-memory budget for a two-warm configuration.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-coder:30b",
    "format": {
      "type": "json_schema",
      "json_schema": {
        "name": "cue_selection",
        "schema": {
          "type": "object",
          "properties": {
            "cue_ids": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["cue_ids"]
        }
      }
    },
    "options": {
      "num_ctx": 16384,
      "num_predict": 256,
      "cache_type_k": "q8_0",
      "cache_type_v": "q8_0",
      "num_keep": 128
    },
    "messages": [{"role": "user", "content": "Return cue IDs as JSON only."}]
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

### Optional verifier model

`keep_alive: 10m` and `think: true` are set by router policy for this model by default.

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nemotron-cascade-2:30b",
    "messages": [{"role": "user", "content": "Verify whether the answer is internally consistent."}]
  }' | jq .
```

## Direct Ollama OpenAI-Compatible Path

If LibreChat can call Ollama directly, set base URL to `http://ORIN_IP:11434/v1`.

Per-request keep_alive can be set in payload if your client supports sending it.

## LibreChat Configuration

- Base URL (recommended with policy routing): `http://ORIN_IP:4000/v1`
- Model IDs:
  - `qwen3-coder:30b`
  - `qwen3.6:35b-a3b`
  - `nemotron-cascade-2:30b` (optional if pulled)
  - `qwen2.5-coder:32b-instruct`
- Set LibreChat default model to `qwen3.6:35b-a3b`.

## Jetson Runtime Notes

- Jetson AI Lab recommends vLLM + AWQ/NVFP4 for top Qwen3.6 throughput on Orin/Thor.
- This stack intentionally uses Ollama for automatic model residency control (`keep_alive` + `OLLAMA_MAX_LOADED_MODELS=2`).
- `qwen2.5-coder` is supported by Ollama even if not currently listed in Jetson AI Lab model cards.
- If you switch to NVIDIA's vLLM command for Qwen3.6, use a separate endpoint (typically `:8000`) and keep this Ollama stack for two-model hot/cold policy behavior.

## Memory Behavior Summary

- `OLLAMA_MAX_LOADED_MODELS=2` keeps `qwen3-coder:30b` and `qwen3.6:35b-a3b` warm together.
- Router policy defaults:
  - `qwen3-coder:30b` -> `keep_alive=-1`, `think=false`
  - `qwen3.6:35b-a3b` -> `keep_alive=-1` (stay loaded)
  - `nemotron-cascade-2:30b` -> `keep_alive=10m`, `think=true`
  - `qwen2.5-coder:32b-instruct` -> `keep_alive=0` (unload after request)
- Global fallback default on Ollama: `OLLAMA_KEEP_ALIVE=10m`.
- Loading `nemotron-cascade-2:30b` while both warm models are resident exceeds the two-warm budget. Ollama will evict one warm model to make room because `OLLAMA_MAX_LOADED_MODELS=2`, so expect a one-time reload penalty on the next call to the evicted model after the verifier runs.
- Leave the verifier at `keep_alive: 10m` so it does not remain resident longer than necessary.

### Verifying Two-Warm Residency

Check the live model table and memory pressure together:

```bash
curl -sS http://127.0.0.1:11434/api/ps | jq .
sudo tegrastats --interval 1000
```

What to look for:

- Before warmup completes, `/api/ps` may return `{"models":[]}`.
- After `ollama-warmup` exits with code 0, `/api/ps` must list both `qwen3-coder:30b` and `qwen3.6:35b-a3b` with `expires_at` far in the future (`keep_alive=-1`).
- RAM usage stabilizing around ~50-56 GB for the documented two-warm plan.
- SWAP staying at `0`, which confirms zram or other swap is not absorbing model pages.

If `/api/ps` is still empty after warmup, check `docker compose logs ollama-warmup` for pull or load errors.

# Jetson AGX Orin / Thor LLM Serving Node (Ollama)

This repository runs only the LLM serving node for LAN access by LibreChat (hosted elsewhere).

This node is single-tenant by design: do not run any other GPU workload or heavyweight CPU workload here. Extra containers, dev tools, or interactive sessions that touch the GPU break the two-warm memory budget.

## Profiles

This repo supports two board profiles through shared Docker Compose structure:

| Profile | Board | RAM | Primary Coding Model | Primary Chat Model |
| --- | --- | --- | --- | --- |
| `orin` | Jetson AGX Orin 64GB | 64 GB | `qwen3-coder:30b` | `qwen3.6:35b-a3b` |
| `thor` | Jetson AGX Thor 128GB | 128 GB | `qwen3-coder-next:q4_K_M` | `qwen3.6:35b-a3b-q8_0` |

Select the profile by setting `PROFILE=orin` or `PROFILE=thor` in `.env` before starting the stack. The profile determines which `models.yaml` and `stack.env` files are mounted into the Ollama container.

## Files

- `docker-compose.yml`: Ollama service with profile-driven model mounting.
- `.env.example`: environment values for ports, profile selection, and model behavior.
- `profiles/orin/models.yaml`: Orin model inventory and per-model options.
- `profiles/thor/models.yaml`: Thor model inventory and per-model options.
- `profiles/orin/stack.env`: Orin-specific environment overrides.
- `profiles/thor/stack.env`: Thor-specific environment overrides.

## Network and Security Notes

- Exposed ports intentionally bind on all interfaces for LAN use:
  - `0.0.0.0:11434` (Ollama API + OpenAI-compatible endpoint)
- Restrict access at host firewall/router ACLs to trusted LAN clients.

## Start Services

```bash
cp .env.example .env
# Set PROFILE=orin or PROFILE=thor in .env before starting
docker compose up -d
```

`docker compose up -d` also runs a one-shot `ollama-warmup` container that preloads the two warm models so `/api/ps` shows them resident without a manual warm call. The warmup logic lives in `scripts/warmup.sh`; you can customize the script directly if needed. Override the model list with `WARMUP_MODELS` in `.env` using the `model@num_ctx` form, for example `WARMUP_MODELS="qwen3-coder-next:q4_K_M@262144 qwen3.6:35b-a3b-q8_0@262144"`. Entries without `@num_ctx` fall back to `WARMUP_DEFAULT_NUM_CTX` (default `16384`). You can rerun warmup independently with `docker compose run --rm ollama-warmup`.

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

`wrong-ctx` means the model is resident but not at the requested `num_ctx`. Warmup now auto-reloads any resident model it finds at the wrong context before warming it again. Operators can confirm the fix by checking `/api/ps` and verifying `context_length` matches the profile-specific target (e.g., `65536` for Orin's `qwen3-coder:30b`, `262144` for Thor's `qwen3-coder-next:q4_K_M`).

Manual recovery:

```bash
docker compose run --rm ollama-warmup
curl -sS http://127.0.0.1:11434/api/ps | jq .
```

If warmup still fails for one model, run:

```bash
docker compose exec ollama ollama pull qwen3-coder-next:q4_K_M
docker compose run --rm ollama-warmup
```

Intermittent warmup pull failures are usually network or registry-side timeouts, not invalid tags. Validated tags currently in use are `qwen3-coder:30b`, `qwen3.6:35b-a3b`, `qwen3-coder-next:q4_K_M`, `qwen3.6:35b-a3b-q8_0`, and `nemotron-cascade-2:30b`.

## Models

### Orin 64 GB

The Orin 64 GB node is sized to keep two MoE models warm by default while leaving headroom for KV cache and the OS.

| Model ID | Purpose | Default keep_alive | Default think | Supported `num_ctx` ceiling | Notes |
| --- | --- | --- | --- | --- | --- |
| `qwen3-coder:30b` | Strict-JSON and structured-output workloads for boundary selection and cue-ID extraction. | `-1` | `false` | `65536` | Always warm; primary Coding preset model. |
| `qwen3.6:35b-a3b` | Narrative summarization workloads. | `10m` | `true` | `32768` | Chat preset model; loads opportunistically. |
| `qwen3:4b` | Lightweight utility model for fast turns. | `10m` | `true` | `65536` | Small enough to load alongside warm models. |
| `qwen3-vl:4b` | Vision-language tasks. | `10m` | `true` | `65536` | Loads opportunistically. |
| `gemma4:12b` | Medium-weight utility model. | `10m` | `true` | `65536` | Loads opportunistically. |
| `qwen3-embedding:4b` | Embedding generation for RAG pipelines. | `5m` | `false` | `8192` | Short residency; embedding-only workload. |
| `nemotron-cascade-2:30b-a3b-q4_K_M` | Optional reasoning verifier for ambiguous structured answers. | `10m` | `true` | `65536` | Only resident while actively in use; expect one warm-model eviction when it loads. |
| `gpt-oss:20b` | Secondary reasoning model. | `10m` | `true` | `65536` | Loads opportunistically. |
| `laguna-xs-2.1:q4_K_M` | Lightweight reasoning/verification model. | `10m` | `true` | `65536` | Loads opportunistically. |

#### Orin Budget Math

The two-warm plan is only valid at Q4_K_M with `q8_0` KV cache and `OLLAMA_NUM_PARALLEL=1`:

WARNING: If a model is loaded without an explicit `num_ctx`, Ollama will use its native context length (256K+ for these models), which inflates the resident footprint to about 33 GB per model and breaks the two-warm budget. Always set `num_ctx` per call or rely on the warmup container.

| Component | Expected residency |
| --- | --- |
| `qwen3-coder:30b` weights | ~19 GB |
| `qwen3.6:35b-a3b` weights | ~24 GB |
| KV cache (`64K` coder, `32K` chat) | ~3.6 GB combined |
| CUDA + Ollama runtime | ~2-3 GB |
| OS + Docker + misc | ~3-5 GB |
| Resident total | ~49-56 GB |
| Headroom on 64 GB | ~8-15 GB |

### Thor 128 GB

The Thor 128 GB node is sized to keep two large-context models warm at maximum context lengths, leveraging its doubled RAM for aggressive long-context workloads.

| Model ID | Purpose | Default keep_alive | Default think | Supported `num_ctx` ceiling | Notes |
| --- | --- | --- | --- | --- | --- |
| `qwen3-coder-next:q4_K_M` | Aggressive coding model with native 256K context. | `-1` | `false` | `262144` | Always warm; primary Coding preset model. |
| `qwen3.6:35b-a3b-q8_0` | High-quality chat and reasoning at 256K context. | `-1` | `true` | `262144` | Always warm; primary Chat preset model. |
| `gemma4:31b-it-q4_K_M` | Medium-weight utility model with extended keep_alive. | `20m` | `true` | `131072` | Loads opportunistically. |
| `devstral-small-2:24b-instruct-2512-q8_0` | French-capable coding assistant. | `20m` | `true` | `131072` | Loads opportunistically. |
| `north-mini-code-1.0:q8_0` | Lightweight coding model. | `20m` | `true` | `131072` | Loads opportunistically. |
| `granite4.1-guardian:8b-q6_K` | Content moderation and safety guardrails. | `20m` | `false` | `65536` | Safety-only workload; low temperature. |
| `qwen3:4b` | Lightweight utility model for fast turns. | `30m` | `true` | `65536` | Small enough to load alongside warm models. |
| `qwen3-vl:4b` | Vision-language tasks. | `30m` | `true` | `65536` | Loads opportunistically. |
| `gemma4:12b` | Medium-weight utility model. | `30m` | `true` | `65536` | Loads opportunistically. |
| `reader-lm:1.5b` | Document reading and extraction specialist. | `30m` | `false` | `65536` | Short context; low temperature. |
| `qwen3-embedding:4b` | Embedding generation for RAG pipelines. | `30m` | `false` | `8192` | Longer residency on Thor. |
| `nemotron-cascade-2:30b-a3b-q4_K_M` | Optional reasoning verifier for ambiguous structured answers. | `20m` | `true` | `131072` | Only resident while actively in use; expect one warm-model eviction when it loads. |
| `gpt-oss:20b` | Secondary reasoning model. | `20m` | `true` | `131072` | Loads opportunistically. |
| `laguna-xs-2.1:q4_K_M` | Lightweight reasoning/verification model. | `20m` | `true` | `131072` | Loads opportunistically. |

#### Thor Budget Math

The dual-warm plan targets 256K context for both primary models with `q8_0` KV cache and `OLLAMA_NUM_PARALLEL=1`:

| Component | Expected residency |
| --- | --- |
| `qwen3-coder-next:q4_K_M` weights | ~49 GB |
| `qwen3.6:35b-a3b-q8_0` weights | 39 GB |
| KV cache (`256K` coder, `256K` chat) | ~5.5 GB combined |
| CUDA + Ollama runtime | ~2-3 GB |
| OS + Docker + misc | ~4-6 GB |
| Resident total | ~99.5-103.5 GB |
| Headroom on 128 GB | ~24.5-28.5 GB |

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

Pull the required models on the target board after Ollama is up:

### Orin

```bash
ollama pull qwen3-coder:30b
ollama pull qwen3.6:35b-a3b
ollama pull qwen3:4b
ollama pull qwen3-vl:4b
ollama pull gemma4:12b
# Optional models:
ollama pull nemotron-cascade-2:30b-a3b-q4_K_M
ollama pull gpt-oss:20b
ollama pull laguna-xs-2.1:q4_K_M
```

### Thor

```bash
ollama pull qwen3-coder-next:q4_K_M
ollama pull qwen3.6:35b-a3b-q8_0
ollama pull gemma4:31b-it-q4_K_M
ollama pull devstral-small-2:24b-instruct-2512-q8_0
ollama pull north-mini-code-1.0:q8_0
ollama pull granite4.1-guardian:8b-q6_K
ollama pull qwen3:4b
ollama pull qwen3-vl:4b
ollama pull gemma4:12b
ollama pull reader-lm:1.5b
# Optional models:
ollama pull nemotron-cascade-2:30b-a3b-q4_K_M
ollama pull gpt-oss:20b
ollama pull laguna-xs-2.1:q4_K_M
```

The warmup container is designed for the documented two-model budget and should normally use the profile-specific defaults from `.env`:

```bash
# Orin:
WARMUP_MODELS="qwen3-coder:30b@65536 qwen3.6:35b-a3b@32768"
# Thor:
WARMUP_MODELS="qwen3-coder-next:q4_K_M@262144 qwen3.6:35b-a3b-q8_0@262144"
```

Use `WARMUP_DEFAULT_NUM_CTX` when you want a shared fallback for entries that omit `@num_ctx`.

## Ollama Runtime Defaults

The `.env.example` file carries the Jetson-oriented defaults for the two-warm-model plan. Profile-specific overrides live in `profiles/orin/stack.env` and `profiles/thor/stack.env`.

| Env var | Default | What it does |
| --- | --- | --- |
| `OLLAMA_KEEP_ALIVE` | `10m` | Global fallback residency when the request and per-model policy do not set `keep_alive`. |
| `OLLAMA_CONTEXT_LENGTH` | `16384` | Default context length applied to any model load that does not specify `num_ctx` (for example LibreChat or ad-hoc `curl`). Warm pipeline models override this per call. |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Allows two primary models to stay loaded together. |
| `OLLAMA_NUM_PARALLEL` | `1` | Serializes generation to preserve memory headroom on the unified pool. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enables flash attention for lower memory pressure and better Jetson throughput. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Uses a higher-quality KV cache format for long-context requests. |
| `WARMUP_DEFAULT_NUM_CTX` | `16384` (Orin) / `262144` (Thor) | Fallback `num_ctx` used by `scripts/warmup.sh` when a `WARMUP_MODELS` entry omits `@num_ctx`. |
| `PULL_MAX_RETRIES` | `3` | Warmup pull+registration retry limit per model in `scripts/warmup.sh`. |
| `PULL_BACKOFF_SEC` | `10` | Warmup base backoff seconds for exponential full-jitter pull retries. |

The Ollama image tag is left unpinned (`ollama/ollama:latest`) per operator preference. Operators who require reproducible deployments may pin a tag here; whichever tag is used must support arm64 flash attention on Jetson for `OLLAMA_FLASH_ATTENTION=1` to take effect.

After the stack starts, confirm model state and flash-attention startup behavior:

```bash
curl -sS http://127.0.0.1:11434/api/ps | jq '.models[] | {name, size_vram, context_length}'
docker compose logs ollama | grep -i 'flash attention'
```

Expect both warm models to be present with `context_length` matching the profile target, and combined `size_vram` to stay within the budget tables above.

## Test Models API

Directly on Ollama tags endpoint:

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

## Chat Completion Tests

### Default/general model (stays warm)

Orin: `qwen3.6:35b-a3b` with `keep_alive: 10m`.
Thor: `qwen3.6:35b-a3b-q8_0` with `keep_alive: -1`.

```bash
curl -sS http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "messages": [{"role": "user", "content": "Give me a one-line summary of Jetson Orin."}]
  }' | jq .
```

### Structured-output model (stays warm, default think=false)

Orin: `qwen3-coder:30b` with `keep_alive: -1`, `think: false`.
Thor: `qwen3-coder-next:q4_K_M` with `keep_alive: -1`, `think: false`.

Warning: raising `num_ctx` beyond the ceiling listed above will exceed the unified-memory budget for a two-warm configuration.

```bash
curl -sS http://127.0.0.1:11434/v1/chat/completions \
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
      "num_ctx": 65536,
      "num_predict": 256,
      "cache_type_k": "q8_0",
      "cache_type_v": "q8_0",
      "num_keep": 128
    },
    "messages": [{"role": "user", "content": "Return cue IDs as JSON only."}]
  }' | jq .
```

### Optional verifier model

Orin: `nemotron-cascade-2:30b-a3b-q4_K_M` with `keep_alive: 10m`, `think: true`.
Thor: `nemotron-cascade-2:30b-a3b-q4_K_M` with `keep_alive: 20m`, `think: true`.

```bash
curl -sS http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nemotron-cascade-2:30b-a3b-q4_K_M",
    "messages": [{"role": "user", "content": "Verify whether the answer is internally consistent."}]
  }' | jq .
```

## Direct Ollama OpenAI-Compatible Path

LibreChat can call Ollama directly. Set base URL to `http://ORIN_THOR_IP:11434/v1`.

Per-request keep_alive can be set in payload if your client supports sending it.

## LibreChat Configuration

- Base URL: `http://ORIN_THOR_IP:11434/v1`
- Model IDs (Orin):
  - `qwen3-coder:30b` (Coding preset)
  - `qwen3.6:35b-a3b` (Chat preset)
  - `nemotron-cascade-2:30b-a3b-q4_K_M` (optional if pulled)
  - `qwen3:4b`, `qwen3-vl:4b`, `gemma4:12b` (utility models)
- Model IDs (Thor):
  - `qwen3-coder-next:q4_K_M` (Coding preset)
  - `qwen3.6:35b-a3b-q8_0` (Chat preset)
  - `gemma4:31b-it-q4_K_M`, `devstral-small-2:24b-instruct-2512-q8_0`, `north-mini-code-1.0:q8_0` (utility models)
  - `granite4.1-guardian:8b-q6_K` (safety guardrails)
  - `qwen3:4b`, `qwen3-vl:4b`, `gemma4:12b`, `reader-lm:1.5b` (utility models)
- Set LibreChat default model to the Chat preset for each profile.

## Jetson Runtime Notes

- Jetson AI Lab recommends vLLM + AWQ/NVFP4 for top Qwen3.6 throughput on Orin/Thor.
- This stack intentionally uses Ollama for automatic model residency control (`keep_alive` + `OLLAMA_MAX_LOADED_MODELS=2`).
- If you switch to NVIDIA's vLLM command for Qwen3.6, use a separate endpoint (typically `:8000`) and keep this Ollama stack for two-model hot/cold policy behavior.

## Memory Behavior Summary

### Orin

- `OLLAMA_MAX_LOADED_MODELS=2` keeps `qwen3-coder:30b` and `qwen3.6:35b-a3b` warm together.
- Global fallback default on Ollama: `OLLAMA_KEEP_ALIVE=10m`.
- Loading `nemotron-cascade-2:30b-a3b-q4_K_M` while both warm models are resident exceeds the two-warm budget. Ollama will evict one warm model to make room because `OLLAMA_MAX_LOADED_MODELS=2`, so expect a one-time reload penalty on the next call to the evicted model after the verifier runs.

### Thor

- `OLLAMA_MAX_LOADED_MODELS=2` keeps `qwen3-coder-next:q4_K_M` and `qwen3.6:35b-a3b-q8_0` warm together at 256K context.
- Both primary models have `keep_alive: -1` (stay loaded indefinitely).
- Loading `nemotron-cascade-2:30b-a3b-q4_K_M` while both warm models are resident exceeds the two-warm budget. Ollama will evict one warm model to make room because `OLLAMA_MAX_LOADED_MODELS=2`, so expect a one-time reload penalty on the next call to the evicted model after the verifier runs.

### Verifying Two-Warm Residency

Check the live model table and memory pressure together:

```bash
curl -sS http://127.0.0.1:11434/api/ps | jq .
sudo tegrastats --interval 1000
```

What to look for:

- Before warmup completes, `/api/ps` may return `{"models":[]}`.
- After `ollama-warmup` exits with code 0, `/api/ps` must list both primary models with `expires_at` far in the future (`keep_alive=-1`).
- Orin RAM usage stabilizing around ~49-56 GB for the documented two-warm plan.
- Thor RAM usage stabilizing around ~99-103 GB for the dual 256K-warm plan.
- SWAP staying at `0`, which confirms zram or other swap is not absorbing model pages.

If `/api/ps` is still empty after warmup, check `docker compose logs ollama-warmup` for pull or load errors.

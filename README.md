# Jetson AGX Orin LLM Serving Node (Ollama)

This repository runs only the LLM serving node for LAN access by LibreChat (hosted elsewhere) and a Coding Agent (Zoo Code).

This node is single-tenant by design: do not run any other GPU workload or heavyweight CPU workload here. Extra containers, dev tools, or interactive sessions that touch the GPU break the two-warm memory budget.

## Repository Structure

```
.
├── .env.example                    # Template for global environment variables
├── docker-compose.yml              # Ollama service + ollama-warmup + verifier containers
├── LICENSE
├── profiles/
│   ├── ollama.env                  # Ollama runtime settings (host binding, cloud disable)
│   ├── warmup.env                  # Warmup container settings (models, retries, URLs)
│   └── jetson/
│       ├── orin.env                # Orin profile (64 GB unified memory)
│       └── thor.env                # Thor profile (128 GB unified memory)
└── scripts/
    ├── validate-model-tags.sh      # Model tag validation script
    └── warmup.sh                   # Warmup container model pull logic
```

## Profile System

The Docker Compose configuration uses a **layered env_file architecture** that separates service-specific defaults from hardware-specific settings:

### Ollama Service

```yaml
env_file:
  - profiles/ollama.env                  # Step 1: Ollama runtime defaults
  - profiles/jetson/${HARDWARE:-orin}.env  # Step 2: Hardware overrides
```

### Warmup Service

```yaml
env_file:
  - profiles/warmup.env                  # Step 1: Warmup defaults
  - profiles/jetson/${HARDWARE:-orin}.env  # Step 2: Hardware overrides
```

Variables defined in later files override earlier ones. This allows a single `docker-compose.yml` to support multiple hardware configurations without modification.

### Profile Files

| File | Purpose | Variables |
|------|---------|-----------|
| [`profiles/ollama.env`](profiles/ollama.env) | Ollama runtime settings | `OLLAMA_HOST`, `OLLAMA_NO_CLOUD` |
| [`profiles/warmup.env`](profiles/warmup.env) | Warmup container settings | `OLLAMA_URL`, `WARMUP_MODELS`, retry config |
| [`profiles/jetson/orin.env`](profiles/jetson/orin.env) | Orin-specific settings (64 GB) | Runtime defaults, warmup models, context lengths |
| [`profiles/jetson/thor.env`](profiles/jetson/thor.env) | Thor-specific settings (128 GB) | Runtime defaults, warmup models, context lengths |

### Selecting a Profile

Set the `HARDWARE` environment variable before running Docker Compose:

```bash
# Orin profile (default)
docker compose up -d

# Thor profile
HARDWARE=thor docker compose up -d
```

The `HARDWARE` variable defaults to `orin` if not set. The selected profile file (`profiles/jetson/${HARDWARE}.env`) is loaded after `ollama.env` or `warmup.env`, so its values take precedence.

### Quick Start

> [!TIP]
> To skip the `HARDWARE=` prefix in every command, copy `.env.example` to `.env` and set `HARDWARE=orin` or `HARDWARE=thor`:
>
> ```bash
> cp .env.example .env
> # Edit .env to set HARDWARE=thor if using Thor
> docker compose up -d
> ```

## Environment Variables

### Global Variables (profiles/global.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_IMAGE_TAG` | `ollama/ollama:latest` | Docker image tag for the Ollama container. Must support arm64 and flash attention for Jetson. |
| `OLLAMA_VOLUME_HOST` | `/storage/ollama` | Host filesystem path mounted as `/root/.ollama` inside the container. Models are stored here. |
| `OLLAMA_HOST` | `0.0.0.0:11434` | Network binding address and port. Format: `IP:port`. Used directly in docker-compose ports directive. |

### Hardware-Specific Variables (profiles/jetson/{orin,thor}.env)

#### Orin (64 GB Unified Memory)

| Variable | Value | Description |
|----------|-------|-------------|
| `HARDWARE` | `orin` | Hardware identifier for profile selection |
| `OLLAMA_KEEP_ALIVE` | `10m` | Global fallback residency when request doesn't set `keep_alive` |
| `OLLAMA_CONTEXT_LENGTH` | `65536` | Default context length for model loads without explicit `num_ctx` |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Maximum concurrent loaded models (two-warm budget) |
| `OLLAMA_NUM_PARALLEL` | `1` | Serialized generation to preserve VRAM headroom |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enable flash attention for lower memory pressure |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Higher-quality KV cache format for long-context requests |
| `MODEL_DEFAULT` | `qwen3.6:35b-a3b` | Default model ID expected by router policy |
| `WARMUP_MODELS` | `qwen3-coder:30b@65536 qwen3.6:35b-a3b@65536` | Models to preload at startup with `keep_alive=-1` |
| `WARMUP_DEFAULT_NUM_CTX` | `65536` | Fallback `num_ctx` when WARMUP_MODELS entry omits `@num_ctx` |
| `VERIFIER_PULL_MODEL` | `qwen3-coder:30b` | Model to pull with verifier container |

#### Thor (128 GB Unified Memory)

| Variable | Value | Description |
|----------|-------|-------------|
| `HARDWARE` | `thor` | Hardware identifier for profile selection |
| `OLLAMA_KEEP_ALIVE` | `10m` | Global fallback residency when request doesn't set `keep_alive` |
| `OLLAMA_CONTEXT_LENGTH` | `262144` | Default context length for model loads without explicit `num_ctx` |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Maximum concurrent loaded models (two-warm budget) |
| `OLLAMA_NUM_PARALLEL` | `2` | Higher parallelism for greater throughput on larger RAM budget |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enable flash attention for lower memory pressure |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Higher-quality KV cache format for long-context requests |
| `MODEL_DEFAULT` | `qwen3.6:35b-a3b-q8_0@262144` | Default model ID expected by router policy |
| `WARMUP_MODELS` | `qwen3-coder-next:q4_K_M@262144 qwen3.6:35b-a3b-q8_0@262144` | Models to preload at startup with `keep_alive=-1` |
| `WARMUP_DEFAULT_NUM_CTX` | `262144` | Fallback `num_ctx` when WARMUP_MODELS entry omits `@num_ctx` |
| `VERIFIER_PULL_MODEL` | `qwen3-coder-next:q4_K_M` | Model to pull with verifier container |

## Deployment

### Start Services

```bash
# Orin profile (default)
docker compose up -d

# Thor profile
HARDWARE=thor docker compose up -d
```

The stack includes two services:
- **ollama**: The main Ollama API server with NVIDIA GPU runtime
- **ollama-warmup**: One-shot container that preloads warm models after Ollama becomes healthy

### Verify Deployment

Check that Ollama is running and models are loaded:

```bash
# Check Ollama health
docker compose logs ollama | grep -i 'flash attention'

# Check loaded models
curl -sS http://127.0.0.1:11434/api/ps | jq '.models[] | {name, size_vram, context_length}'

# Check warmup status
docker compose logs ollama-warmup
```

Expected `context_length` values per profile:

| Profile | `qwen3-coder:30b` / `qwen3-coder-next:q4_K_M` | `qwen3.6:35b-a3b` / `qwen3.6:35b-a3b-q8_0` |
|---------|------------------------------------------------|---------------------------------------------|
| Orin | `65536` | `65536` |
| Thor | `262144` | `262144` |

### Rerun Warmup

```bash
# Orin profile (default)
docker compose run --rm ollama-warmup

# Thor profile
HARDWARE=thor docker compose run --rm ollama-warmup
```

### Verifier Pull Helper

To trigger the optional verifier pull after Ollama becomes healthy:

```bash
# Orin profile verifier (default HARDWARE=orin)
docker compose --profile verifier up ollama-pull-verifier

# Thor profile verifier
HARDWARE=thor docker compose --profile verifier up ollama-pull-verifier
```

## Models

### Orin (64 GB Unified Memory)

The Orin 64 GB node is sized to keep two MoE models warm by default while leaving headroom for KV cache, the OS, and other services.

| Model ID | Purpose | Default keep_alive | Default think | Supported `num_ctx` ceiling | Notes |
|----------|---------|-------------------|---------------|----------------------------|-------|
| `qwen3-coder:30b` | Strict-JSON and structured-output workloads for boundary selection and cue-ID extraction. | `-1` | `false` | `65536` | Orin warmup model; default `num_ctx` is `65536`. |
| `qwen3.6:35b-a3b` | Narrative summarization workloads. | `-1` | `true` | `65536` | Orin warmup model; hybrid attention keeps KV usage comparatively small; default `num_ctx` is `65536`. |
| `nemotron-cascade-2:30b` | Optional reasoning verifier for ambiguous structured answers. | `10m` | `true` | `65536` | Only resident while actively in use; expect one warm-model eviction when it loads. |
| `qwen2.5-coder:32b-instruct` | Ad-hoc LibreChat coding use. | `0` | `true` | Operator-managed | Remains cold by default and should not be counted in the two-warm residency plan. |

#### Memory Budget (Orin)

WARNING: If a model is loaded without an explicit `num_ctx`, Ollama will use its native context length (256K+ for these models), which inflates the resident footprint to about 33 GB per model and breaks the two-warm budget. Always set `num_ctx` per call or rely on the warmup container.

| Component | Expected residency |
|-----------|-------------------|
| `qwen3-coder:30b` weights | ~18-19 GB (measured via `ollama list`) |
| `qwen3.6:35b-a3b` weights | ~22-24 GB (estimated from model size) |
| KV cache (`64K`, `64K`) | ~3-5 GB combined |
| CUDA + Ollama runtime | ~2-3 GB (estimated overhead) |
| OS + Docker + misc | ~3-5 GB (estimated overhead) |
| **Resident total** | **~48-60 GB** |
| Headroom on 64 GB | ~4-16 GB |

### Thor (128 GB Unified Memory)

Thor uses different model variants and context lengths. The two-warm plan is only valid at Q4_K_M with `q8_0` KV cache and `OLLAMA_NUM_PARALLEL=2`:

WARNING: If a model is loaded without an explicit `num_ctx`, Ollama will use its native context length (256K+ for these models), which inflates the resident footprint to about 33 GB per model and breaks the two-warm budget. Always set `num_ctx` per call or rely on the warmup container.

| Component | Expected residency |
|-----------|-------------------|
| `qwen3-coder-next:q4_K_M` weights | ~51 GB (measured via `ollama list`) |
| `qwen3.6:35b-a3b-q8_0` weights | ~38 GB (measured via `ollama list`) |
| KV cache (`262K`, `262K`) | ~11-13 GB combined |
| CUDA + Ollama runtime | ~12 GB (measured via `docker stats`) |
| OS + Docker + misc | ~10-12 GB (estimated overhead) |
| **Resident total** | **~95-105 GB** |
| Headroom on 128 GB | ~23-33 GB |

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

## Test Models API

### List available models

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

### Chat Completion Tests

#### Default/general model (stays warm)

`keep_alive: -1` is set by default for this model.

```bash
# Orin profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "prompt": "Give me a one-line summary of Jetson Orin.",
    "stream": false
  }' | jq .

# Thor profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b-q8_0",
    "prompt": "Give me a one-line summary of Jetson Orin.",
    "stream": false
  }' | jq .
```

#### Structured-output model (stays warm, default think=false)

`keep_alive: -1` and `think: false` are set by default for this model.

Warning: raising `num_ctx` beyond the ceiling listed above will exceed the unified-memory budget for a two-warm configuration.

```bash
# Orin profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-coder:30b",
    "prompt": "Return cue IDs as JSON only.",
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
    "stream": false
  }' | jq .

# Thor profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-coder-next:q4_K_M",
    "prompt": "Return cue IDs as JSON only.",
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
      "num_ctx": 262144,
      "num_predict": 256,
      "cache_type_k": "q8_0",
      "cache_type_v": "q8_0",
      "num_keep": 128
    },
    "stream": false
  }' | jq .
```

#### Coding model (cold/evicted)

`keep_alive: 0` is set by default for this model.

```bash
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-coder:32b-instruct",
    "prompt": "Write a Python function to reverse a linked list.",
    "stream": false
  }' | jq .
```

#### Optional verifier model

`keep_alive: 10m` and `think: true` are set by default for this model.

```bash
# Orin profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nemotron-cascade-2:30b",
    "prompt": "Verify whether the answer is internally consistent.",
    "stream": false
  }' | jq .

# Thor profile
curl -sS http://127.0.0.1:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "nemotron-cascade-2:30b-a3b-q4_K_M",
    "prompt": "Verify whether the answer is internally consistent.",
    "stream": false
  }' | jq .
```

## Direct Ollama API Path

LibreChat can call Ollama directly by setting base URL to `http://OLLAMA_HOST_IP:11434`. Replace `OLLAMA_HOST_IP` with the actual IP address of the Jetson node running Ollama.

Per-request keep_alive can be set in payload if your client supports sending it.

## LibreChat Configuration

- Base URL (direct Ollama): `http://OLLAMA_HOST_IP:11434`
- Model IDs per profile:

| Profile | Model IDs | Default Model |
|---------|-----------|---------------|
| Orin | `qwen3-coder:30b`, `qwen3.6:35b-a3b`, `nemotron-cascade-2:30b` (optional), `qwen2.5-coder:32b-instruct` | `qwen3.6:35b-a3b` |
| Thor | `qwen3-coder-next:q4_K_M`, `qwen3.6:35b-a3b-q8_0`, `nemotron-cascade-2:30b-a3b-q4_K_M` (optional) | `qwen3.6:35b-a3b-q8_0` |

## Jetson Runtime Notes

- Jetson AI Lab recommends vLLM + AWQ/NVFP4 for top Qwen3.6 throughput on Orin/Thor.
- This stack intentionally uses Ollama for automatic model residency control (`keep_alive` + `OLLAMA_MAX_LOADED_MODELS=2`).
- If you switch to NVIDIA's vLLM command for Qwen3.6, use a separate endpoint (typically `:8000`) and keep this Ollama stack for two-model hot/cold policy behavior.

## Memory Behavior Summary

### Orin Profile

- `OLLAMA_MAX_LOADED_MODELS=2` keeps `qwen3-coder:30b` and `qwen3.6:35b-a3b` warm together.
- Per-model defaults:
  - `qwen3-coder:30b` -> `keep_alive=-1`, `think=false`
  - `qwen3.6:35b-a3b` -> `keep_alive=-1` (stay loaded)
  - `nemotron-cascade-2:30b` -> `keep_alive=10m`, `think=true`
  - `qwen2.5-coder:32b-instruct` -> `keep_alive=0` (unload after request)
- Global fallback default on Ollama: `OLLAMA_KEEP_ALIVE=10m`.
- Loading `nemotron-cascade-2:30b` while both warm models are resident exceeds the two-warm budget. Ollama will evict one warm model to make room because `OLLAMA_MAX_LOADED_MODELS=2`, so expect a one-time reload penalty on the next call to the evicted model after the verifier runs.
- Leave the verifier at `keep_alive: 10m` so it does not remain resident longer than necessary.

### Thor Profile

- `OLLAMA_MAX_LOADED_MODELS=2` keeps `qwen3-coder-next:q4_K_M` and `qwen3.6:35b-a3b-q8_0` warm together.
- Per-model defaults:
  - `qwen3-coder-next:q4_K_M` -> `keep_alive=-1`, `think=false`
  - `qwen3.6:35b-a3b-q8_0` -> `keep_alive=-1`, `think=true`
- Global fallback default on Ollama: `OLLAMA_KEEP_ALIVE=10m`.

### Verifying Two-Warm Residency

Check the live model table and memory pressure together:

```bash
curl -sS http://127.0.0.1:11434/api/ps | jq .
sudo tegrastats --interval 1000
```

What to look for:

- Before warmup completes, `/api/ps` may return `{"models":[]}`.
- After `ollama-warmup` exits with code 0, `/api/ps` must list both warm models with `expires_at` far in the future (`keep_alive=-1`).
- Orin: RAM usage stabilizing around ~49-56 GB for the documented two-warm plan.
- Thor: RAM usage stabilizing around ~95-105 GB for the documented two-warm plan.
- SWAP staying at `0`, which confirms zram or other swap is not absorbing model pages.

If `/api/ps` is still empty after warmup, check the warmup logs:

```bash
# Orin profile (default)
docker compose logs ollama-warmup

# Thor profile
HARDWARE=thor docker compose logs ollama-warmup
```

## Warmup Status Codes

The warmup container emits status lines for each model during startup:

| Status | Meaning |
|--------|---------|
| `reloading` | Informational line emitted before warmup unloads a resident model whose `/api/ps` `context_length` does not match the requested `num_ctx`. |
| `already-warm` | Model is already resident in `/api/ps` at the requested `context_length`, so warmup skips it. |
| `pulled-warmed` | Model was missing, pull succeeded, warm call succeeded, and `/api/ps` confirms residency at the requested `context_length`. |
| `already-pulled-warmed` | Model was already present in `/api/tags`, warm call succeeded, and `/api/ps` confirms residency at the requested `context_length`. |
| `pull-failed` | Streaming pull never reached `{"status":"success"}` after retries. |
| `post-pull-missing` | Pull reported success but `/api/tags` still did not list the model. |
| `warm-failed` | `/api/generate` returned non-2xx. |
| `not-resident` | Warm call returned 2xx, but post-warm `/api/ps` polling did not confirm residency with a live `expires_at`. |
| `wrong-ctx` | Model became resident, but `/api/ps` still reported a different `context_length` after the post-warm poll. |

### Troubleshooting Warmup Failures

`not-resident` means the warm call itself succeeded but Ollama did not keep the model loaded. The most common causes are:

- `OLLAMA_MAX_LOADED_MODELS` budget is already exhausted by another resident model.
- A previous request with `keep_alive: 0` evicted the model.

`wrong-ctx` means the model is resident but not at the requested `num_ctx`. Warmup now auto-reloads any resident model it finds at the wrong context before warming it again.

If warmup still fails for one model, run:

```bash
# Orin profile (default)
docker compose exec ollama ollama pull qwen3-coder:30b
docker compose run --rm ollama-warmup

# Thor profile
HARDWARE=thor docker compose exec ollama ollama pull qwen3-coder-next:q4_K_M
HARDWARE=thor docker compose run --rm ollama-warmup
```

Intermittent warmup pull failures are usually network or registry-side timeouts, not invalid tags. Validated tags currently in use are:

| Profile | Warmup Models |
|---------|--------------|
| Orin | `qwen3-coder:30b`, `qwen3.6:35b-a3b` |
| Thor | `qwen3-coder-next:q4_K_M`, `qwen3.6:35b-a3b-q8_0` |

## Network and Security Notes

- Exposed ports intentionally bind on all interfaces for LAN use:
  - `${OLLAMA_HOST}:11434` (Ollama API, default `0.0.0.0:11434`)
- Restrict access at host firewall/router ACLs to trusted LAN clients.

> [!NOTE]
> The Optional OpenAI Router was removed from this repository and moved to the [llmsrouter repository](https://github.com/king-dopey/llmsrouter). Example model policies are retained here for reference only.

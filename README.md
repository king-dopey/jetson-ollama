# Jetson AGX Orin + Thor Shared LLM Serving Stack (Ollama + Optional OpenAI Router)

This repository provides a single shared Ollama/router stack for both Jetson AGX Orin 64GB and Jetson AGX Thor 128GB.
Board behavior is selected with `PROFILE=orin|thor` (default: `orin`), without splitting compose architecture.

For the current board-profile runbook and validation gates, use `docs/UnifiedOrinThorProfiles.md` as the canonical operator guide.

## Files

- `docker-compose.yml`: Ollama service plus optional `proxy` profile that launches a bundled router instance for convenience.
- `.env.example`: environment values for ports and model behavior.
- `profiles/orin/models.yaml`: Orin model/residency policy.
- `profiles/thor/models.yaml`: Thor model/residency policy.
- `profiles/orin/librechat-modelspecs.yaml`: Orin LibreChat `Coding`/`Chat` mapping.
- `profiles/thor/librechat-modelspecs.yaml`: Thor LibreChat `Coding`/`Chat` mapping.
- `docs/UnifiedOrinThorProfiles.md`: profile runbook and validation gates.

## Network and Security Notes

- Exposed ports intentionally bind on all interfaces for LAN use:
  - `0.0.0.0:11434` (Ollama API)
  - `0.0.0.0:4000` (OpenAI-compatible router, only when profile `proxy` is enabled)
- Restrict access at host firewall/router ACLs to trusted LAN clients.
- For the standalone router deployment, see `router/README.md`.

## Start Services

```bash
cp .env.example .env

PROFILE=orin docker compose up -d
# Orin default also applies if PROFILE is unset:
docker compose up -d
# Thor:
PROFILE=thor docker compose up -d

# Optional OpenAI-compatible single endpoint for LibreChat:
PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy up -d --build
PROFILE=thor docker compose -f router/docker-compose.yml --profile proxy up -d --build
# Optional verifier pull helper:
PROFILE=orin docker compose --profile verifier up ollama-pull-verifier
# Optional ASR service:
docker compose --profile asr up -d
```

## Integration with OpenAPI-Compatible Router

This Ollama LLM serving node is designed to work with the OpenAPI-compatible router in the `router` subfolder. The router provides a unified `/v1` endpoint for LLM interactions while managing model residency, context length, and other parameters according to a policy configuration.

The router:
- Enforces model_policy for `keep_alive`, `think`, and `num_ctx` settings
- Provides a single unified `/v1` endpoint for clients
- Forwards requests to Ollama with appropriate per-model settings

For more information about the router, please see the [router/README.md](router/README.md) file.

The `proxy` profile in this repository's docker-compose still launches a bundled router instance for convenience; see `router/README.md` for the standalone router docs.


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
| `qwen3-coder-next:q4_K_M` | Alternative coding model with conservative settings. | `0` | `false` | `16384` | Large model that may cause Ollama to evict other loaded models from memory on Orin AGX 64GB. |

## Recommended model roles

This section describes the recommended roles for each model in this configuration, with emphasis on cold-load models that are not kept warm by default.

### Warm resident models (always loaded)
- `qwen3-coder:30b` - Strict-JSON and structured-output workloads for boundary selection and cue-ID extraction. Always resident with `keep_alive=-1`.
- `qwen3.6:35b-a3b` - Narrative summarization workloads. Always resident with `keep_alive=-1`.

### Cold-load models (loaded on-demand)
- `qwen3:4b` - General chat and reasoning with a smaller footprint. Added to chat policy with `think=true`.
- `qwen3-vl:4b` - Vision-language model for multimodal tasks. Added to chat policy with `think=true`.
- `gemma4:12b` - General-purpose reasoning model with good performance. Added to chat policy with `think=true`.
- `devstral-small-2:24b` - Smaller model optimized for specific tasks. Added to chat policy with `think=false`.
- `reader-lm:1.5b` - Optional lightweight model for reading tasks. Added to chat policy with `think=false`.

### Documentation-only models (not added to chat policy)
- `qwen3-embedding:4b` - Embedding model for vector storage and retrieval. Not added to chat policy as it's not a chat model. Can be used directly through Ollama embedding APIs.
- `qwen2.5-coder:3b-base` - Base completion model for editor workflows. Not added to chat policy by default as it's not the preferred default for LibreChat or general chat/tool use.

### Benchmark/manual-only models
- `qwen3-coder:30b-a3b-q8_0` - Benchmark model for manual testing and evaluation. Not recommended as a default enabled model on this box.


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
# Optional verifier:
ollama pull nemotron-cascade-2:30b
# Optional qwen3-coder-next:
ollama pull qwen3-coder-next:q4_K_M

# New cold-load models:
ollama pull qwen3:4b
ollama pull qwen3-vl:4b
ollama pull gemma4:12b
ollama pull devstral-small-2:24b
ollama pull reader-lm:1.5b
ollama pull qwen3-embedding:4b
ollama pull qwen2.5-coder:3b-base
```

The `qwen3-coder-next:q4_K_M` model is large and may cause Ollama to evict other loaded models from memory on Orin AGX 64GB. It is recommended to start with `num_ctx=16384` for optimal memory usage.

## Ollama Version Compatibility

This configuration is compatible with Ollama version 0.24.0 and later. All added models (qwen3:4b, qwen3-vl:4b, gemma4:12b, devstral-small-2:24b, reader-lm:1.5b) have been tested with this version and support the required features including:
- Proper context length handling
- Support for the `keep_alive` parameter
- Full compatibility with the OpenAI-compatible router

## ASR Service

An optional ASR (Automatic Speech Recognition) + word alignment service is available that can be started with the `asr` profile. This service:

- Runs separately from the Ollama model residency system
- Is designed for on-demand transcription with exact word timing
- Uses the `whisper-large-v3-turbo` model by default
- Supports optional accuracy override with `whisper-large-v3`
- Targets GPU-backed inference on Jetson Orin by default (`ASR_EXPECT_DEVICE=cuda`, `ASR_COMPUTE_TYPE=float16`)
- Treats `whisper-large-v3-turbo` / `whisper-large-v3` as the stable public API names and normalizes them internally for provider-specific loading
- Provides word-level timestamps via forced alignment when available
- Is isolated from the two-warm Ollama model plan

### Starting the ASR Service

```bash
# Start the ASR service
docker compose --profile asr up -d

# Stop the ASR service
docker compose --profile asr down
```

### Router Alignment API

When router is deployed, the public alignment route is:
- `POST /v1/audio/align` on router host (`:4000`)

Router behavior:
- Requires `multipart/form-data` uploads (`media_file` plus form fields)
- Rejects path-only/JSON alignment RPCs with `cross_host_alignment_requires_multipart_upload`
- Forwards uploaded media bytes upstream to ASR `/align` via `ASR_BASE_URL`
- Requires `python-multipart` in the router image to parse multipart form bodies

#### Router Alignment Smoke Check

```bash
curl -sS http://127.0.0.1:4000/v1/audio/align \
  -F "media_file=@/path/to/_audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "model_accuracy=whisper-large-v3" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true" | jq .
```

Equivalent minimal multipart request:

```bash
curl -F "media_file=@/path/to/audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true" \
  http://127.0.0.1:4000/v1/audio/align
```

`BASE_URL=http://ask:4000` remains the standard app-to-router configuration. Do not assume
shared filesystem paths across app/router/ASR containers.

#### ASR Healthcheck

```bash
curl -sS http://127.0.0.1:8000/healthz | jq .
```

#### Alignment Troubleshooting

If router logs show:

`The python-multipart library must be installed to use form parsing.`

the router image is missing multipart parser support. Rebuild the router after installing router dependencies (which now include `python-multipart`) and redeploy the router container.

### ASR Service API

The ASR service exposes a `/align` endpoint that accepts audio files and returns:

- Transcript segments with timing information
- Word-level timestamps
- Metadata about the model used and alignment status

#### Example Request

```bash
curl -X POST http://localhost:8000/align \
  -F "media_file=@/path/to/audio.wav" \
  -H "Content-Type: multipart/form-data"
```

#### Example Response

```json
{
  "text": "This is a test transcription. It includes multiple segments.",
  "language": "en",
  "model": "whisper-large-v3-turbo",
  "provider": "faster-whisper",
  "forced_alignment_used": true,
  "degraded": false,
  "degradation_reason": null,
  "segments": [
    {
      "start_ms": 0,
      "end_ms": 1000,
      "text": "This is a test transcription."
    },
    {
      "start_ms": 1000,
      "end_ms": 2000,
      "text": "It includes multiple segments."
    }
  ],
  "words": [
    {
      "text": "This",
      "start_ms": 0,
      "end_ms": 200,
      "confidence": 0.95
    },
    {
      "text": "is",
      "start_ms": 200,
      "end_ms": 400,
      "confidence": 0.92
    }
  ]
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASR_ENABLED` | `1` | Enable the ASR service |
| `ASR_PORT` | `8000` | Port for the ASR service |
| `ASR_MODEL` | `whisper-large-v3-turbo` | Default transcription model |
| `ASR_MODEL_ACCURACY` | `whisper-large-v3` | Optional accuracy override model |
| `ASR_COMPUTE_TYPE` | `float16` | Compute type for model inference |
| `ASR_DEVICE` | `auto` | Runtime device request (`auto`, `cuda`, `cpu`) |
| `ASR_EXPECT_DEVICE` | `cuda` | Expected backend for startup validation (`cuda` fails fast if unavailable) |
| `ASR_ALLOW_DEGRADED_BACKEND` | `0` | Permit startup on CPU when expected CUDA backend is unavailable |
| `ASR_ALLOW_COMPUTE_FALLBACK` | `0` | Permit compute fallback (e.g., `float16` -> `float32` on CPU) |
| `ASR_FORCE_ALIGNMENT` | `1` | Force word-level alignment |
| `ASR_KEEP_WARM` | `0` | Keep ASR service warm |
| `ASR_MODEL_CACHE` | `/app/models` | Canonical ASR model cache root |
| `HF_HOME` | `/app/models/hf` | Hugging Face home under the ASR cache root |
| `HUGGINGFACE_HUB_CACHE` | `/app/models/hf/hub` | huggingface_hub cache location |
| `TRANSFORMERS_CACHE` | `/app/models/hf/transformers` | Transformers cache location |
| `XDG_CACHE_HOME` | `/app/models/xdg` | XDG cache root used by dependent tooling |
| `ASR_LOG_LEVEL` | `info` | Log level for the service |

Build-time ASR image args (used by `docker compose --profile asr build`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ASR_TORCH_INDEX_URL` | `https://pypi.jetson-ai-lab.io/jp6/cu126` | Jetson wheel index for torch/torchaudio (JetPack 6 + CUDA 12.6) |
| `ASR_TORCH_VERSION` | `2.8.0` | Torch version pinned for WhisperX compatibility |
| `ASR_TORCHAUDIO_VERSION` | `2.8.0` | Torchaudio version pinned for WhisperX compatibility |

Public model contract:
- Callers should keep using `whisper-large-v3-turbo` (default) and `whisper-large-v3` (accuracy override) in `/align` requests and env configuration.
- The ASR service may normalize these to provider-native names (for example `large-v3-turbo` / `large-v3`) internally before loading WhisperX models.

### Notes

- The ASR service is completely separate from the Ollama two-warm model plan
- It can run on the same host but uses its own resources and model loading
- The service will automatically pull required models when started
- `asr-service` now runs with NVIDIA runtime settings in compose (`runtime: nvidia`, `NVIDIA_VISIBLE_DEVICES=all`, `NVIDIA_DRIVER_CAPABILITIES=compute,utility`)
- Compose mounts a named volume (`asr-model-cache`) at `/app/models` so cache survives restarts without host bind-mount ownership drift
- ASR startup validates all cache directories and fails fast with `asr_model_cache_not_writable` if the runtime user cannot write them
- ASR startup also validates backend/compute compatibility and reports resolved runtime diagnostics in `/healthz` (`resolved_device`, `resolved_compute_type`, CUDA visibility, torch/ctranslate2 details)
- Word-level timing is only available when forced alignment is enabled
- ASR now uses `whisperx==3.8.6` with its current alignment flow (`load_model` + `load_align_model` + `align`) and includes torchaudio backend compatibility shims when required by upstream dependencies.
- Upstream compatibility constraints from WhisperX currently require `torch~=2.8.0`, `torchaudio~=2.8.0`, and `huggingface-hub<1.0.0`. The ASR container installs torch/torchaudio from the Jetson CUDA wheel index (`ASR_TORCH_INDEX_URL`).
- JetPack 6 / CUDA 12.6 torch 2.8.0 wheels from `pypi.jetson-ai-lab.io/jp6/cu126` are currently `cp310`; the ASR image uses Python 3.10 to match wheel ABI and avoid incompatible fallback installs.
- ASR dependency caps in `asr/requirements.txt` are ABI-driven: `numpy==2.2.6` (NumPy 2.3+ requires Python >=3.11) and `ctranslate2==4.6.2` (latest wheel available for Python 3.10 on Linux aarch64). These remain compatible with `whisperx==3.8.6` and `faster-whisper==1.2.1`.
- Build-time `import torch` is intentionally avoided in this image: CUDA-linked Jetson torch may fail to import during `docker build` with missing `libcudart`/`libcublas` because NVIDIA runtime libraries are mounted when the container runs on Orin, not guaranteed during image build.

### ASR Cache Troubleshooting

If ASR logs show:

```text
Permission denied: '/app/models/...'
```

check the ASR cache mount and writability first:

```bash
docker compose --profile asr exec asr-service sh -lc 'id && ls -ld /app/models && touch /app/models/.rw_probe && rm -f /app/models/.rw_probe'
docker volume inspect model64_asr-model-cache
```

`asr-service` runs as a non-root `app` user. The cache directory must be writable by that user. The default compose setup uses a named Docker volume for `/app/models`, which avoids host bind-mount ownership mismatches.

### ASR Backend Troubleshooting (`float16` failure)

If you see:

`Requested float16 compute type, but the target device or backend do not support efficient float16 computation.`

the runtime resolved to CPU while `float16` was requested. Check:

```bash
docker compose --profile asr exec asr-service python - <<'PY'
import json, urllib.request
print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz'))['runtime'], indent=2))
PY
```

and then verify GPU visibility and wheel selection:

```bash
docker compose --profile asr exec asr-service python - <<'PY'
import torch, ctranslate2
print('torch=', torch.__version__)
print('torch_cuda=', torch.version.cuda)
print('cuda_available=', torch.cuda.is_available())
print('ctranslate2=', ctranslate2.__version__)
PY
```

Build ASR with the Jetson wheel index explicitly:

```bash
docker compose --profile asr build \
  --no-cache \
  --build-arg ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126 \
  --build-arg ASR_TORCH_VERSION=2.8.0 \
  --build-arg ASR_TORCHAUDIO_VERSION=2.8.0 \
  asr
```

`pypi.jetson-ai-lab.dev` is no longer a valid host; use `pypi.jetson-ai-lab.io`.

Post-build runtime smoke test (run on Jetson Orin with NVIDIA runtime):

```bash
docker compose --profile asr run --rm asr python -c "import torch; print('torch=', torch.__version__); print('torch_cuda=', torch.version.cuda); print('cuda_available=', torch.cuda.is_available())"
```

Expected on a healthy Orin deployment:
- `resolved_device` is `cuda`
- `resolved_compute_type` is `float16`
- `torch` version is not `+cpu`

If CUDA is intentionally unavailable, set both:
- `ASR_ALLOW_DEGRADED_BACKEND=1`
- `ASR_ALLOW_COMPUTE_FALLBACK=1`

This enables explicit degraded CPU startup and will report `degradation_reason` in health diagnostics.

## Dual-Target Deployment (Orin + Thor)

This repository supports both Jetson AGX Orin 64GB and Jetson AGX Thor 128GB with profile-driven configuration. The same compose architecture is used for both boards, with behavior selected via the `PROFILE` environment variable.

### Profile Selection

| Profile | Target Board | Default Context | Model Policy |
|---------|--------------|-----------------|--------------|
| `orin` (default) | Jetson AGX Orin 64GB | `16384` | `profiles/orin/models.yaml` |
| `thor` | Jetson AGX Thor 128GB | `262144` | `profiles/thor/models.yaml` |

### Starting Services by Profile

```bash
# Orin (default)
PROFILE=orin docker compose up -d
# Orin default also applies if PROFILE is unset:
docker compose up -d

# Thor
PROFILE=thor docker compose up -d
```

### ASR Service with Dual-Target

The ASR service uses different Python versions per profile to match the Jetson wheel ABI:

| Profile | Python Base | Torch Index | Dockerfile |
|---------|-------------|-------------|------------|
| `orin` | Python 3.10 (cp310 wheels) | `jp6/cu126` | `asr/Dockerfile` |
| `thor` | Python 3.12 (cp312 wheels) | `jp7/cu126` | `asr/Dockerfile.thor` |

The ASR Dockerfile is selected automatically via the `ASR_DOCKERFILE` environment variable, which is set per-profile in `profiles/*/stack.env`.

To build and run ASR with a specific profile:

```bash
# Orin ASR (default)
PROFILE=orin docker compose --profile asr up -d

# Thor ASR
PROFILE=thor docker compose --profile asr up -d
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROFILE` | `orin` | Board profile (`orin` or `thor`) |
| `ASR_DOCKERFILE` | `Dockerfile` | ASR Dockerfile to use (`Dockerfile` or `Dockerfile.thor`) |
| `ASR_TORCH_INDEX_URL` | `jp6/cu126` | Jetson wheel index (Orin: `jp6`, Thor: `jp7`) |

### Validation

Run the validation scripts to verify both profiles:

```bash
# Validate Orin configuration
./scripts/validation/validate-shared-stack.sh orin

# Validate Thor configuration
./scripts/validation/validate-thor-asr.sh
```

## On-Demand Model Auto-Pull

Configured models can now be auto-pulled on first request. When a configured model such as `qwen3-coder-next:q4_K_M` is requested and is not already present in Ollama, the router will automatically pull it before forwarding the chat request.

This feature:
- Only auto-pulls models that are explicitly allowed by the repo configuration (defined in `router/model_policy.yml`)
- Treats the router's model policy as the allow-list
- Does NOT auto-pull arbitrary model names supplied by clients if they are not in policy
- The first request for a missing allowed model may block until pull completes
- Large models may cause Ollama to evict other models from memory; that is acceptable and should just be documented
- Existing warmup behavior remains unchanged for startup models

To enable auto-pull, set the following environment variables in your `.env` file:
```
AUTO_PULL_MISSING_MODELS=true
MODEL_PULL_TIMEOUT_SEC=7200
MODEL_PULL_MAX_RETRIES=2
MODEL_PULL_BACKOFF_SEC=5
```

Startup warmup behavior is still separate and unchanged. Manual pull is now optional for configured models.

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

When using the router (port 4000), the router intercepts requests and applies the following per-model policies before forwarding to Ollama.

Using optional router endpoint (`/v1`):

```bash
curl -sS http://127.0.0.1:4000/v1/models | jq .
```

Directly on Ollama tags endpoint:

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

## Chat Completion Tests

When using the router (port 4000), the router intercepts requests and applies the following per-model policies before forwarding to Ollama.

### Think Control Policy (Proxy -> Ollama)

LibreChat cannot directly set Ollama's `think` flag for each turn in this setup, so the proxy injects `think` in the Ollama `/api/chat` payload.

Policy defaults:

- Per-model defaults come from `router/model_policy.yml`.
- `qwen3-coder:30b` defaults to `think=false`.
- `qwen3.6:35b-a3b`, `nemotron-cascade-2:30b`, and `qwen3-coder:30b` default to `think=true`.
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
    "model": "qwen3-coder:30b",
    "messages": [{"role": "user", "content": "Write a Python function to reverse a linked list."}]
  }' | jq .
```

### Override keep_alive per request (explicit caller control)

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-coder:30b",
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

- Base URL (recommended with policy routing): `http://ORIN_IP:4000/v1` (requires `proxy` profile)
- Model IDs:
  - `qwen3-coder:30b`
  - `qwen3.6:35b-a3b`
  - `nemotron-cascade-2:30b` (optional if pulled)
  - `qwen3-coder:30b`
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
  - `qwen3-coder:30b` -> `keep_alive=0` (unload after request)
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

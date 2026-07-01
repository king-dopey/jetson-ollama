# ASR Service - Automatic Speech Recognition with Word Alignment

Speech-to-text service with word-level timing extraction, designed for Jetson Orin/Thor platforms.

## Overview

The ASR service provides:

- On-demand transcription with exact word timing via forced alignment
- GPU-backed inference on Jetson Orin (`cuda` device, `float16` compute)
- Word-level timestamps via WhisperX alignment pipeline
- Dual-provider support: `faster-whisper` (throughput) and `whisperx` (alignment)
- Automatic backend degradation when CUDA is unavailable (configurable)
- Isolated from the Ollama two-warm model plan

## Quick Start

```bash
# Start the ASR service
docker compose --profile asr up -d

# Check health
curl -sS http://127.0.0.1:8000/healthz | jq .

# Stop the service
docker compose --profile asr down
```

## API Endpoints

### `POST /align` - Transcribe with Word Alignment

Accepts audio files and returns transcript segments with word-level timestamps.

**Multipart form upload (recommended):**

```bash
curl -X POST http://localhost:8000/align \
  -F "media_file=@audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true"
```

**JSON payload (requires shared filesystem):**

```bash
curl -X POST http://localhost:8000/align \
  -H "Content-Type: application/json" \
  -d '{"audio_path": "/path/to/audio.wav", "return_word_timestamps": true}'
```

**Response:**

```json
{
  "text": "This is a test transcription.",
  "language": "en",
  "model": "whisper-large-v3-turbo",
  "provider": "faster-whisper",
  "forced_alignment_used": true,
  "degraded": false,
  "segments": [
    {"start_ms": 0, "end_ms": 1000, "text": "This is a test transcription."}
  ],
  "words": [
    {"text": "This", "start_ms": 0, "end_ms": 200, "confidence": 0.95}
  ]
}
```

### `GET /healthz` - Health Check

Returns service status and runtime diagnostics:

```bash
curl -sS http://127.0.0.1:8000/healthz | jq .
```

**Response:**

```json
{
  "status": "ok",
  "enabled": true,
  "configured_providers": ["faster-whisper", "whisperx"],
  "loaded_providers": ["faster-whisper"],
  "lazy_load_alignment": true,
  "runtime": {
    "requested_device": "cuda",
    "requested_compute_type": "float16",
    "resolved_device": "cuda",
    "resolved_compute_type": "float16",
    "cuda_available": true,
    "degraded": false,
    "diagnostics": { ... }
  },
  "cuda_compatible": true
}
```

### `GET /models` - Available Models

```bash
curl -sS http://localhost:8000/models | jq .
```

## Providers

| Provider | Use Case | Alignment |
|----------|----------|-----------|
| `faster-whisper` | Default, throughput-optimized | None (segments only) |
| `whisperx` | Forced alignment with word timestamps | Yes |

The provider is selected automatically: when `prefer_forced_alignment=true` and `return_word_timestamps=true`, the service uses `whisperx`. Otherwise, it uses the default `faster-whisper`.

## Environment Variables

### Runtime Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ASR_ENABLED` | `1` | Enable the ASR service |
| `ASR_PORT` | `8000` | Service listen port |
| `ASR_DEFAULT_PROVIDER` | `faster-whisper` | Default provider |
| `ASR_MODEL` | `whisper-large-v3-turbo` | Default transcription model |
| `ASR_MODEL_ACCURACY` | `whisper-large-v3` | Accuracy override model |
| `ASR_COMPUTE_TYPE` | `float16` | Compute type for inference |
| `ASR_DEVICE` | `auto` | Runtime device (`auto`, `cuda`, `cpu`) |
| `ASR_EXPECT_DEVICE` | `cuda` | Expected backend; startup fails if unavailable |
| `ASR_ALLOW_DEGRADED_BACKEND` | `0` | Permit CPU startup when CUDA unavailable |
| `ASR_ALLOW_COMPUTE_FALLBACK` | `0` | Permit compute fallback (`float16` -> `float32`) |
| `ASR_CUDA_COMPAT_MODE` | `fallback` | CUDA compatibility mode: `strict`, `fallback`, or `disabled` |
| `ASR_FORCE_ALIGNMENT` | `1` | Force word-level alignment |
| `ASR_KEEP_WARM` | `0` | Keep ASR models loaded |
| `ASR_LOG_LEVEL` | `info` | Log level |

### Cache Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `ASR_MODEL_CACHE` | `/app/models` | Canonical model cache root |
| `HF_HOME` | `/app/models/hf` | Hugging Face home |
| `HUGGINGFACE_HUB_CACHE` | `/app/models/hf/hub` | huggingface_hub cache |
| `TRANSFORMERS_CACHE` | `/app/models/hf/transformers` | Transformers cache |
| `XDG_CACHE_HOME` | `/app/models/xdg` | XDG cache root |

### Build-Time Variables (Dockerfile args)

| Variable | Default | Description |
|----------|---------|-------------|
| `L4T_JETPACK_TAG` | `r39.2.0` | L4T base image tag (JetPack 7.2) |
| `ASR_TORCH_INDEX_URL` | `https://download.pytorch.org/whl/cu132` | Torch wheel index (cu132 native to JetPack 7.2) |
| `ASR_TORCH_VERSION` | `2.12.1+cu132` | Pinned torch version (native to JetPack 7.2) |
| `ASR_TORCHAUDIO_VERSION` | `2.12.1+cu132` | Pinned torchaudio version |
| `CTranslate2_VERSION` | `4.8.0` | CTranslate2 version for source build |
| `CUDA_ARCHITECTURE` | `90` | CUDA architecture (90=Thor/SM90, 87=Orin/SM87) |
| `BUILD_JOBS` | `4` | Parallel build jobs for CTranslate2 compilation |

## Docker Compose Integration

The ASR service runs as a named profile in the main compose stack:

```bash
# Build with specific torch versions
docker compose --profile asr build \
  --build-arg ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126 \
  --build-arg ASR_TORCH_VERSION=2.8.0 \
  --build-arg ASR_TORCHAUDIO_VERSION=2.8.0

# Start with profile
docker compose --profile asr up -d
```

### Named Volume

The service uses a named Docker volume (`asr-model-cache`) mounted at `/app/models` to persist model cache across restarts without host bind-mount ownership issues.

### NVIDIA Runtime

The container runs with NVIDIA runtime settings:
- `runtime: nvidia`
- `NVIDIA_VISIBLE_DEVICES=all`
- `NVIDIA_DRIVER_CAPABILITIES=compute,utility`

### Multi-Stage Docker Build

The ASR service uses a multi-stage Docker build to compile CTranslate2 from source with CUDA support on Jetson:

1. **Builder Stage**: Uses locally-built `l4t-jetpack:r39.0` image (built from dusty-nv/jetson-containers repo), clones and compiles CTranslate2 v4.8.0 with profile-specific CUDA architecture
2. **Runtime Stage**: Uses same L4T base image, installs Python dependencies (PyTorch cu132 wheels), copies compiled CTranslate2 from builder

Key build configurations:
- `WITH_CUDNN=OFF`: Disabled to avoid cuDNN 9 header mismatches on JetPack 7.2
- CUDA paths: `/usr/local/cuda` (L4T image provides standard CUDA toolkit layout)
- PyTorch wheels: `cu132` tagged (native to JetPack 7.2, compiled with CUDA 12.9.1)
- Profile-specific architecture: Thor uses SM 90 (Blackwell), Orin uses SM 87 (Ampere)

**CRITICAL NOTE**: As of June 2026, NVIDIA has NOT published r39.x tags for JetPack 7.2/Thor on NGC. The official catalog only contains r36.x.x and r35.x.x tags. Community-built `dustynv/l4t-jetpack:r39.x` images also do not exist yet.

**Solution**: Build L4T container from source using DustyNV's jetson-containers repository:
```bash
git clone https://github.com/dusty-nv/jetson-containers.git
cd jetson-containers
./scripts/build.sh l4t-jetpack
```

See [`asr/Dockerfile`](../asr/Dockerfile) for complete build configuration.

## Dual-Target Deployment (Orin + Thor)

Different Python base images are used per profile to match Jetson wheel ABIs:

| Profile | Python Base | Torch Index | Dockerfile |
|---------|-------------|-------------|------------|
| `orin` | 3.10 (cp310) | `jp6/cu126` | `Dockerfile` |
| `thor` | 3.12 (cp312) | `jp7/cu126` | `Dockerfile.thor` |

The Dockerfile is selected via `ASR_DOCKERFILE`, set per-profile in `profiles/*/stack.env`.

```bash
# Orin ASR
PROFILE=orin docker compose --profile asr up -d

# Thor ASR
PROFILE=thor docker compose --profile asr up -d
```

## Router Integration

When the OpenAI-compatible router is deployed, the public alignment route is:

```
POST /v1/audio/align  (router host, typically port 4000)
```

**Router smoke check:**

```bash
curl -sS http://127.0.0.1:4000/v1/audio/align \
  -F "media_file=@audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true" | jq .
```

The router requires `python-multipart` to parse multipart form bodies.

## Dependency Stack

| Package | Version | Notes |
|---------|---------|-------|
| `whisperx` | `3.8.7rc1` | Speech recognition with alignment |
| `faster-whisper` | `1.2.1` | Fast Whisper via CTranslate2 |
| `ctranslate2` | `4.8.0` | Built from source with CUDA support |
| `pyannote-audio` | `4.0.4` | Speaker diarization (optional) |
| `numpy` | `2.3.0` | NumPy 2.3+ requires Python >=3.11 |
| `soundfile` | `0.14.0` | Audio file I/O |
| `fastapi` | `0.137.2` | Web framework |
| `uvicorn` | `0.49.0` | ASGI server |

> **Note:** `ctranslate2` is built from source with CUDA support in the Dockerfile. The PyPI wheel for aarch64 is CPU-only. See [`asr/Dockerfile`](../asr/Dockerfile) for build instructions.

## Troubleshooting

### Cache Permission Errors

```text
Permission denied: '/app/models/...'
```

Check cache mount and writability:

```bash
docker compose --profile asr exec asr-service sh -lc 'id && ls -ld /app/models'
docker volume inspect model64_asr-model-cache
```

The service runs as non-root user `app`. The named volume approach avoids host ownership drift.

### Float16 Compute Failure

```text
Requested float16 compute type, but the target device or backend do not support efficient float16 computation.
```

This indicates CPU resolution when `float16` was requested. Verify GPU visibility:

```bash
docker compose --profile asr exec asr-service python - <<'PY'
import torch, ctranslate2
print('torch=', torch.__version__)
print('cuda_available=', torch.cuda.is_available())
print('ctranslate2=', ctranslate2.__version__)
PY
```

### CUDA Unavailable

If the expected CUDA backend is unavailable:

1. Verify NVIDIA runtime is configured in compose
2. Set `ASR_ALLOW_DEGRADED_BACKEND=1` and `ASR_ALLOW_COMPUTE_FALLBACK=1` for CPU fallback
3. Check health diagnostics: `curl -sS http://127.0.0.1:8000/healthz | jq .runtime`

### Build ASR with JetPack 7.2

The ASR service is configured for JetPack 7.2 (CUDA 13.2) by default. The build uses L4T base images that include the CUDA toolkit pre-installed.

The ASR image build is split into two layers:
- `base-image/Dockerfile`: dependency/runtime base (CUDA userspace, torch/torchaudio, CTranslate2 artifacts, Python deps)
- `Dockerfile`: app layer only (copies ASR app code and entrypoint)

Workflow is intentionally split into two scripts:
- Base only: `./base-image/build-l4t-base.sh [profile] [cuda_arch]`
- App only: `./build-asr-app.sh [profile] [cuda_arch]`

Build the base image first, then build the app image:

```bash
# Build base image consumed by asr/Dockerfile
./base-image/build-l4t-base.sh thor 90

# Build app image using the prebuilt base
./build-asr-app.sh thor 90
```

```bash
# Default build (JetPack 7.2, cu132 native)
./build-asr-app.sh

# Build with profile-specific architecture (override via build args)
docker compose --profile asr build \
  --build-arg CUDA_ARCHITECTURE=90  # Thor (SM 90/Blackwell)
  --build-arg BUILD_JOBS=4          # Parallel build jobs

# Build with explicit prebuilt base tag override
ASR_APP_BASE_IMAGE=asr-runtime-base:cuda13-2-sm90 ./build-asr-app.sh thor 90
```

For JetPack 6.x (Orin), use the Orin profile which sets appropriate values:
```bash
PROFILE=orin docker compose --profile asr build
```

## Architecture

```
asr/
├── app.py                    # FastAPI application with /align, /healthz, /models
├── cache_config.py           # Model cache path resolution and validation
├── runtime_config.py         # Backend/compute resolution logic
├── entrypoint.sh             # Container entrypoint (waits for Ollama)
├── pre_build_verify.sh       # Pre-build verification script (Jetson aarch64 only)
├── Dockerfile                # App layer image (expects prebuilt ASR base image)
├── build-asr-app.sh          # App-only image builder
├── build-l4t-base.sh         # Compatibility wrapper to base-image/build-l4t-base.sh
├── base-image/
│   ├── Dockerfile            # Dependency/runtime base image
│   └── build-l4t-base.sh     # Base-only image builder
├── providers/
│   ├── base.py               # Abstract ASRProvider interface
│   ├── faster_whisper_provider.py  # FasterWhisper implementation
│   ├── whisperx_provider.py        # WhisperX implementation
│   └── model_names.py        # Model name normalization
└── tests/                    # Unit tests
```

## Related Documentation

- [Main README](../README.md) - Full stack documentation including Ollama, router, and profiles
- [ASR Solver](../tools/asr-solver/README.md) - Dependency compatibility discovery tool

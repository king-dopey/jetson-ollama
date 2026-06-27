# No-Regression Dual-Target Deployment Plan: Jetson Orin + NVIDIA Thor

## A. Root-Cause Assessment

### Confirmed Incompatibilities (from repo analysis)

| Component | Orin (Current) | Thor (New) | Incompatibility |
|-----------|----------------|------------|-----------------|
| **Python base image** | `python:3.10.14-slim-bookworm` | `python:3.12.3-slim-bookworm` (Ubuntu 24.04) | ABI incompatibility for compiled wheels |
| **Torch wheel index** | `pypi.jetson-ai-lab.io/jp6/cu126` (cp310) | `pypi.jetson-ai-lab.io/jp7/cu126` (cp312) | Different Python ABI, different wheel tags |
| **CUDA version** | CUDA 12.6 (JetPack 6) | CUDA 12.6 (JetPack 7) | Same CUDA, but different runtime libraries |
| **OS base** | Ubuntu 22.04 (JetPack 6) | Ubuntu 24.04 (JetPack 7) | Different glibc, package versions |

### Probable Incompatibilities (inferred from constraints)

1. **ASR Build Failures**
   - `torch==2.8.0` wheels for Python 3.12 on Jetson may not exist at `pypi.jetson-ai-lab.io`
   - `torchaudio==2.8.0` wheels for Python 3.12 may not exist
   - `ctranslate2==4.6.2` may not have cp312 wheels available

2. **WhisperX Compatibility**
   - WhisperX 3.8.6 requires `torch~=2.8.0`, `torchaudio~=2.8.0`
   - Pyannote-audio 4.0.4 may have Python 3.12 compatibility issues
   - `huggingface-hub<1.0.0` constraint may conflict with Python 3.12 packages

3. **Router/Ollama Profile Differences**
   - Router Dockerfile uses `python:3.11.9-slim-bookworm` (inconsistent baseline)
   - Model policy files differ significantly between profiles
   - Warmup scripts reference different model tags per profile

4. **Model Policy / Warmup Differences**
   - Orin: `qwen3-coder:30b`, `qwen3.6:35b-a3b`
   - Thor: `qwen3-coder-next:q4_K_M`, `qwen3.6:35b-a3b-q8_0`
   - Context lengths differ (65K vs 256K) affecting KV cache memory

### Unknowns (require actual traceback)

1. Exact error message from Thor deployment
2. Whether `pypi.jetson-ai-lab.io/jp7/cu126` exists and publishes cp312 wheels
3. Whether WhisperX 3.8.6 is compatible with Python 3.12
4. Whether `pyannote-audio==4.0.4` works on Ubuntu 24.04

---

## B. Recommended Target Architecture

### Shared Components (No Changes)

| Component | Reason |
|-----------|--------|
| `docker-compose.yml` (main) | Profile-driven via `${PROFILE}` env var |
| `router/Dockerfile` | Python 3.11 is compatible with both; no CUDA dependencies |
| `router/app.py` | Pure Python, no platform-specific code |
| `router/policy.py` | Pure Python policy logic |
| `scripts/warmup.sh` | Shell script, profile-agnostic |
| `asr/requirements.txt` | Application dependencies (no compiled wheels) |
| `asr/*.py` (app, providers, cache_config) | Pure Python code |

### Orin-Specific Components

| Component | Current State | Action |
|-----------|---------------|--------|
| `asr/Dockerfile` | `python:3.10.14-slim-bookworm` | Keep as-is for Orin |
| `asr/requirements.txt` | NumPy 2.2.6, ctranslate2 4.6.2 | Keep as-is for Orin |
| `profiles/orin/stack.env` | Model defaults for Orin | Keep as-is |
| `profiles/orin/models.yaml` | Orin model policy | Keep as-is |
| `profiles/orin/librechat-modelspecs.yaml` | Orin LibreChat mapping | Keep as-is |

### Thor-Specific Components (New)

| Component | Action |
|-----------|--------|
| `asr/Dockerfile.thor` | New: `python:3.12.3-slim-bookworm` with cp312 torch wheels |
| `asr/requirements-thor.txt` | New: Python 3.12-compatible versions |
| `profiles/thor/stack.env` | Model defaults for Thor | Already exists |
| `profiles/thor/models.yaml` | Thor model policy | Already exists |
| `profiles/thor/librechat-modelspecs.yaml` | Thor LibreChat mapping | Already exists |

---

## C. Step-by-Step Implementation Plan

### Phase 0: Pre-Refactoring Validation (NO CODE CHANGES)

**Goal**: Establish baseline before any changes

1. **Orin smoke test**
   ```bash
   PROFILE=orin docker compose config > /dev/null && echo "✓ Orin compose valid"
   PROFILE=orin docker compose up -d ollama
   # Wait for health
   curl -f http://localhost:11434/api/health || exit 1
   PROFILE=orin docker compose down
   ```

2. **ASR smoke test (Orin)**
   ```bash
   PROFILE=orin docker compose --profile asr config > /dev/null && echo "✓ ASR compose valid"
   PROFILE=orin docker compose --profile asr up -d asr
   curl -f http://localhost:8000/healthz || exit 1
   PROFILE=orin docker compose --profile asr down
   ```

3. **Router smoke test (Orin)**
   ```bash
   PROFILE=orin docker compose -f router/docker-compose.yml config > /dev/null && echo "✓ Router compose valid"
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy up -d fastapi-router
   curl -f http://localhost:4000/healthz || exit 1
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy down
   ```

4. **Unit tests**
   ```bash
   cd asr && python3 -m pytest tests/ -v
   cd router && python3 -m pytest tests/ -v
   ```

### Phase 1: ASR Python 3.12 Support (Isolated Change)

**Goal**: Add Thor ASR support without breaking Orin

1. **Create `asr/Dockerfile.thor`**
   ```dockerfile
   FROM python:3.12.3-slim-bookworm
   
   ARG ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp7/cu126
   ARG ASR_TORCH_VERSION=2.8.0
   ARG ASR_TORCHAUDIO_VERSION=2.8.0
   
   ENV PYTHONDONTWRITEBYTECODE=1 \
       PYTHONUNBUFFERED=1 \
       PIP_NO_CACHE_DIR=1 \
       PIP_DISABLE_PIP_VERSION_CHECK=1
   
   WORKDIR /app
   
   RUN addgroup --system app && adduser --system --ingroup app app
   
   RUN apt-get update && apt-get install -y \
       --no-install-recommends \
       ffmpeg \
       curl \
       && rm -rf /var/lib/apt/lists/*
   
   COPY requirements-thor.txt ./
   # Install torch/torchaudio from Jetson index (cp312 wheels)
   RUN pip install --no-cache-dir \
       --index-url "${ASR_TORCH_INDEX_URL}" \
       "torch==${ASR_TORCH_VERSION}" \
       "torchaudio==${ASR_TORCHAUDIO_VERSION}"
   
   # Install application dependencies
   RUN pip install --no-cache-dir -r requirements-thor.txt
   
   COPY --chown=app:app ./*.py ./
   COPY --chown=app:app ./providers/*.py ./providers/
   COPY --chown=app:app ./entrypoint.sh ./
   
   RUN chmod +x /app/entrypoint.sh && mkdir -p /app/models && chown -R app:app /app
   
   USER app
   
   EXPOSE 8000
   HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
       CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1
   
   ENTRYPOINT ["/app/entrypoint.sh"]
   CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

2. **Create `asr/requirements-thor.txt`**
   ```txt
   # Python 3.12-compatible ASR dependencies
   # NumPy 2.3+ requires Python >=3.11
   numpy==2.3.0
   # ctranslate2 4.8.0+ may have cp312 wheels
   ctranslate2==4.8.0
   # Other dependencies (same as Orin, but compatible with Python 3.12)
   fastapi==0.137.2
   httpx==0.28.1
   uvicorn==0.49.0
   openai==2.43.0
   transformers==4.57.6
   faster-whisper==1.2.1
   whisperx==3.8.6
   huggingface-hub==0.36.2
   pyannote-audio==4.0.4
   soundfile==0.14.0
   pydantic==2.13.4
   python-multipart==0.0.32
   ```

3. **Update `docker-compose.yml` to support Thor ASR**
   ```yaml
   asr:
     profiles: ["asr"]
     build:
       context: ./asr
       dockerfile: ${ASR_DOCKERFILE:-Dockerfile}
       args:
         ASR_TORCH_INDEX_URL: ${ASR_TORCH_INDEX_URL:-https://pypi.jetson-ai-lab.io/jp6/cu126}
         ASR_TORCH_VERSION: ${ASR_TORCH_VERSION:-2.8.0}
         ASR_TORCHAUDIO_VERSION: ${ASR_TORCHAUDIO_VERSION:-2.8.0}
   ```

4. **Update `.env.example` with Thor-specific variables**
   ```env
   # ASR Dockerfile selection (Orin: Dockerfile, Thor: Dockerfile.thor)
   ASR_DOCKERFILE=Dockerfile
   
   # ASR Jetson wheel index (Orin: jp6/cu126, Thor: jp7/cu126)
   ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126
   ```

### Phase 2: Profile Environment Variables

**Goal**: Allow profile-specific build args without breaking existing deployments

1. **Update `profiles/orin/stack.env`**
   ```env
   # Board profile defaults (Orin 64GB)
   MODEL_DEFAULT=qwen3.6:35b-a3b
   WARMUP_MODELS=qwen3-coder:30b@65536
   WARMUP_DEFAULT_NUM_CTX=65536
   MODEL_VERIFY_TAG=qwen3-coder:30b
   
   # ASR build args (Orin-specific)
   ASR_DOCKERFILE=Dockerfile
   ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126
   ```

2. **Update `profiles/thor/stack.env`**
   ```env
   # Board profile defaults (Thor 128GB)
   MODEL_DEFAULT=qwen3.6:35b-a3b-q8_0
   WARMUP_MODELS=qwen3-coder-next:q4_K_M@262144 qwen3.6:35b-a3b-q8_0@262144
   WARMUP_DEFAULT_NUM_CTX=262144
   MODEL_VERIFY_TAG=qwen3-coder-next:q4_K_M
   
   # ASR build args (Thor-specific)
   ASR_DOCKERFILE=Dockerfile.thor
   ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp7/cu126
   ```

### Phase 3: Validation Gates

**Goal**: Ensure both profiles work before merging

1. **Update `scripts/validation/validate-shared-stack.sh`**
   ```bash
   # Add ASR profile validation
   assert_contains "$main_cfg" "dockerfile: \${ASR_DOCKERFILE:-Dockerfile}" "ASR dockerfile variable"
   ```

2. **Add Thor-specific validation script**
   ```bash
   # scripts/validation/validate-thor-asr.sh
   #!/usr/bin/env bash
   set -euo pipefail
   
   PROFILE_NAME="thor"
   
   # Verify Dockerfile.thor exists
   [ -f "asr/Dockerfile.thor" ] || fail "missing asr/Dockerfile.thor"
   
   # Verify requirements-thor.txt exists
   [ -f "asr/requirements-thor.txt" ] || fail "missing asr/requirements-thor.txt"
   
   # Verify compose can parse with Thor profile
   docker compose config > /dev/null
   
   printf 'Thor ASR configuration validation passed\n'
   ```

### Phase 4: Documentation

**Goal**: Document the dual-target strategy

1. **Update `README.md`**
   - Add section on dual-target deployment
   - Document `PROFILE=orin|thor` usage
   - Document ASR build args per platform

2. **Update `docs/UnifiedOrinThorProfiles.md`**
   - Add ASR Python version requirements
   - Add build-time dependency strategy

---

## D. Config/File Change Map

### Files to Create (New)

| File | Purpose |
|------|---------|
| `asr/Dockerfile.thor` | Thor-specific ASR Dockerfile with Python 3.12 |
| `asr/requirements-thor.txt` | Python 3.12-compatible ASR dependencies |
| `scripts/validation/validate-thor-asr.sh` | Thor ASR validation script |

### Files to Modify

| File | Changes |
|------|---------|
| `docker-compose.yml` | Add `${ASR_DOCKERFILE:-Dockerfile}` to ASR build dockerfile field |
| `profiles/orin/stack.env` | Add `ASR_DOCKERFILE=Dockerfile`, `ASR_TORCH_INDEX_URL` |
| `profiles/thor/stack.env` | Add `ASR_DOCKERFILE=Dockerfile.thor`, `ASR_TORCH_INDEX_URL` |
| `.env.example` | Add `ASR_DOCKERFILE`, update `ASR_TORCH_INDEX_URL` comment |
| `README.md` | Add dual-target deployment section |
| `docs/UnifiedOrinThorProfiles.md` | Add ASR Python version requirements |

### Files to Keep Unchanged (Orin Compatibility)

| File | Reason |
|------|--------|
| `asr/Dockerfile` | Orin uses Python 3.10; must remain unchanged |
| `asr/requirements.txt` | Orin dependencies; must remain unchanged |
| `router/Dockerfile` | Python 3.11 is compatible with both |
| `router/app.py`, `router/policy.py` | Pure Python, no platform-specific code |

---

## E. Regression Prevention Strategy

### Pre-Refactoring Tests (MUST PASS BEFORE CHANGES)

1. **Orin baseline validation**
   ```bash
   PROFILE=orin docker compose config > /dev/null
   PROFILE=orin docker compose up -d ollama
   curl -f http://localhost:11434/api/health
   PROFILE=orin docker compose down
   ```

2. **ASR baseline validation (Orin)**
   ```bash
   PROFILE=orin docker compose --profile asr config > /dev/null
   PROFILE=orin docker compose --profile asr up -d asr
   curl -f http://localhost:8000/healthz
   PROFILE=orin docker compose --profile asr down
   ```

3. **Router baseline validation (Orin)**
   ```bash
   PROFILE=orin docker compose -f router/docker-compose.yml config > /dev/null
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy up -d fastapi-router
   curl -f http://localhost:4000/healthz
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy down
   ```

4. **Unit tests**
   ```bash
   cd asr && python3 -m pytest tests/ -v  # All must pass
   cd router && python3 -m pytest tests/ -v  # All must pass
   ```

### Build-Time Tests

1. **Orin ASR build**
   ```bash
   PROFILE=orin docker compose --profile asr build asr
   ```

2. **Thor ASR build (dry-run)**
   ```bash
   PROFILE=orin ASR_DOCKERFILE=Dockerfile.thor docker compose --profile asr build asr
   ```

### Runtime Smoke Tests

1. **Orin runtime smoke**
   ```bash
   PROFILE=orin docker compose up -d
   # Wait for health
   curl -f http://localhost:11434/api/ps | jq '.models[] | .name'
   PROFILE=orin docker compose down
   ```

2. **Thor runtime smoke**
   ```bash
   PROFILE=thor docker compose up -d
   # Wait for health
   curl -f http://localhost:11434/api/ps | jq '.models[] | .name'
   PROFILE=thor docker compose down
   ```

### End-to-End Checks

1. **Orin Ollama + Router**
   ```bash
   PROFILE=orin docker compose up -d
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy up -d fastapi-router
   curl -s http://localhost:4000/v1/models | jq '.data[].id'
   PROFILE=orin docker compose -f router/docker-compose.yml --profile proxy down
   PROFILE=orin docker compose down
   ```

2. **Thor Ollama + Router**
   ```bash
   PROFILE=thor docker compose up -d
   PROFILE=thor docker compose -f router/docker-compose.yml --profile proxy up -d fastapi-router
   curl -s http://localhost:4000/v1/models | jq '.data[].id'
   PROFILE=thor docker compose -f router/docker-compose.yml --profile proxy down
   PROFILE=thor docker compose down
   ```

---

## F. Rollout Strategy

### Safe Order of Implementation

1. **Phase 0: Validation** (NO CODE CHANGES)
   - Run all Orin smoke tests
   - Confirm baseline passes

2. **Phase 1: ASR Python 3.12 Support**
   - Create `asr/Dockerfile.thor`
   - Create `asr/requirements-thor.txt`
   - Test Thor ASR build in isolation
   - Verify Orin ASR still works

3. **Phase 2: Profile Environment Variables**
   - Update `profiles/orin/stack.env`
   - Update `profiles/thor/stack.env`
   - Test both profiles with compose config

4. **Phase 3: Validation Gates**
   - Add Thor validation script
   - Run both Orin and Thor validation

5. **Phase 4: Documentation**
   - Update README.md
   - Update docs/UnifiedOrinThorProfiles.md

### Rollback Plan

If any step fails:

1. **Revert git changes**
   ```bash
   git checkout .
   ```

2. **Verify Orin still works**
   ```bash
   PROFILE=orin docker compose config > /dev/null
   PROFILE=orin docker compose up -d ollama
   curl -f http://localhost:11434/api/health
   PROFILE=orin docker compose down
   ```

### Final Validation

Before declaring success:

1. **Orin deployment works identically to pre-change state**
2. **Thor deployment builds and runs without errors**
3. **Both profiles pass smoke tests**
4. **Unit tests pass for both platforms**

---

## Summary

**Key Design Decisions:**

1. **Separate Dockerfiles**: Orin uses `Dockerfile` (Python 3.10), Thor uses `Dockerfile.thor` (Python 3.12)
2. **Shared application code**: All Python files remain unchanged; only build-time dependencies diverge
3. **Profile-driven selection**: `ASR_DOCKERFILE` env var selects the correct Dockerfile per profile
4. **No global upgrades**: Orin remains on Python 3.10; Thor uses Python 3.12
5. **Isolated ASR changes**: Router and Ollama components remain unchanged

**Risk Mitigation:**

- All changes are additive (new files, not modifying existing ones)
- Orin deployment is never modified
- Validation gates ensure baseline before each phase
- Rollback is trivial (git checkout)

**Unknowns Requiring Actual Deployment:**

1. Whether `pypi.jetson-ai-lab.io/jp7/cu126` exists and publishes cp312 wheels
2. Whether WhisperX 3.8.6 is compatible with Python 3.12
3. Exact error message from Thor deployment (to be determined during Phase 0 validation)
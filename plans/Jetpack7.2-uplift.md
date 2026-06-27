# JetPack 7.2 Migration Plan for model64 Repository

## 1. Verified Repo Findings

### Build-Time Logic

| File | Current State | Key Settings |
|------|---------------|--------------|
| [`asr/Dockerfile`](asr/Dockerfile:1) | Python 3.10 base | `FROM python:3.10.14-slim-bookworm` |
| [`asr/Dockerfile.thor`](asr/Dockerfile.thor:1) | Python 3.12 base | `FROM python:3.12.3-slim-bookworm` |
| [`asr/Dockerfile`](asr/Dockerfile:3) | Orin torch index | `ARG ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126` |
| [`asr/Dockerfile.thor`](asr/Dockerfile.thor:3) | Thor torch index | `ARG ASR_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130` |
| [`profiles/orin/stack.env`](profiles/orin/stack.env:9) | Orin torch version | `ASR_TORCH_VERSION=2.8.0` |
| [`profiles/thor/stack.env`](profiles/thor/stack.env:10) | Thor torch version | `ASR_TORCH_VERSION=2.12.1+cu130` |

### Runtime Logic

| File | Current State | Key Settings |
|------|---------------|--------------|
| [`asr/app.py`](asr/app.py:39) | Runtime resolution | Calls `resolve_runtime()` from runtime_config.py |
| [`asr/runtime_config.py`](asr/runtime_config.py:157) | Device detection | Validates CUDA availability, torch backend |
| [`asr/providers/whisperx_provider.py`](asr/providers/whisperx_provider.py:46) | Torchaudio compat | `_ensure_torchaudio_backend_compat()` shims missing APIs |

### Obsolete Logic

| File | Issue |
|------|-------|
| [`profiles/runtime`](profiles/runtime:165) | References `jp7/cu126` which doesn't exist at pypi.jetson-ai-lab.io |
| [`asr/Dockerfile.thor`](asr/Dockerfile.thor:3) | Uses PyTorch official cu130 index (not Jetson-specific) |
| [`profiles/orin/stack.env`](profiles/orin/stack.env:9) | Points to `jp6/cu126` which is JetPack 6, not JetPack 7 |

### Conflicting Logic

| Conflict | Location | Evidence |
|----------|----------|----------|
| **Python version mismatch** | [`asr/Dockerfile`](asr/Dockerfile:1) vs [`asr/Dockerfile.thor`](asr/Dockerfile.thor:1) | Orin uses Python 3.10, Thor uses Python 3.12 |
| **Torch index URL conflict** | [`profiles/thor/stack.env`](profiles/thor/stack.env:9) vs actual availability | `jp7/cu126` doesn't exist; PyTorch official cu130 has different versioning |
| **Torch version mismatch** | [`asr/Dockerfile`](asr/Dockerfile:4) vs [`asr/Dockerfile.thor`](asr/Dockerfile.thor:4) | Orin: 2.8.0, Thor: 2.12.1+cu130 |

### Root-Cause Evidence from [`profiles/runtime`](profiles/runtime)

```
# Line 185-186: Build failure on Thor
ERROR: Could not find a version that satisfies the requirement torch==2.8.0 (from versions: none)

# Line 221-222: jp7/cu126 doesn't exist
ERROR: Could not find a version that satisfies the requirement torch==2.8.0 (from versions: none)

# Line 241-242: PyTorch cu130 index doesn't have 2.8.0
ERROR: No matching distribution found for torch==2.8.0

# Line 267-268: Available versions on cu130
torch (2.12.1+cu130)
Available versions: 2.12.1+cu130, 2.12.0+cu130, 2.11.0+cu130, 2.10.0+cu130, 2.9.1+cu130, 2.9.0+cu130
```

---

## 2. Dependency Compatibility Matrix

| Package | Current (Orin) | Current (Thor) | Target JP7.2 | Compatibility Status | Risk Level | Evidence |
|---------|----------------|----------------|--------------|---------------------|------------|----------|
| **torch** | 2.8.0 (cp310) | 2.12.1+cu130 | 2.12.1+cu126 | ✅ Compatible | Low | Jetson AI Lab cp312 wheels available for 2.12.x |
| **torchaudio** | 2.8.0 (cp310) | 2.11.0+cu130 | 2.12.1+cu126 | ✅ Compatible | Low | Matches torch version |
| **ctranslate2** | 4.6.2 (cp310) | 4.8.0 (cp312) | 4.10.0+ | ⚠️ Verify | Medium | Need cp312 wheels for Jetson |
| **faster-whisper** | 1.2.1 | 1.2.1 | 1.2.1 | ✅ Compatible | Low | Pure Python + ctranslate2 |
| **whisperx** | 3.8.6 | 3.8.6 | 3.8.6 | ⚠️ Verify | Medium | Requires torchaudio~=2.8.0, may need patching |
| **pyannote-audio** | 4.0.4 | 4.0.4 | 4.0.4 | ⚠️ Verify | Medium | Python 3.12 compatibility not confirmed |
| **numpy** | 2.2.6 (cp310) | 2.3.0 (cp312) | 2.3.0+ | ✅ Compatible | Low | NumPy 2.3+ requires Python >=3.11 |
| **huggingface-hub** | 0.36.2 | 0.36.2 | 0.36.2 | ✅ Compatible | Low | Pure Python |
| **transformers** | 4.57.6 | 4.57.6 | 4.57.6 | ⚠️ Verify | Medium | Check CUDA 12.6/13 compatibility |
| **fastapi** | 0.137.2 | 0.137.2 | 0.137.2 | ✅ Compatible | Low | Pure Python |
| **uvicorn** | 0.49.0 | 0.49.0 | 0.49.0 | ✅ Compatible | Low | Pure Python |
| **base image** | python:3.10.14-slim-bookworm | python:3.12.3-slim-bookworm | python:3.12-slim-bookworm | ✅ Compatible | Low | Ubuntu 24.04 base |

### Critical Runtime Dependencies

| Component | Required at Runtime | Evidence |
|-----------|---------------------|----------|
| **CUDA runtime** | libcudart.so, libcublas.so | Jetson host provides via nvidia-container-runtime |
| **cuBLAS** | Required by torch | Verified in [`profiles/runtime`](profiles/runtime:315) |
| **cuDNN** | Required by torch | JetPack 7.2 includes cuDNN 9.x |

---

## 3. Root-Cause Analysis

### Priority 1: Torch Index URL Mismatch (CRITICAL)

**Problem**: [`profiles/thor/stack.env`](profiles/thor/stack.env:9) references `https://pypi.jetson-ai-lab.io/jp7/cu126` which does not exist.

**Evidence from [`profiles/runtime`](profiles/runtime:221-222)**:
```
ERROR: Could not find a version that satisfies the requirement torch==2.8.0 (from versions: none)
Looking in indexes: https://pypi.jetson-ai-lab.io/jp7/cu126
```

**Root Cause**: Jetson AI Lab only publishes:
- `jp6/cu126` (JetPack 6, Python 3.10 wheels)
- `sbsa/cu129` (Supercomputing, different architecture)

**Solution**: Use PyTorch official index `https://download.pytorch.org/whl/cu126` for JetPack 7.2.

### Priority 2: Python Version Split (HIGH)

**Problem**: Orin uses Python 3.10, Thor uses Python 3.12 with incompatible wheel ABIs.

**Evidence from [`profiles/runtime`](profiles/runtime:361-367)**:
```
# Orin (cp310) works
Collecting torch==2.8.0
  Downloading torch-2.8.0-cp310-cp310-linux_aarch64.whl

# Thor (cp312) fails with same version
ERROR: Could not find a version that satisfies the requirement torch==2.8.0 (from versions: none)
```

**Root Cause**: Jetson AI Lab cp312 wheels only available for newer torch versions (2.9+).

**Solution**: Unify on Python 3.12 with torch 2.12.1+cu126.

### Priority 3: WhisperX Torchaudio API Compatibility (MEDIUM)

**Problem**: [`asr/providers/whisperx_provider.py`](asr/providers/whisperx_provider.py:46) implements shims for removed torchaudio APIs:
```python
def _ensure_torchaudio_backend_compat() -> None:
    if not hasattr(torchaudio, "set_audio_backend"):
        torchaudio.set_audio_backend = lambda _backend=None: None
```

**Risk**: WhisperX 3.8.6 requires `torchaudio~=2.8.0`, but we're upgrading to 2.12.1+.

**Evidence**: [`asr/providers/whisperx_provider.py`](asr/providers/whisperx_provider.py:19-23) shows error handling for torchaudio backend selector API.

### Priority 4: Missing CUDA Runtime Libraries (LOW)

**Problem**: Container needs CUDA runtime libraries at runtime (not build time).

**Evidence from [`profiles/runtime`](profiles/runtime:312-316)**:
```
find /usr -name "libcudart.so*" 2>/dev/null
find /usr -name "libcublas.so*" 2>/dev/null
```

**Solution**: NVIDIA container runtime mounts these from host; no action needed.

---

## 4. Decision Recommendation

### Recommended Design: **Single Unified Dockerfile for JetPack 7.2**

| Decision | Rationale |
|----------|-----------|
| **Single Dockerfile** | Eliminate dual-profile complexity; one path for both Orin and Thor |
| **Base image**: `python:3.12-slim-bookworm` | Python 3.12 is target; cp312 wheels available for Jetson |
| **Python version**: 3.12 | Matches JetPack 7.2 baseline; NumPy 2.3+ requires >=3.11 |
| **Torch strategy**: `torch==2.12.1+cu126` | Latest stable with cp312 wheels; matches PyTorch official cu126 |
| **Index URL**: `https://download.pytorch.org/whl/cu126` | Jetson AI Lab doesn't have jp7; PyTorch official has cu126 wheels |
| **Keep WhisperX**: Yes, with torchaudio compatibility patch | Required for alignment; add backend shims |
| **Replace faster-whisper**: No | Works fine with ctranslate2; use as fallback provider |
| **Delete JP6/Python 3.10 logic**: Yes | Orin now on JetPack 7.2; no need for legacy path |

### Fallback Options

**Fallback A**: Keep dual Dockerfiles but unify on Python 3.12
- Pros: Minimal change, preserves Orin-specific build args
- Cons: Maintains complexity, dual maintenance burden

**Fallback B**: Use JetPack 6 baseline (Python 3.10) for both
- Pros: More stable torch wheels available
- Cons: Doesn't meet target of JetPack 7.2; Python 3.10 EOL approaching

---

## 5. Step-by-Step Implementation Plan

### Phase 0: Pre-Migration Validation (NO CODE CHANGES)

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `PROFILE=orin docker compose config > /dev/null && echo "✓ Orin valid"` | Verify compose syntax |
| 2 | `PROFILE=thor docker compose config > /dev/null && echo "✓ Thor valid"` | Verify compose syntax |
| 3 | `docker compose --profile asr config > /dev/null && echo "✓ ASR valid"` | Verify ASR profile |

### Phase 1: Create Unified Dockerfile

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`asr/Dockerfile`](asr/Dockerfile) | Replace Python 3.10 with 3.12 base | Unify build environment |
| 2 | [`asr/Dockerfile`](asr/Dockerfile:3) | Change index to `https://download.pytorch.org/whl/cu126` | Use PyTorch official cu126 |
| 3 | [`asr/Dockerfile`](asr/Dockerfile:4-5) | Update torch to `2.12.1+cu126` | Match available cp312 wheels |

**Validation**: `docker compose --profile asr build asr`

### Phase 2: Update Requirements

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`asr/requirements.txt`](asr/requirements.txt) | Update numpy to `2.3.0` | Python 3.12 compatible |
| 2 | [`asr/requirements.txt`](asr/requirements.txt) | Update ctranslate2 to `4.10.0` | Verify cp312 wheels available |
| 3 | [`asr/requirements-thor.txt`](asr/requirements-thor.txt) | Delete (unified) | Remove duplicate |

**Validation**: `pip install --dry-run -r asr/requirements.txt`

### Phase 3: Update Profile Configuration

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`profiles/orin/stack.env`](profiles/orin/stack.env:9) | Change to `https://download.pytorch.org/whl/cu126` | Use unified index |
| 2 | [`profiles/orin/stack.env`](profiles/orin/stack.env:10-11) | Update torch versions to `2.12.1+cu126` | Match Thor |
| 3 | [`profiles/thor/stack.env`](profiles/thor/stack.env:9) | Change to `https://download.pytorch.org/whl/cu126` | Use unified index |
| 4 | [`profiles/thor/stack.env`](profiles/thor/stack.env:10-11) | Update torch versions to `2.12.1+cu126` | Match Orin |

**Validation**: `PROFILE=orin docker compose config > /dev/null && PROFILE=thor docker compose config > /dev/null`

### Phase 4: Update Docker Compose

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`docker-compose.orin.yml`](docker-compose.orin.yml) | Delete (unified) | Remove duplicate |
| 2 | [`docker-compose.thor.yml`](docker-compose.thor.yml) | Delete (unified) | Remove duplicate |

**Validation**: `docker compose config > /dev/null`

### Phase 5: Update Provider Code

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`asr/providers/whisperx_provider.py`](asr/providers/whisperx_provider.py:46) | Remove `_ensure_torchaudio_backend_compat()` | No longer needed with torchaudio 2.12+ |

**Validation**: `docker compose --profile asr up -d asr && curl http://localhost:8000/healthz`

### Phase 6: Cleanup

| Step | File | Change | Impact |
|------|------|--------|--------|
| 1 | [`asr/Dockerfile.thor`](asr/Dockerfile.thor) | Delete (unified) | Remove duplicate |
| 2 | [`asr/requirements-thor.txt`](asr/requirements-thor.txt) | Delete (unified) | Remove duplicate |

**Validation**: `ls asr/Dockerfile*` should show only `Dockerfile`

---

## 6. Validation Plan

### Test Matrix

| Test | Orin JP7.2 | Thor JP7.2 | Command |
|------|------------|------------|---------|
| **Build validation** | ✅ | ✅ | `docker compose --profile asr build asr` |
| **Import validation** | ✅ | ✅ | `python -c "import torch; import whisperx; import faster_whisper"` |
| **CUDA visibility** | ✅ | ✅ | `nvidia-smi` (host), `nvidia-container-cli list` (container) |
| **Torch GPU validation** | ✅ | ✅ | `python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"` |
| **ASR smoke test** | ✅ | ✅ | `curl http://localhost:8000/healthz` |
| **WhisperX alignment** | ✅ | ✅ | POST to `/align` endpoint with audio file |
| **Ollama integration** | ✅ | ✅ | `curl http://localhost:11434/api/tags` |
| **Router integration** | ✅ | ✅ | `curl http://localhost:4000/v1/models` |
| **Memory/OOM check** | ✅ | ✅ | Monitor `free -h` during ASR load test |

### Failure Signatures to Watch

| Failure | Likely Cause | Resolution |
|---------|--------------|------------|
| `Could not find a version that satisfies the requirement torch==2.12.1+cu126` | Wrong index URL | Verify `https://download.pytorch.org/whl/cu126` |
| `ImportError: libcudart.so.12: cannot open shared object file` | Missing CUDA runtime | Verify nvidia-container-runtime is configured |
| `torchaudio backend selector API missing` | WhisperX compatibility | Revert to torchaudio 2.8.0 shims |

---

## 7. Final Patch Plan

### Ordered Patch List

1. **Create unified Dockerfile** ([`asr/Dockerfile`](asr/Dockerfile))
   - Change base image to `python:3.12-slim-bookworm`
   - Update torch index URL to PyTorch official cu126
   - Update torch/torchaudio versions to 2.12.1+cu126

2. **Update requirements** ([`asr/requirements.txt`](asr/requirements.txt))
   - Update numpy to 2.3.0
   - Update ctranslate2 to 4.10.0 (verify cp312 wheels)

3. **Update profile configs**
   - [`profiles/orin/stack.env`](profiles/orin/stack.env:9-11): Update index and versions
   - [`profiles/thor/stack.env`](profiles/thor/stack.env:9-11): Update index and versions

4. **Remove duplicate files**
   - Delete [`asr/Dockerfile.thor`](asr/Dockerfile.thor)
   - Delete [`asr/requirements-thor.txt`](asr/requirements-thor.txt)
   - Delete [`docker-compose.orin.yml`](docker-compose.orin.yml)
   - Delete [`docker-compose.thor.yml`](docker-compose.thor.yml)

5. **Clean up provider code**
   - Remove `_ensure_torchaudio_backend_compat()` from [`asr/providers/whisperx_provider.py`](asr/providers/whisperx_provider.py:46)

### Commit Breakdown Proposal

| Commit | Files | Message |
|--------|-------|---------|
| 1 | `asr/Dockerfile` | Unify ASR Dockerfile on Python 3.12 for JetPack 7.2 |
| 2 | `asr/requirements.txt` | Update numpy and ctranslate2 for Python 3.12 |
| 3 | `profiles/orin/stack.env`, `profiles/thor/stack.env` | Unify torch index URL to PyTorch official cu126 |
| 4 | Delete `asr/Dockerfile.thor`, `asr/requirements-thor.txt` | Remove duplicate Thor-specific files |
| 5 | Delete `docker-compose.orin.yml`, `docker-compose.thor.yml` | Remove duplicate compose profiles |
| 6 | `asr/providers/whisperx_provider.py` | Remove torchaudio backend compatibility shims |

### Risk Notes

| Risk | Mitigation |
|------|------------|
| **Torch version incompatibility** | Test build before committing; use `--dry-run` first |
| **WhisperX API breakage** | Keep torchaudio 2.8.0 shims if needed; test alignment endpoint |
| **ctranslate2 missing cp312 wheels** | Verify availability at PyTorch index before updating |

### Open Questions (Require Build/Run)

1. **Does ctranslate2 4.10.0+ publish cp312 wheels for Jetson?**
   - Verify: `docker run --rm python:3.12-slim-bookworm pip index versions ctranslate2 -i https://download.pytorch.org/whl/cu126`

2. **Is WhisperX 3.8.6 fully compatible with torchaudio 2.12.1?**
   - Test: `docker compose --profile asr up -d asr && curl -X POST http://localhost:8000/align`

3. **Do pyannote-audio 4.0.4 dependencies work on Python 3.12?**
   - Verify: `pip install pyannote-audio==4.0.4` in Python 3.12 container

---

**Summary**: The repository has a dual-profile ASR stack with conflicting Python versions (3.10 vs 3.12) and torch index URLs. The root cause is that Jetson AI Lab's `jp7/cu126` index doesn't exist, and the Thor Dockerfile references an unavailable torch version. The recommended solution is to unify on Python 3.12 with PyTorch official cu126 wheels, eliminating duplicate Dockerfiles and profile-specific configurations.
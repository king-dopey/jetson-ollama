# ASR Solver - Dependency Compatibility Discovery System

A deterministic solver that finds the newest viable dependency stack for ASR on Jetson.

## Overview

This tool discovers, ranks, probes, and selects compatible versions of:

- `ctranslate2`
- `faster-whisper`
- `torch`
- `torchaudio`
- `whisperx`

## Features

1. **Discovery**: Automatically fetches version metadata from PyPI and PyTorch
2. **Solving**: Constructs candidate stacks with explicit scoring and ranking
3. **Probing**: Runtime validation of top candidates on Jetson hardware
4. **Selection**: Picks the best viable stack with full transparency
5. **Tech Debt**: Automatically generates debt tracking for non-latest selections

## Usage

### Basic Run (Full Pipeline)

```bash
bash tools/asr-solver/run.sh
```

### Phase-Specific Execution

```bash
# Only discover available versions
bash tools/asr-solver/run.sh --phase discover

# Only solve (requires discovery artifacts)
bash tools/asr-solver/run.sh --phase solve

# Only probe top candidates (requires solver artifacts)
bash tools/asr-solver/run.sh --phase probe

# Only select winner (requires probe results)
bash tools/asr-solver/run.sh --phase select

# Only generate report (requires all prior artifacts)
bash tools/asr-solver/run.sh --phase report
```

### Additional Flags

```bash
# Probe more candidates (default: 3)
bash tools/asr-solver/run.sh --top 5

# Ignore cached discovery data
bash tools/asr-solver/run.sh --no-cache
```

## Configuration

Edit `tools/asr-solver/config.env` to customize:

- Target Python version
- CUDA families to consider (in priority order)
- Number of top candidates to probe
- Docker images for each CUDA family

## Output Artifacts

All outputs are written to `tools/asr-solver/artifacts/<timestamp>/`:

| File | Description |
|------|-------------|
| `catalog.json` | All discovered versions and metadata |
| `candidate-stacks.json` | Ranked candidate stacks with scores |
| `probe-results.json` | Runtime probe results for top candidates |
| `selected-stack.json` | Final winner with selection rationale |
| `selected-stack.env` | Environment variables for the winner |
| `report.md` | Human-readable summary report |
| `tech-debt.md` | Debt tracking for non-latest selections |
| `tech-debt.json` | Machine-readable debt data |
| `logs/` | Raw probe execution logs |
| `raw/` | Raw discovery data (PyPI JSON, pip index output) |

## Scoring Formula

Candidates are scored using this exact formula:

```
final_score = cuda_score + freshness_score + wheel_score - penalties + probe_score
```

Where:

- **CUDA Score**: cu132=300000, cu130=200000, older=0
- **Freshness Score**: Sum of rank-based points for each package (latest=1000, decreasing)
- **Wheel Score**: +5000 if all packages have wheels, +1000 per verified wheel
- **Penalties**: -20000 source builds, -5000 unknown deps, -10000 overrides, -50000 older CUDA
- **Probe Score**: +100000 full pass, +60000 core pass, 0 fail

## Target Policy

The solver follows this exact preference order:

1. **CUDA 13.2** (cu132) - highest priority
2. **CUDA 13.0** (cu130) - secondary priority
3. **Latest package versions** - newest viable versions preferred
4. **Wheel-backed installs** - wheels preferred over source builds
5. **Exact torch/torchaudio match** - versions must match exactly
6. **No dependency overrides** - prefer clean dependency resolution
7. **No source builds** - pure wheel installs preferred
8. **Older CUDA only as fallback** - cu128 and older only if 13.x fails

## Error Codes

| Code | Description |
|------|-------------|
| `config_error` | Configuration validation failed |
| `discovery_error` | Failed to discover package versions |
| `solver_error` | Failed to construct or rank candidates |
| `venv_setup_error` | Failed to create solver virtual environment |
| `pip_install_error` | Failed to install packages during probe |
| `dependency_conflict` | Dependency constraints cannot be satisfied |
| `import_error` | Package import failed during probe |
| `missing_shared_library` | Required shared library not found |
| `cuda_runtime_missing` | CUDA runtime not available in container |
| `gpu_unavailable` | GPU not accessible or CUDA not working |
| `inference_error` | Inference test failed |
| `no_viable_candidate` | No candidate passed core probe |
| `unknown_error` | Unexpected error occurred |

## Integration with ASR Service

The generated `selected-stack.env` file contains the exact versions to use:

```bash
source tools/asr-solver/artifacts/<timestamp>/selected-stack.env
```

This provides environment variables for the final ASR implementation:

- `ASR_CUDA_FAMILY`
- `ASR_TORCH_VERSION`
- `ASR_TORCHAUDIO_VERSION`
- `ASR_CTRANSLATE2_VERSION`
- `ASR_FASTER_WHISPER_VERSION`
- `ASR_WHISPERX_VERSION`

## Requirements

- Python 3.12+
- Docker (for runtime probing)
- Network access to PyPI and PyTorch
- Jetson device for final validation

# ASR Solver - Dependency Compatibility Discovery System

A deterministic solver that finds the newest viable dependency stack for ASR on Jetson devices.

## Overview

This tool discovers, ranks, probes, and selects compatible versions of:

- `ctranslate2`
- `faster-whisper`
- `torch`
- `torchaudio`
- `whisperx`

It is designed to work with NVIDIA Jetson devices (linux_aarch64) running CUDA 12.8, 13.0, or 13.2, and targets Python 3.12 environments.

## Features

1. **Discovery**: Automatically fetches version metadata from PyPI and PyTorch wheel indexes
2. **Solving**: Constructs candidate stacks with explicit scoring and ranking based on CUDA family, package freshness, and wheel availability
3. **Probing**: Runtime validation of top candidates in Docker containers with full stack testing (import verification, smoke tests)
4. **Selection**: Picks the best viable stack with full transparency and rejection rationale
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

- Target Python version (default: 3.12)
- CUDA families to consider (in priority order): cu132, cu130, cu128
- Number of top candidates to probe (default: 3)
- Docker images for each CUDA family

## Output Artifacts

All outputs are written to `tools/asr-solver/artifacts/<timestamp>/`:

| File | Description |
|------|-------------|
| `catalog.json` | All discovered versions and metadata |
| `candidate-stacks.json` | Ranked candidate stacks with scores and breakdowns |
| `probe-results.json` | Runtime probe results (pass/fail status for each candidate) |
| `selected-stack.json` | Final winner with selection rationale and stack details |
| `selected-stack.env` | Environment variables for the winner (sourceable) |
| `report.md` | Human-readable summary report with tables |
| `tech-debt.md` | Debt tracking markdown for non-latest selections |
| `tech-debt.json` | Machine-readable debt data |
| `logs/` | Raw probe execution logs (core-rank*.log, full-rank*.log) |
| `raw/` | Raw discovery data (PyPI JSON, pip index output, version lists) |

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

## Probe Phases

The probe phase consists of two stages:

### Core Probe
- Installs torch, torchaudio, ctranslate2, faster-whisper
- Verifies Python imports for each package
- Tests CUDA runtime availability (libcudart)
- Generates synthetic WAV file and runs transcription smoke test
- Exits with status "pass" if all checks succeed

### Full Probe
- Installs whisperx on top of core stack
- Verifies whisperx import and initialization
- Validates complete ASR pipeline compatibility
- Exits with status "pass" if full stack works

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

## Troubleshooting

### Docker Image Not Found Errors

If you see errors like `[ERROR] Docker image asr-probe-core- not found`, ensure:
- The CUDA family is correctly extracted from candidate-stacks.json (nested under `candidate` key)
- Docker images are built before running probes (the pipeline handles this automatically)

### Probe Failing with "Core probe complete" but Status Fail

The probe phase checks for "Core probe complete" and "Full probe complete" markers in log files. If these markers are missing:
- Check the core-rank*.log and full-rank*.log files for error messages
- Ensure numpy and scipy are installed in probe Docker images (required for WAV generation)

### Package Installation Timeout

If pip install commands timeout during probing:
- The subprocess timeout is set to 600 seconds (10 minutes) by default
- Large package installations (torch, torchaudio) on Jetson devices may take several minutes
- Ensure sufficient disk space and network bandwidth

### Whisperx Import Failing

If whisperx import fails during full probe:
- Verify whisperx is installed via pip show
- Check that torch and torchaudio versions are compatible with the whisperx version
- The probe handles missing `__version__` attribute gracefully (uses getattr())

### No Viable Candidate Selected

If the selection phase reports "no_viable_candidate":
- Check probe-results.json for candidate pass/fail status
- Review core-rank*.log and full-rank*.log files for specific failure reasons
- Ensure the Docker solver environment has access to PyPI and PyTorch indexes

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

## Architecture

```
tools/asr-solver/
├── run.sh                    # Main entry point (orchestrates all phases)
├── config.env                # Configuration file
├── lib/                      # Shell script libraries
│   ├── common.sh             # Logging and utility functions
│   ├── discover.sh           # Discovery phase logic
│   ├── solve.sh              # Solve/ranking phase logic
│   ├── probe.sh              # Probe phase logic (Docker image build, execution)
│   ├── select.sh             # Selection phase logic
│   ├── report.sh             # Report generation logic
│   └── debt.sh               # Tech debt generation logic
├── python/                   # Python modules
│   ├── discover.py           # PyPI and PyTorch version discovery
│   ├── solve.py              # Candidate construction, scoring, and selection
│   ├── summarize.py          # Report generation
│   └── metadata_utils.py     # Version parsing utilities
├── docker/                   # Dockerfiles
│   ├── Dockerfile.core-probe # Core probe container (torch, ctranslate2, faster-whisper)
│   └── Dockerfile.full-probe # Full probe container (adds whisperx)
├── container-scripts/        # Scripts executed inside probe containers
│   ├── core_probe.py         # Core probe logic (install, import test, smoke test)
│   ├── full_probe.py         # Full probe logic (whisperx validation)
│   ├── install_core.sh       # Core package installation script
│   └── entrypoint.sh         # Container entrypoint
├── artifacts/                # Output directory (timestamped subdirectories)
└── README.md                 # This file
```

## Requirements

- Python 3.12+
- Docker (for runtime probing)
- Network access to PyPI and PyTorch wheel indexes
- Jetson device for final validation

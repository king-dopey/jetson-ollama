#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Install Core Stack Script
# =============================================================================

set -euo pipefail

export PATH="/opt/venv/bin:$PATH"

# Install core stack packages
python -m pip install \
    --extra-index-url "https://download.pytorch.org/whl/cu132" \
    torch torchaudio ctranslate2 faster-whisper \
    --quiet

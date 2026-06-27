#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Selection Phase
# =============================================================================
# Selects the winning candidate based on probe results.
# =============================================================================
# This script is sourced by run.sh which sets:
#   ASR_SOLVER_DIR, ARTIFACTS_DIR, VENV_DIR
# =============================================================================

set -euo pipefail

# Script location (for reference)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# Source common utilities
# shellcheck source=common.sh
source "${ASR_SOLVER_DIR}/lib/common.sh"

# Use paths from run.sh environment
VENV_DIR="${ASR_SOLVER_DIR}/.solver-venv"

log_info "Starting selection phase..."
log_info "Artifacts directory: $ARTIFACTS_DIR"

# =============================================================================
# Main Selection Pipeline
# =============================================================================

run_selection() {
    log_info "Selecting winning candidate..."
    
    local candidates_file="${ARTIFACTS_DIR}/candidate-stacks.json"
    local probe_results_file="${ARTIFACTS_DIR}/probe-results.json"
    local selected_file="${ARTIFACTS_DIR}/selected-stack.json"
    local selected_env="${ARTIFACTS_DIR}/selected-stack.env"
    
    # Get the relative path from ASR_SOLVER_DIR (full path inside container)
    local artifacts_relative="${ARTIFACTS_DIR#$ASR_SOLVER_DIR/}"
    
    if [[ ! -f "$candidates_file" ]]; then
        error_exit "Candidate stacks not found. Run solve first."
    fi
    
    if [[ ! -f "$probe_results_file" ]]; then
        error_exit "Probe results not found. Run probe first."
    fi
    
    # Run selection algorithm using Docker (use relative paths inside container)
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 /solver/python/solve.py \
            --catalog "/solver/${artifacts_relative}/catalog.json" \
            --select-winner \
            --candidates "/solver/${artifacts_relative}/candidate-stacks.json" \
            --probe-results "/solver/${artifacts_relative}/probe-results.json" \
            --output "/solver/${artifacts_relative}/selected-stack.json"
    
    if [[ -f "$selected_file" ]]; then
        log_info "Selected stack saved to $selected_file"
        
        # Generate selected-stack.env using host Python
        python3 << EOF > "$selected_env"
import json

with open('$selected_file') as f:
    data = json.load(f)

stack = data.get('stack') or {}
print(f"# ASR Stack Selection")
print(f"# Generated: $(date -Iseconds)")
print()
print(f"# No viable candidate found - all probes failed")
print(f"export ASR_CUDA_FAMILY={stack.get('cuda_family', '')}")
print(f"export ASR_TORCH_VERSION={stack.get('torch', '')}")
print(f"export ASR_TORCHAUDIO_VERSION={stack.get('torchaudio', '')}")
print(f"export ASR_CTRANSLATE2_VERSION={stack.get('ctranslate2', '')}")
print(f"export ASR_FASTER_WHISPER_VERSION={stack.get('faster_whisper', '')}")
print(f"export ASR_WHISPERX_VERSION={stack.get('whisperx', '')}")
EOF
        
        log_info "Environment file saved to $selected_env"
    else
        error_exit "Failed to select winner"
    fi
}

main() {
    echo "========================================"
    echo "Selection Phase"
    echo "========================================"
    
    run_selection
    
    echo ""
    echo "Selection complete!"
    echo "Winner: ${ARTIFACTS_DIR}/selected-stack.json"
    echo "Environment: ${ARTIFACTS_DIR}/selected-stack.env"
}

main

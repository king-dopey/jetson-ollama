#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Solve Phase
# =============================================================================
# Constructs candidate stacks and ranks them using the scoring formula.
# =============================================================================
# This script is sourced by run.sh which sets:
#   ASR_SOLVER_DIR, ARTIFACTS_DIR, RAW_DIR, VENV_DIR
# =============================================================================

set -euo pipefail

# Script location (for reference)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# Source common utilities
# shellcheck source=common.sh
source "${ASR_SOLVER_DIR}/lib/common.sh"

# Use paths from run.sh environment
RAW_DIR="${ARTIFACTS_DIR}/raw"
VENV_DIR="${ASR_SOLVER_DIR}/.solver-venv"

log_info "Starting solve phase..."
log_info "Artifacts directory: $ARTIFACTS_DIR"

# =============================================================================
# Main Solve Pipeline
# =============================================================================

run_solver() {
    log_info "Running solver to construct and rank candidates..."
    
    local output_file="${ARTIFACTS_DIR}/candidate-stacks.json"
    
    # Get the relative path from ASR_SOLVER_DIR (full path inside container)
    local artifacts_relative="${ARTIFACTS_DIR#$ASR_SOLVER_DIR/}"
    
    # Use Docker to run Python with all dependencies (use relative paths inside container)
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 /solver/python/solve.py \
            --catalog "/solver/${artifacts_relative}/catalog.json" \
            --output "/solver/${artifacts_relative}/candidate-stacks.json" \
            --top-candidates "$TOP_CANDIDATES" \
            --target-python "$TARGET_PYTHON" \
            --target-platform "$TARGET_PLATFORM" \
            --cuda-families "$CUDA_FAMILIES"
    
    if [[ -f "$output_file" ]]; then
        log_info "Candidate stacks saved to $output_file"
    else
        error_exit "Failed to generate candidate stacks"
    fi
}

main() {
    echo "========================================"
    echo "Solve Phase"
    echo "========================================"
    
    run_solver
    
    echo ""
    echo "Solve complete!"
    echo "Candidates: ${ARTIFACTS_DIR}/candidate-stacks.json"
}

main

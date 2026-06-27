#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Tech Debt Generation Phase
# =============================================================================
# Generates tech debt artifacts if the winner is not fully latest.
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

log_info "Starting tech debt generation..."
log_info "Artifacts directory: $ARTIFACTS_DIR"

# =============================================================================
# Main Tech Debt Generation Pipeline
# =============================================================================

generate_debt() {
    log_info "Generating tech debt artifacts..."
    
    local catalog_file="${ARTIFACTS_DIR}/catalog.json"
    local selected_file="${ARTIFACTS_DIR}/selected-stack.json"
    local debt_md_file="${ARTIFACTS_DIR}/tech-debt.md"
    local debt_json_file="${ARTIFACTS_DIR}/tech-debt.json"
    
    # Get the relative path from ASR_SOLVER_DIR (full path inside container)
    local artifacts_relative="${ARTIFACTS_DIR#$ASR_SOLVER_DIR/}"
    
    # Run tech debt generation using Docker (use relative paths inside container)
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 /solver/python/summarize.py \
            --generate-debt \
            --catalog "/solver/${artifacts_relative}/catalog.json" \
            --candidates "/solver/${artifacts_relative}/candidate-stacks.json" \
            --probe-results "/solver/${artifacts_relative}/probe-results.json" \
            --selected "/solver/${artifacts_relative}/selected-stack.json" \
            --output-md "/solver/${artifacts_relative}/tech-debt.md" \
            --output-json "/solver/${artifacts_relative}/tech-debt.json"
    
    if [[ -f "$debt_md_file" ]] && [[ -f "$debt_json_file" ]]; then
        log_info "Tech debt artifacts saved"
    else
        log_warn "Failed to generate all tech debt artifacts"
    fi
}

main() {
    echo "========================================"
    echo "Tech Debt Generation Phase"
    echo "========================================"
    
    generate_debt
    
    echo ""
    echo "Tech debt generation complete!"
    echo "Markdown: ${ARTIFACTS_DIR}/tech-debt.md"
    echo "JSON: ${ARTIFACTS_DIR}/tech-debt.json"
}

main

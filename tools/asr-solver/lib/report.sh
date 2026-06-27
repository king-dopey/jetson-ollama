#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Report Generation Phase
# =============================================================================
# Generates human-readable report of the discovery and selection process.
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

log_info "Starting report generation..."
log_info "Artifacts directory: $ARTIFACTS_DIR"

# =============================================================================
# Main Report Generation Pipeline
# =============================================================================

generate_report() {
    log_info "Generating report..."
    
    local catalog_file="${ARTIFACTS_DIR}/catalog.json"
    local candidates_file="${ARTIFACTS_DIR}/candidate-stacks.json"
    local probe_results_file="${ARTIFACTS_DIR}/probe-results.json"
    local selected_file="${ARTIFACTS_DIR}/selected-stack.json"
    local report_file="${ARTIFACTS_DIR}/report.md"
    
    # Get the relative path from REPO_ROOT (full path inside container)
    local artifacts_relative="${ARTIFACTS_DIR#$REPO_ROOT/}"
    
    # Run report generation using Docker (use relative paths inside container)
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 /solver/python/summarize.py \
            --catalog "/solver/${artifacts_relative}/catalog.json" \
            --candidates "/solver/${artifacts_relative}/candidate-stacks.json" \
            --probe-results "/solver/${artifacts_relative}/probe-results.json" \
            --selected "/solver/${artifacts_relative}/selected-stack.json" \
            --output "/solver/${artifacts_relative}/report.md"
    
    if [[ -f "$report_file" ]]; then
        log_info "Report saved to $report_file"
    else
        error_exit "Failed to generate report"
    fi
}

main() {
    echo "========================================"
    echo "Report Generation Phase"
    echo "========================================"
    
    generate_report
    
    echo ""
    echo "Report complete!"
    echo "Report: ${ARTIFACTS_DIR}/report.md"
}

main

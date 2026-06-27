#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Main Entrypoint
# =============================================================================
# This script orchestrates the full dependency stack discovery, ranking,
# probing, and selection pipeline for Jetson ASR.
# =============================================================================

set -euo pipefail

# =============================================================================
# Path Resolution
# =============================================================================
# Resolve script location to determine ASR_SOLVER_DIR
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ASR_SOLVER_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd -- "$ASR_SOLVER_DIR/../.." && pwd -P)"

# Export ASR_SOLVER_DIR and REPO_ROOT so they're available to sourced scripts
export ASR_SOLVER_DIR
export REPO_ROOT

# =============================================================================
# Self-Check Mode
# =============================================================================
if [[ "${1:-}" == "--self-check" ]]; then
    echo "========================================"
    echo "ASR Solver Self-Check"
    echo "========================================"
    
    SELF_CHECK_LOG="${ASR_SOLVER_DIR}/artifacts/self-check.log"
    SELF_CHECK_JSON="${ASR_SOLVER_DIR}/artifacts/self-check.json"
    
    mkdir -p "${ASR_SOLVER_DIR}/artifacts"
    
    {
        echo "Self-Check Started: $(date -Iseconds)"
        echo ""
        echo "Paths:"
        echo "  SCRIPT_DIR=$SCRIPT_DIR"
        echo "  ASR_SOLVER_DIR=$ASR_SOLVER_DIR"
        echo "  REPO_ROOT=$REPO_ROOT"
        echo ""
    } > "$SELF_CHECK_LOG"
    
    SELF_CHECK_PASSED=true
    SELF_CHECK_ERRORS=()
    
    # Check config file exists
    CONFIG_FILE="${ASR_SOLVER_DIR}/config.env"
    if [[ ! -f "$CONFIG_FILE" ]]; then
        SELF_CHECK_ERRORS+=("Missing config file: $CONFIG_FILE")
        echo "ERROR: Missing config file: $CONFIG_FILE" >> "$SELF_CHECK_LOG"
    else
        echo "OK: Config file exists" >> "$SELF_CHECK_LOG"
        
        # Source with set -a to export all variables (NOT in subshell)
        set -a
        source "$CONFIG_FILE"
        set +a
        
        for key in TARGET_PYTHON TARGET_PLATFORM CUDA_FAMILIES TOP_CANDIDATES PACKAGE_SET; do
            if [[ -z "${!key:-}" ]]; then
                SELF_CHECK_ERRORS+=("Missing config key: $key")
                echo "ERROR: Missing config key: $key" >> "$SELF_CHECK_LOG"
            else
                echo "OK: Config key $key=${!key}" >> "$SELF_CHECK_LOG"
            fi
        done
    fi
    
    # Check required shell libraries
    for lib in common.sh config.sh discover.sh solve.sh probe.sh select.sh report.sh debt.sh; do
        if [[ ! -f "${ASR_SOLVER_DIR}/lib/$lib" ]]; then
            SELF_CHECK_ERRORS+=("Missing library: lib/$lib")
            echo "ERROR: Missing library: lib/$lib" >> "$SELF_CHECK_LOG"
        else
            # Check bash syntax
            if ! bash -n "${ASR_SOLVER_DIR}/lib/$lib" 2>/dev/null; then
                SELF_CHECK_ERRORS+=("Syntax error in lib/$lib")
                echo "ERROR: Syntax error in lib/$lib" >> "$SELF_CHECK_LOG"
            else
                echo "OK: lib/$lib syntax OK" >> "$SELF_CHECK_LOG"
            fi
        fi
    done
    
    # Check Python files
    for py in discover.py solve.py summarize.py metadata_utils.py; do
        if [[ ! -f "${ASR_SOLVER_DIR}/python/$py" ]]; then
            SELF_CHECK_ERRORS+=("Missing Python file: python/$py")
            echo "ERROR: Missing Python file: python/$py" >> "$SELF_CHECK_LOG"
        else
            # Check Python syntax
            if ! python3 -m py_compile "${ASR_SOLVER_DIR}/python/$py" 2>/dev/null; then
                SELF_CHECK_ERRORS+=("Syntax error in python/$py")
                echo "ERROR: Syntax error in python/$py" >> "$SELF_CHECK_LOG"
            else
                echo "OK: python/$py syntax OK" >> "$SELF_CHECK_LOG"
            fi
        fi
    done
    
    # Check Dockerfiles
    for df in Dockerfile.core-probe Dockerfile.full-probe; do
        if [[ ! -f "${ASR_SOLVER_DIR}/docker/$df" ]]; then
            SELF_CHECK_ERRORS+=("Missing Dockerfile: docker/$df")
            echo "ERROR: Missing Dockerfile: docker/$df" >> "$SELF_CHECK_LOG"
        else
            echo "OK: docker/$df exists" >> "$SELF_CHECK_LOG"
        fi
    done
    
    # Check container scripts
    for cs in entrypoint.sh core_probe.py full_probe.py; do
        if [[ ! -f "${ASR_SOLVER_DIR}/container-scripts/$cs" ]]; then
            SELF_CHECK_ERRORS+=("Missing container script: container-scripts/$cs")
            echo "ERROR: Missing container script: container-scripts/$cs" >> "$SELF_CHECK_LOG"
        else
            echo "OK: container-scripts/$cs exists" >> "$SELF_CHECK_LOG"
        fi
    done
    
    # Check required commands
    for cmd in python3 docker; do
        if ! command -v "$cmd" &>/dev/null; then
            SELF_CHECK_ERRORS+=("Missing command: $cmd")
            echo "ERROR: Missing command: $cmd" >> "$SELF_CHECK_LOG"
        else
            echo "OK: Command $cmd available" >> "$SELF_CHECK_LOG"
        fi
    done
    
    # Check artifact directory is writable
    if ! touch "${ASR_SOLVER_DIR}/artifacts/.write-test" 2>/dev/null; then
        SELF_CHECK_ERRORS+=("Artifact directory not writable: ${ASR_SOLVER_DIR}/artifacts")
        echo "ERROR: Artifact directory not writable" >> "$SELF_CHECK_LOG"
    else
        rm -f "${ASR_SOLVER_DIR}/artifacts/.write-test"
        echo "OK: Artifact directory writable" >> "$SELF_CHECK_LOG"
    fi
    
    # Generate JSON result
    if [[ ${#SELF_CHECK_ERRORS[@]} -eq 0 ]]; then
        SELF_CHECK_PASSED=true
        echo "" >> "$SELF_CHECK_LOG"
        echo "Self-Check PASSED" >> "$SELF_CHECK_LOG"
        
        cat > "$SELF_CHECK_JSON" << EOF
{
  "status": "pass",
  "timestamp": "$(date -Iseconds)",
  "script_dir": "$SCRIPT_DIR",
  "solver_dir": "$ASR_SOLVER_DIR",
  "repo_root": "$REPO_ROOT"
}
EOF
    else
        SELF_CHECK_PASSED=false
        echo "" >> "$SELF_CHECK_LOG"
        echo "Self-Check FAILED with ${#SELF_CHECK_ERRORS[@]} errors:" >> "$SELF_CHECK_LOG"
        for err in "${SELF_CHECK_ERRORS[@]}"; do
            echo "  - $err" >> "$SELF_CHECK_LOG"
        done
        
        # Build JSON errors array
        ERRORS_JSON="["
        first=true
        for err in "${SELF_CHECK_ERRORS[@]}"; do
            if [[ "$first" == "true" ]]; then
                first=false
            else
                ERRORS_JSON+=","
            fi
            ERRORS_JSON+="\"$err\""
        done
        ERRORS_JSON+="]"
        
        cat > "$SELF_CHECK_JSON" << EOF
{
  "status": "fail",
  "timestamp": "$(date -Iseconds)",
  "errors": $ERRORS_JSON,
  "error_count": ${#SELF_CHECK_ERRORS[@]}
}
EOF
    fi
    
    echo ""
    if [[ "$SELF_CHECK_PASSED" == "true" ]]; then
        echo "Self-Check PASSED"
        exit 0
    else
        echo "Self-Check FAILED"
        echo "Errors: ${SELF_CHECK_ERRORS[*]}"
        exit 1
    fi
fi

# =============================================================================
# Configuration Loading
# =============================================================================
CONFIG_FILE="${ASR_SOLVER_DIR}/config.env"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: config.env not found at $CONFIG_FILE" >&2
    exit 1
fi

# Source config with set -a to export all variables
set -a
source "$CONFIG_FILE"
set +a

# =============================================================================
# Command Line Arguments
# =============================================================================
PHASE="all"
TOP_CANDIDATES="${TOP_CANDIDATES:-3}"
NO_CACHE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase)
            PHASE="$2"
            shift 2
            ;;
        --top)
            TOP_CANDIDATES="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# =============================================================================
# Artifact Directory Setup
# =============================================================================
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARTIFACTS_DIR="${ASR_SOLVER_DIR}/artifacts/${TIMESTAMP}"
mkdir -p "${ARTIFACTS_DIR}/logs"
mkdir -p "${ARTIFACTS_DIR}/raw"

# Export ARTIFACTS_DIR for sourced scripts
export ARTIFACTS_DIR

# =============================================================================
# Solver Virtual Environment Setup (using Docker)
# =============================================================================
VENV_DIR="${ASR_SOLVER_DIR}/.solver-venv"

setup_venv() {
    echo "Setting up solver virtual environment using Docker..."
    
    # Build a solver image with all required Python packages
    local solver_image="asr-solver:latest"
    
    if [[ ! -d "$VENV_DIR" ]] || [[ "$NO_CACHE" == "true" ]]; then
        rm -rf "$VENV_DIR"
        mkdir -p "$VENV_DIR"
        
        # Create Dockerfile for solver venv
        cat > "${VENV_DIR}/Dockerfile" << 'DOCKERFILE'
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /solver
COPY python/ /solver/python/
COPY config.env /solver/config.env

# Install required packages
RUN pip install --no-cache-dir \
    packaging \
    urllib3

ENV PYTHONPATH=/solver
DOCKERFILE
        
        # Build the image from ASR_SOLVER_DIR context (not VENV_DIR)
        echo "Building Docker image..."
        if ! docker build -t "$solver_image" -f "${VENV_DIR}/Dockerfile" "$ASR_SOLVER_DIR" 2>&1; then
            echo "ERROR: Failed to build Docker image" >&2
            exit 1
        fi
        
        rm -f "${VENV_DIR}/Dockerfile"
    else
        echo "Using existing Docker image: $solver_image"
    fi
    
    echo "Solver environment ready (Docker image: $solver_image)"
}

# =============================================================================
# Run Python in Solver Container
# =============================================================================
run_solver_python() {
    local args=("$@")
    
    # Mount the solver directory and artifacts
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 "${args[@]}"
}

# =============================================================================
# Phase Execution
# =============================================================================
run_discover() {
    echo "=== DISCOVERY PHASE ==="
    "${ASR_SOLVER_DIR}/lib/discover.sh" || {
        echo "ERROR: Discovery phase failed" >&2
        exit 1
    }
}

run_solve() {
    echo "=== SOLVE PHASE ==="
    "${ASR_SOLVER_DIR}/lib/solve.sh" || {
        echo "ERROR: Solve phase failed" >&2
        exit 1
    }
}

run_probe() {
    echo "=== PROBE PHASE ==="
    "${ASR_SOLVER_DIR}/lib/probe.sh" || {
        echo "ERROR: Probe phase failed" >&2
        exit 1
    }
}

run_select() {
    echo "=== SELECTION PHASE ==="
    "${ASR_SOLVER_DIR}/lib/select.sh" || {
        echo "ERROR: Selection phase failed" >&2
        exit 1
    }
}

run_report() {
    echo "=== REPORT PHASE ==="
    "${ASR_SOLVER_DIR}/lib/report.sh" || {
        echo "ERROR: Report phase failed" >&2
        exit 1
    }
}

run_debt() {
    echo "=== TECH DEBT GENERATION ==="
    "${ASR_SOLVER_DIR}/lib/debt.sh" || {
        echo "ERROR: Tech debt generation failed" >&2
        exit 1
    }
}

# =============================================================================
# Main Pipeline
# =============================================================================
main() {
    echo "========================================"
    echo "ASR Solver - Dependency Stack Solver"
    echo "========================================"
    echo ""
    echo "Target Python: ${TARGET_PYTHON}"
    echo "Target Platform: ${TARGET_PLATFORM}"
    echo "CUDA Families: ${CUDA_FAMILIES}"
    echo "Top Candidates: ${TOP_CANDIDATES}"
    echo "Artifacts Directory: ${ARTIFACTS_DIR}"
    echo ""
    
    # Validate configuration
    "${ASR_SOLVER_DIR}/lib/config.sh" || {
        echo "ERROR: Configuration validation failed" >&2
        exit 1
    }
    
    # Setup virtual environment
    setup_venv
    
    # Export VENV_DIR for sourced scripts
    export VENV_DIR
    
    # Execute requested phase(s)
    case "$PHASE" in
        discover)
            run_discover
            ;;
        solve)
            run_solve
            ;;
        probe)
            run_probe
            ;;
        select)
            run_select
            ;;
        report)
            run_report
            run_debt
            ;;
        all)
            run_discover
            run_solve
            run_probe
            run_select
            run_report
            run_debt
            ;;
        *)
            echo "ERROR: Unknown phase: $PHASE" >&2
            exit 1
            ;;
    esac
    
    # Print summary
    echo ""
    echo "========================================"
    echo "ASR Solver Complete"
    echo "========================================"
    
    if [[ -f "${ARTIFACTS_DIR}/selected-stack.json" ]]; then
        echo ""
        echo "Winner Summary:"
        python3 -c "
import json
with open('${ARTIFACTS_DIR}/selected-stack.json') as f:
    data = json.load(f)
    stack = data.get('stack') or {}
    print(f\"  CUDA Family: {stack.get('cuda_family', 'N/A')}\")
    print(f\"  ctranslate2: {stack.get('ctranslate2', 'N/A')}\")
    print(f\"  faster-whisper: {stack.get('faster_whisper', 'N/A')}\")
    print(f\"  torch: {stack.get('torch', 'N/A')}\")
    print(f\"  torchaudio: {stack.get('torchaudio', 'N/A')}\")
    print(f\"  whisperx: {stack.get('whisperx', 'N/A')}\")
    print(f\"  Mode: {data.get('selection_reason', 'N/A')}\")
"
        echo ""
        echo "Output files:"
        echo "  - ${ARTIFACTS_DIR}/catalog.json"
        echo "  - ${ARTIFACTS_DIR}/candidate-stacks.json"
        echo "  - ${ARTIFACTS_DIR}/probe-results.json"
        echo "  - ${ARTIFACTS_DIR}/selected-stack.json"
        echo "  - ${ARTIFACTS_DIR}/selected-stack.env"
        echo "  - ${ARTIFACTS_DIR}/report.md"
        echo "  - ${ARTIFACTS_DIR}/tech-debt.md"
        echo "  - ${ARTIFACTS_DIR}/tech-debt.json"
    else
        echo ""
        echo "No winner selected. Check logs for details."
    fi
}

main

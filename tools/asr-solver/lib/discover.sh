#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Discovery Phase
# =============================================================================
# Discovers available versions and artifacts for all packages.
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
mkdir -p "$RAW_DIR"

log_info "Starting discovery phase..."
log_info "Artifacts directory: $ARTIFACTS_DIR"
log_info "Raw data directory: $RAW_DIR"

# =============================================================================
# A. PyPI Package Discovery
# =============================================================================

discover_pypi_packages() {
    log_info "Discovering PyPI packages..."
    
    local packages=("ctranslate2" "faster-whisper" "whisperx")
    
    # Get the relative path from REPO_ROOT to RAW_DIR (full path inside container)
    local raw_relative="${RAW_DIR#$REPO_ROOT/}"
    
    for pkg in "${packages[@]}"; do
        local output_file="${RAW_DIR}/pypi-${pkg}.json"
        
        log_info "Fetching PyPI metadata for $pkg..."
        
        # Use Docker to run Python with all dependencies (use relative paths inside container)
        docker run --rm \
            -v "${ASR_SOLVER_DIR}:/solver" \
            -w /solver \
            asr-solver:latest \
            python3 /solver/python/discover.py \
                --package "$pkg" \
                --output "/solver/${raw_relative}/pypi-${pkg}.json" \
                --target-python "$TARGET_PYTHON" \
                --target-platform "$TARGET_PLATFORM"
        
        if [[ -f "$output_file" ]]; then
            log_info "Saved PyPI metadata for $pkg to $output_file"
        else
            log_warn "Failed to fetch metadata for $pkg"
        fi
    done
}

# =============================================================================
# B. PyTorch CUDA Family Discovery
# =============================================================================

discover_pytorch_packages() {
    log_info "Discovering PyTorch packages for CUDA families..."
    
    read -ra cuda_families <<< "$CUDA_FAMILIES"
    
    # Get the relative path from REPO_ROOT to RAW_DIR (full path inside container)
    local raw_relative="${RAW_DIR#$REPO_ROOT/}"
    
    for family in "${cuda_families[@]}"; do
        local index_url
        eval "index_url=\"\${PYTORCH_INDEX_${family}}\""
        
        log_info "Discovering PyTorch packages for $family..."
        
        # Get available versions from pip index (using host pip)
        local torch_file="${RAW_DIR}/pip-index-torch-${family}.txt"
        local torchaudio_file="${RAW_DIR}/pip-index-torchaudio-${family}.txt"
        
        log_info "Querying pip index for torch ($family)..."
        python3 -m pip index versions torch \
            --index-url "$index_url" > "$torch_file" 2>&1 || true
        
        log_info "Querying pip index for torchaudio ($family)..."
        python3 -m pip index versions torchaudio \
            --index-url "$index_url" > "$torchaudio_file" 2>&1 || true
        
        # Parse and save version lists using Docker (use relative paths inside container)
        docker run --rm \
            -v "${ASR_SOLVER_DIR}:/solver" \
            -w /solver \
            asr-solver:latest \
            python3 /solver/python/discover.py \
                --pytorch-family "$family" \
                --torch-index "$index_url" \
                --torch-output "/solver/${raw_relative}/pytorch-${family}-versions.json" \
                --torchaudio-output "/solver/${raw_relative}/torchaudio-${family}-versions.json"
        
        log_info "Saved PyTorch versions for $family"
    done
}

# =============================================================================
# C. Wheel Verification (Optional - can be skipped if slow)
# =============================================================================

verify_wheels() {
    log_info "Verifying wheel availability..."
    
    # This is a lightweight check - full verification happens in solve phase
    # We just ensure the index URLs are accessible
    
    read -ra cuda_families <<< "$CUDA_FAMILIES"
    
    for family in "${cuda_families[@]}"; do
        local index_url
        eval "index_url=\"\${PYTORCH_INDEX_${family}}\""
        
        log_info "Checking PyTorch index accessibility: $family"
        
        if curl -s --head "$index_url" | grep -q "200 OK"; then
            log_info "  Index accessible: $family"
        else
            log_warn "  Index may be unreachable: $family"
        fi
    done
}

# =============================================================================
# D. Generate Catalog
# =============================================================================

generate_catalog() {
    log_info "Generating package catalog..."
    
    local output_file="${ARTIFACTS_DIR}/catalog.json"
    
    # Get the relative paths from REPO_ROOT (full path inside container)
    local raw_relative="${RAW_DIR#$REPO_ROOT/}"
    local artifacts_relative="${ARTIFACTS_DIR#$REPO_ROOT/}"
    
    # Use Docker to run Python with all dependencies (use relative paths inside container)
    docker run --rm \
        -v "${ASR_SOLVER_DIR}:/solver" \
        -w /solver \
        asr-solver:latest \
        python3 /solver/python/discover.py \
            --generate-catalog \
            --raw-dir "/solver/${raw_relative}" \
            --output "/solver/${artifacts_relative}/catalog.json" \
            --target-python "$TARGET_PYTHON" \
            --target-platform "$TARGET_PLATFORM" \
            --cuda-families "$CUDA_FAMILIES"
    
    if [[ -f "$output_file" ]]; then
        log_info "Catalog saved to $output_file"
    else
        error_exit "Failed to generate catalog"
    fi
}

# =============================================================================
# Main Discovery Pipeline
# =============================================================================

main() {
    echo "========================================"
    echo "Discovery Phase"
    echo "========================================"
    
    # Run all discovery steps
    discover_pypi_packages
    discover_pytorch_packages
    verify_wheels
    generate_catalog
    
    echo ""
    echo "Discovery complete!"
    echo "Raw data: $RAW_DIR"
    echo "Catalog: ${ARTIFACTS_DIR}/catalog.json"
}

main

#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Configuration Validation
# =============================================================================
# Validates all required configuration keys before any work starts.
# =============================================================================
# This script is sourced by run.sh which has already loaded config.env
# and exported all variables. We just validate the values here.
# =============================================================================

set -euo pipefail

# Script location (for reference, not used for path resolution)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# Use ASR_SOLVER_DIR from environment (set by run.sh)
# If not set, default to parent of SCRIPT_DIR
if [[ -z "${ASR_SOLVER_DIR:-}" ]]; then
    ASR_SOLVER_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
fi

CONFIG_FILE="${ASR_SOLVER_DIR}/config.env"

# Required configuration keys
REQUIRED_KEYS=(
    "TARGET_PYTHON"
    "TARGET_PLATFORM"
    "CUDA_FAMILIES"
    "TOP_CANDIDATES"
    "PACKAGE_SET"
)

error_exit() {
    echo "[ERROR] Configuration validation failed: $*" >&2
    exit 1
}

validate_keys() {
    local missing=()
    
    for key in "${REQUIRED_KEYS[@]}"; do
        if [[ -z "${!key:-}" ]]; then
            missing+=("$key")
        fi
    done
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        error_exit "Missing required keys: ${missing[*]}"
    fi
}

validate_cuda_families() {
    local errors=()
    
    # Parse CUDA families from config
    read -ra families <<< "$CUDA_FAMILIES"
    
    for family in "${families[@]}"; do
        # Check CUDA_IMAGE key exists
        local image_key="CUDA_IMAGE_${family}"
        if [[ -z "${!image_key:-}" ]]; then
            errors+=("Missing $image_key for CUDA family $family")
        fi
        
        # Check PYTORCH_INDEX key exists
        local index_key="PYTORCH_INDEX_${family}"
        if [[ -z "${!index_key:-}" ]]; then
            errors+=("Missing $index_key for CUDA family $family")
        fi
    done
    
    if [[ ${#errors[@]} -gt 0 ]]; then
        error_exit "CUDA family configuration errors: ${errors[*]}"
    fi
}

validate_python_version() {
    local python_ver="$TARGET_PYTHON"
    
    # Validate format (X.Y or X.Y.Z)
    if ! [[ "$python_ver" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
        error_exit "Invalid Python version format: $python_ver"
    fi
    
    # Check Python is available
    if ! command -v python3 &> /dev/null; then
        error_exit "python3 not found in PATH"
    fi
    
    echo "Detected Python: $(python3 --version 2>&1 | cut -d' ' -f2) (target: $python_ver)"
}

validate_platform() {
    local platform="$TARGET_PLATFORM"
    
    case "$platform" in
        linux_aarch64|linux_arm64)
            echo "Target platform: $platform (Jetson)"
            ;;
        *)
            echo "Warning: Non-standard target platform: $platform"
            ;;
    esac
}

validate_top_candidates() {
    local top="$TOP_CANDIDATES"
    
    if ! [[ "$top" =~ ^[0-9]+$ ]] || [[ "$top" -lt 1 ]]; then
        error_exit "TOP_CANDIDATES must be a positive integer, got: $top"
    fi
    
    echo "Will probe top $top candidates"
}

validate_package_set() {
    local packages="$PACKAGE_SET"
    
    if [[ -z "$packages" ]]; then
        error_exit "PACKAGE_SET is empty"
    fi
    
    # Check for required packages
    local required_packages=("ctranslate2" "faster-whisper" "torch" "torchaudio" "whisperx")
    read -ra pkg_array <<< "$packages"
    
    for req in "${required_packages[@]}"; do
        local found=false
        for pkg in "${pkg_array[@]}"; do
            if [[ "$pkg" == "$req" ]]; then
                found=true
                break
            fi
        done
        if [[ "$found" == "false" ]]; then
            error_exit "Required package not in PACKAGE_SET: $req"
        fi
    done
    
    echo "Package set: $packages"
}

validate_all() {
    echo "Validating configuration..."
    
    validate_keys
    validate_cuda_families
    validate_python_version
    validate_platform
    validate_top_candidates
    validate_package_set
    
    echo "Configuration validation passed."
}

# Run validation if script is executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    validate_all
fi

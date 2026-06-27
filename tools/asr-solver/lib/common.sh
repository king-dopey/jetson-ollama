#!/usr/bin/env bash
# =============================================================================
# ASR Solver - Common Utilities
# =============================================================================
# Shared functions used across all solver phases.
# =============================================================================

set -euo pipefail

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASR_SOLVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# =============================================================================
# Logging Functions
# =============================================================================
log_info() {
    echo "[INFO] $*"
}

log_warn() {
    echo "[WARN] $*" >&2
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_debug() {
    if [[ "${VERBOSE:-1}" -ge 2 ]]; then
        echo "[DEBUG] $*" >&2
    fi
}

# =============================================================================
# Path Utilities
# =============================================================================
get_timestamp() {
    date +%Y%m%d_%H%M%S
}

get_artifacts_dir() {
    local artifacts_base="${ASR_SOLVER_DIR}/artifacts"
    if [[ -d "$artifacts_base" ]]; then
        # Find the most recent timestamped directory
        ls -td "$artifacts_base"/*/ 2>/dev/null | head -1
    else
        echo ""
    fi
}

# =============================================================================
# JSON Utilities (using Python for robustness)
# =============================================================================
json_get() {
    local json="$1"
    local key="$2"
    python3 -c "import json,sys; d=json.loads('$json'); print(d.get('$key',''))" 2>/dev/null || echo ""
}

json_array_length() {
    local json="$1"
    python3 -c "import json,sys; d=json.loads('$json'); print(len(d))" 2>/dev/null || echo "0"
}

# =============================================================================
# Version Comparison
# =============================================================================
version_compare() {
    # Returns: 0 if v1 == v2, 1 if v1 > v2, 2 if v1 < v2
    local v1="$1"
    local v2="$2"
    
    python3 -c "
import sys
from packaging.version import Version

try:
    v1 = Version('$v1')
    v2 = Version('$v2')
    if v1 == v2:
        print(0)
    elif v1 > v2:
        print(1)
    else:
        print(2)
except Exception as e:
    # If parsing fails, do string comparison
    if '$v1' == '$v2':
        print(0)
    elif '$v1' > '$v2':
        print(1)
    else:
        print(2)
"
}

# =============================================================================
# CUDA Family Utilities
# =============================================================================
get_cuda_image() {
    local cuda_family="$1"
    eval "echo \"\${CUDA_IMAGE_${cuda_family}}\""
}

get_pytorch_index() {
    local cuda_family="$1"
    eval "echo \"\${PYTORCH_INDEX_${cuda_family}}\""
}

is_cuda_13x() {
    local cuda_family="$1"
    [[ "$cuda_family" == "cu132" || "$cuda_family" == "cu130" ]]
}

# =============================================================================
# File Utilities
# =============================================================================
ensure_dir() {
    mkdir -p "$1"
}

write_json() {
    local file="$1"
    local data="$2"
    echo "$data" | python3 -m json.tool > "$file"
}

# =============================================================================
# Cleanup Functions
# =============================================================================
cleanup_tmp() {
    local tmp_dir="$1"
    if [[ -d "$tmp_dir" ]]; then
        rm -rf "$tmp_dir"
    fi
}

# =============================================================================
# Error Handling
# =============================================================================
error_exit() {
    log_error "$1"
    exit "${2:-1}"
}

# =============================================================================
# Package Utilities
# =============================================================================
get_package_set() {
    echo "$PACKAGE_SET"
}

is_wheel_package() {
    local package="$1"
    # These packages typically have wheels for target platform
    case "$package" in
        ctranslate2|faster-whisper|torch|torchaudio|whisperx)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

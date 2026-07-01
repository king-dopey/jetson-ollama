#!/bin/bash
# ==============================================================================
# asr/build-asr-app.sh
# Build only the ASR app container image, using a prebuilt ASR base image.
#
# Usage:
#   ./build-asr-app.sh [profile] [cuda_arch]
#
# Examples:
#   ./build-asr-app.sh
#   ./build-asr-app.sh thor
#   ./build-asr-app.sh orin 87
#   ASR_APP_BASE_IMAGE=my-registry/asr-runtime-base:cuda13-2-sm90 ./build-asr-app.sh thor 90
# ==============================================================================

set -euo pipefail

PROFILE="${1:-thor}"
CUDA_ARCH="${CUDA_ARCH:-${2:-90}}"

ASR_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ASR_DIR/.." && pwd)"
STACK_ENV="$REPO_ROOT/profiles/$PROFILE/stack.env"

validate_cuda_arch() {
    case "$1" in
        90|87) ;;
        *)
            echo "ERROR: Unsupported CUDA_ARCH '$1'"
            echo "Supported values: 90 (Thor), 87 (Orin)"
            exit 1
            ;;
    esac
}

if [[ "$PROFILE" != "thor" && "$PROFILE" != "orin" ]]; then
    echo "WARNING: Invalid profile '$PROFILE', defaulting to thor"
    PROFILE="thor"
    STACK_ENV="$REPO_ROOT/profiles/$PROFILE/stack.env"
fi

validate_cuda_arch "$CUDA_ARCH"

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running"
    exit 1
fi

if [[ -z "${ASR_APP_BASE_IMAGE:-}" ]] && [[ -f "$STACK_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$STACK_ENV"
fi

if [[ -z "${ASR_APP_BASE_IMAGE:-}" ]]; then
    if [[ ! -x /usr/local/cuda/bin/nvcc ]]; then
        echo "ERROR: ASR_APP_BASE_IMAGE is unset and nvcc is unavailable to derive a default tag"
        echo "Set ASR_APP_BASE_IMAGE explicitly or install CUDA toolkit"
        exit 1
    fi
    CUDA_VERSION=$(/usr/local/cuda/bin/nvcc --version | grep -oP 'release \K[0-9.]+')
    ASR_APP_BASE_IMAGE="asr-runtime-base:cuda${CUDA_VERSION//./-}-sm${CUDA_ARCH}"
fi

if ! docker image inspect "$ASR_APP_BASE_IMAGE" >/dev/null 2>&1; then
    echo "ERROR: Required base image not found locally: $ASR_APP_BASE_IMAGE"
    echo "Build it first with: ./base-image/build-l4t-base.sh $PROFILE $CUDA_ARCH"
    exit 1
fi

echo "Building ASR app image"
echo "  Profile: $PROFILE"
echo "  Using base image: $ASR_APP_BASE_IMAGE"

(
    cd "$REPO_ROOT"
    export PROFILE
    export ASR_APP_BASE_IMAGE
    docker compose --profile asr build --no-cache --progress=plain asr
)

echo "Done."
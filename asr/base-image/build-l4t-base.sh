#!/bin/bash
# ==============================================================================
# asr/base-image/build-l4t-base.sh — Build ASR runtime base image only
#
# This script performs the full heavy build pipeline:
# 1) build CTranslate2 artifacts in Docker
# 2) build torchaudio wheel in Docker
# 3) build ASR base image from asr/base-image/Dockerfile
#
# It does NOT build the ASR app container. Use ../build-asr-app.sh for that.
# ==============================================================================

set -euo pipefail

PROFILE="${1:-thor}"
CUDA_ARCH="${CUDA_ARCH:-${2:-90}}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${REPO}/../logs"
STEP_LOG_DIR="${LOG_DIR}/build-l4t-base-steps"
OUT="/home/heaps/model128/logs"

CT_VERSION="4.8.0"
CT_SRC_DIR="${REPO}/.cache/ctranslate2-src"
ARTIFACTS_DIR="${REPO}/artifacts/ctranslate2"
TORCHAUDIO_SRC_DIR="${REPO}/.cache/pytorch-audio-src"
TORCHAUDIO_ARTIFACTS_DIR="${REPO}/artifacts/torchaudio"
TORCHAUDIO_INSTALL="/opt/torchaudio-install"
TORCHAUDIO_GIT_REF="main"
DEFAULT_ASR_TORCH_INDEX_URL="https://download.pytorch.org/whl/cu132"
DEFAULT_ASR_TORCH_VERSION="2.12.0"
DEFAULT_ASR_TORCHVISION_VERSION="0.27.0"
DEFAULT_ASR_TORCHAUDIO_VERSION="2.12.0"
ASR_BASE_DOCKERFILE="${REPO}/base-image/Dockerfile"
ASR_APP_BASE_IMAGE=""
CT_INSTALL=""
CT_BUILDER_IMAGE=""
BUILDER_DOCKERFILE="${STEP_LOG_DIR}/ctranslate2-builder.Dockerfile"
CT2_CUDA_ARCH_LIST=""

mkdir -p "$LOG_DIR" "$STEP_LOG_DIR" "$OUT" "$CT_SRC_DIR" "$ARTIFACTS_DIR" "$TORCHAUDIO_SRC_DIR" "$TORCHAUDIO_ARTIFACTS_DIR"
exec > >(tee -a "$LOG_DIR/build-l4t-base.log") 2>&1

print_progress_legend() {
    cat <<'EOF'
=== Progress legend ===
p = prepare builder container image
g = git/source step
c = cmake configure in builder container
m = compile in builder container
i = install artifacts from builder container
d = build ASR base image

A character is printed every 3 seconds only if that step's log changed.
EOF
}

monitor_log_activity() {
    local log_file="$1"
    local cmd_pid="$2"
    local progress_char="$3"
    local last_size=0
    local ticks=0

    while kill -0 "$cmd_pid" 2>/dev/null; do
        sleep 3

        local size=0
        size=$(stat -c%s "$log_file" 2>/dev/null || echo 0)

        if (( size > last_size )); then
            printf "%s" "$progress_char"
            ((ticks += 1))
            if (( ticks % 80 == 0 )); then
                printf "\n"
            fi
        fi

        last_size=$size
    done
}

run_quiet_with_progress() {
    local label="$1"
    local log_file="$2"
    local progress_char="$3"
    shift 3

    : > "$log_file"

    echo "$label"
    echo "Log: $log_file"
    echo -n "Progress: "

    "$@" >"$log_file" 2>&1 &
    local cmd_pid=$!

    monitor_log_activity "$log_file" "$cmd_pid" "$progress_char" &
    local monitor_pid=$!

    local rc=0
    if wait "$cmd_pid"; then
        rc=0
    else
        rc=$?
    fi

    kill "$monitor_pid" 2>/dev/null || true
    wait "$monitor_pid" 2>/dev/null || true
    printf "\n"

    if (( rc != 0 )); then
        echo "ERROR: command failed: $label"
        echo "--- Last 500 lines of $log_file ---"
        tail -n 500 "$log_file" || true
        return "$rc"
    fi
}

validate_cuda_arch() {
    case "$1" in
        90|87) ;;
        *)
            echo "ERROR: Unsupported CUDA_ARCH '$1'"
            echo "Supported values:"
            echo "  90 = Thor"
            echo "  87 = Orin"
            exit 1
            ;;
    esac
}

to_ct2_cuda_arch_list() {
    case "$1" in
        90) echo "9.0" ;;
        87) echo "8.7" ;;
        *)
            echo "ERROR: Cannot convert CUDA arch '$1' to CTranslate2 CUDA_ARCH_LIST format"
            exit 1
            ;;
    esac
}

print_progress_legend

echo "=== Step 1: Verify host CUDA toolkit ==="
if [[ ! -x /usr/local/cuda/bin/nvcc ]]; then
    echo "ERROR: nvcc not found at /usr/local/cuda/bin/nvcc"
    exit 1
fi

CUDA_VERSION=$(/usr/local/cuda/bin/nvcc --version | grep -oP 'release \K[0-9.]+')
echo "Host CUDA Toolkit version: $CUDA_VERSION"

echo "=== Step 2: Verify Docker daemon ==="
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running."
    exit 1
fi

echo "=== Step 3: Determine profile and CUDA arch ==="
if [[ "${PROFILE}" != "thor" && "${PROFILE}" != "orin" ]]; then
    echo "WARNING: Invalid profile '${PROFILE}', defaulting to thor"
    PROFILE="thor"
fi

validate_cuda_arch "$CUDA_ARCH"
CT2_CUDA_ARCH_LIST="$(to_ct2_cuda_arch_list "$CUDA_ARCH")"

if [[ "$PROFILE" == "thor" && "$CUDA_ARCH" != "90" ]]; then
    echo "WARNING: profile=thor usually uses CUDA arch 90, but using explicit override: ${CUDA_ARCH}"
fi

if [[ "$PROFILE" == "orin" && "$CUDA_ARCH" != "87" ]]; then
    echo "WARNING: profile=orin usually uses CUDA arch 87, but using explicit override: ${CUDA_ARCH}"
fi

CT_INSTALL="/opt/ctranslate2-${PROFILE}"
CT_BUILDER_IMAGE="asr-ctranslate2-builder:cuda${CUDA_VERSION//./-}-ubuntu24.04-sm${CUDA_ARCH}"
ASR_APP_BASE_IMAGE="asr-runtime-base:cuda${CUDA_VERSION//./-}-sm${CUDA_ARCH}"

echo "Using profile: $PROFILE (CUDA arch: SM_${CUDA_ARCH}, CTranslate2 CUDA_ARCH_LIST=${CT2_CUDA_ARCH_LIST})"
echo "Builder image tag: $CT_BUILDER_IMAGE"

echo "=== Step 4: Prepare CTranslate2 builder container image ==="
cat > "$BUILDER_DOCKERFILE" <<'EOF'
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    build-essential \
    cmake \
    make \
    ninja-build \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    libopenblas-dev \
 && rm -rf /var/lib/apt/lists/*
EOF

run_quiet_with_progress \
    "Building CTranslate2 builder image..." \
    "$STEP_LOG_DIR/05_builder_image.log" \
    "p" \
    docker build -t "$CT_BUILDER_IMAGE" -f "$BUILDER_DOCKERFILE" "$REPO"

echo "=== Step 5: Prepare CTranslate2 source ==="
if [[ ! -d "$CT_SRC_DIR/.git" ]]; then
    rm -rf "$CT_SRC_DIR"
    mkdir -p "$(dirname "$CT_SRC_DIR")"
    run_quiet_with_progress \
        "Cloning CTranslate2 source..." \
        "$STEP_LOG_DIR/10_git_clone.log" \
        "g" \
        git clone \
            --depth 1 \
            --branch "v${CT_VERSION}" \
            --recurse-submodules \
            --shallow-submodules \
            https://github.com/OpenNMT/CTranslate2.git \
            "$CT_SRC_DIR"
else
    run_quiet_with_progress \
        "Refreshing CTranslate2 source..." \
        "$STEP_LOG_DIR/11_git_refresh.log" \
        "g" \
        bash -lc "
            set -euo pipefail
            git -C '$CT_SRC_DIR' fetch --depth 1 origin 'refs/tags/v${CT_VERSION}:refs/tags/v${CT_VERSION}'
            git -C '$CT_SRC_DIR' checkout -f 'tags/v${CT_VERSION}'
            git -C '$CT_SRC_DIR' submodule sync --recursive
            git -C '$CT_SRC_DIR' submodule update --init --recursive --depth 1
            git -C '$CT_SRC_DIR' clean -fdx
        "
fi

rm -rf "$CT_SRC_DIR/build"
find "$ARTIFACTS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

echo "=== Step 6: Build CTranslate2 v${CT_VERSION} in Docker ==="
run_quiet_with_progress \
    "Configuring CTranslate2 in builder container..." \
    "$STEP_LOG_DIR/20_cmake.log" \
    "c" \
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -v /usr/local/cuda:/usr/local/cuda:ro \
        -v "$CT_SRC_DIR:/work/ctranslate2" \
        -v "$ARTIFACTS_DIR:$CT_INSTALL" \
        -w /work/ctranslate2 \
        -e CUDA_HOME=/usr/local/cuda \
        -e CUDACXX=/usr/local/cuda/bin/nvcc \
        -e CUDA_ARCH="$CUDA_ARCH" \
        -e CT2_CUDA_ARCH_LIST="$CT2_CUDA_ARCH_LIST" \
        -e CT_INSTALL="$CT_INSTALL" \
        -e PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        -e LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/targets/aarch64-linux/lib:/usr/local/cuda/targets/x86_64-linux/lib \
        "$CT_BUILDER_IMAGE" \
        bash -lc '
            set -euo pipefail
            rm -rf /work/ctranslate2/build
            cmake -S /work/ctranslate2 -B /work/ctranslate2/build \
                -DCMAKE_INSTALL_PREFIX="$CT_INSTALL" \
                -DWITH_CUDA=ON \
                -DCUDA_ARCH_LIST="$CT2_CUDA_ARCH_LIST" \
                -DBUILD_SHARED_LIBS=ON \
                -DWITH_CUDNN=OFF \
                -DWITH_MKL=OFF \
                -DOPENMP_RUNTIME=COMP \
                -DWITH_OPENBLAS=ON \
                -DENABLE_CPU_DISPATCH=OFF
        '

run_quiet_with_progress \
    "Building CTranslate2 in builder container..." \
    "$STEP_LOG_DIR/30_build.log" \
    "m" \
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -v /usr/local/cuda:/usr/local/cuda:ro \
        -v "$CT_SRC_DIR:/work/ctranslate2" \
        -v "$ARTIFACTS_DIR:$CT_INSTALL" \
        -w /work/ctranslate2 \
        -e CUDA_HOME=/usr/local/cuda \
        -e CUDACXX=/usr/local/cuda/bin/nvcc \
        -e CUDA_ARCH="$CUDA_ARCH" \
        -e CT2_CUDA_ARCH_LIST="$CT2_CUDA_ARCH_LIST" \
        -e PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        -e LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/targets/aarch64-linux/lib:/usr/local/cuda/targets/x86_64-linux/lib \
        "$CT_BUILDER_IMAGE" \
        bash -lc '
            set -euo pipefail
            cmake --build /work/ctranslate2/build -j"$(nproc)"
        '

run_quiet_with_progress \
    "Installing CTranslate2 artifacts from builder container..." \
    "$STEP_LOG_DIR/40_install.log" \
    "i" \
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -v /usr/local/cuda:/usr/local/cuda:ro \
        -v "$CT_SRC_DIR:/work/ctranslate2" \
        -v "$ARTIFACTS_DIR:$CT_INSTALL" \
        -w /work/ctranslate2 \
        -e CUDA_HOME=/usr/local/cuda \
        -e CUDACXX=/usr/local/cuda/bin/nvcc \
        -e CUDA_ARCH="$CUDA_ARCH" \
        -e CT2_CUDA_ARCH_LIST="$CT2_CUDA_ARCH_LIST" \
        -e CT_INSTALL="$CT_INSTALL" \
        -e PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        -e LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/targets/aarch64-linux/lib:/usr/local/cuda/targets/x86_64-linux/lib \
        "$CT_BUILDER_IMAGE" \
        bash -lc '
            set -euo pipefail
            cmake --install /work/ctranslate2/build
        '

echo "CTranslate2 artifacts installed to: $ARTIFACTS_DIR"
ls -la "$ARTIFACTS_DIR/lib/" || true

if [[ ! -d "$ARTIFACTS_DIR/lib" ]] || [[ ! -f "$ARTIFACTS_DIR/lib/libctranslate2.so" ]]; then
    echo "ERROR: CTranslate2 artifacts not found at $ARTIFACTS_DIR"
    echo "Expected: $ARTIFACTS_DIR/lib/libctranslate2.so"
    ls -la "$ARTIFACTS_DIR/" 2>/dev/null || true
    exit 1
fi
echo "CTranslate2 artifacts verified: $(ls "$ARTIFACTS_DIR/lib/" | tr '\n' ' ')"

echo "=== Step 7: Build torchaudio in Docker ==="

if [[ ! -d "$TORCHAUDIO_SRC_DIR/.git" ]]; then
    rm -rf "$TORCHAUDIO_SRC_DIR"
    mkdir -p "$(dirname "$TORCHAUDIO_SRC_DIR")"
    run_quiet_with_progress \
        "Cloning torchaudio source..." \
        "$STEP_LOG_DIR/50_git_clone_torchaudio.log" \
        "g" \
        git clone \
            --depth 1 \
            --branch "$TORCHAUDIO_GIT_REF" \
            --recurse-submodules \
            https://github.com/pytorch/audio.git \
            "$TORCHAUDIO_SRC_DIR"
else
    run_quiet_with_progress \
        "Refreshing torchaudio source..." \
        "$STEP_LOG_DIR/51_git_refresh_torchaudio.log" \
        "g" \
        bash -lc "
            set -euo pipefail
            git -C '$TORCHAUDIO_SRC_DIR' fetch --depth 1 origin '$TORCHAUDIO_GIT_REF'
            git -C '$TORCHAUDIO_SRC_DIR' checkout -f FETCH_HEAD
            git -C '$TORCHAUDIO_SRC_DIR' submodule sync --recursive
            git -C '$TORCHAUDIO_SRC_DIR' submodule update --init --recursive --depth 1
            git -C '$TORCHAUDIO_SRC_DIR' clean -fdx
        "
fi

find "$TORCHAUDIO_ARTIFACTS_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

run_quiet_with_progress \
    "Building torchaudio wheel in builder container..." \
    "$STEP_LOG_DIR/60_build_torchaudio.log" \
    "m" \
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        -v /usr/local/cuda:/usr/local/cuda:ro \
        -v "$TORCHAUDIO_SRC_DIR:/work/pytorch-audio" \
        -v "$TORCHAUDIO_ARTIFACTS_DIR:$TORCHAUDIO_INSTALL" \
        -w /work/pytorch-audio \
        -e CUDA_HOME=/usr/local/cuda \
        -e CUDACXX=/usr/local/cuda/bin/nvcc \
        -e ASR_TORCH_INDEX_URL="$DEFAULT_ASR_TORCH_INDEX_URL" \
        -e ASR_TORCH_VERSION="$DEFAULT_ASR_TORCH_VERSION" \
        -e ASR_TORCHVISION_VERSION="$DEFAULT_ASR_TORCHVISION_VERSION" \
        -e ASR_TORCHAUDIO_VERSION="$DEFAULT_ASR_TORCHAUDIO_VERSION" \
        -e TORCH_CUDA_ARCH_LIST="$CT2_CUDA_ARCH_LIST" \
        -e TORCHAUDIO_INSTALL="$TORCHAUDIO_INSTALL" \
        -e PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        -e LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/targets/aarch64-linux/lib:/usr/local/cuda/targets/x86_64-linux/lib \
        "$CT_BUILDER_IMAGE" \
        bash -lc '
            set -euo pipefail
            test -x /usr/local/cuda/bin/nvcc
            python3 -m venv /tmp/ta-venv
            . /tmp/ta-venv/bin/activate
            python -m pip install --no-cache-dir --upgrade pip setuptools wheel build cmake ninja
            python -m pip install --no-cache-dir \
                --index-url "$ASR_TORCH_INDEX_URL" \
                "torch==$ASR_TORCH_VERSION" \
                "torchvision==$ASR_TORCHVISION_VERSION"
            python - <<"PY"
from pathlib import Path

p = Path("/work/pytorch-audio/tools/setup_helpers/extension.py")
txt = p.read_text()
orig = txt

replacements = {
    "            sources=[_CSRC_DIR / s for s in sources],": "            sources=[str(_CSRC_DIR / s) for s in sources],",
    "                _CSRC_DIR / \"_torchaudio.cpp\",": "                str(_CSRC_DIR / \"_torchaudio.cpp\"),",
    "                _CSRC_DIR / \"utils.cpp\",": "                str(_CSRC_DIR / \"utils.cpp\"),",
    "                        _CSRC_DIR / \"cuctc\" / \"src\" / s": "                        str(_CSRC_DIR / \"cuctc\" / \"src\" / s)",
}

for old, new in replacements.items():
    txt = txt.replace(old, new)

if txt != orig:
    p.write_text(txt)
    print("Patched torchaudio extension.py source paths for setuptools compatibility")
else:
    print("No extension.py patch needed")
PY
            BUILD_VERSION="$ASR_TORCHAUDIO_VERSION" \
            CUDA_HOME="/usr/local/cuda" \
            CUDACXX="/usr/local/cuda/bin/nvcc" \
            TORCH_CUDA_ARCH_LIST="$TORCH_CUDA_ARCH_LIST" \
            CMAKE_PREFIX_PATH="$(python -c "import torch; print(torch.utils.cmake_prefix_path)")" \
            USE_CUDA=1 \
            BUILD_SOX=0 \
            USE_FFMPEG=0 \
            PIP_NO_BUILD_ISOLATION=1 \
            python -m pip wheel --no-build-isolation --no-deps -w "$TORCHAUDIO_INSTALL" .
        '

if ! compgen -G "$TORCHAUDIO_ARTIFACTS_DIR/torchaudio-*.whl" > /dev/null; then
    echo "ERROR: torchaudio wheel not found at $TORCHAUDIO_ARTIFACTS_DIR"
    ls -la "$TORCHAUDIO_ARTIFACTS_DIR/" 2>/dev/null || true
    exit 1
fi
echo "torchaudio artifacts verified: $(ls "$TORCHAUDIO_ARTIFACTS_DIR"/torchaudio-*.whl | tr '\n' ' ')"

echo "=== Step 8: Build ASR base image ==="
run_quiet_with_progress \
    "Building ASR base image..." \
    "$STEP_LOG_DIR/70_build_asr_base_image.log" \
    "d" \
    docker build \
        -f "$ASR_BASE_DOCKERFILE" \
        -t "$ASR_APP_BASE_IMAGE" \
        --build-arg BASE_IMAGE=ubuntu:24.04 \
        --build-arg ASR_TORCH_INDEX_URL="$DEFAULT_ASR_TORCH_INDEX_URL" \
        --build-arg ASR_TORCH_VERSION="$DEFAULT_ASR_TORCH_VERSION" \
        --build-arg ASR_TORCHVISION_VERSION="$DEFAULT_ASR_TORCHVISION_VERSION" \
        "$REPO"

echo "=== Step 9: Generate stack.env (for app build) ==="
cat > "${REPO}/../profiles/${PROFILE}/stack.env" <<EOF
# Auto-generated by base-image/build-l4t-base.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
MODEL_DEFAULT=qwen3.6:35b-a3b-q8_0
WARMUP_MODELS="qwen3-coder-next:q4_K_M@262144 qwen3.6:35b-a3b-q8_0@262144"
WARMUP_DEFAULT_NUM_CTX=262144
MODEL_VERIFY_TAG=qwen3-coder-next:q4_K_M

# ASR build args (base-only build complete)
ASR_DOCKERFILE=Dockerfile
BASE_IMAGE=ubuntu:24.04
ASR_APP_BASE_IMAGE=${ASR_APP_BASE_IMAGE}
ASR_CUDA_FAMILY=cu132
ASR_TORCH_INDEX_URL=${DEFAULT_ASR_TORCH_INDEX_URL}
ASR_TORCH_VERSION=${DEFAULT_ASR_TORCH_VERSION}
ASR_TORCHVISION_VERSION=${DEFAULT_ASR_TORCHVISION_VERSION}
ASR_TORCHAUDIO_VERSION=${DEFAULT_ASR_TORCHAUDIO_VERSION}
ASR_TORCHAUDIO_GIT_REF=${TORCHAUDIO_GIT_REF}
ASR_CTRANSLATE2_VERSION=${CT_VERSION}
ASR_CUDA_ARCHITECTURE=${CUDA_ARCH}
BUILD_JOBS=$(nproc)
ASR_CUDA_COMPAT_MODE=fallback
ASR_WHISPERX_VERSION=3.8.7rc1
EOF

echo "Generated: profiles/${PROFILE}/stack.env"
echo "Base image built: ${ASR_APP_BASE_IMAGE}"

if [[ "${PUSH:-0}" == "1" ]]; then
    echo "Pushing base image: ${ASR_APP_BASE_IMAGE}"
    docker push "${ASR_APP_BASE_IMAGE}"
fi

echo "=== Base image pipeline complete ==="
echo "Next: run ./build-asr-app.sh ${PROFILE} ${CUDA_ARCH}"
#!/bin/bash
# ==============================================================================
# ASR Service Pre-Build Verification for Jetson Thor/Orin (Ubuntu 24.04 base)
# Fails fast before expensive CTranslate2 build
# ==============================================================================
set -e

# CRITICAL: Architecture check MUST be the first operation, before any Docker commands.
# This prevents confusing errors when accidentally run on x86_64 CI hosts.
if [[ "$(uname -m)" != "aarch64" ]]; then
    echo "ERROR: Pre-build verification must be run on Jetson hardware (aarch64)."
    echo "Detected architecture: $(uname -m)"
    exit 1
fi

echo "=== ASR Service Pre-Build Verification ==="
echo "Target Platform: $(uname -m)"
echo "CUDA Compute Cap: $(nvidia-smi --query-gpu=compute_cap --format=csv | tail -1)"

# Step 1: Verify base image is available
BASE_TAG=${BASE_IMAGE:-ubuntu:24.04}
echo ""
echo "Step 1: Checking base image (${BASE_TAG})..."
if ! docker pull ${BASE_TAG} &>/dev/null; then
    echo "ERROR: Failed to pull ${BASE_TAG}"
    echo "Check network access to Docker Hub."
    exit 1
fi
echo "OK: Base image available"

# Step 2: Verify CUDA toolkit on host
echo ""
echo "Step 2: Verifying CUDA toolkit on host..."
if [[ ! -x /usr/local/cuda/bin/nvcc ]]; then
    echo "ERROR: nvcc not found at /usr/local/cuda/bin/nvcc!"
    echo "CUDA toolkit may be incomplete."
    exit 1
fi
/usr/local/cuda/bin/nvcc --version
echo "OK: CUDA toolkit present on host"

# Step 3: Verify nvidia-container-toolkit on host
echo ""
echo "Step 3: Verifying nvidia-container-toolkit on host..."
if ! command -v nvidia-container-cli &>/dev/null; then
    echo "ERROR: nvidia-container-cli not found."
    echo "Ensure nvidia-container-toolkit is installed: sudo apt install nvidia-container-toolkit"
    exit 1
fi
# Verify runtime is configured by checking stub library availability
if ! docker run --rm --runtime nvidia ${BASE_TAG} ls /usr/local/cuda/lib64/stubs/libcuda.so &>/dev/null; then
    echo "WARNING: nvidia runtime stubs not accessible (non-fatal; nvidia-smi only exists on host)."
fi
echo "OK: nvidia-container-toolkit configured"

# Step 4: Verify CUDA architecture matches target (Thor vs Orin)
echo ""
echo "Step 4: Verifying CUDA architecture..."
HOST_COMPUTE_CAP=$(nvidia-smi --query-gpu=compute_cap --format=csv | tail -1 | tr -d ' ')
EXPECTED_COMPUTE_CAP=${ASR_CUDA_ARCHITECTURE:-90}

if [[ "${HOST_COMPUTE_CAP}" == "${EXPECTED_COMPUTE_CAP}".* ]]; then
    echo "OK: Host CUDA architecture matches target (${HOST_COMPUTE_CAP} approx SM ${EXPECTED_COMPUTE_CAP})"
else
    echo "WARNING: Host CUDA architecture (${HOST_COMPUTE_CAP}) does not match expected (${EXPECTED_COMPUTE_CAP})."
    echo "This may indicate profile mismatch (e.g., running Orin stack on Thor)."
fi

# Step 5: Verify available disk space for CTranslate2 build
echo ""
echo "Step 5: Checking available disk space..."
AVAILABLE_SPACE=$(df -BG /var/lib/docker | tail -1 | awk '{print $4}' | tr -d 'G')
if [[ ${AVAILABLE_SPACE} -lt 10 ]]; then
    echo "ERROR: Insufficient disk space for CTranslate2 build (need >= 10GB, have ${AVAILABLE_SPACE}GB)."
    exit 1
fi
echo "OK: Sufficient disk space (${AVAILABLE_SPACE}GB available)"

echo ""
echo "=== Pre-Build Verification Passed ==="
echo "Proceeding with ASR service Docker build..."

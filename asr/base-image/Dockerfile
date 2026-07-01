# ==============================================================================
# ASR Base Image - JetPack 7.2 (Jetson Thor/Orin)
# This image contains CUDA/Python runtime, CTranslate2 artifacts, torch stack,
# torchaudio wheel, and Python dependencies. App code is not copied here.
# ==============================================================================

ARG BASE_IMAGE=ubuntu:24.04

FROM ${BASE_IMAGE} AS asr-base

ARG DEBIAN_FRONTEND=noninteractive
ARG ASR_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu132
ARG ASR_TORCH_VERSION=2.12.0
ARG ASR_TORCHVISION_VERSION=0.27.0
ARG CUDA_HOME=/usr/local/cuda

ENV CUDA_HOME=${CUDA_HOME}
ENV CUDACXX=${CUDA_HOME}/bin/nvcc
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:/usr/local/cuda/lib64/stubs:/opt/ctranslate2/lib:/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/lib/aarch64-linux-gnu

RUN apt-get update && apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    curl ffmpeg libopenblas0 libgomp1 \
    libsndfile1 libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs:/opt/ctranslate2/lib:/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/lib/aarch64-linux-gnu

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY artifacts/ctranslate2 /opt/ctranslate2
RUN ldconfig

RUN pip install --no-cache-dir --upgrade pip setuptools wheel build cmake ninja

COPY requirements.txt ./
RUN pip install --no-cache-dir \
    --index-url "${ASR_TORCH_INDEX_URL}" \
    "torch==${ASR_TORCH_VERSION}" \
    "torchvision==${ASR_TORCHVISION_VERSION}"

COPY artifacts/torchaudio /tmp/torchaudio-wheel
RUN pip install --no-cache-dir --no-deps /tmp/torchaudio-wheel/torchaudio-*.whl \
 && rm -rf /tmp/torchaudio-wheel

RUN pip install --no-cache-dir whisperx==3.8.7rc1 faster-whisper==1.2.1
RUN pip install --no-cache-dir -r requirements.txt

RUN python - <<'PY'
import torch
import torchvision
import torchaudio
print("torch", torch.__version__)
print("torchvision", torchvision.__version__)
print("torchaudio", torchaudio.__version__)
PY
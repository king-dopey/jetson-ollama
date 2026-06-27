FROM python:3.12-slim-bookworm

ARG ASR_TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130
ARG ASR_TORCH_VERSION=2.12.1+cu130
ARG ASR_TORCHAUDIO_VERSION=2.11.0+cu130

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies for CTranslate2 with CUDA support
# On Jetson, CUDA toolkit is pre-installed at /usr/local/cuda
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    cmake \
    g++ \
    gcc \
    make \
    pkg-config \
    libopenblas-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app app

# Install system dependencies for Whisper and audio processing
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
# Do not import CUDA-linked torch at build time: CUDA runtime libs are provided by
# the NVIDIA container runtime when the container runs on the Jetson host.
RUN pip install --no-cache-dir \
    --index-url "${ASR_TORCH_INDEX_URL}" \
    "torch==${ASR_TORCH_VERSION}" \
    "torchaudio==${ASR_TORCHAUDIO_VERSION}"
# Install whisperx and faster-whisper with --no-deps to avoid overwriting GPU torch
# and to prevent PyPI ctranslate2 from being installed (it's CPU-only on aarch64)
RUN pip install --no-cache-dir --no-deps whisperx==3.8.6 faster-whisper==1.2.1
# Install remaining dependencies from requirements.txt (excluding torch/torchaudio/whisperx/faster-whisper)
RUN pip install --no-cache-dir -r requirements.txt

# Build and install CTranslate2 with CUDA support for Jetson ARM64
# The PyPI wheel for aarch64 is CPU-only; we need to build from source
# On Jetson, CUDA toolkit is pre-installed at /usr/local/cuda
RUN git clone --recursive https://github.com/OpenNMT/CTranslate2.git /tmp/ctranslate2 \
    && cd /tmp/ctranslate2 \
    && mkdir build && cd build \
    && cmake -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX=/usr/local \
        -D CUDA_TOOLKIT_ROOT_DIR=/usr/local/cuda \
        -D CUDA_NVCC_EXECUTABLE=/usr/local/cuda/bin/nvcc \
        -D CUDA_INCLUDE_DIRS=/usr/local/cuda/include \
        -D WITH_CUDA=ON \
        -D WITH_CUDNN=ON \
        -D WITH_MKL=OFF \
        -D OPENMP_RUNTIME=COMP \
        -D WITH_OPENBLAS=ON \
        -D ENABLE_CPU_DISPATCH=OFF \
        .. \
    && make -j$(nproc) \
    && make install \
    && cd /tmp \
    && pip install --no-cache-dir /tmp/ctranslate2/python \
    && rm -rf /tmp/ctranslate2

# Copy the application source
COPY --chown=app:app ./*.py ./
COPY --chown=app:app ./providers/*.py ./providers/

# Copy the entrypoint
COPY --chown=app:app ./entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/models && chown -R app:app /app

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

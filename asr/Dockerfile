FROM python:3.10.14-slim-bookworm

ARG ASR_TORCH_INDEX_URL=https://pypi.jetson-ai-lab.io/jp6/cu126
ARG ASR_TORCH_VERSION=2.8.0
ARG ASR_TORCHAUDIO_VERSION=2.8.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

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
RUN pip install --no-cache-dir -r requirements.txt

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

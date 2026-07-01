# Jetson ASR Base Image

Docker image designed to encapsulate complex platform dependencies—such as CUDA, PyTorch, and CTranslate2—specifically for NVIDIA Jetson devices. Its primary purpose is to separate these low-level hardware requirements from application code. The text details the image's contents (Ubuntu base, Python environment, pre-built wheels), build prerequisites, and instructions for constructing it via helper scripts or Docker. Serves as a foundational layer for an actual ASR application container

## What This Image Contains

`base-image/Dockerfile` builds an image with:

- Ubuntu base and runtime system packages
- Python virtual environment at `/opt/venv`
- CTranslate2 artifacts from `asr/artifacts/ctranslate2`
- `torch` and `torchvision`
- Prebuilt `torchaudio` wheel from `asr/artifacts/torchaudio`
- ASR Python dependencies from `asr/requirements.txt`

It intentionally does **not** copy ASR app source files.

## Built Image Purpose

When you pull or receive a built `asr-runtime-base:*` image, you are getting a runtime layer with the following contract:

- Base OS: `ubuntu:24.04`
- Working directory: `/app`
- Python virtual environment: `/opt/venv`
- Default Python/PIP path: `/opt/venv/bin` is prepended to `PATH`
- CUDA environment variables set:
  - `CUDA_HOME=/usr/local/cuda`
  - `CUDACXX=/usr/local/cuda/bin/nvcc`
- Library search path includes:
  - `/opt/ctranslate2/lib`
  - CUDA libraries under `/usr/local/cuda`
  - OpenBLAS system libraries

Preinstalled Python stack includes:

- `torch`
- `torchvision`
- `torchaudio`
- `whisperx`
- `faster-whisper`
- packages from `asr/requirements.txt`

Preinstalled native/runtime assets include:

- CTranslate2 under `/opt/ctranslate2`
- system audio/runtime libraries such as `ffmpeg`, `libsndfile`, `libopenblas0`, and `libgomp1`

This means a downstream image can usually focus only on:

- copying application code
- creating a non-root app user
- setting entrypoint/cmd
- adding any app-specific configuration files

## What The Base Image Does Not Contain

The built base image does not include:

- ASR application source files such as `app.py`, `providers/`, or `entrypoint.sh`
- any service entrypoint or default command specific to the ASR app
- application healthcheck definition
- model cache contents
- Ollama or router code

It is a dependency/runtime image, not a complete service image by itself.

## Expected Downstream Usage

The intended downstream pattern is:

```dockerfile
ARG ASR_APP_BASE_IMAGE=asr-runtime-base:cuda13-2-sm90
FROM ${ASR_APP_BASE_IMAGE}

WORKDIR /app
COPY ./*.py ./
COPY ./providers/*.py ./providers/
COPY ./entrypoint.sh ./
```

That is, the base image should be treated as a stable platform layer for ASR app images.

## Runtime Assumptions

A consumer of the built image should assume:

- it is designed for Jetson hosts with NVIDIA runtime support
- it expects CUDA userspace compatibility from the target host/runtime environment
- it is intended to run with `runtime: nvidia` or equivalent GPU device configuration
- it does not validate application-specific environment variables on its own

If you run the image directly without a downstream app layer, it will not start an ASR service because no app entrypoint is included.

## Build Scope

`./base-image/build-l4t-base.sh` is the full base pipeline and includes:

- CTranslate2 source build in Docker
- torchaudio wheel build in Docker
- ASR base image build from `base-image/Dockerfile`
- progress/log output in `../logs/build-l4t-base-steps/*`

It does **not** build the app container image.

## Prerequisites

- Docker daemon running
- Host CUDA toolkit available at `/usr/local/cuda/bin/nvcc`
- Built CTranslate2 artifacts under `asr/artifacts/ctranslate2`
- Built torchaudio wheel under `asr/artifacts/torchaudio/torchaudio-*.whl`

## Build With Helper Script

From the `asr/` directory:

```bash
./base-image/build-l4t-base.sh [profile] [cuda_arch]
```

Examples:

```bash
./base-image/build-l4t-base.sh
./base-image/build-l4t-base.sh thor
./base-image/build-l4t-base.sh orin 87
PUSH=1 IMAGE_REPO=my-registry.example.com/asr-runtime-base ./base-image/build-l4t-base.sh thor 90
```

The tag format is:

```text
<IMAGE_REPO>:cuda<cuda-version-with-dashes>-sm<arch>
```

Example:

```text
asr-runtime-base:cuda13-2-sm90
```

## Build Directly With Docker

```bash
docker build \
  -f asr/base-image/Dockerfile \
  -t asr-runtime-base:latest \
  asr
```

## How App Image Uses It

`asr/Dockerfile` consumes this base with:

```dockerfile
ARG ASR_APP_BASE_IMAGE=asr-runtime-base:latest
FROM ${ASR_APP_BASE_IMAGE}
```

When building the app image, pass the base tag through compose/env:

```bash
ASR_APP_BASE_IMAGE=asr-runtime-base:cuda13-2-sm90 docker compose --profile asr build
```

Build the app image separately with:

```bash
./build-asr-app.sh [profile] [cuda_arch]
```

Compatibility notes:
- `asr/build-l4t-base.sh` is a wrapper that delegates to `asr/base-image/build-l4t-base.sh`.
- `asr/base-image/build-base-image.sh` is a wrapper kept for backward compatibility.
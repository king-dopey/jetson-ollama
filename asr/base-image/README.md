# ASR Base Image

This folder contains the dedicated runtime base image for ASR.

The goal is to separate platform/dependency layers from application code so this base image can later move to its own repository.

## What This Image Contains

`base-image/Dockerfile` builds an image with:

- Ubuntu base and runtime system packages
- Python virtual environment at `/opt/venv`
- CTranslate2 artifacts from `asr/artifacts/ctranslate2`
- `torch` and `torchvision`
- Prebuilt `torchaudio` wheel from `asr/artifacts/torchaudio`
- ASR Python dependencies from `asr/requirements.txt`

It intentionally does **not** copy ASR app source files.

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
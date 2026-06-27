#!/usr/bin/env bash
set -euo pipefail

PROFILE_NAME="thor"

# Verify Dockerfile.thor exists
[ -f "asr/Dockerfile.thor" ] || { echo "ERROR: missing asr/Dockerfile.thor"; exit 1; }

# Verify requirements-thor.txt exists
[ -f "asr/requirements-thor.txt" ] || { echo "ERROR: missing asr/requirements-thor.txt"; exit 1; }

# Verify compose can parse with Thor profile
docker compose config > /dev/null

printf 'Thor ASR configuration validation passed\n'

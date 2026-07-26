#!/usr/bin/env bash
set -euo pipefail

PROFILE_NAME="${1:-${PROFILE:-orin}}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODELS_FILE="${ROOT_DIR}/profiles/${PROFILE_NAME}/models.yaml"

if [ ! -f "${MODELS_FILE}" ]; then
  printf 'ERROR: missing profile file: %s\n' "${MODELS_FILE}" >&2
  exit 1
fi

mapfile -t MODELS < <(awk '/^[[:space:]]*-[[:space:]]*model:[[:space:]]*/ {print $3}' "${MODELS_FILE}")
if [ "${#MODELS[@]}" -eq 0 ]; then
  printf 'ERROR: no models found in %s\n' "${MODELS_FILE}" >&2
  exit 1
fi

for model in "${MODELS[@]}"; do
  printf 'Validating model tag: %s\n' "${model}"
  if ! (cd "${ROOT_DIR}" && docker compose exec -T ollama ollama show "${model}" >/dev/null 2>&1); then
    if ! (cd "${ROOT_DIR}" && docker compose exec -T ollama ollama pull "${model}"); then
      printf 'ERROR: planned model tag unavailable or pull failed: %s\n' "${model}" >&2
      exit 1
    fi
  fi
  printf 'OK: %s\n' "${model}"

done

printf 'Model-tag validation passed for profile=%s\n' "${PROFILE_NAME}"

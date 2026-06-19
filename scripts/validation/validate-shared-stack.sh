#!/usr/bin/env bash
set -euo pipefail

PROFILE_NAME="${1:-${PROFILE:-orin}}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local haystack=$1
  local needle=$2
  local label=$3
  if ! grep -Fq "$needle" <<<"$haystack"; then
    fail "missing ${label}: expected to find '${needle}'"
  fi
}

[ -f "${ROOT_DIR}/profiles/${PROFILE_NAME}/models.yaml" ] || fail "missing profile models file for ${PROFILE_NAME}"
[ -f "${ROOT_DIR}/profiles/${PROFILE_NAME}/librechat-modelspecs.yaml" ] || fail "missing LibreChat modelspec file for ${PROFILE_NAME}"

main_cfg="$(cd "${ROOT_DIR}" && PROFILE="${PROFILE_NAME}" docker compose config)"
router_cfg="$(cd "${ROOT_DIR}" && PROFILE="${PROFILE_NAME}" docker compose -f router/docker-compose.yml config)"

assert_contains "$main_cfg" "image: ollama/ollama:0.30.10" "shared Ollama image pin"
assert_contains "$main_cfg" "source: ${ROOT_DIR}/profiles/${PROFILE_NAME}/models.yaml" "warmup selected profile source"
assert_contains "$main_cfg" "target: /profiles/models.yaml" "warmup selected profile target"
assert_contains "$router_cfg" "source: ${ROOT_DIR}/profiles/${PROFILE_NAME}/models.yaml" "router selected profile source"
assert_contains "$router_cfg" "target: /app/model_policy.yml" "router selected profile target"

if ! grep -Fq 'registry.librechat.ai/danny-avila/librechat:0.8.6' "${ROOT_DIR}/librachat.json"; then
  fail "librachat.json is not pinned to LibreChat 0.8.6"
fi

printf 'Shared-stack validation passed for profile=%s\n' "${PROFILE_NAME}"

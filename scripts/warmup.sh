#!/bin/sh
set -eu

OLLAMA_URL=${OLLAMA_URL:-http://ollama:11434}
WARMUP_MODELS=${WARMUP_MODELS:-qwen3-coder:30b qwen3.6:35b-a3b}

echo "[warmup] waiting for ${OLLAMA_URL}/api/tags"
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

if [ "$i" -ge 60 ]; then
  echo "[warmup] ERROR: Ollama not ready after 120s"
  exit 1
fi

failures=0
for model in ${WARMUP_MODELS}; do
  if curl -fsS "${OLLAMA_URL}/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${model}\",\"prompt\":\"ok\",\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":1}}" \
    >/dev/null; then
    echo "[warmup] success ${model}"
  else
    echo "[warmup] failure ${model}"
    failures=$((failures + 1))
  fi
done

if [ "$failures" -eq 0 ]; then
  exit 0
fi

exit 1

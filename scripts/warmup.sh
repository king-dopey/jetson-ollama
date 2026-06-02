#!/bin/sh
set -eu

OLLAMA_URL=${OLLAMA_URL:-http://ollama:11434}
WARMUP_MODELS=${WARMUP_MODELS:-qwen3-coder:30b qwen3.6:35b-a3b}
PULL_MAX_RETRIES=${PULL_MAX_RETRIES:-3}
PULL_BACKOFF_SEC=${PULL_BACKOFF_SEC:-10}

log() {
  printf '[warmup] %s\n' "$*"
}

fetch_tags() {
  curl -fsS "${OLLAMA_URL}/api/tags"
}

model_in_tags() {
  model_name=$1
  tags_json=$2
  compact=$(printf '%s' "${tags_json}" | tr -d '\n\r\t ')
  printf '%s' "${compact}" | grep -F "\"name\":\"${model_name}\"" >/dev/null 2>&1
}

random_0_to() {
  max=$1
  if [ "${max}" -le 0 ]; then
    printf '0\n'
    return
  fi

  rand_raw=$(od -An -N2 -tu2 /dev/urandom 2>/dev/null | tr -d ' ')
  if [ -z "${rand_raw}" ]; then
    rand_raw=$(date +%s)
  fi
  printf '%s\n' $((rand_raw % (max + 1)))
}

pull_stream_once() {
  model_name=$1
  fifo=$(mktemp -u)
  mkfifo "${fifo}"

  curl -fsS -N -X POST "${OLLAMA_URL}/api/pull" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${model_name}\",\"stream\":true}" >"${fifo}" &
  curl_pid=$!

  saw_success=0
  last_log=0

  while IFS= read -r line; do
    case "${line}" in
      *'"status":"success"'*)
        saw_success=1
        ;;
    esac

    now=$(date +%s)
    if [ $((now - last_log)) -ge 5 ]; then
      status=$(printf '%s\n' "${line}" | sed -n 's/.*"status":"\([^"]*\)".*/\1/p')
      digest=$(printf '%s\n' "${line}" | sed -n 's/.*"digest":"\([^"]*\)".*/\1/p')
      total=$(printf '%s\n' "${line}" | sed -n 's/.*"total":\([0-9][0-9]*\).*/\1/p')
      completed=$(printf '%s\n' "${line}" | sed -n 's/.*"completed":\([0-9][0-9]*\).*/\1/p')

      msg="pulling ${model_name}"
      if [ -n "${status}" ]; then
        msg="${msg} status=${status}"
      fi
      if [ -n "${completed}" ] && [ -n "${total}" ]; then
        msg="${msg} progress=${completed}/${total}"
      fi
      if [ -n "${digest}" ]; then
        msg="${msg} digest=${digest}"
      fi

      log "${msg}"
      last_log=${now}
    fi
  done <"${fifo}"

  rm -f "${fifo}"

  if ! wait "${curl_pid}"; then
    return 1
  fi

  if [ "${saw_success}" -eq 1 ]; then
    return 0
  fi

  return 1
}

pull_and_confirm_with_retries() {
  model_name=$1
  attempt=1

  while [ "${attempt}" -le "${PULL_MAX_RETRIES}" ]; do
    if [ "${attempt}" -gt 1 ]; then
      log "retry ${attempt}/${PULL_MAX_RETRIES} ${model_name}"
    fi

    if pull_stream_once "${model_name}"; then
      tags_after=$(fetch_tags || printf '')
      if [ -n "${tags_after}" ] && model_in_tags "${model_name}" "${tags_after}"; then
        return 0
      fi
      log "post-pull-missing ${model_name}"
      last_reason=post-pull-missing
    else
      last_reason=pull-failed
    fi

    if [ "${attempt}" -lt "${PULL_MAX_RETRIES}" ]; then
      exp=$((attempt - 1))
      delay_cap=$((PULL_BACKOFF_SEC * (1 << exp)))
      sleep_for=$(random_0_to "${delay_cap}")
      sleep "${sleep_for}"
    fi
    attempt=$((attempt + 1))
  done

  if [ "${last_reason}" = "post-pull-missing" ]; then
    return 2
  fi
  return 1
}

warm_model() {
  model_name=$1
  http_code=$(curl -fsS -o /dev/null -w '%{http_code}' "${OLLAMA_URL}/api/generate" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${model_name}\",\"prompt\":\"ok\",\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":1}}" \
    || printf '000')

  if [ "${http_code}" = "200" ]; then
    log "success ${model_name}"
    return 0
  fi

  log "warm-failed ${model_name} http=${http_code}"
  return 1
}

log "waiting for ${OLLAMA_URL}/api/tags"
ready_tries=0
while [ "${ready_tries}" -lt 60 ]; do
  if fetch_tags >/dev/null 2>&1; then
    break
  fi
  ready_tries=$((ready_tries + 1))
  sleep 2
done

if [ "${ready_tries}" -ge 60 ]; then
  log 'ERROR: Ollama not ready after 120s'
  exit 1
fi

failed_models=0
summary=''
for m in ${WARMUP_MODELS}; do
  initial_tags=$(fetch_tags || printf '')
  can_warm=0

  if [ -n "${initial_tags}" ] && model_in_tags "${m}" "${initial_tags}"; then
    can_warm=1
  else
    if pull_and_confirm_with_retries "${m}"; then
      can_warm=1
    else
      pull_rc=$?
      if [ "${pull_rc}" -eq 2 ]; then
        status='post-pull-missing'
      else
        status='pull-failed'
      fi
    fi
  fi

  if [ "${can_warm}" -eq 1 ]; then
    confirmed_tags=$(fetch_tags || printf '')
    if [ -z "${confirmed_tags}" ] || ! model_in_tags "${m}" "${confirmed_tags}"; then
      log "post-pull-missing ${m}"
      status='post-pull-missing'
    elif warm_model "${m}"; then
      status='warm'
    else
      status='warm-failed'
    fi
  fi

  if [ "${status}" != 'warm' ]; then
    failed_models=$((failed_models + 1))
  fi

  if [ -n "${summary}" ]; then
    summary="${summary} ${m}=${status}"
  else
    summary="${m}=${status}"
  fi
done

printf '[warmup] summary %s\n' "${summary}"

if [ "${failed_models}" -eq 0 ]; then
  exit 0
fi

exit 1

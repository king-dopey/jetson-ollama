# OpenAI-Compatible LLM Router for Ollama

This is an OpenAI-compatible router that sits in front of an Ollama LLM serving node. It provides a unified endpoint for LLM interactions while managing model residency, context length, and other parameters according to a policy configuration.

## Features

- **OpenAI-Compatible API**: Provides `/v1/chat/completions` endpoint that accepts standard OpenAI API requests
- **Model Policy Management**: Configurable policy for managing model residency (`keep_alive`), think control, and context length
- **Tool Call Support**: Proper translation between OpenAI and Ollama tool call formats
- **Streaming Support**: Full streaming response support for chat completions
- **Think Control**: Automatic and overrideable `think` flag management for Ollama models
- **Warmup Support**: Automatic model warmup at startup for configured models

## Architecture

The router sits between clients (like LibreChat) and the Ollama LLM serving node, translating between OpenAI API format and Ollama's native API format. It manages model residency and context length according to policy configurations.

## Configuration

The router is configured through `model_policy.yml` which defines:
- Which models to keep loaded (`keep_alive`)
- Default `think` behavior for each model
- Context length (`num_ctx`) and other model options
- Whether to warm up models at startup

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | URL of the Ollama service |
| `ASR_BASE_URL` | empty | Optional explicit ASR/alignment upstream override (`http://host:port`) |
| `ASR_PORT` | `8000` | Fallback ASR port used when `ASR_BASE_URL` is not set |
| `ASR_SCHEME` | `http` | Fallback ASR scheme used when `ASR_BASE_URL` is not set |
| `MODEL_POLICY_FILE` | `/app/model_policy.yml` | Path to the model policy configuration |
| `MODEL_DEFAULT` | `qwen3.6:35b-a3b` | Default model to use |
| `KEEP_ALIVE_DEFAULT` | `-1` | Default keep_alive value |
| `LOG_LEVEL` | `INFO` | Logging level |

## Usage

### Start the Router

```bash
docker compose up -d
```

### Test the Router

```bash
curl -sS http://127.0.0.1:4000/v1/models | jq .
```

### Chat Completion

```bash
curl -sS http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.6:35b-a3b",
    "messages": [{"role": "user", "content": "Give me a one-line summary of Jetson Orin."}]
  }' | jq .
```

## Think Control Policy

The router injects the `think` flag in Ollama's `/api/chat` payload based on policy defaults and overrides.

### Policy Defaults

- `qwen3-coder:30b` defaults to `think=false`
- `qwen3.6:35b-a3b`, `nemotron-cascade-2:30b`, and `qwen2.5-coder:32b-instruct` default to `think=true`
- `think=false` for web/browse/search-style tool flows
- `think=true` for non-web tools such as `file_search` and `openweather`

### Manual Override

- `X-Ollama-Think: true`
- `X-Ollama-Think: false`

If the override header is present, it takes precedence over policy.

## Model Policy Configuration

The `model_policy.yml` file defines how each model should be handled:

```yaml
models:
  - model: qwen3-coder:30b
    keep_alive: -1
    think: false
    warmup: true
    options:
      num_ctx: 65536
      num_batch: 512
      temperature: 0.1
      top_p: 0.9
      repeat_penalty: 1.05

  - model: qwen3.6:35b-a3b
    keep_alive: 0
    think: true
    warmup: false
    options:
      num_ctx: 32768
      num_batch: 512
      temperature: 0.6
      top_p: 0.95

  - model: qwen3-coder-next:q4_K_M
    keep_alive: 0
    think: false
    warmup: false
    options:
      num_ctx: 16384
      num_batch: 256
      temperature: 0.2
      top_p: 0.9
      repeat_penalty: 1.05
```

## Integration with Ollama

This router is designed to work with the Ollama LLM serving node in this repository. It forwards requests to the Ollama service at `http://ollama:11434` by default, but can be configured to work with any Ollama instance.

## Integration with ASR Service

The ASR service can be run alongside this router. The ASR service is completely separate from the Ollama model residency system and provides a dedicated endpoint for speech-to-text with word-level timing extraction. It can be started with:

```bash
docker compose --profile asr up -d
```

The ASR service is designed to work independently of the Ollama two-warm model plan and can be used for audio processing tasks without affecting the LLM serving capabilities.

## Native Alignment Endpoints

The router exposes native alignment endpoints that forward to the ASR service while preserving the rich alignment response contract:

- `/align` - Native alignment endpoint
- `/v1/audio/align` - Namespaced alignment endpoint

Upstream wiring:
- If `ASR_BASE_URL` is set, router forwards multipart uploads to `POST ${ASR_BASE_URL}/align`
- If `ASR_BASE_URL` is unset, router infers upstream as `${ASR_SCHEME}://<ollama-host-from-OLLAMA_BASE_URL>:${ASR_PORT}` and forwards multipart uploads to `/align`
- Multipart uploads require `python-multipart` in the router image
- Path-only JSON payloads (for example `audio_path`/`media_path`) are rejected with `cross_host_alignment_requires_multipart_upload`

These endpoints return the full alignment response with:

- Transcript segments with timing information
- Word-level timestamps
- Metadata about the model used and alignment status

Example request through the router (multipart upload):

```bash
curl -sS http://127.0.0.1:4000/v1/audio/align \
  -F "media_file=@/path/to/_audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "model_accuracy=whisper-large-v3" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true" | jq .
```

Minimal contract example:

```bash
curl -F "media_file=@/path/to/audio.wav" \
  -F "model=whisper-large-v3-turbo" \
  -F "return_word_timestamps=true" \
  -F "prefer_forced_alignment=true" \
  http://127.0.0.1:4000/v1/audio/align
```

In split-host deployments, multipart upload is the required contract (`media_file` plus alignment/model fields); do not rely on shared path visibility between containers.

Troubleshooting:

- Error: `The python-multipart library must be installed to use form parsing.`
- Fix: ensure router dependencies include `python-multipart`, rebuild router image, then restart the router container.

Example response:

```json
{
  "text": "This is a test transcription. It includes multiple segments.",
  "language": "en",
  "model": "whisper-large-v3-turbo",
  "provider": "faster-whisper",
  "forced_alignment_used": true,
  "degraded": false,
  "degradation_reason": null,
  "segments": [
    {
      "start_ms": 0,
      "end_ms": 1000,
      "text": "This is a test transcription."
    },
    {
      "start_ms": 1000,
      "end_ms": 2000,
      "text": "It includes multiple segments."
    }
  ],
  "words": [
    {
      "text": "This",
      "start_ms": 0,
      "end_ms": 200,
      "confidence": 0.95
    },
    {
      "text": "is",
      "start_ms": 200,
      "end_ms": 400,
      "confidence": 0.92
    }
  ]
}
```

## On-Demand Model Auto-Pull

Configured models can now be auto-pulled on first request. When a configured model such as `qwen3-coder-next:q4_K_M` is requested and is not already present in Ollama, the router will automatically pull it before forwarding the chat request.

This feature:
- Only auto-pulls models that are explicitly allowed by the repo configuration (defined in `model_policy.yml`)
- Treats the router's model policy as the allow-list
- Does NOT auto-pull arbitrary model names supplied by clients if they are not in policy
- The first request for a missing allowed model may block until pull completes
- Large models may cause Ollama to evict other models from memory; that is acceptable and should just be documented
- Existing warmup behavior remains unchanged for startup models

To enable auto-pull, set the following environment variables:
```
AUTO_PULL_MISSING_MODELS=true
MODEL_PULL_TIMEOUT_SEC=7200
MODEL_PULL_MAX_RETRIES=2
MODEL_PULL_BACKOFF_SEC=5
```

## Health Check

```bash
curl -sS http://127.0.0.1:4000/healthz | jq .

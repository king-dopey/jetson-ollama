# OpenAI-Compatible LLM Router for Ollama

This is an OpenAI-compatible router that sits in front of an Ollama LLM serving node. It provides a unified endpoint for LLM interactions while managing model residency, context length, and other parameters according to a policy configuration.

## Features

- **OpenAI-Compatible API**: Provides `/v1/chat/completions` endpoint that accepts standard OpenAI API requests
- **Model Policy Management**: Configurable policy for managing model residency (`keep_alive`), think control, and context length
- **Tool Call Support**: Proper translation between OpenAI and Ollama tool call formats
- **Streaming Support**: Full streaming response support for chat completions
- **OpenAI Usage Contract**: Non-stream usage plus optional final stream usage chunk (`stream_options.include_usage`)
- **OpenAI-Compatible Embeddings**: `/v1/embeddings` forwards embedding requests to Jetson Ollama
- **Think Control**: Automatic and overrideable `think` flag management for Ollama models
- **Warmup Support**: Automatic model warmup at startup for configured models
- **Transparent Headroom Compression**: In-process Headroom compression (`headroom-ai`) before forwarding, with hard context budget enforcement
- **Optional Qdrant Retrieval**: Repo context retrieval can be injected before forwarding when enabled

## Architecture

The router sits between clients (like LibreChat) and the Ollama LLM serving node, translating between OpenAI API format and Ollama's native API format. It manages model residency and context length according to policy configurations.

## Configuration

The router is configured through `model_policy.yml` which defines:
- Which models to keep loaded (`keep_alive`)
- Default `think` behavior for each model
- Context length (`num_ctx`) and other model options
- Whether to warm up models at startup
- Headroom budget and trim policy (`reserved_output_tokens`, `safety_headroom_tokens`, `trim_strategy`)

In compose deployments, `/app/model_policy.yml` is provided by profile bind mount:
- `PROFILE=orin` -> `profiles/orin/models.yaml`
- `PROFILE=thor` -> `profiles/thor/models.yaml`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | URL of the Ollama service |
| `EMBEDDING_MODEL_DEFAULT` | `qwen3-embedding:4b` | Default model used by `/v1/embeddings` when request omits `model` |
| `ASR_BASE_URL` | empty | Optional explicit ASR/alignment upstream override (`http://host:port`) |
| `ASR_PORT` | `8000` | Fallback ASR port used when `ASR_BASE_URL` is not set |
| `ASR_SCHEME` | `http` | Fallback ASR scheme used when `ASR_BASE_URL` is not set |
| `MODEL_POLICY_FILE` | `/app/model_policy.yml` | Path to the model policy configuration |
| `MODEL_DEFAULT` | `qwen3.6:35b-a3b` | Default model to use |
| `KEEP_ALIVE_DEFAULT` | `-1` | Default keep_alive value |
| `HEADROOM_ENABLED` | `1` | Enable transparent in-process Headroom compression before upstream forwarding |
| `ROUTER_BIND_IP` | `0.0.0.0` | Shared bind IP used by router-host services (`router`, `qdrant`) |
| `ENABLE_QDRANT_RETRIEVAL` | `true` | Enable repository context retrieval before upstream forwarding |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant service URL used for retrieval and ingestion |
| `QDRANT_COLLECTION` | `repo_chunks` | Qdrant collection that stores repo context chunks |
| `QDRANT_EMBEDDING_MODEL` | `qwen3-embedding:4b` | Ollama embedding model used by retrieval and ingestion |
| `QDRANT_PORT` | `6333` | Host port bound for Qdrant API access |
| `QDRANT_TOP_K` | `20` | Number of candidate chunks to consider during retrieval |
| `QDRANT_FINAL_K` | `8` | Number of chunks injected into the prompt |
| `LOG_LEVEL` | `INFO` | Logging level |

## Usage

### Start the Router

```bash
docker compose up -d
```

This compose stack runs both services on the router host:

- `fastapi-router` on `http://<ROUTER_BIND_IP>:<ROUTER_PORT>`
- `qdrant` on `http://<ROUTER_BIND_IP>:<QDRANT_PORT>`

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
  - model: qwen3-coder-next:q4_K_M
    keep_alive: -1
    think: false
    warmup: true
    reserved_output_tokens: 4096
    safety_headroom_tokens: 4096
    trim_strategy: drop_oldest_then_summarize
    allow_auto_pull: true
    options:
      num_ctx: 262144
      num_batch: 512
      temperature: 0.15
      top_p: 0.95
      repeat_penalty: 1.05

  - model: qwen3.6:35b-a3b-q8_0
    keep_alive: -1
    think: true
    warmup: true
    reserved_output_tokens: 8192
    safety_headroom_tokens: 8192
    trim_strategy: summarize_history
    allow_auto_pull: true
    options:
      num_ctx: 262144
      num_batch: 512
      temperature: 0.25
      top_p: 0.95
```

## Usage Contract

### Non-streaming

`/v1/chat/completions` returns OpenAI-style `usage` on every successful non-stream response:

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `cache_creation_input_tokens` (defaults to `0` when upstream does not provide it)
- `cache_read_input_tokens` (defaults to `0` when upstream does not provide it)

When upstream token counters are absent, the router falls back to tokenizer-based counting.

### Streaming

If request body includes:

```json
{
  "stream": true,
  "stream_options": {
    "include_usage": true
  }
}
```

the router emits a final usage chunk (`choices: []`) before the terminal chunk and `data: [DONE]`.

### Embeddings

The router exposes an OpenAI-compatible embeddings endpoint:

```bash
curl -sS http://127.0.0.1:4000/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-embedding:4b",
    "input": ["class Foo", "def bar(): pass"]
  }' | jq .
```

If `model` is omitted, `EMBEDDING_MODEL_DEFAULT` is used.

### Optional Retrieval Injection

If retrieval is enabled via `ENABLE_QDRANT_RETRIEVAL=true`, the router can inject a retrieved repository context block ahead of the user messages when the request provides either:

- a `retrieval` object with `repo` and `query`, or
- top-level `context_repo` plus `context_query`

The injected block is added as a leading `system` message and is transparent to the upstream Ollama call.

## Transparent Headroom Compression

When `HEADROOM_ENABLED=true` (default: `1`), the router applies transparent history compression via the Headroom project before forwarding requests to Ollama. The compression respects per-model policies defined in `model_policy.yml`:

- `reserved_output_tokens`: Tokens reserved for generation output.
- `safety_headroom_tokens`: Additional safety margin.
- `trim_strategy`: One of `drop_oldest`, `summarize_history`, or `drop_oldest_then_summarize`.

If compression cannot fit the request within budget, the router returns HTTP 413 with detailed token budget information.

## Optional Qdrant Retrieval

When `ENABLE_QDRANT_RETRIEVAL=true`, the router can inject retrieved repository context before forwarding to Ollama. Qdrant is treated as an external service; configure its URL via `QDRANT_URL` (default: `http://qdrant:6333`).

### Fail-Open Behavior

If Qdrant is unavailable, the router proceeds with the request without retrieval context. No error is raised to the client.

### Retrieval Request Contract

Include one of the following in the request body:

```json
{
  "retrieval": {
    "repo": "my-repo",
    "query": "find authentication logic",
    "branch": "main",
    "top_k": 20,
    "final_k": 8
  }
}
```

Or use top-level fields:

```json
{
  "context_repo": "my-repo",
  "context_query": "find authentication logic"
}
```

Retrieved chunks are injected as a leading `system` message with formatted context.

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

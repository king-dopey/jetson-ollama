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

## Health Check

```bash
curl -sS http://127.0.0.1:4000/healthz | jq .
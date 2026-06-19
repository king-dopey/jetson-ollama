#!/bin/bash

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
until curl -f http://ollama:11434/api/version >/dev/null 2>&1; do
    echo "Waiting for Ollama..."
    sleep 5
done

echo "Ollama is ready. Starting ASR service..."

# Keep cache default explicit; ASR startup performs writable validation.
export ASR_MODEL_CACHE="${ASR_MODEL_CACHE:-/app/models}"

# Start the ASR service
exec "$@"

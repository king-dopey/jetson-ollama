#!/bin/bash

# Wait for Ollama to be ready
echo "Waiting for Ollama to be ready..."
until curl -f http://ollama:11434/api/version >/dev/null 2>&1; do
    echo "Waiting for Ollama..."
    sleep 5
done

echo "Ollama is ready. Starting ASR service..."

# Create model cache directory if it doesn't exist
mkdir -p "$ASR_MODEL_CACHE"

# Start the ASR service
exec "$@"
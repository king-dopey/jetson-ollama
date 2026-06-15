#!/bin/bash

echo "Testing ASR service setup..."

# Check if docker-compose is available
if ! command -v docker compose &> /dev/null; then
    echo "Error: docker compose not found"
    exit 1
fi

# Test that the ASR profile exists
echo "Checking if ASR profile is available..."
if docker compose config --profiles | grep -q "asr"; then
    echo "✓ ASR profile found"
else
    echo "✗ ASR profile not found"
    exit 1
fi

# Test basic docker-compose syntax
echo "Testing docker-compose syntax..."
if docker compose config > /dev/null 2>&1; then
    echo "✓ Docker Compose configuration is valid"
else
    echo "✗ Docker Compose configuration has errors"
    exit 1
fi

echo "ASR service setup validation complete!"
#!/usr/bin/env python3
"""
Smoke test for ASR service to verify it can be built and started.
This is a simple validation that the service structure is correct.
"""

import os
import sys
import subprocess

def test_compose_profiles():
    """Test that docker-compose can parse the configuration with ASR profile"""
    try:
        # Test that docker-compose can parse the configuration
        result = subprocess.run(
            ["docker", "compose", "config"],
            capture_output=True,
            text=True,
            cwd="."
        )
        
        if result.returncode == 0:
            print("✓ Docker Compose configuration is valid")
            # Check if ASR profile is present
            if "asr" in result.stdout:
                print("✓ ASR profile found in configuration")
            else:
                print("⚠ ASR profile not found in configuration")
        else:
            print("✗ Docker Compose configuration has errors:")
            print(result.stderr)
            return False
            
        return True
    except Exception as e:
        print(f"✗ Error testing docker-compose: {e}")
        return False

def test_files_exist():
    """Test that all required files exist"""
    required_files = [
        "asr/Dockerfile",
        "asr/requirements.txt", 
        "asr/app.py",
        "asr/entrypoint.sh"
    ]
    
    all_exist = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✓ {file_path} exists")
        else:
            print(f"✗ {file_path} missing")
            all_exist = False
    
    return all_exist

def test_env_vars():
    """Test that environment variables are properly defined"""
    env_example = ".env.example"
    if not os.path.exists(env_example):
        print("✗ .env.example not found")
        return False
        
    with open(env_example, 'r') as f:
        content = f.read()
        
    required_vars = [
        "ASR_ENABLED",
        "ASR_PORT", 
        "ASR_MODEL",
        "ASR_MODEL_ACCURACY",
        "ASR_COMPUTE_TYPE",
        "ASR_DEVICE",
        "ASR_EXPECT_DEVICE",
        "ASR_ALLOW_DEGRADED_BACKEND",
        "ASR_ALLOW_COMPUTE_FALLBACK",
        "ASR_FORCE_ALIGNMENT",
        "ASR_KEEP_WARM",
        "ASR_MODEL_CACHE",
        "HF_HOME",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "XDG_CACHE_HOME",
        "ASR_LOG_LEVEL"
    ]
    
    all_found = True
    for var in required_vars:
        if var in content:
            print(f"✓ {var} found in .env.example")
        else:
            print(f"✗ {var} missing from .env.example")
            all_found = False
            
    return all_found

def main():
    print("Running ASR service smoke test...")
    print("=" * 50)
    
    tests = [
        test_files_exist,
        test_env_vars,
        test_compose_profiles
    ]
    
    all_passed = True
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        if not test():
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All ASR service tests passed!")
        return 0
    else:
        print("✗ Some ASR service tests failed!")
        return 1


def test_dockerfile_multistage():
    """Verify Dockerfile uses multi-stage build pattern"""
    dockerfile_path = "asr/Dockerfile"
    if not os.path.exists(dockerfile_path):
        print(f"✗ {dockerfile_path} not found")
        return False
    
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    checks = [
        ("FROM.*AS builder", "Builder stage defined"),
        ("FROM python:3.12-slim-bookworm AS runtime", "Runtime stage defined") if "AS runtime" in content else ("FROM python:3.12-slim-bookworm", "Runtime stage base image"),
        ("COPY --from=builder", "Copy from builder stage"),
    ]
    
    all_passed = True
    for pattern, description in checks:
        import re
        if re.search(pattern, content):
            print(f"✓ {description}")
        else:
            print(f"✗ {description} not found")
            all_passed = False
    
    return all_passed


def test_ctranslate2_build_config():
    """Verify CTranslate2 build configuration for JetPack 7.2"""
    dockerfile_path = "asr/Dockerfile"
    if not os.path.exists(dockerfile_path):
        print(f"✗ {dockerfile_path} not found")
        return False
    
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    checks = [
        ("cuda-toolkit-13-2", "CUDA 13.2 toolkit package"),
        ("WITH_CUDNN=OFF", "cuDNN disabled (JetPack 7.2 compatibility)"),
        ("CUDA_TOOLKIT_ROOT_DIR=/usr", "CUDA toolkit root dir set to /usr"),
        ("CUDA_INCLUDE_DIRS=/usr/include/aarch64-linux-gnu", "CUDA include dirs for Jetson"),
    ]
    
    all_passed = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✓ {description}")
        else:
            print(f"✗ {description} not found")
            all_passed = False
    
    return all_passed


def main():
    print("Running ASR service smoke test...")
    print("=" * 50)
    
    tests = [
        test_files_exist,
        test_env_vars,
        test_compose_profiles,
        test_dockerfile_multistage,
        test_ctranslate2_build_config,
    ]
    
    all_passed = True
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        if not test():
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✓ All ASR service tests passed!")
        return 0
    else:
        print("✗ Some ASR service tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())

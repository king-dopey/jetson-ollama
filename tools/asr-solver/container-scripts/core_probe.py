#!/usr/bin/env python3
"""
ASR Solver - Core Probe Script

Probes the core ASR stack (torch, torchaudio, ctranslate2, faster-whisper).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional


def run_command(cmd: list, cwd: str = None) -> tuple:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def log_message(log_file: str, message: str):
    """Append a message to the log file."""
    with open(log_file, 'a') as f:
        f.write(f"[{datetime.utcnow().isoformat()}Z] {message}\n")


def probe_python_info(log_file: str) -> Dict[str, Any]:
    """Probe Python and pip information."""
    result = {
        'python_version': '',
        'pip_version': '',
        'venv_path': ''
    }
    
    # Get Python version
    success, output = run_command([sys.executable, '--version'])
    if success:
        result['python_version'] = output.strip()
    
    # Get pip version
    success, output = run_command([sys.executable, '-m', 'pip', '--version'])
    if success:
        result['pip_version'] = output.strip()
    
    # Get venv path
    result['venv_path'] = sys.prefix
    
    return result


def probe_installed_packages(log_file: str) -> Dict[str, Any]:
    """Probe installed package versions."""
    result = {
        'packages': {}
    }
    
    packages = ['torch', 'torchaudio', 'ctranslate2', 'faster_whisper']
    
    for pkg in packages:
        success, output = run_command([
            sys.executable, '-m', 'pip', 'show', pkg
        ])
        
        if success:
            # Parse version from output
            for line in output.split('\n'):
                if line.startswith('Version:'):
                    result['packages'][pkg] = line.split(':', 1)[1].strip()
                    break
    
    return result


def probe_pip_freeze(log_file: str) -> str:
    """Get pip freeze output."""
    success, output = run_command([sys.executable, '-m', 'pip', 'freeze'])
    return output if success else ''


def probe_torch_import(log_file: str) -> Dict[str, Any]:
    """Probe torch import and CUDA availability."""
    result = {
        'import_status': 'fail',
        'version': '',
        'cuda_available': False,
        'cuda_version': '',
        'tensor_test': 'fail'
    }
    
    code = '''
import sys
try:
    import torch
    print(f"VERSION:{torch.__version__}")
    
    cuda_available = torch.cuda.is_available()
    print(f"CUDA_AVAILABLE:{cuda_available}")
    
    if cuda_available:
        print(f"CUDA_VERSION:{torch.version.cuda}")
        
        # Test tensor operation
        x = torch.tensor([1.0, 2.0], device='cuda')
        y = x * 2
        print("TENSOR_TEST:pass")
    else:
        print("CUDA_VERSION:N/A")
        print("TENSOR_TEST:gpu_unavailable")
        
except ImportError as e:
    print(f"IMPORT_ERROR:{e}")
except Exception as e:
    print(f"ERROR:{e}")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    if success:
        for line in output.split('\n'):
            if line.startswith('VERSION:'):
                result['version'] = line.split(':', 1)[1].strip()
                result['import_status'] = 'pass'
            elif line.startswith('CUDA_AVAILABLE:'):
                result['cuda_available'] = line.split(':', 1)[1].strip() == 'True'
            elif line.startswith('CUDA_VERSION:'):
                result['cuda_version'] = line.split(':', 1)[1].strip()
            elif line.startswith('TENSOR_TEST:'):
                result['tensor_test'] = line.split(':', 1)[1].strip()
            elif line.startswith('IMPORT_ERROR:'):
                result['import_status'] = 'fail'
    
    return result


def probe_ctranslate2_import(log_file: str) -> Dict[str, Any]:
    """Probe ctranslate2 import and CUDA availability."""
    result = {
        'import_status': 'fail',
        'version': '',
        'cuda_available': False
    }
    
    code = '''
import sys
try:
    import ctranslate2
    print(f"VERSION:{ctranslate2.__version__}")
    
    if hasattr(ctranslate2, 'is_cuda_available'):
        cuda_avail = ctranslate2.is_cuda_available()
        print(f"CUDA_AVAILABLE:{cuda_avail}")
    else:
        print("CUDA_AVAILABLE:N/A")
        
except ImportError as e:
    print(f"IMPORT_ERROR:{e}")
except Exception as e:
    print(f"ERROR:{e}")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    if success:
        for line in output.split('\n'):
            if line.startswith('VERSION:'):
                result['version'] = line.split(':', 1)[1].strip()
                result['import_status'] = 'pass'
            elif line.startswith('CUDA_AVAILABLE:'):
                result['cuda_available'] = line.split(':', 1)[1].strip() == 'True'
            elif line.startswith('IMPORT_ERROR:'):
                result['import_status'] = 'fail'
    
    return result


def probe_faster_whisper_import(log_file: str) -> Dict[str, Any]:
    """Probe faster-whisper import."""
    result = {
        'import_status': 'fail',
        'version': ''
    }
    
    code = '''
import sys
try:
    import faster_whisper
    print(f"VERSION:{faster_whisper.__version__}")
        
except ImportError as e:
    print(f"IMPORT_ERROR:{e}")
except Exception as e:
    print(f"ERROR:{e}")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    if success:
        for line in output.split('\n'):
            if line.startswith('VERSION:'):
                result['version'] = line.split(':', 1)[1].strip()
                result['import_status'] = 'pass'
            elif line.startswith('IMPORT_ERROR:'):
                result['import_status'] = 'fail'
    
    return result


def probe_cuda_runtime(log_file: str) -> Dict[str, Any]:
    """Probe CUDA runtime library visibility."""
    result = {
        'libcudart_visible': False,
        'libcublas_visible': False,
        'libcudnn_visible': False,
        'ldconfig_output': '',
        'libcudart_paths': [],
        'libcublas_paths': [],
        'libcudnn_paths': []
    }
    
    # Run ldconfig
    success, output = run_command(['ldconfig', '-p'])
    if success:
        result['ldconfig_output'] = output
        
        for line in output.split('\n'):
            if 'libcudart.so' in line:
                result['libcudart_visible'] = True
                result['libcudart_paths'].append(line.strip())
            elif 'libcublas.so' in line:
                result['libcublas_visible'] = True
                result['libcublas_paths'].append(line.strip())
            elif 'libcudnn.so' in line:
                result['libcudnn_visible'] = True
                result['libcudnn_paths'].append(line.strip())
    
    # Find library files
    for cmd, key in [
        (['find', '/usr', '-name', 'libcudart.so*'], 'libcudart_paths'),
        (['find', '/usr', '-name', 'libcublas.so*'], 'libcublas_paths'),
        (['find', '/usr', '-name', 'libcudnn.so*'], 'libcudnn_paths')
    ]:
        success, output = run_command(cmd)
        if success:
            for line in output.split('\n'):
                if line.strip():
                    result[key].append(line.strip())
    
    return result


def generate_synthetic_wav(log_file: str) -> tuple:
    """Generate a synthetic WAV file for testing."""
    code = '''
import numpy as np
from scipy.io import wavfile

# Generate 1 second of 440 Hz sine wave at 16 kHz
sample_rate = 16000
duration = 1.0
frequency = 440.0

t = np.linspace(0, duration, int(sample_rate * duration))
waveform = np.sin(2 * np.pi * frequency * t)
waveform = (waveform * 32767).astype(np.int16)

# Save to /tmp/test.wav
wavfile.write('/tmp/test.wav', sample_rate, waveform)
print("SUCCESS:/tmp/test.wav")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    if success:
        for line in output.split('\n'):
            if line.startswith('SUCCESS:'):
                return True, line.split(':', 1)[1].strip()
    
    return False, ''


def run_smoke_test(log_file: str) -> Dict[str, Any]:
    """Run a minimal transcription smoke test."""
    result = {
        'status': 'fail',
        'reason': '',
        'output': ''
    }
    
    code = '''
import sys
try:
    import torch
    import faster_whisper
    
    # Load tiny model
    model = faster_whisper.WhisperModel("tiny", device="cpu", compute_type="int8")
    
    # Transcribe test audio
    segments, info = model.transcribe("/tmp/test.wav", language="en")
    
    text = ""
    for segment in segments:
        text += segment.text
    
    print(f"SUCCESS:{text[:50]}")
        
except ImportError as e:
    print(f"IMPORT_ERROR:{e}")
except Exception as e:
    print(f"ERROR:{e}")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    if success:
        for line in output.split('\n'):
            if line.startswith('SUCCESS:'):
                result['status'] = 'pass'
                result['output'] = line.split(':', 1)[1].strip()
            elif line.startswith('IMPORT_ERROR:'):
                result['reason'] = line.split(':', 1)[1].strip()
            elif line.startswith('ERROR:'):
                result['reason'] = line.split(':', 1)[1].strip()
    
    return result


def main():
    parser = argparse.ArgumentParser(description='ASR Core Probe')
    parser.add_argument('--cuda-family', required=True, help='CUDA family')
    parser.add_argument('--ctranslate2', required=True, help='ctranslate2 version')
    parser.add_argument('--faster-whisper', required=True, help='faster-whisper version')
    parser.add_argument('--torch', required=True, help='torch version')
    parser.add_argument('--torchaudio', required=True, help='torchaudio version')
    parser.add_argument('--constraints', required=True, help='Constraints file path')
    parser.add_argument('--pytorch-index', required=True, help='PyTorch index URL')
    parser.add_argument('--log-file', required=True, help='Log file path')
    parser.add_argument('--artifacts-dir', required=True, help='Artifacts directory')
    
    args = parser.parse_args()
    
    log_file = args.log_file
    artifacts_dir = args.artifacts_dir
    
    # Clear log file
    open(log_file, 'w').close()
    
    log_message(log_file, "Starting core probe...")
    log_message(log_file, f"CUDA Family: {args.cuda_family}")
    log_message(log_file, f"ctranslate2: {args.ctranslate2}")
    log_message(log_file, f"faster-whisper: {args.faster_whisper}")
    log_message(log_file, f"torch: {args.torch}")
    log_message(log_file, f"torchaudio: {args.torchaudio}")
    
    # Install packages
    log_message(log_file, "Installing packages...")
    
    install_cmd = [
        sys.executable, '-m', 'pip', 'install',
        '--extra-index-url', args.pytorch_index,
        '--constraint', args.constraints,
        f'torch=={args.torch}',
        f'torchaudio=={args.torchaudio}',
        f'ctranslate2=={args.ctranslate2}',
        f'faster-whisper=={args.faster_whisper}'
    ]
    
    success, output = run_command(install_cmd)
    
    if not success:
        log_message(log_file, f"Install failed: {output}")
        
        result = {
            'candidate_rank': 1,
            'stack': {
                'cuda_family': args.cuda_family,
                'ctranslate2': args.ctranslate2,
                'faster_whisper': args.faster_whisper,
                'torch': args.torch,
                'torchaudio': args.torchaudio,
                'whisperx': ''
            },
            'core_probe': {
                'status': 'fail',
                'reason': 'pip_install_error',
                'install_status': 'fail',
                'torch_import': 'not_run',
                'ctranslate2_import': 'not_run',
                'faster_whisper_import': 'not_run',
                'cuda_runtime_visible': False,
                'torch_cuda_available': False,
                'ctranslate2_cuda_available': False,
                'smoke_test': 'not_run',
                'log_path': log_file
            },
            'full_probe': {
                'status': 'not_run',
                'reason': 'core_probe_failed',
                'whisperx_import': 'not_run',
                'minimal_init': 'not_run',
                'log_path': log_file
            }
        }
        
        # Save result
        result_file = os.path.join(artifacts_dir, 'probe-results.json')
        if os.path.exists(result_file):
            with open(result_file) as f:
                results = json.load(f)
        else:
            results = {'results': []}
        
        results['results'].append(result)
        
        with open(result_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        sys.exit(1)
    
    log_message(log_file, "Install successful")
    
    # Run probes
    log_message(log_file, "Running Python info probe...")
    python_info = probe_python_info(log_file)
    log_message(log_file, f"Python: {python_info['python_version']}")
    
    log_message(log_file, "Running installed packages probe...")
    installed = probe_installed_packages(log_file)
    log_message(log_file, f"Installed: {installed['packages']}")
    
    log_message(log_file, "Running pip freeze...")
    freeze = probe_pip_freeze(log_file)
    
    log_message(log_file, "Running torch import probe...")
    torch_result = probe_torch_import(log_file)
    log_message(log_file, f"Torch: {torch_result['version']}, CUDA: {torch_result['cuda_available']}")
    
    log_message(log_file, "Running ctranslate2 import probe...")
    ct2_result = probe_ctranslate2_import(log_file)
    log_message(log_file, f"ctranslate2: {ct2_result['version']}, CUDA: {ct2_result['cuda_available']}")
    
    log_message(log_file, "Running faster-whisper import probe...")
    fw_result = probe_faster_whisper_import(log_file)
    log_message(log_file, f"faster-whisper: {fw_result['version']}")
    
    log_message(log_file, "Running CUDA runtime probe...")
    cuda_runtime = probe_cuda_runtime(log_file)
    log_message(log_file, f"libcudart visible: {cuda_runtime['libcudart_visible']}")
    
    log_message(log_file, "Generating synthetic WAV...")
    wav_success, wav_path = generate_synthetic_wav(log_file)
    log_message(log_file, f"WAV generated: {wav_path}")
    
    if wav_success:
        log_message(log_file, "Running smoke test...")
        smoke_result = run_smoke_test(log_file)
        log_message(log_file, f"Smoke test: {smoke_result['status']}")
    else:
        smoke_result = {'status': 'fail', 'reason': 'wav_generation_failed'}
    
    # Build result
    result = {
        'candidate_rank': 1,
        'stack': {
            'cuda_family': args.cuda_family,
            'ctranslate2': args.ctranslate2,
            'faster_whisper': args.faster_whisper,
            'torch': args.torch,
            'torchaudio': args.torchaudio,
            'whisperx': ''
        },
        'core_probe': {
            'status': 'pass' if torch_result['import_status'] == 'pass' else 'fail',
            'reason': '',
            'install_status': 'pass',
            'torch_import': torch_result['import_status'],
            'ctranslate2_import': ct2_result['import_status'],
            'faster_whisper_import': fw_result['import_status'],
            'cuda_runtime_visible': cuda_runtime['libcudart_visible'],
            'torch_cuda_available': torch_result['cuda_available'],
            'ctranslate2_cuda_available': ct2_result['cuda_available'],
            'smoke_test': smoke_result['status'],
            'log_path': log_file
        },
        'full_probe': {
            'status': 'not_run',
            'reason': 'not_attempted',
            'whisperx_import': 'not_run',
            'minimal_init': 'not_run',
            'log_path': log_file
        }
    }
    
    # Save result
    result_file = os.path.join(artifacts_dir, 'probe-results.json')
    if os.path.exists(result_file):
        with open(result_file) as f:
            results = json.load(f)
    else:
        results = {'results': []}
    
    results['results'].append(result)
    
    with open(result_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    log_message(log_file, "Core probe complete")
    
    if torch_result['import_status'] == 'pass':
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

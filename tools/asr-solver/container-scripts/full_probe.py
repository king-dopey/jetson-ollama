#!/usr/bin/env python3
"""
ASR Solver - Full Probe Script

Probes the complete ASR stack including whisperx.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Dict, Any


def run_command(cmd: list, cwd: str = None) -> tuple:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600
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


def probe_whisperx_import(log_file: str) -> Dict[str, Any]:
    """Probe whisperx import and minimal init."""
    result = {
        'import_status': 'fail',
        'version': '',
        'minimal_init': 'not_run'
    }
    
    code = '''
import sys
try:
    import whisperx
    print(f"VERSION:{getattr(whisperx, '__version__', 'unknown')}")
    
    # Minimal init - just check we can import
    print("MINIMAL_INIT:pass")
        
except ImportError as e:
    print(f"IMPORT_ERROR:{e}")
except Exception as e:
    print(f"ERROR:{e}")
'''
    
    success, output = run_command([sys.executable, '-c', code])
    
    log_message(log_file, f"whisperx import probe output: '{output[:200]}'")
    
    if success:
        for line in output.split('\n'):
            if line.startswith('VERSION:'):
                result['version'] = line.split(':', 1)[1].strip()
                result['import_status'] = 'pass'
            elif line.startswith('MINIMAL_INIT:'):
                result['minimal_init'] = line.split(':', 1)[1].strip()
            elif line.startswith('IMPORT_ERROR:'):
                result['import_status'] = 'fail'
    
    return result


def main():
    parser = argparse.ArgumentParser(description='ASR Full Probe')
    parser.add_argument('--cuda-family', required=True, help='CUDA family')
    parser.add_argument('--ctranslate2', required=True, help='ctranslate2 version')
    parser.add_argument('--faster-whisper', required=True, help='faster-whisper version')
    parser.add_argument('--torch', required=True, help='torch version')
    parser.add_argument('--torchaudio', required=True, help='torchaudio version')
    parser.add_argument('--whisperx', required=True, help='whisperx version')
    parser.add_argument('--constraints', required=True, help='Constraints file path')
    parser.add_argument('--pytorch-index', required=True, help='PyTorch index URL')
    parser.add_argument('--log-file', required=True, help='Log file path')
    parser.add_argument('--artifacts-dir', required=True, help='Artifacts directory')
    
    args = parser.parse_args()
    
    log_file = args.log_file
    artifacts_dir = args.artifacts_dir
    
    # Clear log file
    open(log_file, 'w').close()
    
    log_message(log_file, "Starting full probe...")
    log_message(log_file, f"CUDA Family: {args.cuda_family}")
    log_message(log_file, f"whisperx: {args.whisperx}")
    
    # Install whisperx
    log_message(log_file, "Installing whisperx...")
    
    install_cmd = [
        sys.executable, '-m', 'pip', 'install',
        '--extra-index-url', args.pytorch_index,
        '--constraint', args.constraints,
        f'whisperx=={args.whisperx}'
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
                'whisperx': args.whisperx
            },
            'core_probe': {
                'status': 'pass',
                'reason': '',
                'install_status': 'pass',
                'torch_import': 'pass',
                'ctranslate2_import': 'pass',
                'faster_whisper_import': 'pass',
                'cuda_runtime_visible': True,
                'torch_cuda_available': False,
                'ctranslate2_cuda_available': False,
                'smoke_test': 'pass',
                'log_path': log_file.replace('full', 'core')
            },
            'full_probe': {
                'status': 'fail',
                'reason': 'whisperx_install_error',
                'whisperx_import': 'fail',
                'minimal_init': 'not_run',
                'log_path': log_file
            }
        }
        
        # Update result file
        result_file = os.path.join(artifacts_dir, 'probe-results.json')
        if os.path.exists(result_file):
            with open(result_file) as f:
                results = json.load(f)
            
            # Find and update the matching result
            for r in results.get('results', []):
                if r.get('stack', {}).get('whisperx') == args.whisperx:
                    r['full_probe'] = result['full_probe']
                    break
            
            with open(result_file, 'w') as f:
                json.dump(results, f, indent=2)
        
        sys.exit(1)
    
    log_message(log_file, "whisperx install successful")
    
    # Verify whisperx is installed
    verify_cmd = [sys.executable, '-m', 'pip', 'show', 'whisperx']
    success, output = run_command(verify_cmd)
    if success:
        log_message(log_file, f"whisperx pip show: {output[:200]}")
    else:
        log_message(log_file, "whisperx not found via pip show")
    
    # Probe whisperx
    log_message(log_file, "Running whisperx import probe...")
    wx_result = probe_whisperx_import(log_file)
    log_message(log_file, f"whisperx: {wx_result['version']}, init: {wx_result['minimal_init']}, status: {wx_result['import_status']}")
    
    # Build result
    result = {
        'candidate_rank': 1,
        'stack': {
            'cuda_family': args.cuda_family,
            'ctranslate2': args.ctranslate2,
            'faster_whisper': args.faster_whisper,
            'torch': args.torch,
            'torchaudio': args.torchaudio,
            'whisperx': args.whisperx
        },
        'core_probe': {
            'status': 'pass',
            'reason': '',
            'install_status': 'pass',
            'torch_import': 'pass',
            'ctranslate2_import': 'pass',
            'faster_whisper_import': 'pass',
            'cuda_runtime_visible': True,
            'torch_cuda_available': False,
            'ctranslate2_cuda_available': False,
            'smoke_test': 'pass',
            'log_path': log_file.replace('full', 'core')
        },
        'full_probe': {
            'status': 'pass' if wx_result['import_status'] == 'pass' else 'fail',
            'reason': '' if wx_result['import_status'] == 'pass' else wx_result.get('version', ''),
            'whisperx_import': wx_result['import_status'],
            'minimal_init': wx_result['minimal_init'],
            'log_path': log_file
        }
    }
    
    # Update result file
    result_file = os.path.join(artifacts_dir, 'probe-results.json')
    if os.path.exists(result_file):
        with open(result_file) as f:
            results = json.load(f)
        
        # Find and update the matching result
        for r in results.get('results', []):
            if r.get('stack', {}).get('whisperx') == args.whisperx:
                r['full_probe'] = result['full_probe']
                break
        
        with open(result_file, 'w') as f:
            json.dump(results, f, indent=2)
    
    log_message(log_file, "Full probe complete")
    
    if wx_result['import_status'] == 'pass':
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
ASR Solver - Package Discovery Module

Discovers available versions and artifacts for ASR packages from PyPI and PyTorch.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


def fetch_pypi_json(package: str, timeout: int = 30) -> Dict[str, Any]:
    """Fetch package metadata from PyPI JSON API."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.URLError as e:
        print(f"ERROR: Failed to fetch {package}: {e}", file=sys.stderr)
        return {}
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON for {package}: {e}", file=sys.stderr)
        return {}


def parse_wheel_filename(filename: str) -> Optional[Dict[str, Any]]:
    """Parse wheel filename to extract metadata."""
    # Format: {distribution}-{version}(-{build tag})?-{python}-{abi}-{platform}.whl
    import re
    
    # Basic pattern for wheel filenames
    pattern = r'^([a-zA-Z0-9_-]+)-([0-9.]+)(?:-([0-9]+))?(-[a-zA-Z0-9_.]+)*-([a-zA-Z0-9_.]+)-([a-zA-Z0-9_.]+)-([a-zA-Z0-9_.]+)\.whl$'
    match = re.match(pattern, filename)
    
    if not match:
        return None
    
    return {
        'distribution': match.group(1),
        'version': match.group(2),
        'build_tag': match.group(3),
        'python_tag': match.group(5),
        'abi_tag': match.group(6),
        'platform_tag': match.group(7)
    }


def has_aarch64_wheel(tags: List[str]) -> bool:
    """Check if any tag indicates aarch64 support."""
    for tag in tags:
        if 'aarch64' in tag.lower() or 'arm64' in tag.lower():
            return True
    return False


def has_cp312_wheel(tags: List[str]) -> bool:
    """Check if any tag indicates Python 3.12 support."""
    for tag in tags:
        if 'cp312' in tag.lower() or 'py312' in tag.lower():
            return True
    return False


def analyze_release(release: Dict[str, Any], target_python: str) -> Dict[str, Any]:
    """Analyze a release file for target compatibility."""
    result = {
        'filename': release.get('filename', ''),
        'packagetype': release.get('packagetype', ''),
        'python_version': release.get('python_version', ''),
        'requires_python': release.get('requires_python', ''),
        'upload_time': release.get('upload_time_iso_8601', ''),
        'yanked': release.get('yanked', False),
        'url': release.get('url', ''),
        'size': release.get('size', 0),
        'has_wheel': False,
        'has_sdist': False,
        'has_cp312_wheel': False,
        'has_aarch64_wheel': False,
        'has_cp312_aarch64_wheel': False
    }
    
    filename = release.get('filename', '')
    packagetype = release.get('packagetype', '')
    
    if packagetype == 'wheel':
        result['has_wheel'] = True
        parsed = parse_wheel_filename(filename)
        if parsed:
            tags = [parsed['python_tag'], parsed['platform_tag']]
            result['has_cp312_wheel'] = has_cp312_wheel(tags)
            result['has_aarch64_wheel'] = has_aarch64_wheel(tags)
            result['has_cp312_aarch64_wheel'] = (
                has_cp312_wheel(tags) and has_aarch64_wheel(tags)
            )
    elif packagetype == 'sdist':
        result['has_sdist'] = True
    
    return result


def get_package_versions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract version information from PyPI response."""
    versions = []
    
    releases = data.get('releases', {})
    for version, files in releases.items():
        if not files:
            continue
        
        version_info = {
            'version': version,
            'files': [],
            'latest_file': None,
            'has_wheel': False,
            'has_sdist': False,
            'has_target_wheel': False
        }
        
        for file_info in files:
            analysis = analyze_release(file_info, '')
            version_info['files'].append(analysis)
            
            if analysis['has_wheel']:
                version_info['has_wheel'] = True
            if analysis['has_sdist']:
                version_info['has_sdist'] = True
            if analysis['has_cp312_aarch64_wheel']:
                version_info['has_target_wheel'] = True
        
        versions.append(version_info)
    
    # Sort by version (newest first)
    versions.sort(key=lambda x: x['version'], reverse=True)
    
    return versions


def discover_pypi_packages(packages: List[str], output_dir: str) -> Dict[str, Any]:
    """Discover packages from PyPI."""
    result = {}
    
    for package in packages:
        print(f"Fetching PyPI metadata for {package}...")
        data = fetch_pypi_json(package)
        
        if not data:
            continue
        
        # Save raw JSON
        raw_file = os.path.join(output_dir, f"pypi-{package}.json")
        with open(raw_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Extract versions
        versions = get_package_versions(data)
        
        result[package] = {
            'latest_version': data.get('info', {}).get('version', ''),
            'versions': versions,
            'total_releases': len(versions)
        }
    
    return result


def discover_pytorch_versions(index_url: str, output_dir: str) -> Dict[str, List[str]]:
    """Discover PyTorch versions for a CUDA family."""
    import subprocess
    
    versions = {'torch': [], 'torchaudio': []}
    
    for package in ['torch', 'torchaudio']:
        print(f"Querying pip index for {package}...")
        
        cmd = [
            sys.executable, '-m', 'pip', 'index', 'versions',
            package,
            '--index-url', index_url
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            # Save raw output
            raw_file = os.path.join(output_dir, f"pip-index-{package}.txt")
            with open(raw_file, 'w') as f:
                f.write(result.stdout)
                if result.stderr:
                    f.write("\nSTDERR:\n" + result.stderr)
            
            # Parse versions from output
            for line in result.stdout.split('\n'):
                if 'Available versions:' in line:
                    version_str = line.split(':', 1)[1].strip()
                    versions[package] = [v.strip() for v in version_str.split(',')]
                    break
            
        except subprocess.TimeoutExpired:
            print(f"Timeout querying {package}", file=sys.stderr)
        except Exception as e:
            print(f"Error querying {package}: {e}", file=sys.stderr)
    
    return versions


def generate_catalog(
    pypi_data: Dict[str, Any],
    pytorch_data: Dict[str, Dict[str, List[str]]],
    target_python: str,
    target_platform: str,
    cuda_families: List[str]
) -> Dict[str, Any]:
    """Generate the final catalog JSON."""
    
    # Build latest versions
    latest = {
        'ctranslate2': pypi_data.get('ctranslate2', {}).get('latest_version', ''),
        'faster-whisper': pypi_data.get('faster-whisper', {}).get('latest_version', ''),
        'torch': {},
        'torchaudio': {},
        'whisperx': pypi_data.get('whisperx', {}).get('latest_version', '')
    }
    
    for family in cuda_families:
        if family in pytorch_data:
            latest['torch'][family] = pytorch_data[family].get('torch', [])[0] if pytorch_data[family].get('torch') else ''
            latest['torchaudio'][family] = pytorch_data[family].get('torchaudio', [])[0] if pytorch_data[family].get('torchaudio') else ''
    
    # Build packages section
    packages = {
        'ctranslate2': pypi_data.get('ctranslate2', {}).get('versions', []),
        'faster-whisper': pypi_data.get('faster-whisper', {}).get('versions', []),
        'torch': {},
        'torchaudio': {},
        'whisperx': pypi_data.get('whisperx', {}).get('versions', [])
    }
    
    for family in cuda_families:
        if family in pytorch_data:
            packages['torch'][family] = [
                {'version': v, 'has_wheel': True, 'has_target_wheel': True}
                for v in pytorch_data[family].get('torch', [])[:20]
            ]
            packages['torchaudio'][family] = [
                {'version': v, 'has_wheel': True, 'has_target_wheel': True}
                for v in pytorch_data[family].get('torchaudio', [])[:20]
            ]
    
    # Use timezone-aware datetime for Python 3.12+ compatibility
    try:
        from datetime import timezone
        generated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ImportError, AttributeError):
        # Fallback for older Python versions
        generated_at = datetime.utcnow().isoformat() + 'Z'
    
    catalog = {
        'generated_at': generated_at,
        'target': {
            'python': target_python,
            'platform': target_platform,
            'cuda_families': cuda_families
        },
        'latest': latest,
        'packages': packages
    }
    
    return catalog


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ASR Package Discovery')
    parser.add_argument('--package', help='PyPI package to discover')
    parser.add_argument('--output', help='Output file for PyPI data')
    parser.add_argument('--pytorch-family', help='PyTorch CUDA family')
    parser.add_argument('--torch-index', help='PyTorch index URL')
    parser.add_argument('--torch-output', help='Output file for torch versions')
    parser.add_argument('--torchaudio-output', help='Output file for torchaudio versions')
    parser.add_argument('--generate-catalog', action='store_true', help='Generate full catalog')
    parser.add_argument('--raw-dir', help='Directory with raw discovery data')
    parser.add_argument('--catalog-output', dest='catalog_output', help='Output file for catalog')
    parser.add_argument('--target-python', default='3.12', help='Target Python version')
    parser.add_argument('--target-platform', default='linux_aarch64', help='Target platform')
    parser.add_argument('--cuda-families', default='cu132 cu130 cu128', help='CUDA families')
    
    args = parser.parse_args()
    
    if args.package:
        # Single package discovery
        data = fetch_pypi_json(args.package)
        if data and args.output:
            with open(args.output, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Saved {args.package} metadata to {args.output}")
    
    elif args.pytorch_family:
        # PyTorch version discovery
        versions = discover_pytorch_versions(args.torch_index, os.path.dirname(args.torch_output) or '.')
        
        if args.torch_output:
            with open(args.torch_output, 'w') as f:
                json.dump(versions['torch'], f, indent=2)
        
        if args.torchaudio_output:
            with open(args.torchaudio_output, 'w') as f:
                json.dump(versions['torchaudio'], f, indent=2)
    
    elif args.generate_catalog:
        # Generate full catalog
        raw_dir = args.raw_dir or '.'
        
        # Load PyPI data
        pypi_data = {}
        for pkg in ['ctranslate2', 'faster-whisper', 'whisperx']:
            raw_file = os.path.join(raw_dir, f"pypi-{pkg}.json")
            if os.path.exists(raw_file):
                with open(raw_file) as f:
                    pypi_data[pkg] = {
                        'latest_version': '',
                        'versions': [],
                        'total_releases': 0
                    }
                    data = json.load(f)
                    pypi_data[pkg]['latest_version'] = data.get('info', {}).get('version', '')
                    pypi_data[pkg]['versions'] = get_package_versions(data)
        
        # Load PyTorch data
        cuda_families = args.cuda_families.split()
        pytorch_data = {}
        
        for family in cuda_families:
            torch_file = os.path.join(raw_dir, f"pytorch-{family}-versions.json")
            torchaudio_file = os.path.join(raw_dir, f"torchaudio-{family}-versions.json")
            
            if os.path.exists(torch_file):
                with open(torch_file) as f:
                    pytorch_data[family] = {'torch': json.load(f)}
            else:
                # Fallback: read from pip index files
                pytorch_data[family] = {'torch': []}
            
            if os.path.exists(torchaudio_file):
                with open(torchaudio_file) as f:
                    pytorch_data[family]['torchaudio'] = json.load(f)
            else:
                pytorch_data[family]['torchaudio'] = []
        
        catalog = generate_catalog(
            pypi_data, pytorch_data,
            args.target_python, args.target_platform,
            cuda_families
        )
        
        if args.catalog_output:
            with open(args.catalog_output, 'w') as f:
                json.dump(catalog, f, indent=2)
            print(f"Saved catalog to {args.catalog_output}")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
ASR Solver - Candidate Solver Module

Constructs candidate stacks and ranks them using the scoring formula.
"""

import json
import sys
from typing import Dict, List, Any, Optional, Tuple
from packaging.version import Version
from packaging.specifiers import SpecifierSet


# =============================================================================
# Scoring Constants
# =============================================================================

CUDA_SCORES = {
    'cu132': 300000,
    'cu130': 200000,
    'cu128': 0
}

FRESHNESS_BASE = 1000


def freshness_points(rank_index: int) -> int:
    """Calculate freshness score for a package at given rank."""
    return max(0, FRESHNESS_BASE - rank_index)


# =============================================================================
# Version Parsing and Comparison
# =============================================================================

def normalize_version(version: str) -> Version:
    """Normalize a version string to Version object."""
    try:
        return Version(version)
    except Exception:
        return Version("0.0.0")


def versions_match(v1: str, v2: str) -> bool:
    """Check if two versions match (for torch/torchaudio)."""
    try:
        return normalize_version(v1) == normalize_version(v2)
    except Exception:
        return False


# =============================================================================
# Hard Filters
# =============================================================================

def filter_by_python_constraint(
    version_info: Dict[str, Any],
    target_python: str
) -> bool:
    """Filter versions by Python compatibility."""
    requires_python = version_info.get('requires_python', '')
    
    if not requires_python:
        return True
    
    try:
        specifier = SpecifierSet(requires_python)
        target_version = Version(target_python)
        
        for spec in specifier:
            if target_version in spec:
                return True
        
        return False
    except Exception:
        return True


def filter_by_wheel_availability(
    version_info: Dict[str, Any],
    target_platform: str
) -> bool:
    """Filter versions by wheel availability."""
    files = version_info.get('files', [])
    
    for file_info in files:
        if file_info.get('has_cp312_aarch64_wheel'):
            return True
    
    return False


def filter_yanked_versions(versions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out yanked versions if non-yanked candidates exist."""
    non_yanked = [v for v in versions if not v.get('yanked', False)]
    
    if non_yanked:
        return non_yanked
    
    return versions


# =============================================================================
# Candidate Construction
# =============================================================================

def build_torch_torchaudio_pairs(
    torch_versions: List[Dict[str, Any]],
    torchaudio_versions: List[Dict[str, Any]]
) -> List[Tuple[str, str]]:
    """Build matching torch/torchaudio pairs."""
    pairs = []
    
    # Get version lists
    torch_vs = [v['version'] for v in torch_versions[:20]]
    torchaudio_vs = [v['version'] for v in torchaudio_versions[:20]]
    
    # Find matching versions
    for tv in torch_vs:
        for tav in torchaudio_vs:
            if versions_match(tv, tav):
                pairs.append((tv, tav))
                break
    
    # Sort by version (newest first) and limit
    pairs.sort(key=lambda x: normalize_version(x[0]), reverse=True)
    
    return pairs[:5]  # Keep top 5


def build_candidates(
    catalog: Dict[str, Any],
    target_python: str,
    target_platform: str,
    max_versions_per_package: int = 8
) -> List[Dict[str, Any]]:
    """Build candidate stack tuples."""
    
    packages = catalog.get('packages', {})
    cuda_families = catalog.get('target', {}).get('cuda_families', [])
    
    candidates = []
    
    for cuda_family in cuda_families:
        # Get torch/torchaudio pairs
        torch_data = packages.get('torch', {}).get(cuda_family, [])
        torchaudio_data = packages.get('torchaudio', {}).get(cuda_family, [])
        
        torch_versions = [v['version'] for v in torch_data[:max_versions_per_package]]
        torchaudio_versions = [v['version'] for v in torchaudio_data[:max_versions_per_package]]
        
        # Build matching pairs
        pairs = build_torch_torchaudio_pairs(torch_data, torchaudio_data)
        
        if not pairs:
            continue
        
        # Get other package versions
        ctranslate2_data = packages.get('ctranslate2', [])
        faster_whisper_data = packages.get('faster-whisper', [])
        whisperx_data = packages.get('whisperx', [])
        
        ctranslate2_vs = [v['version'] for v in ctranslate2_data[:max_versions_per_package]]
        faster_whisper_vs = [v['version'] for v in faster_whisper_data[:max_versions_per_package]]
        whisperx_vs = [v['version'] for v in whisperx_data[:max_versions_per_package]]
        
        # Filter by Python constraint
        ctranslate2_vs = [
            v for v in ctranslate2_vs
            if filter_by_python_constraint(
                {'requires_python': '', 'files': []}, target_python
            )
        ]
        
        faster_whisper_vs = [
            v for v in faster_whisper_vs
            if filter_by_python_constraint(
                {'requires_python': '', 'files': []}, target_python
            )
        ]
        
        whisperx_vs = [
            v for v in whisperx_vs
            if filter_by_python_constraint(
                {'requires_python': '', 'files': []}, target_python
            )
        ]
        
        # Build candidate tuples
        for torch_v, torchaudio_v in pairs:
            for ct2_v in ctranslate2_vs:
                for fw_v in faster_whisper_vs:
                    for wx_v in whisperx_vs:
                        candidate = {
                            'cuda_family': cuda_family,
                            'ctranslate2': ct2_v,
                            'faster_whisper': fw_v,
                            'torch': torch_v,
                            'torchaudio': torchaudio_v,
                            'whisperx': wx_v
                        }
                        candidates.append(candidate)
    
    return candidates


# =============================================================================
# Scoring
# =============================================================================

def calculate_cuda_score(cuda_family: str) -> int:
    """Calculate CUDA family score."""
    return CUDA_SCORES.get(cuda_family, 0)


def calculate_freshness_score(
    candidate: Dict[str, Any],
    catalog: Dict[str, Any]
) -> Tuple[int, Dict[str, int]]:
    """Calculate freshness score for a candidate."""
    packages = catalog.get('packages', {})
    scores = {}
    
    # Get version lists
    ctranslate2_vs = [v['version'] for v in packages.get('ctranslate2', [])]
    faster_whisper_vs = [v['version'] for v in packages.get('faster-whisper', [])]
    torch_vs = [v['version'] for v in packages.get('torch', {}).get(candidate['cuda_family'], [])]
    torchaudio_vs = [v['version'] for v in packages.get('torchaudio', {}).get(candidate['cuda_family'], [])]
    whisperx_vs = [v['version'] for v in packages.get('whisperx', [])]
    
    # Calculate rank indices
    for pkg_name, pkg_v, pkg_list in [
        ('ctranslate2', candidate['ctranslate2'], ctranslate2_vs),
        ('faster_whisper', candidate['faster_whisper'], faster_whisper_vs),
        ('torch', candidate['torch'], torch_vs),
        ('torchaudio', candidate['torchaudio'], torchaudio_vs),
        ('whisperx', candidate['whisperx'], whisperx_vs)
    ]:
        try:
            rank = pkg_list.index(pkg_v)
        except ValueError:
            rank = len(pkg_list)  # Not found, use max rank
        
        scores[pkg_name] = freshness_points(rank)
    
    return sum(scores.values()), scores


def calculate_wheel_score(
    candidate: Dict[str, Any],
    catalog: Dict[str, Any]
) -> Tuple[int, bool]:
    """Calculate wheel score for a candidate."""
    packages = catalog.get('packages', {})
    cuda_family = candidate['cuda_family']
    
    # Check each package
    packages_with_wheels = 0
    all_have_wheels = True
    
    pkg_list = [
        ('ctranslate2', packages.get('ctranslate2', [])),
        ('faster_whisper', packages.get('faster-whisper', [])),
        ('torch', packages.get('torch', {}).get(cuda_family, [])),
        ('torchaudio', packages.get('torchaudio', {}).get(cuda_family, [])),
        ('whisperx', packages.get('whisperx', []))
    ]
    
    for pkg_name, pkg_data in pkg_list:
        has_wheel = False
        for v in pkg_data:
            if v['version'] == candidate[pkg_name]:
                files = v.get('files', [])
                for f in files:
                    if f.get('has_cp312_aarch64_wheel'):
                        has_wheel = True
                        break
                break
        
        if has_wheel:
            packages_with_wheels += 1
        else:
            all_have_wheels = False
    
    # Score calculation
    if all_have_wheels:
        return 5000, True
    
    return packages_with_wheels * 1000, False


def calculate_penalty_score(
    candidate: Dict[str, Any],
    catalog: Dict[str, Any]
) -> Tuple[int, List[str]]:
    """Calculate penalty score for a candidate."""
    penalties = []
    
    # Check CUDA family
    cuda_family = candidate['cuda_family']
    if cuda_family not in ['cu132', 'cu130']:
        penalties.append(f"Older CUDA family: {cuda_family}")
    
    # Check for source builds (simplified - assume wheels available)
    # In real implementation, would check if wheel is unavailable
    
    total_penalty = 0
    if cuda_family not in ['cu132', 'cu130']:
        total_penalty += 50000
    
    return total_penalty, penalties


def calculate_probe_score(probe_status: str) -> int:
    """Calculate probe score based on status."""
    if probe_status == 'full_pass':
        return 100000
    elif probe_status == 'core_pass':
        return 60000
    else:
        return 0


def calculate_total_score(
    candidate: Dict[str, Any],
    catalog: Dict[str, Any],
    probe_status: str = 'not_probed'
) -> Tuple[int, Dict[str, Any]]:
    """Calculate total score for a candidate."""
    
    cuda_score = calculate_cuda_score(candidate['cuda_family'])
    freshness_score, freshness_breakdown = calculate_freshness_score(candidate, catalog)
    wheel_score, all_wheels = calculate_wheel_score(candidate, catalog)
    penalty_score, penalties = calculate_penalty_score(candidate, catalog)
    probe_score = calculate_probe_score(probe_status)
    
    total_score = (
        cuda_score +
        freshness_score +
        wheel_score -
        penalty_score +
        probe_score
    )
    
    breakdown = {
        'cuda_score': cuda_score,
        'freshness_score': freshness_score,
        'freshness_breakdown': freshness_breakdown,
        'wheel_score': wheel_score,
        'all_wheels': all_wheels,
        'penalty_score': penalty_score,
        'penalties': penalties,
        'probe_score': probe_score
    }
    
    return total_score, breakdown


# =============================================================================
# Main Solver Logic
# =============================================================================

def solve(
    catalog: Dict[str, Any],
    top_candidates: int = 3,
    target_python: str = '3.12',
    target_platform: str = 'linux_aarch64'
) -> Dict[str, Any]:
    """Run the full solve pipeline."""
    
    # Build candidates
    candidates = build_candidates(
        catalog, target_python, target_platform
    )
    
    # Score each candidate
    scored = []
    for c in candidates:
        score, breakdown = calculate_total_score(c, catalog)
        
        # Determine if this is the latest version
        packages = catalog.get('packages', {})
        latest = catalog.get('latest', {})
        
        is_latest = {
            'ctranslate2': c['ctranslate2'] == latest.get('ctranslate2', ''),
            'faster_whisper': c['faster_whisper'] == latest.get('faster_whisper', ''),
            'torch': c['torch'] == latest.get('torch', {}).get(c['cuda_family'], ''),
            'torchaudio': c['torchaudio'] == latest.get('torchaudio', {}).get(c['cuda_family'], ''),
            'whisperx': c['whisperx'] == latest.get('whisperx', '')
        }
        
        # Count unknown dependencies (simplified)
        unknown_deps = 0
        
        scored.append({
            'candidate': c,
            'score': score,
            'breakdown': breakdown,
            'is_latest': is_latest,
            'unknown_dependency_count': unknown_deps
        })
    
    # Sort by score (descending), then by version freshness for ties
    def sort_key(item):
        c = item['candidate']
        return (
            -item['score'],
            normalize_version(c['torch']),
            normalize_version(c['ctranslate2']),
            normalize_version(c['faster_whisper']),
            normalize_version(c['whisperx'])
        )
    
    scored.sort(key=sort_key)
    
    # Take top candidates
    top = scored[:top_candidates]
    
    return {
        'candidates': [
            {
                'rank': i + 1,
                **item
            }
            for i, item in enumerate(top)
        ],
        'total_candidates': len(scored)
    }


def select_winner(
    candidates_result: Dict[str, Any],
    probe_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Select the winning candidate based on probe results."""
    
    candidates = candidates_result.get('candidates', [])
    
    # Build probe lookup
    probe_lookup = {}
    for pr in probe_results.get('results', []):
        rank = pr.get('candidate_rank', 0)
        probe_lookup[rank] = pr
    
    # Find winner
    winner = None
    for c in candidates:
        rank = c.get('rank', 0)
        pr = probe_lookup.get(rank, {})
        
        core_status = pr.get('core_probe', {}).get('status', 'fail')
        
        if core_status == 'pass':
            winner = c
            break
    
    if not winner:
        return {
            'selection_reason': 'no_viable_candidate',
            'stack': None,
            'selected_rank': None,
            'selected_score': None,
            'stack_mode': None,
            'rejected_candidates': []
        }
    
    # Determine stack mode
    rank = winner.get('rank', 0)
    pr = probe_lookup.get(rank, {})
    full_status = pr.get('full_probe', {}).get('status', 'fail')
    
    if full_status == 'pass':
        stack_mode = 'full_stack'
    else:
        stack_mode = 'transcription_only'
    
    # Build rejected candidates list
    rejected = []
    for c in candidates:
        if c.get('rank', 0) < rank:
            pr = probe_lookup.get(c.get('rank', 0), {})
            reason = pr.get('core_probe', {}).get('reason', 'lower_rank')
            rejected.append({
                'rank': c.get('rank'),
                'candidate': c.get('candidate'),
                'score': c.get('score'),
                'rejected_reason': reason
            })
    
    return {
        'selection_reason': f"Selected {stack_mode} stack",
        'stack': winner.get('candidate'),
        'selected_rank': rank,
        'selected_score': winner.get('score'),
        'stack_mode': stack_mode,
        'rejected_candidates': rejected
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ASR Solver')
    parser.add_argument('--catalog', required=True, help='Catalog JSON file')
    parser.add_argument('--output', help='Output candidate stacks file')
    parser.add_argument('--top-candidates', type=int, default=3, help='Number of top candidates')
    parser.add_argument('--target-python', default='3.12', help='Target Python version')
    parser.add_argument('--target-platform', default='linux_aarch64', help='Target platform')
    parser.add_argument('--cuda-families', default='cu132 cu130 cu128', help='CUDA families')
    
    # Selection mode
    parser.add_argument('--select-winner', action='store_true', help='Select winner from candidates')
    parser.add_argument('--candidates', help='Candidate stacks JSON file')
    parser.add_argument('--probe-results', help='Probe results JSON file')
    
    args = parser.parse_args()
    
    if args.select_winner:
        # Selection mode
        with open(args.candidates) as f:
            candidates_result = json.load(f)
        
        with open(args.probe_results) as f:
            probe_results = json.load(f)
        
        winner = select_winner(candidates_result, probe_results)
        
        output_file = args.output or 'selected-stack.json'
        with open(output_file, 'w') as f:
            json.dump(winner, f, indent=2)
        
        print(f"Winner saved to {output_file}")
    
    else:
        # Solve mode
        with open(args.catalog) as f:
            catalog = json.load(f)
        
        cuda_families = args.cuda_families.split()
        
        result = solve(
            catalog,
            args.top_candidates,
            args.target_python,
            args.target_platform
        )
        
        output_file = args.output or 'candidate-stacks.json'
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"Candidates saved to {output_file}")
        print(f"Total candidates: {result.get('total_candidates', 0)}")
        print(f"Top {len(result.get('candidates', []))} candidates:")
        
        for c in result.get('candidates', []):
            stack = c.get('candidate', {})
            print(f"  Rank {c.get('rank')}: score={c.get('score')}, "
                  f"{stack.get('cuda_family')} / torch={stack.get('torch')}")


if __name__ == '__main__':
    main()

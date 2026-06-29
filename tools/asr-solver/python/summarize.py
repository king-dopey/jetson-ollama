#!/usr/bin/env python3
"""
ASR Solver - Report and Tech Debt Generation Module

Generates human-readable reports and tech debt artifacts.
"""

import json
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional


def generate_report(
    catalog: Dict[str, Any],
    candidates_result: Dict[str, Any],
    probe_results: Dict[str, Any],
    selected: Dict[str, Any]
) -> str:
    """Generate the full report markdown."""
    
    lines = []
    
    # Header
    lines.append("# ASR Solver Report")
    lines.append("")
    try:
        from datetime import timezone
        generated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ImportError, AttributeError):
        generated_at = datetime.utcnow().isoformat() + 'Z'
    lines.append(f"Generated: {generated_at}")
    lines.append("")
    
    # Environment Summary
    lines.append("## Environment Summary")
    lines.append("")
    target = catalog.get('target', {})
    lines.append(f"- **Target Python**: {target.get('python', 'N/A')}")
    lines.append(f"- **Target Platform**: {target.get('platform', 'N/A')}")
    lines.append(f"- **CUDA Families**: {', '.join(target.get('cuda_families', []))}")
    lines.append("")
    
    # Discovery Summary
    lines.append("## Discovery Summary")
    lines.append("")
    packages = catalog.get('packages', {})
    lines.append(f"- **Packages Discovered**: {len(packages)}")
    for pkg_name, pkg_data in packages.items():
        if isinstance(pkg_data, list):
            lines.append(f"  - {pkg_name}: {len(pkg_data)} versions")
        elif isinstance(pkg_data, dict):
            for cuda_family, versions in pkg_data.items():
                lines.append(f"  - {pkg_name} ({cuda_family}): {len(versions)} versions")
    lines.append("")
    
    # Latest Versions
    lines.append("## Latest Versions Discovered")
    lines.append("")
    latest = catalog.get('latest', {})
    lines.append(f"- **ctranslate2**: {latest.get('ctranslate2', 'N/A')}")
    lines.append(f"- **faster-whisper**: {latest.get('faster-whisper', latest.get('faster_whisper', 'N/A'))}")
    lines.append(f"- **whisperx**: {latest.get('whisperx', 'N/A')}")
    lines.append("")
    lines.append("### PyTorch Latest Versions by CUDA Family")
    lines.append("")
    torch_latest = latest.get('torch', {})
    torchaudio_latest = latest.get('torchaudio', {})
    
    for cuda_family in target.get('cuda_families', []):
        lines.append(f"- **{cuda_family}**:")
        lines.append(f"  - torch: {torch_latest.get(cuda_family, 'N/A')}")
        lines.append(f"  - torchaudio: {torchaudio_latest.get(cuda_family, 'N/A')}")
    lines.append("")
    
    # Candidate Ranking Table
    lines.append("## Candidate Ranking Table")
    lines.append("")
    lines.append("| Rank | Score | CUDA Family | ctranslate2 | faster-whisper | torch | torchaudio | whisperx | Latest | Wheels | Unknown Deps |")
    lines.append("|------|-------|-------------|-------------|----------------|-------|------------|----------|--------|--------|--------------|")
    
    for c in candidates_result.get('candidates', []):
        stack = c.get('candidate', {})
        breakdown = c.get('breakdown', {})
        
        is_latest_all = all(c.get('is_latest', {}).values())
        latest_str = "Yes" if is_latest_all else "No"
        
        all_wheels = breakdown.get('all_wheels', False)
        wheels_str = "All" if all_wheels else "Partial"
        
        unknown_deps = c.get('unknown_dependency_count', 0)
        
        lines.append(
            f"| {c.get('rank', 'N/A')} | {c.get('score', 'N/A')} | "
            f"{stack.get('cuda_family', 'N/A')} | "
            f"{stack.get('ctranslate2', 'N/A')} | "
            f"{stack.get('faster_whisper', 'N/A')} | "
            f"{stack.get('torch', 'N/A')} | "
            f"{stack.get('torchaudio', 'N/A')} | "
            f"{stack.get('whisperx', 'N/A')} | "
            f"{latest_str} | {wheels_str} | {unknown_deps} |"
        )
    lines.append("")
    
    # Probe Results Table
    lines.append("## Probe Results Table")
    lines.append("")
    lines.append("| Rank | Core Probe | Full Probe | Main Failure | Log Path |")
    lines.append("|------|------------|------------|--------------|----------|")
    
    probe_lookup = {}
    for pr in probe_results.get('results', []):
        rank = pr.get('candidate_rank', 0)
        probe_lookup[rank] = pr
    
    for c in candidates_result.get('candidates', []):
        rank = c.get('rank', 0)
        pr = probe_lookup.get(rank, {})
        
        core_status = pr.get('core_probe', {}).get('status', pr.get('status', 'N/A'))
        full_status = pr.get('full_probe', {}).get('status', pr.get('status', 'N/A'))
        main_failure = pr.get('core_probe', {}).get('reason', pr.get('reason', 'N/A'))
        
        # Construct log path from rank since probe.sh doesn't store it
        log_path = f"logs/core-rank{rank}.log, logs/full-rank{rank}.log"
        
        lines.append(
            f"| {rank} | {core_status} | {full_status} | "
            f"{main_failure} | {log_path} |"
        )
    lines.append("")
    
    # Selected Winner
    lines.append("## Selected Winner")
    lines.append("")
    
    stack = selected.get('stack')
    if stack:
        lines.append(f"- **CUDA Family**: {stack.get('cuda_family', 'N/A')}")
        lines.append(f"- **ctranslate2**: {stack.get('ctranslate2', 'N/A')}")
        lines.append(f"- **faster-whisper**: {stack.get('faster_whisper', 'N/A')}")
        lines.append(f"- **torch**: {stack.get('torch', 'N/A')}")
        lines.append(f"- **torchaudio**: {stack.get('torchaudio', 'N/A')}")
        lines.append(f"- **whisperx**: {stack.get('whisperx', 'N/A')}")
        lines.append("")
        lines.append(f"- **Selected Rank**: {selected.get('selected_rank', 'N/A')}")
        lines.append(f"- **Selected Score**: {selected.get('selected_score', 'N/A')}")
        lines.append(f"- **Stack Mode**: {selected.get('stack_mode', 'N/A')}")
        lines.append("")
        lines.append(f"**Selection Reason**: {selected.get('selection_reason', 'N/A')}")
    else:
        lines.append("No viable candidate was selected.")
    lines.append("")
    
    # Rejected Candidates
    lines.append("## Rejected Newer Candidates and Reasons")
    lines.append("")
    
    rejected = selected.get('rejected_candidates', [])
    if rejected:
        for r in rejected:
            stack = r.get('candidate', {})
            lines.append(f"- **Rank {r.get('rank')}**: {stack.get('cuda_family', 'N/A')} / torch={stack.get('torch', 'N/A')}")
            lines.append(f"  - Score: {r.get('score', 'N/A')}")
            lines.append(f"  - Rejected Reason: {r.get('rejected_reason', 'N/A')}")
    else:
        lines.append("No candidates were rejected (only one candidate was evaluated).")
    lines.append("")
    
    # Tech Debt Section
    lines.append("## Tech Debt")
    lines.append("")
    lines.append("See `tech-debt.md` for detailed tech debt information.")
    lines.append("")
    
    # Recommended Next Step
    lines.append("## Recommended Next Implementation Step")
    lines.append("")
    lines.append("1. Review the selected stack in `selected-stack.env`")
    lines.append("2. Update your ASR service Dockerfile to use these versions")
    lines.append("3. Run integration tests with the selected stack")
    lines.append("4. Monitor for newer versions and update tech debt as needed")
    
    return '\n'.join(lines)


def generate_tech_debt(
    catalog: Dict[str, Any],
    selected: Dict[str, Any]
) -> tuple:
    """Generate tech debt markdown and JSON."""
    
    debt_entries = []
    
    stack = selected.get('stack')
    if not stack:
        return "No ASR dependency tech debt introduced", {"debt_entries": []}
    
    latest = catalog.get('latest', {})
    packages = catalog.get('packages', {})
    
    # Check each package
    for pkg_name in ['ctranslate2', 'faster_whisper', 'whisperx']:
        chosen = stack.get(pkg_name)
        latest_v = latest.get(pkg_name)
        
        if chosen and latest_v and chosen != latest_v:
            debt_entries.append({
                'package': pkg_name,
                'chosen_version': chosen,
                'latest_version': latest_v,
                'reason': f"Selected {chosen} instead of latest {latest_v} due to compatibility constraints",
                'risk': 'medium',
                'removal_trigger': f"Update when {latest_v} is verified compatible",
                'suggested_follow_up': f"Test with {latest_v} and update if compatible"
            })
    
    # Check CUDA family
    cuda_family = stack.get('cuda_family')
    if cuda_family != 'cu132':
        latest_cuda = latest.get('torch', {}).get('cu132', '')
        if latest_cuda:
            debt_entries.append({
                'package': 'cuda',
                'chosen_version': cuda_family,
                'latest_version': 'cu132',
                'reason': f"Selected {cuda_family} instead of cu132 due to compatibility constraints",
                'risk': 'high',
                'removal_trigger': "Update when cu132 is verified compatible",
                'suggested_follow_up': "Test with cu132 and update if compatible"
            })
    
    # Generate markdown
    lines = []
    lines.append("# ASR Dependency Tech Debt")
    lines.append("")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    
    if not debt_entries:
        lines.append("## No ASR dependency tech debt introduced")
        lines.append("")
        lines.append("The selected stack uses the latest available versions for all packages.")
    else:
        lines.append("## Debt Entries")
        lines.append("")
        
        for i, entry in enumerate(debt_entries, 1):
            lines.append(f"### {i}. {entry['package']}")
            lines.append("")
            lines.append(f"- **Chosen Version**: {entry['chosen_version']}")
            lines.append(f"- **Latest Version**: {entry['latest_version']}")
            lines.append(f"- **Reason**: {entry['reason']}")
            lines.append(f"- **Risk Level**: {entry['risk']}")
            lines.append(f"- **Removal Trigger**: {entry['removal_trigger']}")
            lines.append(f"- **Suggested Follow-up**: {entry['suggested_follow_up']}")
            lines.append("")
        
        lines.append("## Summary")
        lines.append("")
        lines.append(f"Total debt entries: {len(debt_entries)}")
    
    markdown = '\n'.join(lines)
    json_data = {'generated_at': datetime.utcnow().isoformat() + 'Z', 'debt_entries': debt_entries}
    
    return markdown, json_data


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ASR Report Generator')
    parser.add_argument('--catalog', required=True, help='Catalog JSON file')
    parser.add_argument('--candidates', required=True, help='Candidate stacks JSON file')
    parser.add_argument('--probe-results', required=True, help='Probe results JSON file')
    parser.add_argument('--selected', required=True, help='Selected stack JSON file')
    parser.add_argument('--output', help='Output report markdown file')
    
    # Tech debt mode
    parser.add_argument('--generate-debt', action='store_true', help='Generate tech debt')
    parser.add_argument('--output-md', help='Output tech debt markdown file')
    parser.add_argument('--output-json', help='Output tech debt JSON file')
    
    args = parser.parse_args()
    
    if args.generate_debt:
        # Tech debt mode
        with open(args.catalog) as f:
            catalog = json.load(f)
        
        with open(args.selected) as f:
            selected = json.load(f)
        
        markdown, json_data = generate_tech_debt(catalog, selected)
        
        if args.output_md:
            with open(args.output_md, 'w') as f:
                f.write(markdown)
        
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump(json_data, f, indent=2)
        
        print(f"Tech debt generated")
    
    else:
        # Report mode
        with open(args.catalog) as f:
            catalog = json.load(f)
        
        with open(args.candidates) as f:
            candidates_result = json.load(f)
        
        with open(args.probe_results) as f:
            probe_results = json.load(f)
        
        with open(args.selected) as f:
            selected = json.load(f)
        
        report = generate_report(catalog, candidates_result, probe_results, selected)
        
        output_file = args.output or 'report.md'
        with open(output_file, 'w') as f:
            f.write(report)
        
        print(f"Report saved to {output_file}")


if __name__ == '__main__':
    main()

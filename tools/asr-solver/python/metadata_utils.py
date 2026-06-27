#!/usr/bin/env python3
"""
ASR Solver - Metadata Utilities

Extracts and parses package metadata from wheels.
"""

import os
import re
import zipfile
from typing import Dict, List, Optional, Tuple
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion


def extract_metadata_from_wheel(wheel_path: str) -> Optional[Dict[str, Any]]:
    """Extract METADATA from a wheel file."""
    try:
        with zipfile.ZipFile(wheel_path, 'r') as zf:
            # Find METADATA file
            metadata_files = [f for f in zf.namelist() if f.endswith('.dist-info/METADATA')]
            
            if not metadata_files:
                return None
            
            with zf.open(metadata_files[0]) as f:
                content = f.read().decode('utf-8')
                return parse_metadata(content)
    
    except Exception as e:
        print(f"Error extracting metadata from {wheel_path}: {e}", file=sys.stderr)
        return None


def parse_metadata(content: str) -> Dict[str, Any]:
    """Parse METADATA content."""
    result = {
        'requires_dist': [],
        'requires_python': '',
        'version': ''
    }
    
    for line in content.split('\n'):
        line = line.strip()
        
        if line.startswith('Requires-Dist:'):
            dep = line[len('Requires-Dist:'):].strip()
            result['requires_dist'].append(dep)
        
        elif line.startswith('Requires-Python:'):
            result['requires_python'] = line[len('Requires-Python:'):].strip()
        
        elif line.startswith('Version:'):
            result['version'] = line[len('Version:'):].strip()
    
    return result


def parse_dependency_spec(spec: str) -> Optional[Requirement]:
    """Parse a dependency specification string."""
    try:
        return Requirement(spec)
    except Exception:
        return None


def check_python_compatibility(requires_python: str, target_python: str) -> bool:
    """Check if target Python version is compatible."""
    if not requires_python:
        return True
    
    try:
        specifier = SpecifierSet(requires_python)
        target_version = Version(target_python)
        
        # Check each version in the specifier
        for spec in specifier:
            if target_version in spec:
                return True
        
        return False
    
    except (InvalidSpecifier, InvalidVersion):
        return True  # If we can't parse, assume compatible


def check_dependency_satisfied(
    requirement: Requirement,
    installed_versions: Dict[str, str]
) -> Tuple[bool, Optional[str]]:
    """Check if a dependency requirement is satisfied."""
    package_name = requirement.name.lower()
    
    if package_name not in installed_versions:
        return False, "package_not_installed"
    
    installed_version = installed_versions[package_name]
    
    try:
        version = Version(installed_version)
        
        for spec in requirement.specifier:
            if version not in spec:
                return False, f"version_{spec}"
        
        return True, None
    
    except InvalidVersion:
        return False, "invalid_version"


def extract_dependency_constraints(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract dependency constraints from metadata."""
    constraints = []
    
    for req_str in metadata.get('requires_dist', []):
        req = parse_dependency_spec(req_str)
        
        if req:
            constraint = {
                'package': req.name,
                'specifier': str(req.specifier) if req.specifier else '*',
                'extras': list(req.extras) if req.extras else [],
                'marker': str(req.marker) if req.marker else None
            }
            constraints.append(constraint)
    
    return constraints


def get_wheel_tags(wheel_path: str) -> List[str]:
    """Extract wheel tags from a wheel filename."""
    import re
    
    filename = os.path.basename(wheel_path)
    
    # Pattern for wheel filenames
    pattern = r'^[a-zA-Z0-9_-]+-[0-9.]+(?:-[0-9]+)?(-[a-zA-Z0-9_.]+)*-([a-zA-Z0-9_.]+)-([a-zA-Z0-9_.]+)-([a-zA-Z0-9_.]+)\.whl$'
    match = re.match(pattern, filename)
    
    if not match:
        return []
    
    # Extract tags
    tags = []
    python_tag = match.group(2)
    abi_tag = match.group(3)
    platform_tag = match.group(4)
    
    if python_tag:
        tags.append(python_tag)
    if abi_tag:
        tags.append(abi_tag)
    if platform_tag:
        tags.append(platform_tag)
    
    return tags


def has_aarch64_compatible_wheel(tags: List[str]) -> bool:
    """Check if wheel is compatible with aarch64."""
    for tag in tags:
        if 'aarch64' in tag.lower() or 'arm64' in tag.lower():
            return True
    return False


def has_cp312_compatible_wheel(tags: List[str]) -> bool:
    """Check if wheel is compatible with Python 3.12."""
    for tag in tags:
        if 'cp312' in tag.lower() or 'py312' in tag.lower():
            return True
    return False

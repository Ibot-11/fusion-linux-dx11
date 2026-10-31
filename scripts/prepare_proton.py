#!/usr/bin/env python3
"""Use an installed Proton-Fusion, or build it in a permanent sibling checkout."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import fusion_runtime
import proton


def ensure(repo):
    try:
        return fusion_runtime.select()['path']
    except ValueError:
        pass
    config = json.loads((repo / 'config/proton-fusion.json').read_text())
    source = repo.parent / 'Proton-Fusion'
    if not source.exists():
        subprocess.run(['git', 'clone', '--depth=1', '--branch', config['branch'],
                        '--', config['repository'], str(source)], check=True, stdout=sys.stderr)
    if not (source / 'fusion/scripts/install-local.py').is_file():
        raise ValueError(f'Update the Proton-Fusion source checkout at {source} before building the runtime.')
    base = proton.find('Proton - Experimental')
    if not base:
        raise ValueError('The initial local build needs the matching official Proton Experimental installed in Steam, or an already built Proton-Fusion runtime.')
    commands = [
        ['git', '-C', source, 'submodule', 'update', '--init', '--depth=1', 'wine', 'dxvk'],
        ['bash', source/'fusion/scripts/build-native-modules.sh', source/'.build/native'],
        ['bash', source/'fusion/scripts/build-pe-modules.sh', source/'.build/pe'],
        [sys.executable, source/'fusion/scripts/install-local.py', '--base', base,
         '--unix-build', source/'.build/native', '--pe-build', source/'.build/pe'],
    ]
    for command in commands:
        subprocess.run([str(part) for part in command], check=True, stdout=sys.stderr)
    return fusion_runtime.select()['path']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    args = parser.parse_args()
    try:
        print(ensure(args.repo.resolve()))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')

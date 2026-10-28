#!/usr/bin/env python3
"""Locate Steam and installed Proton versions using only the standard library."""
import argparse
import os
from pathlib import Path
import re

STEAM_ROOTS = (
    '.local/share/Steam',
    '.steam/root',
    '.steam/steam',
    '.var/app/com.valvesoftware.Steam/.local/share/Steam',
)


def read(path):
    try:
        return path.read_text()
    except OSError:
        return ''


def steam_roots():
    return [Path.home() / relative for relative in STEAM_ROOTS]


def steam_root():
    return next((root for root in steam_roots() if root.is_dir()), None)


def search_roots():
    roots = steam_roots()
    folders = list(roots)
    for root in roots:
        text = read(root / 'steamapps/libraryfolders.vdf')
        folders += [Path(value.replace('\\\\', '\\'))
                    for value in re.findall(r'"path"\s+"([^"]+)"', text)]
    search = [folder / subfolder for folder in folders
              for subfolder in ('compatibilitytools.d', 'steamapps/common')]
    search.append(Path('/usr/share/steam/compatibilitytools.d'))
    return search


def installed():
    versions = {}
    for root in search_roots():
        try:
            for folder in root.iterdir():
                if (folder / 'proton').is_file():
                    path = str(folder.resolve())
                    versions[path] = {'name': folder.name, 'path': path}
        except OSError:
            pass
    return sorted(versions.values(), key=lambda item: item['name'].lower())


def find(name, custom=None):
    if custom:
        path = Path(custom).expanduser()
        if (path / 'proton').is_file():
            return path.resolve()
    return next((Path(item['path']) for item in installed() if item['name'] == name), None)


def natural_key(value):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', value)]


def find_ge():
    versions = [item for item in installed() if item['name'].startswith('GE-Proton')]
    return Path(max(versions, key=lambda item: natural_key(item['name']))['path']) if versions else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('steam')
    find_parser = subparsers.add_parser('find')
    find_parser.add_argument('name')
    find_parser.add_argument('custom', nargs='?', default=os.environ.get('FUSION_PROTON_PATH'))
    subparsers.add_parser('find-ge')
    args = parser.parse_args()
    if args.command == 'steam':
        result = steam_root()
    elif args.command == 'find':
        result = find(args.name, args.custom)
    else:
        result = find_ge()
    if result is None:
        return 1
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

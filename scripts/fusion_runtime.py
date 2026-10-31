#!/usr/bin/env python3
"""Resolve and pin a verified Proton-Fusion build; never fall back to stock Proton."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

FEATURES = ('child_damage', 'managed_qt_panels', 'bcp47_user_languages', 'profile_defaults')
PAYLOAD = ('proton', 'fusion/__init__.py', 'fusion/profile.py', 'fusion/dxvk.conf',
           'files/lib/wine/x86_64-unix/win32u.so',
           'files/lib/wine/x86_64-unix/winex11.so',
           'files/lib/wine/x86_64-windows/bcp47langs.dll')


def default_path():
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'fusion-linux-dx11/runtimes/Proton-Fusion/current'


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fusion-runtime-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(text)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate(path):
    path = Path(path).expanduser().resolve()
    try:
        raw = (path / 'fusion-runtime.json').read_bytes()
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or manifest.get('runtime') != 'Proton-Fusion' or
                not isinstance(manifest.get('build_id'), str) or not manifest['build_id'] or
                not isinstance(manifest.get('features'), dict) or
                not all(manifest.get('features', {}).get(feature) == 1 for feature in FEATURES)):
            raise ValueError('Unsupported Proton-Fusion runtime manifest.')
        files = manifest.get('files', {})
        if not isinstance(files, dict):
            raise ValueError('Invalid Proton-Fusion file manifest.')
        for name in PAYLOAD:
            file = path / name
            if not file.resolve().is_relative_to(path) or not file.is_file():
                raise ValueError(f'Proton-Fusion runtime file is missing: {name}')
            if hashlib.sha256(file.read_bytes()).hexdigest() != files.get(name):
                raise ValueError(f'Proton-Fusion runtime file failed verification: {name}')
        if not os.access(path / 'proton', os.X_OK):
            raise ValueError('The Proton-Fusion launcher is not executable.')
        return {**manifest, 'path': str(path), 'manifest_sha256': hashlib.sha256(raw).hexdigest()}
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f'Proton-Fusion is missing or invalid at {path}. Install the managed Proton-Fusion runtime first.') from error


def installed():
    import proton
    paths = [default_path(), *(Path(item['path']) for item in proton.installed())]
    versions = {}
    for path in paths:
        try:
            runtime = validate(path)
            versions[runtime['path']] = {'name': 'Proton-Fusion · ' + runtime['build_id'],
                                         'path': runtime['path'], 'build_id': runtime['build_id']}
        except ValueError:
            continue
    return list(versions.values())


def select(candidate=None):
    if candidate:
        return validate(candidate)
    try:
        return validate(default_path())
    except ValueError:
        versions = installed()
        if versions:
            return validate(versions[0]['path'])
        raise ValueError('Proton-Fusion is not installed. Build/install Proton-Fusion before setting up Fusion.')


def resolve(app):
    app = Path(app)
    try:
        lock = json.loads((app / 'runtime-lock.json').read_text())
        if not isinstance(lock, dict):
            raise ValueError('Invalid Proton-Fusion runtime lock.')
        saved = (app / 'proton-path').read_text().strip()
        runtime = validate(saved)
        if (lock.get('schema') != 1 or runtime['path'] != lock.get('path') or
                runtime['build_id'] != lock.get('build_id') or
                runtime['manifest_sha256'] != lock.get('manifest_sha256')):
            raise ValueError('The pinned Proton-Fusion build changed. Apply the integration update before launching.')
        return runtime
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise ValueError('The Proton-Fusion runtime selection is missing. Apply the integration update in Fusion Manager.') from error


def bind(app, candidate=None):
    app = Path(app)
    runtime = select(candidate)
    atomic(app / 'proton-version', 'Proton-Fusion\n')
    atomic(app / 'proton-path', runtime['path'] + '\n')
    lock = {key: runtime[key] for key in ('path', 'build_id', 'manifest_sha256')}
    atomic(app / 'runtime-lock.json', json.dumps({'schema': 1, **lock}, indent=2) + '\n')
    return runtime


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('resolve', 'select', 'validate', 'bind'))
    parser.add_argument('path', nargs='?')
    parser.add_argument('runtime', nargs='?')
    args = parser.parse_args()
    try:
        if args.command == 'resolve':
            print(resolve(args.path)['path'])
        elif args.command == 'select':
            print(select(args.path)['path'])
        elif args.command == 'bind':
            print(bind(args.path, args.runtime)['path'])
        else:
            print(json.dumps(validate(args.path), indent=2))
    except ValueError as error:
        parser.exit(1, str(error) + '\n')

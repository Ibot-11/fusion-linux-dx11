"""Small verified runtime fixture for installer/launcher contract tests."""
import hashlib
import json
from pathlib import Path


def make_runtime(path):
    path = Path(path)
    payload = ('proton', 'fusion/__init__.py', 'fusion/profile.py', 'fusion/dxvk.conf',
               'files/lib/wine/x86_64-unix/win32u.so', 'files/lib/wine/x86_64-unix/winex11.so',
               'files/lib/wine/x86_64-windows/bcp47langs.dll')
    for name in payload:
        file = path/name
        file.parent.mkdir(parents=True, exist_ok=True)
        if not file.exists() or not file.stat().st_size:
            file.write_text('#!/bin/sh\nexit 0\n' if name == 'proton' else 'runtime fixture\n')
    (path/'proton').chmod(0o755)
    manifest = dict(schema=1, runtime='Proton-Fusion', build_id='test-build',
                    features=dict(child_damage=1, managed_qt_panels=1, bcp47_user_languages=1, profile_defaults=1),
                    files={name: hashlib.sha256((path/name).read_bytes()).hexdigest() for name in payload})
    (path/'fusion-runtime.json').write_text(json.dumps(manifest))
    return path

#!/usr/bin/env python3
import os, pathlib, subprocess, sys, urllib.parse
if len(sys.argv) != 2 or urllib.parse.urlsplit(sys.argv[1]).scheme not in ('adsk', 'adskidmgr'):
    sys.exit(1)
app = pathlib.Path(os.environ.get('FUSION_APP_DIR', str(pathlib.Path(__file__).resolve().parent)))
prefix_dir = (app/'prefix-dir').read_text().strip() if (app/'prefix-dir').exists() else 'compatdata'
if urllib.parse.urlsplit(sys.argv[1]).scheme == 'adsk':
    sys.exit(subprocess.call([str(app/'launch.sh'), sys.argv[1]]))
production = app/prefix_dir/'pfx/drive_c/Program Files/Autodesk/webdeploy/production'
candidates = list(production.rglob('AdskIdentityManager.exe'))
if not candidates:
    candidates = list((app/prefix_dir/'pfx/drive_c').rglob('AdskIdentityManager.exe'))
if not candidates:
    sys.exit('Autodesk Identity Manager is missing.')
exe = max(candidates, key=lambda path: path.stat().st_mtime)
with (app/'logs/callback.log').open('a') as log:
    sys.exit(subprocess.call([str(app/'run-proton.sh'), str(exe), sys.argv[1]], stdout=log, stderr=log))

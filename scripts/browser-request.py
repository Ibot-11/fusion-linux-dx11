#!/usr/bin/env python3
import os, pathlib, sys, tempfile, urllib.parse
if len(sys.argv) < 2:
    sys.exit(0)
url = sys.argv[1]
if urllib.parse.urlsplit(url).scheme not in ('https', 'http'):
    sys.exit(1)
queue = pathlib.Path('/run/user') / str(os.getuid()) / 'autodesk-fusion-browser'
queue.mkdir(mode=0o700, exist_ok=True)
fd, name = tempfile.mkstemp(dir=queue, suffix='.partial')
with os.fdopen(fd, 'w') as stream:
    stream.write(url)
os.rename(name, name.removesuffix('.partial') + '.request')

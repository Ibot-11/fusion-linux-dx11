#!/usr/bin/env python3
"""Enable, disable or inspect the Fusion SpaceMouse integration."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from processes import fusion_running

root = Path(__file__).resolve().parent
app = root.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=("enable", "disable", "status"))
args = parser.parse_args()
marker = app / "spacemouse-enabled"
if args.action != "status" and fusion_running():
    raise SystemExit("Close Fusion before enabling or disabling the integration.")
if args.action == "disable":
    # Restore before removing the marker: Wine also loads app-local native DLLs
    # without an override. The marker alone cannot disable the old integration.
    for manifest in (root / "backups").glob("*/installation.json"):
        state = json.loads(manifest.read_text())
        fusion = Path(state["fusion"])
        if fusion.is_file():
            subprocess.run([sys.executable, str(root / "install-sdk.py"), "--restore", str(fusion)], check=True)
    marker.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "stop", "fusion-spacemouse.service"], check=True)
elif args.action == "enable":
    prefix = (app / "prefix-dir").read_text().strip()
    candidates = list((app / prefix / "pfx/drive_c").rglob("Fusion360.exe"))
    if not candidates:
        raise SystemExit("Fusion360.exe was not found.")
    fusion = max(candidates, key=lambda p: p.stat().st_mtime)
    subprocess.run([sys.executable, str(root / "install-sdk.py"), str(fusion)], check=True)
    subprocess.run(["systemctl", "--user", "start", "fusion-spacemouse.service"], check=True)
    marker.touch()
print("Fusion SpaceMouse: " + ("enabled" if marker.exists() else "disabled"))
if args.action == "status":
    subprocess.run(["systemctl", "--user", "--no-pager", "status", "fusion-spacemouse.service"])

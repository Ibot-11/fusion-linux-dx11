#!/usr/bin/env python3
"""Install/restore the Wine SDK beside one Fusion version, retaining its original."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from processes import fusion_running


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=".spacemouse-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fusion", type=Path)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    app = Path(__file__).resolve().parent.parent
    fusion = args.fusion.resolve()
    if fusion.name != "Fusion360.exe" or not fusion.is_file() or not fusion.is_relative_to(app):
        raise SystemExit("Ungültiger Fusion-Installationspfad")
    source = app / "spacemouse/siappdll.dll"
    target = fusion.parent / "siappdll.dll"
    backup = app / "spacemouse/backups" / fusion.parent.name
    manifest = backup / "installation.json"
    state = json.loads(manifest.read_text()) if manifest.exists() else {}
    original = backup / "siappdll.dll"
    current = digest(target) if target.exists() else None
    if args.restore:
        if not state or current == state.get("original_sha256"):
            return
        if fusion_running():
            raise SystemExit("Bitte Fusion vor der Wiederherstellung der DLL schließen.")
        if current != state.get("installed_sha256"):
            raise SystemExit("DLL wurde zwischenzeitlich geändert; Wiederherstellung abgebrochen.")
        if state.get("original_sha256"):
            if not original.exists() or digest(original) != state["original_sha256"]:
                raise SystemExit("Die gesicherte Original-DLL fehlt oder wurde geändert.")
            atomic_write(target, original.read_bytes())
        else:
            target.unlink()
        return
    expected = digest(source)
    if current == expected:
        return
    if fusion_running():
        raise SystemExit("Bitte Fusion vor dem Aktualisieren der SpaceMouse-DLL schließen.")
    backup.mkdir(parents=True, exist_ok=True)
    if current is not None and current != state.get("installed_sha256"):
        if original.exists() and digest(original) != current:
            raise SystemExit("Neue Original-DLL erkannt; vorhandene Sicherung wird nicht überschrieben.")
        if not original.exists():
            shutil.copy2(target, original)
    state = {"fusion": str(fusion), "installed_sha256": expected,
             "original_sha256": digest(original) if original.exists() else None}
    atomic_write(manifest, (json.dumps(state, indent=2) + "\n").encode())
    atomic_write(target, source.read_bytes())


if __name__ == "__main__":
    main()

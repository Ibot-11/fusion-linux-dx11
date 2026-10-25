"""Find Fusion by its executable argument: Chromium changes its Linux comm name."""
from pathlib import Path


def fusion_running():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            executable = (proc / "cmdline").read_bytes().split(b"\0", 1)[0]
            if executable.strip(b'"').lower().endswith(b"fusion360.exe"):
                return True
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return False

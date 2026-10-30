#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and update Fusion's Windows DPI in an initialized Wine prefix."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

PERCENT_DPI = {100: 96, 125: 120, 150: 144, 175: 168, 200: 192}
DPI_PERCENT = {dpi: percent for percent, dpi in PERCENT_DPI.items()}
SECTIONS = ("Control Panel\\\\Desktop", "Software\\\\Wine\\\\Fonts")
HEADER = re.compile(r"^\[(.*?)\](?:\s+\d+)?\s*$")
VALUE = re.compile(r'^"LogPixels"\s*=\s*dword:[0-9a-fA-F]+')


def percent_for_scale(scale):
    if not isinstance(scale, (int, float)) or not 1 <= scale <= 2:
        raise ValueError("The display scale must be between 1.0 and 2.0.")
    return max(100, min(200, round(scale * 4) * 25))


def dpi_for(mode, screen_scale=1.0):
    if mode == "auto":
        return PERCENT_DPI[percent_for_scale(screen_scale)]
    try:
        percent = int(mode)
    except (TypeError, ValueError):
        raise ValueError("Invalid fusion UI scale.")
    if percent not in PERCENT_DPI:
        raise ValueError("Invalid fusion UI scale.")
    return PERCENT_DPI[percent]


def nearest_percent(dpi):
    if dpi not in DPI_PERCENT:
        dpi = min(DPI_PERCENT, key=lambda value: abs(value - dpi))
    return DPI_PERCENT[dpi]


def _section(lines, name):
    for index, line in enumerate(lines):
        match = HEADER.match(line.rstrip("\r\n"))
        if match and match.group(1) == name:
            end = len(lines)
            for following in range(index + 1, len(lines)):
                if HEADER.match(lines[following].rstrip("\r\n")):
                    end = following
                    break
            return index, end
    return None


def set_dpi(text, dpi):
    if dpi not in DPI_PERCENT:
        raise ValueError("Unsupported DPI value.")
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    for section in SECTIONS:
        bounds = _section(lines, section)
        if bounds is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.extend([f"[{section}] {int(time.time())}{newline}", f'"LogPixels"=dword:{dpi:08x}{newline}'])
            continue
        start, end = bounds
        for index in range(start + 1, end):
            if VALUE.match(lines[index]):
                ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
                lines[index] = f'"LogPixels"=dword:{dpi:08x}{ending}'
                break
        else:
            lines.insert(start + 1, f'"LogPixels"=dword:{dpi:08x}{newline}')
    return "".join(lines)


def registry_path(prefix):
    return Path(prefix) / "pfx/user.reg"


def read_dpi(prefix):
    path = registry_path(prefix)
    try:
        text = path.read_bytes().decode("utf-8", "surrogateescape")
    except OSError:
        return None
    values = {}
    lines = text.splitlines()
    for section in SECTIONS:
        bounds = _section(lines, section)
        if bounds is None:
            continue
        start, end = bounds
        for line in lines[start + 1:end]:
            match = re.match(r'^"LogPixels"\s*=\s*dword:([0-9a-fA-F]+)', line)
            if match:
                values[section] = int(match.group(1), 16)
    return values.get(SECTIONS[0], values.get(SECTIONS[1]))


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fusion-scale-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_dpi(prefix, dpi):
    prefix = Path(prefix)
    path = registry_path(prefix)
    if not (prefix / "pfx").is_dir() or not path.is_file():
        raise ValueError("The selected Wine prefix is not initialized.")
    raw = path.read_bytes()
    text = raw.decode("utf-8", "surrogateescape")
    updated = set_dpi(text, dpi)
    if updated != text:
        atomic_write(path, updated.encode("utf-8", "surrogateescape"), path.stat().st_mode & 0o777)


def apply(prefix, mode, screen_scale=1.0):
    prefix = Path(prefix)
    dpi = dpi_for(mode, screen_scale)
    write_dpi(prefix, dpi)
    print(f"Fusion UI scale: {nearest_percent(dpi)}% ({dpi} DPI).", flush=True)
    return nearest_percent(dpi)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--scale", choices=("auto", "100", "125", "150", "175", "200"))
    parser.add_argument("--screen-scale", type=float, default=1.0)
    parser.add_argument("--read", action="store_true")
    args = parser.parse_args()
    try:
        if args.read:
            dpi = read_dpi(args.prefix)
            if dpi is None:
                raise ValueError("No DPI value is stored in this prefix.")
            print(json.dumps({"dpi": dpi, "percent": nearest_percent(dpi)}))
        else:
            if not args.scale:
                raise ValueError("--scale is required.")
            apply(args.prefix, args.scale, args.screen_scale)
        return 0
    except (OSError, ValueError) as error:
        print(f"Fusion scale could not be changed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

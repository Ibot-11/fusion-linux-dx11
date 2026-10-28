#!/usr/bin/env python3
"""Apply the Manager language to Fusion's machine-specific user option."""
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

LANGUAGES = {"de": "de-DE", "en": "en-US"}
OPTIONS = Path("AppData/Roaming/Autodesk/Neutron Platform/Options/NMachineSpecificOptions.xml")
TAG = re.compile(r"<userLanguageOptionId\b[^>]*(?:/>|>.*?</userLanguageOptionId>)", re.S)


def options_path(fusion):
    parts = Path(fusion).resolve().parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index].lower() == "users":
            return Path(*parts[:index + 2]) / OPTIONS
    raise ValueError("The Fusion executable is not inside a Wine user profile.")


def decode(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    return raw.decode("utf-8"), "utf-8"


def set_language(text, code):
    match = TAG.search(text)
    if match:
        tag = match.group(0)
        updated = re.sub(r'(\bValue\s*=\s*")[^"]*(")', rf"\g<1>{code}\g<2>", tag, count=1)
        if updated == tag and not re.search(r"\bValue\s*=", tag):
            updated = f'<userLanguageOptionId Value="{code}"/>'
        return text[:match.start()] + updated + text[match.end():]
    group = re.search(r"<BootstrapOptionsGroup\b[^>]*>", text)
    if not group or group.group(0).endswith("/>"):
        raise ValueError("Fusion's BootstrapOptionsGroup is missing or invalid.")
    return text[:group.end()] + f'\n    <userLanguageOptionId Value="{code}"/>' + text[group.end():]


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fusion-language-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def apply_language(fusion, language):
    code = LANGUAGES[language]
    path = options_path(fusion)
    if path.exists():
        raw = path.read_bytes()
        text, encoding = decode(raw)
        mode = path.stat().st_mode & 0o777
    else:
        encoding = "utf-16"
        mode = 0o600
        text = ('<?xml version="1.0" encoding="UTF-16" standalone="no" ?>\n'
                "<OptionGroups>\n"
                '  <BootstrapOptionsGroup SchemaVersion="2">\n'
                "  </BootstrapOptionsGroup>\n"
                "</OptionGroups>\n")
    updated = set_language(text, code)
    if not path.exists() or updated != text:
        atomic_write(path, updated.encode(encoding), mode)
    print(f"Fusion UI language: {code}.", flush=True)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fusion", type=Path, required=True)
    parser.add_argument("--language", choices=sorted(LANGUAGES), required=True)
    args = parser.parse_args()
    try:
        apply_language(args.fusion, args.language)
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Fusion language could not be applied: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

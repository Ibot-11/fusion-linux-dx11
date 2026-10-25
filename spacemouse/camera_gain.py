#!/usr/bin/env python3
"""Set Fusion's native camera gains, without scaling the input-device integers.

Fusion 2705.1.30 uses SpacemousePan/Zoom/Rotation (1..100, default 4) in
UISpaceMouseOptionGroup in NMachineSpecificOptions.xml. The camera multiplies
each integer sample by this positive integer, then converts to double before
its motion transform. This retains the distinction between adjacent samples.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from processes import fusion_running

ROOT = Path(__file__).resolve().parent
KEYS = {"pan": "SpacemousePan", "zoom": "SpacemouseZoom", "rotation": "SpacemouseRotation"}


def validate_settings(settings):
    for name in KEYS:
        value = settings[name]
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("Fusion-Kamerafaktoren müssen zwischen 1 und 100 liegen")
    scale = settings.get("runtime_scale", 1.0)
    if type(scale) not in (int, float) or not math.isfinite(scale) or not .04 <= scale <= 1:
        raise ValueError("Ungültiger zusätzlicher Kamerafaktor")
    return settings


def percentage_settings(percent):
    if type(percent) is not int or not 1 <= percent <= 100:
        raise ValueError("Kamerageschwindigkeit muss zwischen 1 und 100 Prozent liegen")
    native = math.ceil(percent / 25)
    return {**dict.fromkeys(KEYS, native), "runtime_scale": percent / (25 * native), "percent": percent}


def encode_type(data):
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be"
    return "utf-8"


def patch_options(data, gains):
    tree = ET.fromstring(data)
    if tree.tag != "OptionGroups":
        raise ValueError("Unbekanntes Fusion-Einstellungsformat")
    encoding = encode_type(data)
    text = data.decode(encoding)
    matches = list(re.finditer(r"<UISpaceMouseOptionGroup\b[^>]*(?:/>|>.*?</UISpaceMouseOptionGroup>)", text, re.S))
    if len(matches) > 1:
        raise ValueError("Mehrere SpaceMouse-Einstellungsgruppen gefunden")
    if matches:
        match = matches[0]
        group = match.group()
        if group.rstrip().endswith("/>"):
            group = group.rstrip()[:-2] + "></UISpaceMouseOptionGroup>"
    else:
        group = '<UISpaceMouseOptionGroup SchemaVersion="2">\n  </UISpaceMouseOptionGroup>'
    for name, key in KEYS.items():
        value = gains[name]
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError("Fusion-Kamerafaktoren müssen zwischen 1 und 100 liegen")
        pattern = rf"<{key}\b[^>]*(?:/>|>.*?</{key}>)"
        nodes = list(re.finditer(pattern, group, re.S))
        if len(nodes) > 1:
            raise ValueError("Doppelte Kameraeinstellung: " + key)
        if nodes:
            node = nodes[0].group()
            if re.search(r'\bValue="[^"]*"', node):
                node = re.sub(r'\bValue="[^"]*"', f'Value="{value}"', node, count=1)
            else:
                node = node.replace("<" + key, f'<{key} Value="{value}"', 1)
            group = group[:nodes[0].start()] + node + group[nodes[0].end():]
        else:
            group = group.replace("</UISpaceMouseOptionGroup>", f'  <{key} Value="{value}"/>\n  </UISpaceMouseOptionGroup>')
    if matches:
        text = text[:match.start()] + group + text[match.end():]
    else:
        text = text.replace("</OptionGroups>", "  " + group + "\n</OptionGroups>")
    result = text.encode(encoding)
    actual = ET.fromstring(result).find("UISpaceMouseOptionGroup")
    assert actual is not None
    for name, key in KEYS.items():
        assert int(actual.find(key).attrib["Value"]) == gains[name]
    return result


def legacy_options(data):
    """Select the SDK version required by this bridge, preserving other XML."""
    encoding = encode_type(data)
    text = data.decode(encoding)
    ET.fromstring(data)
    groups = list(re.finditer(r'<CompatibilityGroup\b[^>]*(?:/>|>.*?</CompatibilityGroup>)', text, re.S))
    if len(groups) > 1:
        raise ValueError("Mehrere Kompatibilitätsgruppen gefunden")
    group = groups[0].group() if groups else '<CompatibilityGroup SchemaVersion="2"></CompatibilityGroup>'
    if group.endswith('/>'):
        group = group[:-2] + '></CompatibilityGroup>'
    key = r'<spacemouseDriverOptionId\b[^>]*(?:/>|>.*?</spacemouseDriverOptionId>)'
    nodes = list(re.finditer(key, group, re.S))
    if len(nodes) > 1:
        raise ValueError("Mehrere SpaceMouse-Treibereinstellungen gefunden")
    if nodes:
        node = nodes[0].group()
        if re.search(r'\bValue="[^"]*"', node):
            node = re.sub(r'\bValue="[^"]*"', 'Value="0"', node, count=1)
        else:
            node = node.replace('<spacemouseDriverOptionId', '<spacemouseDriverOptionId Value="0"', 1)
        group = group[:nodes[0].start()] + node + group[nodes[0].end():]
    else:
        group = group.replace('</CompatibilityGroup>', '<spacemouseDriverOptionId Value="0"/></CompatibilityGroup>')
    if groups:
        text = text[:groups[0].start()] + group + text[groups[0].end():]
    else:
        text = text.replace('</OptionGroups>', group + '</OptionGroups>')
    result = text.encode(encoding)
    actual = ET.fromstring(result).find('CompatibilityGroup/spacemouseDriverOptionId')
    if actual is None or actual.attrib.get('Value') != '0':
        raise ValueError("Legacy-Einstellung konnte nicht übernommen werden")
    return result


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".camera-gain-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def option_file():
    app = ROOT.parent
    prefix = (app / "prefix-dir").read_text().strip()
    users = app / prefix / "pfx/drive_c/users"
    candidates = list(users.glob("*/AppData/Roaming/Autodesk/Neutron Platform/Options/NMachineSpecificOptions.xml"))
    if not candidates:
        fusion_users = {p.relative_to(users).parts[0] for p in users.glob("*/AppData/Local/Autodesk/webdeploy/production/*/Fusion360.exe")}
        if len(fusion_users) == 1:
            return users / fusion_users.pop() / "AppData/Roaming/Autodesk/Neutron Platform/Options/NMachineSpecificOptions.xml"
    if len(candidates) != 1:
        raise ValueError("Fusion-Einstellungsdatei nicht eindeutig gefunden")
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--queue", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--show", action="store_true")
    mode.add_argument("--runtime-scale", action="store_true")
    parser.add_argument("--percent", type=int, choices=range(1, 101), metavar="1..100")
    for name in KEYS:
        parser.add_argument("--" + name, type=int, choices=range(1, 101), default=1, metavar="1..100")
    args = parser.parse_args()
    pending = ROOT / "camera-gain.json"
    if args.queue:
        gains = (percentage_settings(args.percent) if args.percent is not None
                 else {name: getattr(args, name) for name in KEYS})
        validate_settings(gains)
        atomic_write(pending, (json.dumps(gains, indent=2) + "\n").encode())
        print("Kamerageschwindigkeit gespeichert; wirksam beim nächsten Fusion-Start.")
        return
    if args.show:
        print(pending.read_text() if pending.exists() else json.dumps({name: 4 for name in KEYS}))
        return
    if args.runtime_scale:
        settings = validate_settings(json.loads(pending.read_text())) if pending.exists() else {}
        print(settings.get("runtime_scale", 1.0))
        return
    if not pending.exists():
        return
    if fusion_running():
        print("Fusion läuft bereits; Kamerafaktoren bleiben für den nächsten Start vorgemerkt.")
        return
    gains = validate_settings(json.loads(pending.read_text()))
    path = option_file()
    old = path.read_bytes() if path.exists() else None
    initial = '<?xml version="1.0" encoding="UTF-16"?>\n<OptionGroups></OptionGroups>'.encode('utf-16')
    new = legacy_options(patch_options(old if old is not None else initial, gains))
    if old != new:
        backup = ROOT / "backups/camera-gain"
        backup.mkdir(parents=True, exist_ok=True)
        if old is not None:
            shutil.copy2(path, backup / f"NMachineSpecificOptions-{time.time_ns()}.xml")
        if (path.read_bytes() if path.exists() else None) != old or fusion_running():
            raise RuntimeError("Fusion oder seine Einstellungsdatei wurde zwischenzeitlich geändert")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, new)
    print("Fusion-Kamerafaktoren angewendet: " + json.dumps(gains))


if __name__ == "__main__":
    main()

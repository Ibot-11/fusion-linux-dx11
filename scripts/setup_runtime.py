#!/usr/bin/env python3
"""Deploy built runtime files while preserving user data and active profiles."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "spacemouse"))
from processes import fusion_running

RUNTIME_FILES = ("launch.sh", "run-proton.sh", "switch-mode.sh", "browser-listener.py",
                 "browser-request.py", "callback.py", "window-fix.py", "update.py")
SPACE_HELPERS = ("start.py", "processes.py", "control.py", "install-sdk.py",
                 "camera_gain.py", "camera-settings.sh", "settings.sh")
MANAGED = (*RUNTIME_FILES, "processes.py", "panel-fix.exe", "panel-fix.c",
           "libVkLayer_fusion_present_sync.so", "VkLayer_fusion_present_sync.json",
           "vendor", "spacemouse", "dxvk.conf", "dxvk.conf.dist", "prefix-dir",
           "proton-version", "repo-state.json", "spacemouse-enabled")


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".fusion-setup-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def copy_file(source, target, executable=False):
    atomic_write(target, source.read_bytes(), 0o755 if executable else 0o644)


def valid_prefix(prefix):
    if not prefix or Path(prefix).name != prefix or prefix in (".", ".."):
        raise ValueError("Das Prefix muss ein einzelner Ordnername sein.")
    return prefix


def find_fusion(app, prefix):
    users = app / valid_prefix(prefix) / "pfx/drive_c/users"
    candidates = list(users.glob("*/AppData/Local/Autodesk/webdeploy/production/*/Fusion360.exe"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def snapshot(app):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = app / "backups/updates" / stamp
    backup.mkdir(parents=True)
    files = []
    for name in MANAGED:
        source = app / name
        if not source.exists():
            continue
        dest = backup / name
        if source.is_dir():
            shutil.copytree(source, dest, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "backups", "previous-installation"))
        else:
            shutil.copy2(source, dest)
        files.append(name)
    atomic_write(backup / "snapshot.json", json.dumps({"app": str(app), "files": files}, indent=2).encode())
    return backup


def repository_state(repo, version):
    state = {"version": version, "checkout": None, "revision": None,
             "remote": "https://github.com/Ibot-11/fusion-linux-dx11.git", "branch": "main"}
    if (repo / ".git").exists():
        def git(*args):
            return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()
        state.update(checkout=str(repo), revision=git("rev-parse", "HEAD"))
        try:
            state["branch"] = git("symbolic-ref", "--short", "HEAD")
            remote = git("config", f"branch.{state['branch']}.remote") or "origin"
            state["remote"] = git("remote", "get-url", remote)
        except subprocess.CalledProcessError:
            pass
    return state


def desktop_entry(app, executable, name, comment, terminal=False, icon="autodesk-fusion"):
    # Desktop Exec quoting differs from shell quoting. Escape all reserved chars,
    # including literal percent signs, without invoking a shell.
    path = str(app / executable).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\n"
            f'Exec="{path}"' + (" --interactive" if executable == "update.py" else "") +
            f"\nIcon={icon}\nTerminal={str(terminal).lower()}\nCategories=Graphics;Engineering;\n").encode()


def deploy_desktop(app):
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    apps = data / "applications"
    # Keep protocol and MIME declarations from the existing project templates.
    for name in ("autodesk-fusion", "autodesk-fusion-callback"):
        text = (REPO / "desktop" / (name + ".desktop.in")).read_text()
        line = desktop_entry(app, "launch.sh" if name == "autodesk-fusion" else "callback.py", "", "").decode().split("Exec=", 1)[1].splitlines()[0]
        suffix = " %F" if name == "autodesk-fusion" else " %u"
        text = "\n".join("Exec=" + line + suffix if row.startswith("Exec=") else row for row in text.splitlines()) + "\n"
        atomic_write(apps / (name + ".desktop"), text.encode(), 0o755)
    atomic_write(apps / "autodesk-fusion-update.desktop", desktop_entry(app, "update.py", "Fusion aktualisieren", "Linux-Integration aus dem Git-Repository aktualisieren", True), 0o755)
    copy_file(REPO / "desktop/autodesk-fusion.png", data / "icons/hicolor/256x256/apps/autodesk-fusion.png")
    local_bin = Path.home() / ".local/bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    for name, destination in (("autodesk-fusion", "launch.sh"), ("autodesk-fusion-update", "update.py")):
        link = local_bin / name
        if link.exists() and not link.is_symlink():
            print(f"Vorhandene Datei bleibt erhalten: {link}")
            continue
        link.unlink(missing_ok=True)
        link.symlink_to(app / destination)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(apps)], check=False)


def deploy_spacemouse(repo, app, prefix, service=True, desktop=True, enable=True):
    dest = app / "spacemouse"
    dest.mkdir(exist_ok=True)
    for name in SPACE_HELPERS:
        copy_file(repo / "spacemouse" / name, dest / name, True)
    stage = repo / ".build/spacemouse/runtime"
    for name in ("spacenavd", "spconvd", "spnavcfg", "siappdll.dll", "spnavcfg.png"):
        copy_file(stage / "bin" / name, dest / name, name not in ("siappdll.dll", "spnavcfg.png"))
    (dest / "lib").mkdir(exist_ok=True)
    for library in (stage / "lib").iterdir():
        target = dest / "lib" / library.name
        if library.is_symlink():
            temporary = target.with_name(".setup-" + target.name)
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(os.readlink(library))
            os.replace(temporary, target)
        else:
            copy_file(library, target)
    for label, license_file in (("spacenavd", "COPYING"), ("libspnav", "LICENSE"), ("spnavcfg", "COPYING")):
        copy_file(repo / "third_party/spacenav" / label / license_file, dest / ("COPYING-" + label))
    if not (dest / "settings.conf").exists():
        atomic_write(dest / "settings.conf", b"grab = false\nled = false\ndead-zone = 5\n")
    if not (dest / "camera-gain.json").exists():
        # Portable default: 25% needs no build-specific runtime extension.
        atomic_write(dest / "camera-gain.json", b'{"pan": 1, "zoom": 1, "rotation": 1, "percent": 25}\n')
    if service:
        subprocess.run(["systemctl", "--user", "stop", "fusion-spacemouse.service"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        # systemd's quoted ExecStart also expands percent specifiers.
        path = str(dest / "start.py").replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        unit = ('[Unit]\nDescription=Fusion SpaceMouse driver and Wine relay\nStartLimitIntervalSec=30\nStartLimitBurst=3\n\n'
                '[Service]\nType=notify\nNotifyAccess=main\nExecStart=/usr/bin/python3 "' + path + '"\n'
                'KillMode=control-group\nRestart=on-failure\nRestartSec=2\nTimeoutStartSec=12\nTimeoutStopSec=5\n')
        atomic_write(config / "systemd/user/fusion-spacemouse.service", unit.encode())
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    fusion = find_fusion(app, prefix)
    if fusion and enable:
        subprocess.run([sys.executable, str(dest / "install-sdk.py"), str(fusion)], check=True)
    if enable:
        (app / "spacemouse-enabled").touch()
    if desktop:
        data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        atomic_write(data / "applications/fusion-spacemouse.desktop", desktop_entry(app, "spacemouse/settings.sh", "Fusion SpaceMouse", "Kamerageschwindigkeit, Achsen und Tasten einstellen", icon=str(dest / "spnavcfg.png")), 0o755)


def deploy(repo, app, prefix, version, spacemouse=False, update=False, desktop=True, service=True, enable_spacemouse=False):
    repo, app = Path(repo).resolve(), Path(app).resolve()
    valid_prefix(prefix)
    if fusion_running():
        raise ValueError("Bitte Fusion vor der Installation oder Aktualisierung vollständig schließen.")
    app.mkdir(parents=True, exist_ok=True)
    backup = snapshot(app)
    print(f"Sicherung ersetzter Dateien: {backup}")
    for name in RUNTIME_FILES:
        copy_file(repo / "scripts" / name, app / name, True)
    copy_file(repo / "spacemouse/processes.py", app / "processes.py")
    for name in ("panel-fix.exe", "panel-fix.c"):
        copy_file(repo / "bin" / name, app / name, name.endswith(".exe"))
    copy_file(repo / "layer/libVkLayer_fusion_present_sync.so", app / "libVkLayer_fusion_present_sync.so")
    layer = json.loads((repo / "layer/VkLayer_fusion_present_sync.json").read_text())
    layer["layer"]["library_path"] = str(app / "libVkLayer_fusion_present_sync.so")
    atomic_write(app / "VkLayer_fusion_present_sync.json", json.dumps(layer, indent=2).encode())
    defaults = (repo / "config/dxvk.conf").read_bytes()
    if not (app / "dxvk.conf").exists():
        atomic_write(app / "dxvk.conf", defaults)
    else:
        atomic_write(app / "dxvk.conf.dist", defaults)
    shutil.copytree(repo / "vendor", app / "vendor", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    if not update or not (app / "prefix-dir").exists():
        atomic_write(app / "prefix-dir", (prefix + "\n").encode(), 0o600)
    if not update or not (app / "proton-version").exists():
        atomic_write(app / "proton-version", b"Proton - Experimental\n", 0o600)
    (app / "logs").mkdir(exist_ok=True)
    (app / "cache").mkdir(exist_ok=True)
    fusion = find_fusion(app, prefix)
    if fusion:
        # Preserve custom DXVK choices in the production folder as well.
        copy_file(app / "dxvk.conf", fusion.parent / "dxvk.conf")
        compiler = fusion.parent / "d3dcompiler_47.dll"
        system32 = app / prefix / "pfx/drive_c/windows/system32"
        if compiler.exists() and compiler.stat().st_size > 2 * 1024 * 1024 and system32.is_dir():
            copy_file(compiler, system32 / "d3dcompiler_47.dll")
    if not update:
        registry = app / prefix / "pfx/user.reg"
        if registry.exists():
            # Keep the project's existing input-tolerance fix, without touching
            # registry files during an update of an established installation.
            import re
            text = registry.read_text()
            text = re.sub(r'^"UseTakeFocus"=.*\n?', '', text, flags=re.M)
            section = r'(\[Control Panel\\\\Desktop\][^\n]*\n)(.*?)(?=\n\[|\Z)'
            def patch(match):
                body = re.sub(r'^"Drag(?:Width|Height)"=.*\n?', '', match[2], flags=re.M)
                return match[1] + '"DragHeight"="10"\n"DragWidth"="10"\n' + body
            text = re.sub(section, patch, text, flags=re.S)
            override = r'(\[Software\\\\Wine\\\\DllOverrides\][^\n]*\n)(.*?)(?=\n\[|\Z)'
            def compiler_override(match):
                body = re.sub(r'^"d3dcompiler_47"=.*\n?', '', match[2], flags=re.M)
                return match[1] + '"d3dcompiler_47"="native,builtin"\n' + body
            atomic_write(registry, re.sub(override, compiler_override, text, flags=re.S).encode())
    if spacemouse:
        enabled = (app / "spacemouse-enabled").exists() or enable_spacemouse or not update
        deploy_spacemouse(repo, app, prefix, service, desktop, enabled)
    if desktop:
        deploy_desktop(app)
    atomic_write(app / "repo-state.json", json.dumps(repository_state(repo, version), indent=2).encode(), 0o600)
    print(f"Fusion-Linux {version} eingerichtet. Vorhandene Einstellungen bleiben erhalten.")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--spacemouse", action="store_true")
    parser.add_argument("--enable-spacemouse", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        args.target.mkdir(parents=True, exist_ok=True)
        with (args.target / ".install.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deploy(REPO, args.target, args.prefix, args.version, args.spacemouse, args.update,
                   enable_spacemouse=args.enable_spacemouse)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Einrichtung abgebrochen: {error}")


if __name__ == "__main__":
    main()

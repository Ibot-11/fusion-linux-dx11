#!/usr/bin/env python3
"""Deploy built runtime files while preserving user data and active profiles."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "spacemouse"))
from processes import fusion_running
sys.path.insert(0, str(REPO / "scripts"))
import proton
import fusion_runtime

WINE_SERVER_ROOT = Path("/tmp")
RUNTIME_FILES = ("launch.sh", "run-proton.sh", "switch-mode.sh", "browser-listener.py",
                 "browser-request.py", "callback.py", "window-fix.py", "update.py", "proton.py",
                 "fusion-language.py", "fusion_scale.py", "manager_backend.py", "manager.sh", "fusion_runtime.py")
SPACE_HELPERS = ("start.py", "evdev_input.py", "keybindings.py", "camera_control.py", "hidraw_input.py", "processes.py", "control.py", "install-sdk.py",
                 "camera_gain.py", "camera-settings.sh", "settings.sh")
RETIRED_RUNTIME_FILES = ("panel-fix.exe", "panel-fix.c", "libVkLayer_fusion_present_sync.so",
                         "VkLayer_fusion_present_sync.json", "libVkLayer_fusion_present_sync.c")
# Recognize the former generated configuration during migration without shipping
# another active set of defaults alongside Proton-Fusion's profile.
LEGACY_DXVK_SHA256 = "b67cad363b6e286e547b11bd8f185d1614a5593d757f88956c014cc39276a147"
MANAGED = (*RUNTIME_FILES, "processes.py", *RETIRED_RUNTIME_FILES,
           "vendor", "spacemouse", "dxvk.conf", "dxvk.conf.dist", "prefix-dir",
            "proton-version", "proton-path", "runtime-lock.json", "repo-state.json", "spacemouse-enabled", "fusion-manager", "gpu.conf")


class WineInUse(ValueError):
    pass


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
        raise ValueError("The prefix must be a single folder name.")
    return prefix


def require_complete_clean(app):
    marker = Path(app) / "clean-install.json"
    if marker.is_symlink():
        raise ValueError("The clean installation state is invalid; refusing to modify the installation.")
    if marker.exists():
        try:
            state = json.loads(marker.read_text())
        except (OSError, ValueError) as error:
            raise ValueError("The clean installation state is invalid; refusing to modify the installation.") from error
        if (not isinstance(state, dict) or state.get("phase") != "complete" or
                not isinstance(state.get("prefix"), str) or
                not isinstance(state.get("proton_path"), str) or not state["proton_path"] or
                type(state.get("spacemouse")) is not bool or
                (state.get("installer") is not None and not isinstance(state["installer"], str))):
            raise ValueError("The clean installation is unfinished; resume it before modifying the installation.")
        valid_prefix(state["prefix"])


@contextlib.contextmanager
def wine_server_lock(prefix, wait=0):
    """Hold Wine's Linux server lock while editing a prefix offline."""
    prefix = Path(prefix).resolve()
    if not prefix.is_dir():
        yield False
        return
    base = WINE_SERVER_ROOT / f".wine-{os.getuid()}"
    info = prefix.stat()
    server = base / f"server-{info.st_dev:x}-{info.st_ino:x}"
    for directory in (base, server):
        directory.mkdir(mode=0o700, exist_ok=True)
        details = directory.lstat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise ValueError(f"Unsafe Wine server directory: {directory}")
    fd = os.open(server / "lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            raise ValueError("Unsafe Wine server lock.")
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise WineInUse("Wine is still using this prefix. Close its applications and retry.")
                time.sleep(0.25)
        # Wine can fall back to a socket lock if fcntl locks are unsupported.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(str(server / "socket"))
            except (FileNotFoundError, ConnectionRefusedError):
                pass
            else:
                raise WineInUse("Wine is still using this prefix. Close its applications and retry.")
        yield [info.st_dev, info.st_ino]
    finally:
        os.close(fd)


def patch_registry(registry, expected_identity=None):
    directory_fd = os.open(registry.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if expected_identity is not None and [info.st_dev, info.st_ino] != expected_identity:
            raise ValueError("The Wine prefix was replaced; refusing to modify the registry.")
        fd = os.open(registry.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        with os.fdopen(fd, "r") as source:
            mode = stat.S_IMODE(os.fstat(source.fileno()).st_mode)
            text = source.read()
        text = patched_registry_text(text)
        name = ".fusion-setup-" + uuid.uuid4().hex
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=directory_fd)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb") as out:
                out.write(text.encode())
            os.replace(name, registry.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        finally:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(directory_fd)


def patched_registry_text(text):
    for name, values, remove in (
        (r"Control Panel\\Desktop", '"DragHeight"="10"\n"DragWidth"="10"\n', r'UseTakeFocus|DragWidth|DragHeight'),
        (r"Software\\Wine\\DllOverrides", '"d3dcompiler_47"="native,builtin"\n', r'd3dcompiler_47'),
    ):
        section = r'(\[' + re.escape(name) + r'\][^\n]*\n)(.*?)(?=\n\[|\Z)'
        def patch(match):
            body = re.sub(r'^"(?:' + remove + r')"=.*\n?', '', match[2], flags=re.M | re.I)
            return match[1] + values + body
        text, count = re.subn(section, patch, text, count=1, flags=re.S)
        if not count:
            text = text.rstrip('\n') + f'\n\n[{name}]\n' + values
    return text


def find_fusion(app, prefix):
    users = app / valid_prefix(prefix) / "pfx/drive_c/users"
    candidates = [path for path in users.glob("*/AppData/Local/Autodesk/webdeploy/production/*/Fusion360.exe")
                  if path.is_file() and not path.is_symlink()]
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
                            ignore=shutil.ignore_patterns("__pycache__", "backups"))
        else:
            shutil.copy2(source, dest)
        files.append(name)
    atomic_write(backup / "snapshot.json", json.dumps({"app": str(app), "files": files}, indent=2).encode())
    return backup


def repository_state(repo):
    state = {"checkout": None, "revision": None,
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


def migrate_gpu_preferences(app):
    """Preserve known literal GPU overrides from an older custom launcher.

    Read shell syntax as data only; never evaluate a previous launcher. An
    existing gpu.conf remains authoritative and is never modified here.
    """
    import re
    import shlex
    target, launcher = app / "gpu.conf", app / "run-proton.sh"
    if target.exists() or not launcher.is_file():
        return
    values = {}
    for line in launcher.read_text().splitlines():
        match = re.fullmatch(r"\s*export (VK_DRIVER_FILES|DXVK_FILTER_DEVICE_NAME|DRI_PRIME|DXVK_STATE_CACHE)=(.+?)\s*", line)
        if not match or any(c in match[2] for c in ("$", "`", ";")):
            continue
        try:
            parsed = shlex.split(match[2])
        except ValueError:
            continue
        if len(parsed) == 1:
            values[match[1]] = parsed[0]
    if values:
        data = "# Preserved static GPU preferences from the previous launcher.\n"
        data += "".join(f"export {key}={shlex.quote(value)}\n" for key, value in values.items())
        atomic_write(target, data.encode(), 0o600)


def systemd_escape(value):
    """Escape a value inside a quoted systemd command-line argument."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")


@contextlib.contextmanager
def integration_lock():
    home = Path.home()
    directories = {path.resolve() for path in (home / ".local/share",
                   Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share"))),
                   Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))))}
    with contextlib.ExitStack() as stack:
        for directory in sorted(directories):
            directory.mkdir(parents=True, exist_ok=True)
            fd = os.open(directory / ".fusion-integration.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def desktop_entry(app, executable, name, comment, terminal=False, icon="autodesk-fusion"):
    # Desktop Exec quoting differs from shell quoting. Escape all reserved chars,
    # including literal percent signs, without invoking a shell.
    path = str(app / executable).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\n"
            f'Exec="{path}"' + (" --interactive" if executable == "update.py" else "") +
            f"\nIcon={icon}\nTerminal={str(terminal).lower()}\nCategories=Graphics;Engineering;\n").encode()


def desktop_files(app):
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    apps = data / "applications"
    files = {}
    for name in ("autodesk-fusion", "autodesk-fusion-callback"):
        text = (REPO / "desktop" / (name + ".desktop.in")).read_text()
        line = desktop_entry(app, "launch.sh" if name == "autodesk-fusion" else "callback.py", "", "").decode().split("Exec=", 1)[1].splitlines()[0]
        suffix = " %F" if name == "autodesk-fusion" else " %u"
        text = "\n".join("Exec=" + line + suffix if row.startswith("Exec=") else row for row in text.splitlines()) + "\n"
        files[apps / (name + ".desktop")] = (text.encode(), 0o755)
    files[apps / "autodesk-fusion-update.desktop"] = (desktop_entry(app, "update.py", "Update Fusion", "Update the Linux integration from its Git repository", True), 0o755)
    files[apps / "fusion-manager.desktop"] = (desktop_entry(app, "manager.sh", "Fusion Manager", "Manage Fusion, updates and SpaceMouse", icon="fusion-manager"), 0o755)
    for name, folder in (("autodesk-fusion.png", "256x256"), ("fusion-manager.png", "256x256"), ("fusion-manager.svg", "scalable")):
        files[data / "icons/hicolor" / folder / "apps" / name] = ((REPO / "desktop" / name).read_bytes(), 0o644)
    return files


def check_desktop_conflicts(app):
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    for path, (contents, _) in desktop_files(app).items():
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != contents)):
            raise ValueError(f"Existing desktop integration would be overwritten: {path}")
    legacy = data / "applications/fusion-spacemouse.desktop"
    if legacy.exists() or legacy.is_symlink():
        raise ValueError(f"Existing desktop integration would be removed: {legacy}")
    for name, destination in (("autodesk-fusion", "launch.sh"), ("autodesk-fusion-update", "update.py"), ("fusion-manager", "manager.sh")):
        link = Path.home() / ".local/bin" / name
        if link.is_symlink() and link.resolve() != app / destination:
            raise ValueError(f"Existing launcher points to another installation: {link}")


def deploy_desktop(app, protect_existing=False):
    with integration_lock():
        _deploy_desktop(app, protect_existing)


def _deploy_desktop(app, protect_existing=False):
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    apps = data / "applications"
    if protect_existing:
        check_desktop_conflicts(app)
    for path, (contents, mode) in desktop_files(app).items():
        atomic_write(path, contents, mode)
    local_bin = Path.home() / ".local/bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    (apps / "fusion-spacemouse.desktop").unlink(missing_ok=True)
    for name, destination in (("autodesk-fusion", "launch.sh"), ("autodesk-fusion-update", "update.py"), ("fusion-manager", "manager.sh")):
        link = local_bin / name
        if link.exists() and not link.is_symlink():
            print(f"Keeping existing file: {link}")
            continue
        link.unlink(missing_ok=True)
        link.symlink_to(app / destination)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(apps)], check=False)


def clean_legacy_spacemouse(dest):
    # deploy() has already snapshotted these files and imported their settings.
    # Restrict deletion to files belonging to the former integration.
    for name in ("spacenavd", "spconvd", "spconvd.orig", "spnavcfg", "spnavcfg.png",
                 "COPYING-spacenavd", "COPYING-spnavcfg", "COPYING-libspnav", "LICENSE-libspnav",
                 "spnavrc", "settings.conf", "buttons.json", "button_mapper.py",
                 "fusion-spacemouse-gui.py", "versions.json", "sdk-probe.exe", "spacenavd-test.log"):
        (dest / name).unlink(missing_ok=True)
    library = dest / "lib"
    if library.is_dir() and not library.is_symlink():
        for path in library.glob("libspnav.*"):
            path.unlink()
        if not any(library.iterdir()):
            library.rmdir()
    for name in ("__pycache__", "previous-installation"):
        path = dest / name
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def spacemouse_unit(dest):
    path = systemd_escape(str(dest / "start.py"))
    executable = systemd_escape(str(Path(sys.executable).resolve()))
    return ('[Unit]\nDescription=Fusion SpaceMouse direct HID bridge (evdev fallback)\nStartLimitIntervalSec=30\nStartLimitBurst=3\n\n'
            '[Service]\nType=notify\nNotifyAccess=main\nExecStart="' + executable + '" "' + path + '"\n'
            'KillMode=control-group\nRestart=on-failure\nRestartSec=2\nTimeoutStartSec=12\nTimeoutStopSec=5\n').encode()


def check_clean_service(app):
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    unit = config / "systemd/user/fusion-spacemouse.service"
    dropins = unit.parent / "fusion-spacemouse.service.d"
    if dropins.exists() or dropins.is_symlink():
        raise ValueError(f"Existing SpaceMouse service overrides require manual review: {dropins}")
    expected = spacemouse_unit(app / "spacemouse")
    if unit.is_symlink() or (unit.exists() and (not unit.is_file() or unit.read_bytes() != expected)):
        raise ValueError(f"Existing SpaceMouse service would be overwritten: {unit}")
    result = subprocess.run(["systemctl", "--user", "show", "fusion-spacemouse.service", "--property=FragmentPath", "--value"],
                            check=True, capture_output=True, text=True)
    fragment = result.stdout.strip()
    if fragment and (Path(fragment) != unit or not unit.is_file()):
        raise ValueError(f"A SpaceMouse service from another installation is loaded: {fragment}")
    result = subprocess.run(["systemctl", "--user", "show", "fusion-spacemouse.service", "--property=DropInPaths", "--value"],
                            check=True, capture_output=True, text=True)
    if result.stdout.strip():
        raise ValueError("Existing SpaceMouse service overrides require manual review.")
    return unit, expected


def install_clean_service(app):
    with integration_lock():
        unit, contents = check_clean_service(app)
        unit.parent.mkdir(parents=True, exist_ok=True)
        if not unit.exists():
            fd = os.open(unit, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "wb") as out:
                out.write(contents)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)


def deploy_spacemouse(repo, app, prefix, service=True, desktop=True, enable=True):
    dest = app / "spacemouse"
    dest.mkdir(exist_ok=True)
    for name in SPACE_HELPERS:
        copy_file(repo / "spacemouse" / name, dest / name, True)
    stage = repo / ".build/spacemouse/runtime"
    copy_file(stage / "bin/siappdll.dll", dest / "siappdll.dll")
    copy_file(repo / "spacemouse/bridge/COPYING", dest / "COPYING-bridge")
    if not (dest / "device.json").exists():
        # Import only known legacy preferences, never overwrite current ones.
        import re
        deadzone = 0
        legacy = dest / "settings.conf"
        if legacy.exists():
            match = re.search(r"^dead-zone\s*=\s*(\d+)\s*$", legacy.read_text(), re.M)
            if match:
                deadzone = int(match[1])
        bindings = ["ESC", "I"]
        if (dest / "buttons.json").exists():
            old_buttons = json.loads((dest / "buttons.json").read_text())
            bindings = [old_buttons.get("left", "ESC"), old_buttons.get("right", "I")]
        from evdev_input import settings
        config = {"deadzone": deadzone, "enabled": [True]*6, "inverted": [False]*6, "buttons": bindings}
        # Validate via a temporary file before creating the migrated settings.
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "device.json"
            candidate.write_text(json.dumps(config))
            settings(candidate)
        atomic_write(dest / "device.json", (json.dumps(config, indent=2) + "\n").encode(), 0o600)
    if not (dest / "camera-gain.json").exists():
        # Portable default: 25% needs no build-specific runtime extension.
        atomic_write(dest / "camera-gain.json", b'{"pan": 1, "zoom": 1, "rotation": 1, "percent": 25}\n')
    if service:
        with integration_lock():
            subprocess.run(["systemctl", "--user", "stop", "fusion-spacemouse.service"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            atomic_write(config / "systemd/user/fusion-spacemouse.service", spacemouse_unit(dest))
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    fusion = find_fusion(app, prefix)
    if fusion and enable:
        subprocess.run([sys.executable, str(dest / "install-sdk.py"), str(fusion)], check=True)
    if enable:
        (app / "spacemouse-enabled").touch()
    clean_legacy_spacemouse(dest)


def deploy(repo, app, prefix, spacemouse=False, update=False, desktop=True, service=True, enable_spacemouse=False, selected_proton=None):
    valid_prefix(prefix)
    with wine_server_lock(Path(app) / prefix / "pfx", wait=5) as registry_locked:
        return _deploy(repo, app, prefix, spacemouse, update, desktop, service, enable_spacemouse,
                       registry_locked=registry_locked, selected_proton=selected_proton)


def _deploy(repo, app, prefix, spacemouse=False, update=False, desktop=True, service=True, enable_spacemouse=False, registry_locked=False, selected_proton=None):
    repo, app = Path(repo).resolve(), Path(app).resolve()
    valid_prefix(prefix)
    if fusion_running():
        raise ValueError("Close Fusion before installing or updating.")
    runtime = fusion_runtime.select(selected_proton)
    app.mkdir(parents=True, exist_ok=True)
    backup = snapshot(app)
    print(f"Backup: {backup}")
    migrate_gpu_preferences(app)
    for name in RUNTIME_FILES:
        copy_file(repo / "scripts" / name, app / name, True)
    copy_file(repo / "spacemouse/processes.py", app / "processes.py")
    copy_file(repo / ".build/manager/fusion-manager", app / "fusion-manager", True)
    # Device inspection and queued camera configuration are available even when
    # the optional SDK integration is disabled.
    (app / "spacemouse").mkdir(exist_ok=True)
    for helper in ("processes.py", "evdev_input.py", "keybindings.py", "camera_control.py", "hidraw_input.py", "camera_gain.py"):
        copy_file(repo / "spacemouse" / helper, app / "spacemouse" / helper)
    copy_file(repo / ".build/manager/fusion-spacemouse-access", app / "spacemouse/fusion-spacemouse-access", True)
    for name in RETIRED_RUNTIME_FILES:
        (app / name).unlink(missing_ok=True)
    defaults = (Path(runtime['path']) / 'fusion/dxvk.conf').read_bytes()
    config_file = app / 'dxvk.conf'
    config_bytes = config_file.read_bytes() if config_file.is_file() else None
    if config_bytes is not None and (config_bytes == defaults or hashlib.sha256(config_bytes).hexdigest() == LEGACY_DXVK_SHA256):
        # The generated defaults now belong to the Proton profile.
        config_file.unlink()
    if config_file.exists():
        atomic_write(app / "dxvk.conf.dist", defaults)
    else:
        (app / 'dxvk.conf.dist').unlink(missing_ok=True)
    shutil.copytree(repo / "vendor", app / "vendor", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    if not update or not (app / "prefix-dir").exists():
        atomic_write(app / "prefix-dir", (prefix + "\n").encode(), 0o600)
    fusion_runtime.bind(app, runtime['path'])
    (app / "logs").mkdir(exist_ok=True)
    (app / "cache").mkdir(exist_ok=True)
    fusion = find_fusion(app, prefix)
    if fusion:
        # Preserve custom DXVK choices in the production folder as well.
        if config_file.exists():
            copy_file(config_file, fusion.parent / "dxvk.conf")
        compiler = fusion.parent / "d3dcompiler_47.dll"
        system32 = app / prefix / "pfx/drive_c/windows/system32"
        if compiler.exists() and compiler.stat().st_size > 2 * 1024 * 1024 and system32.is_dir():
            copy_file(compiler, system32 / "d3dcompiler_47.dll")
    if not update:
        registry = app / prefix / "pfx/user.reg"
        if registry.exists():
            if not registry_locked:
                raise ValueError("The Wine prefix appeared during deployment; retry after closing Wine.")
            patch_registry(registry, registry_locked)
    if spacemouse:
        enabled = (app / "spacemouse-enabled").exists() or enable_spacemouse or not update
        deploy_spacemouse(repo, app, prefix, service, desktop, enabled)
    if desktop:
        deploy_desktop(app)
    atomic_write(app / "repo-state.json", json.dumps(repository_state(repo), indent=2).encode(), 0o600)
    print("Linux integration files deployed.")
    return backup


def wait_for_browser_listener(listener):
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    lock = runtime / "autodesk-fusion-browser/listener.lock"
    deadline = time.monotonic() + 5
    while True:
        try:
            fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            pass
        else:
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
            finally:
                os.close(fd)
        if listener.poll() is not None or time.monotonic() >= deadline:
            raise ValueError("Browser listener could not start; Autodesk installation was not launched.")
        time.sleep(0.05)


def clean_install(app, prefix, selected_proton, spacemouse, installer, resume=None):
    app = Path(app).resolve()
    state_path = app / "clean-install.json"

    def save(state, phase):
        state["phase"] = phase
        state["revision"] = uuid.uuid4().hex
        atomic_write(state_path, (json.dumps(state, indent=2) + "\n").encode(), 0o600)

    def clean_prefix(name):
        valid_prefix(name)
        if name in (*MANAGED, "logs", "cache", "backups", "update-source", ".install.lock",
                    "clean-install.json", "FusionClientDownloader.exe"):
            raise ValueError("The prefix name is reserved for installer files.")
        return name

    if not resume:
        if any(item.name != ".install.lock" for item in app.iterdir()):
            raise ValueError("A clean installation requires an empty target folder; existing files were not changed.")
        if fusion_running():
            raise ValueError("Close Fusion before installing.")
        check_desktop_conflicts(app)
        if spacemouse:
            check_clean_service(app)
        if selected_proton and not (Path(selected_proton).expanduser() / "proton").is_file():
            raise ValueError("The selected Proton folder does not contain a proton launcher.")
        selected = Path(fusion_runtime.select(selected_proton)['path'])
        installer_path = Path(installer).expanduser().resolve() if installer else None
        if installer_path and not installer_path.is_file():
            raise ValueError(f"Installer not found: {installer_path}")
        state = {"prefix": clean_prefix(prefix), "proton_path": str(selected),
                 "spacemouse": bool(spacemouse), "installer": str(installer_path) if installer_path else None}
        save(state, "prepared")
    else:
        if not state_path.is_file():
            raise ValueError("No interrupted clean installation was found in this folder.")
        state = json.loads(state_path.read_text())
        clean_prefix(state["prefix"])
        if state.get("phase") not in ("prepared", "prefix-ready", "installer-running", "installer-complete"):
            raise ValueError("This clean installation cannot be resumed.")
        if resume == "finish" and state["phase"] not in ("installer-running", "installer-complete"):
            raise ValueError("Autodesk installation was not started; use --retry-installer.")
        if fusion_running():
            raise ValueError("Close Fusion before resuming.")
        check_desktop_conflicts(app)
        if state["spacemouse"]:
            check_clean_service(app)
        fusion_runtime.validate(state['proton_path'])

    prefix = state["prefix"]
    compat = app / prefix
    pfx = compat / "pfx"
    if compat.is_symlink() or pfx.is_symlink():
        raise ValueError("The clean installation prefix must not be a symlink.")
    for name, expected in (("prefix-dir", prefix), ("proton-path", state["proton_path"])):
        path = app / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_text().strip() != expected)):
            raise ValueError("Prefix or Proton selection changed; refusing to resume.")
        if state["phase"] != "prepared" and not path.is_file():
            raise ValueError("Prefix or Proton selection is missing; refusing to resume.")
    def identity(path):
        info = path.stat()
        return [info.st_dev, info.st_ino]
    if state.get("prefix_identity") is None:
        if state["phase"] != "prepared" or compat.exists():
            raise ValueError("The prefix ownership is unknown; refusing to modify it.")
        compat.mkdir()
        state["prefix_identity"] = identity(compat)
        save(state, "prepared")
    elif not compat.is_dir() or identity(compat) != state["prefix_identity"]:
        raise ValueError("The clean installation prefix was replaced; refusing to modify it.")
    if state.get("pfx_identity") is None:
        if state["phase"] != "prepared" or pfx.exists():
            raise ValueError("The Wine prefix ownership is unknown; refusing to modify it.")
        pfx.mkdir()
        state["pfx_identity"] = identity(pfx)
        save(state, "prepared")
    elif not pfx.is_dir() or identity(pfx) != state["pfx_identity"]:
        raise ValueError("The Wine prefix is missing or was replaced; refusing to continue.")
    env = dict(os.environ, FUSION_APP_DIR=str(app))
    print(f"Clean installation phase: {state['phase']}", flush=True)
    if state["phase"] == "prepared":
        print("Preparing Linux integration and the selected Proton prefix...", flush=True)
        deploy(REPO, app, prefix, state["spacemouse"], update=True, desktop=False, service=False,
               enable_spacemouse=state["spacemouse"], selected_proton=state['proton_path'])
        deploy_desktop(app, protect_existing=True)
        if state["spacemouse"]:
            install_clean_service(app)
        selected = Path(state["proton_path"])
        fusion_runtime.bind(app, selected)
        with wine_server_lock(pfx, wait=5) as locked:
            if locked != state["pfx_identity"]:
                raise ValueError("The Wine prefix was replaced; refusing to initialize it.")
        subprocess.run([str(app / "run-proton.sh"), "wineboot.exe", "-u"], env=env, check=True)
        if pfx.is_symlink() or not pfx.is_dir():
            raise ValueError("Proton did not create a regular Wine prefix.")
        if state.get("pfx_identity") is not None and identity(pfx) != state["pfx_identity"]:
            raise ValueError("The Wine prefix was replaced during initialization.")
        state["pfx_identity"] = identity(pfx)
        save(state, "prepared")
        with wine_server_lock(pfx, wait=15) as locked:
            if locked != state["pfx_identity"]:
                raise ValueError("The Wine prefix was replaced; refusing to modify the registry.")
            registry = pfx / "user.reg"
            if not registry.is_file():
                raise ValueError("Proton did not create user.reg; prefix initialization is incomplete.")
            patch_registry(registry, locked)
        save(state, "prefix-ready")

    if resume != "finish":
        if not pfx.is_dir():
            raise ValueError("The initialized prefix is missing; refusing to start the installer.")
        with wine_server_lock(pfx, wait=5) as locked:
            if locked != state["pfx_identity"]:
                raise ValueError("The Wine prefix was replaced; refusing to start the installer.")
            if fusion_running():
                raise ValueError("Close Fusion before starting the installer.")
        if installer:
            candidate = Path(installer).expanduser().resolve()
            if not candidate.is_file():
                raise ValueError(f"Installer not found: {candidate}")
            state["installer"] = str(candidate)
        elif state.get("installer"):
            candidate = Path(state["installer"])
            if not candidate.is_file():
                raise ValueError(f"Installer not found: {candidate}; supply --installer FILE to retry.")
        else:
            candidate = app / "FusionClientDownloader.exe"
            print("Downloading the official Autodesk installer...", flush=True)
            fd, temporary = tempfile.mkstemp(prefix=".fusion-download-", dir=app)
            os.close(fd)
            try:
                subprocess.run(["curl", "--fail", "--location", "--retry", "2",
                                "--connect-timeout", "30", "--max-time", "600",
                                "https://dl.appstreaming.autodesk.com/production/installers/Fusion%20Client%20Downloader.exe",
                                "-o", temporary], check=True)
                os.replace(temporary, candidate)
            finally:
                Path(temporary).unlink(missing_ok=True)
            state["installer"] = str(candidate)
        save(state, state["phase"])
        print("Starting Autodesk setup. Follow its instructions and close Fusion when finished.", flush=True)
        print("If interrupted, use --resume-clean with --retry-installer or --finish-install; no Fusion process will be terminated.", flush=True)
        listener = subprocess.Popen([sys.executable, str(app / "browser-listener.py")], env=env)
        try:
            wait_for_browser_listener(listener)
            save(state, "installer-running")
            process = subprocess.Popen([str(app / "run-proton.sh"), str(candidate)], env=env)
            result = process.wait()
            announced = False
            while True:
                try:
                    with wine_server_lock(pfx) as locked:
                        if locked != state["pfx_identity"]:
                            raise ValueError("The Wine prefix was replaced during installation.")
                        break
                except WineInUse:
                    if not announced:
                        print("Autodesk or Fusion is still using the prefix. Close its windows when finished; browser handoff remains active.", flush=True)
                        announced = True
                    time.sleep(1)
        except KeyboardInterrupt:
            print("Browser handoff is stopping; close any remaining Autodesk and Wine windows before resuming.", file=sys.stderr)
            raise
        finally:
            if listener.poll() is None:
                listener.terminate()
                try:
                    listener.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    listener.kill()
                    listener.wait()
        if result:
            raise ValueError(f"Autodesk installer returned exit code {result}; completion is unconfirmed.")
        if not find_fusion(app, prefix):
            raise ValueError("Autodesk installer returned successfully, but Fusion360.exe was not found; completion is unconfirmed.")
        save(state, "installer-complete")

    print("Checking Autodesk installation and completing Linux integration...", flush=True)
    with wine_server_lock(pfx, wait=5) as locked:
        if locked != state["pfx_identity"]:
            raise ValueError("The Wine prefix was replaced; refusing to finish installation.")
        if fusion_running():
            raise ValueError("Close Fusion before completing the installation.")
        if not find_fusion(app, prefix):
            raise ValueError("Fusion360.exe was not found; Autodesk installation is unconfirmed.")
        _deploy(REPO, app, prefix, state["spacemouse"], update=True, desktop=False, service=False,
                enable_spacemouse=state["spacemouse"], selected_proton=state['proton_path'])
        deploy_desktop(app, protect_existing=True)
        if state["spacemouse"]:
            install_clean_service(app)
        save(state, "complete")
    if resume == "finish":
        print("Autodesk completion was confirmed by the user and Fusion360.exe was found.")
    else:
        print("The Autodesk installer returned success and Fusion360.exe was found.")
    print("Linux integration postprocessing completed. Fusion functionality and sign-in have not been verified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--spacemouse", action="store_true")
    parser.add_argument("--enable-spacemouse", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--clean-install", action="store_true")
    parser.add_argument("--resume-clean", choices=("retry", "finish"))
    parser.add_argument("--proton")
    parser.add_argument("--installer")
    parser.add_argument("--expected-clean-state")
    args = parser.parse_args()
    try:
        args.target.mkdir(parents=True, exist_ok=True)
        lock_path = args.target / ".install.lock"
        if args.clean_install and any(args.target.iterdir()):
            raise ValueError("A clean installation requires an empty target folder; existing files were not changed.")
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        if args.clean_install:
            flags |= os.O_EXCL
        fd = os.open(lock_path, flags, 0o600)
        with os.fdopen(fd, "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if args.clean_install or args.resume_clean:
                    if args.expected_clean_state:
                        if not args.resume_clean:
                            raise ValueError("An expected clean state requires a resume action.")
                        expected = json.loads(args.expected_clean_state)
                        actual = json.loads((args.target / "clean-install.json").read_text())
                        if not isinstance(actual, dict) or expected != {**actual, "valid": True}:
                            raise ValueError("The clean installation changed. Refresh its status before continuing.")
                    def interrupted(signum, frame):
                        raise KeyboardInterrupt
                    previous_handler = signal.signal(signal.SIGTERM, interrupted)
                    try:
                        clean_install(args.target, args.prefix, args.proton, args.spacemouse,
                                      args.installer, args.resume_clean)
                    finally:
                        signal.signal(signal.SIGTERM, previous_handler)
                else:
                    require_complete_clean(args.target)
                    deploy(REPO, args.target, args.prefix, args.spacemouse, args.update,
                           enable_spacemouse=args.enable_spacemouse, selected_proton=args.proton)
            finally:
                marker = args.target / "clean-install.json"
                if args.clean_install and not marker.exists() and not marker.is_symlink():
                    try:
                        current = lock_path.lstat()
                        held = os.fstat(lock.fileno())
                        if (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino):
                            lock_path.unlink()
                    except FileNotFoundError:
                        pass
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError, KeyboardInterrupt) as error:
        if (args.clean_install or args.resume_clean) and (args.target / "clean-install.json").is_file():
            command = ["bash", str(REPO / "install.sh"), "--resume-clean", str(args.target.resolve())]
            print("Clean installation incomplete; preserve this folder. Choose explicitly:", file=sys.stderr)
            print("Retry Autodesk: " + shlex.join(command + ["--retry-installer"]), file=sys.stderr)
            print("Finish only after Autodesk confirmed completion: " + shlex.join(command + ["--finish-install"]), file=sys.stderr)
        raise SystemExit(f"Setup stopped: {error}")


if __name__ == "__main__":
    main()

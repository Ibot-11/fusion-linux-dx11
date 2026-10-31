#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON status and explicit actions for the native Fusion Manager (stdlib only)."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent if (HERE.parent / 'install.sh').exists() else None
SPACE = HERE.parent / 'spacemouse' if SOURCE else HERE / 'spacemouse'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SPACE))
from processes import fusion_running
from evdev_input import DEFAULTS, discover, settings
from camera_gain import percentage_settings
from camera_control import selected_status, runtime_dir
from hidraw_input import discover as discover_hidraw
import proton
import fusion_scale
import fusion_runtime


def atomic(path, value):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.manager-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(value)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read(path, default=''):
    try:
        return path.read_text().strip()
    except OSError:
        return default


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def valid_prefix(value):
    if not value or Path(value).name != value or value in ('.', '..'):
        raise ValueError('The prefix must be a single folder name.')
    return value


def clean_install(app):
    marker = app / 'clean-install.json'
    try:
        marker.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return {'valid': False}
    try:
        value = json.loads(marker.read_text())
        if not isinstance(value, dict) or value.get('phase') not in (
                'prepared', 'prefix-ready', 'installer-running', 'installer-complete', 'complete'):
            raise ValueError('Invalid phase')
        if not isinstance(value.get('prefix'), str):
            raise ValueError('Invalid prefix')
        valid_prefix(value['prefix'])
        if not isinstance(value.get('proton_path'), str) or not value['proton_path']:
            raise ValueError('Invalid Proton path')
        if type(value.get('spacemouse')) is not bool:
            raise ValueError('Invalid SpaceMouse setting')
        if value.get('installer') is not None and not isinstance(value['installer'], str):
            raise ValueError('Invalid installer path')
        return {**value, 'valid': True}
    except (OSError, ValueError, TypeError):
        return {'valid': False}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.PIPE).strip()


def repository(repo):
    result = {'path': str(repo) if repo else '', 'valid': False}
    if not repo:
        return result
    try:
        revision = git(repo, 'rev-parse', 'HEAD')
        try:
            branch = git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        except subprocess.CalledProcessError:
            branch = 'Detached HEAD'
        result.update(valid=True, revision=revision, branch=branch,
                      dirty=bool(git(repo, 'status', '--porcelain', '--untracked-files=normal')))
        try:
            upstream = git(repo, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
            counts = git(repo, 'rev-list', '--left-right', '--count', 'HEAD...@{upstream}').split()
            result.update(upstream=upstream, ahead=int(counts[0]), behind=int(counts[1]))
            fetch = Path(git(repo, 'rev-parse', '--git-path', 'FETCH_HEAD'))
            if not fetch.is_absolute():
                fetch = repo / fetch
            result['checked'] = fetch.stat().st_mtime if fetch.exists() else None
        except (OSError, subprocess.CalledProcessError, ValueError):
            result['upstream'] = None
    except (OSError, subprocess.CalledProcessError) as error:
        result['error'] = str(error)
    return result


def proton_versions():
    steam = proton.steam_root()
    return str(steam) if steam else None, fusion_runtime.installed()


def find_fusion(app, prefix):
    root = app / valid_prefix(prefix) / 'pfx/drive_c/users'
    candidates = list(root.glob('*/AppData/Local/Autodesk/webdeploy/production/*/Fusion360.exe'))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def fusion_version(exe):
    if not exe:
        return None
    version = read(exe.parent / 'fusion_version.txt')
    if re.fullmatch(r'\d+\.\d+\.\d+', version):
        return version
    data = read_json(exe.parent / 'version.json')
    if all(type(data.get(k)) is int for k in ('major', 'minor', 'build')):
        return '.'.join(str(data[k]) for k in ('major', 'minor', 'build'))
    return None


def direct_integration(app):
    source = read(app / 'spacemouse/start.py')
    return 'from evdev_input import' in source or 'from hidraw_input import' in source


def access_helper():
    # The chosen installation/--target never controls the privileged executable.
    return SOURCE / '.build/manager/fusion-spacemouse-access' if SOURCE else HERE / 'spacemouse/fusion-spacemouse-access'


def setup_device_access():
    pkexec = shutil.which('pkexec')
    if not pkexec:
        raise ValueError('pkexec is missing. Install Polkit to set up device access.')
    helper = access_helper()
    if not helper.is_file() or not os.access(helper, os.X_OK):
        raise ValueError('The device-access helper is missing. Build the manager or update the integration.')
    print('Setting up device access for the Universal Receiver. Polkit will request administrator approval.', flush=True)
    result = subprocess.run([pkexec, str(helper)])
    if result.returncode in (126, 127):
        raise ValueError('Device access was not set up: administrator approval was cancelled or denied.')
    if result.returncode != 0:
        raise ValueError('Device access setup failed. See the helper message above.')
    print('Unplug and reconnect the Universal Receiver to apply device access.', flush=True)


def status(app, repo):
    clean = clean_install(app)
    pending = clean is not None and (not clean['valid'] or clean['phase'] != 'complete')
    prefix = clean['prefix'] if pending and clean['valid'] else read(app / 'prefix-dir', 'compatdata-exp-dx11')
    proton_path = clean['proton_path'] if pending and clean['valid'] else read(app / 'proton-path')
    proton_name = 'Proton-Fusion'
    runtime_state = None
    runtime_error = None
    try:
        runtime_state = fusion_runtime.validate(proton_path) if pending and clean['valid'] else fusion_runtime.resolve(app)
        proton_name += ' · ' + runtime_state['build_id']
        proton_path = runtime_state['path']
    except ValueError as problem:
        runtime_error = str(problem)
    try:
        prefix = valid_prefix(prefix)
        prefix_path = app / prefix
    except ValueError:
        prefix_path = None
    error = None
    try:
        fusion = find_fusion(app, prefix_path.name if prefix_path else prefix)
    except ValueError as problem:
        fusion = None
        error = str(problem)
    steam, protons = proton_versions()
    driver = read_json(Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'autodesk-fusion-spacemouse/status.json')
    driver['fresh'] = bool(driver.get('timestamp') and 0 <= time.time() - driver['timestamp'] < 3)
    try:
        device_config = settings(app / 'spacemouse/device.json')
    except (OSError, ValueError, TypeError) as problem:
        device_config = dict(DEFAULTS)
        error = str(problem)
    if not (app / 'spacemouse/device.json').exists():
        legacy_buttons = read_json(app / 'spacemouse/buttons.json')
        if legacy_buttons:
            device_config['buttons'] = [legacy_buttons.get('left', 'ESC'), legacy_buttons.get('right', 'I')]
    prefixes = sorted(p.name for p in app.iterdir() if p.is_dir() and (p / 'pfx').is_dir()) if app.is_dir() else []
    hid_devices = discover_hidraw()
    evdev_devices = [dict(device, backend='evdev') for device in discover()]
    input_access = {'hid_available': bool(hid_devices), 'hid_readable': any(d['readable'] for d in hid_devices),
                    'evdev_readable': any(d['readable'] for d in evdev_devices),
                    'requires_setup': bool(hid_devices) and not any(d['readable'] for d in hid_devices),
                    'pkexec_available': bool(shutil.which('pkexec')), 'helper_available': access_helper().is_file()}
    camera = read_json(app / 'spacemouse/camera-gain.json', {'percent': 25})
    if not isinstance(camera, dict):
        camera = {'percent': 25}
        error = 'Invalid saved camera configuration.'
    scale_dpi = fusion_scale.read_dpi(prefix_path) if prefix_path else None
    scale_percent = fusion_scale.nearest_percent(scale_dpi) if scale_dpi else None
    scale_mode = read(app / 'fusion-scale', str(scale_percent) if scale_percent else 'auto')
    if scale_mode not in ('auto', '100', '125', '150', '175', '200'):
        scale_mode = str(scale_percent) if scale_percent else 'auto'
    try:
        scale_target_dpi = int(read(app / 'fusion-dpi', ''))
    except ValueError:
        scale_target_dpi = None
    return {'app': str(app), 'exists': app.is_dir(), 'integration_exists': (app / 'launch.sh').is_file(), 'prefix': prefix, 'prefixes': prefixes,
            'clean_install': clean,
            'prefix_exists': bool(prefix_path and (prefix_path / 'pfx').is_dir()),
            'scale_mode': scale_mode, 'scale_dpi': scale_dpi, 'scale_percent': scale_percent,
            'scale_target_dpi': scale_target_dpi,
            'scale_target_percent': fusion_scale.nearest_percent(scale_target_dpi) if scale_target_dpi else None,
            'proton': proton_name, 'proton_path': proton_path, 'protons': protons, 'steam': steam,
            'runtime': runtime_state, 'runtime_error': runtime_error,
            'fusion': str(fusion) if fusion else None, 'fusion_version': fusion_version(fusion),
            'running': fusion_running(), 'installed': read_json(app / 'repo-state.json'),
            'repo': repository(repo), 'spacemouse_enabled': (app / 'spacemouse-enabled').exists(),
            'spacemouse_installed': (app / 'spacemouse/start.py').is_file(),
            'devices': hid_devices + evdev_devices, 'input_access': input_access, 'driver': driver, 'direct_driver': direct_integration(app), 'device_config': device_config,
            'camera': camera, 'camera_live': selected_status(app, driver, camera.get('percent')), 'error': error}


def run(command):
    print('Running: ' + ' '.join(str(x) for x in command), flush=True)
    subprocess.run([str(x) for x in command], check=True)


def closed():
    if fusion_running():
        raise ValueError('Close Fusion before continuing.')


def action(args, app, repo):
    name = args.action
    clean = clean_install(app)
    pending = clean is not None and (not clean['valid'] or clean['phase'] != 'complete')
    if pending and name in ('clone', 'install', 'patch', 'apply', 'update', 'launch', 'profile', 'scale',
                            'settings', 'camera', 'enable', 'disable', 'driver-start', 'driver-stop'):
        raise ValueError('The clean installation is unfinished. Resume it before changing the installation.')
    if name in ('retry-installer', 'finish-install'):
        closed()
        if not clean or not clean['valid'] or clean['phase'] == 'complete':
            raise ValueError('No valid unfinished clean installation was found.')
        if name == 'finish-install' and clean['phase'] not in ('installer-running', 'installer-complete'):
            raise ValueError('The Autodesk installer has not been started yet.')
        try:
            expected = json.loads(args.expected_clean or '')
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Refresh the installation status before continuing.')
        if expected != clean:
            raise ValueError('Refresh the installation status before continuing.')
        if not repo or not (repo / 'install.sh').is_file():
            raise ValueError('Select the local fusion-linux-dx11 checkout.')
        run(['bash', repo / 'install.sh', '--resume-clean', app, '--' + name,
             '--expected-clean-state', args.expected_clean])
        return
    if name == 'setup-access':
        setup_device_access()
    elif name == 'clone':
        state = read_json(app / 'repo-state.json')
        destination = repo or app / 'update-source'
        if destination.exists() and any(destination.iterdir()):
            raise ValueError('The destination folder is not empty. Choose an empty folder.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(['git', 'clone', '--branch', state.get('branch', 'main'), '--single-branch', '--',
             state.get('remote', 'https://github.com/Ibot-11/fusion-linux-dx11.git'), destination])
        print('Checkout ready: ' + str(destination), flush=True)
    elif name == 'check':
        if not repo:
            raise ValueError('Select a repository.')
        branch = git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        remote = git(repo, 'config', f'branch.{branch}.remote')
        if not remote or remote == '.':
            raise ValueError('No remote update source is configured.')
        run(['git', '-C', repo, 'fetch', '--prune', remote])
    elif name in ('install', 'patch', 'apply', 'update'):
        closed()
        if not repo or not (repo / 'install.sh').is_file():
            raise ValueError('Select the local fusion-linux-dx11 checkout.')
        mode = {'install': '--clean', 'patch': '--patch', 'apply': '--apply-update', 'update': '--update'}[name]
        command = ['bash', repo / 'install.sh', mode, app]
        if name != 'update':
            command += ['--with-spacemouse' if args.spacemouse else '--without-spacemouse']
        if args.installer:
            command += ['--installer', Path(args.installer).expanduser().resolve()]
        if args.prefix:
            command += ['--prefix', valid_prefix(args.prefix)]
        if args.proton:
            command += ['--proton', args.proton]
        run(command)
    elif name == 'launch':
        if fusion_running():
            raise ValueError('Fusion is already running.')
        if not (app / 'launch.sh').is_file():
            raise ValueError('The Linux integration is missing. Set it up first.')
        fusion_runtime.resolve(app)
        (app / 'logs').mkdir(exist_ok=True)
        with (app / 'logs/manager-launch.log').open('ab') as log:
            subprocess.Popen([str(app / 'launch.sh')], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print('Starting Fusion. Log: logs/manager-launch.log.', flush=True)
    elif name == 'profile':
        closed()
        prefix = valid_prefix(args.prefix or read(app / 'prefix-dir', 'compatdata-exp-dx11'))
        if not (app / prefix / 'pfx').is_dir():
            raise ValueError('The selected Wine prefix does not exist.')
        proton = Path(args.proton or '').expanduser().resolve()
        fusion_runtime.validate(proton)
        atomic(app / 'prefix-dir', prefix + '\n')
        fusion_runtime.bind(app, proton)
        print('Prefix and Proton saved.', flush=True)
    elif name == 'scale':
        closed()
        prefix = valid_prefix(args.prefix or read(app / 'prefix-dir', 'compatdata-exp-dx11'))
        mode = args.scale or 'auto'
        dpi = fusion_scale.dpi_for(mode, args.screen_scale)
        runtime = app / 'run-proton.sh'
        if runtime.is_file():
            subprocess.run(['bash', str(runtime), '--set-dpi', str(dpi)],
                           env=dict(os.environ, FUSION_APP_DIR=str(app), FUSION_PREFIX_DIR=prefix), check=True)
            fusion_scale.write_dpi(app / prefix, dpi)
        else:
            fusion_scale.apply(app / prefix, mode, args.screen_scale)
        atomic(app / 'fusion-scale', mode + '\n')
        atomic(app / 'fusion-dpi', str(dpi) + '\n')
        print('Restart Fusion to apply the display scaling.', flush=True)
    elif name == 'settings':
        value = json.loads(args.settings)
        if not isinstance(value, dict):
            raise ValueError('Invalid device settings.')
        # Validate before touching the persistent configuration.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'device.json'
            path.write_text(json.dumps(value))
            value = settings(path)
        atomic(app / 'spacemouse/device.json', json.dumps(value, indent=2) + '\n')
        print('Axes and buttons saved.', flush=True)
    elif name == 'camera':
        value = percentage_settings(args.percent)
        atomic(app / 'spacemouse/camera-gain.json', json.dumps(value, indent=2) + '\n')
        live = None
        if fusion_running():
            until = time.monotonic() + 1.8
            while True:
                live = selected_status(app, read_json(runtime_dir() / 'status.json'), args.percent)
                if live['state'] in ('live', 'unsupported') or time.monotonic() >= until:
                    break
                time.sleep(.05)
        if live and live['state'] == 'live':
            print(f'Camera speed applied and confirmed: {live["percent"]}%.', flush=True)
        else:
            print('Camera speed saved for the next launch.' + (' ' + live['reason'] if live else ''), flush=True)
    elif name in ('enable', 'disable'):
        closed()
        if not direct_integration(app):
            raise ValueError('Apply the current checkout before managing the driver.')
        run([sys.executable, app / 'spacemouse/control.py', name])
    elif name in ('driver-start', 'driver-stop'):
        if not direct_integration(app):
            raise ValueError('Apply the current checkout before managing the driver.')
        run(['systemctl', '--user', 'start' if name == 'driver-start' else 'stop', 'fusion-spacemouse.service'])
    else:
        raise ValueError('Unknown action: ' + name)


def main():
    # Keep tool output in the same language as the manager.
    os.environ['LC_MESSAGES'] = 'C'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'autodesk-fusion')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--action', default='status')
    parser.add_argument('--prefix')
    parser.add_argument('--proton')
    parser.add_argument('--installer')
    parser.add_argument('--expected-clean')
    parser.add_argument('--spacemouse', action='store_true')
    parser.add_argument('--settings')
    parser.add_argument('--percent', type=int)
    parser.add_argument('--scale', choices=('auto', '100', '125', '150', '175', '200'))
    parser.add_argument('--screen-scale', type=float, default=1.0)
    args = parser.parse_args()
    app = args.target.expanduser().resolve()
    state = read_json(app / 'repo-state.json')
    repo = (args.repo or (Path(state['checkout']) if state.get('checkout') else
                         app / 'update-source' if (app / 'update-source/.git').exists() else SOURCE))
    repo = repo.expanduser().resolve() if repo else None
    try:
        if args.action == 'status':
            print(json.dumps(status(app, repo), ensure_ascii=False))
        else:
            # A per-user lock also covers first installs whose target is absent.
            runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/fusion-manager-{os.getuid()}'))
            runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (runtime / 'fusion-manager-operation.lock').open('w') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('Another manager operation is in progress.')
                action(args, app, repo)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print('Action failed: ' + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

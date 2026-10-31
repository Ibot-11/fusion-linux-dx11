import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import sys
from runtime_fixture import make_runtime


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'scripts'))
import fusion_runtime


class LauncherInstallStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'Fusion installation'
        self.app.mkdir()
        self.commands = self.root / 'commands'
        self.commands.mkdir()
        self.calls = self.root / 'calls'
        self.dialog = self.root / 'dialog'
        self.env = dict(os.environ, FUSION_APP_DIR=str(self.app), HOME=str(self.root),
                        XDG_CONFIG_HOME=str(self.root / 'config'), XDG_RUNTIME_DIR=str(self.root),
                        FUSION_LANGUAGE='de', TEST_CALLS=str(self.calls), TEST_DIALOG=str(self.dialog),
                        PATH=str(self.commands) + ':' + os.environ['PATH'])
        self.env.pop('FUSION_PREFIX_DIR', None)
        self.executable(self.commands / 'kdialog', '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_DIALOG"\n')
        self.executable(self.commands / 'powerprofilesctl', '#!/bin/sh\nexit 1\n')
        self.executable(self.commands / 'systemctl', '#!/bin/sh\nprintf "systemctl %s\\n" "$*" >> "$TEST_CALLS"\n')
        shutil.copy2(REPO / 'scripts/launch.sh', self.app / 'launch.sh')
        (self.app / 'launch.sh').chmod(0o755)
        for name in ('manager_backend.py', 'proton.py', 'fusion_scale.py', 'fusion_runtime.py'):
            shutil.copy2(REPO / 'scripts' / name, self.app / name)
        shutil.copy2(REPO / 'spacemouse/processes.py', self.app / 'processes.py')
        space = self.app / 'spacemouse'
        space.mkdir()
        for name in ('evdev_input.py', 'keybindings.py', 'camera_gain.py', 'camera_control.py', 'hidraw_input.py'):
            shutil.copy2(REPO / 'spacemouse' / name, space / name)
        self.fusion = self.app / 'prefix/pfx/drive_c/users/test/AppData/Local/Autodesk/webdeploy/production/id/Fusion360.exe'
        self.fusion.parent.mkdir(parents=True)
        self.fusion.write_bytes(b'test executable; never run')
        (self.app / 'prefix-dir').write_text('prefix\n')
        (self.app / 'prefix/pfx/user.reg').write_text('original registry\n')
        (self.app / 'fusion-dpi').write_text('144\n')
        (self.app / 'spacemouse-enabled').touch()
        (self.app / '.install.lock').touch()
        self.runtime = make_runtime(self.root/'Proton-Fusion')
        fusion_runtime.bind(self.app, self.runtime)
        for name in ('fusion-language.py', 'browser-listener.py', 'window-fix.py', 'spacemouse/install-sdk.py'):
            (self.app / name).write_text('import os\nopen(os.environ["TEST_CALLS"], "a").write("helper started\\n")\n')
        (self.app / 'panel-fix.exe').touch()
        self.executable(self.app / 'run-proton.sh', '#!/bin/sh\nprintf "proton %s\\n" "$*" >> "$TEST_CALLS"\n')

    def test_changed_runtime_blocks_before_helpers_or_writes(self):
        self.marker()
        (self.runtime/'files/lib/wine/x86_64-unix/win32u.so').write_bytes(b'changed')
        self.assert_blocked_without_changes('failed verification')

    @staticmethod
    def executable(path, contents):
        path.write_text(contents)
        path.chmod(0o755)

    def marker(self, phase='complete', **changes):
        value = dict(phase=phase, prefix='prefix', proton_path='/fake/Proton', spacemouse=True, installer=None)
        value.update(changes)
        (self.app / 'clean-install.json').write_text(json.dumps(value))
        return value

    def snapshot(self):
        return {str(path.relative_to(self.app)): path.read_bytes() if path.is_file() and not path.is_symlink()
                else ('link', os.readlink(path)) if path.is_symlink() else 'directory'
                for path in self.app.rglob('*')}

    def launch(self):
        return subprocess.run(['bash', str(self.app / 'launch.sh')], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def assert_blocked_without_changes(self, expected):
        before = self.snapshot()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(expected, result.stderr)
        self.assertIn(expected, self.dialog.read_text())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.calls.exists())

    def test_all_incomplete_phases_block_before_any_helper_or_write(self):
        for phase in ('prepared', 'prefix-ready', 'installer-running', 'installer-complete'):
            with self.subTest(phase=phase):
                self.marker(phase)
                self.assert_blocked_without_changes('installation is incomplete')

    def test_corrupt_and_invalid_markers_block(self):
        cases = ['not json', '[]', '{}',
                 json.dumps(dict(phase='unknown', prefix='prefix', proton_path='/p', spacemouse=True)),
                 json.dumps(dict(phase='complete', prefix='../escape', proton_path='/p', spacemouse=True)),
                 json.dumps(dict(phase='complete', prefix='prefix', proton_path='/p', spacemouse='yes')),
                 json.dumps(dict(phase='complete', prefix='prefix', proton_path=7, spacemouse=True)),
                 json.dumps(dict(phase='complete', prefix='prefix', proton_path='/p', spacemouse=True, installer=7))]
        for content in cases:
            with self.subTest(content=content):
                (self.app / 'clean-install.json').write_text(content)
                self.assert_blocked_without_changes('could not be verified')
        (self.app / 'clean-install.json').write_bytes(b'\xff\xfe\xff')
        self.assert_blocked_without_changes('could not be verified')

    def test_dangling_symlink_and_non_regular_marker_block(self):
        marker = self.app / 'clean-install.json'
        marker.symlink_to(self.root / 'missing')
        self.assert_blocked_without_changes('invalid or unreadable')
        marker.unlink()
        os.mkfifo(marker)
        self.assert_blocked_without_changes('invalid or unreadable')

    def test_missing_or_old_validator_blocks_marker_but_not_legacy(self):
        self.marker()
        (self.app / 'manager_backend.py').unlink()
        self.assert_blocked_without_changes('could not be verified')
        (self.app / 'manager_backend.py').write_text('pass\n')
        self.assert_blocked_without_changes('could not be verified')
        (self.app / 'clean-install.json').unlink()
        (self.app / '.install.lock').unlink()
        (self.app / 'spacemouse-enabled').unlink()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.fusion), self.calls.read_text())

    def test_missing_validator_dependency_or_python_blocks(self):
        self.marker()
        (self.app / 'spacemouse/camera_gain.py').unlink()
        self.assert_blocked_without_changes('could not be verified')
        shutil.copy2(REPO / 'spacemouse/camera_gain.py', self.app / 'spacemouse/camera_gain.py')
        self.executable(self.commands / 'python3', '#!/bin/sh\nexit 1\n')
        self.assert_blocked_without_changes('could not be verified')

    def test_symlink_launcher_checks_the_actual_installation(self):
        self.marker('installer-running')
        link = self.commands / 'autodesk-fusion'
        link.symlink_to(self.app / 'launch.sh')
        self.env.pop('FUSION_APP_DIR')
        before = self.snapshot()
        result = subprocess.run([str(link)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('installation is incomplete', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.calls.exists())

    def test_valid_complete_marker_starts_normally(self):
        self.marker()
        (self.app / 'spacemouse-enabled').unlink()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertIn('proton --set-dpi 144', calls)
        self.assertIn('proton ' + str(self.fusion), calls)
        self.assertFalse(self.dialog.exists())

    def test_missing_symlinked_or_busy_lock_blocks_without_writing(self):
        self.marker()
        lock = self.app / '.install.lock'
        lock.unlink()
        self.assert_blocked_without_changes('installation lock is unavailable')
        external = self.root / 'other-lock'
        external.touch()
        lock.symlink_to(external)
        self.assert_blocked_without_changes('installation lock is unavailable')
        lock.unlink()
        lock.touch()
        with lock.open('r+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_blocked_without_changes('installation is in progress')

    def test_launcher_holds_installer_lock_until_fusion_exits(self):
        self.marker()
        (self.app / 'spacemouse-enabled').unlink()
        (self.app / 'fusion-dpi').unlink()
        (self.app / 'panel-fix.exe').unlink()
        ready, release = self.root / 'ready', self.root / 'release'
        self.executable(self.app / 'run-proton.sh',
                        f'#!/bin/sh\ntouch "{ready}"\nwhile [ ! -e "{release}" ]; do sleep 0.05; done\n')
        process = subprocess.Popen(['bash', str(self.app / 'launch.sh')], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(ready.exists(), 'Fake Proton did not start')
        with (self.app / '.install.lock').open('r+') as handle:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.touch()
        _, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)


if __name__ == '__main__':
    unittest.main()

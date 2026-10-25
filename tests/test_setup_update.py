import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import setup_runtime
import update


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()


class GitUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / 'remote.git'
        self.publisher = self.root / 'publisher'
        self.checkout = self.root / 'checkout'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'init', '-b', 'main', str(self.publisher)], check=True, capture_output=True)
        self.identity(self.publisher)
        (self.publisher / '.gitignore').write_text('.build/\n')
        self.publish('first')
        git(self.publisher, 'remote', 'add', 'origin', str(self.remote))
        git(self.publisher, 'push', '-u', 'origin', 'main')
        subprocess.run(['git', 'clone', '--branch', 'main', str(self.remote), str(self.checkout)], check=True, capture_output=True)
        self.identity(self.checkout)

    def identity(self, repo):
        git(repo, 'config', 'user.email', 'test@example.invalid')
        git(repo, 'config', 'user.name', 'Installer test')

    def publish(self, value):
        (self.publisher / 'version').write_text(value)
        # The integration test must execute the freshly fetched installer.
        (self.publisher / 'install.sh').write_text('#!/bin/sh\nprintf "' + value + '" > "$2/installer-ran"\n')
        git(self.publisher, 'add', '.')
        git(self.publisher, 'commit', '-m', value)

    def test_fetch_and_execute_the_new_installer(self):
        self.publish('second')
        git(self.publisher, 'push')
        app = self.root / 'Fusion custom path'
        app.mkdir()
        argv = ['update.py', '--repo', str(self.checkout), '--target', str(app)]
        with patch.object(sys, 'argv', argv), patch.object(update, 'fusion_running', return_value=False):
            self.assertEqual(update.main(), 0)
        self.assertEqual((app / 'installer-ran').read_text(), 'second')
        self.assertEqual(git(self.checkout, 'rev-parse', 'HEAD'), git(self.publisher, 'rev-parse', 'HEAD'))

    def test_dirty_checkout_is_preserved(self):
        (self.checkout / 'version').write_text('my local changes')
        before = git(self.checkout, 'rev-parse', 'HEAD')
        with self.assertRaises(ValueError):
            update.pull_checkout(self.checkout)
        self.assertEqual((self.checkout / 'version').read_text(), 'my local changes')
        self.assertEqual(git(self.checkout, 'rev-parse', 'HEAD'), before)

    def test_untracked_files_are_preserved(self):
        local = self.checkout / 'my-settings'
        local.write_text('keep')
        with self.assertRaises(ValueError):
            update.pull_checkout(self.checkout)
        self.assertEqual(local.read_text(), 'keep')

    def test_build_artifacts_do_not_block_updates(self):
        (self.checkout / '.build').mkdir()
        (self.checkout / '.build/local.so').write_text('generated')
        update.pull_checkout(self.checkout)

    def test_divergent_history_does_not_reset_local_commits(self):
        (self.checkout / 'local-file').write_text('keep')
        git(self.checkout, 'add', '.')
        git(self.checkout, 'commit', '-m', 'local commit')
        before = git(self.checkout, 'rev-parse', 'HEAD')
        self.publish('remote change')
        git(self.publisher, 'push')
        with self.assertRaises(subprocess.CalledProcessError):
            update.pull_checkout(self.checkout)
        self.assertEqual(git(self.checkout, 'rev-parse', 'HEAD'), before)
        self.assertEqual((self.checkout / 'local-file').read_text(), 'keep')

    def test_removed_checkout_can_be_recreated(self):
        app = self.root / 'app'
        app.mkdir()
        (app / 'repo-state.json').write_text(json.dumps(dict(checkout=str(app / 'removed'), remote=str(self.remote), branch='main')))
        checkout = update.checkout_for_installation(app)
        self.assertEqual(git(checkout, 'branch', '--show-current'), 'main')


class RuntimeDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / 'Fusion custom $ path %'
        self.app.mkdir()
        self.environment = patch.dict(os.environ, HOME=str(self.root), XDG_DATA_HOME=str(self.root / 'data'), XDG_CONFIG_HOME=str(self.root / 'config'))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.closed = patch.object(setup_runtime, 'fusion_running', return_value=False)
        self.closed.start()
        self.addCleanup(self.closed.stop)

    def deploy(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return setup_runtime.deploy(REPO, self.app, 'custom-prefix', 'test-version', desktop=False, service=False, **kwargs)

    def test_update_keeps_user_data_and_saves_replaced_files(self):
        originals = {'prefix-dir': 'custom-prefix\n', 'proton-version': 'My Proton\n',
                     'gpu.conf': 'export DRI_PRIME=1\n', 'dxvk.conf': 'my DXVK settings\n'}
        for name, value in originals.items():
            (self.app / name).write_text(value)
        (self.app / 'launch.sh').write_text('previous launcher')
        prefix = self.app / 'custom-prefix/pfx'
        prefix.mkdir(parents=True)
        (prefix / 'user.reg').write_text('registry untouched')
        (prefix / 'model.f3d').write_bytes(b'user document')
        backup = self.deploy(update=True)
        for name, value in originals.items():
            self.assertEqual((self.app / name).read_text(), value)
        self.assertEqual((prefix / 'user.reg').read_text(), 'registry untouched')
        self.assertEqual((prefix / 'model.f3d').read_bytes(), b'user document')
        self.assertEqual((backup / 'launch.sh').read_text(), 'previous launcher')
        self.assertNotEqual((self.app / 'launch.sh').read_text(), 'previous launcher')
        self.assertEqual((self.app / 'dxvk.conf.dist').read_bytes(), (REPO / 'config/dxvk.conf').read_bytes())
        self.assertTrue((self.app / 'update.py').is_file())

    def test_new_install_gets_defaults_and_update_metadata(self):
        self.deploy()
        self.assertEqual((self.app / 'prefix-dir').read_text(), 'custom-prefix\n')
        self.assertEqual((self.app / 'proton-version').read_text(), 'Proton - Experimental\n')
        self.assertEqual(json.loads((self.app / 'repo-state.json').read_text())['version'], 'test-version')
        self.assertTrue(os.access(self.app / 'update.py', os.X_OK))

    def test_initial_patch_keeps_registry_fixes(self):
        registry = self.app / 'custom-prefix/pfx/user.reg'
        registry.parent.mkdir(parents=True)
        registry.write_text('WINE REGISTRY Version 2\n\n[Control Panel\\\\Desktop] 1\n"DragWidth"="4"\n"UseTakeFocus"="N"\n\n[Software\\\\Wine\\\\DllOverrides] 1\n"other"="native"\n')
        self.deploy()
        text = registry.read_text()
        self.assertIn('"DragWidth"="10"', text)
        self.assertIn('"DragHeight"="10"', text)
        self.assertIn('"d3dcompiler_47"="native,builtin"', text)
        self.assertIn('"other"="native"', text)
        self.assertNotIn('UseTakeFocus', text)

    def test_running_fusion_prevents_any_deployment(self):
        with patch.object(setup_runtime, 'fusion_running', return_value=True):
            with self.assertRaises(ValueError):
                self.deploy(update=True)
        self.assertEqual(list(self.app.iterdir()), [])

    @unittest.skipUnless((REPO / '.build/spacemouse/runtime/bin/spnavcfg').exists(), 'Build SpaceMouse first')
    def test_space_settings_and_disabled_state_survive_update(self):
        dest = self.app / 'spacemouse'
        dest.mkdir()
        settings = b'sensitivity = 1\ndead-zone = 7\n'
        speed = b'{"pan": 1, "zoom": 1, "rotation": 1, "runtime_scale": 0.8, "percent": 20}\n'
        (dest / 'settings.conf').write_bytes(settings)
        (dest / 'camera-gain.json').write_bytes(speed)
        self.deploy(update=True, spacemouse=True)
        self.assertEqual((dest / 'settings.conf').read_bytes(), settings)
        self.assertEqual((dest / 'camera-gain.json').read_bytes(), speed)
        self.assertFalse((self.app / 'spacemouse-enabled').exists())
        self.assertTrue((dest / 'lib/libspnav.so.0').is_file())

    @unittest.skipUnless((REPO / '.build/spacemouse/runtime/bin/spnavcfg').exists(), 'Build SpaceMouse first')
    def test_new_space_install_creates_service_and_settings_entry(self):
        with patch.object(setup_runtime.subprocess, 'run') as run:
            setup_runtime.deploy_spacemouse(REPO, self.app, 'custom-prefix')
        unit = self.root / 'config/systemd/user/fusion-spacemouse.service'
        self.assertIn('Type=notify', unit.read_text())
        self.assertIn('$$', unit.read_text())
        self.assertIn('%%', unit.read_text())
        self.assertTrue((self.app / 'spacemouse-enabled').exists())
        self.assertTrue((self.root / 'data/applications/fusion-spacemouse.desktop').is_file())
        self.assertEqual(json.loads((self.app / 'spacemouse/camera-gain.json').read_text())['percent'], 25)
        self.assertEqual(run.call_args_list[-1].args[0], ['systemctl', '--user', 'daemon-reload'])

    def test_desktop_exec_quotes_custom_paths(self):
        data = setup_runtime.desktop_entry(self.app, 'update.py', 'Update', 'Update', True).decode()
        self.assertIn('Exec="', data)
        self.assertIn('\\$', data)
        self.assertIn('%%', data)
        self.assertIn('" --interactive\n', data)

    def test_symlink_launcher_uses_its_actual_installation(self):
        self.deploy()
        commands = self.root / 'commands'
        commands.mkdir()
        capture = self.root / 'searched-path'
        (commands / 'find').write_text('#!/bin/sh\nprintf "%s" "$1" > "$FIND_CAPTURE"\n')
        (commands / 'kdialog').write_text('#!/bin/sh\nexit 0\n')
        for name in ('find', 'kdialog'):
            (commands / name).chmod(0o755)
        link = commands / 'autodesk-fusion'
        link.symlink_to(self.app / 'launch.sh')
        env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'], FIND_CAPTURE=str(capture))
        env.pop('FUSION_APP_DIR', None)
        result = subprocess.run([str(link)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 1)  # Expected: no Fusion EXE in test prefix.
        self.assertEqual(capture.read_text(), str(self.app / 'custom-prefix/pfx/drive_c'))


if __name__ == '__main__':
    unittest.main()

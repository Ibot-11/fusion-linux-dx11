import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import setup_runtime
import update

LANGUAGE_SPEC = importlib.util.spec_from_file_location('fusion_language', REPO / 'scripts/fusion-language.py')
fusion_language = importlib.util.module_from_spec(LANGUAGE_SPEC)
LANGUAGE_SPEC.loader.exec_module(fusion_language)
SCALE_SPEC = importlib.util.spec_from_file_location('fusion_scale', REPO / 'scripts/fusion_scale.py')
fusion_scale = importlib.util.module_from_spec(SCALE_SPEC)
SCALE_SPEC.loader.exec_module(fusion_scale)


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
            return setup_runtime.deploy(REPO, self.app, 'custom-prefix', desktop=False, service=False, **kwargs)

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
        self.assertEqual(json.loads((self.app / 'repo-state.json').read_text())['checkout'], str(REPO))
        self.assertNotIn('version', json.loads((self.app / 'repo-state.json').read_text()))
        self.assertTrue(os.access(self.app / 'update.py', os.X_OK))
        self.assertTrue((self.app / 'proton.py').is_file())
        self.assertTrue((self.app / 'fusion-language.py').is_file())
        self.assertTrue((self.app / 'fusion_scale.py').is_file())

    def test_static_gpu_preferences_migrate_without_evaluating_shell(self):
        marker = self.app / 'must-not-exist'
        (self.app / 'run-proton.sh').write_text(
            'export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/radeon_icd.json\n'
            'export DXVK_FILTER_DEVICE_NAME="AMD Radeon RX 7900 XTX"\n'
            'export DRI_PRIME=1002:744c\n'
            f'export DXVK_STATE_CACHE=$(touch "{marker}")\n')
        self.deploy(update=True)
        text = (self.app / 'gpu.conf').read_text()
        self.assertIn("export DXVK_FILTER_DEVICE_NAME='AMD Radeon RX 7900 XTX'", text)
        self.assertIn('export DRI_PRIME=1002:744c', text)
        self.assertNotIn('DXVK_STATE_CACHE', text)
        self.assertFalse(marker.exists())

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

    @unittest.skipUnless((REPO / '.build/spacemouse/runtime/bin/siappdll.dll').exists(), 'Build SpaceMouse first')
    def test_space_settings_and_disabled_state_survive_update(self):
        dest = self.app / 'spacemouse'
        dest.mkdir()
        settings = b'sensitivity = 1\ndead-zone = 7\n'
        speed = b'{"pan": 1, "zoom": 1, "rotation": 1, "runtime_scale": 0.8, "percent": 20}\n'
        (dest / 'settings.conf').write_bytes(settings)
        (dest / 'camera-gain.json').write_bytes(speed)
        backup = self.deploy(update=True, spacemouse=True)
        self.assertFalse((dest / 'settings.conf').exists())
        self.assertEqual((backup / 'spacemouse/settings.conf').read_bytes(), settings)
        self.assertEqual(json.loads((dest / 'device.json').read_text())['deadzone'], 7)
        self.assertEqual((dest / 'camera-gain.json').read_bytes(), speed)
        self.assertFalse((self.app / 'spacemouse-enabled').exists())
        self.assertTrue((dest / 'siappdll.dll').is_file())
        self.assertTrue((dest / 'evdev_input.py').is_file())
        self.assertFalse((dest / 'spacenavd').exists())

    @unittest.skipUnless((REPO / '.build/spacemouse/runtime/bin/siappdll.dll').exists(), 'Build SpaceMouse first')
    def test_new_space_install_creates_service_and_settings_entry(self):
        with patch.object(setup_runtime.subprocess, 'run') as run:
            setup_runtime.deploy_spacemouse(REPO, self.app, 'custom-prefix')
        unit = self.root / 'config/systemd/user/fusion-spacemouse.service'
        self.assertIn('Type=notify', unit.read_text())
        self.assertIn('ExecStart="' + setup_runtime.systemd_escape(str(Path(sys.executable).resolve())) + '"', unit.read_text())
        self.assertIn('$$', unit.read_text())
        self.assertIn('%%', unit.read_text())
        self.assertTrue((self.app / 'spacemouse-enabled').exists())
        self.assertFalse((self.root / 'data/applications/fusion-spacemouse.desktop').exists())
        self.assertEqual(json.loads((self.app / 'spacemouse/camera-gain.json').read_text())['percent'], 25)
        self.assertEqual(run.call_args_list[-1].args[0], ['systemctl', '--user', 'daemon-reload'])

    def test_legacy_space_migration_preserves_user_camera_and_buttons(self):
        dest = self.app / 'spacemouse'
        dest.mkdir()
        (dest / 'settings.conf').write_text('dead-zone = 0\n')
        (dest / 'buttons.json').write_text('{"left":"ESC","right":"I"}')
        (dest / 'button_mapper.py').write_text('old mapper')
        (dest / 'spacenavd').write_text('old daemon')
        (dest / 'lib').mkdir()
        (dest / 'lib/libspnav.so.0.5').write_text('old lib')
        (dest / 'my-notes.txt').write_text('preserve')
        camera = b'{"pan":1,"zoom":1,"rotation":1,"runtime_scale":0.6,"percent":15}\n'
        (dest / 'camera-gain.json').write_bytes(camera)
        self.deploy(update=True, spacemouse=True)
        config = json.loads((dest / 'device.json').read_text())
        self.assertEqual(config['deadzone'], 0)
        self.assertEqual(config['buttons'], ['ESC','I'])
        self.assertEqual((dest / 'camera-gain.json').read_bytes(), camera)
        self.assertFalse((dest / 'spacenavd').exists())
        self.assertTrue((self.app / 'fusion-manager').is_file())
        self.assertTrue((dest / 'hidraw_input.py').is_file())
        self.assertTrue((dest / 'fusion-spacemouse-access').is_file())
        self.assertFalse((dest / 'button_mapper.py').exists())
        self.assertFalse((dest / 'lib').exists())
        self.assertFalse((dest / 'buttons.json').exists())
        self.assertEqual((dest / 'my-notes.txt').read_text(), 'preserve')

    def test_desktop_exec_quotes_custom_paths(self):
        data = setup_runtime.desktop_entry(self.app, 'update.py', 'Update', 'Update', True).decode()
        self.assertIn('Exec="', data)
        self.assertIn('\\$', data)
        self.assertIn('%%', data)
        self.assertIn('" --interactive\n', data)

    def test_desktop_installs_scalable_manager_icon(self):
        with contextlib.redirect_stdout(io.StringIO()):
            setup_runtime.deploy_desktop(self.app)
        icons = self.root / 'data/icons/hicolor'
        self.assertTrue((icons / '256x256/apps/fusion-manager.png').is_file())
        self.assertTrue((icons / 'scalable/apps/fusion-manager.svg').is_file())

    def test_systemd_escaping_covers_executable_and_path_characters(self):
        escaped = setup_runtime.systemd_escape('/opt/python % $/a\\b"c')
        self.assertEqual(escaped, '/opt/python %% $$/a\\\\b\\"c')

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


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / 'Fusion app'
        self.app.mkdir()
        shutil.copy2(REPO / 'scripts/proton.py', self.app / 'proton.py')
        self.env = dict(os.environ, HOME=str(self.root / 'home'), FUSION_APP_DIR=str(self.app))
        Path(self.env['HOME']).mkdir()

    def executable(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def test_installer_uses_the_current_autodesk_downloader(self):
        installer = (REPO / 'install.sh').read_text()
        self.assertIn('Fusion%20Client%20Downloader.exe', installer)
        self.assertIn('FusionClientDownloader.exe', installer)
        self.assertNotIn('Fusion360installer.exe', installer)

    def test_run_proton_uses_custom_path_without_steam(self):
        custom = self.root / 'Custom Proton'
        self.executable(custom / 'proton', '#!/bin/sh\nprintf "%s\\n" "$@"\n')
        (self.app / 'proton-path').write_text(str(custom) + '\n')
        result = subprocess.run(['bash', str(REPO / 'scripts/run-proton.sh'), 'Fusion 360.exe'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['run', 'Fusion 360.exe'])

    def test_switch_mode_resolves_profiles_and_removes_stale_custom_path(self):
        commands = self.root / 'commands'
        self.executable(commands / 'pgrep', '#!/bin/sh\nexit 1\n')
        self.env['PATH'] = str(commands) + ':' + self.env['PATH']
        common = self.root / 'home/.local/share/Steam/steamapps/common'
        for name in ('Proton - Experimental', 'GE-Proton12-1'):
            (common / name).mkdir(parents=True)
            (common / name / 'proton').touch()
        (self.app / 'proton-path').write_text(str(self.root / 'stale custom Proton') + '\n')
        for mode, name in (('exp-dx11', 'Proton - Experimental'), ('ge-opengl', 'GE-Proton12-1')):
            with self.subTest(mode=mode):
                result = subprocess.run(['bash', str(REPO / 'scripts/switch-mode.sh'), mode],
                                        env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.app / 'proton-version').read_text(), name + '\n')
                self.assertFalse((self.app / 'proton-path').exists())

    def test_camera_preparation_failure_warns_and_still_launches(self):
        fusion = self.app / 'compatdata-exp-dx11/pfx/drive_c/Fusion360.exe'
        fusion.parent.mkdir(parents=True)
        fusion.touch()
        (self.app / 'spacemouse').mkdir()
        (self.app / 'spacemouse-enabled').touch()
        self.executable(self.app / 'spacemouse/camera_gain.py', '#!/bin/sh\nexit 1\n')
        self.executable(self.app / 'spacemouse/install-sdk.py', '#!/bin/sh\nexit 0\n')
        launched = self.root / 'launched'
        self.executable(self.app / 'run-proton.sh', '#!/bin/sh\ntouch "$LAUNCHED"\n')
        commands = self.root / 'commands'
        for name in ('kdialog', 'zenity', 'powerprofilesctl'):
            self.executable(commands / name, '#!/bin/sh\nexit 1\n')
        self.executable(commands / 'systemctl', '#!/bin/sh\nexit 0\n')
        env = dict(self.env, PATH=str(commands) + ':' + self.env['PATH'], LAUNCHED=str(launched))
        result = subprocess.run(['bash', str(REPO / 'scripts/launch.sh')], env=env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(launched.exists())
        self.assertIn('Warning: Could not apply SpaceMouse camera speed.', result.stderr)
        self.assertNotIn('wineserver', (REPO / 'scripts/launch.sh').read_text())


class BrowserHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.queue = self.runtime / 'autodesk-fusion-browser'
        self.queue.mkdir(parents=True)
        self.app = self.root / 'app'
        (self.app / 'logs').mkdir(parents=True)
        self.request = self.queue / 'test.request'
        self.request.write_text('https://example.invalid/path')
        self.env = dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime), FUSION_APP_DIR=str(self.app))

    def wait_for_request_removal(self):
        deadline = time.monotonic() + 3
        while self.request.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(self.request.exists(), 'Browser request was not consumed')

    def test_listener_uses_xdg_open_from_path(self):
        commands = self.root / 'commands'
        commands.mkdir()
        capture = self.root / 'url'
        opener = commands / 'xdg-open'
        opener.write_text('#!/bin/sh\nprintf "%s" "$1" > "$CAPTURE"\n')
        opener.chmod(0o755)
        env = dict(self.env, PATH=str(commands) + ':' + self.env['PATH'], CAPTURE=str(capture))
        process = subprocess.Popen([sys.executable, str(REPO / 'scripts/browser-listener.py')], env=env)
        try:
            self.wait_for_request_removal()
            deadline = time.monotonic() + 2
            while not capture.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertEqual(capture.read_text(), 'https://example.invalid/path')
        finally:
            process.terminate()
            process.wait(timeout=3)

    def test_listener_does_not_retry_after_launch_failure(self):
        empty_path = self.root / 'empty'
        empty_path.mkdir()
        env = dict(self.env, PATH=str(empty_path))
        process = subprocess.Popen([sys.executable, str(REPO / 'scripts/browser-listener.py')], env=env)
        try:
            self.wait_for_request_removal()
            time.sleep(.4)
            log = (self.app / 'logs/browser.log').read_text()
            self.assertEqual(log.count('Browser handoff failed:'), 1)
        finally:
            process.terminate()
            process.wait(timeout=3)


class FusionLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        self.fusion = self.app / 'compatdata-exp-dx11/pfx/drive_c/users/steamuser/AppData/Local/Autodesk/webdeploy/production/hash/Fusion360.exe'
        self.fusion.parent.mkdir(parents=True)
        self.fusion.touch()
        self.options = fusion_language.options_path(self.fusion)

    def test_existing_options_are_updated_without_losing_settings(self):
        self.options.parent.mkdir(parents=True)
        source = ('<?xml version="1.0" encoding="UTF-16" standalone="no" ?>\n'
                  '<OptionGroups><BootstrapOptionsGroup SchemaVersion="2">\n'
                  '<LastVersionLaunched Value="2705.1.30"/>\n'
                  '<userLanguageOptionId UserName="Sprache" Value="en-US"/>\n'
                  '</BootstrapOptionsGroup></OptionGroups>\n')
        self.options.write_bytes(source.encode('utf-16'))
        with contextlib.redirect_stdout(io.StringIO()):
            fusion_language.apply_language(self.fusion, 'de')
        raw = self.options.read_bytes()
        self.assertTrue(raw.startswith((b'\xff\xfe', b'\xfe\xff')))
        text = raw.decode('utf-16')
        self.assertIn('Value="de-DE"', text)
        self.assertNotIn('Value="en-US"', text)
        self.assertEqual(text.count('<userLanguageOptionId'), 1)
        self.assertIn('<LastVersionLaunched Value="2705.1.30"/>', text)

    def test_missing_language_and_missing_file_are_created_once(self):
        with contextlib.redirect_stdout(io.StringIO()):
            fusion_language.apply_language(self.fusion, 'en')
        text = self.options.read_bytes().decode('utf-16')
        self.assertIn('<userLanguageOptionId Value="en-US"/>', text)
        with contextlib.redirect_stdout(io.StringIO()):
            fusion_language.apply_language(self.fusion, 'de')
        text = self.options.read_bytes().decode('utf-16')
        self.assertIn('<userLanguageOptionId Value="de-DE"/>', text)
        self.assertEqual(text.count('<userLanguageOptionId'), 1)

    def test_launcher_uses_the_saved_manager_language(self):
        app = self.app
        shutil.copy2(REPO / 'scripts/launch.sh', app / 'launch.sh')
        shutil.copy2(REPO / 'scripts/fusion-language.py', app / 'fusion-language.py')
        (app / 'browser-listener.py').write_text('')
        launched = self.root / 'launched'
        (app / 'run-proton.sh').write_text(f'#!/bin/sh\nprintf "%s" "$1" > "{launched}"\n')
        (app / 'run-proton.sh').chmod(0o755)
        config = self.root / 'config/fusion-linux-dx11/Fusion Manager.conf'
        config.parent.mkdir(parents=True)
        config.write_text('[General]\nlanguage=de\n')
        commands = self.root / 'commands'
        commands.mkdir()
        (commands / 'powerprofilesctl').write_text('#!/bin/sh\nexit 1\n')
        (commands / 'powerprofilesctl').chmod(0o755)
        env = dict(os.environ, FUSION_APP_DIR=str(app), HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'),
                   PATH=str(commands) + ':' + os.environ['PATH'])
        env.pop('FUSION_LANGUAGE', None)
        result = subprocess.run(['bash', str(app / 'launch.sh')], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(launched.read_text(), str(self.fusion))
        text = self.options.read_bytes().decode('utf-16')
        self.assertIn('Value="de-DE"', text)


class FusionScaleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        self.prefix = self.app / 'compatdata-exp-dx11'
        (self.prefix / 'pfx').mkdir(parents=True)
        self.fusion = self.prefix / 'pfx/drive_c/users/steamuser/AppData/Local/Autodesk/webdeploy/production/hash/Fusion360.exe'
        self.fusion.parent.mkdir(parents=True)
        self.fusion.touch()
        self.registry = self.prefix / 'pfx/user.reg'
        self.registry.write_text(
            'WINE REGISTRY Version 2\n\n'
            '[Control Panel\\\\Desktop] 1792861744\n'
            '"LogPixels"=dword:00000090\n'
            '"Win8DpiScaling"=dword:00000001\n\n'
            '[Software\\\\Wine\\\\Fonts] 1793394577\n'
            '"LogPixels"=dword:00000090\n'
            '[Software\\\\Example] 1793394577\n'
            '"Keep"="unchanged"\n')

    def test_updates_both_dpi_values_and_preserves_other_settings(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fusion_scale.apply(self.prefix, '125'), 125)
        text = self.registry.read_text()
        self.assertEqual(text.count('"LogPixels"=dword:00000078'), 2)
        self.assertIn('"Win8DpiScaling"=dword:00000001', text)
        self.assertIn('"Keep"="unchanged"', text)
        self.assertEqual(fusion_scale.read_dpi(self.prefix), 120)

    def test_automatic_scale_uses_the_reported_primary_display(self):
        self.assertEqual(fusion_scale.dpi_for('auto', 1.0), 96)
        self.assertEqual(fusion_scale.dpi_for('auto', 1.45), 144)
        self.assertEqual(fusion_scale.dpi_for('auto', 1.5), 144)
        self.assertEqual(fusion_scale.dpi_for('auto', 2.0), 192)
        with self.assertRaises(ValueError):
            fusion_scale.dpi_for('auto', 0.5)

    def test_missing_dpi_sections_are_added_once(self):
        self.registry.write_text('WINE REGISTRY Version 2\n\n[Software\\\\Example] 1\n"Keep"="yes"\n')
        with contextlib.redirect_stdout(io.StringIO()):
            fusion_scale.apply(self.prefix, '100')
        text = self.registry.read_text()
        self.assertEqual(text.count('"LogPixels"=dword:00000060'), 2)
        self.assertIn('"Keep"="yes"', text)
        self.assertEqual(fusion_scale.read_dpi(self.prefix), 96)

    def test_uninitialized_prefix_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not initialized'):
            fusion_scale.apply(self.root / 'missing', '100')

    def test_launcher_reapplies_the_saved_dpi_to_the_live_registry(self):
        app = self.app
        shutil.copy2(REPO / 'scripts/launch.sh', app / 'launch.sh')
        (app / 'browser-listener.py').write_text('')
        (app / 'fusion-dpi').write_text('144\n')
        calls = self.root / 'calls'
        (app / 'run-proton.sh').write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\n')
        (app / 'run-proton.sh').chmod(0o755)
        commands = self.root / 'commands'
        commands.mkdir()
        (commands / 'powerprofilesctl').write_text('#!/bin/sh\nexit 1\n')
        (commands / 'powerprofilesctl').chmod(0o755)
        env = dict(os.environ, FUSION_APP_DIR=str(app), HOME=str(self.root), XDG_CONFIG_HOME=str(self.root / 'config'),
                   PATH=str(commands) + ':' + os.environ['PATH'])
        env.pop('FUSION_LANGUAGE', None)
        result = subprocess.run(['bash', str(app / 'launch.sh')], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.read_text().splitlines(), ['--set-dpi 144', str(self.fusion)])


if __name__ == '__main__':
    unittest.main()

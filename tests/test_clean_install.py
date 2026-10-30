import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import setup_runtime as setup


class CleanInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        self.proton = self.root / 'Custom Proton'
        self.proton.mkdir()
        (self.proton / 'proton').touch()
        self.installer = self.root / 'Autodesk.exe'
        self.installer.touch()
        self.events = []
        self.listener = None
        self.result = 0
        self.create_fusion = True
        self.interrupt = False
        for name, value in [('WINE_SERVER_ROOT', self.root), ('fusion_running', lambda: False),
                            ('_deploy', self.deploy), ('REPO', self.root),
                            ('check_desktop_conflicts', lambda app: None),
                            ('deploy_desktop', lambda *args, **kwargs: None),
                            ('wait_for_browser_listener', lambda listener: None)]:
            item = patch.object(setup, name, value)
            item.start()
            self.addCleanup(item.stop)
        for name, value in [('run', self.fake_run), ('Popen', self.popen)]:
            item = patch.object(setup.subprocess, name, value)
            item.start()
            self.addCleanup(item.stop)

    def deploy(self, repo, app, prefix, spacemouse=False, update=False, *args, **kwargs):
        self.events.append(('deploy', update, spacemouse))
        app = Path(app)
        (app / 'prefix-dir').write_text(prefix + '\n')
        (app / 'run-proton.sh').touch()
        (app / 'browser-listener.py').touch()
        return app

    def fake_run(self, command, **kwargs):
        self.events.append(('wineboot', command, kwargs['env']))
        registry = self.app / 'custom/pfx/user.reg'
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text('WINE REGISTRY Version 2\n\n[Control Panel\\\\Desktop] 1\n'
                            '"UseTakeFocus"="N"\n"DragWidth"="4"\n"Other"="keep"\n')

    def popen(self, command, **kwargs):
        if command[-1].endswith('browser-listener.py'):
            self.listener = Listener()
            self.events.append(('listener',))
            return self.listener
        self.events.append(('installer', command))
        test = self

        class Installer:
            def wait(self):
                if test.interrupt:
                    raise KeyboardInterrupt
                if test.create_fusion:
                    fusion = test.app / 'custom/pfx/drive_c/users/user/AppData/Local/Autodesk/webdeploy/production/build/Fusion360.exe'
                    fusion.parent.mkdir(parents=True, exist_ok=True)
                    fusion.touch()
                return test.result
        return Installer()

    def clean(self, resume=None, installer=True):
        return setup.clean_install(self.app, 'custom', str(self.proton), False,
                                   str(self.installer) if installer else None, resume)

    def state(self):
        return json.loads((self.app / 'clean-install.json').read_text())

    def test_clean_initializes_selected_proton_then_patches_and_finalizes(self):
        self.clean()
        self.assertEqual([event[0] for event in self.events],
                         ['deploy', 'wineboot', 'listener', 'installer', 'deploy'])
        registry = (self.app / 'custom/pfx/user.reg').read_text()
        self.assertIn('"DragWidth"="10"', registry)
        self.assertIn('"DragHeight"="10"', registry)
        self.assertIn('"d3dcompiler_47"="native,builtin"', registry)
        self.assertIn('"Other"="keep"', registry)
        self.assertNotIn('UseTakeFocus', registry)
        self.assertEqual((self.app / 'proton-path').read_text().strip(), str(self.proton))
        self.assertEqual(self.events[1][1][1:], ['wineboot.exe', '-u'])
        self.assertEqual(self.events[1][2]['FUSION_APP_DIR'], str(self.app))
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertTrue(self.listener.terminated)

    def test_nonempty_target_is_never_modified(self):
        data = self.app / 'my-document'
        data.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'empty target'):
            self.clean()
        self.assertEqual(data.read_text(), 'keep')
        self.assertEqual(self.events, [])

    def test_failed_installer_requires_explicit_finish_and_never_reruns(self):
        self.result = 1
        with self.assertRaisesRegex(ValueError, 'exit code'):
            self.clean()
        self.assertTrue(self.listener.terminated)
        self.assertEqual(self.state()['phase'], 'installer-running')
        self.clean(resume='finish', installer=False)
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertEqual(sum(event[0] == 'installer' for event in self.events), 1)

    def test_no_exe_does_not_complete_even_after_successful_return(self):
        self.create_fusion = False
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.clean()
        self.assertEqual(self.state()['phase'], 'installer-running')
        self.assertTrue(self.listener.terminated)
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.clean(resume='finish', installer=False)
        fake = self.app / 'custom/pfx/drive_c/users/user/AppData/Local/Autodesk/webdeploy/production/build/Fusion360.exe'
        fake.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'not found'):
            self.clean(resume='finish', installer=False)

    def test_interruption_cleans_up_listener_and_retry_is_explicit(self):
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.clean()
        self.assertTrue(self.listener.terminated)
        self.assertEqual(self.state()['phase'], 'installer-running')
        self.interrupt = False
        self.clean(resume='retry', installer=False)
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertEqual(sum(event[0] == 'installer' for event in self.events), 2)
        self.assertEqual(sum(event[0] == 'wineboot' for event in self.events), 1)

    def test_retry_after_prefix_failure_keeps_selected_installer(self):
        with patch.object(setup.subprocess, 'run', side_effect=OSError('wineboot failed')):
            with self.assertRaisesRegex(OSError, 'wineboot failed'):
                self.clean()
        self.assertEqual(self.state()['phase'], 'prepared')
        self.assertEqual(self.state()['installer'], str(self.installer))
        self.clean(resume='retry', installer=False)
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertEqual([event for event in self.events if event[0] == 'installer'][0][1][-1], str(self.installer))

    def test_prepared_resume_refuses_changed_prefix_before_wineboot(self):
        with patch.object(setup.subprocess, 'run', side_effect=OSError('wineboot failed')):
            with self.assertRaises(OSError):
                self.clean()
        (self.app / 'prefix-dir').write_text('other\n')
        other = self.app / 'other/pfx/user.reg'
        other.parent.mkdir(parents=True)
        other.write_text('preserve')
        events = list(self.events)
        with self.assertRaisesRegex(ValueError, 'selection changed'):
            self.clean(resume='retry', installer=False)
        self.assertEqual(other.read_text(), 'preserve')
        self.assertEqual(self.events, events)

    def test_prepared_resume_refuses_unowned_wine_prefix(self):
        with patch.object(setup.subprocess, 'run', side_effect=OSError('wineboot failed')):
            with self.assertRaises(OSError):
                self.clean()
        (self.app / 'custom/pfx').rename(self.app / 'custom/pfx-original')
        other = self.app / 'custom/pfx/user.reg'
        other.parent.mkdir(parents=True)
        other.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'was replaced'):
            self.clean(resume='retry', installer=False)
        self.assertEqual(other.read_text(), 'preserve')

    def test_interrupted_wineboot_prefix_remains_resumable(self):
        def fail_after_creation(command, **kwargs):
            (self.app / 'custom/pfx/user.reg').write_text('partial')
            raise OSError('wineboot failed')
        with patch.object(setup.subprocess, 'run', side_effect=fail_after_creation):
            with self.assertRaises(OSError):
                self.clean()
        self.assertIsNotNone(self.state()['pfx_identity'])
        self.clean(resume='retry', installer=False)
        self.assertEqual(self.state()['phase'], 'complete')

    def test_reserved_prefix_is_rejected_without_state(self):
        with self.assertRaisesRegex(ValueError, 'reserved'):
            setup.clean_install(self.app, 'run-proton.sh', str(self.proton), False, str(self.installer))
        self.assertFalse((self.app / 'clean-install.json').exists())

    def test_listener_remains_alive_until_prefix_is_idle(self):
        original = setup.wine_server_lock
        attempts = []
        @contextlib.contextmanager
        def lock(prefix, wait=0):
            if any(event[0] == 'installer' for event in self.events) and not attempts:
                self.assertFalse(self.listener.terminated)
                attempts.append(True)
                raise setup.WineInUse('busy')
            with original(prefix, wait=wait) as held:
                yield held
        with patch.object(setup, 'wine_server_lock', lock), patch.object(setup.time, 'sleep') as sleep:
            self.clean()
        self.assertEqual(len(attempts), 1)
        sleep.assert_called_once_with(1)
        self.assertTrue(self.listener.terminated)

    def test_installer_launch_error_cleans_up_listener(self):
        original = self.popen
        def fail(command, **kwargs):
            if not command[-1].endswith('browser-listener.py'):
                raise OSError('cannot start installer')
            return original(command, **kwargs)
        with patch.object(setup.subprocess, 'Popen', fail):
            with self.assertRaisesRegex(OSError, 'cannot start'):
                self.clean()
        self.assertTrue(self.listener.terminated)
        self.assertEqual(self.state()['phase'], 'installer-running')

    def test_listener_start_failure_never_launches_installer(self):
        with patch.object(setup, 'wait_for_browser_listener', side_effect=ValueError('listener failed')):
            with self.assertRaisesRegex(ValueError, 'listener failed'):
                self.clean()
        self.assertTrue(self.listener.terminated)
        self.assertEqual(self.state()['phase'], 'prefix-ready')
        self.assertFalse(any(event[0] == 'installer' for event in self.events))

    def test_failed_postprocessing_keeps_installer_complete_for_finish(self):
        original = self.deploy
        def fail_post(repo, app, prefix, spacemouse=False, update=False, *args, **kwargs):
            if any(event[0] == 'installer' for event in self.events):
                raise OSError('postprocessing failed')
            return original(repo, app, prefix, spacemouse, update, *args, **kwargs)
        with patch.object(setup, '_deploy', fail_post):
            with self.assertRaisesRegex(OSError, 'postprocessing failed'):
                self.clean()
        self.assertEqual(self.state()['phase'], 'installer-complete')
        self.clean(resume='finish', installer=False)
        self.assertEqual(self.state()['phase'], 'complete')
        self.assertEqual(sum(event[0] == 'installer' for event in self.events), 1)

    def test_running_fusion_prevents_finish_and_preserves_state(self):
        self.result = 1
        with self.assertRaises(ValueError):
            self.clean()
        with patch.object(setup, 'fusion_running', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Close Fusion'):
                self.clean(resume='finish', installer=False)
        self.assertEqual(self.state()['phase'], 'installer-running')

    def test_registry_patch_is_idempotent_and_creates_missing_sections(self):
        registry = self.root / 'user.reg'
        registry.write_text('WINE REGISTRY Version 2\n')
        setup.patch_registry(registry)
        once = registry.read_bytes()
        setup.patch_registry(registry)
        self.assertEqual(registry.read_bytes(), once)
        self.assertIn(b'[Control Panel\\\\Desktop]', once)
        self.assertIn(b'[Software\\\\Wine\\\\DllOverrides]', once)


class Listener:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class WineLockTests(unittest.TestCase):
    def test_registry_edit_refuses_a_different_locked_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, other = root / 'first', root / 'other'
            first.mkdir()
            other.mkdir()
            registry = other / 'user.reg'
            registry.write_text('original')
            info = first.stat()
            with self.assertRaisesRegex(ValueError, 'replaced'):
                setup.patch_registry(registry, [info.st_dev, info.st_ino])
            self.assertEqual(registry.read_text(), 'original')

    def test_prefix_appearing_during_deploy_does_not_patch_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            registry = app / 'prefix/pfx/user.reg'
            def snapshot(target):
                registry.parent.mkdir(parents=True)
                registry.write_text('original')
                return root
            with patch.object(setup, 'WINE_SERVER_ROOT', root), \
                    patch.object(setup, 'fusion_running', return_value=False), \
                    patch.object(setup, 'snapshot', side_effect=snapshot), \
                    patch.object(setup, 'copy_file'), patch.object(setup, 'atomic_write'), \
                    patch.object(setup.shutil, 'copytree'):
                with self.assertRaisesRegex(ValueError, 'appeared during deployment'):
                    setup.deploy(REPO, app, 'prefix', desktop=False, service=False)
            self.assertEqual(registry.read_text(), 'original')

    def test_active_server_lock_blocks_registry_edit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pfx = root / 'pfx'
            pfx.mkdir()
            registry = pfx / 'user.reg'
            registry.write_text('original')
            details = pfx.stat()
            server = root / f'.wine-{os.getuid()}' / f'server-{details.st_dev:x}-{details.st_ino:x}'
            server.mkdir(parents=True, mode=0o700)
            server.parent.chmod(0o700)
            lock = server / 'lock'
            code = ('import fcntl,sys; f=open(sys.argv[1],"w"); '
                    'fcntl.lockf(f,fcntl.LOCK_EX,1); print("ready",flush=True); sys.stdin.read()')
            process = subprocess.Popen([sys.executable, '-c', code, str(lock)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                with patch.object(setup, 'WINE_SERVER_ROOT', root):
                    with self.assertRaisesRegex(ValueError, 'Wine is still using'):
                        with setup.wine_server_lock(pfx):
                            setup.patch_registry(registry)
                self.assertEqual(registry.read_text(), 'original')
            finally:
                process.stdin.close()
                process.wait(timeout=5)
                process.stdout.close()


class IntegrationSafetyTests(unittest.TestCase):
    def test_global_integration_lock_prevents_parallel_deployment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = root / '.local/share'
            shared.mkdir(parents=True)
            lock = shared / '.fusion-integration.lock'
            code = ('import fcntl,sys; f=open(sys.argv[1],"w"); '
                    'fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read()')
            process = subprocess.Popen([sys.executable, '-c', code, str(lock)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                with patch.dict(os.environ, HOME=str(root), XDG_DATA_HOME=str(root / 'different-data'),
                                XDG_CONFIG_HOME=str(root / 'config')):
                    with patch.object(setup, '_deploy_desktop') as deploy:
                        with self.assertRaises(BlockingIOError):
                            setup.deploy_desktop(root / 'app', protect_existing=True)
                        deploy.assert_not_called()
            finally:
                process.stdin.close()
                process.wait(timeout=5)
                process.stdout.close()

    def test_incomplete_or_invalid_marker_blocks_direct_deploy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'clean-install.json'
            for content in ('{}', '{invalid', '{"phase":"installer-running"}', '{"phase":"complete"}'):
                marker.write_text(content)
                with self.assertRaises(ValueError):
                    setup.require_complete_clean(root)

    def test_real_deployment_with_fake_proton_and_isolated_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / 'repo'
            repo.mkdir()
            for name in ('scripts', 'spacemouse', 'desktop', 'bin', 'config', 'vendor'):
                shutil.copytree(REPO / name, repo / name, ignore=shutil.ignore_patterns('__pycache__'))
            (repo / 'layer').mkdir()
            shutil.copy2(REPO / 'layer/VkLayer_fusion_present_sync.json', repo / 'layer')
            (repo / 'layer/libVkLayer_fusion_present_sync.so').write_bytes(b'fake layer')
            (repo / '.build/manager').mkdir(parents=True)
            for name in ('fusion-manager', 'fusion-spacemouse-access'):
                (repo / '.build/manager' / name).write_bytes(b'fake binary')
            proton = root / 'proton'
            proton.mkdir()
            launcher = proton / 'proton'
            launcher.write_text('#!/bin/sh\nset -eu\n'
                'pfx="$STEAM_COMPAT_DATA_PATH/pfx"\n'
                'if [ "$2" = wineboot.exe ]; then\n'
                '  mkdir -p "$pfx"\n'
                '  printf "WINE REGISTRY Version 2\\n" > "$pfx/user.reg"\n'
                'else\n'
                '  dir="$pfx/drive_c/users/test/AppData/Local/Autodesk/webdeploy/production/build"\n'
                '  mkdir -p "$dir"\n'
                '  : > "$dir/Fusion360.exe"\n'
                'fi\n')
            launcher.chmod(0o755)
            installer = root / 'Autodesk.exe'
            installer.touch()
            app = root / 'app'
            app.mkdir()
            runtime = root / 'runtime'
            runtime.mkdir()
            env = dict(HOME=str(root), XDG_DATA_HOME=str(root / 'data'),
                       XDG_CONFIG_HOME=str(root / 'config'), XDG_RUNTIME_DIR=str(runtime))
            with patch.dict(os.environ, env), patch.object(setup, 'REPO', repo), \
                    patch.object(setup, 'WINE_SERVER_ROOT', root), \
                    patch.object(setup, 'fusion_running', return_value=False), \
                    patch.object(setup.shutil, 'which', return_value=None):
                setup.clean_install(app, 'prefix', str(proton), False, str(installer))
            state = json.loads((app / 'clean-install.json').read_text())
            self.assertEqual(state['phase'], 'complete')
            registry = (app / 'prefix/pfx/user.reg').read_text()
            self.assertIn('"DragWidth"="10"', registry)
            self.assertIn('"d3dcompiler_47"="native,builtin"', registry)
            fusion = setup.find_fusion(app, 'prefix')
            self.assertIsNotNone(fusion)
            self.assertTrue((fusion.parent / 'dxvk.conf').is_file())
            self.assertTrue((root / 'data/applications/autodesk-fusion.desktop').is_file())

    def test_foreign_desktop_entry_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = root / 'data/applications/autodesk-fusion.desktop'
            entry.parent.mkdir(parents=True)
            entry.write_text('other installation')
            with patch.dict(os.environ, HOME=str(root), XDG_DATA_HOME=str(root / 'data')):
                with self.assertRaisesRegex(ValueError, 'overwritten'):
                    setup.check_desktop_conflicts(root / 'app')
            self.assertEqual(entry.read_text(), 'other installation')

    def test_foreign_spacemouse_unit_is_not_stopped_or_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unit = root / 'config/systemd/user/fusion-spacemouse.service'
            unit.parent.mkdir(parents=True)
            unit.write_text('other installation')
            with patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config')):
                with patch.object(setup.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'overwritten'):
                        setup.check_clean_service(root / 'app')
                    run.assert_not_called()
            self.assertEqual(unit.read_text(), 'other installation')

    def test_spacemouse_dropins_are_preserved_and_block_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dropin = root / 'config/systemd/user/fusion-spacemouse.service.d/override.conf'
            dropin.parent.mkdir(parents=True)
            dropin.write_text('foreign override')
            with patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config')):
                with patch.object(setup.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'overrides'):
                        setup.check_clean_service(root / 'app')
                    run.assert_not_called()
            self.assertEqual(dropin.read_text(), 'foreign override')

    def test_loaded_foreign_service_is_not_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config')):
                with patch.object(setup.subprocess, 'run', return_value=SimpleNamespace(stdout='/elsewhere/service\n')) as run:
                    with self.assertRaisesRegex(ValueError, 'another installation'):
                        setup.check_clean_service(root / 'app')
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][2], 'show')

    def test_clean_service_reuses_own_unit_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            unit = root / 'config/systemd/user/fusion-spacemouse.service'
            with patch.dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data')):
                with patch.object(setup.subprocess, 'run', return_value=SimpleNamespace(stdout='')) as run:
                    setup.install_clean_service(app)
                    before = unit.read_bytes()
                    setup.install_clean_service(app)
                    self.assertEqual(unit.read_bytes(), before)
                    commands = [call.args[0] for call in run.call_args_list]
                    self.assertTrue(all('stop' not in command for command in commands))

    def test_install_lock_does_not_truncate_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            lock = app / '.install.lock'
            lock.write_text('existing content')
            (app / 'document').write_text('keep')
            argv = ['setup_runtime.py', '--target', str(app), '--prefix', 'new', '--clean-install']
            with patch.object(sys, 'argv', argv):
                with self.assertRaises(SystemExit):
                    setup.main()
            self.assertEqual(lock.read_text(), 'existing content')
            self.assertEqual((app / 'document').read_text(), 'keep')

    def test_clean_preflight_leaves_nonempty_target_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            (app / 'document').write_text('keep')
            argv = ['setup_runtime.py', '--target', str(app), '--prefix', 'new', '--clean-install']
            with patch.object(sys, 'argv', argv), self.assertRaises(SystemExit):
                setup.main()
            self.assertEqual([path.name for path in app.iterdir()], ['document'])

    def test_failed_preflight_removes_only_its_own_unneeded_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            argv = ['setup_runtime.py', '--target', str(app), '--prefix', 'new', '--clean-install']
            with patch.object(sys, 'argv', argv), patch.object(setup, 'clean_install', side_effect=ValueError('failed')):
                with self.assertRaises(SystemExit):
                    setup.main()
            self.assertEqual(list(app.iterdir()), [])

    def test_resume_checks_expected_marker_under_install_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            state = {'phase': 'installer-running', 'revision': 'new', 'prefix': 'p',
                     'proton_path': '/proton', 'spacemouse': False, 'installer': None}
            (app / 'clean-install.json').write_text(json.dumps(state))
            expected = {**state, 'revision': 'old', 'valid': True}
            argv = ['setup_runtime.py', '--target', str(app), '--prefix', 'p',
                    '--resume-clean', 'finish', '--expected-clean-state', json.dumps(expected)]
            with patch.object(sys, 'argv', argv), patch.object(setup, 'clean_install') as clean:
                with self.assertRaisesRegex(SystemExit, 'changed'):
                    setup.main()
                clean.assert_not_called()
                argv[-1] = json.dumps({**state, 'valid': True})
                setup.main()
                clean.assert_called_once()


if __name__ == '__main__':
    unittest.main()

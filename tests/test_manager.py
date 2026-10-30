import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
import manager_backend as manager
import proton


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=self.root/'Fusion user installation';self.app.mkdir()
        self.args=argparse.Namespace(action='status',prefix=None,proton=None,installer=None,spacemouse=False,settings=None,percent=None,scale=None,screen_scale=1.0,expected_clean=None)

    def action(self,name,**values):
        self.args.action=name
        for key,value in values.items():setattr(self.args,key,value)
        with contextlib.redirect_stdout(io.StringIO()):return manager.action(self.args,self.app,REPO)

    def test_real_version_and_missing_metadata_are_distinct(self):
        folder=self.app/'prefix/pfx/drive_c/users/user/AppData/Local/Autodesk/webdeploy/production/hash';folder.mkdir(parents=True)
        exe=folder/'Fusion360.exe';exe.write_bytes(b'not executable in test')
        (folder/'fusion_version.txt').write_text('2705.1.30\n');(self.app/'prefix-dir').write_text('prefix\n');(self.app/'launch.sh').write_text('existing integration')
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'proton_versions',return_value=(None,[])),patch.object(manager,'discover',return_value=[]):
            state=manager.status(self.app,REPO)
        self.assertEqual(state['fusion_version'],'2705.1.30');self.assertEqual(state['installed'],{});self.assertTrue(state['integration_exists'])

    def test_version_fallback_is_validated_and_unknown_stays_unknown(self):
        exe=self.app/'Fusion360.exe';exe.touch()
        (self.app/'version.json').write_text('{"major": 2705,"minor":1,"build":31}')
        self.assertEqual(manager.fusion_version(exe),'2705.1.31')
        (self.app/'version.json').write_text('{"major":"not a version"}')
        self.assertIsNone(manager.fusion_version(exe))

    def test_invalid_prefix_is_rejected_without_traversal(self):
        with self.assertRaises(ValueError):manager.find_fusion(self.app,'../outside')

    def test_profile_only_accepts_existing_prefix_and_proton(self):
        (self.app/'chosen/pfx').mkdir(parents=True);proton=self.root/'Proton custom';proton.mkdir();(proton/'proton').touch()
        with patch.object(manager,'fusion_running',return_value=False):self.action('profile',prefix='chosen',proton=str(proton))
        self.assertEqual((self.app/'prefix-dir').read_text(),'chosen\n');self.assertEqual((self.app/'proton-path').read_text(),str(proton)+'\n')
        with patch.object(manager,'fusion_running',return_value=False):
            with self.assertRaises(ValueError):self.action('profile',prefix='missing')
        self.assertEqual((self.app/'prefix-dir').read_text(),'chosen\n')

    def test_running_fusion_blocks_install_profile_launch_and_sdk_mutation(self):
        with patch.object(manager,'fusion_running',return_value=True),patch.object(manager,'run') as run:
            for name in ('install','patch','apply','update','profile','enable','disable','launch','scale'):
                with self.subTest(action=name),self.assertRaises(ValueError):self.action(name)
            run.assert_not_called()
        self.assertEqual(list(self.app.iterdir()),[])

    def test_camera_is_only_queued_and_keeps_fifteen_percent(self):
        with patch.object(manager,'fusion_running',return_value=True):self.action('camera',percent=15)
        data=json.loads((self.app/'spacemouse/camera-gain.json').read_text())
        self.assertEqual(data,dict(pan=1,zoom=1,rotation=1,runtime_scale=.6,percent=15))
        self.assertEqual([p.name for p in (self.app/'spacemouse').iterdir()],['camera-gain.json'])

    def test_bad_settings_cannot_replace_saved_settings(self):
        config=dict(manager.DEFAULTS);self.action('settings',settings=json.dumps(config))
        original=(self.app/'spacemouse/device.json').read_bytes()
        with self.assertRaises(ValueError):self.action('settings',settings='{"deadzone":999}')
        self.assertEqual((self.app/'spacemouse/device.json').read_bytes(),original)

    def test_scale_action_applies_to_the_selected_prefix_and_is_reported(self):
        prefix = self.app/'chosen';prefix.joinpath('pfx').mkdir(parents=True)
        prefix.joinpath('pfx/user.reg').write_text('[Control Panel\\\\Desktop] 1\n"LogPixels"=dword:00000060\n[Software\\\\Wine\\\\Fonts] 1\n"LogPixels"=dword:00000060\n')
        (self.app/'prefix-dir').write_text('chosen\n')
        with patch.object(manager,'fusion_running',return_value=False):
            self.action('scale',scale='auto',screen_scale=1.45)
        self.assertEqual((self.app/'fusion-scale').read_text(),'auto\n')
        self.assertEqual((self.app/'fusion-dpi').read_text(),'144\n')
        self.assertEqual(manager.fusion_scale.read_dpi(prefix),144)
        with patch.object(manager,'proton_versions',return_value=(None,[])),patch.object(manager,'discover_hidraw',return_value=[]),patch.object(manager,'discover',return_value=[]),patch.object(manager,'fusion_running',return_value=False):
            state=manager.status(self.app,REPO)
        self.assertTrue(state['prefix_exists']);self.assertEqual(state['scale_mode'],'auto');self.assertEqual(state['scale_percent'],150)

    def test_scale_action_updates_the_live_wine_registry_when_runtime_is_available(self):
        prefix=self.app/'chosen';prefix.joinpath('pfx').mkdir(parents=True)
        prefix.joinpath('pfx/user.reg').write_text('[Control Panel\\\\Desktop] 1\n"LogPixels"=dword:00000060\n[Software\\\\Wine\\\\Fonts] 1\n"LogPixels"=dword:00000060\n')
        calls=self.root/'scale-calls'
        (self.app/'run-proton.sh').write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{calls}"\n')
        with patch.object(manager,'fusion_running',return_value=False):
            self.action('scale',prefix='chosen',scale='150',screen_scale=1.0)
        self.assertEqual(calls.read_text().splitlines(),['--set-dpi','144'])
        self.assertEqual((self.app/'fusion-dpi').read_text(),'144\n')

    def test_update_keeps_existing_disabled_state_instead_of_forcing_enable(self):
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:self.action('update',spacemouse=True)
        command=[str(x) for x in run.call_args.args[0]]
        self.assertEqual(command,['bash',str(REPO/'install.sh'),'--update',str(self.app)])

    def test_install_passes_concrete_user_paths_without_shell_interpolation(self):
        installer=self.root/'installer $().exe';installer.touch()
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:
            self.action('install',prefix='custom',proton='/custom/Proton with spaces',installer=str(installer),spacemouse=True)
        command=[str(x) for x in run.call_args.args[0]]
        self.assertIn('--clean',command);self.assertIn('--with-spacemouse',command);self.assertIn(str(installer),command);self.assertIn('/custom/Proton with spaces',command)

    def marker(self, phase='installer-running', **overrides):
        state=dict(phase=phase,prefix='saved-prefix',proton_path='/saved/Proton with spaces',spacemouse=True,installer='/saved/installer.exe')
        state.update(overrides)
        (self.app/'clean-install.json').write_text(json.dumps(state))
        return state

    def manager_status(self):
        with patch.object(manager,'proton_versions',return_value=(None,[])),patch.object(manager,'discover_hidraw',return_value=[]),patch.object(manager,'discover',return_value=[]),patch.object(manager,'fusion_running',return_value=False):
            return manager.status(self.app,REPO)

    def test_legacy_installation_without_marker_is_not_changed(self):
        folder=self.app/'prefix/pfx/drive_c/users/user/AppData/Local/Autodesk/webdeploy/production/hash';folder.mkdir(parents=True)
        exe=folder/'Fusion360.exe';exe.touch();(self.app/'prefix-dir').write_text('prefix\n')
        before=sorted(str(p.relative_to(self.app)) for p in self.app.rglob('*'))
        state=self.manager_status()
        self.assertIsNone(state['clean_install']);self.assertEqual(state['fusion'],str(exe))
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:
            self.action('apply')
            self.assertIn('--apply-update',[str(x) for x in run.call_args.args[0]])
        self.assertEqual(before,sorted(str(p.relative_to(self.app)) for p in self.app.rglob('*')))

    def test_status_reports_all_marker_phases_and_uses_saved_prefix(self):
        (self.app/'prefix-dir').write_text('old-dialog-prefix\n')
        exe=self.app/'saved-prefix/pfx/drive_c/users/user/AppData/Local/Autodesk/webdeploy/production/hash/Fusion360.exe'
        exe.parent.mkdir(parents=True);exe.touch()
        for phase in ('prepared','prefix-ready','installer-running','installer-complete','complete'):
            with self.subTest(phase=phase):
                marker=self.marker(phase)
                state=self.manager_status()
                self.assertEqual(state['clean_install'],dict(marker,valid=True))
                self.assertEqual(state['prefix'],'old-dialog-prefix' if phase=='complete' else 'saved-prefix')
                if phase!='complete':
                    self.assertEqual(state['fusion'],str(exe))
                    self.assertEqual(state['proton_path'],'/saved/Proton with spaces')
                    self.assertEqual(state['proton'],'Proton with spaces')

    def test_invalid_markers_are_not_legacy_or_resumable(self):
        for content in ('not json','[]','{}',json.dumps(dict(phase='unknown',prefix='p',proton_path='/p',spacemouse=True)),
                        json.dumps(dict(phase='prepared',prefix='../outside',proton_path='/p',spacemouse=True)),
                        json.dumps(dict(phase='prepared',prefix='p',proton_path='/p',spacemouse='false'))):
            with self.subTest(content=content):
                (self.app/'clean-install.json').write_text(content)
                self.assertEqual(self.manager_status()['clean_install'],{'valid':False})
                with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:
                    for name in ('retry-installer','finish-install','clone','apply','launch','scale'):
                        with self.assertRaises(ValueError):self.action(name)
                    run.assert_not_called()

    def test_resume_requires_valid_marker_and_unchanged_confirmation(self):
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:
            for phase in ('prepared','prefix-ready','installer-running','installer-complete'):
                with self.subTest(phase=phase):
                    marker=self.marker(phase)
                    expected=json.dumps(dict(marker,valid=True))
                    self.action('retry-installer',expected_clean=expected,prefix='wrong',proton='/wrong',installer='/wrong.exe',spacemouse=False)
                    self.assertEqual([str(x) for x in run.call_args.args[0]],['bash',str(REPO/'install.sh'),'--resume-clean',str(self.app),'--retry-installer','--expected-clean-state',expected])
                    run.reset_mock()
                    if phase in ('installer-running','installer-complete'):
                        self.action('finish-install',expected_clean=expected)
                        self.assertEqual([str(x) for x in run.call_args.args[0]],['bash',str(REPO/'install.sh'),'--resume-clean',str(self.app),'--finish-install','--expected-clean-state',expected])
                        run.reset_mock()
                    else:
                        with self.assertRaisesRegex(ValueError,'not been started'):self.action('finish-install',expected_clean=expected)
                    self.marker(phase,installer='/changed/installer.exe')
                    with self.assertRaisesRegex(ValueError,'Refresh'):self.action('retry-installer',expected_clean=expected)
                    run.assert_not_called()
            self.marker('complete')
            with self.assertRaisesRegex(ValueError,'No valid unfinished'):self.action('retry-installer')
            (self.app/'clean-install.json').unlink()
            with self.assertRaisesRegex(ValueError,'No valid unfinished'):self.action('finish-install')
            run.assert_not_called()

    def test_incomplete_installation_blocks_other_mutations_and_running_fusion(self):
        state=self.marker();expected=json.dumps(dict(state,valid=True))
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run,patch.object(manager.subprocess,'Popen') as popen:
            for name in ('clone','install','patch','apply','update','launch','profile','scale','settings','camera','enable','disable','driver-start','driver-stop'):
                with self.subTest(name=name),self.assertRaisesRegex(ValueError,'unfinished'):self.action(name)
            run.assert_not_called();popen.assert_not_called()
        with patch.object(manager,'fusion_running',return_value=True),patch.object(manager,'run') as run:
            for name in ('retry-installer','finish-install'):
                with self.assertRaisesRegex(ValueError,'Close Fusion'):self.action(name,expected_clean=expected)
            run.assert_not_called()
        self.assertEqual(json.loads((self.app/'clean-install.json').read_text()),state)

    @unittest.skipUnless((REPO/'.build/manager/fusion-manager').exists(),'Build manager first')
    def test_qt_smoke_reads_interrupted_install_without_modifying_it(self):
        state=self.marker();before=(self.app/'clean-install.json').read_bytes()
        env=dict(os.environ,HOME=str(self.root),XDG_CONFIG_HOME=str(self.root/'config'),
                 XDG_DATA_HOME=str(self.root/'data'),XDG_RUNTIME_DIR=str(self.root),QT_QPA_PLATFORM='offscreen')
        result=subprocess.run([str(REPO/'.build/manager/fusion-manager'),'--backend',str(REPO/'scripts/manager_backend.py'),
                               '--target',str(self.app),'--repo',str(REPO),'--page','setup','--lang','de','--smoke-test'],
                              env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.app/'clean-install.json').read_bytes(),before)
        self.assertEqual(list(self.app.iterdir()),[self.app/'clean-install.json'])
        self.assertEqual(json.loads(before),state)

    @unittest.skipUnless((REPO/'.build/manager/resources.cpp').exists(),'Build manager first')
    def test_qt_resume_state_and_confirmation_are_explicit(self):
        # Exercise the actual widgets with an isolated status backend and no real action.
        source=self.root/'manager_ui_test.cpp';binary=self.root/'manager-ui-test'
        source.write_text('''#include <QThread>
#define main fusion_manager_application_main
#include "''' + str(REPO/'manager/main.cpp') + '''"
#undef main
int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setApplicationName("Fusion Manager");
    app.setOrganizationName("fusion-linux-dx11-test");
    I18n::setLanguage("de");
    Manager window(argv[1], argv[2], argv[3], "", false);
    window.selectPage(2);
    window.show();
    auto *headline = window.findChild<QLabel *>("installation-headline");
    auto *info = window.findChild<QLabel *>("installation-resume-info");
    auto *retry = window.findChild<QPushButton *>("action-retry-installer");
    auto *finish = window.findChild<QPushButton *>("action-finish-install");
    auto *proton = window.findChild<QComboBox *>("proton");
    if (!headline || !info || !retry || !finish || !proton) {
        qWarning() << "Missing widgets" << headline << info << retry << finish;
        return 6;
    }
    QElapsedTimer wait; wait.start();
    while (headline->text() == I18n::tr("Checking…") && wait.elapsed() < 8000) {
        app.processEvents(); QThread::msleep(10);
    }
    const QString phase = argv[4];
    const bool pending = phase != "complete" && phase != "legacy";
    if (headline->text() != I18n::tr(pending ? "Installation incomplete" : "●  Ready")) return 1;
    if (retry->isEnabled() != (pending && phase != "invalid")) return 2;
    if (finish->isEnabled() != (phase == "installer-running")) return 3;
    if (pending && phase != "invalid" && !info->text().contains("saved-prefix")) return 4;
    if (pending && phase != "invalid" && proton->currentData().toString() != "/saved/Proton") return 7;
    if (phase == "installer-running") {
        bool confirmed = false;
        QTimer::singleShot(0, [&] {
            auto *dialog = qobject_cast<QMessageBox *>(QApplication::activeModalWidget());
            if (dialog && dialog->defaultButton() && dialog->defaultButton()->text() == I18n::tr("Cancel") &&
                dialog->informativeText().contains("saved-prefix") && dialog->text().contains("erneut"))
                confirmed = true;
            if (dialog) dialog->reject();
        });
        retry->click();
        if (!confirmed) return 5;
    }
    return 0;
}
''')
        flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','Qt6Widgets'],text=True))
        subprocess.run(['c++','-O0','-std=c++17','-fPIC',str(source),str(REPO/'.build/manager/resources.cpp'),'-o',str(binary),*flags],check=True,capture_output=True,timeout=120)
        fake=self.root/'fake_backend.py';snapshot=self.root/'status.json';calls=self.root/'actions'
        fake.write_text('import pathlib,sys\nroot=pathlib.Path(__file__).parent\nif "--action" in sys.argv: (root/"actions").touch()\nprint((root/"status.json").read_text())\n')
        env=dict(os.environ,HOME=str(self.root),XDG_CONFIG_HOME=str(self.root/'config'),
                 XDG_RUNTIME_DIR=str(self.root),QT_QPA_PLATFORM='offscreen')
        for phase in ('prepared','installer-running','complete','invalid','legacy'):
            with self.subTest(phase=phase):
                clean=None if phase=='legacy' else {'valid':False} if phase=='invalid' else dict(
                    valid=True,phase=phase,prefix='saved-prefix',proton_path='/saved/Proton',spacemouse=True,installer='/saved/installer.exe')
                snapshot.write_text(json.dumps(dict(app=str(self.app),clean_install=clean,fusion='/fake/Fusion360.exe',
                                                     running=False,repo=dict(valid=True,path=str(REPO)),
                                                     device_config=manager.DEFAULTS)))
                result=subprocess.run([str(binary),str(fake),str(self.app),str(REPO),phase],env=env,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertFalse(calls.exists())
        self.assertEqual(list(self.app.iterdir()),[])

    def test_detached_checkout_is_still_a_real_checkout(self):
        checkout=self.root/'repo';subprocess.run(['git','init','-b','main',str(checkout)],check=True,capture_output=True)
        for key,value in [('user.name','Manager tests'),('user.email','tests@example.invalid')]:subprocess.run(['git','-C',str(checkout),'config',key,value],check=True)
        (checkout/'marker').write_text('current checkout\n');subprocess.run(['git','-C',str(checkout),'add','.'],check=True);subprocess.run(['git','-C',str(checkout),'commit','-m','test'],check=True,capture_output=True);subprocess.run(['git','-C',str(checkout),'checkout','--detach'],check=True,capture_output=True)
        state=manager.repository(checkout);self.assertTrue(state['valid']);self.assertEqual(state['branch'],'Detached HEAD');self.assertNotIn('version',state);self.assertFalse(state['dirty'])

    def test_missing_checkout_can_be_recreated_without_overwriting_files(self):
        publisher = self.root / 'publisher'
        subprocess.run(['git','init','-b','main',str(publisher)],check=True,capture_output=True)
        for key,value in [('user.name','Manager tests'),('user.email','tests@example.invalid')]:
            subprocess.run(['git','-C',str(publisher),'config',key,value],check=True)
        (publisher/'version').write_text('actual source')
        subprocess.run(['git','-C',str(publisher),'add','.'],check=True)
        subprocess.run(['git','-C',str(publisher),'commit','-m','test'],check=True,capture_output=True)
        (self.app/'repo-state.json').write_text(json.dumps(dict(remote=str(publisher),branch='main')))
        destination = self.root / 'restored checkout'
        self.args.action = 'clone'
        with contextlib.redirect_stdout(io.StringIO()):manager.action(self.args,self.app,destination)
        self.assertEqual((destination/'version').read_text(),'actual source')
        with self.assertRaises(ValueError):manager.action(self.args,self.app,destination)
        self.assertEqual((destination/'version').read_text(),'actual source')

    def test_old_driver_is_not_started_or_modified_from_source_gui_backend(self):
        (self.app/'spacemouse').mkdir()
        (self.app/'spacemouse/start.py').write_text('legacy driver supervisor')
        with patch.object(manager,'fusion_running',return_value=False),patch.object(manager,'run') as run:
            for name in ('driver-start','driver-stop','enable','disable'):
                with self.subTest(action=name),self.assertRaisesRegex(ValueError,'checkout'):self.action(name)
            run.assert_not_called()

    def test_access_setup_missing_pkexec_does_not_run_any_helper(self):
        with patch.object(manager.shutil,'which',return_value=None),patch.object(manager.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'pkexec is missing'):self.action('setup-access')
            run.assert_not_called()

    def test_access_setup_only_runs_fixed_helper_without_user_paths_or_arguments(self):
        helper=self.root/'fixed-helper';helper.touch();helper.chmod(0o755)
        with patch.object(manager.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(manager,'access_helper',return_value=helper),patch.object(manager.subprocess,'run',return_value=argparse.Namespace(returncode=0)) as run:
            self.action('setup-access',prefix='user-controlled',proton='/untrusted/user/path')
        run.assert_called_once_with(['/usr/bin/pkexec',str(helper)])

    def test_access_setup_cancel_or_denial_is_understandable(self):
        helper=self.root/'fixed-helper';helper.touch();helper.chmod(0o755)
        for code in (126,127):
            with self.subTest(code=code),patch.object(manager.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(manager,'access_helper',return_value=helper),patch.object(manager.subprocess,'run',return_value=argparse.Namespace(returncode=code)):
                with self.assertRaisesRegex(ValueError,'cancelled or denied'):self.action('setup-access')

    def test_access_setup_missing_helper_does_not_invoke_pkexec(self):
        with patch.object(manager.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(manager,'access_helper',return_value=self.root/'missing'),patch.object(manager.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'access helper is missing'):self.action('setup-access')
            run.assert_not_called()

    def test_status_identifies_raw_access_missing_despite_readable_evdev_fallback(self):
        hid=dict(path='/dev/hidraw-test',name='Receiver',backend='hidraw',readable=False)
        event=dict(path='/dev/event-test',name='Receiver',readable=True)
        with patch.object(manager,'discover_hidraw',return_value=[hid]),patch.object(manager,'discover',return_value=[event]),patch.object(manager,'proton_versions',return_value=(None,[])),patch.object(manager,'fusion_running',return_value=False):
            state=manager.status(self.app,REPO)
        self.assertTrue(state['input_access']['requires_setup']);self.assertFalse(state['input_access']['hid_readable'])
        self.assertTrue(state['input_access']['evdev_readable'])
        self.assertEqual([d['backend'] for d in state['devices']],['hidraw','evdev'])

    @unittest.skipUnless((REPO/'.build/manager/fusion-spacemouse-access').exists(),'Build manager first')
    def test_privileged_helper_rejects_all_arguments_before_any_effect(self):
        # No pkexec/elevation and no supported no-argument invocation here.
        target=self.root/'must-never-exist'
        result=subprocess.run([str(REPO/'.build/manager/fusion-spacemouse-access'),'--target',str(target)],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertIn('no arguments',result.stderr);self.assertFalse(target.exists())

    def test_other_steam_library_proton_is_discovered(self):
        steam=self.root/'.local/share/Steam';(steam/'steamapps').mkdir(parents=True)
        library=self.root/'other Steam library';proton_dir=library/'steamapps/common/Proton Test';proton_dir.mkdir(parents=True);(proton_dir/'proton').touch()
        (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+str(library)+'" } }')
        with patch.dict(os.environ,HOME=str(self.root)):
            found,versions=manager.proton_versions()
        self.assertEqual(found,str(steam));self.assertIn(dict(name='Proton Test',path=str(proton_dir)),versions)

    def test_custom_proton_is_valid_without_a_steam_root(self):
        custom=self.root/'Custom Proton';custom.mkdir();(custom/'proton').touch()
        with patch.dict(os.environ,HOME=str(self.root/'home without Steam')):
            self.assertEqual(proton.find('Not installed',custom),custom.resolve())

    def test_name_discovery_does_not_stop_at_the_first_steam_root(self):
        (self.root/'.local/share/Steam').mkdir(parents=True)
        folder=self.root/'.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Proton - Experimental'
        folder.mkdir(parents=True);(folder/'proton').touch()
        with patch.dict(os.environ,HOME=str(self.root)):
            self.assertEqual(proton.find('Proton - Experimental'),folder.resolve())


if __name__=='__main__':unittest.main()

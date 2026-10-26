import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
import manager_backend as manager


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=self.root/'Fusion user installation';self.app.mkdir()
        self.args=argparse.Namespace(action='status',prefix=None,proton=None,installer=None,spacemouse=False,settings=None,percent=None)

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
            for name in ('install','patch','apply','update','profile','enable','disable','launch'):
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

    def test_detached_checkout_is_still_a_real_checkout(self):
        checkout=self.root/'repo';subprocess.run(['git','init','-b','main',str(checkout)],check=True,capture_output=True)
        for key,value in [('user.name','Manager tests'),('user.email','tests@example.invalid')]:subprocess.run(['git','-C',str(checkout),'config',key,value],check=True)
        (checkout/'install.sh').write_text('VERSION="9.8.7"\n');subprocess.run(['git','-C',str(checkout),'add','.'],check=True);subprocess.run(['git','-C',str(checkout),'commit','-m','test'],check=True,capture_output=True);subprocess.run(['git','-C',str(checkout),'checkout','--detach'],check=True,capture_output=True)
        state=manager.repository(checkout);self.assertTrue(state['valid']);self.assertEqual(state['branch'],'Detached HEAD');self.assertEqual(state['version'],'9.8.7');self.assertFalse(state['dirty'])

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
                with self.subTest(action=name),self.assertRaisesRegex(ValueError,'Checkout'):self.action(name)
            run.assert_not_called()

    def test_access_setup_missing_pkexec_does_not_run_any_helper(self):
        with patch.object(manager.shutil,'which',return_value=None),patch.object(manager.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'pkexec fehlt'):self.action('setup-access')
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
                with self.assertRaisesRegex(ValueError,'abgebrochen oder nicht erteilt'):self.action('setup-access')

    def test_access_setup_missing_helper_does_not_invoke_pkexec(self):
        with patch.object(manager.shutil,'which',return_value='/usr/bin/pkexec'),patch.object(manager,'access_helper',return_value=self.root/'missing'),patch.object(manager.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'zugriffshelfer fehlt'):self.action('setup-access')
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
        self.assertEqual(result.returncode,2);self.assertIn('keine Argumente',result.stderr);self.assertFalse(target.exists())

    def test_other_steam_library_proton_is_discovered(self):
        steam=self.root/'.local/share/Steam';(steam/'steamapps').mkdir(parents=True)
        library=self.root/'other Steam library';proton=library/'steamapps/common/Proton Test';proton.mkdir(parents=True);(proton/'proton').touch()
        (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+str(library)+'" } }')
        with patch.dict(os.environ,HOME=str(self.root)):
            found,versions=manager.proton_versions()
        self.assertEqual(found,str(steam));self.assertIn(dict(name='Proton Test',path=str(proton)),versions)


if __name__=='__main__':unittest.main()

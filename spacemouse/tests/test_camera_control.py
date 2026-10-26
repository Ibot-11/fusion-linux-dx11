# SPDX-License-Identifier: GPL-3.0-or-later
import json
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import camera_control as control
import camera_gain


class CameraControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Path(self.temp.name)/'app';(self.app/'spacemouse').mkdir(parents=True)
        self.runtime=Path(self.temp.name)/'runtime'
        self.record=control.create_session(self.app,1,15,self.runtime)
        self.save(15)
        self.bridge=control.CameraControl(self.app,self.runtime)
        self.client=object();self.bridge.add(self.client)
        self.sent=[]

    def save(self,percent):
        (self.app/'spacemouse/camera-gain.json').write_text(json.dumps(camera_gain.percentage_settings(percent)))

    def hello(self,client=None,token=None,basis=1):
        words=struct.unpack('<4i',bytes.fromhex(token or self.record['token']))
        return control.PACKET.pack(5,1,*words,basis,123)

    def authenticate(self):
        raw=self.hello()
        self.assertTrue(self.bridge.receive(self.client,raw[:7]))
        self.assertTrue(self.bridge.receive(self.client,raw[7:]))

    def request(self,now=1.):
        self.bridge.tick(lambda client,data:self.sent.append((client,control.PACKET.unpack(data))),now)
        return self.sent[-1][1]

    def ack(self,packet,percent=None,status=0,now=1.1):
        reply=(7,*packet[1:6],status,packet[6] if percent is None else percent)
        self.assertTrue(self.bridge.receive(self.client,control.PACKET.pack(*reply),now))

    def test_session_is_private_app_bound_and_fresh_launch_changes_fingerprint(self):
        self.assertEqual((self.runtime/'camera-session.json').stat().st_mode&0o777,0o600)
        self.assertIsNone(control.session_record(self.app.parent/'other',self.runtime))
        old=control.fingerprint(self.record)
        new=control.create_session(self.app,2,40,self.runtime)
        self.assertNotEqual(old,control.fingerprint(new))

    def test_only_matching_hello_authenticates_fragmented_connection(self):
        self.assertFalse(self.bridge.receive(self.client,self.hello(token='00'*16)))
        self.bridge.remove(self.client);self.bridge.add(self.client)
        self.assertFalse(self.bridge.receive(self.client,self.hello(basis=4)))
        self.bridge.remove(self.client);self.bridge.add(self.client)
        self.authenticate();request=self.request()
        self.assertEqual(request[0],6);self.assertEqual(request[6:],(15,1))
        self.assertEqual(self.bridge.status(1.)['state'],'pending')
        self.ack(request)
        state=self.bridge.status(1.1)
        self.assertEqual((state['state'],state['percent'],state['pid']),('live',15,123))
        self.assertNotIn(self.record['token'],json.dumps(state))

    def test_foreign_stale_duplicate_and_unverified_values_never_confirm(self):
        self.authenticate();request=self.request()
        foreign=list(request);foreign[2]^=1
        self.ack(foreign);self.assertEqual(self.bridge.status(1.2)['state'],'pending')
        self.ack(request,percent=20);self.assertEqual(self.bridge.status(1.2)['state'],'pending')
        self.ack(request,now=2.);self.assertEqual(self.bridge.status(2.)['state'],'pending')
        retry=self.request(2.);self.assertNotEqual(request[1:6],retry[1:6])
        self.ack(request,now=2.1);self.assertEqual(self.bridge.status(2.1)['state'],'pending')
        self.ack(retry,now=2.1);self.assertEqual(self.bridge.status(2.1)['state'],'live')
        self.bridge.remove(self.client)
        self.assertEqual(self.bridge.status(2.2)['state'],'saved')

    def test_new_saved_basis_does_not_replace_actual_session_basis(self):
        self.authenticate();first=self.request();self.ack(first)
        self.save(100);new=self.request(1.3)
        self.assertEqual(new[6],100)
        self.assertEqual(self.bridge.record['basis'],1)
        self.assertEqual(self.bridge.status(1.3)['state'],'pending')
        self.ack(new,status=3,percent=0,now=1.4)
        self.assertEqual(self.bridge.status(1.4)['state'],'unsupported')

    def test_multiple_authenticated_clients_get_no_commands_and_no_live_claim(self):
        self.authenticate();other=object();self.bridge.add(other)
        self.assertTrue(self.bridge.receive(other,self.hello()))
        self.bridge.tick(lambda client,data:self.fail('ambiguous camera write'),1.)
        self.assertEqual(self.bridge.status(1.)['state'],'saved')

    def test_status_rejects_other_app_previous_session_and_stale_ack(self):
        self.authenticate();packet=self.request();self.ack(packet)
        live=self.bridge.status(1.1)
        driver=dict(app=str(self.app.resolve()),timestamp=time.time(),camera_live=live)
        self.assertEqual(control.selected_status(self.app,driver,15,self.runtime)['state'],'live')
        self.assertEqual(control.selected_status(self.app.parent/'other',driver,15,self.runtime)['state'],'saved')
        driver['camera_live']=dict(live,updated=time.time()-4)
        self.assertNotEqual(control.selected_status(self.app,driver,15,self.runtime)['state'],'live')
        driver['camera_live']=live
        control.create_session(self.app,1,15,self.runtime)
        self.assertEqual(control.selected_status(self.app,driver,15,self.runtime)['state'],'saved')

    def test_prepare_preserves_legacy_separate_gains_and_records_no_guessed_basis(self):
        gains=dict(pan=2,zoom=3,rotation=4,runtime_scale=.8)
        (self.app/'spacemouse/camera-gain.json').write_text(json.dumps(gains))
        with patch.object(camera_gain,'ROOT',self.app/'spacemouse'),patch.object(camera_gain,'apply_settings') as apply,patch('camera_control.runtime_dir',return_value=self.runtime):
            scale,basis,token=camera_gain.prepare_session()
        apply.assert_called_once_with(gains)
        self.assertEqual((scale,basis),(.8,0));self.assertEqual(len(token),32)

    def test_prepared_session_basis_is_actual_verified_native_factor(self):
        for percent,basis in ((15,1),(40,2),(60,3),(100,4)):
            gains=camera_gain.percentage_settings(percent)
            (self.app/'spacemouse/camera-gain.json').write_text(json.dumps(gains))
            with patch.object(camera_gain,'ROOT',self.app/'spacemouse'),patch.object(camera_gain,'apply_settings') as apply,patch('camera_control.runtime_dir',return_value=self.runtime):
                scale,actual_basis,token=camera_gain.prepare_session()
            apply.assert_called_once_with(gains)
            self.assertEqual(actual_basis,basis)
            self.assertAlmostEqual(scale*25*actual_basis,percent)

    def test_invalid_camera_json_does_not_break_full_manager_status(self):
        spec=importlib.util.spec_from_file_location('camera_test_backend',ROOT.parent/'scripts/manager_backend.py')
        backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
        (self.app/'spacemouse/camera-gain.json').write_text('[]')
        with patch.object(backend,'proton_versions',return_value=(None,[])),patch.object(backend,'discover',return_value=[]),patch.object(backend,'discover_hidraw',return_value=[]),patch.object(backend,'fusion_running',return_value=False):
            result=backend.status(self.app,None)
        self.assertEqual(result['camera'],{'percent':25})
        self.assertIn('Invalid saved camera',result['error'])

    def test_running_guard_prevents_all_xml_writes(self):
        with patch.object(camera_gain,'fusion_running',return_value=True),patch.object(camera_gain,'option_file') as option:
            with self.assertRaises(RuntimeError):camera_gain.apply_settings(camera_gain.percentage_settings(20))
        option.assert_not_called()


if __name__=='__main__':unittest.main()

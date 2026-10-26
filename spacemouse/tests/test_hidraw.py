import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evdev_input import DEFAULTS, PACKET
from hidraw_input import Decoder, MotionWatchdog, DESCRIPTOR_SHA256, discover, matches_profile
FIXTURE=ROOT/'tests/fixtures/universal-receiver-c652.bin'
FEATURE_FIXTURE=ROOT/'tests/fixtures/universal-receiver-c652-feature.bin'


def motion(values):return struct.pack('<B6h',1,*values)


class HidProfileTests(unittest.TestCase):
    def test_actual_descriptor_is_pinned_and_vendor_feature_interfaces_are_rejected(self):
        descriptor=FIXTURE.read_bytes()
        self.assertEqual(len(descriptor),448)
        self.assertEqual(hashlib.sha256(descriptor).hexdigest(),DESCRIPTOR_SHA256)
        self.assertTrue(matches_profile(descriptor,0x256f,0xc652))
        self.assertFalse(matches_profile(FEATURE_FIXTURE.read_bytes(),0x256f,0xc652))

    def test_changed_profile_wrong_bus_or_identity_are_never_accepted(self):
        descriptor=FIXTURE.read_bytes()
        self.assertFalse(matches_profile(descriptor[:-1],0x256f,0xc652))
        self.assertFalse(matches_profile(descriptor[:-1]+b'\x01',0x256f,0xc652))
        for vendor,product,bus in [(0x046d,0xc652,3),(0x256f,0xc653,3),(0x256f,0xc652,5)]:
            self.assertFalse(matches_profile(descriptor,vendor,product,bus))

    def test_discovery_checks_actual_descriptor_instead_of_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sysfs=root/'sysfs';dev=root/'dev';dev.mkdir()
            for index,descriptor,vendor in [(0,FIXTURE.read_bytes(),'256F'),(1,FEATURE_FIXTURE.read_bytes(),'256F'),(2,FIXTURE.read_bytes(),'1234')]:
                base=sysfs/f'hidraw{index}'/'device';base.mkdir(parents=True)
                (base/'uevent').write_text(f'HID_ID=0003:0000{vendor}:0000C652\nHID_NAME=Misleading keyboard name\n')
                (base/'report_descriptor').write_bytes(descriptor);(dev/f'hidraw{index}').touch()
            devices=discover(sysfs,dev)
            self.assertEqual([Path(d['path']).name for d in devices],['hidraw0'])
            self.assertEqual(devices[0]['backend'],'hidraw');self.assertTrue(devices[0]['readable'])

    def test_all_six_axes_full_signed_counts_and_native_mapping(self):
        decoder=Decoder()
        self.assertEqual(list(decoder.feed(motion([1,-1,350,-350,2,-2]),1.)),
                         [('motion',[1,-350,1,-350,2,-2],0)])
        self.assertEqual(list(decoder.feed(motion([-1,1,-350,350,-2,2]),1.016)),
                         [('motion',[-1,350,-1,350,-2,2],16)])

    def test_identical_hid_reports_and_every_neighbor_count_are_forwarded(self):
        decoder=Decoder();values=[]
        for i in range(-350,351):values.append(list(decoder.feed(motion([i,0,0,0,0,0]),1+(i+350)*.016))[0][1][0])
        self.assertEqual(values,list(range(-350,351)))
        repeated=motion([17]*6)
        self.assertEqual(list(decoder.feed(repeated,20.))[0][1],list(decoder.feed(repeated,20.016))[0][1])

    def test_buttons_independent_release_and_no_duplicate_down(self):
        decoder=Decoder()
        self.assertEqual(list(decoder.feed(b'\x03\x01\x00')),[('button',0,True)])
        self.assertEqual(list(decoder.feed(b'\x03\x01\x00')),[])
        self.assertEqual(list(decoder.feed(b'\x03\x03\x00')),[('button',1,True)])
        self.assertEqual(list(decoder.feed(b'\x03\x00\x00')),[('button',0,False),('button',1,False)])

    def test_short_or_out_of_range_report_cannot_partially_replace_state(self):
        decoder=Decoder();list(decoder.feed(motion([1,2,3,4,5,6]),1.))
        for report in [b'\x01'+b'\x00'*11,b'\x01'+b'\x00'*13,motion([351,0,0,0,0,0]),b'\x03\x04\x00']:
            with self.subTest(report=report),self.assertRaises(ValueError):list(decoder.feed(report,2.))
            self.assertEqual(decoder.raw,[1,2,3,4,5,6]);self.assertEqual(decoder.last_motion,1.)

    def test_battery_status_and_unknown_reports_never_emit_motion(self):
        decoder=Decoder();list(decoder.feed(motion([1]*6),1.))
        for report in (b'\x17\x50\x01',b'\x1b\x01',b'\x11\x00',b'\xff\x01'):
            self.assertEqual(list(decoder.feed(report,100.)),[])
        self.assertEqual(decoder.last_motion,1.)
        self.assertEqual(decoder.telemetry,dict(battery_strength=80,vendor_27_bit=1,vendor_28_bit=1))
        self.assertEqual(decoder.ignored_reports,2)

    def test_watchdog_is_250ms_one_shot_and_only_motion_renews_it(self):
        decoder=Decoder();guard=MotionWatchdog()
        event=list(decoder.feed(motion([17,0,0,0,0,0]),1.))[0];guard.motion(event[1],1.)
        for stamp,report in [(1.1,b'\x17\x50\x00'),(1.2,b'\x1b\x01'),(1.249,b'\x03\x01\x00')]:
            for kind,axes,_period in decoder.feed(report,stamp):
                if kind=='motion':guard.motion(axes,stamp)
        self.assertFalse(guard.due(1.249));self.assertTrue(guard.due(1.250));self.assertFalse(guard.due(100.))
        self.assertEqual(list(decoder.neutralize()),[('button',0,False),('motion',[0]*6,0)])
        self.assertEqual(decoder.raw,[0]*6)
        guard.motion([1]*6,3.);guard.motion([1]*6,3.2)
        self.assertFalse(guard.due(3.3));self.assertTrue(guard.due(3.451))

    def test_neutral_report_cancels_watchdog_and_usb_disconnect_releases(self):
        guard=MotionWatchdog();guard.motion([1]*6,1.);guard.motion([0]*6,1.1)
        self.assertFalse(guard.due(100.))
        decoder=Decoder();list(decoder.feed(motion([1]*6),1.));list(decoder.feed(b'\x03\x03\x00'))
        with self.assertRaises(OSError):list(decoder.feed(b''))
        self.assertEqual(list(decoder.neutralize()),[('button',0,False),('button',1,False),('motion',[0]*6,0)])


def run_hid_driver(reader,writer,root,runtime,port):
    os.close(writer)
    spec=importlib.util.spec_from_file_location('fusion_hid_test_driver',ROOT/'start.py')
    driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
    driver.ROOT=Path(root);driver.RUNTIME=Path(runtime);driver.PORT=port
    driver.discover_hidraw=lambda:[dict(path='test-hidraw',name='Fixture Universal Receiver',backend='hidraw',readable=True)]
    driver.discover=lambda:[dict(path='unused-event-fallback',name='Unused event fallback',readable=True)]
    def open_input(candidate):
        if candidate['backend']!='hidraw':raise OSError('HID must be preferred')
        return os.dup(reader)
    driver.open_input=open_input
    os.environ.pop('NOTIFY_SOCKET',None)
    raise SystemExit(driver.main())


class HidDaemonTests(unittest.TestCase):
    def test_camera_ack_traffic_never_renews_hid_motion_watchdog(self):
        from camera_control import create_session
        from camera_gain import percentage_settings
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)/'app';root=app/'spacemouse';root.mkdir(parents=True)
            runtime=Path(tmp)/'runtime';record=create_session(app,1,15,runtime)
            (root/'device.json').write_text(json.dumps(dict(DEFAULTS)))
            (root/'camera-gain.json').write_text(json.dumps(percentage_settings(15)))
            reader,writer=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            child=multiprocessing.get_context('fork').Process(target=run_hid_driver,args=(reader.fileno(),writer.fileno(),str(root),str(runtime),port))
            child.start();reader.close();client=socket.socket();client.settimeout(.03)
            try:
                deadline=time.monotonic()+3
                while True:
                    try:client.connect(('127.0.0.1',port));break
                    except (ConnectionRefusedError,ConnectionAbortedError):
                        if time.monotonic()>deadline:raise
                        time.sleep(.01)
                client.sendall(PACKET.pack(5,1,*struct.unpack('<4i',bytes.fromhex(record['token'])),1,123))
                writer.send(motion([1,0,0,0,0,0]))
                start=time.monotonic();buffer=b'';acks=0;neutral=None;last_target=0
                while time.monotonic()-start<.45:
                    elapsed=time.monotonic()-start;target=15+int(elapsed/.06)
                    if target!=last_target:
                        (root/'camera-gain.json').write_text(json.dumps(percentage_settings(target)));last_target=target
                    try:buffer+=client.recv(4096)
                    except socket.timeout:continue
                    while len(buffer)>=PACKET.size:
                        packet=PACKET.unpack(buffer[:PACKET.size]);buffer=buffer[PACKET.size:]
                        if packet[0]==6:
                            client.sendall(PACKET.pack(7,*packet[1:6],0,packet[6]));acks+=1
                        elif packet[0]==0 and packet[1:7]==(0,)*6:
                            neutral=time.monotonic()-start
                self.assertGreaterEqual(acks,2)
                self.assertIsNotNone(neutral);self.assertLess(neutral,.4)
                self.assertTrue(json.loads((runtime/'status.json').read_text())['motion_watchdog'])
            finally:
                writer.close();client.close();child.terminate();child.join(3)
                if child.is_alive():child.kill();child.join()
            self.assertEqual(child.exitcode,0)

    def test_real_hid_report_boundaries_tcp_no_repeat_watchdog_metadata_and_usb_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'device.json').write_text(json.dumps(dict(DEFAULTS)))
            reader,writer=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            child=multiprocessing.get_context('fork').Process(target=run_hid_driver,args=(reader.fileno(),writer.fileno(),str(root),str(root/'runtime'),port))
            child.start();reader.close();client=socket.socket();client.settimeout(2)
            try:
                deadline=time.monotonic()+3
                while True:
                    try:client.connect(('127.0.0.1',port));break
                    except (ConnectionRefusedError,ConnectionAbortedError):
                        if time.monotonic()>deadline:raise
                        time.sleep(.01)
                def packet():
                    data=b''
                    while len(data)<PACKET.size:
                        chunk=client.recv(PACKET.size-len(data))
                        if not chunk:raise EOFError('daemon closed socket')
                        data+=chunk
                    return PACKET.unpack(data)
                report=motion([1,2,3,-4,-5,-6]);writer.send(report)
                self.assertEqual(packet(),(0,1,-3,-2,-4,6,5,0))
                client.settimeout(.035)
                with self.assertRaises(socket.timeout):packet()  # no synthetic HID repeat
                client.settimeout(2);writer.send(report)
                self.assertEqual(packet()[1:7],(1,-3,-2,-4,6,5))
                writer.send(b'\x03\x01\x00');self.assertEqual(packet(),(4,0,1,0,27,0,0,0))
                for i in range(5):
                    writer.send(b'\x17\x50\x01');writer.send(b'\x1b\x01');time.sleep(.06)
                self.assertEqual(packet(),(0,0,0,0,0,0,0,0))
                self.assertEqual(packet(),(4,0,0,0,27,0,0,0))
                deadline=time.monotonic()+1
                while True:
                    state=json.loads((root/'runtime/status.json').read_text())
                    if state['motion_watchdog'] or time.monotonic()>deadline:break
                    time.sleep(.01)
                self.assertEqual(state['input_backend'],'hidraw');self.assertTrue(state['motion_watchdog'])
                self.assertEqual(state['telemetry']['battery_strength'],80)
                self.assertEqual(state['raw'],[0]*6)
                client.settimeout(.03)
                with self.assertRaises(socket.timeout):packet()  # one neutral event only
                client.settimeout(2);writer.send(motion([0]*6));self.assertEqual(packet()[1:7],(0,)*6)
                writer.send(b'\x03\x02\x00');self.assertEqual(packet(),(4,1,1,1,73,0,0,0))
                writer.close()
                self.assertEqual(packet(),(0,0,0,0,0,0,0,0));self.assertEqual(packet(),(4,1,0,1,73,0,0,0))
            finally:
                writer.close();client.close();child.terminate();child.join(3)
                if child.is_alive():child.kill();child.join()
            self.assertEqual(child.exitcode,0)


if __name__=='__main__':unittest.main()

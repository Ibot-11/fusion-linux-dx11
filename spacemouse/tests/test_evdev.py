import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evdev_input import Decoder, DEFAULTS, EVENT, HeldMotion, PACKET, discover, settings, transform


def event(kind, code, value, stamp=1000000):
    return EVENT.pack(stamp // 1000000, stamp % 1000000, kind, code, value)


def report(values, stamp=1000000):
    return b''.join(event(3, i, value, stamp) for i, value in enumerate(values)) + event(0, 0, 0, stamp)


class InputTests(unittest.TestCase):
    def test_all_axes_and_native_signed_counts(self):
        decoder = Decoder()
        self.assertEqual(list(decoder.feed(report([1, 2, 3, -4, -5, -350]))),
                         [('motion', [1, -3, -2, -4, 350, 5], 0)])
        self.assertEqual(transform([-350, 350, -1, 1, -349, 349], DEFAULTS),
                         [-350, 1, -350, 1, -349, 349])

    def test_no_frame_before_syn_and_fragmented_reads(self):
        decoder = Decoder()
        data = event(3, 0, 17)
        self.assertEqual(list(decoder.feed(data[:3])), [])
        self.assertEqual(list(decoder.feed(data[3:])), [])
        self.assertEqual(list(decoder.feed(event(0, 0, 0))), [('motion', [17, 0, 0, 0, 0, 0], 0)])

    def test_abs_unmentioned_axes_keep_their_state_and_zero_stops(self):
        decoder = Decoder()
        list(decoder.feed(report([1, 2, 3, 4, 5, 6])))
        result = list(decoder.feed(event(3, 1, 0, 1008000) + event(0, 0, 0, 1008000)))
        self.assertEqual(result, [('motion', [1, -3, 0, 4, -6, -5], 8)])
        self.assertEqual(list(decoder.feed(report([0]*6, 1016000))), [('motion', [0]*6, 8)])

    def test_every_original_frame_and_neighboring_count_survives(self):
        decoder = Decoder()
        frames = list(decoder.feed(b''.join(report([i, 0, 0, 0, 0, 0], 1000000+i*8000) for i in range(351))))
        self.assertEqual([x[1][0] for x in frames], list(range(351)))
        self.assertEqual(len(frames), 351)

    def test_syn_dropped_discards_partial_axes_and_recovers_buttons(self):
        decoder = Decoder(recover=lambda: ([7, 8, 9, 10, 11, 12], [False, True]))
        list(decoder.feed(event(1, 256, 1)))
        data = event(3, 0, 99) + event(0, 3, 0) + event(3, 1, 888) + event(1, 257, 1) + event(0, 0, 0)
        self.assertEqual(list(decoder.feed(data)), [('button', 0, False), ('button', 1, True), ('motion', [7, -9, -8, 10, -12, -11], 0)])

    def test_buttons_repeat_ignored_and_independent(self):
        decoder = Decoder()
        data = event(1,256,1)+event(1,256,2)+event(1,256,1)+event(1,257,1)+event(1,256,0)+event(1,257,0)
        self.assertEqual(list(decoder.feed(data)), [('button',0,True),('button',1,True),('button',0,False),('button',1,False)])

    def test_deadzone_and_explicit_axis_options(self):
        config = dict(DEFAULTS, deadzone=1, enabled=[True,False,True,True,True,True], inverted=[True,False,False,False,False,False])
        self.assertEqual(transform([2, 1, 99, 1, 0, 0], config), [-2,0,0,0,0,0])

    def test_config_rejects_invalid_and_defaults_are_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'device.json'
            self.assertEqual(settings(path)['deadzone'], 0)
            path.write_text('{"deadzone": -1}')
            with self.assertRaises(ValueError): settings(path)
            path.write_text('{"buttons": ["SHELL", "I"]}')
            with self.assertRaises(ValueError): settings(path)

    def test_keyboard_without_six_absolute_axes_is_never_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, bitmap, vendor in [('event1','0','256f'),('event2','3f','256f'),('event3','3f','1234')]:
                base = root/name/'device'
                (base/'id').mkdir(parents=True); (base/'capabilities').mkdir()
                (base/'name').write_text('SpaceMouse Buttons Virtual Keyboard' if name=='event1' else '3Dconnexion Universal Receiver')
                (base/'id/vendor').write_text(vendor); (base/'id/product').write_text('c652'); (base/'capabilities/abs').write_text(bitmap)
            self.assertEqual([Path(d['path']).name for d in discover(root,root)], ['event2'])

    def test_held_state_continues_without_new_abs_reports_and_stops(self):
        held = HeldMotion()
        for i in range(3):
            held.update([17, 0, 0, 0, 0, 0], 8, 1. + i * .008)
        # A small grace avoids a repeat racing the next real hardware report.
        self.assertIsNone(held.due(1.024))
        self.assertEqual(held.due(1.025), ('motion', [17, 0, 0, 0, 0, 0], 8))
        self.assertEqual(held.due(1.034), ('motion', [17, 0, 0, 0, 0, 0], 8))
        held.update([0]*6, 8, 1.035)
        self.assertIsNone(held.due(100))

    def test_no_catchup_batch_and_real_samples_replace_repeat_state(self):
        held = HeldMotion()
        held.update([1]*6, 0, 1.)
        self.assertIsNotNone(held.due(10.))
        self.assertIsNone(held.due(10.))
        held.update([2]*6, 0, 10.001)
        self.assertIsNone(held.due(10.017))
        self.assertEqual(held.due(10.019)[1], [2]*6)

    def test_suppressed_duplicates_do_not_slow_held_motion_cadence(self):
        held = HeldMotion()
        for i in range(3):
            held.update([1]*6, 16.01, i * .01601)
        before = held.interval
        for i in range(30):
            held.update([2]*6, 32.02, 1 + i * .03202)
        self.assertAlmostEqual(held.interval, before)
        # New real input immediately replaces the held state and its timer.
        held.update([3]*6, 16.01, 3.)
        self.assertIsNone(held.due(3.0165))
        self.assertEqual(held.due(3.018)[1], [3]*6)


def run_driver(read_fd, write_fd, root, runtime, port):
    os.close(write_fd)
    spec=importlib.util.spec_from_file_location('fusion_driver',ROOT/'start.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ROOT=Path(root);module.RUNTIME=Path(runtime);module.PORT=port
    module.discover_hidraw=lambda:[]
    module.discover=lambda:[{'path':f'/proc/self/fd/{read_fd}','name':'Test SpaceMouse','readable':True}]
    module.axis_state=lambda _fd:[0]*6
    module.button_state=lambda _fd:[False,False]
    os.environ.pop('NOTIFY_SOCKET',None)
    raise SystemExit(module.main())


class DaemonTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','Linux evdev only')
    def test_real_pipe_parser_tcp_buttons_stop_and_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'device.json').write_text(json.dumps(dict(DEFAULTS)))
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            read_fd,write_fd=os.pipe()
            context=multiprocessing.get_context('fork')
            process=context.Process(target=run_driver,args=(read_fd,write_fd,str(root),str(root/'runtime'),port))
            process.start();os.close(read_fd)
            client=socket.socket();client.settimeout(.2)
            try:
                deadline=time.monotonic()+4
                while True:
                    try:client.connect(('127.0.0.1',port));break
                    except (ConnectionRefusedError,ConnectionAbortedError):
                        if time.monotonic()>deadline:raise
                        time.sleep(.02)
                client.settimeout(2)
                def packet():
                    data=b''
                    while len(data)<PACKET.size:data+=client.recv(PACKET.size-len(data))
                    return PACKET.unpack(data)
                os.write(write_fd,report([1,2,3,4,5,6]))
                self.assertEqual(packet(),(0,1,-3,-2,4,-6,-5,0))
                self.assertEqual(packet()[1:7],(1,-3,-2,4,-6,-5))  # held state
                os.write(write_fd,report([0]*6,1008000))
                while packet()[1:7]!=(0,0,0,0,0,0):pass
                os.write(write_fd,event(1,256,1)+event(1,256,2)+event(1,256,0)+event(1,257,1)+event(1,257,0))
                self.assertEqual([packet()[:3] for _ in range(4)],[(3,27,1),(3,27,0),(3,73,1),(3,73,0)])
                config=dict(DEFAULTS,buttons=['ESC','ESC'])
                (root/'device.json').write_text(json.dumps(config))
                time.sleep(1.1)  # wait for the daemon's documented reload interval
                os.write(write_fd,event(1,256,1)+event(1,257,1)+event(1,256,0))
                self.assertEqual(packet()[:3],(3,27,1))
                client.settimeout(.05)
                with self.assertRaises(socket.timeout):packet()  # right still holds ESC
                client.settimeout(2)
                os.write(write_fd,event(1,257,0))
                self.assertEqual(packet()[:3],(3,27,0))
                os.write(write_fd,event(1,256,1));self.assertEqual(packet()[:3],(3,27,1))
                (root/'device.json').write_text(json.dumps(dict(DEFAULTS,buttons=['I','ESC'])))
                time.sleep(1.1)
                os.write(write_fd,event(1,256,0));self.assertEqual(packet()[:3],(3,27,0))  # original binding released
                os.write(write_fd,event(1,256,1));self.assertEqual(packet()[:3],(3,73,1))
                os.close(write_fd);write_fd=None
                self.assertEqual(packet(),(0,0,0,0,0,0,0,0))
                self.assertEqual(packet()[:3],(3,73,0))
            finally:
                if write_fd is not None:os.close(write_fd)
                client.close();process.terminate();process.join(3)
                if process.is_alive():process.kill();process.join()
            self.assertEqual(process.exitcode,0)


if __name__=='__main__':unittest.main()

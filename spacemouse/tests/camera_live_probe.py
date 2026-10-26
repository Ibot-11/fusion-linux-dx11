"""Optional private Proton/daemon/backend integration; never starts Fusion.

Build camera-live-probe.exe + DLL with FUSION_BRIDGE_PORT=11113 in TEST_RUNTIME.
Set TEST_PROTON_RUNNER to a dedicated prefix/display runner and TEST_FUSION_PE
to the original NuBase10.dll (read only). No real input device is opened.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from camera_control import create_session,selected_status
from camera_gain import percentage_settings


def driver(app,runtime,port):
    spec=importlib.util.spec_from_file_location('private_camera_driver',ROOT/'start.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ROOT=Path(app)/'spacemouse';module.RUNTIME=Path(runtime);module.PORT=port
    module.discover=lambda:[];module.discover_hidraw=lambda:[]
    os.environ.pop('NOTIFY_SOCKET',None)
    raise SystemExit(module.main())


def main():
    runtime=Path(os.environ['TEST_RUNTIME']).resolve()
    for name in ('probe-command','probe-state.json','camera-live-probe.log'):(runtime/name).unlink(missing_ok=True)
    pe=Path(os.environ['TEST_FUSION_PE']).resolve()
    spec=importlib.util.spec_from_file_location('private_manager_backend',ROOT.parent/'scripts/manager_backend.py')
    backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
    with tempfile.TemporaryDirectory(prefix='fusion-camera-probe-') as temp:
        app=Path(temp)/'app';(app/'spacemouse').mkdir(parents=True)
        state_dir=Path(temp)/'state';state_dir.mkdir()
        (app/'spacemouse/camera-gain.json').write_text(json.dumps(percentage_settings(15)))
        xml=app/'untouched-camera-options.xml';xml.write_text('<untouched/>')
        session=create_session(app,1,15,state_dir)
        child=multiprocessing.get_context('fork').Process(target=driver,args=(app,state_dir,int(os.environ.get('TEST_PORT','11113'))))
        child.start()
        proc=subprocess.Popen([os.environ['TEST_PROTON_RUNNER'],str(runtime/'camera-live-probe.exe'),
                               'Z:'+str(pe).replace('/','\\'),session['token'],'1'],cwd=runtime,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        sequence=0
        def wait(predicate,label):
            until=time.monotonic()+8
            while time.monotonic()<until:
                try:
                    value=predicate()
                    if value:return value
                except (OSError,ValueError):pass
                if proc.poll() is not None:raise AssertionError((label,proc.returncode))
                time.sleep(.04)
            raise AssertionError(label)
        def state():return json.loads((state_dir/'status.json').read_text())
        def command(name):
            nonlocal sequence
            sequence+=1;(runtime/'probe-command').write_text(f'{sequence} {name}')
            if name!='stop':wait(lambda:json.loads((runtime/'probe-state.json').read_text())['sequence']==sequence,name)
        def apply(percent):
            output=io.StringIO()
            with patch.object(backend,'fusion_running',return_value=True),patch.object(backend,'runtime_dir',return_value=state_dir),patch('camera_control.runtime_dir',return_value=state_dir),contextlib.redirect_stdout(output):
                backend.action(argparse.Namespace(action='camera',percent=percent),app,None)
            print(output.getvalue().strip())
        try:
            wait(lambda:state().get('camera_live',{}).get('state')=='unsupported','late-module status')
            assert 'not loaded' in state()['camera_live']['reason']
            command('load')
            wait(lambda:state()['camera_live'].get('state')=='live','late-module retry')
            for percent in (100,1,20,75,15):
                apply(percent)
                live=selected_status(app,state(),percent,state_dir)
                assert live['state']=='live' and live['percent']==percent,live
                observed=wait(lambda:abs(json.loads((runtime/'probe-state.json').read_text())['normalizer']-1024.*25/percent)<1e-8,'actual data value')
                assert observed
                assert json.loads((runtime/'probe-state.json').read_text())['background']
            # A bridge restart must establish a fresh challenged ACK, rather
            # than carrying the disconnected client's previous live claim.
            child.terminate();child.join(3);assert child.exitcode==0
            child=multiprocessing.get_context('fork').Process(target=driver,args=(app,state_dir,int(os.environ.get('TEST_PORT','11113'))))
            child.start()
            wait(lambda:state().get('pid')==child.pid and state().get('camera_live',{}).get('state')=='live','authenticated reconnect')
            before=json.loads((runtime/'probe-state.json').read_text())['normalizer']
            command('tamper');apply(30)
            wait(lambda:state()['camera_live'].get('state')=='unsupported','unknown build')
            assert json.loads((runtime/'probe-state.json').read_text())['normalizer']==before
            command('restore-code');apply(20)
            assert selected_status(app,state(),20,state_dir)['state']=='live'
            command('conflict');apply(40)
            assert 'outside' in state()['camera_live']['reason']
            assert json.loads((runtime/'probe-state.json').read_text())['normalizer']==512.
            assert xml.read_text()=='<untouched/>'
            command('stop')
            stdout,_=proc.communicate(timeout=8);print(stdout)
            assert proc.returncode==0,proc.returncode
            print((runtime/'camera-live-probe.log').read_text())
        finally:
            if proc.poll() is None:
                (runtime/'probe-command').write_text(f'{sequence+1} stop')
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=5)
            child.terminate();child.join(3)
            if child.is_alive():child.kill();child.join()
        assert child.exitcode==0,child.exitcode


if __name__=='__main__':main()

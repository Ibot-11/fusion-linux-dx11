import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime_fixture import make_runtime
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'scripts'))
import fusion_runtime


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root/'app'
        self.app.mkdir()
        self.runtime = make_runtime(self.root/'runtime')

    def test_stock_proton_is_never_accepted_as_a_fusion_runtime(self):
        stock = self.root/'stock'
        stock.mkdir()
        (stock/'proton').write_text('#!/bin/sh\nexit 0\n')
        with self.assertRaises(ValueError): fusion_runtime.bind(self.app, stock)
        self.assertEqual(list(self.app.iterdir()), [])

    def test_runtime_binding_detects_modified_module_before_execution(self):
        fusion_runtime.bind(self.app, self.runtime)
        saved = (self.app/'runtime-lock.json').read_bytes()
        module = self.runtime/'files/lib/wine/x86_64-unix/winex11.so'
        module.write_bytes(b'changed module')
        with self.assertRaisesRegex(ValueError, 'verification'):
            fusion_runtime.resolve(self.app)
        self.assertEqual((self.app/'runtime-lock.json').read_bytes(), saved)

    def test_active_binding_does_not_follow_a_changed_current_symlink(self):
        current = self.root/'current'
        current.symlink_to(self.runtime, target_is_directory=True)
        fusion_runtime.bind(self.app, current)
        replacement = make_runtime(self.root/'replacement')
        current.unlink(); current.symlink_to(replacement, target_is_directory=True)
        self.assertEqual(fusion_runtime.resolve(self.app)['path'], str(self.runtime))

    def test_metadata_change_requires_explicit_rebind(self):
        fusion_runtime.bind(self.app, self.runtime)
        file = self.runtime/'fusion-runtime.json'
        manifest = json.loads(file.read_text()); manifest['build_id']='different'
        file.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'pinned'):
            fusion_runtime.resolve(self.app)

    def test_malformed_capabilities_are_reported_as_invalid(self):
        file = self.runtime/'fusion-runtime.json'
        manifest = json.loads(file.read_text()); manifest['features']=[]
        file.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): fusion_runtime.validate(self.runtime)

    def test_launcher_removes_only_the_legacy_fusion_layer(self):
        capture = self.root/'environment.json'
        (self.runtime/'proton').write_text('#!/usr/bin/env python3\nimport json,os\nopen(os.environ["CAPTURE"],"w").write(json.dumps(dict(os.environ)))\n')
        make_runtime(self.runtime)
        fusion_runtime.bind(self.app,self.runtime)
        for name in ('fusion_runtime.py','proton.py'):
            shutil.copy2(REPO/'scripts'/name,self.app/name)
        env = dict(os.environ,FUSION_APP_DIR=str(self.app),CAPTURE=str(capture),
                   VK_INSTANCE_LAYERS='OTHER:VK_LAYER_FUSION_present_sync:ANOTHER',VK_LAYER_PATH='/custom/layers')
        result = subprocess.run(['bash',str(REPO/'scripts/run-proton.sh'),'Fusion360.exe'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        actual=json.loads(capture.read_text())
        self.assertEqual(actual['VK_INSTANCE_LAYERS'],'OTHER:ANOTHER')
        self.assertEqual(actual['VK_LAYER_PATH'],'/custom/layers')
        self.assertNotIn('bcp47langs=',actual.get('WINEDLLOVERRIDES',''))


if __name__ == '__main__': unittest.main()

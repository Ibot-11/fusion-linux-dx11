import json
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from keybindings import MODIFIER_BITS, NAMED_KEYS, LEGACY, canonical_key, normalize_binding, button_packet
from evdev_input import settings


def packet(index,down,binding):return struct.unpack('<8i',button_packet(index,down,binding))


class BindingTests(unittest.TestCase):
    def test_existing_saved_bindings_remain_valid(self):
        for key in LEGACY:self.assertEqual(normalize_binding(key),key)
        self.assertIsNone(button_packet(0,True,'off'))
        self.assertEqual(packet(1,False,'sdk'),(2,1,0,0,0,0,0,0))

    def test_printable_custom_key_and_modifier_chord(self):
        binding={'key':'s','modifiers':['shift','ctrl']}
        self.assertEqual(normalize_binding(binding),{'key':'S','modifiers':['CTRL','SHIFT']})
        self.assertEqual(packet(1,True,binding),(4,1,1,1,ord('S'),3,0,0))
        self.assertEqual(packet(1,False,binding),(4,1,0,1,ord('S'),3,0,0))

    def test_modifier_only_and_altgr_chords(self):
        self.assertEqual(packet(0,True,{'key':'CTRL','modifiers':[]}),(4,0,1,0,0,1,0,0))
        self.assertEqual(packet(0,True,{'key':'SHIFT','modifiers':['CTRL']}),(4,0,1,0,0,3,0,0))
        self.assertEqual(packet(0,True,{'key':'ALTGR','modifiers':['CTRL']}),(4,0,1,0,0,17,0,0))

    def test_named_keys_f1_through_f24_and_extended_flags(self):
        for name,(vk,extended) in NAMED_KEYS.items():
            with self.subTest(name=name):
                self.assertEqual(packet(0,True,{'key':name,'modifiers':[]}),(4,0,1,0,vk,0,int(extended),0))
        self.assertEqual(canonical_key(' '),'SPACE')
        self.assertEqual(packet(0,True,'HOME'),(4,0,1,0,0x24,0,1,0))

    def test_unicode_bmp_punctuation_and_spaces_are_logical_keys(self):
        for key in ('ä','Ö','ß','+','?','漢'):
            self.assertEqual(packet(0,True,{'key':key,'modifiers':['ALTGR']})[3:6],(1,ord(key),16))

    def test_malformed_config_rejected(self):
        invalid=[None,True,3,[],{},'A','F25',{'key':'S'}, {'modifiers':[]},
                 {'key':'S','modifiers':[],'command':'shell'}, {'key':'S','modifiers':'CTRL'},
                 {'key':'S','modifiers':['CTRL','ctrl']},{'key':'S','modifiers':['SUPER']},
                 {'key':'S','modifiers':[1]},{'key':'','modifiers':[]},
                 {'key':'two keys','modifiers':[]},{'key':'😀','modifiers':[]},
                 {'key':'\ud800','modifiers':[]},{'key':'\n','modifiers':[]},
                 {'key':'\x00','modifiers':[]},{'key':'\x7f','modifiers':[]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):normalize_binding(value)

    def test_settings_roundtrip_keeps_object_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'device.json'
            path.write_text(json.dumps({'buttons':[{'key':'S','modifiers':['CTRL']},'ESC']}))
            self.assertEqual(settings(path)['buttons'],[{'key':'S','modifiers':['CTRL']},'ESC'])

    def test_packet_rejects_invalid_physical_button_or_state(self):
        for index,state in [(2,True),(-1,True),(True,True),(0,1),(0,None)]:
            with self.subTest(index=index,state=state),self.assertRaises(ValueError):button_packet(index,state,'ESC')

    @unittest.skipUnless(shutil.which('c++'), 'A C++17 compiler is required for the native chord tracker test')
    def test_actual_dll_chord_tracker_overlap_cleanup_and_packet_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable=Path(tmp)/'key-chords-test'
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',
                            '-I'+str(ROOT/'bridge/siappdll/src'),
                            str(ROOT/'tests/key-chords-test.cpp'),'-o',str(executable)],check=True)
            bindings=[{'key':name,'modifiers':['CTRL','SHIFT','ALT','META','ALTGR']}
                      for name in (*NAMED_KEYS,*MODIFIER_BITS,'ä','?','漢')]
            wire=''.join(' '.join(map(str,packet(button,down,binding)))+'\n'
                         for binding in bindings for button in (0,1) for down in (False,True))
            subprocess.run([str(executable)],input=wire,text=True,check=True)


if __name__=='__main__':unittest.main()

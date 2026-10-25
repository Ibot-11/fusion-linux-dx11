import importlib.util
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_gain


class CameraGainTest(unittest.TestCase):
    def test_legacy_selection_preserves_other_compatibility_preferences(self):
        source = ('<?xml version="1.0" encoding="UTF-16"?><OptionGroups>'
                  '<CompatibilityGroup SchemaVersion="2"><spacemouseDriverOptionId Value="1" UserName="Treiber"/>'
                  '<other Value="ä"/></CompatibilityGroup></OptionGroups>').encode('utf-16')
        result = camera_gain.legacy_options(source)
        tree = ET.fromstring(result)
        self.assertEqual(result[:2], source[:2])
        self.assertEqual(tree.find('CompatibilityGroup/other').attrib['Value'], 'ä')
        self.assertEqual(tree.find('CompatibilityGroup/spacemouseDriverOptionId').attrib, dict(Value='0', UserName='Treiber'))
        self.assertEqual(camera_gain.legacy_options(result), result)

    def test_legacy_selection_can_initialize_missing_groups(self):
        for source in (b'<OptionGroups></OptionGroups>', b'<OptionGroups><CompatibilityGroup/></OptionGroups>'):
            result = camera_gain.legacy_options(source)
            self.assertEqual(ET.fromstring(result).find('CompatibilityGroup/spacemouseDriverOptionId').attrib['Value'], '0')

    def test_percentages_keep_integer_inputs_out_of_scaling(self):
        for percent in range(1, 101):
            with self.subTest(percent=percent):
                settings = camera_gain.percentage_settings(percent)
                camera_gain.validate_settings(settings)
                for key in camera_gain.KEYS:
                    self.assertAlmostEqual(settings[key] / 4 * settings['runtime_scale'], percent / 100)
        self.assertEqual(camera_gain.percentage_settings(20), dict(pan=1, zoom=1, rotation=1, runtime_scale=.8, percent=20))

    def test_invalid_runtime_scale_is_rejected(self):
        for scale in (0, -1, 1.1, float('nan'), float('inf'), True, '0.8'):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                camera_gain.validate_settings(dict(pan=1, zoom=1, rotation=1, runtime_scale=scale))

    def test_utf16_preferences_keep_bom_and_other_groups(self):
        source = ('<?xml version="1.0" encoding="UTF-16"?>\n'
                  '<OptionGroups><CompatibilityGroup><spacemouseDriverOptionId Value="0"/>'
                  '</CompatibilityGroup><DisplayOptionGroup Value="äöü"/></OptionGroups>').encode('utf-16')
        result = camera_gain.patch_options(source, dict(pan=1, zoom=1, rotation=1))
        self.assertEqual(result[:2], source[:2])
        tree = ET.fromstring(result)
        self.assertEqual(tree.find('CompatibilityGroup/spacemouseDriverOptionId').attrib['Value'], '0')
        self.assertEqual(tree.find('DisplayOptionGroup').attrib['Value'], 'äöü')
        self.assertEqual(tree.find('UISpaceMouseOptionGroup/SpacemousePan').attrib['Value'], '1')
        self.assertIn('<CompatibilityGroup><spacemouseDriverOptionId Value="0"/></CompatibilityGroup>', result.decode('utf-16'))

    def test_existing_gains_keep_other_spacemouse_preferences(self):
        source = b'<OptionGroups><UISpaceMouseOptionGroup SchemaVersion="2"><SpacemousePan Value="4" UserName="Pan"/><SpacemouseUseRotate Value="1"/></UISpaceMouseOptionGroup></OptionGroups>'
        result = camera_gain.patch_options(source, dict(pan=2, zoom=1, rotation=3))
        group = ET.fromstring(result).find('UISpaceMouseOptionGroup')
        self.assertEqual(group.find('SpacemousePan').attrib, dict(Value='2', UserName='Pan'))
        self.assertEqual(group.find('SpacemouseUseRotate').attrib['Value'], '1')
        self.assertEqual(group.find('SpacemouseZoom').attrib['Value'], '1')
        self.assertEqual(group.find('SpacemouseRotation').attrib['Value'], '3')

    def test_reapplying_does_not_rewrite_file(self):
        gains = dict(pan=1, zoom=1, rotation=1)
        first = camera_gain.patch_options(b'<OptionGroups/>'.replace(b'/>', b'></OptionGroups>'), gains)
        self.assertEqual(camera_gain.patch_options(first, gains), first)

    def test_empty_group_is_supported(self):
        result = camera_gain.patch_options(b'<OptionGroups><UISpaceMouseOptionGroup/></OptionGroups>', dict(pan=1, zoom=1, rotation=1))
        self.assertEqual(len(ET.fromstring(result).find('UISpaceMouseOptionGroup')), 3)

    def test_invalid_gain_is_rejected(self):
        for value in (0, 101, .25, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                camera_gain.patch_options(b'<OptionGroups></OptionGroups>', dict(pan=value, zoom=1, rotation=1))

    def test_ambiguous_group_is_rejected(self):
        with self.assertRaises(ValueError):
            camera_gain.patch_options(b'<OptionGroups><UISpaceMouseOptionGroup/><UISpaceMouseOptionGroup/></OptionGroups>', dict(pan=1, zoom=1, rotation=1))


if __name__ == '__main__':
    unittest.main(verbosity=2)

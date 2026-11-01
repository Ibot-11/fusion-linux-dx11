import contextlib
import importlib.util
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'vendor'))
spec = importlib.util.spec_from_file_location('window_fix', REPO / 'scripts/window-fix.py')
window_fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window_fix)

NORMAL = '_NET_WM_WINDOW_TYPE_NORMAL'
DIALOG = '_NET_WM_WINDOW_TYPE_DIALOG'


class Window:
    id = 1

    def __init__(self, size, parent=None, kind=DIALOG, override=True, mapped=True, input=False):
        self.size, self.parent, self.kind = size, parent, kind
        self.override, self.mapped, self.input = override, mapped, input

    def get_attributes(self):
        return SimpleNamespace(override_redirect=self.override,
                               map_state=window_fix.X.IsViewable if self.mapped else window_fix.X.IsUnmapped)

    def get_wm_name(self):
        return 'Fusion360'

    def get_full_property(self, atom, _):
        return SimpleNamespace(value=[self.kind]) if self.kind else None

    def get_wm_hints(self):
        return SimpleNamespace(input=self.input)

    def get_wm_transient_for(self):
        return self.parent

    def get_geometry(self):
        return SimpleNamespace(width=self.size[0], height=self.size[1])


class PhantomDialogTests(unittest.TestCase):
    def setUp(self):
        self.main = Window((3768, 2119), kind=NORMAL, override=False)
        self.connection = SimpleNamespace(intern_atom=lambda name: name)

    def problematic(self, window):
        with contextlib.redirect_stdout(io.StringIO()):
            return window_fix.is_problematic(window, self.connection)

    def test_plane_dropdown_remains_visible_when_larger_than_its_panel(self):
        # Actual Fusion dimensions: the dropdown covers 90% of the tool panel.
        panel = Window((375, 281), parent=self.main, override=False)
        menu = Window((308, 309), parent=panel)
        self.assertFalse(self.problematic(menu))

    def test_main_window_phantom_remains_filtered(self):
        self.assertTrue(self.problematic(Window((3768, 2119), parent=self.main)))

    def test_small_main_window_popup_remains_visible(self):
        self.assertFalse(self.problematic(Window((308, 309), parent=self.main)))

    def test_transient_or_unmanaged_normal_owner_is_not_a_main_window(self):
        for owner in (Window((375, 281), parent=self.main, kind=NORMAL, override=False),
                      Window((375, 281), kind=NORMAL)):
            with self.subTest(owner=owner):
                self.assertFalse(self.problematic(Window((308, 309), parent=owner)))

    def test_dialog_owner_without_transient_is_not_a_main_window(self):
        self.assertFalse(self.problematic(Window((308, 309), parent=Window((375, 281), override=False))))

    def test_existing_focus_and_mapping_exclusions_are_preserved(self):
        for options in ({'input': True}, {'mapped': False}, {'override': False}):
            with self.subTest(options=options):
                self.assertFalse(self.problematic(Window((3768, 2119), parent=self.main, **options)))


if __name__ == '__main__':
    unittest.main()

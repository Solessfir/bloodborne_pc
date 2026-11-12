"""Input editing uses the same serializers on Qt, including native event capture."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import QApplication
    import bbport_qt_controls as controls
else:
    controls = None


@unittest.skipIf(controls is None, 'PySide6 is needed for the Qt launcher')
class QtControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'input.ini'
        self.path.write_text(controls.inputs.DEFAULT_INPUT_INI +
            '\n# untouched settings\nunknown_output = anything # keep\n')
        self.library = patch.object(controls.bbport_pad, 'sdl_path', return_value=None)
        self.library.start()
        self.addCleanup(self.library.stop)
        self.settings = {'play_with': 'keyboard', 'button_prompts': 'auto'}
        self.page = controls.ControlsPage(self.settings, self.path)
        self.addCleanup(self.page.close)
        self.warning = patch.object(self.page, 'warning')
        self.warnings = self.warning.start()
        self.addCleanup(self.warning.stop)

    def key(self, key, release=False, modifiers=Qt.KeyboardModifier.NoModifier):
        event = QKeyEvent(QEvent.Type.KeyRelease if release else QEvent.Type.KeyPress, key, modifiers)
        QApplication.sendEvent(self.page, event)

    def mouse(self, button):
        event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
                            button, button, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.page, event)

    def wheel(self, x=0, y=120, modifiers=Qt.KeyboardModifier.NoModifier):
        event = QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(), QPoint(x, y),
                            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(self.page, event)

    def test_menu_choices_report_only_changes_and_replace_unknown_values(self):
        self.assertEqual(self.page.app_values(), {})
        self.page.menu_boxes['menu_key'].setCurrentIndex(self.page.menu_boxes['menu_key'].findData('none'))
        self.assertEqual(self.page.app_values(), {'menu_key': 'none'})
        self.page.preferences_saved()
        self.assertEqual(self.page.app_values(), {})
        page = controls.ControlsPage({'play_with': 'keyboard', 'menu_pad': 'select'}, self.path)
        self.addCleanup(page.close)
        self.assertEqual(page.app_values(), {'menu_pad': 'l3+r3'})
        page.refresh_preferences({'play_with': 'keyboard', 'menu_key': 'F5', 'menu_pad': 'off'}, {})
        self.assertEqual((page.menu_boxes['menu_key'].currentData(), page.menu_boxes['menu_pad'].currentData()), ('F5', 'off'))
        self.assertEqual(page.app_values(), {})

    def test_construction_and_unedited_save_do_not_write(self):
        before = self.path.read_bytes()
        self.page.save()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(self.page.remap_rows), len(controls.inputs.KEYBOARD_OUTPUTS))
        self.assertEqual(len(self.page.controller_rows), len(controls.inputs.CONTROLLER_OUTPUTS))
        self.assertEqual(set(self.page.mouse_widgets), set(controls.inputs.MOUSE_SETTINGS_DEFAULTS) - {'deadzone_offset'})
        self.assertEqual(self.page.ini_values(), {})

    def test_roundtrip_preserves_unknown_controller_axis_and_extra_bindings(self):
        self.path.write_text(self.path.read_text() + '\ncross = u\ncross = t\ncross = y\n')
        self.page.load()
        self.page.set_slot('cross', 0, 'h')
        self.page.set_controller('square', 'r4')
        self.page.set_mouse('camera', 'direct')
        self.page.set_mouse('speed', 2.25)
        self.page.set_mouse('invert_x', True)
        self.page.save()
        bindings, lines, _toggle, _reload, mouse = controls.inputs.load_input_ini(self.path)
        self.assertEqual(bindings['cross'], ['h', 'u', 't', 'y'])
        self.assertIn('cross = cross', lines)
        self.assertIn('axis_left_x = axis_left_x', lines)
        self.assertIn('unknown_output = anything # keep', lines)
        self.assertEqual(controls.inputs.load_controller_bindings(lines)['square'], 'r4')
        self.assertEqual(mouse['camera'], 'direct')
        self.assertEqual(mouse['speed'], 2.25)
        self.assertTrue(mouse['invert_x'])
        self.assertEqual(mouse['deadzone_offset'], 0.5)
        self.assertEqual(self.page.edits, {})

    def test_save_reads_external_changes_and_merges_only_edited_mouse_fields(self):
        self.page.set_slot('square', 0, 'u')
        self.page.set_mouse('invert_y', True)
        self.path.write_text(self.path.read_text() +
            '\nexternal = retained\nmouse_camera_sensitivity = 2.75\ntriangle = p\n')
        self.page.save()
        bindings, lines, _toggle, _reload, mouse = controls.inputs.load_input_ini(self.path)
        self.assertEqual(bindings['square'][0], 'u')
        self.assertIn('p', bindings['triangle'])
        self.assertIn('external = retained', lines)
        self.assertEqual(mouse['camera_sensitivity'], 2.75)
        self.assertTrue(mouse['invert_y'])

    def test_atomic_failure_keeps_original_and_pending_edits(self):
        before = self.path.read_bytes()
        self.page.set_slot('cross', 0, 'u')
        with patch.object(controls.os, 'replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.page.save()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.page.edits['cross'][0], 'u')
        self.assertEqual(list(self.path.parent.glob('.input-*')), [])

    def test_changed_external_hotkey_rejects_pending_binding_without_writing(self):
        self.page.set_slot('cross', 0, 'u')
        self.path.write_text(self.path.read_text() + '\nhotkey_reload_inputs = u\n')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.page.save()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.page.edits['cross'][0], 'u')

    def test_capture_keys_combo_modifier_only_and_escape(self):
        self.page.start_capture('cross', 0)
        self.key(Qt.Key.Key_Shift)
        self.key(Qt.Key.Key_Control)
        self.key(Qt.Key.Key_U)
        self.assertEqual(self.page.current_slots('cross')[0], 'lshift, lctrl, u')
        self.assertIsNone(self.page.capture)
        self.page.start_capture('circle', 0)
        self.key(Qt.Key.Key_Alt)
        self.key(Qt.Key.Key_Alt, release=True)
        self.assertEqual(self.page.current_slots('circle')[0], 'lalt')
        before = self.page.current_slots('square')
        self.page.start_capture('square', 0)
        self.key(Qt.Key.Key_Escape)
        self.assertEqual(self.page.current_slots('square'), before)
        self.assertIsNone(self.page.capture)

    def test_capture_custom_reserved_hotkeys_rejected_without_losing_binding(self):
        self.path.write_text(self.path.read_text() +
            '\nhotkey_toggle_mouse_to_joystick = f5\nhotkey_reload_inputs = f6\n')
        self.page.load()
        original = self.page.current_slots('cross')
        for key in (Qt.Key.Key_Insert, Qt.Key.Key_F9, Qt.Key.Key_F5, Qt.Key.Key_F6):
            with self.subTest(key=key):
                self.page.start_capture('cross', 0)
                self.key(key)
                self.assertEqual(self.page.current_slots('cross'), original)
                self.assertIsNone(self.page.capture)
        self.assertEqual(self.warnings.call_count, 4)
        self.page.start_capture('cross', 0)
        self.key(Qt.Key.Key_F7)
        self.assertEqual(self.page.current_slots('cross')[0], 'f7')

    def test_capture_mouse_wheel_and_stick_restrictions(self):
        self.page.start_capture('r2', 0)
        self.key(Qt.Key.Key_Shift)
        self.mouse(Qt.MouseButton.LeftButton)
        self.assertEqual(self.page.current_slots('r2')[0], 'lshift, leftbutton')
        self.page.start_capture('pad_left', 0)
        self.wheel(x=120, y=0)
        self.assertEqual(self.page.current_slots('pad_left')[0], 'mousewheelleft')
        self.page.start_capture('pad_right', 0)
        self.wheel(y=120, modifiers=Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.page.current_slots('pad_right')[0], 'mousewheelright')
        self.page.start_capture('axis_left_y_minus', 0)
        self.mouse(Qt.MouseButton.LeftButton)
        self.assertIsNotNone(self.page.capture)
        self.wheel()
        self.assertIsNotNone(self.page.capture)
        self.assertEqual(self.warnings.call_count, 2)
        self.key(Qt.Key.Key_U)
        self.assertEqual(self.page.current_slots('axis_left_y_minus')[0], 'u')

    def test_unsupported_key_waits_and_invalid_programmatic_bindings_reject(self):
        self.page.start_capture('cross', 0)
        self.key(Qt.Key.Key_VolumeUp)
        self.assertIsNotNone(self.page.capture)
        self.key(Qt.Key.Key_U)
        self.assertEqual(self.page.current_slots('cross')[0], 'u')
        for output, value in [('cross', 'insert'), ('cross', 'a, a'),
                              ('axis_left_y_minus', 'leftbutton')]:
            with self.subTest(output=output, value=value):
                with self.assertRaises(ValueError):
                    self.page.set_slot(output, 0, value)

    def test_native_side_keypad_and_shifted_key_names(self):
        right = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier,
                          0, 0xffe2, 0)
        self.assertEqual(controls.key_name(right), 'rshift')
        keypad = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_7, Qt.KeyboardModifier.KeypadModifier)
        self.assertEqual(controls.key_name(keypad), 'kp7')
        plus = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Plus, Qt.KeyboardModifier.ShiftModifier, '+')
        self.assertEqual(controls.key_name(plus), 'equals')

    def test_layout_changes_keyboard_preserves_controller_and_pending_controller_edit(self):
        self.page.set_controller('cross', 'circle')
        self.page.set_slot('cross', 0, 'u')
        self.assertTrue(self.page.write_layout())
        self.assertEqual(controls.inputs.keyboard_layout(self.page.lines), 'ds3')
        self.assertEqual(self.page.controller_edits, {'cross': 'circle'})
        self.assertEqual(controls.inputs.load_controller_bindings(self.page.lines)['cross'], 'cross')
        self.assertEqual(self.page.mouse['camera'], 'direct')
        self.assertTrue(self.page.mouse_widgets['enabled'].isChecked())
        self.page.save()
        self.assertEqual(controls.inputs.load_controller_bindings(self.page.lines)['cross'], 'circle')

    def test_device_switch_preserves_custom_keys_when_preset_declined(self):
        self.page.set_slot('cross', 0, 'u')
        with patch.object(self.page, 'confirm', return_value=False):
            self.page.set_play_with('controller')
            self.assertFalse(self.page.mouse_widgets['enabled'].isChecked())
            self.page.set_play_with('keyboard')
        self.assertEqual(self.page.current_slots('cross')[0], 'u')
        self.assertTrue(self.page.mouse_widgets['enabled'].isChecked())
        self.assertEqual(self.settings['play_with'], 'keyboard')
        self.page.prompts.setCurrentIndex(self.page.prompts.findData('xbox'))
        self.assertEqual(self.page.ini_values(), {'button_prompts': 'xbox'})

    def test_controller_poll_capture_ignores_initially_held_and_releases_reader(self):
        pad = controls.bbport_pad.Pad(1, 'Test pad', 'xbox', {'south': True}, {})
        class Reader:
            closed = False
            def poll(self):
                return [pad]
            def close(self):
                self.closed = True
        reader = Reader()
        self.page.reader = reader
        self.page.start_controller_capture('square')
        self.assertEqual(self.page.capture[0], 'controller')
        self.page.poll_pads()
        self.assertNotIn('square', self.page.controller_edits)
        pad.buttons['south'] = False
        self.page.poll_pads()
        pad.buttons['south'] = True
        self.page.poll_pads()
        self.assertEqual(self.page.controller_edits['square'], 'cross')
        self.assertIsNone(self.page.capture)
        self.assertIn('Test pad', self.page.pad_status.text())
        self.page.stop()
        self.assertTrue(reader.closed)
        self.assertIsNone(self.page.reader)
        self.assertFalse(self.page.timer.isActive())

    def test_controller_timeout_disconnect_and_unavailable_reported(self):
        self.page.start_controller_capture('cross')
        self.assertIsNone(self.page.capture)
        self.assertIn('SDL3', self.page.pad_status.text())
        self.warnings.assert_called_once()
        pad = controls.bbport_pad.Pad(1, 'Test pad', 'switch', {}, {})
        class Reader:
            def poll(self):
                return [pad]
            def close(self):
                pass
        self.page.reader = Reader()
        self.page.start_controller_capture('cross')
        self.page.deadline = time.monotonic() - 1
        self.page.poll_pads()
        self.assertIsNone(self.page.capture)
        self.assertEqual(self.page.controller_edits, {})


if __name__ == '__main__':
    unittest.main()

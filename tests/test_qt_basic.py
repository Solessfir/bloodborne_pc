"""Basic Qt pages preserve settings types, original choices and game safety rules."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import (QApplication, QFrame, QGroupBox, QHBoxLayout, QLabel,
        QPushButton, QVBoxLayout, QWidget)
    from PySide6.QtTest import QTest
    import bbport_qt_basic as basic
else:
    basic = None


@unittest.skipIf(basic is None, 'PySide6 is needed for native Qt pages')
class BasicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = {**basic.backend.APP_DEFAULTS, 'game_dir': ''}
        self.graphics = dict(basic.backend.INI_DEFAULTS)
        self.pages = []
        self.addCleanup(self.close_pages)

    def close_pages(self):
        for page in self.pages:
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def page(self, name):
        page = basic.BasicPage(self.settings, self.graphics, name)
        self.pages.append(page)
        return page

    def test_every_reference_field_has_a_named_widget_and_original_hint(self):
        for name in ('game', 'gameplay', 'cheats', 'language', 'advanced'):
            page = self.page(name)
            for field in basic.FIELDS[name]:
                with self.subTest(page=name, key=field['key']):
                    if field['key'] == 'mangohud' and basic.backend.WINDOWS:
                        continue
                    widget = page.findChild(basic.QWidget, field['key'])
                    self.assertIsNotNone(widget)
                    self.assertEqual(widget.toolTip(), basic._(field['hint']))
            self.assertEqual(page.app_values(), {})
            self.assertEqual(page.ini_values(), {})

    def test_options_are_the_shared_original_options_and_unknown_values_survive(self):
        for name, choices in [('gameplay', {'language': basic.backend.LANGUAGES,
                                           'voice_language': basic.backend.VOICE_LANGUAGES}),
                              ('language', {'ui_language': basic.backend.UI_LANGUAGES,
                                            'on_play': basic.backend.ON_PLAY}),
                              ('advanced', {'draw_pipe': basic.backend.DRAW_PIPE,
                                            'readbacks': basic.backend.READBACKS,
                                            'low_vram': basic.backend.LOW_VRAM})]:
            page = self.page(name)
            for key, options in choices.items():
                combo = page.app_widgets[key]
                self.assertEqual([(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())],
                                 [(value, basic._(*text)) for value, text in options])
        self.settings['voice_language'] = 'future-track'
        gameplay = self.page('gameplay')
        self.assertEqual(gameplay.app_widgets['voice_language'].currentData(), 'future-track')
        self.assertEqual(gameplay.app_values(), {})
        gameplay.app_widgets['player_name'].setText('Hunter')
        gameplay.save()
        self.assertEqual(self.settings['voice_language'], 'future-track')

    def test_roundtrip_only_changed_fields_and_ini_flags_are_strings(self):
        page = self.page('gameplay')
        changes = []
        page.settings_changed.connect(lambda: changes.append(True))
        page.app_widgets['language'].setCurrentIndex(1)
        page.app_widgets['player_name'].setText('Hunter')
        page.ini_widgets['mute_unfocused'].setChecked(True)
        self.settings['voice_language'] = 'frf'
        self.graphics['tweak_camera_distance'] = '1'
        self.assertEqual(page.app_values(), {'language': '8', 'player_name': 'Hunter'})
        self.assertEqual(page.ini_values(), {'mute_unfocused': '1'})
        self.assertTrue(page.save())
        self.assertEqual(self.settings['voice_language'], 'frf')
        self.assertEqual(self.graphics['tweak_camera_distance'], '1')
        self.assertEqual(self.graphics['mute_unfocused'], '1')
        self.assertTrue(changes)
        self.assertEqual(page.ini_values(), {'mute_unfocused': '1'})
        page.refresh()
        self.assertEqual(page.app_values(), {})
        self.assertEqual(page.ini_values(), {})
        self.assertTrue(page.ini_widgets['tweak_camera_distance'].isChecked())

    def test_enemy_control_and_free_camera_are_mutually_exclusive(self):
        page = self.page('cheats')
        control, camera = [page.ini_widgets[key] for key in ('cheat_enemy_control', 'debug_camera')]
        control.setChecked(True)
        camera.setChecked(True)
        self.assertFalse(control.isChecked())
        self.assertEqual(page.ini_values(), {'debug_camera': '1'})
        control.setChecked(True)
        self.assertFalse(camera.isChecked())
        self.assertEqual(page.ini_values(), {'cheat_enemy_control': '1'})

    def test_folder_browse_and_dlc_status_use_current_paths(self):
        page = self.page('game')
        with patch.object(basic.QFileDialog, 'getExistingDirectory', return_value='/owned/game'), \
             patch.object(basic.backend, 'dlc_status', return_value=('ok', 'DLC found')) as status:
            page.findChild(QPushButton, 'button:browse_game_dir').click()
            self.assertEqual(page.app_values(), {'game_dir': '/owned/game'})
            self.assertEqual(status.call_args.args[0], '/owned/game')
            self.assertEqual(page.dlc_note.text(), '✓  DLC found')
        with patch.object(basic.QFileDialog, 'getExistingDirectory', return_value=''):
            page.findChild(QPushButton, 'button:browse_game_dir').click()
        self.assertEqual(page.app_values(), {'game_dir': '/owned/game'})

    def test_language_apply_actions_and_running_safety(self):
        page = self.page('language')
        self.assertTrue(page.actions['relaunch'].isHidden())
        page.app_widgets['ui_language'].setCurrentIndex(1)
        self.assertFalse(page.actions['relaunch'].isHidden())
        actions = []
        page.action_requested.connect(actions.append)
        page.actions['shortcut'].click()
        page.actions['steam'].click()
        page.actions['relaunch'].click()
        self.assertEqual(actions, ['shortcut', 'steam', 'relaunch'])
        self.settings['on_play'] = 'close'
        page.save()
        self.assertEqual(self.settings['on_play'], 'close')
        self.assertIsInstance(self.settings['translucent_window'], bool)
        page.set_game_running(True)
        self.assertFalse(page.actions['relaunch'].isEnabled())
        page.set_game_running(False)
        self.assertTrue(page.actions['relaunch'].isEnabled())
        cheats = self.page('cheats')
        cheats.set_game_running(True)
        self.assertFalse(cheats.actions['respec'].isEnabled())

    def test_linux_unsupported_actions_stay_disabled_after_refresh_and_running(self):
        with patch.object(basic.backend, 'WINDOWS', False):
            page = self.page('advanced')
            for running in (True, False):
                page.set_game_running(running)
                page.refresh()
                for key in ('updates', 'versions', 'benchmark'):
                    self.assertFalse(page.actions[key].isEnabled())
            self.assertNotIn('windows_title_bar', page.app_widgets)
            self.assertNotIn('check_updates', page.app_widgets)
            self.assertEqual(page.actions['updates'].text(), 'Check for updates')
            self.assertIn('mangohud', page.app_widgets)

    def test_patch_version_warning_refreshes_from_the_current_game(self):
        with patch.object(basic.backend, 'game_info', return_value=('Bloodborne', '01.00')):
            page = self.page('gameplay')
            self.assertFalse(page.version_warning.isHidden())
            self.assertIn('01.00', page.version_warning.text())
        with patch.object(basic.backend, 'game_info', return_value=('Bloodborne', basic.backend.PATCH_VERSION)):
            page.refresh()
            self.assertTrue(page.version_warning.isHidden())

    def test_flat_sections_and_original_field_widths_replace_expanding_cards(self):
        expected = {'game': 1, 'gameplay': 3, 'cheats': 3, 'language': 3,
                    'advanced': 4 if basic.backend.WINDOWS else 3}
        for name, sections in expected.items():
            page = self.page(name)
            self.assertEqual(page.findChildren(QGroupBox), [])
            self.assertEqual(len(page.findChildren(QFrame, 'sectionHairline')), sections)
            self.assertEqual(page.body.contentsMargins().top(), 0)
        gameplay = self.page('gameplay')
        self.assertEqual(gameplay.app_widgets['voice_language'].maximumWidth(), 390)
        launcher = self.page('language')
        self.assertEqual(launcher.app_widgets['ui_language'].maximumWidth(), 250)
        self.assertIs(launcher.actions['shortcut'].parentWidget(), launcher.actions['steam'].parentWidget())
        self.assertIs(launcher.actions['relaunch'].parentWidget(), launcher.app_widgets['ui_language'].parentWidget())
        self.assertNotIn("The game's language and sound, and changes to how it plays and its menus.",
                         [label.text() for label in gameplay.findChildren(QLabel)])

    def test_folder_open_uses_the_editable_path_and_reports_errors(self):
        page = self.page('game')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'game'
            page.app_widgets['game_dir'].setText(str(folder))
            with patch.object(basic, 'open_path') as opened:
                page.findChild(QPushButton, 'button:open_game_dir').click()
                opened.assert_called_once_with(folder)
            self.assertTrue(folder.is_dir())
            with patch.object(basic, 'open_path', side_effect=OSError('Cannot open')), \
                 patch.object(basic.QMessageBox, 'critical') as message:
                page.findChild(QPushButton, 'button:open_game_dir').click()
                message.assert_called_once_with(page, 'Bloodborne', 'Cannot open')

    def test_native_window_geometry_keeps_wrapped_hints_and_folder_buttons_whole(self):
        import bbport_theme_qt
        bbport_theme_qt.apply(self.app)
        for name in ('language', 'game', 'gameplay', 'advanced'):
            with self.subTest(page=name):
                host = QWidget()
                self.addCleanup(host.close)
                layout = QHBoxLayout(host)
                layout.setContentsMargins(0, 0, 0, 0)
                sidebar = QWidget()
                sidebar.setFixedWidth(248)
                layout.addWidget(sidebar)
                right = QVBoxLayout()
                layout.addLayout(right)
                header = QWidget()
                header.setFixedHeight(118)
                right.addWidget(header)
                page = self.page(name)
                right.addWidget(page)
                footer = QWidget()
                footer.setFixedHeight(80)
                right.addWidget(footer)
                host.setFixedSize(1180, 800)
                host.show()
                QTest.qWait(40)
                for label in page.findChildren(QLabel):
                    if label.wordWrap() and label.isVisible():
                        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), label.text())
                for button in page.findChildren(QPushButton):
                    if button.objectName().startswith(('button:browse_', 'button:open_')):
                        self.assertGreaterEqual(button.height(), button.sizeHint().height(), button.objectName())
                page.setParent(None)
                host.hide()


if __name__ == '__main__':
    unittest.main()

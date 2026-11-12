"""Cross-page preferences and lifecycle checks on a disposable launcher profile."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog
    import bbport_launcher_qt as qt
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for native Qt pages')
class IntegratedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.config = self.data / 'settings.json'
        self.ini = self.data / 'bbport.ini'
        self.config.write_text(json.dumps({'game_dir': str(self.data / 'game'),
            'setup_done': True, 'auto_backup': False, 'ui_mode': 'expert'}))
        self.ini.write_text('upscaler=dlss\npreset=2\noutput_res=2560x1440\n')
        for mock in (patch.multiple(qt.backend, DATA_DIR=self.data, PORT_DIR=self.data,
                                   CONFIG_DIR=self.data, CONFIG_FILE=self.config),
                     patch.dict(os.environ, BB_CONFIG=str(self.ini)),
                     patch.object(qt.QMessageBox, 'critical'),
                     patch.object(qt.QMessageBox, 'warning'),
                     patch.object(qt.QMessageBox, 'information')):
            mock.start()
            self.addCleanup(mock.stop)
        self.windows = []
        self.addCleanup(self.close_windows)

    def close_windows(self):
        for window in self.windows:
            window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def window(self):
        window = qt.LauncherWindow()
        self.windows.append(window)
        return window

    def test_controls_use_the_separate_input_file(self):
        window = self.window()
        self.assertEqual(window.pages['controls'].ini_path, qt.backend.input_ini_path(self.ini))

    def test_navigation_keeps_output_preferences_in_sync(self):
        window = self.window()
        window.show_page('graphics')
        page = window.pages['graphics']
        page.output_combo.setCurrentIndex(page.output_combo.findData('1920x1080'))
        page._choose_output(page.output_combo.currentIndex())
        window.show_page('picture')
        self.assertEqual(window.pages['picture'].output.currentData(), '1920x1080')
        window.show_page('graphics')
        self.assertEqual(page.output_combo.currentData(), '1920x1080')
        self.assertTrue(window.save())
        self.assertIn('output_res=1920x1080', self.ini.read_text())

    def test_mod_reorder_and_disabled_state_survive_navigation_and_save(self):
        for name in ('A', 'B'):
            (self.data / 'mods' / name / 'chr').mkdir(parents=True)
            (self.data / 'mods' / name / 'chr/hunter.bin').write_bytes(b'mod')
        window = self.window()
        window.show_page('mods')
        page = window.pages['mods']
        page.mods.setCurrentRow(1)
        page.move_mod(-1)
        page.mods.item(0).setCheckState(Qt.CheckState.Unchecked)
        window.show_page('play')
        window.show_page('mods')
        self.assertEqual(page.mods.item(0).text(), 'B')
        self.assertEqual(page.mods.item(0).checkState(), Qt.CheckState.Unchecked)
        self.assertTrue(window.save())
        self.assertEqual(json.loads((self.data / 'mods.json').read_text()),
                         {'order': ['B', 'A'], 'disabled': ['B']})

    def test_closing_persists_unsaved_preferences(self):
        window = self.window()
        window.pages['gameplay'].app_widgets['player_name'].setText('Hunter')
        window.close()
        self.windows.remove(window)
        self.assertEqual(json.loads(self.config.read_text()).get('player_name'), 'Hunter')

    def test_game_exit_refreshes_all_graphics_widgets(self):
        window = self.window()
        self.ini.write_text(self.ini.read_text().replace('preset=2', 'preset=1'))
        window._game_finished(0)
        self.assertEqual(window.graphics['preset'], '1')
        self.assertEqual(window.pages['graphics'].ini_widgets['preset'].currentData(), '1')

    def test_overlay_prompt_changes_keep_pending_input_bindings(self):
        window = self.window()
        controls = window.pages['controls']
        controls.edits['cross'] = ['space']
        prompt = qt.backend.PROMPT_MODES[1][0]
        self.ini.write_text(self.ini.read_text() + f'button_prompts={prompt}\n')
        window.runner.process = object()
        try:
            window._sync_ini()
            window._sync_ini()
        finally:
            window.runner.process = None
        self.assertEqual(controls.prompts.currentData(), prompt)
        self.assertEqual(controls.edits['cross'], ['space'])

    def test_crash_reopens_hidden_launcher_and_log_even_without_reopen_preference(self):
        window = self.window()
        window.hidden_for_game = True
        window.settings['reopen_after_game'] = False
        with patch.object(window, 'close') as close, patch.object(window, 'showNormal') as show:
            window._game_finished(7)
            close.assert_not_called()
            show.assert_called_once()
        self.assertEqual(window.page_ids[window.tabs.currentIndex()], 'log')

    def test_a_failed_start_names_the_cause_and_opens_its_fix(self):
        window = self.window()
        user = Path(window.settings.get('user_dir') or qt.backend.DATA_DIR / 'user')
        user.mkdir(parents=True, exist_ok=True)
        (user / 'last_run.log').write_text('Failed to enumerate physical devices: ErrorInitializationFailed\n')
        with patch.object(qt.QMessageBox, 'question', return_value=qt.QMessageBox.StandardButton.Yes) as asked:
            window._game_finished(1)
            self.app.processEvents()
            time.sleep(.4)
            self.app.processEvents()
        asked.assert_called_once()
        self.assertEqual(window.page_ids[window.tabs.currentIndex()], 'help')
        toggle, _body = window.pages['help'].topic_bodies['gpu_unseen']
        self.assertTrue(toggle.isChecked())

    def test_saved_launcher_language_is_applied_before_building_widgets(self):
        saved = json.loads(self.config.read_text())
        saved['ui_language'] = 'de'
        self.config.write_text(json.dumps(saved))
        with patch.object(qt.backend, 'LANG', 'en'):
            window = self.window()
            self.assertEqual(qt.backend.LANG, 'de')
            self.assertEqual(window.save_button.text(), qt.backend._('Save settings'))

    def test_invalid_resolution_on_play_shows_a_validation_error(self):
        window = self.window()
        graphics = window.pages['graphics']
        graphics.output_combo.setCurrentIndex(graphics.output_combo.findData('custom'))
        graphics.output_custom.setText('invalid')
        with patch.object(window.runner, 'start') as start:
            window.play()
            start.assert_not_called()

    def test_play_runs_the_shared_checks_and_starts_the_game(self):
        game = self.data / 'game'
        game.mkdir()
        window = self.window()
        with patch.object(qt.backend, 'game_info', return_value=('Bloodborne', '01.09')), \
                patch.object(window.runner, 'start') as start:
            window.play()
        start.assert_called_once()

    def test_setup_view_choice_survives_the_parent_save(self):
        class Wizard(QDialog):
            page_requested = Signal(str)
            device_requested = Signal(str)
            shortcut_requested = Signal()
            steam_requested = Signal()

            def __init__(self, settings, _graphics, parent):
                super().__init__(parent)
                self.settings = settings
                self.device = QComboBox()
                self.device.addItem('Controller', 'controller')
                self.download, self.play = QCheckBox(), QCheckBox()

            def exec(self):
                self.settings['ui_mode'] = 'simple'
                self.accepted.emit()
                return QDialog.DialogCode.Accepted

        window = self.window()
        with patch('bbport_qt_home.SetupWizard', Wizard):
            window._action('setup')
        self.assertEqual(json.loads(self.config.read_text())['ui_mode'], 'simple')
        self.assertFalse(window.expert.isChecked())


if __name__ == '__main__':
    unittest.main()

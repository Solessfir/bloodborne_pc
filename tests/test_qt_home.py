"""Home, profile and setup behavior without an installed game or live hardware probes."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
    import bbport_qt_home as qt
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for the Qt launcher')
class QtHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.settings = {**qt.backend.APP_DEFAULTS, 'user_dir': str(self.data / 'user')}
        self.graphics = dict(qt.backend.INI_DEFAULTS)
        for target in (patch.multiple(qt.backend, DATA_DIR=self.data, PORT_DIR=self.data),
                       patch.object(qt.SystemPage, 'check_hardware'),
                       patch.object(qt.HelpPage, 'check_installation'),
                       patch.object(qt.SavesPage, 'search')):
            target.start()
            self.addCleanup(target.stop)
        self.pages = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for page in self.pages:
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def page(self, cls):
        page = cls(self.settings, self.graphics)
        self.pages.append(page)
        return page

    def test_home_pending_edits_do_not_overwrite_other_pages(self):
        page = self.page(qt.HomePage)
        fullscreen = page.fields['fullscreen']
        fullscreen.setChecked(not fullscreen.isChecked())
        value = fullscreen.isChecked()
        self.assertNotEqual(self.settings['fullscreen'], value)
        page.save()
        self.settings['online'] = not self.settings['online']
        online = self.settings['online']
        page.save()
        self.assertEqual(self.settings['fullscreen'], value)
        self.assertEqual(self.settings['online'], online)

    def test_recommendation_and_undo_use_shared_profile(self):
        page = self.page(qt.PicturePage)
        gpu = next(gpu for gpu in qt.hardware.GPU_LIST if '4070' in gpu.label)
        cpu = qt.hardware.cpu_from_name('AMD Ryzen 7 5700X')
        rating = qt.hardware.assess(gpu, cpu, 32, tr=qt.backend._)
        page.system_page = SimpleNamespace(rating=rating, gpu_line=gpu.label, cpu=cpu, ram=32)
        before = dict(self.graphics)
        page.apply_recommended()
        self.assertTrue(page.app_values().get('auto_undo'))
        self.assertEqual(qt._Profile(page).differences(), [])
        self.assertEqual(self.graphics, before)
        page.undo_recommended()
        self.assertFalse(page.app_values().get('auto_undo'))
        self.assertEqual(page.ini_values(), {})

    def test_monitor_match_keeps_pending_monitor_and_resolution(self):
        page = self.page(qt.PicturePage)
        page.monitor.addItem('Test monitor', 'test-monitor')
        with patch.object(qt.display, 'monitor', return_value=SimpleNamespace(size=(3840, 2160))):
            page.match.setChecked(True)
            page.monitor.setCurrentIndex(page.monitor.findData('test-monitor'))
        self.assertEqual(page.monitor.currentData(), 'test-monitor')
        self.assertEqual(page.ini_values().get('output_res'), '3840x2160')
        self.assertTrue(page.app_values().get('output_display', self.settings['output_display']))

    def test_custom_resolution_validation(self):
        page = self.page(qt.PicturePage)
        page.output.setEditText('2400x1080')
        page.save()
        self.assertEqual(self.graphics['output_res'], '2400x1080')
        page.output.setEditText('invalid')
        with self.assertRaises(ValueError):
            page.save()

    def test_setup_gates_broken_game_and_saves_only_when_accepted(self):
        wizard = self.page(qt.SetupWizard)
        before = dict(self.settings), dict(self.graphics)
        wizard.game_dir.setText(str(self.data / 'missing'))
        wizard._check_game()
        wizard._checks_finished([])
        self.assertFalse(wizard.check_step.isComplete())
        game = self.data / 'game'
        game.mkdir()
        (game / 'eboot.bin').write_bytes(b'fixture')
        for folder in ('sce_module', 'sce_sys', 'dvdroot_ps4'):
            (game / folder).mkdir()
        wizard.game_dir.setText(str(game))
        wizard.game_timer.stop()
        wizard._check_game()
        wizard._checks_finished([('bad', 'eboot_truncated', 'broken')])
        self.assertFalse(wizard.check_step.isComplete())
        wizard._checks_finished([('warn', 'version', 'other version')])
        self.assertTrue(wizard.check_step.isComplete())
        self.assertEqual((self.settings, self.graphics), before)
        wizard.accept()
        self.assertTrue(self.settings['setup_done'])
        self.assertEqual(self.settings['game_dir'], str(game))

    def test_setup_back_preserves_picture_and_online_edits(self):
        wizard = self.page(qt.SetupWizard)
        wizard._enter(2)
        wizard.picture.fields['fullscreen'].setChecked(False)
        wizard.device.setCurrentIndex(wizard.device.findData('keyboard'))
        wizard._enter(1)
        wizard._enter(2)
        self.assertFalse(wizard.picture.fields['fullscreen'].isChecked())
        self.assertEqual(wizard.settings['play_with'], 'keyboard')
        wizard._enter(3)
        wizard.online.fields['online'].setChecked(False)
        wizard._enter(2)
        wizard._enter(3)
        self.assertFalse(wizard.online.fields['online'].isChecked())

    def test_pages_render_offscreen_and_running_disables_edits(self):
        for cls in (qt.HomePage, qt.PicturePage, qt.SetupWizard):
            page = self.page(cls)
            page.resize(1050, 800)
            page.show()
            self.app.processEvents()
            self.assertFalse(page.grab().isNull())
            if hasattr(page, 'set_game_running'):
                page.set_game_running(True)
                self.assertTrue(all(not widget.isEnabled() for widget in page.fields.values()))

    def test_ready_check_wraps_at_native_window_size_and_after_resize(self):
        import bbport_theme_qt as theme
        theme.apply(self.app)
        window = QWidget()
        self.pages.append(window)
        layout = QHBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        sidebar = QWidget()
        sidebar.setFixedWidth(244)
        layout.addWidget(sidebar)
        page = qt.HomePage(self.settings, self.graphics)
        layout.addWidget(page, 1)
        window.resize(1180, 800)
        window.show()
        for width in (1180, 1000, 1180):
            window.resize(width, 800)
            self.app.processEvents()
            for key, (button, label) in page.checks.items():
                if not button.isHidden():
                    self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()), key)
        page._check('saves', 'Save information with additional words. ' * 12, 'saves')
        self.app.processEvents()
        label = page.checks['saves'][1]
        self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))


if __name__ == '__main__':
    unittest.main()

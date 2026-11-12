"""Qt migration checks use temporary profiles and disposable game processes."""
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
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import bbport_launcher_qt as qt
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for the Qt preview')
class QtLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        qt.theme.apply(cls.app)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.config = self.data / 'settings.json'
        self.ini = self.data / 'bbport.ini'
        self.config.write_text(json.dumps({'game_dir': str(self.data / 'game'), 'auto_backup': False,
                                          'online_npid': 'retained-account', 'ui_mode': 'expert'}))
        self.ini.write_text('# keep this comment\nupscaler=dlss\npreset=2\noutput_res=2560x1600\ncustom_setting=keep\n')
        profile = patch.multiple(qt.backend, PORT_DIR=self.data, DATA_DIR=self.data,
                                 CONFIG_DIR=self.data, CONFIG_FILE=self.config)
        profile.start()
        self.addCleanup(profile.stop)
        env = patch.dict(os.environ, BB_CONFIG=str(self.ini))
        env.start()
        self.addCleanup(env.stop)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def close_window(self, window):
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_initialization_does_not_write_and_saves_preserve_unmigrated_fields(self):
        before = self.ini.read_bytes(), self.config.read_bytes()
        window = qt.LauncherWindow()
        self.addCleanup(self.close_window, window)
        self.assertEqual((self.ini.read_bytes(), self.config.read_bytes()), before)
        self.assertEqual(window.ini_widgets['output_res'].currentData(), '2560x1600')
        widget = window.ini_widgets['output_res']
        widget.setCurrentIndex(widget.findData('1920x1200'))
        self.assertTrue(window.save())
        self.assertIn('output_res=1920x1200', self.ini.read_text())
        self.assertIn('# keep this comment', self.ini.read_text())
        self.assertIn('custom_setting=keep', self.ini.read_text())
        self.assertEqual(json.loads(self.config.read_text())['online_npid'], 'retained-account')

    def test_unedited_fields_follow_external_ini_changes(self):
        window = qt.LauncherWindow()
        self.addCleanup(self.close_window, window)
        self.ini.write_text(self.ini.read_text().replace('preset=2', 'preset=1') + 'unknown=value\n')
        self.assertTrue(window.save())
        self.assertIn('preset=1', self.ini.read_text())
        self.assertIn('unknown=value', self.ini.read_text())
        self.assertEqual(window.ini_widgets['preset'].currentData(), '1')

    def test_sidebar_navigation_and_compact_folder_rows(self):
        window = qt.LauncherWindow()
        self.addCleanup(self.close_window, window)
        self.assertEqual(window.navigation.count(), window.tabs.count())
        self.assertEqual(window.page_title.text(), 'Play')
        self.assertTrue(window.tabs.tabBar().isHidden())
        self.assertEqual(len(window.pages), 16)
        window.navigation.setCurrentRow(1)
        self.assertEqual(window.tabs.currentIndex(), 1)
        self.assertEqual(window.page_title.text(), 'Picture & performance')
        window.show_page('log')
        self.assertEqual(window.navigation.currentRow(), window.tabs.count() - 1)
        self.assertEqual(window.page_title.text(), 'Log')

    def test_native_runner_streams_output_and_saves_log(self):
        runner = qt.GameProcess()
        output, exited = [], []
        runner.output.connect(output.append)
        runner.finished.connect(exited.append)
        command = [sys.executable, '-c', 'import os; print("native", os.environ["BB_FPS_LIMIT"])']
        settings = {**qt.backend.APP_DEFAULTS, **qt.backend.load_profile(), 'frame_cap': '90'}
        with patch.object(qt.backend, 'run_command', return_value=command):
            runner.start(settings, qt.backend.INI_DEFAULTS)
        self.wait_for(lambda: bool(exited))
        self.assertEqual(exited, [0])
        self.assertIsNone(runner.process)
        self.assertIn('native 90', ''.join(output))
        self.assertIn('native 90', (self.data / 'user/last_run.log').read_text())

    @unittest.skipIf(os.name == 'nt', 'Native process group test')
    def test_stop_terminates_runner_and_returns_to_idle(self):
        runner = qt.GameProcess()
        exited = []
        runner.finished.connect(exited.append)
        command = [sys.executable, '-c', 'import time; time.sleep(60)']
        settings = {**qt.backend.APP_DEFAULTS, **qt.backend.load_profile()}
        with patch.object(qt.backend, 'run_command', return_value=command):
            runner.start(settings, qt.backend.INI_DEFAULTS)
        try:
            runner.stop()
            self.wait_for(lambda: bool(exited))
            self.assertLess(exited[0], 0)
            self.assertIsNone(runner.process)
        finally:
            if runner.process is not None:
                runner.stop()
                runner.process.wait(timeout=5)

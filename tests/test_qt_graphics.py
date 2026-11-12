"""Graphics forms and atomic asset downloads use temporary profiles and mocked requests."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    import bbport_qt_graphics as qt
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for the Qt launcher')
class QtGraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.settings = dict(qt.backend.APP_DEFAULTS)
        self.graphics = dict(qt.backend.INI_DEFAULTS)
        for target in (patch.multiple(qt.backend, DATA_DIR=self.folder, PORT_DIR=self.folder),
                       patch.object(qt.GraphicsPage, 'recheck_support')):
            target.start()
            self.addCleanup(target.stop)
        self.page = qt.GraphicsPage(self.settings, self.graphics)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.page.close()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_dirty_save_preserves_shared_and_external_values(self):
        widget = self.page.ini_widgets['upscaler']
        widget.setCurrentIndex(widget.findData('fsr3'))
        self.page.save()
        self.assertEqual(self.graphics['upscaler'], 'fsr3')
        self.graphics['preset'] = '2'
        self.page.save()
        self.assertEqual(self.graphics['preset'], '2')
        self.settings['frame_cap'] = '60'
        self.page.save()
        self.assertEqual(self.settings['frame_cap'], '60')

    def test_custom_resolution_and_running_lock(self):
        self.page.output_combo.setCurrentIndex(self.page.output_combo.findData('custom'))
        self.page.output_custom.setText('2400x1080')
        self.page.save()
        self.assertEqual(self.graphics['output_res'], '2400x1080')
        self.assertFalse(self.settings['output_display'])
        self.page.output_custom.setText('bad')
        with self.assertRaises(ValueError):
            self.page.save()
        self.page.set_game_running(True)
        self.assertTrue(all(not widget.isEnabled() for widget in self.page.ini_widgets.values()))
        self.assertFalse(self.page.output_custom.isEnabled())
        self.assertFalse(self.page.fsr4_button.isEnabled())

    def test_early_submit_is_greyed_out_on_radeon_unless_forced(self):
        early = self.page.app_widgets['early_submit']
        self.assertTrue(early.isEnabled())
        unsupported = {'supported': False, 'reason': 'hardware'}
        self.page.fsr411_support = {'vk': unsupported, 'dx12': unsupported, 'gpu': {'vendor_id': 0x1002}}
        self.page._refresh_choices()
        self.assertFalse(early.isEnabled())
        self.assertFalse(self.page.early_reason.isHidden())
        self.settings['extra_env'] = 'BB_EARLY_SUBMIT=force'
        self.page._refresh_choices()
        self.assertTrue(early.isEnabled())
        self.assertTrue(self.page.early_reason.isHidden())

    def test_complete_download_replaces_atomically(self):
        target = self.folder / 'asset.spv'
        target.write_bytes(b'old')
        response = io.BytesIO(b'new-shader')
        response.headers = {'Content-Length': '10'}
        progress = []
        with patch.object(qt.urllib.request, 'urlopen', return_value=response):
            qt.download_fsr4_assets(self.folder, ['asset.spv'], 'https://example.invalid',
                lambda done, total: progress.append((done, total)), threading.Event())
        self.assertEqual(target.read_bytes(), b'new-shader')
        self.assertEqual(progress, [(1, 1)])
        self.assertEqual(list(self.folder.glob('*.part')), [])

    def test_incomplete_and_cancelled_download_preserve_existing_files(self):
        target = self.folder / 'asset.spv'
        target.write_bytes(b'old')
        response = io.BytesIO(b'short')
        response.headers = {'Content-Length': '100'}
        with patch.object(qt.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(OSError):
                qt.download_fsr4_assets(self.folder, ['asset.spv'], 'https://example.invalid',
                    lambda *_args: None, threading.Event())
        self.assertEqual(target.read_bytes(), b'old')
        self.assertEqual(list(self.folder.glob('*.part')), [])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(qt.DownloadCancelled):
            qt.download_fsr4_assets(self.folder, ['asset.spv'], '', lambda *_args: None, cancel)
        self.assertEqual(target.read_bytes(), b'old')

    def test_graphics_renders_offscreen(self):
        self.page.resize(1050, 800)
        self.page.show()
        self.app.processEvents()
        self.assertFalse(self.page.grab().isNull())


if __name__ == '__main__':
    unittest.main()

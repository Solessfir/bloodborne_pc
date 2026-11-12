"""Audit the integrated Qt window against controls rendered by the reference launcher."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox,
        QDoubleSpinBox, QLabel, QLineEdit, QSlider, QSpinBox, QWidget)
    import bbport_launcher_qt as qt
else:
    qt = None


@unittest.skipIf(qt is None, 'PySide6 is needed for the Qt launcher')
class QtParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        qt.theme.apply(cls.app)
        cls.reference = json.loads((ROOT / 'docs/qt-parity.json').read_text())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        config = self.data / 'settings.json'
        config.write_text(json.dumps({'setup_done': True, 'ui_mode': 'expert', 'auto_graphics': False,
                                      'ui_language': 'en', 'seen_version': qt.backend.VERSION}))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.multiple(qt.backend, PORT_DIR=self.data, DATA_DIR=self.data,
            CONFIG_DIR=self.data, CONFIG_FILE=config))
        stack.enter_context(patch.dict(os.environ, BB_CONFIG=str(self.data / 'bbport.ini')))
        # Hardware, network checks and controller acquisition have their own service tests.
        for cls, method in ((qt.SystemPage, 'check_hardware'), (qt.HelpPage, 'check_installation'),
                            (qt.GraphicsPage, 'recheck_support'), (qt.ControlsPage, 'start_pads')):
            stack.enter_context(patch.object(cls, method))
        self.window = qt.LauncherWindow()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_all_reference_pages_are_integrated_and_navigable(self):
        self.assertEqual(set(self.window.pages), set(self.reference['pages']))
        self.assertEqual(len(self.window.page_ids), len(self.reference['pages']))
        self.assertEqual(set(self.window.page_ids), set(self.reference['pages']))
        self.assertEqual(self.window.tabs.count(), len(self.reference['pages']))
        self.assertEqual(self.window.navigation.count(), len(self.reference['pages']))
        for page in self.reference['pages']:
            with self.subTest(page=page):
                self.window.show_page(page)
                index = self.window.page_ids.index(page)
                self.assertEqual(self.window.tabs.currentIndex(), index)
                self.assertEqual(self.window.navigation.currentRow(), index)
                self.assertEqual(self.window.navigation.item(index).isHidden(), page == 'log')
                self.assertEqual(self.window.header.title.text(), self.window.tabs.tabText(index))
                self.assertEqual(self.window.header.isHidden(), page == 'play')
                if page not in ('play', 'log'):
                    self.assertTrue(self.window.header.description.text().strip(), 'Page description is missing')

    def test_reference_entries_are_real_controls_in_their_pages(self):
        interactive = (QAbstractButton, QComboBox, QLineEdit, QDoubleSpinBox, QSlider, QSpinBox)
        for entry in self.reference['entries']:
            page, key = entry['page'], entry['key']
            with self.subTest(page=page, key=key, title=entry['title']):
                widget = self.window.pages[page].findChild(QWidget, key)
                self.assertIsNotNone(widget, f'Missing {page}: {key} ({entry["title"]})')
                if key.startswith('button:') or key == 'mouse:layout':
                    self.assertIsInstance(widget, QAbstractButton)
                    self.assertGreater(widget.receivers('2clicked(bool)'), 0, 'Action has no handler')
                elif key == 'window_size' and isinstance(widget, QLabel):
                    self.assertTrue(widget.text().strip(), 'Informational field is empty')
                elif key == 'controller_test':
                    self.assertIs(widget, self.window.pages[page].setting_widgets[key])
                    self.assertFalse(self.window.pages[page].pad_picture.pixmap().isNull())
                elif key == 'characters':
                    self.assertIsNotNone(widget.layout(), 'Character list is an empty placeholder')
                elif isinstance(widget, interactive):
                    if isinstance(widget, QComboBox):
                        self.assertGreater(widget.count(), 0, 'Choice has no options')
                        self.assertGreaterEqual(widget.currentIndex(), 0, 'Choice has no selected value')
                else:
                    buttons = widget.findChildren(QAbstractButton)
                    self.assertTrue(buttons, 'Setting has no editable controls')
                    self.assertTrue(any(button.isChecked() for button in buttons), 'Choice has no selected value')
                    self.assertTrue(all(button.receivers('2clicked(bool)') or button.receivers('2toggled(bool)')
                                        for button in buttons), 'Choice has no handlers')

    def test_shared_palette_and_control_states_render(self):
        colors = qt.theme.theme
        palette = self.app.palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Window).name(), colors.BG)
        self.assertEqual(palette.color(QPalette.ColorRole.Highlight).name(), colors.BLOOD)
        switch = QCheckBox('Enabled')
        self.addCleanup(switch.deleteLater)
        switch.resize(140, 40)
        switch.show()
        self.app.processEvents()
        off = switch.grab().toImage()
        switch.setChecked(True)
        on = switch.grab().toImage()
        self.assertNotEqual(off, on)
        self.assertTrue(any(on.pixelColor(x, on.height() // 2).name() in (colors.BLOOD, colors.BLOOD_HOVER)
                            for x in range(round(36 * on.devicePixelRatio()))))
        for widget in (QComboBox(), QDoubleSpinBox()):
            with self.subTest(control=type(widget).__name__):
                self.addCleanup(widget.deleteLater)
                if isinstance(widget, QComboBox):
                    widget.addItem('Quality')
                widget.resize(180, 36)
                widget.show()
                self.app.processEvents()
                image = widget.grab().toImage()
                left = image.width() - round(30 * image.devicePixelRatio())
                gold = tuple(bytes.fromhex(colors.GOLD_LIGHT[1:]))
                self.assertTrue(any(sum(abs(value - target) for value, target in
                                        zip(image.pixelColor(x, y).getRgb()[:3], gold)) < 30
                                    for x in range(left, image.width()) for y in range(image.height())),
                                'Control arrows are not visible against the field')

    def test_page_header_uses_reference_cathedral_art(self):
        self.window.show_page('graphics')
        header = self.window.header
        header.resize(932, 118)
        header._render()
        self.assertFalse(header.art.isNull())
        image = header.art.toImage()
        self.assertNotEqual(image.pixelColor(image.width() // 2, 10),
                            image.pixelColor(image.width() - 40, 10))


if __name__ == '__main__':
    unittest.main()

"""Reference sidebar geometry, icon fallback and shared multilingual search."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))

if importlib.util.find_spec('PySide6'):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication, QListWidget, QStyle, QStyleOptionViewItem
    import bbport_qt_navigation as navigation
else:
    navigation = None


@unittest.skipIf(navigation is None, 'PySide6 is needed for native Qt navigation')
class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reference_row_heights_and_expert_heading_preserve_indices(self):
        widget = QListWidget()
        self.addCleanup(widget.deleteLater)
        widget.addItems(['Play', 'All graphics', 'Game files'])
        pages = ['play', 'graphics', 'game']
        for compact, height in ((False, 37), (True, 32)):
            delegate = navigation.NavigationDelegate(pages, compact, widget)
            widget.setItemDelegate(delegate)
            for row, page in enumerate(pages):
                size = delegate.sizeHint(QStyleOptionViewItem(), widget.model().index(row, 0))
                self.assertEqual(size.height(), height + (24 if page == 'graphics' else 0))
            self.assertEqual(widget.count(), 3)
            self.assertEqual(delegate.page_ids, pages)

    def test_icon_font_prefers_fluent_and_falls_back_to_reference_linux_symbols(self):
        pages = ['play', 'controls', 'graphics']
        with patch.object(navigation.QFontDatabase, 'families', return_value=['Segoe Fluent Icons']):
            delegate = navigation.NavigationDelegate(pages)
            self.assertEqual(delegate.icon_font.family(), 'Segoe Fluent Icons')
            self.assertEqual(delegate.icons, {key: navigation.backend.theme.ICON[key] for key in pages})
        with patch.object(navigation.QFontDatabase, 'families', return_value=[]):
            delegate = navigation.NavigationDelegate(pages)
            self.assertEqual(delegate.icons, {key: navigation.SYMBOLS[key] for key in pages})
            self.assertTrue(all(ord(glyph) < 0xE000 for glyph in delegate.icons.values()))

    def test_selected_row_draws_reference_accent_and_leaves_heading_clear(self):
        widget = QListWidget()
        self.addCleanup(widget.deleteLater)
        widget.addItem('All graphics')
        delegate = navigation.NavigationDelegate(['graphics'], parent=widget)
        image = QImage(224, 61, QImage.Format.Format_ARGB32)
        background = QColor(navigation.backend.theme.BG)
        image.fill(background)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 224, 61)
        option.state = QStyle.StateFlag.State_Selected
        painter = QPainter(image)
        delegate.paint(painter, option, widget.model().index(0, 0))
        painter.end()
        self.assertEqual(image.pixelColor(2, 42), QColor(navigation.backend.theme.BLOOD_LIGHT))
        self.assertEqual(image.pixelColor(2, 10), background)
        self.assertEqual(image.pixelColor(200, 42), QColor(navigation.backend.theme.CARD))

    def test_search_reuses_aliases_topics_inflections_and_resolution_normalization(self):
        with patch.object(navigation.backend, 'LANG', 'en'):
            for query, key in [('godmode', 'cheat_no_death'), ('mauskamera', 'play_with'),
                               ('2560x1440', 'output_res'), ('black screen', 'topic:black_screen'),
                               ('first start', 'action:setup')]:
                with self.subTest(query=query):
                    results = navigation.ranked_settings(query, limit=100)
                    self.assertIn(key, [entry['key'] for entry in results])
            self.assertEqual(navigation.ranked_settings(''), [])
            self.assertEqual(navigation.ranked_settings('godmode', page_ids=['play']), [])
            self.assertIn('page:controls', [entry['key'] for entry in navigation.ranked_settings('controller')])


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-2.0-or-later
"""Reference sidebar geometry and shared settings-search ranking for Qt."""
from types import SimpleNamespace

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

import bbport_launcher_win as backend
import bbport_search as search
from bbport_qt_catalog import FIELDS


# The reference Linux theme uses these symbols when Windows' private-use fonts are absent.
SYMBOLS = dict(play='▶', graphics='▦', game='♟', cheats='⚒', online='◎', mods='▤',
    trophies='★', controls='✥', advanced='⚙', log='≡', system='▣', help='?',
    picture='▧', saves='↓', language='文', gameplay='⚔')


class NavigationDelegate(QStyledItemDelegate):
    def __init__(self, page_ids, compact=False, parent=None):
        super().__init__(parent)
        self.page_ids = page_ids
        self.row_height = 32 if compact else 37
        self.heading_height = 24
        families = set(QFontDatabase.families())
        family = next((name for name in ('Segoe Fluent Icons', 'Segoe MDL2 Assets') if name in families), None)
        self.icon_font = QFont(family or 'DejaVu Sans', 12)
        self.icons = {page: backend.theme.ICON.get(page, '') if family else SYMBOLS.get(page, '')
                      for page in page_ids}

    def sizeHint(self, option, index):
        heading = self.heading_height if self.page_ids[index.row()] == 'graphics' else 0
        return QSize(224, self.row_height + heading)

    def paint(self, painter, option, index):
        page = self.page_ids[index.row()]
        theme = backend.theme
        rect = QRect(option.rect)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        if page == 'graphics':
            font = QFont('Inter', 8)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(rect.adjusted(12, 4, 0, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                             backend._('EXPERT'))
            rect.setTop(rect.top() + self.heading_height)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            painter.setBrush(QColor(theme.CARD if selected else theme.SURFACE))
            painter.setPen(QPen(QColor(theme.BORDER), 1) if selected else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(rect.adjusted(1, 0, -1, -1)), 8, 8)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.BLOOD_LIGHT))
            painter.drawRoundedRect(QRectF(rect.left() + 1, rect.center().y() - 9, 3, 18), 1.5, 1.5)
        painter.setFont(self.icon_font)
        painter.setPen(QColor(theme.GOLD if selected or hover else theme.MUTED))
        painter.drawText(QRect(rect.left() + 10, rect.top(), 24, rect.height()),
                         Qt.AlignmentFlag.AlignCenter, self.icons.get(page, ''))
        font = QFont(option.font)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT_STRONG if selected else theme.TEXT if hover else theme.TEXT_SOFT))
        text_rect = rect.adjusted(44, 0, -8, 0)
        text = painter.fontMetrics().elidedText(str(index.data() or ''), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


def ranked_settings(query, page_ids=None, limit=7, expert=False):
    """Return the reference search's page, setting, help-topic and setup results."""
    titles = {page: backend._(*labels) for page, labels in backend.NAV_SIMPLE + backend.NAV_EXPERT}
    titles['log'] = backend._('Log')
    allowed = set(page_ids) if page_ids is not None else set(titles)
    entries = []
    for page, title in titles.items():
        if page not in allowed:
            continue
        entries.append(dict(kind='page', page=page, title=title, hint='', key='page:' + page))
        for field in FIELDS.get(page, []):
            # Qt reveals the target after navigation; the shared ranker must skip Tk visibility checks.
            entries.append(dict(kind='setting', page=page, title=backend._(field['title']),
                hint=backend._(field['hint']).replace('{data_dir}', str(backend.DATA_DIR)), key=field['key'], reveal=True))
    if 'help' in allowed:
        for topic in backend.bbport_help.TOPIC_ORDER:
            title, why, _steps = backend.bbport_help.TOPICS[topic]
            entries.append(dict(kind='topic', page='help', topic=topic, title=backend._(title),
                                hint=backend._(why), key='topic:' + topic))
        entries.append(dict(kind='action', page='help', run='open_setup', title=backend._('Repeat the setup'),
                            hint=backend._('Set everything up again, step by step.'), key='action:setup'))
    for entry in entries:
        extra = search.WORDS.get(entry['key'], '')
        if backend.GAME_TESTS:
            extra += ' ' + search.GAME_TEST_WORDS.get(entry['key'], '')
        entry['haystack'] = tuple(search.fold(text) for text in (entry['title'], entry['hint'], extra))
    # Every Qt entry is revealed after navigation, so none is hidden for another choice.
    state = SimpleNamespace(search_entries=entries, app={'ui_mode': 'expert' if expert else 'simple'},
                            hidden_for_now=lambda _entry: False)
    return search.SearchMixin.search(state, query, limit)

# SPDX-License-Identifier: GPL-2.0-or-later
"""The reference launcher's cathedral header and page descriptions."""
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

import bbport_launcher_win as backend


DESCRIPTIONS = {
    'picture': 'The launcher sets the technical settings for your PC. You choose how it should feel; the in-game menu (Insert or L3+R3) changes the same values.',
    'controls': 'Keyboard, mouse and controller: each has its own buttons, and both work side by side.',
    'online': "Messages, bloodstains and ghosts come from The Hunter's Dream; bells and summons go through a shadNet server.",
    'saves': 'Your characters: bring them from another version, back them up, put a backup back.',
    'mods': 'The game files are never changed: mods are layered over them at start.',
    'language': "The launcher's language and look, what it does while you play, and shortcuts to the game.",
    'trophies': 'Trophies the game unlocks while you play; updated live, kept with your saves.',
    'help': 'The problems any installation can run into, checked for this PC, and how to fix each of them.',
    'graphics': 'Every graphics and frame rate setting. Stored in bbport.ini; the in-game menu (Insert or L3+R3) changes the same values.',
    'game': 'Your game files and their add-ons. Set once, usually by the setup guide.',
    'gameplay': "The game's language and sound, and changes to how it plays and its menus.",
    'cheats': 'Game patches for version 1.09, applied at start. Leave them off for a normal play-through.',
    'system': 'What your PC can do, rated like the hardware check on bbport.de, and the system requirements.',
    'advanced': 'Launcher options, performance switches and diagnostics.',
    'log': '',
}

RUSSIAN_DESCRIPTIONS = {
    'controls': 'Клавиатура, мышь и геймпад: у каждого свои кнопки, и они работают одновременно.',
    'mods': 'Файлы игры не меняются: моды накладываются при запуске.',
    'trophies': 'Трофеи, которые игра открывает во время игры; обновляются сразу, хранятся с сохранениями.',
    'cheats': 'Патчи игры для версии 1.09, применяются при запуске. Для обычного прохождения оставьте их выключенными.',
    'advanced': 'Настройки лаунчера, производительность и диагностика.',
}


class PageHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('pageHeader')
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.art = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 22)
        layout.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName('pageTitle')
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.description = QLabel()
        self.description.setObjectName('pageSubtitle')
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._render)

    def set_page(self, page, title):
        self.title.setText(title)
        description = DESCRIPTIONS.get(page, '')
        if page == 'system' and backend.GAME_TESTS:
            description = 'What your PC can do, rated like the hardware check on bbport.de, and game tests that measure it: the best settings for a goal, settings side by side, stability.'
        self.description.setText(backend._(description, RUSSIAN_DESCRIPTIONS.get(page)))
        self.description.setVisible(bool(description))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.timer.start(30)

    def _render(self):
        ratio = self.devicePixelRatioF()
        size = max(200, round(self.width() * ratio)), max(1, round(self.height() * ratio))
        self.art = QPixmap.fromImage(ImageQt(backend.theme.header(size, backend.PANEL)))
        self.art.setDevicePixelRatio(ratio)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.art:
            painter.drawPixmap(self.rect(), self.art)
        else:
            painter.fillRect(self.rect(), QColor(backend.PANEL))

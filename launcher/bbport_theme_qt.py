# SPDX-License-Identifier: GPL-2.0-or-later
"""Qt presentation using the existing launcher's palette and bundled fonts."""
from PySide6.QtCore import Qt, QTemporaryDir
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap

import bbport_theme as theme


def apply(app):
    for path in sorted((theme.ASSETS / 'fonts').glob('*.ttf')):
        QFontDatabase.addApplicationFont(str(path))
    app.setStyle('Fusion')
    app.setFont(QFont('Inter', 10))
    app._bbport_style_assets = QTemporaryDir()
    assets = app._bbport_style_assets.path()
    if not assets:
        raise OSError('Could not create launcher style assets.')
    for name, checked, track, knob in (
            ('off', False, '#2a2c31', theme.MUTED), ('on', True, theme.BLOOD, theme.TEXT_STRONG),
            ('off-hover', False, '#33363b', '#a9abaf'), ('on-hover', True, theme.BLOOD_HOVER, '#ffffff'),
            ('off-disabled', False, '#1b1c1f', '#45474b'), ('on-disabled', True, '#3a1518', '#7d7470')):
        image = QPixmap(144, 80)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(0, 0, 36, 20, 10, 10)
        painter.setBrush(QColor(knob))
        painter.drawEllipse(19 if checked else 3, 3, 14, 14)
        painter.end()
        if not image.save(f'{assets}/{name}.png'):
            raise OSError('Could not write launcher style assets.')
    for name, flipped in (('down', False), ('up', True)):
        image = QPixmap(48, 28)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(4, 4)
        painter.setPen(QPen(QColor(theme.GOLD_LIGHT), 1.5))
        end, middle = (5, 2) if flipped else (2, 5)
        painter.drawLine(2, end, 6, middle)
        painter.drawLine(6, middle, 10, end)
        painter.end()
        if not image.save(f'{assets}/{name}.png'):
            raise OSError('Could not write launcher style assets.')
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, theme.BG), (QPalette.ColorRole.WindowText, theme.TEXT),
                        (QPalette.ColorRole.Base, theme.SURFACE), (QPalette.ColorRole.Text, theme.TEXT),
                        (QPalette.ColorRole.Button, theme.CARD), (QPalette.ColorRole.ButtonText, theme.TEXT),
                        (QPalette.ColorRole.AlternateBase, theme.CARD),
                        (QPalette.ColorRole.ToolTipBase, theme.CARD), (QPalette.ColorRole.ToolTipText, theme.TEXT),
                        (QPalette.ColorRole.PlaceholderText, theme.MUTED),
                        (QPalette.ColorRole.Highlight, theme.BLOOD), (QPalette.ColorRole.HighlightedText, theme.TEXT_STRONG),
                        (QPalette.ColorRole.Link, theme.GOLD_LIGHT)]:
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.MUTED))
    app.setPalette(palette)
    app.setStyleSheet(f'''
        QMainWindow, QDialog, QWizard, QWidget#launcher {{ background: {theme.BG}; color: {theme.TEXT}; }}
        QWidget {{ font-family: "Inter"; font-size: 10pt; }}
        QWidget#sidebar {{ background: {theme.BG}; border-right: 1px solid {theme.BORDER}; }}
        QLabel#brand {{ font-family: "Cinzel Bold"; font-size: 17px; color: {theme.TEXT_STRONG}; }}
        QLabel#brandSubtitle {{ font-family: "Cinzel SemiBold"; color: {theme.GOLD}; font-size: 11px; }}
        QLabel#pageTitle {{ font-family: "Cinzel SemiBold"; font-size: 28px; color: {theme.TEXT_STRONG}; }}
        QLabel#pageSubtitle {{ font-size: 9pt; color: {theme.TEXT_SOFT}; }}
        QLabel#pageDescription, QLabel#previewNotice {{ color: {theme.MUTED}; }}
        QLabel#pageDescription {{ font-size: 9pt; }}
        QLabel#sectionTitle, QLabel#sectionHeading {{ font-family: "Cinzel SemiBold"; font-size: 16px; color: {theme.GOLD_LIGHT}; }}
        QLabel#deviceCode {{ font-size: 28px; font-weight: 600; color: {theme.GOLD_LIGHT}; }}
        QLabel#lockedTrophyName {{ color: {theme.MUTED}; }}
        QLabel#trophyName {{ color: {theme.TEXT_STRONG}; font-weight: 600; }}
        QLabel#trophyName, QLabel#lockedTrophyName {{ font-size: 11pt; }}
        QLabel#trophyPercent {{ font-family: "Cinzel SemiBold"; font-size: 26pt; }}
        QProgressBar#trophyProgress {{ min-height: 4px; max-height: 4px; border-radius: 0; }}
        QProgressBar#trophyProgress::chunk {{ background: {theme.GOLD}; border-radius: 0; }}
        QPushButton#trophyTab {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0; color: {theme.MUTED}; padding: 0 0 5px 0; }}
        QPushButton#trophyTab:checked {{ color: {theme.TEXT}; border-bottom-color: {theme.GOLD}; font-weight: 600; }}
        QGroupBox#helpTopicCard {{ border: none; border-radius: 0; }}
        QPushButton#helpTopic {{ background: transparent; border: none; border-radius: 0; text-align: left; color: {theme.TEXT_STRONG}; font-weight: 600; padding: 4px 0; }}
        QPushButton#helpTopic:hover {{ color: {theme.GOLD_LIGHT}; }}
        QPushButton#helpTopic:checked {{ background: transparent; }}
        QPushButton#helpLink {{ background: transparent; border: none; color: {theme.GOLD_LIGHT}; text-align: left; padding: 0; }}
        QLabel#previewNotice {{ font-size: 11px; }}
        QWidget#pageHeader {{ background: {theme.BG}; }}
        QWidget#footer {{ background: {theme.BG}; border-top: 1px solid {theme.BORDER}; }}
        QListWidget#navigation {{ background: transparent; border: none; outline: none; padding: 8px; }}
        QListWidget#navigation::item {{ color: {theme.TEXT_SOFT}; padding: 8px 10px; margin: 2px 0; border: 1px solid transparent; border-radius: 7px; }}
        QListWidget#navigation::item:hover {{ background: {theme.SURFACE}; color: {theme.TEXT}; }}
        QListWidget#navigation::item:selected {{ background: {theme.CARD}; color: {theme.TEXT_STRONG}; border: 1px solid {theme.BORDER}; border-left: 3px solid {theme.BLOOD_LIGHT}; }}
        QTabWidget::pane {{ border: none; background: {theme.BG}; }}
        QScrollArea {{ border: none; background: {theme.BG}; }}
        QPlainTextEdit, QTextEdit {{ border: 1px solid {theme.BORDER}; background: {theme.DEEP}; color: {theme.TEXT_SOFT}; padding: 10px; selection-background-color: {theme.BLOOD}; selection-color: {theme.TEXT_STRONG}; }}
        QWidget#settingsPage {{ background: {theme.BG}; }}
        QGroupBox {{ background: {theme.CARD}; color: {theme.GOLD_LIGHT}; border: 1px solid {theme.BORDER}; border-radius: 12px; padding-top: 18px; font-family: "Cinzel SemiBold"; font-size: 16px; }}
        QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; top: 16px; left: 18px; }}
        QGroupBox[title=""] {{ padding-top: 0; }}
        QGroupBox[flatSection="true"] {{ background: transparent; border: none; border-radius: 0; margin: 0; padding: 0; }}
        QWidget[card="true"] {{ background: {theme.CARD}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: {theme.SURFACE}; color: {theme.TEXT}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px; padding: 7px 10px; min-height: 18px; selection-background-color: {theme.BLOOD}; selection-color: {theme.TEXT_STRONG}; }}
        QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {theme.BORDER_HOVER}; }}
        QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {theme.GOLD}; }}
        QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {{ background: {theme.BG}; color: {theme.MUTED}; border-color: {theme.BORDER}; }}
        QComboBox QAbstractItemView {{ background: {theme.CARD}; color: {theme.TEXT}; border: 1px solid {theme.BORDER_STRONG}; selection-background-color: {theme.CARD_HOVER}; selection-color: {theme.TEXT_STRONG}; padding: 4px; }}
        QComboBox::drop-down {{ border: none; width: 28px; }}
        QComboBox::down-arrow {{ width: 12px; height: 7px; image: url("{assets}/down.png"); }}
        QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ background: {theme.SURFACE}; border: none; width: 18px; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 12px; height: 7px; image: url("{assets}/up.png"); }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 12px; height: 7px; image: url("{assets}/down.png"); }}
        QPushButton {{ background: {theme.CARD}; color: {theme.TEXT}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px; padding: 9px 18px; }}
        QPushButton:hover {{ background: {theme.CARD_HOVER}; border-color: {theme.BORDER_HOVER}; }}
        QPushButton:pressed {{ background: {theme.SURFACE}; }}
        QPushButton:focus {{ border-color: {theme.GOLD}; }}
        QPushButton:checked {{ background: {theme.BLOOD}; border-color: {theme.BLOOD_LIGHT}; color: {theme.TEXT_STRONG}; }}
        QPushButton:disabled {{ color: {theme.MUTED}; background: {theme.BG}; border-color: {theme.BORDER}; }}
        QPushButton#readyLine {{ background: transparent; border: none; text-align: left; color: {theme.TEXT_SOFT}; padding: 5px 0; }}
        QPushButton#readyLine:hover {{ background: {theme.CARD_HOVER}; color: {theme.TEXT_STRONG}; }}
        QPushButton#playButton {{ background: {theme.BLOOD}; border-color: {theme.BLOOD}; color: {theme.TEXT_STRONG}; font-family: "Cinzel Bold"; font-size: 20px; min-width: 160px; min-height: 30px; }}
        QPushButton#playButton:hover {{ background: {theme.BLOOD_HOVER}; border-color: {theme.BLOOD_HOVER}; }}
        QPushButton#playButton:disabled {{ background: {theme.CARD}; border-color: {theme.BORDER}; color: {theme.MUTED}; }}
        QCheckBox, QRadioButton {{ spacing: 8px; padding: 5px 0; }}
        QCheckBox:hover, QRadioButton:hover {{ color: {theme.TEXT_STRONG}; }}
        QCheckBox:disabled, QRadioButton:disabled {{ color: {theme.MUTED}; }}
        QCheckBox::indicator {{ width: 36px; height: 20px; image: url("{assets}/off.png"); }}
        QCheckBox::indicator:checked {{ image: url("{assets}/on.png"); }}
        QCheckBox::indicator:unchecked:hover {{ image: url("{assets}/off-hover.png"); }}
        QCheckBox::indicator:checked:hover {{ image: url("{assets}/on-hover.png"); }}
        QCheckBox::indicator:unchecked:disabled {{ image: url("{assets}/off-disabled.png"); }}
        QCheckBox::indicator:checked:disabled {{ image: url("{assets}/on-disabled.png"); }}
        QRadioButton::indicator {{ width: 18px; height: 18px; }}
        QListWidget, QTreeWidget, QTableWidget {{ background: {theme.SURFACE}; alternate-background-color: {theme.CARD}; color: {theme.TEXT}; border: 1px solid {theme.BORDER}; border-radius: 6px; outline: none; selection-background-color: {theme.BLOOD}; selection-color: {theme.TEXT_STRONG}; }}
        QListWidget::item, QTreeWidget::item, QTableWidget::item {{ padding: 6px; }}
        QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {{ background: {theme.CARD_HOVER}; }}
        QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {theme.BLOOD}; color: {theme.TEXT_STRONG}; }}
        QHeaderView::section {{ background: {theme.CARD}; color: {theme.GOLD_LIGHT}; border: none; border-bottom: 1px solid {theme.BORDER_STRONG}; padding: 8px 6px; }}
        QProgressBar {{ background: {theme.BORDER}; border: none; border-radius: 4px; min-height: 14px; text-align: center; color: {theme.TEXT_STRONG}; }}
        QProgressBar::chunk {{ background: {theme.GOLD_LIGHT}; border-radius: 4px; }}
        QSlider::groove:horizontal {{ height: 4px; background: {theme.BORDER_STRONG}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: {theme.GOLD_LIGHT}; border: none; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}
        QSlider::handle:horizontal:hover {{ background: {theme.TEXT_STRONG}; }}
        QSlider::handle:horizontal:disabled {{ background: {theme.BORDER_STRONG}; }}
        QToolTip {{ color: {theme.TEXT}; background: {theme.CARD}; border: 1px solid {theme.BORDER_STRONG}; padding: 6px; }}
        QMenu {{ background: {theme.CARD}; border: 1px solid {theme.BORDER_STRONG}; padding: 4px; }}
        QMenu::item {{ padding: 7px 20px; }}
        QMenu::item:selected {{ background: {theme.BLOOD}; color: {theme.TEXT_STRONG}; }}
        QStatusBar {{ background: {theme.BG}; color: {theme.MUTED}; font-size: 11px; }}
        QStatusBar::item {{ border: none; }}
        QScrollBar:vertical {{ background: {theme.BG}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {theme.BORDER_STRONG}; border-radius: 4px; min-height: 28px; }}
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {theme.BORDER_HOVER}; }}
        QScrollBar:horizontal {{ background: {theme.BG}; height: 10px; margin: 0; }}
        QScrollBar::handle:horizontal {{ background: {theme.BORDER_STRONG}; border-radius: 4px; min-width: 28px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    ''')

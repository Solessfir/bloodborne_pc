# SPDX-License-Identifier: GPL-2.0-or-later
"""Play, picture preferences and setup using the shared launcher's hardware profiles."""
from pathlib import Path
from types import SimpleNamespace

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget, QWizard, QWizardPage)

import bbport_display as display
import bbport_hardware as hardware
import bbport_help as help_service
import bbport_launcher_win as backend
import bbport_saves as saves
import bbport_setup as setup
from bbport_qt_services import _Page, _label, _open
from bbport_qt_services import HelpPage, OnlinePage, SystemPage
from bbport_qt_content import SavesPage


class _Profile(setup.SetupMixin):
    """Supply the existing profile helpers with plain pending preferences instead of Tk vars."""
    def __init__(self, page):
        self.page = page
        self.app = {**backend.APP_DEFAULTS, **page.settings, **page.app_values()}
        self.graphics = {**backend.INI_DEFAULTS, **page.graphics, **page.ini_values()}
        system = getattr(page, 'system_page', None)
        self.rating = system.rating if system else None
        self.gpu_line = system.gpu_line if system else ''
        self.cpu = system.cpu if system else None
        self.ram = system.ram if system else 0
        self.rating_views = []
        self.tk = SimpleNamespace(TclError=RuntimeError)
        self.status = SimpleNamespace(configure=lambda **_kwargs: None)

    def var(self, key, store='app'):
        values = self.app if store == 'app' else self.graphics

        def get():
            value = values.get(key, '')
            return value == '1' if store == 'ini' and key in backend.INI_FLAGS else value

        def put(value):
            values[key] = ('1' if value else '0') if store == 'ini' and isinstance(value, bool) else str(value) if store == 'ini' else value
            if store == 'ini' and key == 'output_res' and self.app.get('output_display') and value != display.size_text(self.display_size()):
                self.app['output_display'] = False
        return SimpleNamespace(get=get, set=put)

    def display_size(self):
        monitor = display.monitor(self.app.get('game_monitor', ''))
        if monitor:
            return monitor.size
        screen = self.page.screen() or QApplication.primaryScreen()
        return (round(screen.size().width() * screen.devicePixelRatio()),
                round(screen.size().height() * screen.devicePixelRatio())) if screen else (1920, 1080)

    def refresh_status(self):
        pass


class _Preferences(_Page):
    settings_changed = Signal()
    device_requested = Signal(str)
    play_requested = Signal()

    def __init__(self, settings, graphics, parent=None):
        super().__init__(settings, parent)
        self.graphics = graphics
        self.ini_fields = {}
        self._initial_app, self._initial_ini = dict(settings), dict(graphics)
        self._app_pending, self._ini_pending = {}, {}
        self._refreshing = False
        self.goal_buttons = {}

    def _value(self, widget, store):
        if isinstance(widget, QCheckBox):
            return ('1' if widget.isChecked() else '0') if store == 'ini' else widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        return widget.text()

    def app_values(self):
        values = {**self._app_pending, **{key: self._value(widget, 'app') for key, widget in self.fields.items()}}
        return {key: value for key, value in values.items() if self._initial_app.get(key, backend.APP_DEFAULTS.get(key)) != value}

    def ini_values(self):
        values = {**self._ini_pending, **{key: self._value(widget, 'ini') for key, widget in self.ini_fields.items()}}
        return {key: value for key, value in values.items() if self._initial_ini.get(key, backend.INI_DEFAULTS.get(key)) != value}

    def _control(self, form, key, title, store='app', options=None, checkbox=False):
        if checkbox:
            widget = QCheckBox(backend._(title))
        elif options is not None:
            widget = QComboBox()
            for value, labels in options:
                widget.addItem(backend._(*labels), value)
        else:
            widget = QLineEdit()
        widget.setObjectName(key)
        (self.fields if store == 'app' else self.ini_fields)[key] = widget
        form.addRow(widget) if checkbox else form.addRow(backend._(title), widget)
        signal = widget.toggled if checkbox else widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.textEdited
        signal.connect(self._changed)
        return widget

    def _changed(self, *_args):
        if not self._refreshing:
            self._draw()
            self.settings_changed.emit()

    def _goals(self, form):
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        self.goal_group = QButtonGroup(row)
        for goal in ('smooth', 'balanced', 'quiet'):
            button = QPushButton(backend.Launcher.goal_name(self, goal))
            button.setObjectName('goal_' + goal)
            button.setCheckable(True)
            button.setStyleSheet('padding: 5px 14px; border-radius: 0;')
            self.goal_group.addButton(button)
            self.goal_buttons[goal] = button
            button.clicked.connect(lambda _checked=False, goal=goal: self.set_goal(goal))
            line.addWidget(button)
        line.addStretch()
        row.setObjectName('goal')
        form.addRow(row)
        self.goal_note = _label('')
        form.addRow(self.goal_note)

    GOAL_TEXTS = backend.Launcher.GOAL_TEXTS

    def set_goal(self, goal):
        self._app_pending['goal'] = goal
        profile = _Profile(self)
        chosen = profile.recommended()
        if chosen:
            profile.apply_profile(chosen[2])
            self._take_profile(profile)
        self._draw()
        self.settings_changed.emit()

    def _take_profile(self, profile):
        self._app_pending = {key: value for key, value in profile.app.items() if self._initial_app.get(key, backend.APP_DEFAULTS.get(key)) != value}
        self._ini_pending = {key: value for key, value in profile.graphics.items() if self._initial_ini.get(key, backend.INI_DEFAULTS.get(key)) != value}
        self._fill()

    def apply_recommended(self, res=None):
        profile = _Profile(self)
        chosen = profile.recommended(res)
        if chosen:
            profile.apply_profile(chosen[2])
            self._take_profile(profile)
            self._draw()
            self.settings_changed.emit()

    def undo_recommended(self):
        profile = _Profile(self)
        profile.undo_profile()
        self._take_profile(profile)
        self._draw()
        self.settings_changed.emit()

    def save(self):
        app, ini = self.app_values(), self.ini_values()
        self.settings.update(app)
        self.graphics.update(ini)
        self._initial_app.update(app)
        self._initial_ini.update(ini)
        self._app_pending.clear()
        self._ini_pending.clear()

    def refresh(self, settings=None, graphics=None):
        if settings is not None:
            self.settings = settings
        if graphics is not None:
            self.graphics = graphics
        self._initial_app, self._initial_ini = dict(self.settings), dict(self.graphics)
        self._app_pending.clear()
        self._ini_pending.clear()
        self._fill()
        self._draw()

    def _fill(self):
        self._refreshing = True
        for store, fields, initial, pending, defaults in (
                ('app', self.fields, self._initial_app, self._app_pending, backend.APP_DEFAULTS),
                ('ini', self.ini_fields, self._initial_ini, self._ini_pending, backend.INI_DEFAULTS)):
            for key, widget in fields.items():
                value = pending.get(key, initial.get(key, defaults.get(key, '')))
                if isinstance(widget, QCheckBox):
                    widget.setChecked(value == '1' if store == 'ini' else bool(value))
                elif isinstance(widget, QComboBox):
                    index = widget.findData(value)
                    if index < 0:
                        widget.addItem(str(value), value)
                        index = widget.count() - 1
                    widget.setCurrentIndex(index)
                else:
                    widget.setText(str(value))
        self._refreshing = False

    def _draw(self):
        goal = self.app_values().get('goal', self.settings.get('goal', 'smooth'))
        for key, button in self.goal_buttons.items():
            button.setChecked(key == goal)
        if self.goal_buttons:
            self.goal_note.setText(backend._(self.GOAL_TEXTS.get(goal, self.GOAL_TEXTS['smooth'])[1]))

    def set_game_running(self, running):
        super().set_game_running(running)
        for widget in [*self.fields.values(), *self.ini_fields.values(), *self.goal_buttons.values()]:
            widget.setEnabled(not running)


class _Hero(QWidget):
    game_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('homeHero')
        screen = self.screen() or QApplication.primaryScreen()
        self.setFixedHeight(200 if screen and screen.availableGeometry().height() < 1000 else 286)
        self.info = None
        self.art = None
        self.choose_rect = QRect()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._render)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.timer.start(30)

    def _render(self):
        self.art = QPixmap.fromImage(ImageQt(backend.theme.hero((max(400, self.width()), self.height()), backend.PANEL)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.art:
            painter.drawPixmap(0, 0, self.art)
        else:
            painter.fillRect(self.rect(), QColor(backend.PANEL))
        painter.setPen(QColor(backend.GOLD))
        painter.setFont(QFont('Cinzel SemiBold', 10))
        painter.drawText(36, 62, backend._('native port · Windows' if backend.WINDOWS else 'native port · Linux').upper())
        painter.setFont(QFont('Cinzel Bold', 40))
        painter.setPen(QColor(backend.theme.TEXT_STRONG))
        painter.drawText(34, 120, 'BLOODBORNE')
        painter.setFont(QFont('Inter Medium', 9))
        chip = backend._('CUSA03173 · game version {}').format(self.info[1]) if self.info else backend._('Choose your game folder (Game files)')
        x = 36
        for index, text in enumerate((chip, f'v{backend.VERSION}')):
            width = painter.fontMetrics().horizontalAdvance(text) + 26
            rect = QRect(x, 148, width, 28)
            painter.setBrush(QColor(8, 9, 10, 190))
            painter.setPen(QColor(backend.theme.BORDER_STRONG))
            painter.drawRoundedRect(rect, 14, 14)
            painter.setPen(QColor(backend.GOLD if index == 0 and self.info else backend.theme.TEXT_STRONG))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if index == 0:
                self.choose_rect = rect if not self.info else QRect()
            x += width + 8
        painter.end()

    def mousePressEvent(self, event):
        if self.choose_rect.contains(event.position().toPoint()):
            self.game_requested.emit()


class _ReadyLine(QPushButton):
    def __init__(self):
        super().__init__()
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.timeout.connect(self.fit_text)

    def fit_text(self):
        margins = self.layout().contentsMargins()
        self.setMinimumHeight(self.label.heightForWidth(self.label.width()) + margins.top() + margins.bottom())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.fit_timer.start(0)
        return super().eventFilter(watched, event)


class HomePage(_Preferences):
    def __init__(self, settings, graphics, parent=None):
        super().__init__(settings, graphics, parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.hero = _Hero()
        self.hero.game_requested.connect(lambda: self.page_requested.emit('game'))
        self.body.insertWidget(0, self.hero)
        cards = QWidget()
        row = QHBoxLayout(cards)
        row.setContentsMargins(28, 0, 28, 22)
        row.setSpacing(20)
        self.body.addWidget(cards)
        _, ready = self._card('Ready check')
        ready_card = ready.parentWidget()
        self.body.removeWidget(ready_card)
        row.addWidget(ready_card, 1)
        self.checks = {}
        self.check_icons, self.check_arrows = {}, {}
        self.targets = {}
        for key in ('news', 'system', 'settings', 'game', 'saves', 'online', 'cheats', 'fsr4'):
            button = _ReadyLine()
            button.setObjectName('readyLine')
            policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            policy.setHeightForWidth(True)
            button.setSizePolicy(policy)
            line = QHBoxLayout(button)
            line.setContentsMargins(4, 4, 4, 4)
            icon = _label('')
            icon.setFixedWidth(16)
            icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            line.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            label = _label('')
            button.label = label
            label.installEventFilter(button)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            line.addWidget(label, 1)
            arrow = _label('›')
            arrow.setStyleSheet(f'color: {backend.GOLD};')
            arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            line.addWidget(arrow, 0, Qt.AlignmentFlag.AlignTop)
            self.check_icons[key], self.check_arrows[key] = icon, arrow
            button.clicked.connect(lambda _checked=False, key=key: self._follow(key))
            ready.addRow(button)
            self.checks[key] = button, label
        _, quick = self._card('Your goal')
        quick_card = quick.parentWidget()
        self.body.removeWidget(quick_card)
        row.addWidget(quick_card, 1)
        self._goals(quick)
        self.expected = QPushButton()
        self.expected.setStyleSheet(f'color: {backend.theme.GOLD_LIGHT}; background: transparent; border: none; text-align: left; padding: 0;')
        self.expected.clicked.connect(lambda: self.page_requested.emit('picture'))
        quick.addRow(self.expected)
        self.device = QComboBox(self)
        self.device.hide()
        self.device.addItem(backend._('Controller'), 'controller')
        self.device.addItem(backend._('Keyboard and mouse'), 'keyboard')
        self.fields['play_with'] = self.device
        devices = QWidget()
        device_row = QHBoxLayout(devices)
        device_row.setContentsMargins(0, 0, 0, 0)
        device_row.setSpacing(0)
        self.device_group = QButtonGroup(devices)
        self.device_buttons = {}
        for value, title in (('controller', 'Controller'), ('keyboard', 'Keyboard and mouse')):
            button = QPushButton(backend._(title))
            button.setCheckable(True)
            button.setStyleSheet('padding: 5px 12px; border-radius: 0;')
            self.device_group.addButton(button)
            self.device_buttons[value] = button
            button.clicked.connect(lambda _checked=False, value=value: self._choose_device(value))
            device_row.addWidget(button)
        device_row.addStretch()
        devices.setObjectName('play_with')
        quick.addRow(backend._('You play with'), devices)
        self._control(quick, 'fullscreen', 'Fullscreen', checkbox=True)
        self._control(quick, 'online', 'Play online', checkbox=True)
        self.online_note = _label('')
        quick.addRow(self.online_note)
        self.characters = _label('')
        quick.addRow(self.characters)
        self.refresh()

    def _choose_device(self, value):
        self.device.setCurrentIndex(self.device.findData(value))
        self._changed()
        self.device_requested.emit(value)

    def set_game_running(self, running):
        super().set_game_running(running)
        for button in self.device_buttons.values():
            button.setEnabled(not running)

    def _follow(self, key):
        target = self.targets.get(key)
        if target:
            target()

    def _check(self, key, text, page=None):
        button, label = self.checks[key]
        glyph, color = {'✓': ('✓', backend.GOLD), '•': ('ⓘ', backend.theme.MUTED),
            '⚠': ('ⓘ', backend.theme.AMBER), '✗': ('×', backend.theme.BLOOD_LIGHT)}.get(text[:1], ('', backend.TEXT))
        self.check_icons[key].setText('▣' if key == 'system' else glyph)
        self.check_icons[key].setStyleSheet(f'color: {backend.GOLD if key == "system" else color};')
        label.setText(text[1:].lstrip() if glyph else text)
        label.setStyleSheet(f'color: {backend.TEXT if text.startswith("✓") else color};')
        self.check_arrows[key].setVisible(bool(page) or key == 'news')
        button.layout().invalidate()
        button.fit_text()
        button.updateGeometry()
        button.setVisible(bool(text))
        self.targets[key] = (lambda: self.page_requested.emit(page)) if page else None

    def _draw(self):
        super()._draw()
        values = {**self.settings, **self.app_values()}
        for device, button in self.device_buttons.items():
            button.setChecked(device == (values.get('play_with') or 'controller'))
            button.setEnabled(not self.running)
        graphics = {**self.graphics, **self.ini_values()}
        info = backend.game_info(values.get('game_dir', ''))
        self.hero.info = info
        self.hero.update()
        self._check('game', backend._('✓ Game version {}: every patch available').format(info[1]) if info and info[1] == backend.PATCH_VERSION else
            backend._('⚠ Game version {}: runs at 30 FPS without the community patches (they are for 1.09)').format(info[1]) if info else
            backend._('✗ No eboot.bin in the game folder (Game files)'), 'game')
        target = saves.target_dir(backend.saves_folder(values), values.get('game_dir', ''))
        names = []
        try:
            if saves.is_save_folder(target):
                names = saves.SaveSet('', target).names
        except OSError:
            pass
        self._check('saves', backend._('✓ Saves found in {}').format(backend.saves_folder(values)) if target.is_dir() else
            backend._('• No saves yet: bring your character from another version, or the game creates them'), 'saves')
        self.characters.setText(', '.join(names))
        online = values.get('online')
        name = backend.pool_account(values)
        signed = bool(name)
        self._check('online', backend._('⚠ Online is on, but you are not signed in yet: sign in now') if online and not signed else '', 'online')
        self.online_note.setText(backend._('signed in as {}').format(name) if online and signed else
            backend._('not signed in ›') if online and not signed else '')
        cheats = [backend._(*title).split(' (')[0] for key, title, _on in backend.CHEATS if graphics.get(key) == '1']
        self._check('cheats', backend._('⚠ Cheats on: {}').format(', '.join(cheats)) if cheats else '', 'cheats')
        self._check('fsr4', backend._('• FSR 4 files missing: FSR 3.1 is used meanwhile. Click to download (30 MB)')
            if graphics.get('upscaler') == 'fsr4' and backend.fsr4_missing() else '', 'graphics')
        self._check('news', backend._('• New in version {}: what has changed').format(backend.VERSION)
            if values.get('setup_done') and values.get('seen_version') != backend.VERSION else '')
        self.targets['news'] = lambda: _open(backend.RELEASES_PAGE)
        profile = _Profile(self)
        expected = profile.expectation()
        self.expected.setText(expected[0] + '  ›' if expected else '')
        self._check('system', backend._('Performance: {}').format(profile.rating.summary) if profile.rating else backend._('Performance: checking your PC…'), 'system')
        differences = profile.differences()
        self._check('settings', '⚠ ' + backend._('Settings: {} differ from the recommendation for your PC').format(len(differences)) if differences else
            '✓ ' + backend._('Settings: made for your PC and your goal') if profile.rating else '', 'picture')


class PicturePage(_Preferences):
    def __init__(self, settings, graphics, parent=None):
        super().__init__(settings, graphics, parent)
        _, form = self._card('Made for your PC')
        self.state = _label('')
        self.summary = _label('')
        self.pc = _label('')
        form.addRow(self.state)
        form.addRow(self.summary)
        form.addRow(self.pc)
        form.addRow(_label('Your goal'))
        self._goals(form)
        self.details_button = self._button(form, 'Show the settings one by one', self.toggle_details)
        self.undo_button = self._button(form, 'Undo', self.undo_recommended)
        self.undo_button.setObjectName('button:undo')
        self.details_card, detail_form = self._card('Settings for your PC')
        self.detail_rows = QVBoxLayout()
        detail_form.addRow(self.detail_rows)
        self.apply_button = self._button(detail_form, 'Apply the settings for my PC', self.apply_recommended)
        self._control(detail_form, 'auto_graphics', 'Adjust them automatically when the hardware changes', checkbox=True)
        self.details_card.hide()
        _, screen = self._card('Screen')
        self._control(screen, 'fullscreen', 'Fullscreen', checkbox=True)
        screen.addRow(_label('Recommended: the game gets the display to itself (smoother, and 4K downsampling works).'))
        self._control(screen, 'exclusive_fullscreen', 'Exclusive fullscreen', checkbox=True)
        screen.addRow(_label('Fullscreen takes the display over instead of covering the desktop: frames can arrive more evenly, '
            'but switching to another window takes a moment. Only with Fullscreen on.'))
        self.monitor = self._control(screen, 'game_monitor', 'Monitor', options=backend.monitor_options(settings.get('game_monitor', '')))
        self.monitor.currentIndexChanged.connect(self._monitor_changed)
        screen.addRow(_label('Where the game opens, in a window and in fullscreen.' if display.WINDOW_PLACEMENT_SUPPORTED else
            'Used for output resolution. Your compositor controls which monitor the game opens on.'))
        self.output = self._control(screen, 'output_res', 'Resolution', 'ini', options=backend.OUTPUTS)
        self.output.setEditable(True)
        self.output.lineEdit().setPlaceholderText('2560x1440')
        self.output.lineEdit().editingFinished.connect(self._custom_resolution)
        self.match = self._control(screen, 'output_display', 'Same as the monitor', checkbox=True)
        self.match.toggled.connect(self._monitor_changed)
        self.output.activated.connect(lambda _index: self.match.setChecked(False))
        self.resolution_note = _label('')
        screen.addRow(self.resolution_note)
        screen.addRow(_label('The size of the picture. Your goal picks it for this PC; change it here if you like.'))
        if display.WINDOW_PLACEMENT_SUPPORTED:
            self.window_mode = self._control(screen, 'window_size', 'Window size', options=setup.SetupMixin.WINDOW_SIZES)
            self.window_custom = self._control(screen, 'window_custom', 'Custom size…')
        else:
            label = _label('Your compositor manages the game window size and placement.')
            label.setObjectName('window_size')
            screen.addRow(backend._('Window size'), label)
        self._control(screen, 'hdr', 'Allow HDR output', checkbox=True)
        screen.addRow(_label('When HDR is on in Windows and the display supports it.' if backend.WINDOWS else
            'When HDR is enabled in your desktop session and the display supports it.'))
        _, taste = self._card('Taste')
        flags = {key: title for key, title, _on in backend.EFFECTS}
        for key in backend.TASTE_EFFECTS:
            self._control(taste, key, backend._(*flags[key]), 'ini', checkbox=True)
        self._control(taste, 'show_fps', 'Show the FPS counter', 'ini', checkbox=True)
        self._button(taste, 'Every graphics setting one by one:', lambda: self.page_requested.emit('graphics'))
        self.refresh()

    def _value(self, widget, store):
        if widget is getattr(self, 'output', None) and widget.isEditable():
            size = display.parse_size(widget.currentText())
            return display.size_text(size) if size else widget.currentData()
        return super()._value(widget, store)

    def _custom_resolution(self):
        value = self.output.currentData() if self.output.currentText() == self.output.itemText(self.output.currentIndex()) else self.output.currentText()
        size = display.parse_size(value)
        if not size:
            self.resolution_note.setText(backend._('Enter a size such as 2560x1440.'))
            return
        value = display.size_text(size)
        index = self.output.findData(value)
        if index < 0:
            self.output.addItem(value.replace('x', ' × '), value)
            index = self.output.count() - 1
        self.output.setCurrentIndex(index)
        self.match.setChecked(False)
        self._changed()

    def _monitor_changed(self, *_args):
        if self._refreshing:
            return
        if self.match.isChecked():
            size = display.size_text(_Profile(self).display_size())
            self._app_pending.update(self.app_values())
            self._ini_pending.update(self.ini_values())
            self._ini_pending['output_res'] = size
            self._fill()
        self._changed()

    def toggle_details(self):
        show = self.details_card.isHidden()
        self.details_card.setVisible(show)
        self.details_button.setText(backend._('Hide the settings' if show else 'Show the settings one by one'))

    def _draw(self):
        super()._draw()
        values = {**self.settings, **self.app_values()}
        graphics = {**self.graphics, **self.ini_values()}
        profile = _Profile(self)
        chosen = profile.recommended()
        differences = profile.differences() if chosen else []
        self.state.setText(backend._('as recommended') if chosen and not differences else
            backend._('{} differ from the recommendation').format(len(differences)) if differences else backend._('checking your PC…'))
        upscaler = backend._(*dict(backend.UPSCALERS).get(graphics.get('upscaler'), ('?',))).split(' (')[0]
        preset = backend._(*dict(backend.PRESETS).get(graphics.get('preset'), ('',))).split(' (')[0]
        fps = backend._(*dict(backend.FPS_MODES).get(values.get('fps_mode'), ('?',))).split(' (')[0]
        effects = sum(graphics.get(key) == '1' for key in ('effect_ssao', 'effect_dynamic_shadows', 'object_motion'))
        self.summary.setText('  ·  '.join([str(graphics.get('output_res', '')).replace('x', ' × '),
            upscaler + ('' if graphics.get('upscaler') in ('off', 'taa') else ' ' + preset), fps,
            backend._('every effect' if effects == 3 else 'fewer effects' if effects else 'no costly effects')]))
        rating = profile.rating
        self.pc.setText(backend._('Your PC: {} · {}').format(rating.tier_label, rating.cpu.label if rating.limit == 'cpu' else rating.gpu.label)
            + ('  ·  ' + backend._(hardware.LIMITS['cpu']) if rating.limit == 'cpu' else '') if rating else '')
        self.undo_button.setVisible(bool(values.get('auto_undo')))
        self.undo_button.setEnabled(not self.running)
        self.apply_button.setEnabled(bool(differences) and not self.running)
        while self.detail_rows.count():
            self.detail_rows.takeAt(0).widget().deleteLater()
        if chosen:
            names = profile.setting_names()
            now = profile.current_settings()
            for _store, key, value, why in chosen[2]:
                self.detail_rows.addWidget(_label(f'{names[key][0]}: {profile.show_value(key, now.get(key))}  ›  {profile.show_value(key, value)}\n{backend._(why)}'))
        else:
            self.detail_rows.addWidget(_label('Checking your PC…'))
        size = display.parse_size(graphics.get('output_res', ''))
        self.resolution_note.setText(backend._('Narrower than 16:9: the picture may look stretched.') if size and display.narrower_than_16_9(size) else '')

    def set_game_running(self, running):
        super().set_game_running(running)
        self._draw()

    def save(self):
        if not display.parse_size(self._value(self.output, 'ini')):
            raise ValueError(backend._('Enter a size such as 2560x1440.'))
        if self.output.currentText() != self.output.itemText(self.output.currentIndex()):
            if not display.parse_size(self.output.currentText()):
                raise ValueError(backend._('Enter a size such as 2560x1440.'))
            self._custom_resolution()
        super().save()

    def apply_automatic(self):
        profile = _Profile(self)
        before = dict(profile.app), dict(profile.graphics)
        profile.auto_settings()
        if (profile.app, profile.graphics) != before:
            self._take_profile(profile)
            self._draw()
            self.settings_changed.emit()


class _CheckStep(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self.guide = wizard
        self.complete = False

    def isComplete(self):
        return self.complete


class SetupWizard(QWizard):
    """Keep setup edits local until accepted; the owner persists them before starting the game."""
    device_requested = Signal(str)
    page_requested = Signal(str)
    shortcut_requested = Signal()
    steam_requested = Signal()

    def __init__(self, settings, graphics, parent=None):
        super().__init__(parent)
        self._settings_target, self._graphics_target = settings, graphics
        self.settings, self.graphics = dict(settings), dict(graphics)
        self.first = not settings.get('setup_done')
        self._picture_visited = False
        self._online_offered = False
        self._last_step = 0
        self.setWindowTitle(backend._('Your first hunt'))
        self.resize(1000, 800)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)

        def step(title):
            page = QWizardPage()
            page.setTitle(backend._(title))
            self.addPage(page)
            return QVBoxLayout(page)

        welcome = step('Welcome')
        welcome.addWidget(_label('A few steps to your first hunt: the guide checks your game and your PC, sets the picture for your hardware and brings your character along. Every setting can be changed in the launcher afterwards.'))
        welcome.addWidget(_label('Only with your own copy of the game'))
        welcome.addWidget(_label("The port does not come with the game, and we can't give out game files or help anyone find them. Asking for them or sharing them breaks rule 2 of the community Discord and can get you banned."))
        self.language = QComboBox()
        for value, title in backend.UI_LANGUAGES:
            self.language.addItem(backend._(*title), value)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.get('ui_language', 'auto'))))
        welcome.addWidget(_label('Launcher language'))
        welcome.addWidget(self.language)
        welcome.addWidget(_label('Applies when the launcher opens again.'))
        welcome.addWidget(_label('Where do you come from?'))
        self.origin = QComboBox()
        for value, title in setup.SetupGuide.ORIGINS:
            self.origin.addItem(backend._(title), value)
        welcome.addWidget(self.origin)
        welcome.addWidget(_label('Your own Bloodborne game files (CUSA03173, Game of the Year Edition) with the 1.09 update.'))
        welcome.addWidget(_label('Windows 10 or 11 (64-bit) and a graphics card with Vulkan 1.3 and at least 4 GB of video memory.' if backend.WINDOWS else 'Linux (64-bit) and a graphics card with Vulkan 1.3 and at least 4 GB of video memory.'))
        welcome.addStretch()

        self.check_step = _CheckStep(self)
        self.check_step.setTitle(backend._('Check the game'))
        self.addPage(self.check_step)
        check = QVBoxLayout(self.check_step)
        check.addWidget(_label('Your game folder: the one with eboot.bin, sce_module, sce_sys and dvdroot_ps4 directly inside.'))
        folder = QHBoxLayout()
        self.game_dir = QLineEdit(settings.get('game_dir', ''))
        self.game_dir.setObjectName('game_dir')
        folder.addWidget(self.game_dir, 1)
        browse = QPushButton(backend._('Browse…'))
        browse.clicked.connect(self._browse_game)
        folder.addWidget(browse)
        check.addLayout(folder)
        self.game_note = _label('')
        check.addWidget(self.game_note)
        self.help = HelpPage(self.settings)
        self.system = SystemPage(self.settings)
        checks = QTabWidget()
        checks.addTab(self.help, backend._('Your game'))
        checks.addTab(self.system, backend._('Your PC'))
        check.addWidget(checks, 1)
        self.game_dir.textChanged.connect(self._game_changed)
        self.help.checks_finished.connect(self._checks_finished)
        self.game_timer = QTimer(self)
        self.game_timer.setSingleShot(True)
        self.game_timer.setInterval(250)
        self.game_timer.timeout.connect(self._check_game)

        picture = step('Picture & controls')
        self.picture = PicturePage(self.settings, self.graphics)
        self.picture.system_page = self.system
        picture.addWidget(self.picture, 1)
        options = QFormLayout()
        self.resolution = QComboBox()
        options.addRow(backend._('Settings for this resolution'), self.resolution)
        self.frame_gen = QCheckBox(backend._('Frame generation: higher frame rates, a little more input latency'))
        options.addRow(self.frame_gen)
        self.download = QCheckBox(backend._('Download the FSR 4 files now (about 30 MB)'))
        options.addRow(self.download)
        self.device = QComboBox()
        self.device.addItem(backend._('Controller'), 'controller')
        self.device.addItem(backend._('Keyboard and mouse'), 'keyboard')
        self.device.setCurrentIndex(max(0, self.device.findData(settings.get('play_with', 'controller'))))
        options.addRow(backend._('You play with'), self.device)
        picture.addLayout(options)

        carry = step('Saves & online')
        tabs = QTabWidget()
        self.saves = SavesPage(self.settings)
        self.online = OnlinePage(self.settings)
        tabs.addTab(self.saves, backend._('Your characters from other versions'))
        tabs.addTab(self.online, backend._('Online co-op'))
        carry.addWidget(tabs)

        ready = step('Ready to play')
        self.summary = _label('')
        ready.addWidget(self.summary)
        self.mode = QComboBox()
        self.mode.addItem(backend._('Simple (recommended): the pages you need, everything technical is set for you'), 'simple')
        self.mode.addItem(backend._('Expert: every page and every option'), 'expert')
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.get('ui_mode', 'simple'))))
        ready.addWidget(self.mode)
        self.play = QCheckBox(backend._('Play after setup'))
        self.play.setChecked(True)
        ready.addWidget(self.play)
        for title, signal in (('Desktop shortcut', self.shortcut_requested), ('Add to Steam', self.steam_requested)):
            button = QPushButton(backend._(title))
            button.clicked.connect(lambda _checked=False, signal=signal: signal.emit())
            ready.addWidget(button)
        ready.addWidget(_label('The first start takes longer and the first minutes can stutter while the shader cache is built. That is normal.'))
        ready.addWidget(_label('In the game, Insert (keyboard) or L3 + R3 (controller) opens the port\'s menu.'))
        ready.addStretch()
        self.system.rating_changed.connect(self.picture._draw)
        self.currentIdChanged.connect(self._enter)
        self.finished.connect(lambda _result: self.online.shutdown())
        self._game_changed()

    def _browse_game(self):
        chosen = QFileDialog.getExistingDirectory(self, backend._('Choose the folder with eboot.bin'),
            self.game_dir.text() or str(backend.PORT_DIR))
        if chosen:
            found = setup.find_game(chosen)
            self.game_dir.setText(found if found and Path(found).parent == Path(chosen) else chosen)

    def _game_changed(self, *_args):
        self.check_step.complete = False
        self.check_step.completeChanged.emit()
        self.game_timer.start()

    def _check_game(self):
        self.settings['game_dir'] = self.game_dir.text().strip()
        rows, ok = setup.game_checks(self.settings['game_dir'])
        self.game_note.setText('\n'.join(backend._(text) for _state, text in rows))
        self.check_step.complete = False
        self.check_step.completeChanged.emit()
        if ok:
            self.help.refresh(self.settings)
            self.help.check_installation()

    def _checks_finished(self, results):
        if self.game_timer.isActive() or self.settings.get('game_dir') != self.game_dir.text().strip():
            return
        blocking = {'eboot_truncated', 'eboot_unreadable', 'update_only', 'empty_files', 'eboot_modified'}
        self.check_step.complete = setup.game_checks(self.game_dir.text().strip())[1] and not any(
            state == 'bad' and topic in blocking for state, topic, _text in results)
        self.check_step.completeChanged.emit()

    def validateCurrentPage(self):
        try:
            return self._validate_current()
        except ValueError as error:
            QMessageBox.warning(self, backend._('Picture & performance'), str(error))
            return False

    def _validate_current(self):
        if self.currentId() == 0:
            self.settings['ui_language'] = self.language.currentData()
        elif self.currentId() == 1:
            self.help.save()
            self.system.save()
        elif self.currentId() == 2:
            if self.system.rating:
                self.picture.apply_recommended(self.resolution.currentData())
                if self.frame_gen.isChecked() and self.system.rating.frame_gen:
                    self.picture._ini_pending['frame_gen'] = self.system.rating.frame_gen
            self.picture.save()
            self.settings['play_with'] = self.device.currentData()
        elif self.currentId() == 3:
            self.saves.save()
            self.online.save()
        return True

    def _enter(self, index):
        if self._last_step == 2:
            try:
                self.picture.save()
            except ValueError:
                pass  # Back remains available while an unfinished custom size is being edited.
            self.settings['play_with'] = self.device.currentData()
        elif self._last_step == 3:
            self.saves.save()
            self.online.save()
        self._last_step = index
        if index == 1:
            if not backend.game_info(self.game_dir.text()):
                found = setup.find_game()
                if found:
                    self.game_dir.setText(found)
            self._check_game()
        elif index == 2:
            if self.first and not self._picture_visited:
                self.settings['fullscreen'] = True
            self._picture_visited = True
            self.picture.refresh(self.settings, self.graphics)
            self.resolution.clear()
            profile = _Profile(self.picture)
            chosen = profile.recommended()
            if chosen:
                for key, output in hardware.outputs(*profile.display_size()).items():
                    self.resolution.addItem(key + '  -  ' + output.replace('x', ' × '), key)
                self.resolution.setCurrentIndex(self.resolution.findData(chosen[0]))
            rating = self.system.rating
            self.frame_gen.setVisible(bool(rating and rating.frame_gen))
            self.download.setVisible(bool(rating and hardware.upscaler_name(rating.gpu) == 'FSR 4' and backend.fsr4_missing()))
        elif index == 3:
            if self.first and not self._online_offered:
                self.settings['online'] = True
                self._online_offered = True
            self.online.refresh(self.settings)
        elif index == 4:
            self.summary.setText('\n\n'.join((self.settings.get('game_dir', ''), self.picture.summary.text(),
                self.online.account.text(), self.picture.expected.text() if hasattr(self.picture, 'expected') else self.picture.pc.text())))

    def save(self):
        self.settings.update(setup_done=True, seen_version=backend.VERSION, ui_mode=self.mode.currentData())
        if self.system.rating and not self.settings.get('auto_hw'):
            self.settings['auto_hw'] = hardware.signature(self.system.gpu_line, self.system.cpu, self.system.ram,
                _Profile(self.picture).display_size())
        self._settings_target.update(self.settings)
        self._graphics_target.update(self.graphics)

    def accept(self):
        self.save()
        super().accept()

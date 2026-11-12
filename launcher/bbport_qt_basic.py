# SPDX-License-Identifier: GPL-2.0-or-later
"""Game files, gameplay, cheats and launcher preferences using the shared settings."""
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget)

import bbport_launcher_win as backend
from bbport_qt_catalog import FIELDS
from bbport_qt_content import open_path

_ = backend._


class _Hint(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setObjectName('pageDescription')
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = self.font()
        font.setPointSize(9)
        self.setFont(font)

    def resizeEvent(self, event):
        # QFormLayout measures capped hints using its wider column instead of their actual width.
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())))
        super().resizeEvent(event)

    def setText(self, text):
        super().setText(text)
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())))


def note(layout, text):
    label = _Hint(text)
    layout.addWidget(label)
    return label


class BasicPage(QWidget):
    settings_changed = Signal()
    action_requested = Signal(str)

    def __init__(self, settings, graphics, page_id, parent=None):
        super().__init__(parent)
        if page_id not in ('game', 'gameplay', 'cheats', 'language', 'advanced'):
            raise ValueError('Unknown basic settings page: ' + page_id)
        self.settings, self.graphics, self.page_id = settings, graphics, page_id
        self.app_widgets, self.ini_widgets, self.actions = {}, {}, {}
        self.initial_app, self.initial_ini = {}, {}
        self.running = self._refreshing = False
        self.metadata = {field['key']: field for field in FIELDS[page_id]}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('settingsPage')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(32, 0, 32, 28)
        self.body.setSpacing(0)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.version_warning = note(self.body, '')
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(6)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(self.form)
        getattr(self, '_build_' + page_id)()
        self.body.addStretch()
        self.refresh()

    def card(self, title):
        heading = QWidget()
        heading.setObjectName('basicSection')
        row = QHBoxLayout(heading)
        row.setContentsMargins(0, 10 if not self.form.rowCount() else 24, 0, 6)
        row.setSpacing(14)
        label = QLabel(_(title))
        label.setObjectName('sectionTitle')
        row.addWidget(label)
        line = QFrame()
        line.setObjectName('sectionHairline')
        line.setFixedHeight(1)
        line.setStyleSheet('background: ' + backend.theme.BORDER + ';')
        row.addWidget(line, 1)
        self.form.addRow(heading)
        return self.form

    def _metadata(self, key, title='', hint=''):
        field = self.metadata.get(key, {})
        return _(title or field.get('title', key)), _(hint or field.get('hint', ''))

    def _row(self, form, key, widget, title='', hint=''):
        title, hint = self._metadata(key, title, hint)
        widget.setObjectName(key)
        widget.setToolTip(hint)
        if isinstance(widget, (QComboBox, QLineEdit)):
            widget.setFixedWidth(250 if key in ('ui_language', 'on_play') else
                                 300 if key == 'player_name' else 580 if key == 'extra_env' else 390)
        widget.ensurePolished()
        widget.setMinimumHeight(widget.sizeHint().height())
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        row.addWidget(widget)
        widget.inline_row = row
        layout.addLayout(row)
        if hint:
            label = note(layout, hint)
            label.setMaximumWidth(560)
        label = QLabel(title)
        label.setContentsMargins(0, 6, 0, 0)
        form.addRow(label, holder)

    def choice(self, form, key, options):
        widget = QComboBox()
        for value, text in options:
            widget.addItem(_(*text), value)
        self.app_widgets[key] = widget
        self._row(form, key, widget)
        widget.currentIndexChanged.connect(lambda _index: self._edited(key))
        return widget

    def check(self, form, key, store='app', title='', hint=''):
        title, hint = self._metadata(key, title, hint)
        widget = QCheckBox(title)
        widget.setObjectName(key)
        widget.setToolTip(hint)
        (self.ini_widgets if store == 'ini' else self.app_widgets)[key] = widget
        form.addRow(widget)
        if hint:
            self._note(form, hint).setContentsMargins(26, 0, 0, 0)
        widget.toggled.connect(lambda _checked: self._edited(key))
        return widget

    def text(self, form, key):
        widget = QLineEdit()
        self.app_widgets[key] = widget
        self._row(form, key, widget)
        widget.textChanged.connect(lambda _text: self._edited(key))
        return widget

    @staticmethod
    def _note(form, text, field=False):
        label = _Hint(_(text))
        label.setMaximumWidth(680)
        form.addRow('', label) if field else form.addRow(label)
        return label

    def action(self, form, key, title='', hint='', enabled=True, row=None):
        title, hint = self._metadata('button:' + key, title, hint)
        widget = QPushButton(title)
        widget.setObjectName('button:' + key)
        widget.setToolTip(hint)
        widget.setEnabled(enabled)
        widget.clicked.connect(lambda _checked=False: self.action_requested.emit(key))
        self.actions[key] = widget
        if row is not None:
            row.addWidget(widget)
        else:
            holder = QWidget()
            layout = QHBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(widget)
            layout.addStretch()
            form.addRow(holder)
        if hint and row is None:
            self._note(form, hint)
        return widget

    def folder(self, form, key, dialog_title):
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        field = QLineEdit()
        field.setObjectName(key)
        field.setFixedWidth(390)
        self.app_widgets[key] = field
        field.textChanged.connect(lambda _text: self._edited(key))
        row.addWidget(field, 1)
        browse = QPushButton(_('Browse…'))
        browse.setObjectName('button:browse_' + key)
        row.addWidget(browse)
        opened = QPushButton(_('Open'))
        opened.setObjectName('button:open_' + key)
        opened.clicked.connect(lambda: self._open_folder(field.text()))
        row.addWidget(opened)
        row.addStretch()

        def choose():
            selected = QFileDialog.getExistingDirectory(self, _(dialog_title), field.text() or str(backend.DATA_DIR))
            if selected:
                field.setText(selected)
        browse.clicked.connect(choose)
        self._row(form, key, holder)
        # The searchable setting is the editable path, not its layout container.
        holder.setObjectName(key + '_row')
        field.setToolTip(holder.toolTip())
        return field

    def _open_folder(self, value):
        try:
            folder = Path(value or backend.DATA_DIR)
            folder.mkdir(parents=True, exist_ok=True)
            open_path(folder)
        except OSError as error:
            QMessageBox.critical(self, 'Bloodborne', str(error))

    def _build_game(self):
        form = self.card('Game')
        self.folder(form, 'game_dir', 'Choose the folder with eboot.bin')
        self.folder(form, 'dlc_dir', 'Choose the DLC folder')
        self.dlc_note = self._note(form, '', field=True)
        for key, text, title in [('help', 'Is the game folder all right? Help checks it.', 'Open'),
                                 ('setup', 'Set everything up again, step by step.', 'Repeat the setup')]:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            label = QLabel(_(text))
            label.setObjectName('pageDescription')
            row.addWidget(label)
            link = self.action(form, key, _(title) + '  ›', row=row)
            link.setStyleSheet('color: ' + backend.theme.GOLD + '; background: transparent; border: none; padding: 0;')
            row.addStretch()
            form.addRow(holder)
        notice = QFrame()
        notice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        notice.setObjectName('ownershipNotice')
        notice.setStyleSheet('QFrame#ownershipNotice { border: 1px solid ' + backend.theme.BLOOD + '; border-left: 4px solid ' + backend.theme.BLOOD + '; }')
        warning = QHBoxLayout(notice)
        warning.setContentsMargins(12, 10, 14, 10)
        icon = QLabel('⚠')
        icon.setStyleSheet('color: ' + backend.theme.BLOOD_LIGHT + '; font-size: 18px;')
        warning.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        contents = QWidget()
        words = QVBoxLayout(contents)
        words.setContentsMargins(0, 0, 0, 0)
        warning.addWidget(contents, 1)
        title = QLabel(_('Only with your own copy of the game'))
        title.setStyleSheet('color: ' + backend.theme.BLOOD_LIGHT + '; font-weight: 600;')
        words.addWidget(title)
        note(words, _("The port does not come with the game, and we can't give out game files or help anyone find them. Asking for them or sharing them breaks rule 2 of the community Discord and can get you banned."))
        form.addRow(notice)

    def _build_gameplay(self):
        language = self.card('Language')
        self.choice(language, 'language', backend.LANGUAGES)
        self.choice(language, 'voice_language', backend.VOICE_LANGUAGES)
        self.text(language, 'player_name')
        sound = self.card('Starting the game and sound')
        for key in ('skip_intro', 'mute_unfocused'):
            self.check(sound, key, 'ini')
        tweaks = self.card('Gameplay tweaks')
        self._note(tweaks, 'Game patches for version 1.09, applied at start.')
        for key, title, _on in backend.TWEAKS:
            self.check(tweaks, key, 'ini', _(*title))

    def _build_cheats(self):
        cheats = self.card('Cheats')
        for key, title, _on in backend.CHEATS:
            self.check(cheats, key, 'ini', _(*title))
        debug = self.card('Debug')
        for key, title, _on in backend.EXTRAS:
            if key != 'skip_intro':
                self.check(debug, key, 'ini', _(*title))
        respec = self.card('Respec')
        self.action(respec, 'respec', 'Respec a character…')
        self._note(respec, "Spread a character's attribute points again: same level, same Blood Echoes. Changes the save while the game is closed; a copy of the saves is kept in respec-backups beside them.")

    def _build_language(self):
        launcher = self.card('Launcher')
        self.choice(launcher, 'ui_language', backend.UI_LANGUAGES)
        self.action(launcher, 'relaunch', 'Apply (restarts the launcher)', row=self.app_widgets['ui_language'].inline_row)
        self.check(launcher, 'translucent_window')
        play = self.card('While you play')
        self.choice(play, 'on_play', backend.ON_PLAY)
        self.check(play, 'reopen_after_game')
        if backend.bbport_tray.AVAILABLE:
            self.check(play, 'minimize_to_tray', title='Minimize to the system tray',
                hint='Minimized, the launcher leaves the task bar for an icon next to the clock: click it to open the launcher again.')
        shortcuts = self.card('Shortcuts')
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        self.action(shortcuts, 'shortcut', row=row)
        self.action(shortcuts, 'steam', row=row)
        row.addStretch()
        shortcuts.addRow(holder)
        self._note(shortcuts, 'The desktop shortcut opens this launcher; the Steam entry starts the game straight away with these settings.')

    def _build_advanced(self):
        launcher = self.card('Launcher')
        if backend.WINDOWS:
            self.check(launcher, 'check_updates', title='Check for updates when the launcher opens')
        else:
            self._note(launcher, 'Linux builds are updated from the source checkout.')
        for entries in [[('port_folder', ''), ('language', _('Launcher language') + '  ›'),
                          ('ini', 'bbport.ini'), ('setup', 'Repeat the setup')],
                        [('updates', 'Check for updates'), ('versions', 'Other versions…')]]:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 4, 0, 0)
            for key, title in entries:
                self.action(launcher, key, title, enabled=backend.WINDOWS or key not in ('updates', 'versions'), row=row)
            if entries[0][0] == 'updates':
                version = QLabel('v' + backend.VERSION)
                version.setObjectName('pageDescription')
                row.addWidget(version)
            row.addStretch()
            launcher.addRow(holder)
        if backend.WINDOWS:
            self.check(self.card('Appearance'), 'windows_title_bar',
                title="Windows' title bar instead of the launcher's own",
                hint='Applies when the launcher opens again.')
        performance = self.card('Performance')
        for key, options in [('draw_pipe', backend.DRAW_PIPE), ('readbacks', backend.READBACKS),
                             ('low_vram', backend.LOW_VRAM)]:
            self.choice(performance, key, options)
        self.check(performance, 'vram_warning')
        self._note(performance, 'Low-VRAM profile by fixdag and bashiku.')
        diagnostics = self.card('Diagnostics')
        for key in ('frame_stats', 'mangohud', 'gpu_profile', 'vk_validation'):
            if key != 'mangohud' or not backend.WINDOWS:
                self.check(diagnostics, key)
        self.text(diagnostics, 'extra_env')
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 4, 0, 0)
        self.action(diagnostics, 'benchmark', enabled=backend.WINDOWS, row=row)
        description = QLabel(_(self.metadata['button:benchmark']['hint']))
        description.setObjectName('pageDescription')
        row.addWidget(description)
        row.addStretch()
        diagnostics.addRow(holder)

    @staticmethod
    def _value(widget, ini=False):
        if isinstance(widget, QCheckBox):
            value = widget.isChecked()
            return ('1' if value else '0') if ini else value
        return widget.currentData() if isinstance(widget, QComboBox) else widget.text()

    def app_values(self):
        return {key: self._value(widget) for key, widget in self.app_widgets.items()
                if self._value(widget) != self.initial_app.get(key)}

    def ini_values(self):
        return {key: self._value(widget, True) for key, widget in self.ini_widgets.items()
                if self._value(widget, True) != self.initial_ini.get(key)}

    def save(self):
        self.settings.update(self.app_values())
        self.graphics.update(self.ini_values())
        return True

    def _edited(self, key):
        if self._refreshing:
            return
        if key in ('cheat_enemy_control', 'debug_camera') and self.ini_widgets[key].isChecked():
            other = 'debug_camera' if key == 'cheat_enemy_control' else 'cheat_enemy_control'
            self.ini_widgets[other].setChecked(False)
        self._update_status()
        self.settings_changed.emit()

    def _update_status(self):
        if self.page_id == 'game':
            kind, text = backend.dlc_status(self.app_widgets['game_dir'].text(),
                self.app_widgets['dlc_dir'].text().strip(), self.settings.get('user_dir') or backend.DATA_DIR / 'user')
            self.dlc_note.setText({'ok': '✓', 'warn': '!', 'none': '–'}[kind] + '  ' + text)
        info = backend.game_info(self.settings.get('game_dir', ''))
        show = self.page_id in ('gameplay', 'cheats') and info and info[1] != backend.PATCH_VERSION
        self.version_warning.setVisible(bool(show))
        if show:
            self.version_warning.setText(_('Your game is version {}: these options are patches for 1.09 and are not applied; the game runs at 30 FPS. Update the game to 1.09 to use them.').format(info[1]))
        if self.page_id == 'language':
            self.actions['relaunch'].setVisible(self._value(self.app_widgets['ui_language']) != self.initial_app.get('ui_language'))

    def refresh(self, settings=None, graphics=None):
        if settings is not None:
            self.settings = settings
        if graphics is not None:
            self.graphics = graphics
        self._refreshing = True
        try:
            for ini, widgets, values, defaults in [(False, self.app_widgets, self.settings, backend.APP_DEFAULTS),
                                                  (True, self.ini_widgets, self.graphics, backend.INI_DEFAULTS)]:
                for key, widget in widgets.items():
                    value = values.get(key, defaults[key])
                    with QSignalBlocker(widget):
                        if isinstance(widget, QCheckBox):
                            widget.setChecked(value == '1' if ini else bool(value))
                        elif isinstance(widget, QComboBox):
                            index = widget.findData(value)
                            if index < 0:
                                widget.addItem(str(value), value)
                                index = widget.count() - 1
                            widget.setCurrentIndex(index)
                        else:
                            widget.setText(str(value))
            self.initial_app = {key: self._value(widget) for key, widget in self.app_widgets.items()}
            self.initial_ini = {key: self._value(widget, True) for key, widget in self.ini_widgets.items()}
            self._update_status()
        finally:
            self._refreshing = False
        self.set_game_running(self.running)

    def set_game_running(self, running):
        self.running = running
        for key in ('respec', 'setup', 'relaunch', 'updates', 'versions', 'benchmark'):
            if key in self.actions:
                self.actions[key].setEnabled(not running and (backend.WINDOWS or key not in ('updates', 'versions', 'benchmark')))

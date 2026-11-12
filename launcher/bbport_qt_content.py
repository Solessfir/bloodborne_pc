# SPDX-License-Identifier: GPL-2.0-or-later
"""Native mod and save management, using the existing launcher's file helpers."""
import json
import os
from pathlib import Path
import shutil
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget)

import bbport_launcher_win as backend
import bbport_benchmark as bench
import bbport_character as character
import bbport_respec as respec
import bbport_saves as saves
from mods import discover, unrecognized
from patches import external_patches

_ = backend._


def open_path(path):
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).absolute()))):
        raise OSError(_('Could not open {}').format(path))


def button(layout, title, action):
    widget = QPushButton(_(title))
    widget.clicked.connect(lambda _checked=False: action())
    layout.addWidget(widget)
    return widget


def note(layout, text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setObjectName('pageDescription')
    layout.addWidget(label)
    return label


class _ContentPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.fields, self.initial = {}, {}
        self.running = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('settingsPage')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(32, 24, 32, 28)
        self.body.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll)

    def card(self, title):
        heading = QHBoxLayout()
        label = QLabel(_(title))
        label.setObjectName('sectionHeading')
        heading.addWidget(label)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet('color: #25272b;')
        heading.addWidget(line, 1)
        self.body.addLayout(heading)
        card = QGroupBox()
        card.setProperty('flatSection', getattr(self, 'flat_sections', False))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 20, 16, 14)
        layout.setSpacing(8)
        self.body.addWidget(card)
        return layout

    def folder(self, layout, key, title):
        form = QFormLayout()
        row = QHBoxLayout()
        field = QLineEdit()
        field.setObjectName(key)
        field.setPlaceholderText(str(backend.DATA_DIR / {'user_dir': 'user', 'mods_dir': 'mods',
                                                         'patches_dir': 'patches'}.get(key, 'user')))
        self.fields[key] = field
        row.addWidget(field, 1)

        def browse():
            chosen = QFileDialog.getExistingDirectory(self, _(title), field.text() or str(backend.DATA_DIR))
            if chosen:
                field.setText(chosen)
                self._collect_settings()
                self.refresh()
        button(row, 'Browse…', browse)
        button(row, 'Open', lambda: self._try(lambda: open_path(self._folder_path(key))))
        field.editingFinished.connect(self._folder_edited)
        form.addRow(_(title), row)
        layout.addLayout(form)
        return field

    def _folder_path(self, key):
        self._collect_settings()
        if key == 'cache_dir':
            return backend.cache_folder(self.settings)
        return Path(self.settings.get(key) or backend.DATA_DIR / {
            'user_dir': 'user', 'mods_dir': 'mods', 'patches_dir': 'patches'}[key])

    def _folder_edited(self):
        self._collect_settings()
        self.refresh()

    def check(self, layout, key, title, default=False):
        widget = QCheckBox(_(title))
        widget.setObjectName(key)
        widget.setChecked(self.settings.get(key, default))
        self.fields[key] = widget
        layout.addWidget(widget)
        return widget

    def _collect_settings(self):
        for key, widget in self.fields.items():
            value = widget.isChecked() if isinstance(widget, QCheckBox) else widget.text()
            if key in self.initial and value != self.initial[key]:
                self.settings[key] = value
            self.initial[key] = value

    def _refresh_fields(self, settings):
        if settings is not None:
            self.settings = settings
        for key, widget in self.fields.items():
            value = self.settings.get(key, key == 'auto_backup')
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
                self.initial[key] = widget.isChecked()
            else:
                widget.setText(str(value or ''))
                self.initial[key] = widget.text()

    def set_game_running(self, running):
        self.running = running

    def _try(self, action):
        try:
            return action()
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, 'Bloodborne', str(error))
            return None

    def _ask(self, text):
        return QMessageBox.question(self, 'Bloodborne', text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


class ModsPage(_ContentPage):
    """Loose file mod ordering and shadPS4/GoldHEN patch selections."""
    flat_sections = True
    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        mods = self.card('Mods')
        self.check(mods, 'mods_enabled', 'Load mods')
        note(mods, _('The game files are never changed: mods are layered over them at start.'))
        self.folder(mods, 'mods_dir', 'Mods folder')
        self.mods = QListWidget()
        self.mods.setObjectName('modsList')
        self.mods.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.mods.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.mods.setMinimumHeight(150)
        self.mods.setMaximumHeight(300)
        mods.addWidget(self.mods)
        note(mods, _('Drag a mod by its grip to change the order. Lower in the list loads later and wins conflicts.'))
        move = QHBoxLayout()
        button(move, 'Move up', lambda: self.move_mod(-1))
        button(move, 'Move down', lambda: self.move_mod(1))
        move.addStretch()
        mods.addLayout(move)
        self.mod_problems = note(mods, '')
        patches = self.card('Third-party patches')
        self.folder(patches, 'patches_dir', 'Patches folder')
        note(patches, _('shadPS4/GoldHEN XML patch files for version 1.09.'))
        self.patches = QListWidget()
        self.patches.setObjectName('patchesList')
        self.patches.setMinimumHeight(140)
        patches.addWidget(self.patches)
        row = QHBoxLayout()
        button(row, 'Refresh', self.rescan)
        row.addStretch()
        self.body.addLayout(row)
        self.body.addStretch()
        self._mods_root = self._patches_root = None
        self.refresh(settings)

    @staticmethod
    def _choices(widget):
        return {widget.item(i).data(Qt.ItemDataRole.UserRole):
                widget.item(i).checkState() == Qt.CheckState.Checked for i in range(widget.count())}

    def move_mod(self, offset):
        row = self.mods.currentRow()
        if row < 0 or not 0 <= row + offset < self.mods.count():
            return
        item = self.mods.takeItem(row)
        self.mods.insertItem(row + offset, item)
        self.mods.setCurrentRow(row + offset)

    def rescan(self):
        self._collect_settings()
        self.refresh()

    def refresh(self, settings=None):
        self._refresh_fields(settings)
        root = self._folder_path('mods_dir')
        patch_root = self._folder_path('patches_dir')
        old_mods = self._choices(self.mods) if root == self._mods_root else {}
        old_order = list(old_mods)
        old_patches = self._choices(self.patches) if patch_root == self._patches_root else {}
        self._mods_root, self._patches_root = root, patch_root
        profile = backend.load_json(backend.DATA_DIR / 'mods.json', {})
        chosen = backend.load_json(backend.DATA_DIR / 'patches.json', {})
        available = discover(root)
        order = list(dict.fromkeys(n for n in [*old_order, *profile.get('order', []), *available] if n in available))
        self.mods.clear()
        for name in order:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setCheckState(Qt.CheckState.Checked if old_mods.get(name, name not in profile.get('disabled', []))
                               else Qt.CheckState.Unchecked)
            self.mods.addItem(item)
        problems = [_('Not loaded: {}: {}').format(name, problem) for name, problem in unrecognized(root)]
        if not available:
            problems.insert(0, _('No mods in {} yet.').format(root))
        self.mod_problems.setText('\n'.join(problems))
        self.patches.clear()
        for key, path, meta in external_patches(patch_root, backend.PATCH_VERSION):
            on = key in chosen.get('enabled', []) or (key not in chosen.get('disabled', []) and
                meta.get('isEnabled', 'false').lower() == 'true')
            item = QListWidgetItem(key + ('  -  ' + meta.get('Author') if meta.get('Author') else ''))
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(str(path))
            item.setCheckState(Qt.CheckState.Checked if old_patches.get(key, on) else Qt.CheckState.Unchecked)
            self.patches.addItem(item)
        if not self.patches.count():
            item = QListWidgetItem(_('No patch files for version 1.09 yet.'))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.patches.addItem(item)

    def save(self):
        self._collect_settings()
        mods = self._choices(self.mods)
        patches = {key: value for key, value in self._choices(self.patches).items() if key is not None}
        if mods or patches:
            backend.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if mods:
            (backend.DATA_DIR / 'mods.json').write_text(json.dumps(
                {'order': list(mods), 'disabled': [key for key, on in mods.items() if not on]}, indent=2), encoding='utf-8')
        if patches:
            chosen = backend.load_json(backend.DATA_DIR / 'patches.json', {})
            enabled = (set(chosen.get('enabled', [])) - patches.keys()) | {key for key, on in patches.items() if on}
            disabled = (set(chosen.get('disabled', [])) - patches.keys()) | {key for key, on in patches.items() if not on}
            (backend.DATA_DIR / 'patches.json').write_text(json.dumps(
                {'enabled': sorted(enabled), 'disabled': sorted(disabled)}, indent=2), encoding='utf-8')
        return True


class SavesPage(_ContentPage):
    search_finished = Signal(object, object, str)

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        self.characters_layout = self.card('Your characters')
        tools = QHBoxLayout()
        self.backup_button = QPushButton(_('Back up now'))
        self.backup_button.clicked.connect(self.backup_now)
        self.backup_button.setObjectName('button:backup')
        self.export_button = button(tools, 'Export…', self.export_saves)
        self.respec_button = button(tools, 'Respec', self.open_respec)
        self.refresh_button = button(tools, 'Refresh', self.rescan)
        button(tools, 'Open the folder', lambda: self._try(lambda: open_path(self.target_dir())))
        tools.addStretch()
        self.characters_layout.addLayout(tools)
        self.characters_body = QWidget()
        self.characters_body.setObjectName('characters')
        self.characters_layout.addWidget(self.characters_body)
        self.character_rows = QVBoxLayout(self.characters_body)
        self.character_rows.setContentsMargins(0, 0, 0, 0)
        backups = self.card('Backups')
        self.check(backups, 'auto_backup', 'Back up automatically before every start', True)
        note(backups, _('Only when you played since the last backup. The last {} automatic backups are kept; '
                        'the ones you make yourself always.').format(saves.AUTO_KEEP))
        self.check(backups, 'exit_backup', 'Back up after every game exit')
        note(backups, _('Copies the final save after a normal exit or crash. No periodic copies; exit backups are kept.'))
        self.backups = QListWidget()
        self.backups.setObjectName('backupsList')
        self.backups.setMinimumHeight(170)
        backups.addWidget(self.backups)
        self.backups_status = note(backups, '')
        row = QHBoxLayout()
        self.restore_button = button(row, 'Restore', self.restore_backup)
        self.restore_button.setObjectName('button:restore')
        button(row, 'Rename', self.rename_backup)
        button(row, 'Copy to…', self.copy_backup)
        button(row, 'Show in folder', self.show_backup)
        button(row, 'Delete', self.delete_backup)
        self.backup_actions = [row.itemAt(index).widget() for index in range(row.count())]
        backups.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.backup_button)
        button(row, 'Add a backup file…', self.add_backup_file).setObjectName('button:add_backup')
        button(row, 'Open the folder', lambda: self._try(lambda: open_path(saves.backup_dir(self.user_dir()))))
        row.addStretch()
        backups.addLayout(row)
        imports = self.card('From other versions')
        note(imports, _('Characters from shadPS4, Awaken\'s port, bbhost or a PS4 export: found on this PC and '
                        'copied into this port\'s saves folder. Your current saves are backed up first.'))
        self.sources = QListWidget()
        self.sources.setObjectName('saveSourcesList')
        self.sources.setMinimumHeight(150)
        imports.addWidget(self.sources)
        self.search_status = note(imports, '')
        row = QHBoxLayout()
        self.search_button = button(row, 'Search again', self.search)
        button(row, 'Choose a folder…', self.choose_save_folder)
        self.import_button = button(row, 'Import', self.import_save)
        self.import_button.setObjectName('button:import')
        row.addStretch()
        imports.addLayout(row)
        folders = self.card('Saves folder')
        self.folder(folders, 'user_dir', 'Saves folder')
        self.folder(folders, 'cache_dir', 'Cache folder')
        self.cache_note = note(folders, '')
        self.body.addStretch()
        self._searching = False
        self._source_revision = 0
        self.search_finished.connect(self._search_done)
        self.refresh(settings)
        QTimer.singleShot(0, self, self.search)

    def save(self):
        self._collect_settings()
        return True

    def user_dir(self):
        return self._folder_path('user_dir')

    def target_dir(self):
        return saves.target_dir(self.user_dir(), self.settings.get('game_dir', ''))

    def _guard(self):
        if self.running or bench.game_pids():
            QMessageBox.information(self, 'Bloodborne', _('Close the game first; it writes its saves while it runs.'))
            return False
        self._collect_settings()
        return True

    def set_game_running(self, running):
        super().set_game_running(running)
        for widget in (self.backup_button, self.export_button, self.respec_button, self.restore_button, self.import_button):
            widget.setEnabled(not running)

    @staticmethod
    def backup_title(item):
        title = item.label or _(saves.REASONS[item.reason])
        return title + (': ' + item.detail if item.detail and not item.label else '')

    @staticmethod
    def describe_save(save):
        text = _('{} characters').format(len(save.slots))
        return text + (': ' + ', '.join(save.names) if save.names else '')

    def refresh(self, settings=None):
        self._refresh_fields(settings)
        user, target = self.user_dir(), self.target_dir()
        items = [item for item in saves.backups(user) if item.ok]
        self._refresh_characters(target, items)
        selected = self._selected(self.backups)
        selected_path = selected.path if selected else None
        self.backups.clear()
        for backup in items:
            info = saves.backup_characters(backup)
            who = ', '.join(f'{c.name} ({_("Level")} {c.level})' for c in info.values()) or ', '.join(backup.names)
            size = f'{backup.size / 1024 / 1024:.1f} MB' if backup.size >= 1024 * 1024 else f'{max(1, round(backup.size / 1024))} KB'
            row = QListWidgetItem(self.backup_title(backup) + '\n' + backup.created.strftime('%d.%m.%Y %H:%M') +
                                  '  ·  ' + (who or _('no characters')) + '  ·  ' + size)
            row.setData(Qt.ItemDataRole.UserRole, backup)
            row.setToolTip(str(backup.path))
            self.backups.addItem(row)
            if backup.path == selected_path:
                self.backups.setCurrentItem(row)
        if self.backups.count() and self.backups.currentRow() < 0:
            self.backups.setCurrentRow(0)
        self.backups_status.setText('' if items else _('No backups yet.'))
        self.backups.setVisible(bool(items))
        for action in self.backup_actions:
            action.setVisible(bool(items))
        text = _('Caches now: {}').format(backend.cache_folder(self.settings))
        if backend.synced_folder(user):
            text += '\n' + _('Your saves folder is in a cloud folder: the saves go with you, the shaders stay on this '
                              'PC. Play on one PC at a time and let it finish syncing before you start on another one; '
                              'in OneDrive, set the folder to "Always keep on this device".')
        self.cache_note.setText(text)

    @staticmethod
    def _clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _character_text(self, info, words):
        attributes = '  ·  '.join(f'{words.attribute(key)} {value}' for key, value in info.attributes.items())
        weapons = '  ·  '.join(filter(None, map(words.weapon, info.weapons))) or '–'
        bosses = '  ·  '.join(filter(None, map(words.boss, info.bosses))) or _('None beaten yet')
        return '\n'.join([f'{words.word(character.LEVEL_TEXT)} {info.level}  ·  '
                          f'{words.word(character.PLAY_TIME_TEXT)} {info.played // 3600}:{info.played % 3600 // 60:02d}',
            attributes, _('Weapons') + ': ' + weapons,
            _('Bosses') + f' {len(info.bosses)}/{len(character.BOSSES)}: ' + bosses,
            f'{words.word(character.ECHOES_TEXT)} {info.echoes}  ·  '
            f'{words.word(character.INSIGHT_TEXT)} {info.insight}  ·  ' + _('Deaths') + f' {info.deaths}' +
            (f'  ·  NG+{info.journey}' if info.journey else '')])

    def _refresh_characters(self, target, backups):
        self._clear(self.character_rows)
        words = character.names(self.settings.get('game_dir', ''), self.settings.get('language', '1'))
        slots = [target / slot for slot in saves.SLOTS if saves.used(target / slot)]
        for action in (self.export_button, self.respec_button, self.refresh_button):
            action.setVisible(bool(slots))
        if not slots:
            note(self.character_rows, _('No characters yet. The game makes them, or bring yours from another version (below).'))
        for path in slots:
            info = character.read_file(path)
            box = QGroupBox((info.name if info else saves.character_name(path)) or _('A character without a readable name'))
            layout = QVBoxLayout(box)
            import datetime
            try:
                when = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime('%d.%m.%Y %H:%M')
            except OSError:
                when = '?'
            note(layout, _('Slot {}').format(int(path.name[-4:]) + 1) + '  ·  ' + _('saved {}').format(when))
            note(layout, self._character_text(info, words) if info else _('Its level, weapons and bosses cannot be read from this save.'))
            if info:
                history = [(item, then) for item in backups
                           for then in [saves.backup_characters(item).get(path.name)] if then and then.name == info.name]
                if history:
                    earlier = QGroupBox(_('Earlier states in your backups ({})').format(len(history)))
                    earlier.setCheckable(True)
                    earlier.setChecked(False)
                    content = QWidget()
                    states = QVBoxLayout(content)
                    states.setContentsMargins(0, 0, 0, 0)
                    for item, then in history:
                        row = QHBoxLayout()
                        title = self.backup_title(item) + '  ·  ' + item.created.strftime('%d.%m.%Y %H:%M')
                        if then.summary() == info.summary():
                            title += '  ·  ' + _('same as now')
                        row.addWidget(QLabel(title), 1)
                        button(row, 'Restore', lambda i=item, slot=path.name, c=then: self.restore_character(i, slot, c))
                        states.addLayout(row)
                        note(states, self._character_text(then, words))
                    folding = QVBoxLayout(earlier)
                    folding.addWidget(content)
                    content.hide()
                    earlier.toggled.connect(content.setVisible)
                    layout.addWidget(earlier)
            self.character_rows.addWidget(box)

    def rescan(self):
        self._collect_settings()
        self._try(self.refresh)
        self.search()

    @staticmethod
    def _selected(widget):
        item = widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def search(self):
        if self._searching:
            return
        self._collect_settings()
        context = (str(self.user_dir()), self.settings.get('game_dir', ''), self._source_revision)
        self._searching = True
        self.search_button.setEnabled(False)
        self.search_status.setText(_('Searching this PC for saves of shadPS4, Awaken\'s port and bbhost…'))
        port, target = backend.PORT_DIR, self.target_dir()
        signal = self.search_finished

        def work():
            found, error = [], ''
            try:
                found = saves.scan(port, context[1], exclude=[target])
            except Exception as failure:
                error = str(failure)
            try:
                signal.emit(context, found, error)
            except RuntimeError:
                pass  # The window may close during the disk scan.
        threading.Thread(target=work, daemon=True).start()

    def _search_done(self, context, found, error):
        self._searching = False
        self.search_button.setEnabled(True)
        if context[2] != self._source_revision:
            return
        if context[:2] != (str(self.user_dir()), self.settings.get('game_dir', '')):
            self.search()
            return
        self._show_sources(found)
        if error:
            self.search_status.setText(_('Could not search for saves: {}').format(error))

    def _show_sources(self, found):
        self.sources.clear()
        self.sources.setVisible(bool(found))
        self.import_button.setVisible(bool(found))
        for save in found:
            row = QListWidgetItem(save.source + '\n' + self.describe_save(save) + '  ·  ' + save.when() + '\n' + str(save.folder))
            row.setData(Qt.ItemDataRole.UserRole, save)
            self.sources.addItem(row)
        if found:
            self.sources.setCurrentRow(0)
        self.search_status.setText('' if found else _('No saves from shadPS4, Awaken\'s port or bbhost found on this PC. '
                                                     'If yours are somewhere else (a backup, a PS4 export), choose their folder.'))

    def choose_save_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, _('Choose the folder with the saves'), str(Path.home()))
        if not chosen:
            return

        def choose():
            folders, encrypted = saves.find_in(chosen)
            found = [saves.SaveSet(saves.label_for(folder), folder) for folder in folders]
            complete = sorted((save for save in found if save.complete), key=lambda save: -save.modified)
            if not complete:
                if encrypted and not found:
                    raise OSError(_('These are a PS4\'s own encrypted backups (sdimg_…); they cannot be used. '
                                    'Export the save with Apollo Save Tool on the PS4 instead.'))
                raise OSError(_('No complete Bloodborne save in {} or its subfolders: it needs userdata0010 and '
                                'at least one character (userdata0000 to userdata0009).').format(chosen))
            self._source_revision += 1
            self._show_sources(complete)
        self._try(choose)

    def import_save(self, save=None):
        if not self._guard():
            return
        save = save or self._selected(self.sources)
        if save is None:
            return
        question = _('Import the saves from {} ({}, last played {})?').format(save.source, self.describe_save(save), save.when())
        question += '\n\n' + _('They replace this port\'s saves. Your current saves are backed up first, so nothing is lost.')
        if self._ask(question) and self._guard():
            def apply():
                archive = saves.import_set(save, self.user_dir(), self.settings.get('game_dir', ''))
                self.refresh()
                message = _('Saves imported. Your characters are in the game\'s Load Game menu.')
                if archive:
                    message += '\n\n' + _('Your previous saves: {}').format(archive)
                QMessageBox.information(self, 'Bloodborne', message)
            self._try(apply)

    def backup_now(self):
        if not self._guard():
            return
        def apply():
            made = saves.backup(self.user_dir(), self.settings.get('game_dir', ''), reason='manual')
            self.refresh()
            if not made:
                QMessageBox.information(self, 'Bloodborne', _('There is no save to back up yet.'))
                return
            item = next(item for item in saves.backups(self.user_dir()) if item.path == made)
            self.rename_backup(item)
        self._try(apply)

    def export_saves(self):
        if not self._guard():
            return
        target, _filter = QFileDialog.getSaveFileName(self, _('Copy the backup to…'),
            str(Path.home() / 'Bloodborne-saves.zip'), _('Backups') + ' (*.zip)')
        if target and self._guard():
            def apply():
                made = saves.backup(self.user_dir(), self.settings.get('game_dir', ''), reason='manual')
                if not made:
                    QMessageBox.information(self, 'Bloodborne', _('There is no save to back up yet.'))
                    return
                shutil.copy2(made, target)
                self.refresh()
            self._try(apply)

    def restore_backup(self, item=None):
        if not self._guard():
            return
        item = item or self._selected(self.backups)
        if item is None:
            return
        question = _('Put this backup back?') + '\n\n' + self.backup_title(item) + '\n' + item.created.strftime('%d.%m.%Y %H:%M')
        question += '\n\n' + _('Every character in this backup goes back to this state.')
        question += '\n' + _('Your current saves are backed up first, so nothing is lost.')
        if self._ask(question) and self._guard():
            self._try(lambda: (saves.restore(item.path, self.user_dir(), self.settings.get('game_dir', '')), self.refresh()))

    def restore_character(self, item, slot, then):
        if not self._guard():
            return
        question = _('Put {} back to this state?').format(then.name) + '\n\n' + self.backup_title(item) + '\n'
        question += item.created.strftime('%d.%m.%Y %H:%M') + f'  ·  {_("Level")} {then.level}'
        question += '\n\n' + _('Only this character changes; your other characters stay as they are. Its current '
                               'state is backed up first, so nothing is lost.')
        if self._ask(question) and self._guard():
            self._try(lambda: (saves.restore_character(item.path, slot, self.user_dir(), self.settings.get('game_dir', '')),
                               self.refresh()))

    def rename_backup(self, item=None):
        item = item or self._selected(self.backups)
        if item is None:
            return
        name, ok = QInputDialog.getText(self, _('Rename'), _('A name for this backup.'), text=item.label or self.backup_title(item))
        if ok:
            self._try(lambda: (saves.rename_backup(item.path, name.strip()), self.refresh()))

    def add_backup_file(self):
        path, _filter = QFileDialog.getOpenFileName(self, _('Choose a backup (zip)'), str(Path.home()), _('Backups') + ' (*.zip)')
        if not path:
            return
        try:
            saves.add_backup_file(path, self.user_dir())
        except OSError as error:
            QMessageBox.critical(self, 'Bloodborne', _('This file is no Bloodborne save backup: {}').format(error))
            return
        self._try(self.refresh)

    def copy_backup(self, item=None):
        item = item or self._selected(self.backups)
        if item is None:
            return
        target, _filter = QFileDialog.getSaveFileName(self, _('Copy the backup to…'), str(Path.home() / item.path.name),
                                                     _('Backups') + ' (*.zip)')
        if target:
            self._try(lambda: shutil.copy2(item.path, target))

    def show_backup(self, item=None):
        item = item or self._selected(self.backups)
        if item:
            self._try(lambda: open_path(item.path.parent))

    def delete_backup(self, item=None):
        item = item or self._selected(self.backups)
        if item is None:
            return
        question = _('Delete this backup? It goes to the Recycle Bin.' if os.name == 'nt'
                     else 'Delete this backup? It goes to the Trash.')
        if self._ask(question + '\n\n' + self.backup_title(item) + '  ·  ' + item.created.strftime('%d.%m.%Y %H:%M')):
            def apply():
                if not saves.to_recycle_bin(item.path):
                    raise OSError(_('Could not move the backup to the Trash. The backup was kept.'))
                self.refresh()
            self._try(apply)

    def open_respec(self):
        if not self._guard():
            return
        def show():
            found = [(folder, slot, who) for folder in respec.save_folders(self.user_dir())
                     for slot, who in respec.characters(folder)]
            if not found:
                QMessageBox.information(self, _('Respec'), _('No characters found in {}.').format(self.user_dir()))
                return
            dialog = QDialog(self)
            dialog.setWindowTitle(_('Respec'))
            form = QFormLayout(dialog)
            chosen = QComboBox()
            for _folder, slot, who in found:
                chosen.addItem(_('Slot {}: {} (level {})').format(slot + 1, who['name'], who['level']))
            form.addRow(chosen)
            words = character.names(self.settings.get('game_dir', ''), self.settings.get('language', '1'))
            values = {}
            for attr in respec.ATTRIBUTES:
                spin = QSpinBox()
                spin.setRange(respec.FLOORS[attr], respec.MAX)
                values[attr] = spin
                form.addRow(words.attribute(attr), spin)
            remaining = QLabel()
            form.addRow(remaining)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Reset |
                                       QDialogButtonBox.StandardButton.Cancel)
            form.addRow(buttons)
            def points():
                left = sum(found[chosen.currentIndex()][2]['attributes'].values()) - sum(spin.value() for spin in values.values())
                remaining.setText(_('Points to place: {}').format(left))
                buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(left == 0)
            def load():
                for attr, spin in values.items():
                    spin.setValue(found[chosen.currentIndex()][2]['attributes'][attr])
                points()
            def apply():
                if not self._guard():
                    return
                def write():
                    folder, slot, _who = found[chosen.currentIndex()]
                    backup = respec.respec(folder, slot, {attr: spin.value() for attr, spin in values.items()})
                    QMessageBox.information(dialog, _('Respec'), _('Done. A copy of the saves from before is in {}.').format(backup.parent))
                    dialog.accept()
                    self.refresh()
                self._try(write)
            for spin in values.values():
                spin.valueChanged.connect(points)
            chosen.currentIndexChanged.connect(load)
            buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
            buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(load)
            buttons.rejected.connect(dialog.reject)
            load()
            dialog.exec()
        self._try(show)

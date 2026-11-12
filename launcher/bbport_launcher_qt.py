#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Qt launcher sharing the existing configuration and game services."""
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QTabWidget, QVBoxLayout, QWidget, QGraphicsOpacityEffect)

import bbport_launcher_win as backend
import bbport_theme_qt as theme
from bbport_qt_content import ModsPage, SavesPage
from bbport_qt_controls import ControlsPage
from bbport_qt_graphics import GraphicsPage
from bbport_qt_home import HomePage, PicturePage
from bbport_qt_services import OnlinePage, TrophiesPage, HelpPage, SystemPage
from bbport_qt_navigation import NavigationDelegate, ranked_settings
from bbport_qt_header import PageHeader


class GameProcess(QObject):
    output = Signal(str)
    finished = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = self.job = None
        self.finished.connect(self._finished)

    def start(self, settings, graphics):
        if self.process is not None:
            raise RuntimeError('The game is already running.')
        user = backend.saves_folder(settings)
        user.mkdir(parents=True, exist_ok=True)
        if settings.get('auto_backup', True):
            try:
                backend.saves.auto_backup(user, settings['game_dir'])
            except OSError as error:
                self.output.emit(backend._('The automatic backup of the saves failed: {}').format(error) + '\n')
        log = (user / 'last_run.log').open('w', encoding='utf-8', buffering=1)
        try:
            self.process = subprocess.Popen(backend.run_command(), cwd=backend.PORT_DIR,
                env=backend.game_environment(settings, graphics), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **backend.game_process_options())
        except OSError:
            log.close()
            raise
        self.job = backend.GameJob(self.process)
        threading.Thread(target=self._read, args=(self.process, log), daemon=True).start()

    def _read(self, process, log):
        code = 1
        try:
            with log, process.stdout:
                for raw in iter(process.stdout.readline, b''):
                    text = raw.decode('utf-8', errors='replace')
                    log.write(text)
                    self.output.emit(text)
            code = process.wait()
        except OSError as error:
            self.output.emit(f'Launcher: {error}\n')
            self.stop()
            process.wait()
        finally:
            self.finished.emit(code)

    def stop(self):
        if self.job:
            self.job.terminate()

    def _finished(self, _code):
        if self.job:
            self.job.close()
        self.process = self.job = None


class _BackendUi(SimpleNamespace, backend.bbport_help.HelpMixin):
    """The Tk launcher's view of this window for the shared Help checks: whatever helper a check calls on
    itself (preflight's gpu_problem, unused_card) comes from HelpMixin instead of a hand-kept list."""


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        from bbport_qt_basic import BasicPage
        saved = backend.load_profile()
        self.settings = {**backend.APP_DEFAULTS, **saved}
        self.initial_settings = dict(self.settings)
        self.settings.update(backend.settled_online(self.settings, saved))  # dead ends to SuperMedo Server
        backend.bbport_tls.set_routes(backend.relay_routes(self.settings))
        # 1.9.2's account (the password in plain text) and the sign-in of a server no longer offered.
        for key in ('supermedo_user', 'supermedo_password', 'thd_online_id', 'thd_token', 'bridge_live_map'):
            self.settings.pop(key, None)
        if self.settings.get('ui_mode') not in ('simple', 'expert'):
            self.settings['ui_mode'] = 'expert' if saved.get('setup_done') or saved.get('game_dir') else 'simple'
        if 'on_play' not in saved and saved.get('close_on_play'):
            self.settings['on_play'] = 'close'
        if self.settings.get('on_play') not in dict(backend.ON_PLAY):
            self.settings['on_play'] = 'stay'
        if self.settings.get('play_with') not in ('controller', 'keyboard'):
            mouse = backend.load_input_ini(backend.input_ini_path(backend.ini_path()))[-1]
            self.settings['play_with'] = 'keyboard' if mouse['enabled'] else 'controller'
        backend.LANG = self.settings.get('ui_language') or backend.windows_language()
        self.graphics, _ = backend.load_ini(self.settings)
        self.initial_graphics = dict(self.graphics)
        self.runner = GameProcess(self)
        self.closing = self.hidden_for_game = self._collecting = False
        self.placer = None
        self.pages, self.page_ids = {}, []
        self.setWindowTitle('Bloodborne')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet('QMainWindow { background: transparent; }')
        self.setWindowIcon(QIcon(str(backend.PORT_DIR / 'launcher/bloodborne.png')))
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry().size() if screen else None
        self.resize(min(1180, available.width() - 40) if available else 1180,
                    min(760, available.height() - 80) if available else 760)
        self.setMinimumSize(860, 580)
        content = QWidget()
        content.setObjectName('launcher')
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(248)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 24, 12, 16)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setFixedWidth(48)
        emblem = QPixmap(str(backend.theme.ASSETS / 'emblem-bone.png'))
        mark.setPixmap(emblem.scaled(42, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(mark)
        words = QVBoxLayout()
        for text, name in [('BLOODBORNE', 'brand'), ('PC PORT', 'brandSubtitle')]:
            label = QLabel(text)
            label.setObjectName(name)
            words.addWidget(label)
        brand.addLayout(words)
        side.addLayout(brand)
        credit = QLabel(backend._('by Super Medo') + f'  ·  v{backend.VERSION}')
        credit.setObjectName('pageDescription')
        side.addWidget(credit)
        self.search = QLineEdit()
        self.search.setPlaceholderText(backend._('Search settings…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search)
        side.addWidget(self.search)
        self.search_results = QListWidget()
        self.search_results.setObjectName('searchResults')
        self.search_results.hide()
        self.search_results.itemActivated.connect(self._search_open)
        self.search_results.itemClicked.connect(self._search_open)
        self.search.returnPressed.connect(lambda: self._search_open(self.search_results.item(0)))
        side.addWidget(self.search_results)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(self.navigation, 1)
        self.expert = QCheckBox(backend._('Expert view'))
        self.expert.setChecked(self.settings.get('ui_mode') == 'expert')
        self.expert.toggled.connect(self._mode)
        side.addWidget(self.expert)
        site = QLabel(f'<a href="{backend.COMMUNITY_SITE}" style="color:{backend.GOLD};text-decoration:none">bbport.de ↗</a>')
        site.setOpenExternalLinks(True)
        side.addWidget(site)
        layout.addWidget(sidebar)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.header = PageHeader()
        self.page_title = self.header.title
        right.addWidget(self.header)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        right.addWidget(self.tabs, 1)
        self.pages.update(play=HomePage(self.settings, self.graphics),
            picture=PicturePage(self.settings, self.graphics),
            controls=ControlsPage({**self.settings, **self.graphics}, backend.input_ini_path(backend.ini_path())),
            online=OnlinePage(self.settings), saves=SavesPage(self.settings),
            mods=ModsPage(self.settings), trophies=TrophiesPage(self.settings),
            help=HelpPage(self.settings), graphics=GraphicsPage(self.settings, self.graphics),
            system=SystemPage(self.settings))
        for key in ('game', 'gameplay', 'cheats', 'language', 'advanced'):
            self.pages[key] = BasicPage(self.settings, self.graphics, key)
            self.pages[key].action_requested.connect(self._action)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(backend.MAX_LOG_LINES)
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(28, 18, 28, 18)
        row = QHBoxLayout()
        for title, callback in [('Copy log', lambda: QApplication.clipboard().setText(self.log.toPlainText())),
                                 ('Open log', self._open_log)]:
            button = QPushButton(backend._(title))
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        log_layout.addLayout(row)
        log_layout.addWidget(self.log)
        self.pages['log'] = log_page
        for key, titles in backend.NAV_SIMPLE + backend.NAV_EXPERT + [('log', ('Log',))]:
            self.page_ids.append(key)
            page = self.pages[key]
            if key not in ('controls', 'graphics'):
                view = page
            else:
                view = QScrollArea()
                view.setWidgetResizable(True)
                view.setWidget(page)
            self.tabs.addTab(view, backend._(*titles))
            self.navigation.addItem(backend._(*titles))
            if hasattr(page, 'page_requested'):
                page.page_requested.connect(self.show_page)
            if hasattr(page, 'play_requested'):
                page.play_requested.connect(self.play)
            if hasattr(page, 'device_requested'):
                page.device_requested.connect(self._device)
        self.pages['controls'].help_requested.connect(lambda _topic: self.show_page('help'))
        for key in ('play', 'picture'):
            self.pages[key].system_page = self.pages['system']
        self.pages['system'].rating_changed.connect(self._rating_changed)
        self.navigation.currentRowChanged.connect(self._navigate)
        self.navigation.setItemDelegate(NavigationDelegate(self.page_ids, self.height() < 800, self.navigation))
        self.tabs.currentChanged.connect(self._tab_changed)
        footer = QWidget()
        footer.setObjectName('footer')
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        self.save_button = QPushButton(backend._('Save settings'))
        self.play_button = QPushButton(backend._('Play'))
        self.play_button.setObjectName('playButton')
        self.stop_button = QPushButton(backend._('Stop'))
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        buttons.addWidget(self.save_button)
        self.save_button.hide()
        self.footer_status = QLabel()
        self.footer_status.setObjectName('pageDescription')
        buttons.addWidget(self.footer_status)
        buttons.addStretch()
        log_button = QPushButton(backend._('Log'))
        log_button.clicked.connect(lambda: self.show_page('log'))
        buttons.addWidget(log_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.play_button)
        right.addWidget(footer)
        layout.addLayout(right, 1)
        self.setCentralWidget(content)
        self.opacity_effect = QGraphicsOpacityEffect(content)
        content.setGraphicsEffect(self.opacity_effect)
        self._appearance()
        self.runner.output.connect(self._append_log)
        self.runner.finished.connect(self._game_finished)
        self.save_button.clicked.connect(self.save)
        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.runner.stop)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self.search.setFocus)
        self._mode(self.expert.isChecked())
        self.navigation.setCurrentRow(0)
        self._tab_changed(0)
        self._index_fields()
        self.pages['game'].settings_changed.connect(self._ready)
        self._ready()
        self.statusBar().messageChanged.connect(self.footer_status.setText)
        self.statusBar().hide()
        self.footer_status.setText(self.statusBar().currentMessage())
        self.ini_timer = QTimer(self)
        self.ini_timer.setInterval(250)
        self.ini_timer.timeout.connect(self._sync_ini)
        self.ini_timer.start()

    def _sync_ini(self):
        if self.runner.process is None:
            return
        try:
            stamp = backend.ini_path().stat().st_mtime_ns
            if stamp != getattr(self, '_ini_seen', None):
                self._ini_seen = stamp
                return
            if stamp == getattr(self, '_ini_synced', None):
                return
            graphics, _ = backend.load_ini(self.settings)
            for key, value in graphics.items():
                if self.graphics.get(key) == self.initial_graphics.get(key):
                    self.graphics[key] = value
            self.initial_graphics = dict(graphics)
            for key, page in self.pages.items():
                if hasattr(page, 'ini_values') and key != 'controls':
                    page.refresh(self.settings, self.graphics)
            self._ini_synced = stamp
            self.pages['controls'].refresh_preferences(self.settings, self.graphics)
        except OSError:
            pass

    def _appearance(self):
        self.opacity_effect.setOpacity(0.985 if self.settings.get('translucent_window') else 1.0)

    def _ready(self):
        if self.runner.process is not None:
            return
        folder = self.pages['game'].app_widgets['game_dir'].text()
        ready = bool(backend.game_info(folder))
        self.play_button.setEnabled(ready)
        self.statusBar().showMessage(backend._('Ready to play.') if ready else backend._('Choose the game folder first.'))

    def _index_fields(self):
        self.app_widgets, self.ini_widgets = {}, {}
        for page in self.pages.values():
            self.app_widgets.update(getattr(page, 'fields', {}))
            self.app_widgets.update(getattr(page, 'app_widgets', {}))
            self.ini_widgets.update(getattr(page, 'ini_fields', {}))
            self.ini_widgets.update(getattr(page, 'ini_widgets', {}))
        self.ini_widgets['button_prompts'] = self.pages['controls'].prompts

    def _collect(self):
        if self._collecting:
            return
        self._collecting = True
        try:
            for key, page in self.pages.items():
                if key in ('saves', 'mods'):
                    page._collect_settings()
                elif key == 'controls':
                    self.settings.update(page.app_values())
                    self.graphics.update(page.ini_values())
                elif hasattr(page, 'save'):
                    page.save()
            self.settings['ui_mode'] = 'expert' if self.expert.isChecked() else 'simple'
            for key, page in self.pages.items():
                if key in ('play', 'picture', 'graphics', 'game', 'gameplay', 'cheats', 'language', 'advanced'):
                    page.refresh(self.settings, self.graphics)
            self.pages['controls'].refresh_preferences(self.settings, self.graphics)
        finally:
            self._collecting = False

    def _navigate(self, index):
        if index < 0:
            return
        try:
            self._collect()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Settings', str(error))
            self.navigation.setCurrentRow(self.tabs.currentIndex())
            return
        self.tabs.setCurrentIndex(index)

    def _tab_changed(self, index):
        self.navigation.setCurrentRow(index)
        key = self.page_ids[index]
        self.header.set_page(key, self.tabs.tabText(index))
        self.header.setVisible(key != 'play')
        if key in ('saves', 'mods', 'trophies', 'online', 'help'):
            self.pages[key].refresh(self.settings)

    def open_topic(self, key):
        self.show_page('help')
        self.pages['help'].open_topic(key)

    def show_page(self, key):
        if key == 'setup':
            self._action('setup')
            return
        if key not in self.pages:
            return
        if key in backend.EXPERT_PAGES and key != 'log':
            self.expert.setChecked(True)
        self.navigation.setCurrentRow(self.page_ids.index(key))

    def _mode(self, expert):
        self.settings['ui_mode'] = 'expert' if expert else 'simple'
        for index, key in enumerate(self.page_ids):
            self.navigation.item(index).setHidden(key == 'log' or (not expert and key in backend.EXPERT_PAGES))
        if self.page_ids and not expert and self.page_ids[self.tabs.currentIndex()] in backend.EXPERT_PAGES:
            self.show_page('play')

    def _search(self, query):
        active = bool(query.strip())
        self.search_results.clear()
        self.search_results.setVisible(active)
        self.navigation.setVisible(not active)
        if active:
            for entry in ranked_settings(query, self.page_ids, expert=self.expert.isChecked()):
                self.search_results.addItem(entry['title'])
                item = self.search_results.item(self.search_results.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                item.setToolTip(entry['hint'])

    def _search_open(self, item):
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        self.search.clear()
        if entry.get('run') == 'open_setup':
            self._action('setup')
            return
        self.show_page(entry['page'])
        if entry.get('topic'):
            self.pages['help'].open_topic(entry['topic'])
            return
        widget = self.pages[entry['page']].findChild(QWidget, entry['key'])
        if widget:
            widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
            ancestor = widget.parentWidget()
            while ancestor:
                if isinstance(ancestor, QScrollArea):
                    ancestor.ensureWidgetVisible(widget, 12, 24)
                ancestor = ancestor.parentWidget()

    def _device(self, device):
        self.pages['controls'].set_play_with(device)

    def _rating_changed(self):
        self.pages['picture'].apply_automatic()
        for key in ('play', 'picture'):
            self.pages[key]._draw()

    def save(self):
        try:
            self._collect()
            self.pages['controls'].save()
            self.pages['mods'].save()
            self.pages['saves'].save()
            settings = {**backend.APP_DEFAULTS, **backend.load_profile()}
            settings.update({key: value for key, value in self.settings.items()
                             if value != self.initial_settings.get(key)})
            for key in ('supermedo_user', 'supermedo_password'):
                settings.pop(key, None)
            graphics, lines = backend.load_ini(settings)
            graphics.update({key: value for key, value in self.graphics.items()
                             if value != self.initial_graphics.get(key)})
            backend.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            backend.save_ini(graphics, lines)
            backend.CONFIG_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding='utf-8')
            self.settings.clear()
            self.settings.update(settings)
            self.graphics.clear()
            self.graphics.update(graphics)
            self.initial_settings, self.initial_graphics = dict(settings), dict(graphics)
            self._appearance()
            for key, page in self.pages.items():
                if hasattr(page, 'ini_values') and key != 'controls':
                    page.refresh(self.settings, self.graphics)
            self.pages['controls'].refresh_preferences(self.settings, self.graphics)
            self.statusBar().showMessage(backend._('Settings saved'))
            return True
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, 'Could not save settings', str(error))
            return False

    def _open_log(self):
        self._open_path(backend.saves_folder(self.settings) / 'last_run.log')

    def _open_path(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _backend_ui(self):
        messages = SimpleNamespace(showinfo=lambda title, text: QMessageBox.information(self, title, text),
            showerror=lambda title, text: QMessageBox.critical(self, title, text),
            askyesno=lambda title, text, **_kwargs: QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes)
        return _BackendUi(app=self.settings, process=self.runner.process, messagebox=messages,
            collect=self.save, open_topic=self.open_topic,
            var=lambda key, store='app': SimpleNamespace(get=lambda: (self.graphics if store == 'ini' else self.settings).get(key)))

    def _action(self, action):
        if action in ('language', 'help'):
            self.show_page(action)
        elif action == 'respec':
            self.pages['saves'].open_respec()
        elif action in ('port_folder', 'ini'):
            self._open_path(backend.PORT_DIR if action == 'port_folder' else backend.ini_path())
        elif action in ('updates', 'versions'):
            QDesktopServices.openUrl(QUrl(backend.RELEASES_PAGE))
        elif action == 'benchmark':
            QMessageBox.information(self, 'Bloodborne', 'Game tests are not available on Linux.')
        elif action in ('shortcut', 'steam', 'cache'):
            if not self.save():
                return
            getattr(backend.Launcher, {'steam': 'add_to_steam', 'cache': 'clear_cache'}.get(action, action))(self._backend_ui())
        elif action == 'setup':
            from bbport_qt_home import SetupWizard
            wizard = SetupWizard(self.settings, self.graphics, self)
            wizard.page_requested.connect(self.show_page)
            wizard.device_requested.connect(self._device)
            wizard.shortcut_requested.connect(lambda: self._action('shortcut'))
            wizard.steam_requested.connect(lambda: self._action('steam'))
            def finish_setup():
                blocked = self.expert.blockSignals(True)
                self.expert.setChecked(self.settings.get('ui_mode') == 'expert')
                self.expert.blockSignals(blocked)
                for page in self.pages.values():
                    if hasattr(page, 'ini_values') and page is not self.pages['controls']:
                        page.refresh(self.settings, self.graphics)
                    elif hasattr(page, 'refresh') and page not in (self.pages['controls'], self.pages['saves'], self.pages['mods']):
                        page.refresh(self.settings)
                self._mode(self.expert.isChecked())
                self._device(wizard.device.currentData())
                if self.save():
                    if wizard.download.isChecked() and not wizard.download.isHidden():
                        self.show_page('graphics')
                        self.pages['graphics'].download_fsr4()
                    elif wizard.play.isChecked():
                        QTimer.singleShot(0, self, self.play)
            wizard.accepted.connect(finish_setup)
            wizard.exec()
        elif action == 'relaunch' and self.runner.process is None and self.save():
            subprocess.Popen([sys.executable, str(backend.PORT_DIR / 'launcher/bbport_launcher_qt.py')])
            self.close()

    def _running(self, running):
        self.play_button.setEnabled(not running)
        self.save_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.stop_button.setVisible(running)
        for page in self.pages.values():
            if hasattr(page, 'set_game_running'):
                page.set_game_running(running)
        if not running:
            self._ready()

    def play(self):
        assets = self.pages['graphics']
        if assets.downloading or assets.fsr411_downloading:
            QMessageBox.warning(self, 'Downloads', 'Wait for the graphics asset download to finish or cancel it.')
            return
        if self.runner.process is not None:
            return
        try:
            self._collect()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Settings', str(error))
            return
        if not self.settings.get('online') and backend.pool_account(self.settings):
            choice = QMessageBox.question(self, 'Bloodborne', backend._('An online account is filled in, but "Play online" is off.\n\nYes: play online.   No: play offline.'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            self.settings['online'] = choice == QMessageBox.StandardButton.Yes
        # "No" is this start only: a later start from Steam or a shortcut must not stay offline without a word.
        offline_once = False
        if backend.needs_sign_in(self.settings):
            choice = QMessageBox.question(self, 'Bloodborne', backend._('Online play needs a free SuperMedo account: one for SuperMedo Server and Seamless '
                'co-op. Sign in or make one here.') + '\n\n' + backend._('Sign in now? (No: play offline this time.)'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Yes:
                self.show_page('online')
                return
            offline_once = True
        if self.settings.get('online') and self.settings.get('online_pool') == 'shadnet' and '@' in self.settings.get('online_npid', ''):
            QMessageBox.warning(self, 'Bloodborne', backend._('The Online ID is the account name (NPID) you registered on the server, not your email address.'))
            self.show_page('online')
            return
        self.pages['play'].refresh(self.settings, self.graphics)
        self.pages['online'].refresh(self.settings)
        if not self.save():
            return
        if not backend.game_info(self.settings['game_dir']):
            QMessageBox.warning(self, 'Game folder', 'Choose the game folder containing eboot.bin.')
            self.show_page('game')
            return
        if not self._backend_ui().preflight():
            return
        if self.graphics['upscaler'] == 'fsr411':
            env = backend.bbport_fsr411.environment(backend.PORT_DIR, self.settings)
            support = backend.bbport_fsr411.query(backend.PORT_DIR, env)
            status = backend.bbport_fsr411.method_status(backend.PORT_DIR, backend.DATA_DIR,
                backend.fsr411_backend(self.graphics), support, backend.fetch_fsr4vk, env,
                output_res=self.graphics['output_res'], preset=self.graphics['preset'])
            if not status['supported']:
                QMessageBox.warning(self, 'FSR 4.1.1', backend.bbport_fsr411.message(status, backend._))
                return
        self.log.clear()
        try:
            self.runner.start({**self.settings, 'online': False} if offline_once else dict(self.settings), dict(self.graphics))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, 'Could not start game', str(error))
            return
        self._running(True)
        self.statusBar().showMessage(backend._('Preparing the game; it opens in its own window…'))
        self.placer = backend.display.Placer(self.settings, backend.display.parse_size(self.graphics.get('output_res')) or (1920, 1080)).start()
        mode = self.settings.get('on_play', 'stay')
        QTimer.singleShot(5000, self, lambda: self._after_start(mode))

    def _after_start(self, mode):
        if self.runner.process is None:
            return
        if mode == 'minimize':
            self.showMinimized()
        elif mode == 'close':
            self.hidden_for_game = True
            self.hide()

    def _append_log(self, text):
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self.log.setTextCursor(cursor)
        self.pages['trophies'].observe(text)
        if 'Entering original x86-64 code' in text:
            self.statusBar().showMessage(backend._('The game is running.'))

    def _game_finished(self, code):
        self._append_log(f'\nGame exited with code {code}.\n')
        self._running(False)
        graphics, _ = backend.load_ini(self.settings)
        self.graphics.clear()
        self.graphics.update(graphics)
        self.initial_graphics = dict(graphics)
        for key, page in self.pages.items():
            if hasattr(page, 'ini_values') and key != 'controls':
                page.refresh(self.settings, self.graphics)
        if self.placer:
            if self.placer.last and not self.settings.get('fullscreen'):
                self.settings['window_last'] = backend.display.size_text(self.placer.last)
                backend.remember_window(self.placer.last)
            self.placer.stop()
            self.placer = None
        if code and self.hidden_for_game:
            self.hidden_for_game = False
            self.showNormal()
            self.show_page('log')
        elif self.closing or (self.hidden_for_game and not self.settings.get('reopen_after_game', False)):
            self.close()
        elif self.hidden_for_game or self.isMinimized():
            self.hidden_for_game = False
            self.showNormal()
        self.pages['play'].refresh(self.settings, self.graphics)
        self.pages['controls'].refresh_preferences(self.settings, self.graphics)
        if code:
            # always: an error the log does not name still gets an answer, not silence.
            QTimer.singleShot(300, self, lambda: self._backend_ui().after_exit(code, always=True))

    def closeEvent(self, event):
        if not self.closing:
            self.save()
        if self.runner.process is not None:
            self.hidden_for_game = True
            self.hide()
            event.ignore()
            return
        self.pages['controls'].stop()
        self.pages['online'].shutdown()
        self.pages['graphics'].cancel_downloads()
        self.closing = True
        event.accept()


def main():
    args = sys.argv[1:]
    if args[:1] in (['--run'], ['--script']):
        return backend.run_role(args)
    settings = {**backend.APP_DEFAULTS, **backend.load_profile()}
    backend.LANG = settings.get('ui_language') or backend.windows_language()
    if '--play' in args and backend.CONFIG_FILE.exists() and (backend.Path(settings['game_dir'] or '.') / 'eboot.bin').is_file():
        result = backend.play_without_window(settings)
        if result is not None:
            return result
    if not backend.WINDOWS and os.environ.get('WAYLAND_DISPLAY'):
        os.environ.setdefault('QT_QPA_PLATFORM', 'wayland')
    app = QApplication(sys.argv)
    theme.apply(app)
    # An error in a button's handler only reached stderr, which a desktop start does not show: Play did nothing.
    def report(kind, error, trace):
        sys.__excepthook__(kind, error, trace)
        QMessageBox.critical(QApplication.activeWindow(), 'Bloodborne', backend.error_text(error, kind=True))
    sys.excepthook = report
    window = LauncherWindow()
    window.show()
    if not window.settings.get('setup_done'):
        QTimer.singleShot(0, window, lambda: window._action('setup'))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())

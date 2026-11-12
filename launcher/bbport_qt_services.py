# SPDX-License-Identifier: GPL-2.0-or-later
"""Qt views for the existing account, trophy, installation and hardware services."""
import json
import os
import platform
import queue
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHeaderView,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import bbport_launcher_win as backend
import bbport_hardware as hardware
import bbport_help as help_service
import bbport_setup as setup
import bbport_trophies as trophies


def _label(text):
    label = QLabel(backend._(text))
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return label


def _open(url):
    QDesktopServices.openUrl(QUrl(url))


def _hint(text):
    label = _label(text)
    label.setObjectName('pageDescription')
    font = label.font()
    font.setPointSize(9)
    label.setFont(font)
    label.setMaximumWidth(640)
    label.setFixedHeight(label.heightForWidth(640))
    return label


class _Page(QScrollArea):
    page_requested = Signal(str)
    _done = Signal(object, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.running = False
        self.fields = {}
        self._initial_fields = {}
        self.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('settingsPage')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(28, 22, 28, 28)
        self.body.setSpacing(16)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(body)
        self._done.connect(self._dispatch)

    def _card(self, title):
        if getattr(self, 'FLAT_SECTIONS', False):
            card = QWidget()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            if title:
                heading = QHBoxLayout()
                label = QLabel(backend._(title))
                label.setObjectName('sectionTitle')
                heading.addWidget(label)
                rule = QWidget()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f'background: {backend.theme.BORDER};')
                heading.addWidget(rule, 1)
                layout.addLayout(heading)
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(10)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            layout.addLayout(form)
            self.body.addWidget(card)
            return card, form
        card = QGroupBox(backend._(title))
        form = QFormLayout(card)
        form.setContentsMargins(18, 22, 18, 16)
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.body.addWidget(card)
        return card, form

    def _field(self, form, key, title, checkbox=False, password=False):
        widget = QCheckBox(backend._(title)) if checkbox else QLineEdit()
        widget.setObjectName(key)
        if password:
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        if getattr(self, 'FLAT_SECTIONS', False) and not checkbox:
            widget.setMaximumWidth(390)
        self.fields[key] = widget
        form.addRow(widget) if checkbox else form.addRow(backend._(title), widget)
        return widget

    def _button(self, form, title, callback):
        button = QPushButton(backend._(title))
        if getattr(self, 'FLAT_SECTIONS', False):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        button.clicked.connect(callback)
        form.addRow(button)
        return button

    def _work(self, work, done):
        def run():
            try:
                result = work()
            except Exception as error:
                result = error
            try:
                self._done.emit(done, result)
            except RuntimeError:
                pass  # The window can close while a bounded service request is finishing.
        threading.Thread(target=run, daemon=True).start()

    def _dispatch(self, callback, result):
        callback(result)

    def app_values(self):
        values = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            else:
                value = widget.text()
            if value != self._initial_fields.get(key):
                values[key] = value
        return values

    def save(self):
        values = self.app_values()
        self.settings.update(values)
        self._initial_fields.update(values)

    def refresh(self, settings=None):
        if settings is not None:
            self.settings = settings
        for key, widget in self.fields.items():
            value = self.settings.get(key, backend.APP_DEFAULTS.get(key, ''))
            blocked = widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            else:
                widget.setText(str(value))
            widget.blockSignals(blocked)
        self._initial_fields = {key: widget.isChecked() if isinstance(widget, QCheckBox) else
            widget.currentData() if isinstance(widget, QComboBox) else widget.text()
            for key, widget in self.fields.items()}

    def set_game_running(self, running):
        self.running = bool(running)


def _row(*widgets):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return row, layout


def _box(form):
    """Rows that show or hide together inside a card."""
    holder = QWidget()
    inner = QFormLayout(holder)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(10)
    inner.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.addRow(holder)
    return holder, inner


class OnlinePage(_Page):
    """SuperMedo Server's account and parties (the reference: bbport_launcher_win.build_online and build_party).
    An own server only for Seamless co-op's own start (backend.settled_pool)."""
    FLAT_SECTIONS = True
    PARTY_POLL_MS = 15000

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        self._account = ('', '')
        self._party_key = ''
        self._register_open = False
        _, form = self._card('')
        self._field(form, 'online', 'Play online', checkbox=True)
        form.addRow(_hint(backend._('Off: the game stays offline, as before.') + ' ' +
                          backend._('Cheats, debug features and third-party patches run offline only.')))
        self.state = _label('')
        form.addRow(self.state)
        _, form = self._card('Co-op pool')
        self.pool = QComboBox(self)
        self.pool.hide()
        self.pool.addItem(backend._('SuperMedo Server'), 'supermedo')
        if backend.started_by_bbsc():
            self.pool.addItem(backend._("Own server (Seamless co-op, a friend's)"), 'shadnet')
        self.pool.setObjectName('online_pool')
        self.fields['online_pool'] = self.pool
        pool_row = QWidget()
        pool_row.setStyleSheet(f'QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {backend.theme.BORDER_HOVER}; border-radius: 7px; background: transparent; }} '
            f'QRadioButton::indicator:checked {{ border-color: {backend.theme.BLOOD_LIGHT}; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, stop:0 {backend.theme.BLOOD_LIGHT}, stop:0.45 {backend.theme.BLOOD_LIGHT}, stop:0.5 transparent, stop:1 transparent); }}')
        pool_layout = QHBoxLayout(pool_row)
        pool_layout.setContentsMargins(0, 0, 0, 0)
        self.pool_group = QButtonGroup(pool_row)
        self.pool_buttons = {}
        for index in range(self.pool.count()):
            value = self.pool.itemData(index)
            radio = QRadioButton(self.pool.itemText(index))
            self.pool_buttons[value] = radio
            self.pool_group.addButton(radio)
            radio.clicked.connect(lambda _checked=False, value=value: self.pool.setCurrentIndex(self.pool.findData(value)))
            pool_layout.addWidget(radio)
        pool_layout.addStretch()
        form.addRow(backend._('Play with'), pool_row)
        form.addRow(_hint("SuperMedo Server (recommended): supermedo.com's own servers, with a free account made below."))

        self.supermedo_card, account = self._card('SuperMedo account')
        account.addRow(_hint('One account for SuperMedo Server and Seamless co-op.'))
        self.account = _label('Not signed in')
        self.sign_out_button = QPushButton(backend._('Sign out'))
        self.sign_out_button.setObjectName('button:signout')
        self.sign_out_button.clicked.connect(self.sign_out)
        row, _layout = _row(self.account, self.sign_out_button)
        account.addRow(backend._('Account'), row)
        self.signed_out, out = _box(account)
        self.sign_in_button = QPushButton(backend._('Sign in with Discord'))
        self.sign_in_button.setObjectName('button:signin_supermedo')
        self.sign_in_button.clicked.connect(self.sign_in)
        out.addRow('Discord', _row(self.sign_in_button)[0])
        out.addRow(_hint('Discord makes your SuperMedo account the first time, named after your Discord name; nothing to '
                         'remember. Sign in again on any PC.'))
        self.signing = _label('')
        out.addRow(self.signing)
        self.login_npid = QLineEdit()
        self.login_npid.setObjectName('supermedo_npid')
        self.login_npid.setMaximumWidth(390)
        out.addRow(backend._('Online ID'), self.login_npid)
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.returnPressed.connect(self.sign_in_password)
        self.login_button = QPushButton(backend._('Sign in'))
        self.login_button.setObjectName('button:signin_password')
        self.login_button.clicked.connect(self.sign_in_password)
        out.addRow(backend._('Password'), _row(self.login_password, self.login_button)[0])
        out.addRow(_hint('An account made here, on another PC or before: its Online ID and password.'))
        self.login_line = _label('')
        out.addRow(self.login_line)
        self.register_link = QPushButton('')
        self.register_link.setFlat(True)
        self.register_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.register_link.clicked.connect(self.toggle_register)
        out.addRow(_row(self.register_link)[0])
        self.register_box, register = _box(out)
        self.new_npid, self.new_password, self.email = QLineEdit(), QLineEdit(), QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        register.addRow(backend._('New Online ID'), self.new_npid)
        register.addRow(_hint('1 to 16 letters, numbers, _ or -. Other players see this name.'))
        register.addRow(backend._('New password'), self.new_password)
        register.addRow(backend._('Email address'), self.email)
        register.addRow(_hint('Only to make the account.'))
        self.create_button = QPushButton(backend._('Create account'))
        self.create_button.setObjectName('button:create_account')
        self.create_button.clicked.connect(self.create_account)
        register.addRow(_row(self.create_button)[0])
        self.sign_up = _label('')
        register.addRow(self.sign_up)

        self.party_card, party = self._card('Party (play with friends)')
        self.party_line = _label('Not in a party.')
        party.addRow(backend._('Your party'), self.party_line)
        party.addRow(_hint("While you are in a party, your bells and summon signs find only your party's hunters, with no "
                           "level limit. Leave the password in the game's network settings empty: the party brings you "
                           'together.'))
        self.party_code = _label('')
        self.party_code.setObjectName('deviceCode')
        copy = QPushButton(backend._('Copy'))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.party_code.text()))
        new_code = QPushButton(backend._('New code'))
        new_code.clicked.connect(lambda: self.party_act('new_code'))
        self.code_box, code = _box(party)
        code.addRow(backend._('Party code'), _row(self.party_code, copy, new_code)[0])
        code.addRow(_hint('Send this code to your friends. A new code stops the old one; friends already in stay.'))
        self.kicks, self.kick_layout = _row()
        party.addRow(self.kicks)
        self.roster = _label('')
        party.addRow(self.roster)
        self.join_code = QLineEdit()
        self.join_code.setObjectName('party_key')
        self.join_code.setMaximumWidth(200)
        join = QPushButton(backend._('Join'))
        join.clicked.connect(lambda: self.party_act('join', {'code': self.join_code.text().strip()}))
        party.addRow(backend._('Join a party'), _row(self.join_code, join)[0])
        party.addRow(_hint('Paste the code a friend sent you (SM-XXXX-XXXX).'))
        host = QPushButton(backend._('Make party code'))
        host.clicked.connect(lambda: self.party_act('host'))
        self.leave_button = QPushButton(backend._('Leave party'))
        self.leave_button.clicked.connect(lambda: self.party_act('leave'))
        refresh = QPushButton(backend._('Refresh'))
        refresh.clicked.connect(lambda: self.party_act('status'))
        party.addRow(_row(host, self.leave_button, refresh)[0])
        self.party_said = _label('')
        party.addRow(self.party_said)
        self.party_timer = QTimer(self)
        self.party_timer.setInterval(self.PARTY_POLL_MS)
        self.party_timer.timeout.connect(self._poll_party)
        self.party_timer.start()

        self.shadnet_card, shadnet = self._card('Own server')
        self._field(shadnet, 'online_npid', 'Online ID (NPID)')
        shadnet.addRow(_hint('Your account name on that server, not your email.'))
        self._field(shadnet, 'online_password', 'Password', password=True)
        shadnet.addRow(_hint('Saved on this PC with the other launcher settings.'))
        self._field(shadnet, 'online_community', 'Game server')
        shadnet.addRow(_hint('game.supermedo.com by default. Only the name is needed; the game picks the ports.'))
        self._field(shadnet, 'online_server', 'Server address')
        shadnet.addRow(_hint('host:port from the person who runs the server (Seamless co-op: its own address).'))
        self._field(shadnet, 'online_webapi', 'WebAPI address')
        shadnet.addRow(_hint('Of the shadNet server, not the game server. Leave empty: the server address with '
                             'port 31315 is used.'))

        _, connection = self._card('Connection')
        self._field(connection, 'online_upnp', 'UPnP (open a port on the router automatically)', checkbox=True)
        connection.addRow(_hint('Turn it off on Tailscale or another VPN.'))
        self.relay_box, relay = _box(connection)
        self.relay = self._field(relay, 'online_relay', 'Russia route (through a relay in Kazakhstan)', checkbox=True)
        relay.addRow(_hint('Only if your network in Russia cannot reach the SuperMedo server: the connection goes '
                           'through a relay to the same server and players. Leave it off otherwise.'))
        self.check_button = self._button(connection, 'Test connection', self.check_connection)
        self.check_button.setObjectName('button:test_connection')
        self.result = _label('')
        connection.addRow(self.result)
        connection.addRow(_hint(backend._('Everyone in a session needs the same game version (1.09) and the same server.') +
                                ' ' + backend._('Cheats, debug features and third-party patches run offline only.')))
        self.pool.currentIndexChanged.connect(self._show_pool)
        self.relay.toggled.connect(self._route_changed)
        self.fields['online'].toggled.connect(self._show_state)
        self.refresh()

    def _pool(self):
        return self.pool.currentData() or 'supermedo'

    def _signed_name(self):
        return backend.pool_account({'online_pool': 'supermedo', 'supermedo_npid': self._account[0],
                                     'supermedo_pass': self._account[1]})

    def _route_changed(self, *_args):
        backend.bbport_tls.set_routes(backend.relay_routes({'online_relay': self.relay.isChecked(),
                                                            'online_pool': self._pool()}))

    def _show_pool(self, *_args):
        supermedo = self._pool() == 'supermedo'
        for value, radio in self.pool_buttons.items():
            radio.setChecked(value == self._pool())
        self.supermedo_card.setVisible(supermedo)
        self.party_card.setVisible(supermedo)
        self.relay_box.setVisible(supermedo)
        self.shadnet_card.setVisible(not supermedo)
        self._route_changed()
        self._show_account()

    def _show_state(self, *_args):
        if not self.fields['online'].isChecked():
            text = backend._('• Online play is off: the game starts offline.')
        else:
            name = self._signed_name() if self._pool() == 'supermedo' else self.fields['online_npid'].text().strip()
            title = self.pool.currentText()
            text = (backend._('✓ Online with {0}, signed in as {1}.').format(title, name) if name else
                    backend._('⚠ Not signed in yet: sign in below to play online.'))
        self.state.setText(text)

    def _show_account(self):
        name = self._signed_name()
        self.account.setText(backend._('Signed in as {}').format(name) if name else backend._('Not signed in'))
        self.sign_out_button.setEnabled(bool(name) and not self.running)
        self.signed_out.setVisible(not name)
        self.register_box.setVisible(not name and self._register_open)
        self.register_link.setText(backend._('No account yet? Make one') + ('  ⌄' if self._register_open else '  ›'))
        for label in (self.signing, self.login_line, self.sign_up, self.party_said):
            label.setVisible(bool(label.text()))
        self._show_state()

    def refresh(self, settings=None):
        super().refresh(settings)
        if self.pool.findData(self.settings.get('online_pool')) < 0:
            self.pool.setCurrentIndex(0)
            self._initial_fields['online_pool'] = None  # the settled pool is saved
        self._account = (str(self.settings.get('supermedo_npid', '')), str(self.settings.get('supermedo_pass', '')))
        self._initial_account = self._account
        self._party_key = str(self.settings.get('party_key', ''))
        self._initial_party_key = self._party_key
        self._show_pool()
        if self._party_key and self._signed_name():
            self.party_act('status', quiet=True)

    def save(self):
        super().save()
        if self._account != self._initial_account:
            self.settings['supermedo_npid'], self.settings['supermedo_pass'] = self._account
            self._initial_account = self._account
        if self._party_key != self._initial_party_key:
            self.settings['party_key'] = self._party_key
            self._initial_party_key = self._party_key

    def _set_account(self, npid, password):
        if npid != self._account[0]:
            self._party_key = ''  # another account: its own key
            self._show_party({})
        self._account = (npid, password)
        self._show_account()

    def sign_out(self):
        self._set_account('', '')

    def toggle_register(self):
        self._register_open = not self._register_open
        self._show_account()

    def _say(self, label, text):
        label.setText(text)
        label.setVisible(bool(text))

    def sign_in(self):
        if self.running:
            return
        self.sign_in_button.setEnabled(False)
        self._say(self.signing, backend._('Starting the sign-in…'))

        def on_page(page):
            def show(_):
                self._say(self.signing, backend._('Sign in with Discord in the page that opened, then come back here.'))
                _open(page)
            self._done.emit(show, None)

        def work():
            try:
                return backend.discord_sign_in(backend.COMMUNITY_SERVER, on_page)
            except Exception as error:
                return ValueError(backend.connection_error(error, backend.COMMUNITY_SERVER))

        def done(result):
            self.sign_in_button.setEnabled(not self.running)
            if isinstance(result, Exception):
                self._say(self.signing, backend._('Sign-in failed: {}').format(result))
                return
            self._say(self.signing, '')
            self._set_account(*result)
        self._work(work, done)

    def sign_in_password(self):
        npid, password = self.login_npid.text().strip(), self.login_password.text()
        if not npid or not password:
            self._say(self.login_line, backend._('Enter your Online ID and your password.'))
            return
        self._say(self.login_line, backend._('Checking the account…'))

        def done(problem):
            if problem:
                self._say(self.login_line, str(problem))
                return
            self.login_password.clear()
            self._say(self.login_line, '')
            self._set_account(npid, password)
        self._work(lambda: backend.bbport_signin.password_problem(npid, password), done)

    def create_account(self):
        npid, password, mail = self.new_npid.text().strip(), self.new_password.text(), self.email.text().strip()
        if not npid or not password or '@' not in mail:
            self._say(self.sign_up, backend._('Enter a new Online ID, a password and your email address.'))
            return
        self._say(self.sign_up, backend._('Creating the account…'))

        def done(problem):
            if problem:
                self._say(self.sign_up, str(problem))
                return
            self._set_account(npid, password)
            self._say(self.sign_up, backend._('Account {} created and signed in. Press Play to go online.').format(npid))
        self._work(lambda: backend.bbport_signin.register_problem(npid, password, mail), done)

    def _show_party(self, answer):
        party = answer.get('party')
        while self.kick_layout.count() > 1:  # the trailing stretch stays
            self.kick_layout.takeAt(0).widget().deleteLater()
        if not party:
            self.party_line.setText(backend._('Not in a party.'))
            self.code_box.hide()
            self.roster.hide()
            self.leave_button.setEnabled(False)
            return
        self.party_line.setText(backend.party_line(party))
        hunters = party.get('members', [])
        lines = [backend._('IN THE PARTY  {}/{}').format(len(hunters), party.get('size', 4))]
        for m in hunters:
            level = backend._('Level {}').format(m['level']) if m.get('level') else '–'
            lines.append(f"{'●' if m.get('online') else '○'} {m['name']}{'  ★' if m.get('host') else ''}   {level}")
        self.roster.setText('\n'.join(lines))
        self.roster.show()
        self.leave_button.setEnabled(not self.running)
        self.code_box.setVisible(bool(party.get('code')))
        if party.get('code'):  # the host's: copy it, and kick a hunter
            self.party_code.setText(party['code'])
            for m in hunters:
                if not m.get('host'):
                    kick = QPushButton(backend._('Kick') + ' ' + m['name'])
                    kick.clicked.connect(lambda _checked=False, n=m['name']: self.party_act('kick', {'member': n}))
                    self.kick_layout.insertWidget(self.kick_layout.count() - 1, kick)

    def party_act(self, call, body=None, quiet=False):
        name, password = self._account
        name = name.strip()
        if not name or not password:
            if not quiet:
                self._say(self.party_said, backend._('Sign in to your SuperMedo account first (above).'))
            return
        if not quiet:
            self._say(self.party_said, backend._('Checking…'))
        stored = self._party_key

        def work():
            key = stored
            status, answer = backend.party_call(call, body, key) if key else (401, {})
            if status == 401:  # no key yet, or an old one: sign in with the account once
                status, signed = backend.party_call('signin', {'name': name, 'password': password})
                if status != 200:
                    raise ValueError(signed.get('error', status))
                key = signed['key']
                status, answer = backend.party_call(call, body, key)
            if status != 200:
                raise ValueError(answer.get('error', status))
            if not isinstance(answer, dict):
                raise ValueError(backend._('an answer that is not a party'))
            return key, answer

        def done(result):
            if self._account[0].strip() != name:  # a late answer after a switch of account
                return
            if isinstance(result, Exception):
                if not quiet:
                    self._say(self.party_said, backend._('SuperMedo Server said: {}').format(result))
                return
            self._party_key, answer = result
            self._show_party(answer)
            if not quiet:
                self._say(self.party_said, '')
        self._work(work, done)

    def _poll_party(self):
        # While the party box is on screen: friends who join or leave show up by themselves.
        if self.roster.isVisible() and self._party_key:
            self.party_act('status', quiet=True)

    def check_connection(self):
        self.check_button.setEnabled(False)
        self.result.setText(backend._('Checking…'))
        values = {key: self.fields[key].text() for key in ('online_server', 'online_webapi', 'online_community')}
        pool = self._pool()
        online = self.fields['online'].isChecked()
        name = self._signed_name()
        own = {**values, 'online_pool': pool, 'online_custom_servers': True}
        address, webapi = ((backend.SUPERMEDO_SERVER, backend.SUPERMEDO_WEBAPI) if pool == 'supermedo' else
                           backend.shadnet_servers(own))
        game = backend.game_server(own)

        def check():
            try:
                text = backend.server_check(address, webapi, game)
                if pool == 'supermedo':
                    text += '\n' + (backend._('Signed in as {}').format(name) if name else
                                    backend._('Not signed in: sign in with Discord, or create an account below.'))
                elif values['online_webapi'].strip() and values['online_webapi'].strip() != webapi:
                    text += '\n' + backend._('The WebAPI box holds the game server address; it is ignored.')
                if not online:
                    text += '\n' + backend._('"Play online" is off: the game starts offline.')
            except Exception as error:
                text = backend._('The check stopped: {}').format(backend.error_text(error, kind=True))
            return text

        def done(result):
            self.check_button.setEnabled(True)
            self.result.setText(str(result))
        self._work(check, done)

    def set_game_running(self, running):
        super().set_game_running(running)
        for widget in self.fields.values():
            widget.setEnabled(not running)
        for radio in self.pool_buttons.values():
            radio.setEnabled(not running)
        for widget in (self.sign_in_button, self.login_button, self.create_button):
            widget.setEnabled(not running)
        self._show_account()

    def shutdown(self):
        self.party_timer.stop()


def _trophy_icon(grade, earned):
    pixmap = QPixmap(46, 46)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(backend.PANEL))
    painter.drawEllipse(1, 1, 44, 44)
    color = QColor(backend.TROPHY_COLORS[grade] if earned else backend.TROPHY_LOCKED)
    painter.setPen(color)
    painter.drawArc(10, 12, 10, 11, 90 * 16, 180 * 16)
    painter.drawArc(26, 12, 10, 11, 270 * 16, 180 * 16)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in ((15, 11), (31, 11), (30, 20), (26, 26), (20, 26), (16, 20))]))
    painter.drawRect(22, 26, 2, 6)
    painter.drawRect(18, 32, 10, 2)
    painter.drawRect(16, 35, 14, 2)
    painter.end()
    return QIcon(pixmap)


class TrophiesPage(_Page):
    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        self.tracker = None
        self._state = None
        self._searching = False
        self.import_hint = backend._('From an older port folder, the drive of your old PC or shadPS4: added to yours, '
                                     'none removed.')
        import_button = QPushButton(backend._('Bring achievements from another installation'))
        import_button.setObjectName('button:trophies')
        import_button.clicked.connect(lambda: self.import_trophies())
        self.import_note = _label(self.import_hint)
        self.import_note.setObjectName('pageDescription')
        self.body.addWidget(_row(import_button, self.import_note)[0])
        card = QGroupBox()
        row = QHBoxLayout(card)
        row.setContentsMargins(22, 16, 22, 16)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.percent = _label('')
        self.percent.setObjectName('trophyPercent')
        self.summary = _label('')
        self.summary.setObjectName('pageDescription')
        self.progress = QProgressBar()
        self.progress.setObjectName('trophyProgress')
        self.progress.setFixedSize(260, 4)
        self.progress.setTextVisible(False)
        left.addWidget(self.percent)
        left.addWidget(self.progress)
        left.addWidget(self.summary)
        row.addLayout(left)
        row.addStretch()
        self.grade_counts = {}
        for grade in trophies.GRADES:
            column = QVBoxLayout()
            column.setSpacing(4)
            icon = QLabel()
            icon.setPixmap(_trophy_icon(grade, True).pixmap(34, 34))
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count = _label('')
            count.setObjectName('pageDescription')
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(icon)
            column.addWidget(count)
            row.addLayout(column)
            self.grade_counts[grade] = count
        self.body.addWidget(card)
        self.filter = QComboBox(self)
        self.filter.hide()
        self.filter_buttons = {}
        tabs = QHBoxLayout()
        tabs.setSpacing(24)
        self.filter_group = QButtonGroup(self)
        for title, value in (('All', 'all'), ('Earned', 'earned'), ('Locked', 'locked')):
            self.filter.addItem(backend._(title), value)
            button = QPushButton()
            button.setObjectName('trophyTab')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=value:
                                   self.filter.setCurrentIndex(self.filter.findData(value)))
            self.filter_group.addButton(button)
            self.filter_buttons[value] = button
            tabs.addWidget(button)
        tabs.addStretch()
        self.body.addLayout(tabs)
        self.trophy_body = QWidget()
        self.trophy_layout = QVBoxLayout(self.trophy_body)
        self.trophy_layout.setContentsMargins(0, 0, 0, 0)
        self.trophy_layout.setSpacing(8)
        self.cards = {}
        self.body.addWidget(self.trophy_body)
        self.filter.currentIndexChanged.connect(self._render)
        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self, settings=None):
        super().refresh(settings if isinstance(settings, dict) else None)
        folder = backend.saves_folder(self.settings)
        if self.tracker is None or self.tracker.user_dir != folder:
            self.tracker = trophies.Tracker(folder)
            self._state = None
        self.tracker.poll()
        self._render()

    def _render(self):
        if self.tracker is None:
            return
        unlocked = self.tracker.unlocked
        state = (tuple(sorted(unlocked.items())), self.filter.currentData())
        if state == self._state:
            return
        self._state = state
        earned = sum(item[0] in unlocked for item in trophies.TROPHIES)
        self.summary.setText(backend._('{} of {} trophies earned').format(earned, len(trophies.TROPHIES)))
        percent = earned * 100 // len(trophies.TROPHIES)
        self.percent.setText(f'{percent}%')
        self.progress.setValue(percent)
        for grade, count in self.grade_counts.items():
            count.setText(f'{sum(item[0] in unlocked for item in trophies.TROPHIES if item[3] == grade)} / '
                          f'{sum(item[3] == grade for item in trophies.TROPHIES)}')
        while self.trophy_layout.count():
            self.trophy_layout.takeAt(0).widget().deleteLater()
        self.cards.clear()
        mode = self.filter.currentData()
        for index, (title, count) in enumerate((('All', len(trophies.TROPHIES)), ('Earned', earned),
                ('Locked', len(trophies.TROPHIES) - earned))):
            self.filter.setItemText(index, f'{backend._(title)}  {count}')
            button = self.filter_buttons[self.filter.itemData(index)]
            button.setText(f'{backend._(title)}   {count}')
            button.setChecked(self.filter.itemData(index) == mode)
        for group in (trophies.BASE, trophies.DLC):
            items = [item for item in trophies.TROPHIES if item[4] == group]
            heading = None
            for trophy_id, name, description, grade, _ in items:
                when = unlocked.get(trophy_id)
                if (mode == 'earned' and when is None) or (mode == 'locked' and when is not None):
                    continue
                if heading is None:
                    heading = QWidget()
                    heading_row = QHBoxLayout(heading)
                    heading_row.setContentsMargins(0, 8, 0, 0)
                    label = _label(group)
                    label.setObjectName('sectionHeading')
                    heading_row.addWidget(label)
                    count = _label(f'{sum(item[0] in unlocked for item in items)} / {len(items)}')
                    count.setObjectName('pageDescription')
                    heading_row.addWidget(count)
                    heading_row.addStretch()
                    self.trophy_layout.addWidget(heading)
                card = QGroupBox()
                row = QHBoxLayout(card)
                row.setContentsMargins(14, 10, 18, 10)
                row.setSpacing(14)
                icon = QLabel()
                icon.setPixmap(_trophy_icon(grade, when is not None).pixmap(46, 46))
                row.addWidget(icon)
                text = QVBoxLayout()
                title = _label(name)
                title.setObjectName('trophyName' if when is not None else 'lockedTrophyName')
                text.addWidget(title)
                detail = _label(description)
                detail.setObjectName('pageDescription')
                text.addWidget(detail)
                row.addLayout(text, 1)
                status = QVBoxLayout()
                grade_label = _label(backend._(*backend.GRADE_NAMES[grade]))
                grade_label.setStyleSheet(f'color: {backend.TROPHY_COLORS[grade] if when is not None else backend.MUTED}; font-size: 9pt; font-weight: 600;')
                date = _label(time.strftime('%d %b %Y', time.localtime(when)) if when is not None else backend._('Locked'))
                date.setObjectName('pageDescription')
                for label in (grade_label, date):
                    label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    status.addWidget(label)
                row.addLayout(status)
                self.cards[trophy_id] = card
                self.trophy_layout.addWidget(card)
        if not self.cards:
            self.trophy_layout.addWidget(_label('No trophies yet. They appear here as soon as the game unlocks them.'
                if mode == 'earned' else 'Every trophy is earned. Hail, good hunter.'))

    def observe(self, text):
        self.tracker.observe(text)
        self._render()

    def _saves_folder_gone(self):
        problem = backend.missing_saves_folder(self.settings)
        if problem:
            QMessageBox.critical(self, 'Bloodborne', problem)
        return bool(problem)

    def _ask(self, text):
        return QMessageBox.question(self, 'Bloodborne', text) == QMessageBox.StandardButton.Yes

    def import_trophies(self, folder=None):
        if self._searching or self._saves_folder_gone():
            return
        self._searching = True
        self.import_note.setText(backend._('Looking for achievements on this PC…'))
        target = Path(self.settings.get('user_dir') or backend.DATA_DIR / 'user') / trophies.LOG_NAME
        game = self.settings.get('game_dir', '')

        def work():
            records = (backend.saves.trophy_records_in(folder, [target]) if folder else
                       backend.saves.trophy_records(backend.PORT_DIR, game, [target]))
            return [(where, path, trophies.missing(trophies.read_unlocks(path), target)) for where, path in records]
        self._work(work, lambda found: self._offer_trophies([] if isinstance(found, Exception) else found, target, folder))

    def _offer_trophies(self, found, target, folder):
        self._searching = False
        self.import_note.setText(self.import_hint)
        have = trophies.read_log(target)
        found = [(where, path, unlocks) for where, path, unlocks in found if set(unlocks) - set(have)]
        if not found:
            text = (backend._('No achievements in {} that are not here yet.').format(folder) if folder else
                    backend._('No other installation on this PC has achievements that are not here yet.'))
            if self._ask(text + '\n\n' + backend._('Choose a folder to look in? An old port folder, a shadPS4 folder '
                                                    'or the drive of your old PC.')):
                chosen = QFileDialog.getExistingDirectory(self, backend._('Choose the folder with the achievements'),
                                                          str(Path.home()))
                if chosen:
                    self.import_trophies(Path(chosen))
            return
        lines = '\n'.join('• ' + backend._('{}: {} new here').format(where, len(set(unlocks) - set(have)))
                          + f'\n   {path}' for where, path, unlocks in found)
        if not self._ask(backend._('Achievements found:\n\n{}\n\nAdd them to yours? Your trophies.log is copied '
                                   'first, and no trophy is removed.').format(lines)):
            return
        union = {}
        for _where, _path, unlocks in found:
            for trophy, when in unlocks.items():
                union[trophy] = min(when, union.get(trophy, when))
        if self._saves_folder_gone():  # its drive went away during the search
            return
        try:
            if not self.settings.get('user_dir'):
                target.parent.mkdir(parents=True, exist_ok=True)
            added, copy = trophies.add_unlocks(union, target)
        except OSError as error:
            QMessageBox.critical(self, 'Bloodborne', backend._('Could not add the achievements: {}').format(error))
            return
        if self.tracker is not None and Path(self.tracker.user_dir) == target.parent:
            self.tracker.refresh_log()
            self.tracker.award_platinum()
            self._render()
        done = backend._('Achievements added: {} new.').format(added)
        if copy:
            done += '\n\n' + backend._('Your previous list is kept as {}.').format(copy)
        QMessageBox.information(self, 'Bloodborne', done)


def _detect_hardware(settings):
    # Reuse the existing Vulkan probe without its Tk callbacks.
    ignored = lambda: None
    state = SimpleNamespace(app=dict(settings), ui_calls=queue.Queue(), refresh_status=ignored,
        hardware_ready=ignored, refresh_fg401=ignored, refresh_fsr411=ignored)
    backend.Launcher.detect_gpu(state)
    return state.gpu_line, state.cpu, state.ram


class SystemPage(_Page):
    rating_changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        self.gpu_line, self.cpu, self.ram, self.rating = '', None, 0, None
        self._checking = False
        _, form = self._card('Your PC')
        self.status = _label('Checking your PC…')
        form.addRow(self.status)
        self.override = QComboBox()
        self.override.addItem(backend._('Detected automatically'), '')
        for gpu in hardware.GPU_LIST:
            self.override.addItem(gpu.label, gpu.id)
        self.override.setObjectName('gpu_override')
        self.fields['gpu_override'] = self.override
        form.addRow(backend._('Wrong graphics card?'), self.override)
        self.check_button = self._button(form, 'Check again', self.check_hardware)
        self.rating_text = _label('')
        form.addRow(self.rating_text)
        self._button(form, 'Settings for your PC', lambda: self.page_requested.emit('picture'))
        _, req = self._card('System requirements')
        self.requirements = QTreeWidget()
        self.requirements.setHeaderLabels(['', *(backend._(head) for head in hardware.REQUIREMENT_HEADS), backend._('Your PC')])
        self.requirements.setRootIsDecorated(False)
        self.requirements.setWordWrap(True)
        self.requirements.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            self.requirements.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.requirements.setMinimumHeight(260)
        req.addRow(self.requirements)
        req.addRow(_label(hardware.FOUR_K))
        _, limits = self._card('Hard limits')
        for text in hardware.HARD_LIMITS:
            limits.addRow(_label(text))
        _, drivers = self._card('Driver notes')
        for text in hardware.DRIVER_NOTES:
            drivers.addRow(_label(text))
        self._button(drivers, 'Install guide and FAQ on bbport.de', lambda: _open(backend.COMMUNITY_SITE + 'install/'))
        self.override.currentIndexChanged.connect(self._render)
        self.refresh()
        QTimer.singleShot(0, self, self.check_hardware)

    def var(self, key, _store='app'):
        return SimpleNamespace(get=lambda: self.override.currentData() if key == 'gpu_override' else self.settings.get(key, ''),
            set=lambda _value: self.override.setCurrentIndex(0))

    def detected_gpu(self):
        return setup.SetupMixin.detected_gpu(self)

    def refresh(self, settings=None):
        super().refresh(settings)
        self._render()

    def check_hardware(self):
        if self._checking:
            return
        self._checking = True
        self.check_button.setEnabled(False)
        self.status.setText(backend._('Checking your PC…'))
        values = dict(self.settings)

        def done(result):
            self._checking = False
            self.check_button.setEnabled(True)
            if isinstance(result, Exception):
                self.status.setText(backend._('The check stopped: {}').format(result))
                return
            self.gpu_line, self.cpu, self.ram = result
            self._render()
        self._work(lambda: _detect_hardware(values), done)

    def _render(self):
        gpu = self.detected_gpu()[0]
        self.rating = hardware.assess(gpu, self.cpu, self.ram, tr=backend._) if gpu and self.cpu else None
        if self.cpu:
            self.status.setText(f'{self.gpu_line or backend._("Graphics card: not detected")}\n{self.cpu.name}\n{self.ram} GB RAM')
        elif not self._checking:
            self.status.setText(backend._('Hardware has not been checked.'))
        if self.rating:
            rating = self.rating
            self.rating_text.setText(f'{rating.tier_label}\n{rating.summary}\n\n' + '\n'.join(
                f'{res}: {label} - {settings}' for res, _level, label, settings in rating.rows) + '\n\n' +
                '\n'.join(text for _state, _part, text in rating.checks) + '\n\n' + '\n'.join(rating.notes))
        else:
            self.rating_text.setText(backend._('No rating is available until the graphics card and processor are identified.'))
        yours = setup.SetupMixin.your_pc(self)
        self.requirements.clear()
        for part, low, high in hardware.REQUIREMENTS:
            self.requirements.addTopLevelItem(QTreeWidgetItem([backend._(part), backend._(low), backend._(high), yours.get(part, (None, '…'))[1]]))
        self.rating_changed.emit()

    def diagnostics(self):
        return '\n'.join([f'Bloodborne PC port launcher v{backend.VERSION}', platform.platform(),
            f'GPU: {self.gpu_line or "not detected"}', f'CPU: {self.cpu.name if self.cpu else "not detected"}',
            f'RAM: {self.ram} GB', f'Rating: {self.rating.tier_label if self.rating else "not available"}'])


class HelpPage(_Page):
    checks_finished = Signal(object)
    def __init__(self, settings, parent=None):
        super().__init__(settings, parent)
        self.results = []
        self._checking = False
        self._eboot = settings.get('eboot_check')
        self._initial_eboot = dict(self._eboot or {})
        self._generation = 0
        _, checks = self._card('')
        checks.setContentsMargins(22, 16, 22, 16)
        head = QHBoxLayout()
        title = _label('Check this installation')
        title.setObjectName('sectionHeading')
        head.addWidget(title, 1)
        self.check_button = QPushButton(backend._('Check again'))
        self.check_button.clicked.connect(self.check_installation)
        head.addWidget(self.check_button)
        checks.addRow(head)
        self.check_result = _label('Checking the game files…')
        checks.addRow(self.check_result)
        self.fix_links = QWidget()
        self.fix_layout = QHBoxLayout(self.fix_links)
        self.fix_layout.setContentsMargins(0, 0, 0, 0)
        checks.addRow(self.fix_links)
        self._files_running = False
        self.files_button = self._key_button('button:game_files', 'Check the game files', self.check_game_files)
        self.files_note = _label('Compares every file with the clean 1.09 (a few minutes).')
        self.files_note.setObjectName('pageDescription')
        checks.addRow(_row(self.files_button, self.files_note)[0])
        hint = 'For a black screen, or a broken picture after a driver update. The next start stutters for a few minutes.'
        cache_button = self._key_button('button:shader_cache', 'Clear the shader cache', self.clear_cache)
        self.cache_buttons = [cache_button]
        checks.addRow(_row(cache_button, _hint(hint))[0])
        version_row = QHBoxLayout()
        # Updates and other versions are installed by the Windows launcher only.
        for key, title in (('button:updates', 'Check for updates'), ('button:versions', 'Other versions…')):
            button = self._key_button(key, title, lambda: _open(backend.RELEASES_PAGE))
            button.setEnabled(os.name == 'nt')
            version_row.addWidget(button)
        installed = _label(backend._('Installed: v{}').format(backend.VERSION_TEXT))
        installed.setObjectName('pageDescription')
        version_row.addWidget(installed)
        version_row.addStretch()
        checks.addRow(version_row)
        for text, key, title, callback in (
                ('Set everything up again, step by step.', 'helpLink', 'Repeat the setup',
                 lambda: self.page_requested.emit('setup')),
                ('What changed in this version, and what to know.', 'button:news', "What's new", self.open_news)):
            link_row = QHBoxLayout()
            link_row.addWidget(_label(text))
            button = QPushButton(backend._(title) + '  ›')
            button.setObjectName(key)
            if key != 'helpLink':  # the theme styles links by objectName, and the search needs this one's key
                button.setStyleSheet(f'background: transparent; border: none; color: {backend.theme.GOLD_LIGHT}; '
                                     'text-align: left; padding: 0;')
            button.clicked.connect(callback)
            link_row.addWidget(button)
            link_row.addStretch()
            self.body.addLayout(link_row)
        self._section('Problems and their fixes')
        self.topics = {}
        self.topic_bodies = {}
        for key in help_service.TOPIC_ORDER:
            title, explanation, steps = help_service.TOPICS[key]
            card, container = self._card('')
            card.setObjectName('helpTopicCard')
            container.setContentsMargins(18, 8, 18, 8)
            container.setVerticalSpacing(0)
            toggle = QPushButton('›  ' + help_service._(title))
            toggle.setObjectName('helpTopic')
            toggle.setCheckable(True)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            container.addRow(toggle)
            details = QWidget()
            form = QFormLayout(details)
            form.setContentsMargins(34, 8, 0, 6)
            container.addRow(details)
            details.hide()
            toggle.toggled.connect(details.setVisible)
            toggle.toggled.connect(lambda checked, toggle=toggle, title=title:
                toggle.setText(('⌄  ' if checked else '›  ') + help_service._(title)))
            self.topic_bodies[key] = (toggle, details)
            self.topics[key] = card
            form.addRow(_label(explanation))
            for number, step in enumerate(steps, 1):
                form.addRow(_label(f'{number}. {help_service._(step)}'))
            for title, action in help_service.TOPIC_ACTIONS.get(key, []):
                button = self._button(form, title, lambda _checked=False, action=action: self._action(action))
                if action == 'clear_cache':
                    self.cache_buttons.append(button)
        self._section('Still stuck?')
        _, support = self._card('')
        support.addRow(_label('Only with your own copy of the game'))
        support.addRow(_label("The port does not come with the game, and we can't give out game files or help anyone find them. Asking for them or sharing them breaks rule 2 of the community Discord and can get you banned."))
        support.addRow(_label('Ask in Help & Support on forum.bbport.de: start a new topic. Save a report and attach it: it has the log, your settings and this PC\'s details (no passwords), so a helper sees the cause at once.'))
        for actions in ((('button:report', 'Save a report', self.save_report),
                         ('button:copy_summary', 'Copy a summary', self.copy_summary),
                         ('button:forum', 'Open the forum', lambda: _open(help_service.FORUM_HELP))),
                        (('button:show_log', 'Show the log', lambda: self.page_requested.emit('log')),
                         ('button:discord', 'Open the Discord', lambda: _open(help_service.DISCORD)))):
            row = QHBoxLayout()
            for key, title, callback in actions:
                row.addWidget(self._key_button(key, title, callback))
            row.addStretch()
            support.addRow(row)
        self.report_note = _label('')
        support.addRow(self.report_note)
        QTimer.singleShot(0, self, self.check_installation)

    @staticmethod
    def _key_button(key, title, callback):
        button = QPushButton(backend._(title))
        button.setObjectName(key)
        button.clicked.connect(callback)
        return button

    def _section(self, title):
        row = QHBoxLayout()
        label = _label(title)
        label.setObjectName('sectionTitle')
        row.addWidget(label)
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f'background: {backend.theme.BORDER};')
        row.addWidget(line, 1)
        self.body.addLayout(row)

    def refresh(self, settings=None):
        super().refresh(settings)
        self._eboot = self.settings.get('eboot_check', self._eboot)
        self._initial_eboot = dict(self._eboot or {})
        self._generation += 1

    def save(self):
        if self._eboot and self._eboot != self._initial_eboot:
            self.settings['eboot_check'] = self._eboot
            self._initial_eboot = dict(self._eboot)

    def check_installation(self):
        if self._checking:
            return
        self._checking = True
        generation = self._generation
        self.check_button.setEnabled(False)
        self.check_result.setText(backend._('Checking the game files…'))
        values = dict(self.settings)
        cached = self._eboot

        def check():
            graphics, _ = backend.load_ini(values)
            return help_service.run_checks(values.get('game_dir', ''), values.get('mods_dir') or backend.DATA_DIR / 'mods',
                backend.PORT_DIR, graphics['output_res'], cached)

        def done(result):
            self._checking = False
            self.check_button.setEnabled(True)
            if generation != self._generation:
                self.check_installation()
                return
            if isinstance(result, Exception):
                self.results = [('warn', None, backend._('The check stopped: {}').format(result))]
            else:
                self.results, self._eboot = result
            self.check_result.setText('\n\n'.join(f'[{state}] {text}' for state, _topic, text in self.results))
            self.checks_finished.emit(self.results)
            while self.fix_layout.count():
                self.fix_layout.takeAt(0).widget().deleteLater()
            for key in dict.fromkeys(topic for _state, topic, _text in self.results if topic in self.topics):
                button = QPushButton(backend._('How to fix') + ': ' + help_service._(help_service.TOPICS[key][0]))
                button.clicked.connect(lambda _checked=False, key=key: self.open_topic(key))
                self.fix_layout.addWidget(button)
            for key, card in self.topics.items():
                card.setProperty('problemDetected', any(topic == key for _state, topic, _text in self.results))
        self._work(check, done)

    def open_topic(self, key):
        toggle, _body = self.topic_bodies[key]
        toggle.setChecked(True)
        QTimer.singleShot(0, self, lambda: self.ensureWidgetVisible(self.topics[key], 0, 20))

    def _action(self, action):
        pages = {'choose_game_page': 'game', 'open_backups': 'saves', 'open_controller_test': 'controls'}
        if action in pages:
            self.page_requested.emit(pages[action])
        elif action == 'open_game_folder':
            if self.settings.get('game_dir'):
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings['game_dir']))
        elif action == 'open_port_folder':
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(backend.PORT_DIR)))
        elif action == 'clear_cache':
            self.clear_cache()
        elif action == 'open_memory_settings':
            help_service.HelpMixin.open_memory_settings(self)
        elif action == 'open_windows_security':
            help_service.HelpMixin.open_windows_security(self)

    def clear_cache(self):
        if self.running:
            return
        state = SimpleNamespace(process=None, app=self.settings, messagebox=SimpleNamespace(
            showinfo=lambda title, text: QMessageBox.information(self, title, text)))
        backend.Launcher.clear_cache(state)

    def check_game_files(self):
        if self._files_running:
            return
        game = self.settings.get('game_dir', '')
        self.files_note.setStyleSheet('')
        if not game or not (Path(game) / 'dvdroot_ps4').is_dir():
            self.files_note.setText(backend._('No game folder chosen yet.'))
            return
        self._files_running = True
        self.files_button.setEnabled(False)
        self.files_note.setText(backend._('Checking the game files… {}%').format(0))
        shown = [0]

        def progress(done, total):
            percent = int(done * 100 / max(1, total))
            if percent != shown[0]:
                shown[0] = percent
                self._done.emit(lambda value: self.files_note.setText(
                    backend._('Checking the game files… {}%').format(value)), percent)

        def work():
            import game_files
            return game_files.check(game, progress)

        def done(result):
            self._files_running = False
            self.files_button.setEnabled(True)
            if isinstance(result, Exception):
                self.files_note.setText(backend._('The check stopped: {}').format(result))
                return
            bad = result['differ'] + result['missing']
            if bad:
                self.files_note.setText(backend._('{0} of {1} game files differ from the clean 1.09 or are missing, '
                    'for example: {2}. See "Game files are damaged" below.').format(help_service.number(len(bad)),
                    help_service.number(result['checked']), ', '.join(bad[:3])))
                self.files_note.setStyleSheet(f'color: {backend.theme.AMBER};')
            else:
                self.files_note.setText(backend._('All {} game files are those of the clean 1.09.').format(
                    help_service.number(result['checked'])))
        self._work(work, done)

    def open_news(self):
        self.settings['seen_version'] = backend.VERSION_TEXT
        news = backend.bbport_news.notes(backend.VERSION_TEXT)
        if news is None:
            _open(backend.BETA_PAGE if backend.BETA else backend.RELEASES_PAGE)
            return
        notice, sections = news
        text = [backend.bbport_news._(notice)] if notice else []
        for section, changes in sections:
            text.append(backend.bbport_news._(section) + '\n' + '\n'.join('• ' + backend.bbport_news._(change)
                                                                         for change in changes))
        QMessageBox.information(self, backend._("What's new"),
                                backend._('Version {}').format(backend.VERSION_TEXT) + '\n\n' + '\n\n'.join(text))

    def diagnostics(self):
        window = self.window()
        system = getattr(window, 'system_page', None)
        text = system.diagnostics() if system is not None else f'Bloodborne PC port launcher v{backend.VERSION}\n{platform.platform()}'
        return text + '\n\nChecks:\n' + '\n'.join(f'[{state}] {text}' for state, _topic, text in self.results)

    def copy_summary(self):
        QApplication.clipboard().setText(self.diagnostics())
        self.report_note.setText(backend._('Copied: paste it into your message on Discord or in the forum.'))

    def save_report(self):
        filename, _ = QFileDialog.getSaveFileName(self, backend._('Save a report'),
            str(Path.home() / time.strftime('bbport-report-%Y%m%d-%H%M%S.zip')), 'ZIP (*.zip)')
        if not filename:
            return
        values = dict(self.settings)
        summary = self.diagnostics()

        def write():
            with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as report:
                report.writestr('summary.txt', summary)
                report.writestr('settings.json', json.dumps(help_service.private_free(values), indent=2, ensure_ascii=False))
                ini = backend.ini_path()
                if ini.is_file():
                    report.write(ini, 'bbport.ini')
                log = backend.saves_folder(values) / 'last_run.log'
                if log.is_file():
                    report.write(log, 'last_run.log')
            return backend._('Saved: {}').format(filename)

        self._work(write, lambda result: self.report_note.setText(str(result)))

    def set_game_running(self, running):
        super().set_game_running(running)
        for button in self.cache_buttons:
            button.setEnabled(not running)

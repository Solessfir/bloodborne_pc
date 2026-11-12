# SPDX-License-Identifier: GPL-2.0-or-later
"""Qt Controls page using the game's existing input.ini editor and SDL controller reader."""
import os
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget)

import bbport_gamepad
import bbport_input_config as inputs
import bbport_launcher_win as backend
import bbport_pad
import bbport_pad_art


def key_name(event):
    """Qt's key symbols follow the same layout as Tk; native symbols distinguish sides."""
    native = {0xffe1: 'lshift', 0xffe2: 'rshift', 0xffe3: 'lctrl', 0xffe4: 'rctrl',
              0xffe9: 'lalt', 0xffea: 'ralt', 0xffeb: 'lwin', 0xffec: 'rwin',
              0xa0: 'lshift', 0xa1: 'rshift', 0xa2: 'lctrl', 0xa3: 'rctrl',
              0xa4: 'lalt', 0xa5: 'ralt'}
    if event.nativeVirtualKey() in native:
        return native[event.nativeVirtualKey()]
    key = event.key()
    names = {Qt.Key.Key_Escape: 'escape', Qt.Key.Key_Backspace: 'backspace',
        Qt.Key.Key_Delete: 'delete', Qt.Key.Key_Insert: 'insert', Qt.Key.Key_Home: 'home',
        Qt.Key.Key_End: 'end', Qt.Key.Key_PageUp: 'pgup', Qt.Key.Key_PageDown: 'pgdown',
        Qt.Key.Key_Tab: 'tab', Qt.Key.Key_Backtab: 'tab', Qt.Key.Key_CapsLock: 'capslock',
        Qt.Key.Key_Return: 'enter', Qt.Key.Key_Enter: 'kpenter',
        Qt.Key.Key_Shift: 'lshift', Qt.Key.Key_Control: 'lctrl', Qt.Key.Key_Alt: 'lalt',
        Qt.Key.Key_AltGr: 'ralt', Qt.Key.Key_Meta: 'lwin', Qt.Key.Key_Space: 'space',
        Qt.Key.Key_Up: 'up', Qt.Key.Key_Down: 'down', Qt.Key.Key_Left: 'left',
        Qt.Key.Key_Right: 'right', Qt.Key.Key_QuoteLeft: 'grave', Qt.Key.Key_Minus: 'minus',
        Qt.Key.Key_Equal: 'equals', Qt.Key.Key_BracketLeft: 'lbracket',
        Qt.Key.Key_BracketRight: 'rbracket', Qt.Key.Key_Backslash: 'backslash',
        Qt.Key.Key_Semicolon: 'semicolon', Qt.Key.Key_Apostrophe: 'apostrophe',
        Qt.Key.Key_Comma: 'comma', Qt.Key.Key_Period: 'period', Qt.Key.Key_Slash: 'slash',
        Qt.Key.Key_Print: 'printscreen', Qt.Key.Key_ScrollLock: 'scrolllock',
        Qt.Key.Key_Pause: 'pausebreak'}
    if event.modifiers() & Qt.KeyboardModifier.KeypadModifier:
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return f'kp{key - Qt.Key.Key_0}'
        return {Qt.Key.Key_Period: 'kpperiod', Qt.Key.Key_Comma: 'kpcomma',
                Qt.Key.Key_Slash: 'kpslash', Qt.Key.Key_Asterisk: 'kpasterisk',
                Qt.Key.Key_Minus: 'kpminus', Qt.Key.Key_Plus: 'kpplus',
                Qt.Key.Key_Equal: 'kpequals', Qt.Key.Key_Enter: 'kpenter',
                Qt.Key.Key_Return: 'kpenter'}.get(key)
    if key in names:
        return names[key]
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key).lower()
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        return f'f{key - Qt.Key.Key_F1 + 1}'
    shifted = {'!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7',
               '*': '8', '(': '9', ')': '0', '_': 'minus', '+': 'equals',
               '{': 'lbracket', '}': 'rbracket', '|': 'backslash', ':': 'semicolon',
               '"': 'apostrophe', '<': 'comma', '>': 'period', '?': 'slash', '~': 'grave'}
    return shifted.get(event.text())


class DevicePages(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages, self.current = [], None
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, page):
        self.pages.append(page)
        self.body.addWidget(page)
        page.hide()

    def currentWidget(self):
        return self.current

    def setCurrentWidget(self, page):
        # A normal layout ignores hidden pages, including their height-for-width constraints.
        self.current = page
        for child in self.pages:
            child.setVisible(child is page)
        self.body.invalidate()
        self.updateGeometry()
        self.currentChanged.emit(self.pages.index(page))


class ControlsPage(QWidget):
    changed = Signal()
    help_requested = Signal(str)

    def __init__(self, settings, ini_path, parent=None):
        super().__init__(parent)
        self.settings, self.ini_path = settings, Path(ini_path)
        self.initial_preferences = {key: settings.get(key, default) for key, default in
                                    [('play_with', 'keyboard'), ('button_prompts', 'auto'),
                                     ('menu_key', 'Insert'), ('menu_pad', 'l3+r3')]}
        self.app_keys, self.ini_keys = {'play_with', 'menu_key', 'menu_pad'}, {'button_prompts'}
        self.setting_widgets = {}
        self.edits, self.controller_edits, self.mouse_edits = {}, {}, {}
        self.capture = None
        self.modifiers = []
        self.reader = None
        self.pad_state = None
        self.pad_kind = 'playstation'
        self.game_running = False
        self.message_open = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.poll_pads)
        self.load()
        self.setObjectName('settingsPage')
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(32, 18, 32, 24)
        self.body.setSpacing(10)
        form = QFormLayout()
        devices = QWidget()
        devices.setObjectName('play_with')
        self.setting_widgets['play_with'] = devices
        device_row = QHBoxLayout(devices)
        device_row.setContentsMargins(0, 0, 0, 0)
        self.device_group = QButtonGroup(self)
        self.devices = {}
        for value, text in [('controller', 'Controller'), ('keyboard', 'Keyboard and mouse')]:
            button = QPushButton(backend._(text))
            button.setCheckable(True)
            button.setChecked(settings.get('play_with', 'keyboard') == value)
            button.clicked.connect(lambda _checked=False, v=value: self.set_play_with(v))
            self.device_group.addButton(button)
            self.devices[value] = button
            device_row.addWidget(button)
        device_row.addStretch()
        form.addRow(backend._('You play with'), devices)
        devices.setToolTip(backend._('Keyboard and mouse turns the mouse camera on and uses the Dark Souls III layout (asked first if you changed keys yourself). Controller turns the mouse camera off, so the game leaves the pointer alone. Keys and controller buttons keep working either way.'))
        device_hint = QLabel(devices.toolTip())
        device_hint.setWordWrap(True)
        device_hint.setObjectName('pageDescription')
        form.addRow('', device_hint)
        self.prompts = QComboBox()
        self.prompts.setObjectName('button_prompts')
        self.prompts.setMaximumWidth(390)
        self.setting_widgets['button_prompts'] = self.prompts
        for value, label in backend.PROMPT_MODES:
            self.prompts.addItem(backend._(*label), value)
        prompt = settings.get('button_prompts', 'auto')
        if self.prompts.findData(prompt) < 0:
            self.prompts.addItem(str(prompt), prompt)
        self.prompts.setCurrentIndex(self.prompts.findData(prompt))
        self.prompts.currentIndexChanged.connect(self.set_prompts)
        self.prompts.setToolTip(backend._("The game's button icons: your keyboard and mouse keys while you play with them, the controller's (PlayStation, Xbox or Switch) while you use it."))
        form.addRow(backend._('Button prompts', 'Подсказки кнопок'), self.prompts)
        prompts_hint = QLabel(self.prompts.toolTip())
        prompts_hint.setWordWrap(True)
        prompts_hint.setObjectName('pageDescription')
        form.addRow('', prompts_hint)
        self.menu_boxes = {}
        for key, title, options, hint in [
                ('menu_key', 'In-game menu key', backend.MENU_KEYS, 'Opens the settings menu during play. No key: the menu only opens with the controller, or not at all; the launcher has every setting either way. A key you move the menu off can be bound to the game.'),
                ('menu_pad', 'In-game menu on the controller', backend.MENU_PADS, 'Off if pressing both sticks or Select + Start opens it by accident.')]:
            box = QComboBox()
            box.setObjectName(key)
            box.setMaximumWidth(390)
            self.setting_widgets[key] = box
            self.menu_boxes[key] = box
            for value, label in options:
                box.addItem(backend._(*label), value)
            self.show_menu_choice(key, settings.get(key))
            box.currentIndexChanged.connect(lambda _index, k=key: self.set_menu_choice(k))
            box.setToolTip(backend._(hint))
            form.addRow(backend._(title), box)
            menu_hint = QLabel(box.toolTip())
            menu_hint.setWordWrap(True)
            menu_hint.setObjectName('pageDescription')
            form.addRow('', menu_hint)
        self.body.addLayout(form)
        self.tabs = DevicePages()
        self.tabs.currentChanged.connect(self.tabs.updateGeometry)
        self.body.addWidget(self.tabs)
        self.controller_page, self.keyboard_page = QWidget(), QWidget()
        self.controller_body = QVBoxLayout(self.controller_page)
        self.keyboard_body = QVBoxLayout(self.keyboard_page)
        for layout in (self.controller_body, self.keyboard_body):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tabs.addWidget(self.controller_page)
        self.tabs.addWidget(self.keyboard_page)
        self.build_controller()
        self.build_keyboard()
        self.tabs.setCurrentWidget(self.controller_page if settings.get('play_with') == 'controller' else self.keyboard_page)
        self.body.addStretch()
        QApplication.instance().installEventFilter(self)

    def read_lines(self):
        try:
            return self.ini_path.read_text(encoding='utf-8').splitlines()
        except FileNotFoundError:
            return inputs.DEFAULT_INPUT_INI.splitlines()

    def load(self):
        self.bindings, self.lines, self.toggle_key, self.reload_key, self.mouse = inputs.read_input_lines(self.read_lines())
        self.controllers = inputs.load_controller_bindings(self.lines)

    def section(self, layout, text):
        row = QHBoxLayout()
        label = QLabel(text)
        label.setObjectName('sectionTitle')
        row.addWidget(label)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet('color: #25272b;')
        row.addWidget(line, 1)
        layout.addLayout(row)

    def note(self, layout, text):
        label = QLabel(text)
        label.setObjectName('pageDescription')
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def set_prompts(self, _index):
        self.settings['button_prompts'] = self.prompts.currentData()
        self.changed.emit()

    def show_menu_choice(self, key, value):
        # Like the Tk choice: a value it does not offer becomes the first one, and is saved as such.
        box = self.menu_boxes[key]
        blocked = box.blockSignals(True)
        box.setCurrentIndex(max(0, box.findData(value)))
        box.blockSignals(blocked)
        self.settings[key] = box.currentData()

    def set_menu_choice(self, key):
        self.settings[key] = self.menu_boxes[key].currentData()
        self.changed.emit()

    def ini_values(self):
        return {'button_prompts': self.prompts.currentData()} if self.prompts.currentData() != self.initial_preferences['button_prompts'] else {}

    def app_values(self):
        values = {'play_with': self.settings.get('play_with', 'keyboard'),
                  **{key: box.currentData() for key, box in self.menu_boxes.items()}}
        return {key: value for key, value in values.items() if value != self.initial_preferences[key]}

    def preferences_saved(self):
        self.initial_preferences.update(play_with=self.settings.get('play_with', 'keyboard'),
                                        button_prompts=self.prompts.currentData(),
                                        **{key: box.currentData() for key, box in self.menu_boxes.items()})

    def refresh_preferences(self, settings, graphics):
        device = settings.get('play_with') or 'controller'
        self.settings['play_with'] = device
        for key, button in self.devices.items():
            button.setChecked(key == device)
        self.tabs.setCurrentWidget(self.controller_page if device == 'controller' else self.keyboard_page)
        prompt = graphics.get('button_prompts', 'auto')
        blocked = self.prompts.blockSignals(True)
        if self.prompts.findData(prompt) < 0:
            self.prompts.addItem(str(prompt), prompt)
        self.prompts.setCurrentIndex(self.prompts.findData(prompt))
        self.prompts.blockSignals(blocked)
        self.settings['button_prompts'] = prompt
        for key in self.menu_boxes:
            self.show_menu_choice(key, settings.get(key))
        self.preferences_saved()

    def build_keyboard(self):
        layout = self.keyboard_body
        preset = QPushButton(backend._('Use the Dark Souls III layout', 'Раскладка Dark Souls III'))
        preset.setObjectName('mouse:layout')
        self.setting_widgets['mouse:layout'] = preset
        preset.clicked.connect(self.apply_layout_preset)
        layout.addWidget(preset, alignment=Qt.AlignmentFlag.AlignLeft)
        preset.setToolTip(backend._('WASD, Space to dodge, left click / Shift + left click to attack, right click / Shift + right click (or Ctrl) for the off hand, E interact, R item, F vial, Q lock on, Tab or Esc menu, and the 1:1 mouse camera. Replaces the keyboard and mouse bindings; the controller keeps its own.'))
        self.section(layout, backend._('Mouse look', 'Обзор мышью'))
        self.mouse_widgets = {}
        enabled = QCheckBox(backend._('Enable mouse look', 'Включить обзор мышью'))
        enabled.setObjectName('mouse:enabled')
        self.setting_widgets['mouse:enabled'] = enabled
        enabled.setChecked(self.mouse['enabled'])
        enabled.toggled.connect(lambda value: self.set_mouse('enabled', value))
        self.mouse_widgets['enabled'] = enabled
        layout.addWidget(enabled)
        toggle, reload = inputs.display_name(self.toggle_key), inputs.display_name(self.reload_key)
        self.note(layout, backend._('F7 also toggles this in-game, instantly; F8 reloads these settings without restarting.', 'F7 также переключает это прямо в игре мгновенно; F8 применяет эти настройки без перезапуска.').replace('F7', '{toggle}').replace('F8', '{reload}').format(toggle=toggle, reload=reload))
        form = QFormLayout()
        self.mouse_form = form
        self.mouse_choice(form, 'stick', backend._('Mouse controls', 'Мышь управляет'),
                          [('right', backend._('Camera (right stick)', 'Камера (правый стик)')),
                           ('left', backend._('Movement (left stick)', 'Движение (левый стик)'))])
        self.mouse_choice(form, 'camera', backend._('Camera', 'Камера'),
                          [('direct', backend._('Direct (1:1, like a PC game)', 'Прямая (1:1, как в ПК-играх)')),
                           ('stick', backend._('Stick emulation', 'Эмуляция стика'))])
        self.mouse_widgets['camera'].setToolTip(backend._("Direct turns the game's camera by exact angles: no stick acceleration or turn-speed cap. While locked on, moving the mouse switches target."))
        for key, title, hint, lo, hi in [
            ('camera_sensitivity', 'Sensitivity (direct)', 'How far the direct camera turns per mouse movement (1.00 = 900 counts per radian).', 0.1, 5.0),
            ('speed', 'Sensitivity (stick)', 'How fast the camera turns for a given mouse movement in stick emulation.', 0.1, 5.0),
            ('speed_offset', 'Minimum turn speed (stick)', 'A constant added on top of sensitivity; raises the floor for slow movements without affecting fast ones as much.', 0.0, 1.0),
            ('sensitivity_y', 'Vertical sensitivity', 'Up and down as a multiple of left and right (1.00 = the same).', 0.1, 3.0)]:
            holder = QWidget()
            holder.setMaximumWidth(440)
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(round(lo * 1000), round(hi * 1000))
            slider.setValue(round(self.mouse[key] * 1000))
            slider.setMinimumWidth(190)
            value = QDoubleSpinBox()
            value.setDecimals(3)
            value.setRange(min(lo, self.mouse[key]), max(hi, self.mouse[key]))
            value.setSingleStep(0.01)
            value.setValue(self.mouse[key])
            slider.valueChanged.connect(lambda v, w=value: w.setValue(v / 1000))
            value.valueChanged.connect(lambda v, s=slider: self.sync_slider(s, v))
            value.valueChanged.connect(lambda v, k=key: self.set_mouse(k, v))
            self.mouse_widgets[key] = value
            value.setObjectName('mouse:' + key)
            self.setting_widgets['mouse:' + key] = value
            row.addWidget(slider, 1)
            row.addWidget(value)
            holder.setToolTip(backend._(hint))
            form.addRow(backend._(title), holder)
        layout.addLayout(form)
        for key, text in [('invert_x', backend._('Invert horizontal', 'Инвертировать по горизонтали')),
                          ('invert_y', backend._('Invert vertical', 'Инвертировать по вертикали'))]:
            check = QCheckBox(text)
            check.setChecked(self.mouse[key])
            check.toggled.connect(lambda value, k=key: self.set_mouse(k, value))
            self.mouse_widgets[key] = check
            check.setObjectName('mouse:' + key)
            self.setting_widgets['mouse:' + key] = check
            layout.addWidget(check)
        self.show_camera_mode()
        self.note(layout, backend._('Vertical sensitivity and inverting apply to both camera modes.'))
        self.note(layout, backend._('Mouse buttons and the scroll wheel are bound in the slots below: click a slot, then click or turn the wheel. They work while the mouse is captured (mouse look on).'))
        self.note(layout, backend._('Changes apply the next time the game starts, or press {} in-game to reload input.ini without restarting.').format(reload))
        self.note(layout, backend._('Click a slot, then press a key, click a mouse button or turn the wheel; Esc cancels. Right-click a slot to clear it. Movement and camera directions take keys only.'))
        self.remap_rows = self.binding_table(layout, False)
        fold = QPushButton(backend._('Key combinations and reserved keys') + '  ›')
        fold.setCheckable(True)
        layout.addWidget(fold, alignment=Qt.AlignmentFlag.AlignLeft)
        details = self.note(layout, backend._('Combinations: hold Shift, Ctrl or Alt while pressing the key or mouse button (up to three inputs, such as Shift + left click). A held combination wins over the bindings on its parts, so left click and Shift + left click can be two actions. ⚠ marks an input another action uses too. A key that is both an action of its own and part of a combination is pressed on the way into it: with Shift on Circle, Shift + left click starts a sprint that ends as a dodge.') + '\n\n' + backend._('Reserved: Insert (the port\'s menu), F9 (route recording), and whichever key toggles mouse look or reloads input.ini ({} / {} currently). Esc cancels capture.').format(toggle, reload))
        details.hide()
        fold.toggled.connect(details.setVisible)
        self.refresh_bindings()

    @staticmethod
    def sync_slider(slider, value):
        slider.blockSignals(True)
        slider.setValue(round(value * 1000))
        slider.blockSignals(False)

    def mouse_choice(self, form, key, title, options):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(holder)
        for value, text in options:
            button = QRadioButton(text)
            button.setProperty('value', value)
            button.setChecked(self.mouse[key] == value)
            button.toggled.connect(lambda checked, k=key, v=value: checked and self.set_mouse(k, v))
            group.addButton(button)
            row.addWidget(button)
        row.addStretch()
        holder.group = group
        self.mouse_widgets[key] = holder
        holder.setObjectName('mouse:' + key)
        self.setting_widgets['mouse:' + key] = holder
        form.addRow(title, holder)

    def set_mouse(self, key, value):
        self.mouse[key] = value
        self.mouse_edits[key] = value
        if key == 'camera':
            self.show_camera_mode()
        self.changed.emit()

    def show_camera_mode(self):
        for key in ('camera_sensitivity', 'speed', 'speed_offset'):
            widget = self.mouse_widgets.get(key)
            if widget:
                self.mouse_form.setRowVisible(widget.parentWidget(), (key == 'camera_sensitivity') == (self.mouse['camera'] == 'direct'))

    def sync_mouse_widgets(self):
        for key, widget in self.mouse_widgets.items():
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(self.mouse[key])
            elif isinstance(widget, QDoubleSpinBox):
                widget.setRange(min(widget.minimum(), self.mouse[key]), max(widget.maximum(), self.mouse[key]))
                widget.setValue(self.mouse[key])
                self.sync_slider(widget.parentWidget().findChild(QSlider), self.mouse[key])
            else:
                for button in widget.group.buttons():
                    button.blockSignals(True)
                    button.setChecked(button.property('value') == self.mouse[key])
                    button.blockSignals(False)
            widget.blockSignals(False)
        self.show_camera_mode()

    def build_controller(self):
        layout = self.controller_body
        self.section(layout, backend._('Controller test'))
        card = QFrame()
        card.setObjectName('controller_test')
        card.setProperty('card', True)
        self.setting_widgets['controller_test'] = card
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(22, 16, 22, 16)
        card_layout.setSpacing(26)
        self.pad_picture = QLabel()
        self.pad_picture.setFixedSize(420, 266)
        self.pad_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.pad_picture)
        side = QVBoxLayout()
        side.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pad_status = self.note(side, backend._('No controller found. Connect it by cable or Bluetooth.'))
        self.note(side, backend._('Press the buttons: what lights up here reaches the game.'))
        help_button = QPushButton(backend._('The controller does nothing') + '  ›')
        help_button.clicked.connect(lambda: self.help_requested.emit('controller'))
        side.addWidget(help_button, alignment=Qt.AlignmentFlag.AlignLeft)
        card_layout.addLayout(side, 1)
        layout.addWidget(card)
        self.draw_pad(None)
        self.section(layout, backend._('Controller', 'Геймпад'))
        self.note(layout, backend._('Click a slot, then press the controller button for that action; Esc cancels. Right-click a slot to put back its default. A button on two actions presses both. The sticks always move and turn the camera.'))
        self.controller_rows = self.binding_table(layout, True)
        reset = QPushButton(backend._('Reset controller buttons', 'Сбросить кнопки геймпада'))
        reset.setObjectName('button:reset_controller')
        self.setting_widgets['button:reset_controller'] = reset
        reset.clicked.connect(self.reset_controller)
        layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        self.refresh_controller()

    def binding_table(self, layout, controller):
        table = QGridLayout()
        table.setHorizontalSpacing(8)
        table.setVerticalSpacing(4)
        table.setColumnMinimumWidth(0, 340)
        rows, row = {}, 0
        for title, actions in inputs.ACTION_GROUPS:
            actions = [(o, label) for o, label in actions if not controller or o in inputs.CONTROLLER_OUTPUTS]
            if not actions:
                continue
            heading = QLabel(backend._(*title))
            heading.setObjectName('sectionTitle')
            table.addWidget(heading, row, 0, 1, 5)
            row += 1
            for output, label in actions:
                caption = QLabel(backend._(*label))
                caption.setWordWrap(True)
                caption.setMaximumWidth(380)
                table.addWidget(caption, row, 0)
                buttons = []
                for slot in range(1 if controller else inputs.SLOTS):
                    button = QPushButton()
                    button.setMinimumWidth(122)
                    button.setMaximumWidth(160)
                    button.setObjectName(('controller:' + output) if controller else f'input:{output}:{slot}')
                    self.setting_widgets[button.objectName()] = button
                    button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                    if controller:
                        button.clicked.connect(lambda _checked=False, o=output: self.start_controller_capture(o))
                        button.customContextMenuRequested.connect(lambda _pos, o=output: self.set_controller(o, inputs.DEFAULT_CONTROLLER.get(o)))
                    else:
                        button.clicked.connect(lambda _checked=False, o=output, i=slot: self.start_capture(o, i))
                        button.customContextMenuRequested.connect(lambda _pos, o=output, i=slot: self.clear_slot(o, i))
                    table.addWidget(button, row, slot + 1)
                    buttons.append(button)
                warn = QLabel()
                warn.setWordWrap(True)
                warn.setObjectName('pageDescription')
                table.addWidget(warn, row, (2 if controller else inputs.SLOTS + 1))
                rows[output] = buttons, warn
                row += 1
        table.setColumnStretch(2 if controller else inputs.SLOTS + 1, 1)
        layout.addLayout(table)
        return rows

    def current_slots(self, output):
        values = list(self.edits.get(output, self.bindings.get(output, [])))
        return values + [None] * max(0, inputs.SLOTS - len(values))

    def set_slot(self, output, slot, value):
        if output not in self.bindings or not 0 <= slot < inputs.SLOTS:
            raise ValueError('Unknown binding slot')
        if value and (not inputs.is_bindable(output, value) or any(p in inputs.reserved_keys(self.toggle_key, self.reload_key) for p in inputs.binding_parts(value))):
            raise ValueError('Unsupported or reserved input')
        values = self.current_slots(output)
        values[slot] = value
        self.edits[output] = values
        self.refresh_bindings()
        self.changed.emit()

    def clear_slot(self, output, slot):
        if self.capture is None:
            self.set_slot(output, slot, None)

    def refresh_bindings(self):
        current = {o: self.current_slots(o) for o in self.remap_rows}
        conflicts = inputs.slot_conflicts(current)
        for output, (buttons, warn) in self.remap_rows.items():
            marked = conflicts.get(output, {})
            for slot, button in enumerate(buttons):
                value = current[output][slot]
                text = ' + '.join(inputs.display_name(p, backend.LANG == 'ru') for p in inputs.binding_parts(value)) if value else '—'
                button.setText(text + ('  ⚠' if slot in marked else ''))
            others = sorted({o for names in marked.values() for o in names})
            warn.setText(('⚠ ' + backend._('also {}', 'также {}').format(', '.join(backend._(*inputs.OUTPUT_LABELS[o]) for o in others))) if others else '')

    def set_controller(self, output, value):
        if self.capture:
            return
        if output not in inputs.CONTROLLER_OUTPUTS or value is not None and value not in inputs.CONTROLLER_NAMES:
            raise ValueError('Unknown controller binding')
        self.controller_edits[output] = value
        self.refresh_controller()
        self.changed.emit()

    def reset_controller(self):
        for output in inputs.CONTROLLER_OUTPUTS:
            self.set_controller(output, inputs.DEFAULT_CONTROLLER.get(output))

    def refresh_controller(self):
        current = {**self.controllers, **self.controller_edits}
        conflicts = inputs.controller_conflicts(current)
        for output, (buttons, warn) in self.controller_rows.items():
            value = current[output]
            buttons[0].setText((inputs.controller_display_name(value, backend.LANG == 'ru') if value else '—') + ('  ⚠' if output in conflicts else ''))
            warn.setText(('⚠ ' + backend._('also {}', 'также {}').format(', '.join(backend._(*inputs.OUTPUT_LABELS[o]) for o in conflicts[output]))) if output in conflicts else '')

    def set_play_with(self, device):
        self.finish_capture()
        self.settings['play_with'] = device
        self.devices[device].setChecked(True)
        self.tabs.setCurrentWidget(self.controller_page if device == 'controller' else self.keyboard_page)
        if device == 'keyboard':
            layout = 'own' if self.edits else inputs.keyboard_layout(self.read_lines())
            if layout == 'default' or layout == 'own' and self.confirm(backend._('Dark Souls III layout'), backend._("You changed the keyboard and mouse bindings yourself. Replace them with the Dark Souls III layout? The controller's buttons stay.\n\nNo keeps your keys and only turns the mouse camera on.")):
                self.write_layout()
        self.mouse_widgets['enabled'].setChecked(device == 'keyboard')
        if self.isVisible():
            self.start_pads() if device == 'controller' else self.stop_pads()
        self.changed.emit()

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def warning(self, title, text):
        self.message_open = True
        try:
            QMessageBox.warning(self, title, text)
        finally:
            self.message_open = False

    def apply_layout_preset(self):
        if self.confirm(backend._('Dark Souls III layout'), backend._('Replace your keyboard and mouse bindings with the Dark Souls III layout? Controller bindings stay as they are.')):
            self.write_layout()

    def atomic_write(self, writer):
        # Work through the shared serializers on a sibling file; an interrupted save keeps the original.
        target = self.ini_path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.input-', suffix='.ini', dir=target.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            writer(temporary)
            if target.exists():
                temporary.chmod(target.stat().st_mode & 0o777)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def write_layout(self):
        try:
            lines = inputs.apply_layout(self.read_lines())
            self.atomic_write(lambda path: path.write_text('\n'.join(lines) + '\n', encoding='utf-8'))
        except OSError as error:
            self.warning(backend._('Layout', 'Раскладка'), str(error))
            return False
        self.edits.clear()
        self.mouse_edits.clear()
        self.load()
        self.sync_mouse_widgets()
        self.refresh_bindings()
        self.changed.emit()
        return True

    def save(self):
        if not (self.edits or self.controller_edits or self.mouse_edits):
            return
        fresh = self.read_lines()
        _bindings, _lines, toggle, reload, _mouse = inputs.read_input_lines(fresh)
        reserved = inputs.reserved_keys(toggle, reload)
        for values in self.edits.values():
            if any(p in reserved for value in values if value for p in inputs.binding_parts(value)):
                raise ValueError(backend._('A binding uses a reserved input. The input.ini hotkeys may have changed; choose another key.'))
        def write(path):
            lines = fresh
            if self.edits:
                inputs.save_input_ini(path, {o: [v for v in values if v] for o, values in self.edits.items()}, lines)
                lines = path.read_text(encoding='utf-8').splitlines()
            if self.controller_edits:
                inputs.save_controller_bindings(path, self.controller_edits, lines)
                lines = path.read_text(encoding='utf-8').splitlines()
            if self.mouse_edits:
                mouse = {**inputs.read_input_lines(lines)[4], **self.mouse_edits}
                inputs.save_mouse_settings(path, mouse, lines)
        self.atomic_write(write)
        self.edits.clear()
        self.controller_edits.clear()
        self.mouse_edits.clear()
        self.load()
        self.sync_mouse_widgets()
        self.refresh_bindings()
        self.refresh_controller()

    def start_capture(self, output, slot):
        if self.capture:
            return
        _bindings, _lines, self.toggle_key, self.reload_key, _mouse = inputs.read_input_lines(self.read_lines())
        self.capture = ('keyboard', output, slot)
        self.modifiers = []
        self.set_slots_enabled(False)
        self.remap_rows[output][0][slot].setText(backend._('Press…', 'Нажмите…'))
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def finish_capture(self):
        if not self.capture:
            return
        self.capture = None
        self.timer.setInterval(40)
        self.modifiers = []
        self.set_slots_enabled(True)
        self.refresh_bindings()
        self.refresh_controller()

    def set_slots_enabled(self, enabled):
        for rows in (self.remap_rows, self.controller_rows):
            for buttons, _warn in rows.values():
                for button in buttons:
                    button.setEnabled(enabled)

    def capture_name(self, name):
        if not self.capture or self.capture[0] != 'keyboard':
            return
        _kind, output, slot = self.capture
        parts = (self.modifiers + [name])[-inputs.MAX_COMBO:] if name not in self.modifiers else list(self.modifiers)
        reserved = [p for p in parts if p in inputs.reserved_keys(self.toggle_key, self.reload_key)]
        if reserved:
            self.finish_capture()
            self.warning(backend._('Reserved', 'Зарезервировано'), backend._('{} is reserved (menu, recording, or a hotkey) and cannot be bound to a game action.').format(inputs.display_name(reserved[0])))
            return
        if not inputs.is_bindable(output, ', '.join(parts)):
            self.warning(backend._('Keyboard only', 'Только клавиатура'), backend._('A stick direction can only be bound to a key, not a mouse button.'))
            return
        self.set_slot(output, slot, ', '.join(parts))
        self.finish_capture()

    def eventFilter(self, watched, event):
        if not self.capture or self.message_open:
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if kind == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.finish_capture()
                return True
            if self.capture[0] == 'controller' or event.isAutoRepeat():
                return True
            name = key_name(event)
            if name is None:
                self.warning(backend._('Unsupported key', 'Клавиша не поддерживается'), backend._('That key has no bbport name; pick another one.'))
            elif name in inputs.MODIFIER_NAMES:
                if name not in self.modifiers and len(self.modifiers) < inputs.MAX_COMBO - 1:
                    self.modifiers.append(name)
                    self.remap_rows[self.capture[1]][0][self.capture[2]].setText(' + '.join(inputs.display_name(m) for m in self.modifiers) + ' + …')
            else:
                self.capture_name(name)
            return True
        if kind == QEvent.Type.KeyRelease:
            if self.capture[0] == 'keyboard' and self.modifiers and not event.isAutoRepeat() and key_name(event) in self.modifiers:
                self.capture_name(self.modifiers[-1])
            return True
        if kind == QEvent.Type.MouseButtonPress:
            if self.capture[0] == 'keyboard':
                name = {Qt.MouseButton.LeftButton: 'leftbutton', Qt.MouseButton.MiddleButton: 'middlebutton',
                        Qt.MouseButton.RightButton: 'rightbutton', Qt.MouseButton.BackButton: 'sidebuttonback',
                        Qt.MouseButton.ForwardButton: 'sidebuttonforward'}.get(event.button())
                if name:
                    self.capture_name(name)
            return True
        if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return True
        if kind == QEvent.Type.Wheel:
            if self.capture[0] == 'keyboard':
                delta = event.angleDelta()
                horizontal = abs(delta.x()) > abs(delta.y()) or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                # Qt's horizontal delta is positive to the left; the input format is positive right.
                amount = -delta.x() if delta.x() and horizontal else delta.y()
                name = inputs.wheel_to_name(amount, horizontal)
                if name:
                    self.capture_name(name)
            return True
        return super().eventFilter(watched, event)

    def start_controller_capture(self, output):
        if self.capture:
            return
        self.start_pads()
        pads = self.poll_pads()
        if not pads:
            self.warning(backend._('Controller', 'Геймпад'), self.pad_status.text())
            return
        self.capture = ('controller', output, 0)
        self.ignored = self.held_buttons(pads)
        self.deadline = time.monotonic() + 10
        self.set_slots_enabled(False)
        self.controller_rows[output][0][0].setText(backend._('Press a button…', 'Нажмите кнопку…'))
        self.timer.setInterval(15)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def held_buttons(pads):
        held = set()
        for pad in pads:
            held.update(name for index, name in bbport_gamepad.BUTTONS.items() if pad.buttons.get(bbport_pad.BUTTONS[index]))
            held.update(name for axis, name in bbport_gamepad.TRIGGERS.items() if pad.axes.get(bbport_pad.AXES[axis], 0) > bbport_gamepad.TRIGGER_PRESSED / 32767)
        return held

    def draw_pad(self, pad):
        kind = pad.kind if pad else self.pad_kind
        buttons = tuple(sorted(b for b, value in pad.buttons.items() if value)) if pad else ()
        axes = tuple(round(pad.axes.get(a, 0.0) * 20) / 20 for a in bbport_pad.AXES) if pad else (0.0,) * 6
        state = kind, buttons, axes
        if state == self.pad_state:
            return
        self.pad_state, self.pad_kind = state, kind
        image = bbport_pad_art.render(kind, dict.fromkeys(buttons, True), dict(zip(bbport_pad.AXES, axes)), width=420).convert('RGBA')
        data = image.tobytes()
        picture = QImage(data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()
        self.pad_picture.setPixmap(QPixmap.fromImage(picture))

    def start_pads(self):
        if self.game_running:
            self.pad_status.setText(backend._('The game is running: the test waits until it is closed.'))
            return
        if self.reader is None:
            try:
                library = bbport_pad.sdl_path(backend.PORT_DIR)
                if not library:
                    raise OSError(backend._('SDL3 is not installed or bundled with the port.'))
                self.reader = bbport_pad.Pads(library)
            except (OSError, AttributeError) as error:
                self.pad_status.setText(backend._('The controller test cannot start: {}').format(error))
                return
        self.timer.start()

    def poll_pads(self):
        if self.reader is None:
            return []
        try:
            pads = self.reader.poll()
        except OSError as error:
            self.pad_status.setText(backend._('The controller test cannot start: {}').format(error))
            self.stop_pads()
            return []
        if pads:
            self.pad_status.setText('   ·   '.join(f'{pad.name} ({bbport_pad.KIND_NAMES[pad.kind]})' for pad in pads))
            active = [pad for pad in pads if any(pad.buttons.values()) or any(abs(v) > 0.2 for v in pad.axes.values())]
            self.draw_pad((active or pads)[0])
        else:
            self.pad_status.setText(backend._('No controller found. Connect it by cable or Bluetooth.'))
            self.draw_pad(None)
        if self.capture and self.capture[0] == 'controller':
            held = self.held_buttons(pads)
            self.ignored.intersection_update(held)
            new = sorted(held - self.ignored)
            if new:
                output = self.capture[1]
                self.finish_capture()
                self.set_controller(output, new[0])
                self.timer.setInterval(40)
            elif time.monotonic() > self.deadline or not pads:
                self.finish_capture()
                self.timer.setInterval(40)
        return pads

    def stop_pads(self):
        self.timer.stop()
        if self.reader is not None:
            self.reader.close()
            self.reader = None

    def stop(self):
        self.finish_capture()
        self.stop_pads()

    def set_game_running(self, running):
        self.game_running = running
        self.stop()
        if self.isVisible() and self.tabs.currentWidget() is self.controller_page:
            self.start_pads()

    def showEvent(self, event):
        super().showEvent(event)
        if self.tabs.currentWidget() is self.controller_page:
            self.start_pads()

    def hideEvent(self, event):
        self.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.stop()
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

# SPDX-License-Identifier: GPL-2.0-or-later
"""All graphics settings and optional FSR assets, using the launcher's shared backends."""
import os
from pathlib import Path
import shutil
import tempfile
import threading
import urllib.request

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget)

import bbport_launcher_win as backend
import bbport_fsr411 as fsr411
import bbport_fg401 as fg401
from bbport_qt_content import button, note as content_note, open_path

_ = backend._
CHUNK = 256 * 1024


def note(layout, text):
    label = content_note(layout, text)
    font = label.font()
    font.setPointSize(9)
    label.setFont(font)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return label


class DownloadCancelled(Exception):
    pass


def _check_cancel(cancel):
    if cancel.is_set():
        raise DownloadCancelled()


def download_fsr4_assets(folder, names, base_url, progress, cancel):
    """Complete files replace their destinations atomically; temporary files never survive errors."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(names):
        _check_cancel(cancel)
        part = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix='.' + name + '.', suffix='.part', delete=False) as stream:
                part = Path(stream.name)
                with urllib.request.urlopen(f'{base_url}/{name}', timeout=30) as response:
                    expected = response.headers.get('Content-Length')
                    written = 0
                    while True:
                        _check_cancel(cancel)
                        data = response.read(CHUNK)
                        if not data:
                            break
                        stream.write(data)
                        written += len(data)
                if not written or expected is not None and written != int(expected):
                    raise OSError(_('Download incomplete: {}').format(name))
            _check_cancel(cancel)
            part.replace(folder / name)
            progress(index + 1, len(names))
        finally:
            if part is not None:
                part.unlink(missing_ok=True)


def download_fsr411_assets(folder, progress, cancel):
    """The pinned downloader verifies a staging folder before its files enter the installation."""
    folder = Path(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder.parent, prefix='.fsr4vk-') as temporary:
        staged = Path(temporary)
        def report(done, total):
            _check_cancel(cancel)
            progress(done, total)
        _check_cancel(cancel)
        backend.fetch_fsr4vk.fetch(staged, report)
        _check_cancel(cancel)
        if not backend.fetch_fsr4vk.files_ok(staged):
            raise backend.fetch_fsr4vk.FetchError(_('Vulkan (fsr4vk): files missing or need updating.'))
        folder.mkdir(parents=True, exist_ok=True)
        for filename in [name for _member, name, _size, _hash in backend.fetch_fsr4vk.FILES] + [*backend.fetch_fsr4vk.EXTRA, 'SOURCE.txt']:
            _check_cancel(cancel)
            source = staged / filename
            if source.is_file():
                destination = folder / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)


class GraphicsPage(QWidget):
    settings_changed = Signal()
    page_requested = Signal(str)
    busy_changed = Signal(bool)
    download_progress = Signal(str, int, int)
    download_finished = Signal(str, str, bool)
    support_finished = Signal(object, object)

    def __init__(self, settings, graphics, parent=None):
        super().__init__(parent)
        self.settings, self.graphics = settings, graphics
        self.app_widgets, self.ini_widgets = {}, {}
        self.initial_app, self.initial_ini = {}, {}
        self.running = self.downloading = self.fsr411_downloading = False
        self.fsr411_support = self.fg401_support = None
        self._checking = self._refreshing = False
        self._cancel = threading.Event()
        self.destroyed.connect(lambda _obj=None, event=self._cancel: event.set())
        self._activate_backend = False
        self._output_value = graphics.get('output_res', backend.INI_DEFAULTS['output_res'])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName('settingsPage')
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(32, 8, 32, 28)
        self.body.setSpacing(18)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.warning = note(self.body, '')
        self.warning.hide()
        link = QHBoxLayout()
        picture_note = note(link, _('Fullscreen, HDR and the taste effects are on Picture & performance.'))
        picture_note.setWordWrap(False)
        open_picture = button(link, 'Open ›', lambda: self.page_requested.emit('picture'))
        open_picture.setStyleSheet(f'color: {backend.GOLD}; border: none; background: transparent; padding: 0;')
        link.addStretch()
        self.body.addLayout(link)
        form = self.section('Upscaling')
        self.choice(form, 'upscaler', 'Upscaler', backend.UPSCALERS,
            hint="Temporal upscaling with the game's own motion vectors. FSR 4 needs its files (below) and "
                 'a GPU with INT8 dot products; otherwise the game falls back to FSR 3.1 by itself.')
        self.choice(form, 'preset', 'Quality preset', backend.PRESETS,
            hint='Render scale per axis: Quality renders at 1/1.5 of the output size.')
        self.backend_choice = QComboBox()
        self.backend_choice.setObjectName('fsr411_backend')
        self.backend_choice.setFixedWidth(390)
        self.ini_widgets['fsr411_backend'] = self.backend_choice
        self.backend_label = QLabel(_('FSR 4.1.1 backend'))
        self.backend_holder = QWidget()
        self.backend_holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        backend_layout = QVBoxLayout(self.backend_holder)
        backend_layout.setContentsMargins(0, 0, 0, 0)
        backend_layout.addWidget(self.backend_choice)
        self.backend_hint = note(backend_layout, _("AMD DX12 uses AMD's FSR library. Vulkan uses fsr4vk. "
                                                 'Switching applies the next time the game starts.'))
        form.addRow(self.backend_label, self.backend_holder)
        self.backend_choice.activated.connect(self._select_backend)
        self._build_output(form)
        self.choice(form, 'hud_position', 'HUD position (ultrawide)', backend.HUD_POSITIONS,
            hint='21:9 outputs: health, items and Blood Echoes at the screen edges, or in the centred '
                 '16:9 area as on a 16:9 screen.')
        # Awaken's idea from the Lantern Engine (patches.py ui_viewport, UiComposition).
        self.check(form, 'sharp_ui', 'Sharp UI',
            'Menus, HUD and text drawn at the output resolution instead of 1080p stretched up: much '
            'sharper at 1440p and 4K. From the next start, with live resolution changes off; not on '
            "ultrawide screens yet. An idea from Awaken's Lantern Engine.")
        self.choice(form, 'live_resolution', 'Live resolution changes', backend.LIVE,
            hint='Off: outputs other than 1080p are set by a patch at start (fastest; changing them in the '
                 'game restarts it). On: change output and preset in the game without a restart, at a cost.')
        self.check(form, 'sharpen', 'Sharpening (RCAS)')
        self.sharpness = QDoubleSpinBox()
        self.sharpness.setObjectName('sharpnessValue')
        self.sharpness.setRange(0, 2)
        self.sharpness.setDecimals(2)
        self.sharpness.setSingleStep(0.05)
        self.ini_widgets['sharpness'] = self.sharpness
        self.sharpness.hide()
        sharpness_row = QHBoxLayout()
        self.sharpness_slider = QSlider(Qt.Orientation.Horizontal)
        self.sharpness_slider.setObjectName('sharpness')
        self.sharpness_slider.setRange(0, 200)
        self.sharpness_slider.setMaximumWidth(300)
        sharpness_value = QLabel()
        sharpness_row.addWidget(self.sharpness_slider)
        sharpness_row.addWidget(sharpness_value)
        sharpness_row.addStretch()
        form.addRow(_('Sharpness'), sharpness_row)
        self.sharpness_slider.valueChanged.connect(lambda value: self.sharpness.setValue(value / 100))
        self.sharpness.valueChanged.connect(lambda value: (self.sharpness_slider.setValue(round(value * 100)), sharpness_value.setText(f'{value:.2f}')))
        self.sharpness.valueChanged.connect(lambda _value: self._edited('sharpness'))
        self.check(form, 'object_motion', 'Object motion vectors',
            'Less ghosting on characters, cloth and weapons; costs about 5–10% FPS.')
        self.check(form, 'object_motion_cache', 'Motion-vector cache (experimental)',
            'May improve FSR performance; uses extra VRAM. Requires object motion vectors. Applies at next game start.')
        effects = self.section('Effects')
        for key, title, _on in backend.EFFECTS:
            if key not in backend.TASTE_EFFECTS:
                self.check(effects, key, _(*title))
        self.choice(effects, 'model_lod', 'Model detail (LOD)', backend.LODS,
                    hint='A game patch (game version 1.09).')
        effects.addRow(self._label(_('Effects are game patches for version 1.09, applied at start.')))
        fps = self.section('Frame rate')
        self.choice(fps, 'fps_mode', 'Frame rate', backend.FPS_MODES, store='app',
            hint='Community patches for game version 1.09. Unlocked makes the game use the real frame time. '
                 'Other game versions always run at 30 FPS (the patches would corrupt them).')
        self.choice(fps, 'frame_cap', 'Frame cap (unlocked mode)', backend.FRAME_CAPS, store='app',
            hint="Above about 120 FPS the game's movement timing breaks (running and rolling get slower, "
                 'physics and animations can glitch): higher caps are at your own risk.')
        self.choice(fps, 'frames_ahead', 'Frames ahead of the GPU', backend.FRAMES_AHEAD, store='app',
            hint='1 keeps frame pacing even; more can raise FPS when the graphics card is the limit.')
        self.choice(fps, 'present_mode', 'Presentation', backend.PRESENT_MODES, store='app')
        self.choice(fps, 'low_latency', 'Low latency (Reflex / Anti-Lag 2)', backend.LOW_LATENCY, store='app',
            hint='Less input lag: the game starts each frame just in time instead of queuing frames for the '
                 'display. NVIDIA Reflex on GeForce, AMD Anti-Lag 2 on Radeon (current drivers); other GPUs ignore '
                 'it. Boost keeps the GPU clocks up. Auto: On + Boost on NVIDIA, off on other GPUs.')
        early = self.choice(fps, 'early_submit', 'Send frames to the GPU in parts', backend.EARLY_SUBMIT, store='app',
            hint='The graphics card starts drawing a frame while the rest of it is still being prepared, '
                 'so it is finished about 2 ms sooner. Uses a little more CPU. New: turn it off if you see '
                 'flickering or missing objects.')
        self.early_reason = note(early.parentWidget().layout(), '')
        self.choice(fps, 'vrr', 'Variable refresh rate (VRR)', backend.VRR_MODES, store='app',
            hint='For a G-Sync or FreeSync display: the display follows the frames of the game, without tearing '
                 'and without the lag of V-Sync. Uses V-Sync (Presentation is ignored) and keeps the frame rate a '
                 'little below the refresh rate (117 FPS at 120 Hz, at most 120). Turn on G-Sync/FreeSync in '
                 'the NVIDIA/AMD control panel; fullscreen works best.')
        self.choice(fps, 'async_pipelines', 'New shaders while playing', backend.ASYNC_PIPELINES, store='app',
            hint='In the background: a place seen for the first time does not stutter while its shaders are '
                 'compiled; things drawn with them appear a moment later instead. Each is compiled once and kept.')
        counter = self.section('FPS counter')
        boxes = QGridLayout()
        boxes.setHorizontalSpacing(32)
        for index, (key, title) in enumerate(backend.READOUTS):
            box = QCheckBox(_(*title))
            box.setObjectName(key)
            self.ini_widgets[key] = box
            boxes.addWidget(box, index // 2, index % 2)
            box.toggled.connect(lambda _checked, key=key: self._edited(key))
        boxes.setColumnStretch(2, 1)
        counter.addRow(boxes)
        self.choice(counter, 'counter_colors', 'Value colours', backend.COUNTER_COLORS,
            hint='Colour-coded shows at a glance how each value stands; plain keeps the counter quiet.')
        counter.addRow(self._label(_('One box per line of the counter in the top right; also in the in-game menu. Render '
                                     'latency is the time from the game starting a frame to it being shown, which Low latency '
                                     'lowers; frame time is the time between two frames.')))
        frames = self.section('Frame generation')
        self.choice(frames, 'frame_gen', 'Frame generation', backend.FRAME_GENERATION,
            hint="Frames made between two of the game's: 60 FPS on screen becomes 120. Needs a display with "
                 'that refresh rate (120 Hz or more at 60 FPS); it pauses when the display cannot show the extra '
                 'frames. Adds a little input latency. Menus and movies are not generated. DLSS needs a GeForce '
                 'RTX 40 or newer, otherwise FSR 3.1 is used.')
        self.fg_status = self._label('')
        frames.addRow(self.fg_status)
        self.fg_recheck = QPushButton(_('Recheck support'))
        self.fg_recheck.clicked.connect(self.recheck_support)
        frames.addRow(self.fg_recheck)
        self.choice(frames, 'frame_gen_multiplier', 'Multiplier', backend.FRAME_GEN_MULTIPLIERS,
            hint='FSR 3.1 makes one frame (2×); DLSS on a GeForce RTX 50 up to three (4×).')
        self.check(frames, 'frame_gen_fit_display', 'Fit to display refresh',
            'On: no more frames than the display shows (an uncapped game gets fewer generated frames, and '
            'the GPU does less). Off: the multiplier as chosen.')
        self._build_assets()
        self.body.addStretch()
        self.download_progress.connect(self._download_progress)
        self.download_finished.connect(self._download_done)
        self.support_finished.connect(self._support_done)
        self.refresh(settings, graphics)
        QTimer.singleShot(0, self, self.recheck_support)

    @staticmethod
    def _label(text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        widget.setObjectName('pageDescription')
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return widget

    def section(self, title):
        card = QWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        text = QLabel(_(title))
        text.setObjectName('sectionTitle')
        heading.addWidget(text)
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f'background: {backend.theme.BORDER};')
        heading.addWidget(rule, 1)
        layout.addLayout(heading)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(18)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        self.body.addWidget(card)
        return form

    def choice(self, form, key, title, options, store='ini', hint=''):
        combo = QComboBox()
        combo.setObjectName(key)
        combo.setToolTip(_(hint))
        combo.setFixedWidth(390)
        for value, text in options:
            combo.addItem(_(*text), value)
        (self.ini_widgets if store == 'ini' else self.app_widgets)[key] = combo
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(combo, 0, Qt.AlignmentFlag.AlignLeft)
        if hint:
            note(layout, _(hint))
        form.addRow(_(title), holder)
        form.labelForField(holder).setMinimumWidth(184)
        combo.currentIndexChanged.connect(lambda _index: self._edited(key))
        return combo

    def check(self, form, key, title, hint=''):
        widget = QCheckBox(_(title))
        widget.setObjectName(key)
        widget.setToolTip(_(hint))
        self.ini_widgets[key] = widget
        form.addRow(widget)
        if hint:
            form.addRow(self._label(_(hint)))
        widget.toggled.connect(lambda _checked: self._edited(key))
        return widget

    def _build_output(self, form):
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        holder.setObjectName('output_display')
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.output_combo = QComboBox()
        self.output_combo.setObjectName('output_res')
        self.output_combo.setFixedWidth(315)
        self.output_combo.addItem(_('Same as the monitor'), 'display')
        for value, text in backend.OUTPUTS:
            self.output_combo.addItem(_(*text), value)
        self.output_combo.addItem(_('Custom size…'), 'custom')
        self.output_custom = QLineEdit()
        self.output_custom.setObjectName('output_custom')
        self.output_custom.setMaximumWidth(180)
        row.addWidget(self.output_combo, 1)
        row.addWidget(self.output_custom)
        row.addStretch()
        layout.addLayout(row)
        self.output_note = note(layout, '')
        note(layout, _('What the upscaler produces; the HUD is drawn at this size too.'))
        form.addRow(_('Output resolution'), holder)
        self.output_combo.activated.connect(self._choose_output)
        self.output_custom.editingFinished.connect(self._commit_custom)

    def monitor_size(self):
        monitor = backend.display.monitor(self.settings.get('game_monitor', ''))
        if monitor:
            return monitor.size
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            size, scale = screen.size(), screen.devicePixelRatio()
            return round(size.width() * scale), round(size.height() * scale)
        return 1920, 1080

    def _choose_output(self, _index):
        selected = self.output_combo.currentData()
        if selected == 'display':
            self._output_value = backend.display.size_text(self.monitor_size())
        elif selected != 'custom':
            self._output_value = selected
        self.output_custom.setText(self._output_value)
        self._show_output()
        self._edited('output_res')
        if selected == 'custom':
            self.output_custom.setFocus()
            self.output_custom.selectAll()

    def _show_output(self):
        selected = self.output_combo.currentData()
        self.output_custom.setVisible(selected == 'custom')
        size = backend.display.parse_size(self._output_value)
        text = _('now {} × {}').format(*self.monitor_size()) if selected == 'display' else \
            _('Narrower than 16:9: the picture may look stretched.') if size and backend.display.narrower_than_16_9(size) else ''
        self.output_note.setText(text)
        self.output_note.setVisible(bool(text))

    def _commit_custom(self, strict=False):
        if self.output_combo.currentData() != 'custom':
            return True
        size = backend.display.parse_size(self.output_custom.text())
        if not size:
            text = _('Width × height, e.g. 2400x1080 (from 640x360 to 7680x4320).')
            self.output_note.setText(text)
            if strict:
                raise ValueError(text)
            return False
        value = backend.display.size_text(size)
        changed = value != self._output_value
        self._output_value = value
        self.output_custom.setText(value)
        self._show_output()
        if changed:
            self._edited('output_res')
        return True

    @staticmethod
    def _value(widget, ini):
        if isinstance(widget, QCheckBox):
            value = widget.isChecked()
            return ('1' if value else '0') if ini else value
        if isinstance(widget, QDoubleSpinBox):
            return f'{widget.value():.2f}'
        return widget.currentData()

    def app_values(self):
        values = {key: self._value(widget, False) for key, widget in self.app_widgets.items()}
        values['output_display'] = self.output_combo.currentData() == 'display'
        return {key: value for key, value in values.items() if value != self.initial_app.get(key)}

    def ini_values(self):
        values = {key: self._value(widget, True) for key, widget in self.ini_widgets.items()}
        values['output_res'] = self._output_value
        return {key: value for key, value in values.items() if value != self.initial_ini.get(key)}

    def save(self):
        self._commit_custom(strict=True)
        app, ini = self.app_values(), self.ini_values()
        self.settings.update(app)
        self.graphics.update(ini)
        self.initial_app.update(app)
        self.initial_ini.update(ini)
        return True

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
                    value = values.get(key, defaults.get(key))
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(value == '1' if ini else bool(value))
                    elif isinstance(widget, QDoubleSpinBox):
                        widget.setValue(float(value))
                    else:
                        index = widget.findData(value)
                        if index < 0:
                            widget.addItem(str(value), value)
                            index = widget.count() - 1
                        widget.setCurrentIndex(index)
            self._output_value = self.graphics.get('output_res', backend.INI_DEFAULTS['output_res'])
            self.initial_app = {key: self._value(widget, False) for key, widget in self.app_widgets.items()}
            self.initial_app['output_display'] = bool(self.settings.get('output_display', False))
            self.initial_ini = {key: self._value(widget, True) for key, widget in self.ini_widgets.items()}
            self.initial_ini['output_res'] = self._output_value
            pick = 'display' if self.initial_app['output_display'] else self._output_value
            if self.output_combo.findData(pick) < 0:
                pick = 'custom'
            self.output_combo.setCurrentIndex(self.output_combo.findData(pick))
            if pick == 'display':
                self._output_value = backend.display.size_text(self.monitor_size())
            self.output_custom.setText(self._output_value)
            self._show_output()
            info = backend.game_info(self.settings.get('game_dir', ''))
            self.warning.setText(_('Game version {}: the community patches only apply to 1.09.').format(info[1])
                                 if info and info[1] != backend.PATCH_VERSION else '')
            self.warning.setVisible(bool(self.warning.text()))
            self._refresh_choices()
            self.refresh_fsr4()
            self.refresh_fsr411()
        finally:
            self._refreshing = False

    def _edited(self, key):
        if self._refreshing:
            return
        if key in ('upscaler', 'object_motion', 'frame_gen'):
            self._refresh_choices()
        if key in ('upscaler', 'preset', 'output_res'):
            self.refresh_fsr411()
        self.settings_changed.emit()

    def _refresh_choices(self):
        widgets = self.ini_widgets
        # Off on Radeon cards whatever the setting says (vk_rasterizer.cpp MaybeSubmitEarly).
        why = backend.early_submit_unavailable(backend.Launcher.detected_vendor(self), self.settings.get('extra_env', ''))
        self.app_widgets['early_submit'].setEnabled(not self.running and not why)
        self.early_reason.setText(why)
        self.early_reason.setVisible(bool(why))
        widgets['object_motion_cache'].setEnabled(not self.running and backend.motion_cache_available(
            {'upscaler': widgets['upscaler'].currentData(), 'object_motion': self._value(widgets['object_motion'], True)}))
        upscaler = widgets['upscaler'].currentData()
        options = backend.UPSCALERS
        caps = self.fsr411_support
        if caps and upscaler != 'fsr411' and not any(caps[m]['supported'] or caps[m]['reason'] == 'files' for m in ('vk', 'dx12')):
            options = [(value, text) for value, text in options if value != 'fsr411']
        self._replace_options(widgets['upscaler'], options, upscaler)
        current = widgets['frame_gen'].currentData()
        ready = bool(self.fg401_support and self.fg401_support.get('supported'))
        options = [(value, text) for value, text in backend.FRAME_GENERATION
                   if (value != 'fsr401' or ready) and (backend.WINDOWS or value != 'dlss')]
        unavailable = _('ML-FG 4.0.1: checking support…') if self.fg401_support is None else _(fg401.KEYS[0])
        self._replace_options(widgets['frame_gen'], options, current, unavailable)
        text = fg401.message(self.fg401_support, _, hdr=bool(self.settings.get('hdr')), selected=True) if current == 'fsr401' else ''
        self.fg_status.setText(text)
        self.fg_status.setVisible(bool(text))
        self.fg_recheck.setVisible(bool(text))

    @staticmethod
    def _replace_options(combo, options, current, unavailable=None):
        blocker = QSignalBlocker(combo)
        combo.clear()
        for value, text in options:
            combo.addItem(_(*text), value)
        index = combo.findData(current)
        if index < 0:
            combo.addItem(unavailable or str(current), current)
            index = combo.count() - 1
            combo.model().item(index).setEnabled(False)
        combo.setCurrentIndex(index)
        del blocker

    def _build_assets(self):
        assets = self.section('FSR 4 assets')
        self.fsr4_status = self._label('')
        assets.addRow(self.fsr4_status)
        row = QHBoxLayout()
        self.fsr4_button = button(row, 'Download FSR 4 assets', self.download_fsr4)
        self.fsr4_button.setObjectName('button:fsr4')
        self.fsr4_progress = QProgressBar()
        self.fsr4_progress.setRange(0, len(backend.fsr4_files()))
        row.addWidget(self.fsr4_progress, 1)
        assets.addRow(row)
        assets.addRow(self._label(_("From FireBurn/Q2RTX on GitHub (built from AMD's MIT-licensed FidelityFX source), "
                                   'about 30 MB, into the fsr4_shaders folder of the port.')))
        self.fsr411_card = QGroupBox(_('FSR 4.1.1 (experimental)'))
        native = QVBoxLayout(self.fsr411_card)
        native.setContentsMargins(16, 20, 16, 14)
        self.fsr411_status_label = note(native, '')
        self.fsr411_native_label = note(native, '')
        row = QHBoxLayout()
        self.fsr411_button = button(row, 'Download fsr4vk', self.download_fsr411)
        self.fsr411_button.setObjectName('button:fsr4vk')
        self.fsr411_progress = QProgressBar()
        self.fsr411_progress.setRange(0, 100)
        row.addWidget(self.fsr411_progress, 1)
        self.fsr411_recheck = button(row, 'Recheck support', self.recheck_support)
        native.addLayout(row)
        self.fsr411_install_note = note(native, '')
        row = QHBoxLayout()
        button(row, 'Open the folder', self.open_fsr411_folder)
        self.cancel_button = button(row, 'Cancel download', self.cancel_downloads)
        row.addStretch()
        native.addLayout(row)
        self.body.addWidget(self.fsr411_card)

    def fsr411_status(self, method):
        return fsr411.method_status(backend.PORT_DIR, backend.DATA_DIR, method, self.fsr411_support,
            backend.fetch_fsr4vk, fsr411.environment(backend.PORT_DIR, self.settings),
            output_res=self._output_value, preset=self.ini_widgets['preset'].currentData())

    def fsr411_folder(self):
        return fsr411.vulkan_folder(backend.PORT_DIR, backend.DATA_DIR, fsr411.environment(backend.PORT_DIR, self.settings))

    def open_fsr411_folder(self):
        env = fsr411.environment(backend.PORT_DIR, self.settings)
        if backend.WINDOWS:
            folder = self.fsr411_folder()
        else:
            folder = Path(env['BB_FSR411_DIR']) if env.get('BB_FSR411_DIR') else (
                backend.PORT_DIR / 'fsr4_411' if (backend.PORT_DIR / 'fsr4_411').is_dir() else backend.DATA_DIR / 'fsr4_411')
            if not folder.is_absolute():
                folder = backend.PORT_DIR / folder
        try:
            open_path(folder)
        except OSError as error:
            QMessageBox.critical(self, 'FSR 4.1.1', str(error))

    def refresh_fsr4(self):
        total, missing = len(backend.fsr4_files()), len(backend.fsr4_missing())
        self.fsr4_status.setText(_('Installed: {} files in {}.').format(total, backend.PORT_DIR / 'fsr4_shaders') if not missing
            else _('{} of {} files missing in {}.').format(missing, total, backend.PORT_DIR / 'fsr4_shaders'))
        if not self.downloading:
            self.fsr4_progress.setRange(0, total)
            self.fsr4_progress.setValue(total - missing)
        self.fsr4_progress.setVisible(bool(missing))
        self.fsr4_button.setEnabled(bool(missing) and not self.downloading and not self.fsr411_downloading and not self.running)
        self.cancel_button.setVisible(self.downloading or self.fsr411_downloading)

    def refresh_fsr411(self):
        active = self.ini_widgets['upscaler'].currentData() == 'fsr411'
        self.backend_label.setVisible(active)
        self.backend_holder.setVisible(active)
        self.fsr411_card.setVisible(active)
        vk = self.fsr411_status('vk')
        statuses = {'vk': vk}
        if backend.WINDOWS:
            statuses['dx12'] = self.fsr411_status('dx12')
            self.fsr411_status_label.setText(_('Vulkan (fsr4vk)') + ': ' + fsr411.hint(vk, _))
            self.fsr411_native_label.setText(_('AMD DX12') + ': ' + fsr411.message(statuses['dx12'], _))
            self.fsr411_install_note.setText(_('Download fsr4vk here. AMD DX12 is included.'))
        else:
            self.fsr411_status_label.setText(_('Vulkan (portable shaders)') + ': ' + fsr411.message(vk, _))
            self.fsr411_native_label.setText('')
            self.fsr411_install_note.setText(_('Install the portable fsr4_411 shader files in the folder shown above. '
                                             'BB_FSR411_DIR can select another folder. GPU support is checked when the game starts.'))
        chosen = self.backend_choice.currentData() or self.graphics.get('fsr411_backend', 'vk')
        options = backend.FSR411_BACKENDS
        labels = {value: _(*text) for value, text in options}
        if fsr411.needs_download(vk) and backend.WINDOWS:
            labels['vk'] = _(fsr411.VULKAN_DOWNLOAD_LABEL)
        blocker = QSignalBlocker(self.backend_choice)
        self.backend_choice.clear()
        for method, _text in options:
            self.backend_choice.addItem(labels[method], method)
            offer = method == 'vk' and backend.WINDOWS and not self.running and fsr411.can_download(vk, self.fsr411_support)
            self.backend_choice.model().item(self.backend_choice.count() - 1).setEnabled(statuses[method]['supported'] or offer)
        index = self.backend_choice.findData(chosen)
        if index < 0:
            self.backend_choice.addItem(str(chosen), chosen)
            index = self.backend_choice.count() - 1
            self.backend_choice.model().item(index).setEnabled(False)
        self.backend_choice.setCurrentIndex(index)
        self.backend_choice.setEnabled(active and not self.running and not self.downloading and not self.fsr411_downloading)
        del blocker
        caps = self.fsr411_support
        hardware_ok = caps is None or caps['vk']['supported'] or caps['vk']['reason'] == 'check'
        installed = backend.fetch_fsr4vk.files_ok(self.fsr411_folder()) if backend.WINDOWS else False
        self.fsr411_button.setEnabled(backend.WINDOWS and hardware_ok and not installed and not self.running and
                                     not self.downloading and not self.fsr411_downloading)
        self.fsr411_progress.setVisible(self.fsr411_downloading)
        self.fsr411_recheck.setEnabled(not self._checking)
        self.cancel_button.setVisible(self.downloading or self.fsr411_downloading)

    def _select_backend(self, index):
        method = self.backend_choice.itemData(index)
        previous = self.graphics.get('fsr411_backend', 'vk')
        status = self.fsr411_status(method)
        if status['supported']:
            self.settings_changed.emit()
            return
        if method == 'vk' and backend.WINDOWS and not self.running and fsr411.can_download(status, self.fsr411_support):
            answer = QMessageBox.question(self, _(fsr411.DOWNLOAD_TITLE), _(fsr411.DOWNLOAD_QUESTION),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self._activate_backend = True
                self.download_fsr411()
        self.backend_choice.setCurrentIndex(self.backend_choice.findData(previous))

    def recheck_support(self):
        if self._checking:
            return
        self._checking = True
        self.fsr411_support = self.fg401_support = None
        self._refresh_choices()
        self.refresh_fsr411()
        self.fg_recheck.setEnabled(False)
        signal = self.support_finished
        port, env = backend.PORT_DIR, fsr411.environment(backend.PORT_DIR, self.settings)
        def work():
            caps = fsr411.query(port, env, refresh=True)
            fg = fg401.query(port, env)
            try:
                signal.emit(caps, fg)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _support_done(self, caps, fg):
        self._checking = False
        self.fsr411_support, self.fg401_support = caps, fg
        self.fg_recheck.setEnabled(True)
        self._refresh_choices()
        self.refresh_fsr411()

    def _start_download(self, kind, folder, names=None):
        if self.running or self.downloading or self.fsr411_downloading:
            return
        self._cancel.clear()
        self.downloading, self.fsr411_downloading = kind == 'fsr4', kind == 'fsr411'
        self.refresh_fsr4()
        self.refresh_fsr411()
        self.busy_changed.emit(True)
        progress, finished = self.download_progress, self.download_finished
        cancel, base = self._cancel, backend.FSR4_BASE
        def report(done, total):
            try:
                progress.emit(kind, done, total)
            except RuntimeError:
                cancel.set()
        def work():
            error, cancelled = '', False
            try:
                if kind == 'fsr4':
                    download_fsr4_assets(folder, names, base, report, cancel)
                else:
                    download_fsr411_assets(folder, report, cancel)
            except DownloadCancelled:
                cancelled = True
            except (OSError, ValueError, backend.fetch_fsr4vk.FetchError) as failure:
                error = str(failure)
            try:
                finished.emit(kind, error, cancelled)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def download_fsr4(self):
        self._start_download('fsr4', backend.PORT_DIR / 'fsr4_shaders', backend.fsr4_missing())

    def download_fsr411(self):
        if backend.WINDOWS:
            self._start_download('fsr411', self.fsr411_folder())

    def cancel_downloads(self):
        self._cancel.set()

    def _download_progress(self, kind, done, total):
        widget = self.fsr4_progress if kind == 'fsr4' else self.fsr411_progress
        widget.setRange(0, max(1, total))
        widget.setValue(done)

    def _download_done(self, kind, error, cancelled):
        self.downloading = self.fsr411_downloading = False
        self.refresh_fsr4()
        self.refresh_fsr411()
        if kind == 'fsr411' and self._activate_backend and not error and not cancelled and self.fsr411_status('vk')['supported']:
            self.backend_choice.setCurrentIndex(self.backend_choice.findData('vk'))
            self.settings_changed.emit()
        self._activate_backend = False
        self.busy_changed.emit(False)
        if error:
            QMessageBox.critical(self, 'FSR 4.1.1' if kind == 'fsr411' else 'FSR 4', _('Download failed: {}').format(error))

    def set_game_running(self, running):
        self.running = running
        if running:
            self.cancel_downloads()
        for widget in [*self.app_widgets.values(), *self.ini_widgets.values(), self.output_combo, self.output_custom]:
            widget.setEnabled(not running)
        self.sharpness_slider.setEnabled(not running)
        self._refresh_choices()
        self.refresh_fsr4()
        self.refresh_fsr411()

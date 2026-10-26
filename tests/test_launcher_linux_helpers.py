# SPDX-License-Identifier: GPL-2.0-or-later
"""Native platform helpers for the shared launcher, without a game or display server."""
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'launcher'), str(ROOT / 'scripts')]

import bbport_display as display
import bbport_frame as frame
import bbport_hardware as hardware
import bbport_tray as tray


@unittest.skipIf(os.name == 'nt', 'Linux platform helpers')
class LinuxHelpersTests(unittest.TestCase):
    def test_unavailable_tray_keeps_the_window_accessible(self):
        self.assertFalse(tray.AVAILABLE)
        with self.assertRaises(OSError):
            tray.Tray('unused.ico', 'Test', lambda: None, lambda: None)

    def test_native_frame_is_kept(self):
        native = frame.Frame(0, [])
        self.assertFalse(native.install())
        self.assertIsNone(frame.picture(0, 100, 100))
        native.uninstall()

    def test_window_placement_does_not_start_windows_thread(self):
        find = mock.Mock(side_effect=AssertionError('must leave placement to the compositor'))
        with mock.patch.object(display.threading, 'Thread') as thread:
            placer = display.Placer({}, (1280, 800), find).start()
            placer.step()
            placer.stop()
        thread.assert_not_called()
        find.assert_not_called()
        self.assertFalse(display.WINDOW_PLACEMENT_SUPPORTED)
        self.assertEqual(display.game_windows(), [])

    def test_hyprland_monitor_physical_size_rotation_and_reserved_space(self):
        result = SimpleNamespace(stdout='''[
            {"name":"DP-1","description":"Scaled screen","x":0,"y":0,
             "width":3840,"height":2160,"scale":2,"reserved":[0,30,0,0]},
            {"name":"DP-2","x":1920,"y":0,"width":1920,"height":1080,"transform":1}
        ]''')
        with mock.patch.dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE='test'), \
                mock.patch.object(display.subprocess, 'run', return_value=result):
            monitors = display.monitors()
        self.assertEqual(monitors[0].size, (3840, 2160))
        self.assertEqual(monitors[0].work, (0, 60, 3840, 2160))
        self.assertEqual(display.monitor_dpi(monitors[0]), 192)
        self.assertEqual(monitors[1].size, (1080, 1920))
        self.assertEqual(monitors[0].name, 'Scaled screen')

    def test_xrandr_fallback_when_hyprland_is_unavailable(self):
        result = SimpleNamespace(stdout='''DP-1 connected 1920x1080-1920+0 (normal)
eDP-1 connected primary 2560x1600+0+0 (normal)
DP-2 disconnected (normal)
''')
        with mock.patch.dict(os.environ, HYPRLAND_INSTANCE_SIGNATURE='test', DISPLAY=':0'), \
                mock.patch.object(display.subprocess, 'run', side_effect=[FileNotFoundError, result]), \
                mock.patch.dict(sys.modules, {'gi': None}):
            monitors = display.monitors()
        self.assertEqual(monitors[0].size, (2560, 1600))
        self.assertEqual(monitors[0].device, 'eDP-1')
        self.assertEqual(monitors[1].rect, (-1920, 0, 0, 1080))

    def test_no_display_does_not_open_a_toolkit_or_call_xrandr(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(display.subprocess, 'run') as run:
            self.assertEqual(display.monitors(), [])
        run.assert_not_called()

    def test_missing_xrandr_does_not_prevent_launcher_start(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True), \
                mock.patch.object(display.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(display.monitors(), [])

    def test_cpu_name_and_instruction_support_come_from_linux(self):
        info = 'model name : AMD Ryzen 7 7800X3D\nflags : avx bmi1 abm movbe\n'
        with mock.patch.object(hardware.Path, 'read_text', return_value=info):
            self.assertEqual(hardware.processor_name(), 'AMD Ryzen 7 7800X3D')
            self.assertEqual(hardware.processor_support(), 'ok')
        with mock.patch.object(hardware.Path, 'read_text', return_value='flags : avx abm movbe\n'):
            self.assertEqual(hardware.processor_support(), 'compat')
        with mock.patch.object(hardware.Path, 'read_text', return_value='flags : sse2\n'):
            self.assertEqual(hardware.processor_support(), 'none')

    def test_memory_uses_physical_pages(self):
        values = {'SC_PHYS_PAGES': 16 * 1024 ** 3 // 4096, 'SC_PAGE_SIZE': 4096}
        with mock.patch.object(hardware.os, 'sysconf', side_effect=values.__getitem__):
            self.assertEqual(hardware.memory_gb(), 16)

    def test_sdl3_system_library_lookup(self):
        try:
            pad = importlib.import_module('bbport_pad')
        except ImportError as error:
            self.skipTest(str(error))
        with mock.patch.object(pad.Path, 'is_file', return_value=False), \
                mock.patch.object(pad.ctypes.util, 'find_library', return_value='libSDL3.so.0'):
            self.assertEqual(pad.sdl_path(ROOT), 'libSDL3.so.0')

    def test_tk_style_loads_with_linux_fonts_and_icons(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            import bbport_theme as theme
        except ImportError as error:
            self.skipTest(str(error))
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.withdraw()
        theme.load_fonts(root)
        theme.Theme(root, 1.0).style(ttk.Style(root))
        ttk.Label(root, text=' '.join(theme.ICON.values())).pack()
        root.update_idletasks()
        self.assertTrue(theme.BODY)
        self.assertFalse(any(0xE000 <= ord(character) <= 0xF8FF
                             for glyph in theme.ICON.values() for character in glyph))


if __name__ == '__main__':
    unittest.main()

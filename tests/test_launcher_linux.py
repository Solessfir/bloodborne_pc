"""The shared launcher uses native Linux paths and retains existing GTK profiles."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import bbport_launcher_win as launcher


@unittest.skipIf(os.name == 'nt', 'Linux integration')
class LinuxLauncherTests(unittest.TestCase):
    def test_direct_play_uses_saved_preferences_and_writes_a_persistent_log(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            ini = data / 'bbport.ini'
            ini.write_text('upscaler=dlss\npreset=2\noutput_res=2560x1600\n')
            settings = {**launcher.APP_DEFAULTS, 'game_dir': str(data / 'game'),
                        'user_dir': str(data / 'user'), 'frame_cap': '90',
                        'frame_stats': True, 'auto_backup': False}
            command = [sys.executable, '-c', 'import os; print("native-runner", os.environ["BB_FPS_LIMIT"], os.environ["BB_FRAME_STATS"])']
            with patch.multiple(launcher, DATA_DIR=data, PORT_DIR=data), \
                    patch.dict(os.environ, BB_CONFIG=str(ini)), \
                    patch.object(launcher, 'run_command', return_value=command):
                self.assertEqual(launcher.play_without_window(settings), 0)
            self.assertIn('native-runner 90 1', (data / 'user/last_run.log').read_text())
            self.assertEqual(ini.read_text(), 'upscaler=dlss\npreset=2\noutput_res=2560x1600\n')

    def test_existing_profile_keeps_preferences_and_skips_automatic_reconfiguration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            original = {'game_dir': '/games/Bloodborne/game', 'fps_limit': 90, 'mangohud': True,
                        'hdr': True, 'frame_stats': True, 'extra_env': 'BB_ONLINE=0'}
            path.write_text(json.dumps(original))
            with patch.object(launcher, 'CONFIG_FILE', path):
                loaded = launcher.load_profile()
            self.assertEqual(loaded['frame_cap'], '90')
            self.assertTrue(loaded['setup_done'])
            self.assertFalse(loaded['auto_graphics'])
            self.assertEqual(json.loads(path.read_text()), original)
            env = launcher.game_environment({**launcher.APP_DEFAULTS, **loaded}, launcher.INI_DEFAULTS)
            self.assertEqual(env['BB_GAME_DIR'], original['game_dir'])
            self.assertEqual(env['BB_FPS_LIMIT'], '90')
            self.assertEqual(env['MANGOHUD'], '1')
            self.assertEqual(env['BB_ONLINE'], '0')
            self.assertEqual(launcher.game_process_options(), {'start_new_session': True})

    def test_stop_terminates_the_game_process_group(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                   start_new_session=True)
        job = launcher.GameJob(process)
        try:
            job.terminate()
            self.assertEqual(process.wait(timeout=5), -15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            job.close()

    @unittest.skipUnless(os.environ.get('DISPLAY'), 'Needs a display for Tk')
    def test_all_settings_pages_open_on_linux(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        errors = []
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            profile = data / 'settings.json'
            profile.write_text(json.dumps({'setup_done': True, 'auto_graphics': False,
                                          'check_updates': False, 'ui_mode': 'expert',
                                          'seen_version': launcher.VERSION}))
            with patch.multiple(launcher, DATA_DIR=data, CONFIG_DIR=data, CONFIG_FILE=profile), \
                    patch.dict(os.environ, BB_CONFIG=str(data / 'bbport.ini')), \
                    patch.object(launcher, 'hunters_online', return_value=None):
                root = tk.Tk()
                root.withdraw()
                root.report_callback_exception = lambda *error: errors.append(error)
                try:
                    ui = launcher.Launcher(root, tk, ttk, filedialog, messagebox)
                    for page in list(ui.pages):
                        ui.show(page)
                        root.update()
                    self.assertIsNone(ui.titlebar)
                    self.assertEqual(ui.app['ui_mode'], 'expert')
                    self.assertFalse(errors, errors)
                finally:
                    root.destroy()

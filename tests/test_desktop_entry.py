"""Install and remove menu entries without touching the user's application menu."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from paths import ROOT


class DesktopEntryTests(unittest.TestCase):
    def test_install_launch_remove(self):
        try:
            import gi
            gi.require_version('GioUnix', '2.0')
            from gi.repository import GioUnix
        except (ImportError, ValueError):
            self.skipTest('PyGObject is needed to test desktop-entry execution')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Bloodborne $ ` " \\ % space'
            launcher = root / 'launcher'
            launcher.mkdir(parents=True)
            for name in ('install-desktop.sh', 'io.github.bbport.Launcher.desktop.in', 'bloodborne.png'):
                shutil.copy2(ROOT / 'launcher' / name, launcher / name)
            (root / 'launch.sh').write_text('#!/bin/bash\nprintf "%s" "$*" > "$(dirname -- "$0")/started"\n')
            env = dict(os.environ, XDG_DATA_HOME=str(Path(directory) / 'data'))
            script = launcher / 'install-desktop.sh'
            entry = Path(env['XDG_DATA_HOME']) / 'applications/io.github.bbport.Launcher.desktop'
            subprocess.run(['bash', str(script), 'remove'], env=env, check=True, capture_output=True)
            subprocess.run(['bash', str(script), 'install'], env=env, check=True, capture_output=True)
            self.assertTrue(entry.is_file())
            if shutil.which('desktop-file-validate'):
                subprocess.run(['desktop-file-validate', str(entry)], check=True, capture_output=True)
            app = GioUnix.DesktopAppInfo.new_from_filename(str(entry))
            self.assertIsNotNone(app)
            self.assertTrue(app.launch([], None))
            for _ in range(100):
                if (root / 'started').exists():
                    break
                time.sleep(0.01)
            self.assertTrue((root / 'started').exists())
            self.assertEqual((root / 'started').read_text(), '')
            (root / 'started').unlink()
            subprocess.run(['bash', str(script), '--play'], env=env, check=True, capture_output=True)
            app = GioUnix.DesktopAppInfo.new_from_filename(str(entry))
            self.assertTrue(app.launch([], None))
            for _ in range(100):
                if (root / 'started').exists() and (root / 'started').read_text() == '--play':
                    break
                time.sleep(0.01)
            self.assertEqual((root / 'started').read_text(), '--play')
            for action in ('-r', 'remove'):
                subprocess.run(['bash', str(script), action], env=env, check=True, capture_output=True)
                self.assertFalse(entry.exists())
            result = subprocess.run(['bash', str(script), 'invalid'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 2)

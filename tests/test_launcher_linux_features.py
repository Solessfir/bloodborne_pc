"""Native launcher helpers keep saves safe and distinguish portable features from Windows APIs."""
from paths import ROOT
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(ROOT / 'launcher'))
import bbport_benchmark as bench
import bbport_fg401 as fg
import bbport_fsr411 as fsr
import bbport_help as help_
import bbport_saves as saves
import bbport_setup as setup
import bbport_steam as steam


@unittest.skipIf(os.name == 'nt', 'Linux helpers')
class LinuxFeaturesTests(unittest.TestCase):
    def test_memory_uses_available_ram_and_swap(self):
        meminfo = 'MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\nSwapTotal: 4194304 kB\nSwapFree: 2097152 kB\n'
        with patch.object(help_.Path, 'read_text', return_value=meminfo):
            self.assertEqual(help_.memory_status(), (10, 20, 16))
        with patch.object(help_.Path, 'read_text', return_value='MemTotal: invalid kB'):
            self.assertIsNone(help_.memory_status())

    def test_linux_help_does_not_offer_windows_tuning(self):
        self.assertNotIn('smartscreen', help_.TOPICS)
        self.assertNotIn('page_file', help_.TOPIC_ACTIONS)
        self.assertNotIn('antivirus', help_.TOPIC_ACTIONS)
        self.assertIn('swap', str(help_.TOPICS['page_file']).lower())
        self.assertNotIn('NVIDIA App', str(help_.TOPICS['driver']))

    def test_recycle_uses_gio_and_keeps_files_when_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            save = Path(folder) / '-backup.zip'
            save.write_bytes(b'keep')
            with patch.object(saves.subprocess, 'run', side_effect=FileNotFoundError):
                self.assertFalse(saves.to_recycle_bin(save))
            self.assertEqual(save.read_bytes(), b'keep')
            with patch.object(saves.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
                self.assertFalse(saves.to_recycle_bin(save))
            self.assertEqual(save.read_bytes(), b'keep')

            def trash(command, **_kwargs):
                self.assertEqual(command, ['gio', 'trash', '--', str(save)])
                save.unlink()
                return types.SimpleNamespace(returncode=0)

            with patch.object(saves.subprocess, 'run', side_effect=trash):
                self.assertTrue(saves.to_recycle_bin(save))

    def test_save_scan_includes_xdg_locations(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'XDG_DATA_HOME': str(Path(folder) / 'data'), 'XDG_CONFIG_HOME': str(Path(folder) / 'config')}):
            paths = saves.sources(ROOT)
            self.assertIn(str(Path(folder) / 'data/shadPS4/home/*/savedata/*/SPRJ0005'), paths)
            self.assertIn(str(Path(folder) / 'config/shadPS4/savedata/*/*/SPRJ0005'), paths)

    def test_trashing_backup_symlink_keeps_its_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target, link = Path(folder) / 'original.zip', Path(folder) / 'link.zip'
            target.write_bytes(b'original')
            link.symlink_to(target)

            def trash(command, **_kwargs):
                self.assertEqual(command[-1], str(link))
                Path(command[-1]).unlink()
                return types.SimpleNamespace(returncode=0)

            with patch.object(saves.subprocess, 'run', side_effect=trash):
                self.assertTrue(saves.to_recycle_bin(link))
            self.assertEqual(target.read_bytes(), b'original')

    def test_steam_finds_native_and_flatpak_data(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(steam.Path, 'home', return_value=Path(folder)), \
                patch.dict(os.environ, {'XDG_DATA_HOME': str(Path(folder) / 'data')}):
            self.assertIsNone(steam.steam_folder())
            flatpak = Path(folder) / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
            flatpak.mkdir(parents=True)
            self.assertEqual(steam.steam_folder(), flatpak)
            native = Path(folder) / 'data/Steam'
            native.mkdir(parents=True)
            self.assertEqual(steam.steam_folder(), native)

    def test_steam_process_detection_reads_proc(self):
        with tempfile.TemporaryDirectory() as folder:
            comm = Path(folder) / 'comm'
            comm.write_text('steamwebhelper\n')
            with patch.object(steam.Path, 'glob', return_value=[comm]):
                self.assertFalse(steam.steam_running())
                comm.write_text('steam\n')
                self.assertTrue(steam.steam_running())

    def test_steam_shortcuts_preserve_linux_filename_case(self):
        with tempfile.TemporaryDirectory() as folder:
            vdf = Path(folder) / 'shortcuts.vdf'
            self.assertEqual(steam.add_shortcut(vdf, 'Game', '/games/Play', '/games', ''), 'added')
            self.assertEqual(steam.add_shortcut(vdf, 'Game', '/games/play', '/games', ''), 'added')
            self.assertEqual(steam.add_shortcut(vdf, 'Game', '/games/Play', '/games', ''), 'updated')

    def test_native_game_processes_are_detected_without_windows_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            process = Path(folder) / '4242'
            process.mkdir()
            (process / 'exe').symlink_to('/games/bb-probe')
            with patch.object(bench.Path, 'glob', return_value=[process]):
                self.assertEqual(bench.game_pids(), [4242])
                self.assertEqual(bench.game_pids('other'), [])
            self.assertIsNone(bench.game_window(4242))

    def test_benchmark_rejects_unsupported_host_before_touching_files(self):
        self.assertFalse(bench.supported())
        task = bench.Test.__new__(bench.Test)
        task.emit = Mock()
        task.work_thread('/missing-save')
        task.emit.assert_called_once_with('error', bench.unsupported_reason())
        run = bench.Run.__new__(bench.Run)
        with self.assertRaisesRegex(OSError, 'require Windows'):
            run.go()
        ui = setup.SetupMixin.__new__(setup.SetupMixin)
        ui.messagebox = types.SimpleNamespace(showinfo=Mock())
        with patch.object(setup, 'L', types.SimpleNamespace(_=lambda *texts: texts[0])):
            ui.start_benchmark()
        ui.messagebox.showinfo.assert_called_once()

    def test_backup_reveal_opens_parent_folder(self):
        ui = setup.SetupMixin.__new__(setup.SetupMixin)
        ui.open_path = Mock()
        ui.show_backup(types.SimpleNamespace(path=Path('/tmp/save-backups/one.zip')))
        ui.open_path.assert_called_once_with(Path('/tmp/save-backups'))

    def test_system_page_reports_native_os(self):
        ui = setup.SetupMixin.__new__(setup.SetupMixin)
        ui.rating, ui.cpu = None, None
        ui.var = lambda *_args: types.SimpleNamespace(get=lambda: str(ROOT))
        with patch.object(setup, 'L', types.SimpleNamespace(PORT_DIR=ROOT, _=lambda *texts: texts[0])):
            state, label = ui.your_pc()['OS']
        self.assertEqual(state, 'ok')
        self.assertTrue(label.startswith('Linux '))

    def test_window_controls_explain_compositor_placement(self):
        import tkinter as tk
        from tkinter import ttk
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.withdraw()
        ui = setup.SetupMixin.__new__(setup.SetupMixin)
        ui.ttk, ui.px = ttk, lambda size: size
        with patch.object(setup, 'L', types.SimpleNamespace(_=lambda *texts: texts[0])), \
                patch.object(setup.display, 'WINDOW_PLACEMENT_SUPPORTED', False):
            widget = ui.window_choice(root)
        self.assertEqual(widget.setting_key, 'window_size')
        self.assertEqual(len(widget.winfo_children()), 1)
        self.assertIn('compositor', widget.winfo_children()[0].cget('text'))

    @staticmethod
    def shader_model(folder, name):
        model = folder / name
        model.mkdir(parents=True)
        names = ['spd', 'prepass', 'pass0_post', 'postpass', 'rcas']
        names += [f'pass{i}{suffix}' for i in range(1, 13) for suffix in ('', '_post')]
        for shader in names:
            (model / f'{shader}.spv').write_bytes(bytes(20))
        (model / 'initializer.bin').write_bytes(bytes(131072))

    def test_portable_fsr411_validates_selected_model_without_windows_download(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(fsr, 'WINDOWS', False):
            root = Path(folder)
            caps = fsr.query(root)
            fetch = Mock()
            self.assertTrue(caps['vk']['supported'])
            self.assertEqual(caps['vk']['reason'], 'runtime_check')
            self.assertFalse(caps['dx12']['supported'])
            self.assertEqual(fsr.method_status(root, root, 'vk', caps, fetch)['reason'], 'portable_files')
            self.shader_model(root / 'fsr4_411', 't1080_m0')
            status = fsr.method_status(root, root, 'vk', caps, fetch)
            self.assertTrue(status['supported'])
            self.assertIn('checked when the game starts', fsr.message(status, str))
            self.assertFalse(fsr.can_download(status, caps))
            self.assertFalse(fsr.method_status(root, root, 'vk', caps, fetch,
                                               output_res='2560x1440', preset=4)['supported'])
            self.shader_model(root / 'fsr4_411', 't2160_m1')
            self.assertTrue(fsr.method_status(root, root, 'vk', caps, fetch,
                                              output_res='2560x1440', preset=4)['supported'])
            fetch.verified.assert_not_called()

    def test_native_capability_paths_and_platform_restrictions(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(fsr, 'WINDOWS', False), \
                patch.object(fg, 'WINDOWS', False):
            root = Path(folder)
            (root / 'bin').mkdir()
            for module, name in ((fsr, 'bb-gpu-capabilities'), (fg, 'bb-fg401-capabilities')):
                self.assertEqual(module.executable(root), root / 'out' / name)
                (root / 'bin' / name).touch()
                self.assertEqual(module.executable(root), root / 'bin' / name)
            with patch.dict(os.environ, {'PATH': '/usr/bin'}, clear=True):
                self.assertEqual(fsr.environment(root)['PATH'], '/usr/bin')
            self.assertEqual(fsr.default_backend(root), 'vk')
            self.assertEqual(fg.query(root)['reason'], 'platform')
            self.assertIn('Windows 11', fg.message(fg.query(root), str))
            self.assertEqual(fsr.method_status(root, root, 'dx12', None, Mock())['reason'], 'platform')


if __name__ == '__main__':
    unittest.main()

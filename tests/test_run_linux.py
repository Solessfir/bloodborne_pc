"""Native runner commands and environment, using disposable game/probe stand-ins."""
from paths import ROOT
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('bbport_run_linux', ROOT / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


@unittest.skipUnless(sys.platform.startswith('linux'), 'native Linux runner')
class LinuxRunnerTests(unittest.TestCase):
    def fixture(self, directory, packaged=True):
        port = Path(directory) / 'port with spaces'
        binaries = port / ('bin' if packaged else 'out')
        binaries.mkdir(parents=True)
        game = port / 'game'
        game.mkdir()
        (game / 'eboot.bin').touch()
        (game / 'sce_module').mkdir()
        (game / 'sce_sys').mkdir()
        (game / 'sce_sys' / 'param.sfo').touch()
        config = port / 'bbport.ini'
        config.write_text('quit_to_desktop=0\nrebirth=0\nupscaler=dlss\npreset=1\n'
                          'output_res=2560x1600\nlive_resolution=1\n')
        probe = binaries / 'bb-probe'
        probe.write_text(f'#!{sys.executable}\n'
                         'import json, os, sys\n'
                         'from pathlib import Path\n'
                         'Path(os.environ["BB_TEST_RECORD"]).write_text(json.dumps({\n'
                         ' "argv": sys.argv, "env": dict(os.environ), "pid": os.getpid(),\n'
                         ' "group": os.getpgrp()}))\n'
                         'if os.environ.get("BB_TEST_WAIT") == "1":\n'
                         ' import time\n'
                         ' time.sleep(60)\n')
        probe.chmod(0o755)
        caps = binaries / 'bb-gpu-capabilities'
        caps.write_text('#!/bin/sh\nif [ "$1" = "--vram" ]; then echo "24000 1"; else echo 1; fi\n')
        caps.chmod(0o755)
        env = {'PATH': os.defpath, 'XDG_RUNTIME_DIR': str(port), 'BB_GAME_DIR': str(game), 'BB_DATA_DIR': str(port),
               'BB_CONFIG': str(config), 'BB_FORCE_PATCHES': '1', 'BB_SKIP_GAME_CHECK': '1',
               'BB_TEST_RECORD': str(port / 'record.json'), 'BB_ONLINE': '0'}
        return port, probe, env

    def launch(self, packaged=True, overrides=None, scaled=None, missing_caps=False, upscaler='dlss'):
        with tempfile.TemporaryDirectory() as directory:
            port, probe, env = self.fixture(directory, packaged)
            env.update(overrides or {})
            if upscaler != 'dlss':
                config = Path(env['BB_CONFIG'])
                config.write_text(config.read_text().replace('upscaler=dlss', f'upscaler={upscaler}'))
            if missing_caps:
                (probe.parent / 'bb-gpu-capabilities').unlink()
            scripts = []

            def prepare(name, *args, **kwargs):
                scripts.append((name, [str(arg) for arg in args]))
                if name == 'mods.py':
                    return env['BB_GAME_DIR'] + '\n'
                if name == 'patches.py' and '--print-scaled' in args:
                    if scaled is not None:
                        return scaled
                    return subprocess.check_output([sys.executable, str(ROOT / 'scripts/patches.py'),
                                                    *map(str, args)], text=True)
                return None

            previous = Path.cwd()
            try:
                with mock.patch.object(run, 'PORT', port), mock.patch.object(run, 'run_script', prepare), \
                     mock.patch.object(run, 'prepare_driver_environment', lambda env: env), \
                     mock.patch.dict(os.environ, env, clear=True), \
                     mock.patch.object(sys, 'argv', [str(ROOT / 'run.py'), '--cpu-only']):
                    self.assertEqual(run.main(), 0)
                record = json.loads((port / 'record.json').read_text())
                record['scripts'] = scripts
                record['probe'] = str(probe)
                return record
            finally:
                os.chdir(previous)

    def test_packaged_and_development_native_commands_preserve_sixteen_ten(self):
        for packaged in (True, False):
            with self.subTest(packaged=packaged):
                record = self.launch(packaged)
                self.assertEqual(record['argv'][0], record['probe'])
                self.assertNotIn('.exe', record['argv'][0])
                self.assertEqual(record['argv'][-1], '--cpu-only')
                self.assertIn('--content-profile', record['argv'])
                self.assertIn('--patches', record['argv'])
                env = record['env']
                self.assertEqual(env['BB_UI_RES'], '1920x1200')
                self.assertEqual(env['BB_RENDER_RES'], '1706x1066')
                self.assertEqual(env['BB_OUTPUT_RES'], '2560x1600')
                self.assertEqual(env['BB_ONLINE'], '0')
                self.assertEqual(env['BB_VBLANK_HZ'], '0')
                self.assertEqual(record['group'], os.getpgrp())
                self.assertEqual([name for name, _ in record['scripts']],
                                 ['quit_menu.py', 'discord_names.py', 'mods.py', 'prepare.py', 'link_libc.py', 'link_modules.py',
                                  'content_profile.py', 'patches.py', 'patches.py'])
                restart = shlex.split(env['BB_RESTART_COMMAND'])
                self.assertEqual(restart[:2], [sys.executable, str(ROOT / 'run.py')])
                self.assertEqual(restart[2:4], ['--after', str(os.getpid())])
                self.assertEqual(restart[-1], '--cpu-only')

    def test_sixteen_ten_taa_keeps_the_native_scene_and_camera_patch(self):
        record = self.launch(upscaler='taa')
        self.assertEqual(record['env']['BB_RENDER_RES'], '2560x1600')
        self.assertEqual(record['env']['BB_OUTPUT_RES'], '2560x1600')
        self.assertEqual(record['env']['BB_UI_RES'], '1920x1200')

    def test_native_capability_checker_and_missing_checker(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                # Below 1080p auto consults the native checker without the DoF override.
                record = self.launch(overrides={'BB_LIVE_RES': 'auto'},
                                     scaled='854x480 1280x720', missing_caps=missing)
                if missing:
                    self.assertEqual(record['env']['BB_RENDER_RES'], '854x480')
                else:
                    self.assertNotIn('BB_RENDER_RES', record['env'])
                self.assertNotIn('BB_UI_RES', record['env'])

    def test_online_uses_the_same_hunters_dream_environment(self):
        record = self.launch(overrides={'BB_ONLINE': '1', 'BB_NET_BACKEND': 'thd',
                                      'BB_THD_TOKEN': 'fake-token', 'BB_THD_ONLINE_ID': 'TestHunter',
                                      'BB_SHADNET_TOKEN': 'stale-token'})
        env = record['env']
        self.assertEqual(env['BB_THD_ONLINE_ID'], 'TestHunter')
        self.assertEqual(env['BB_THD_SERVER'], run.HUNTERS_DREAM_SERVER + ':18671')
        self.assertEqual(env['BB_THD_RULESET'], 'vanilla')
        self.assertNotIn('BB_SHADNET_TOKEN', env)
        self.assertTrue(env['SHADPS4_HTTP_HOST_OVERRIDES_JSON'].endswith('/user/host_overrides.json'))

    def test_no_console_and_physical_cores_use_linux(self):
        self.assertEqual(run.no_console(), 0)
        with mock.patch.object(os, 'sched_getaffinity', return_value={0, 1, 2, 3}), \
             mock.patch.object(Path, 'read_text', lambda path: '0' if path.name == 'physical_package_id'
                               else str(int(path.parts[-3][3:]) // 2)):
            self.assertEqual(run.physical_cores(), 2)

    def test_after_waits_for_exit_and_accepts_unreaped_zombies(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.05)'])
        try:
            run.wait_for(child.pid)
            self.assertIsNotNone(child.poll())
            # An exited but unreaped runner must not block a restart for 30 seconds.
            child = subprocess.Popen([sys.executable, '-c', 'pass'])
            time.sleep(0.1)
            started = time.monotonic()
            with mock.patch.object(os, 'pidfd_open', side_effect=OSError):
                run.wait_for(child.pid)
            self.assertLess(time.monotonic() - started, 2)
        finally:
            child.wait()
        with self.assertRaises(ValueError):
            run.wait_for(0)

    def test_termination_stops_only_its_game_and_removes_the_mod_view(self):
        with tempfile.TemporaryDirectory() as directory:
            port, _probe, env = self.fixture(directory)
            view = port / 'mod view'
            view.mkdir()
            env['BB_TEST_WAIT'] = '1'
            bootstrap = port / 'runner.py'
            bootstrap.write_text(
                'import importlib.util, os, signal, sys\n'
                'from pathlib import Path\n'
                f'sys.path.insert(0, {str(ROOT / "scripts")!r})\n'
                f'spec=importlib.util.spec_from_file_location("runner", {str(ROOT / "run.py")!r})\n'
                'run=importlib.util.module_from_spec(spec); spec.loader.exec_module(run)\n'
                f'run.PORT=Path({str(port)!r})\n'
                f'run.run_script=lambda name,*args,**kwargs: {str(view)!r} if name=="mods.py" else ""\n'
                'run.prepare_driver_environment=lambda env: env\n'
                'signal.signal(signal.SIGTERM, run.terminate)\n'
                'sys.exit(run.main())\n')
            process = subprocess.Popen([sys.executable, str(bootstrap)], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       start_new_session=True)
            try:
                record_path = Path(env['BB_TEST_RECORD'])
                deadline = time.monotonic() + 5
                while not record_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(record_path.is_file(), 'fake game did not start')
                record = json.loads(record_path.read_text())
                process.terminate()  # Signal the runner alone, as a standalone invocation can receive.
                _, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 128 + signal.SIGTERM, error.decode())
                self.assertFalse(view.exists())
                with self.assertRaises(ProcessLookupError):
                    os.kill(record['pid'], 0)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                process.stderr.close()

    def test_help_has_no_game_side_effects(self):
        result = subprocess.run([sys.executable, str(ROOT / 'run.py'), '--help'],
                                capture_output=True, text=True, timeout=5,
                                env={'PATH': os.defpath})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BB_GAME_DIR', result.stdout)


if __name__ == '__main__':
    unittest.main()

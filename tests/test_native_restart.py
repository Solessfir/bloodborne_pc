"""Exercise the native restart implementation without loading a game or touching saves."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('cc'), 'Linux C compiler required')
class NativeRestartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        source = (ROOT / 'src/probe.c').read_text()
        function = source[source.index('void runtime_restart(void) {'):source.index('\nint main(')]
        harness = '#define _GNU_SOURCE\n#include <stdio.h>\n#include <stdlib.h>\n#include <unistd.h>\n#include <sys/types.h>\n#include <sys/syscall.h>\n'
        harness += function + '\nint main(void) { setvbuf(stdout,NULL,_IONBF,0); printf("original-group:%ld\\n",(long)getpgrp()); runtime_restart(); }\n'
        path = cls.folder / 'restart.c'
        path.write_text(harness)
        cls.binary = cls.folder / 'restart'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(cls.binary)],
                       check=True, capture_output=True)

    def test_configured_command_preserves_arguments_output_and_process_group(self):
        code = 'import os,sys; print("replacement-group:"+str(os.getpgrp())); print(sys.argv[1])'
        argument = 'a path with spaces, $ and "quotes"'
        command = shlex.join([sys.executable, '-c', code, argument])
        result = subprocess.run([str(self.binary)], env=dict(os.environ, BB_RESTART_COMMAND=command),
                                start_new_session=True, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('restarting through run.py', result.stdout)
        self.assertIn(argument, result.stdout)
        groups = [line.split(':')[1] for line in result.stdout.splitlines() if '-group:' in line]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0], groups[1])

    def test_legacy_shell_entry_point_remains_available(self):
        (self.folder / 'run.sh').write_text('printf "legacy-shell-entry\\n"\n')
        env = dict(os.environ)
        env.pop('BB_RESTART_COMMAND', None)
        result = subprocess.run([str(self.binary)], cwd=self.folder, env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('legacy-shell-entry', result.stdout)

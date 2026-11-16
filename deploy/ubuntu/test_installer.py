# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = (r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else shutil.which('bash'))


@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is required')
class InstallerArgumentsTest(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([BASH, 'deploy/ubuntu/install.sh', *args], cwd=ROOT,
                              capture_output=True, encoding='utf-8', timeout=10)

    def test_default_plan(self):
        result = self.run_script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('127.0.0.1:8090/scm/', result.stdout)

    def test_custom_plan(self):
        result = self.run_script('--dry-run', '--bind-ip', '192.168.10.20',
                                 '--http-port', '18090', '--data-dir', '/srv/team-scm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('192.168.10.20:18090', result.stdout)
        self.assertIn('/srv/team-scm', result.stdout)

    def test_reject_invalid_arguments(self):
        cases = [('--http-port', '22'), ('--http-port', '65536'), ('--http-port', 'abc'),
                 ('--bind-ip', '0.0.0.0'), ('--bind-ip', '256.1.1.1'),
                 ('--data-dir', '/'), ('--data-dir', '/srv/../etc'),
                 ('--data-dir', '/var/lib/docker'), ('--data-dir', '/etc/scm'),
                 ('--name', 'bad;name'), ('--image', 'latest'), ('--bind-ip',),
                 ('--unknown',)]
        for args in cases:
            with self.subTest(args=args):
                self.assertNotEqual(self.run_script('--dry-run', *args).returncode, 0)


if __name__ == '__main__':
    unittest.main()

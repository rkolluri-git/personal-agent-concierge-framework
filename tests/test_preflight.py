"""Exercise dependency failures without Docker, installs, or household configuration."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        for name in ['preflight.sh', 'start.sh']:
            shutil.copy2(ROOT / name, self.project / name)
        for name in ['Dockerfile', 'docker-compose.yml', 'backend/requirements.txt', 'backend/regional_settings.py']:
            target = self.project / name
            target.parent.mkdir(exist_ok=True)
            target.touch()
        (self.project / '.env').write_text('POSTGRES_PASSWORD=unit-test-password\n')
        self.bin = self.project / 'bin'
        self.bin.mkdir()
        for name in ['dirname', 'awk', 'uname']:
            (self.bin / name).symlink_to(shutil.which(name))
        self.env = dict(os.environ, PATH=str(self.bin))

    def docker(self, mode='ready'):
        script = self.bin / 'docker'
        script.write_text('''#!/bin/sh
case "$1 $2" in
  "compose version") [ "$MOCK_DOCKER" != missing_compose ] ;;
  "compose config") [ "$MOCK_DOCKER" != bad_config ] ;;
  "compose up") echo START_CALLED ;;
  "info ") [ "$MOCK_DOCKER" != stopped ] ;;
  "image inspect") exit 1 ;;
  "inspect --format")
    if [ "$MOCK_DOCKER" = conflict ]; then echo /some/other/project; else exit 1; fi ;;
  *) exit 1 ;;
esac
''')
        script.chmod(0o755)
        self.env['MOCK_DOCKER'] = mode

    def run_check(self, *args, start=False):
        return subprocess.run(['/bin/sh', str(self.project / ('start.sh' if start else 'preflight.sh')), *args],
                              env=self.env, text=True, capture_output=True, timeout=10)

    def test_core_needs_no_host_python_and_missing_images_are_notes(self):
        self.docker()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('first build will download', result.stdout)
        self.assertNotIn('unit-test-password', result.stdout + result.stderr)

    def test_missing_docker_has_actionable_failure(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn('Docker is missing', result.stdout)

    def test_compose_daemon_config_and_container_conflict_failures(self):
        for mode in ['missing_compose', 'stopped', 'bad_config', 'conflict']:
            with self.subTest(mode=mode):
                self.docker(mode)
                self.assertEqual(self.run_check().returncode, 1)

    def test_missing_env_and_placeholder_fail_without_echoing_secret(self):
        self.docker()
        (self.project / '.env').unlink()
        self.assertEqual(self.run_check().returncode, 1)
        (self.project / '.env').write_text('POSTGRES_PASSWORD="replace-with-a-long-random-password"\n')
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('replace-with-a-long-random-password', result.stdout)

    def test_env_contents_are_never_executed(self):
        self.docker()
        marker = self.project / 'should-not-exist'
        (self.project / '.env').write_text(f'POSTGRES_PASSWORD=$(echo unsafe > {marker})\n')
        self.run_check()
        self.assertFalse(marker.exists())

    def test_start_refuses_build_on_failure(self):
        self.docker('stopped')
        result = self.run_check(start=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('START_CALLED', result.stdout)
        self.docker()
        result = self.run_check(start=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('START_CALLED', result.stdout)

    def test_bridge_rejects_non_macos(self):
        (self.bin / 'uname').unlink()
        fake = self.bin / 'uname'
        fake.write_text('#!/bin/sh\necho Linux\n')
        fake.chmod(0o755)
        self.docker()
        result = self.run_check('--macos')
        self.assertEqual(result.returncode, 1)
        self.assertIn('requires macOS', result.stdout)

    def test_unknown_option_is_an_error_and_help_succeeds(self):
        self.assertEqual(self.run_check('--unknown').returncode, 2)
        self.assertEqual(self.run_check('--help').returncode, 0)

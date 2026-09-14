from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from macos import self_healing


class WeeklySelfHealingTests(unittest.TestCase):
    def test_weekly_slot_starts_sunday_at_seven(self):
        zone = ZoneInfo("America/New_York")
        self.assertIsNone(self_healing.weekly_slot(datetime(2026, 9, 13, 6, 59, tzinfo=zone)))
        self.assertEqual(self_healing.weekly_slot(datetime(2026, 9, 13, 7, 0, tzinfo=zone)), "2026-W37")
        self.assertIsNone(self_healing.weekly_slot(datetime(2026, 9, 14, 7, 0, tzinfo=zone)))

    def test_same_week_is_not_run_twice(self):
        zone = ZoneInfo("America/New_York")
        now = datetime(2026, 9, 13, 9, 0, tzinfo=zone)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            with patch.object(self_healing, "CONFIG_DIR", config), \
                 patch.object(self_healing, "LOCK_PATH", config / "self-healing.lock"), \
                 patch.object(self_healing, "read_state", return_value={"slot": "2026-W37"}), \
                 patch.object(self_healing, "run_weekly_validation") as run:
                self.assertIsNone(self_healing.maybe_run_weekly_validation(now))
                run.assert_not_called()

    def test_parallel_weekly_run_is_skipped(self):
        zone = ZoneInfo("America/New_York")
        now = datetime(2026, 9, 13, 9, 0, tzinfo=zone)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            lock_path = config / "self-healing.lock"
            with patch.object(self_healing, "CONFIG_DIR", config), \
                 patch.object(self_healing, "LOCK_PATH", lock_path), \
                 patch.object(self_healing, "read_state", return_value={}):
                with lock_path.open("a+") as lock:
                    self_healing.fcntl.flock(lock.fileno(), self_healing.fcntl.LOCK_EX | self_healing.fcntl.LOCK_NB)
                    with patch.object(self_healing, "run_weekly_validation") as run:
                        self.assertIsNone(self_healing.maybe_run_weekly_validation(now))
                        run.assert_not_called()

    def test_private_permissions_are_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config = project / "config"
            config.mkdir(mode=0o755)
            secret = config / "token.json"
            secret.write_text("private", encoding="utf-8")
            secret.chmod(0o644)
            env = project / ".env"
            env.write_text("SECRET=value", encoding="utf-8")
            env.chmod(0o644)
            traffic = config / "traffic_eta"
            traffic.write_text("binary", encoding="utf-8")
            traffic.chmod(0o600)
            actions = []
            with patch.object(self_healing, "PROJECT_DIR", project), \
                 patch.object(self_healing, "CONFIG_DIR", config):
                self_healing.repair_private_permissions(actions)
            self.assertEqual(config.stat().st_mode & 0o777, 0o700)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual(traffic.stat().st_mode & 0o777, 0o700)
            self.assertTrue(actions)

    def test_command_timeout_becomes_a_failed_result(self):
        with patch("macos.self_healing.subprocess.run", side_effect=self_healing.subprocess.TimeoutExpired("docker", 1)):
            result = self_healing.run_command(["docker", "compose", "ps"], timeout=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()

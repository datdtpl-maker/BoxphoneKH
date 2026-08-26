import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import call, patch

from adb_controller import ADBController
from gui_app import GUIApp


def portrait_execute_recorder(commands):
    def execute(device_id, args, timeout=15):
        commands.append((device_id, tuple(args)))
        if "dumpsys input" in " ".join(args):
            return (
                0,
                "ACCELEROMETER_ROTATION=0\n"
                "USER_ROTATION=0\n"
                "SurfaceOrientation: 0",
                "",
            )
        if args[-2:] == ["dumpsys", "input"]:
            return 0, "SurfaceOrientation: 0", ""
        return 0, "", ""

    return execute


class ADBPerformanceTests(unittest.TestCase):
    def test_screen_size_queries_share_device_cache(self):
        controller = ADBController(adb_path="adb")
        commands = []

        def execute(device_id, args, timeout=15):
            commands.append((device_id, tuple(args)))
            return (
                0,
                "Physical size: 1440x2560\nOverride size: 1080x1920",
                "",
            )

        controller.execute_adb = execute

        self.assertEqual(
            (1080, 1920),
            controller.get_effective_screen_size("device-1"),
        )
        self.assertEqual(
            (1440, 2560), controller.get_screen_size("device-1")
        )
        self.assertEqual(1, len(commands))

    @patch("adb_controller.time.sleep", return_value=None)
    def test_portrait_lock_coalesces_repeated_calls(self, _sleep):
        controller = ADBController(adb_path="adb")
        commands = []
        controller.execute_adb = portrait_execute_recorder(commands)

        self.assertTrue(controller.lock_portrait("device-1"))
        self.assertTrue(controller.lock_portrait("device-1"))

        self.assertLessEqual(
            len(commands),
            2,
            "Hai lần khóa liên tiếp không được phát 28 lệnh ADB.",
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_portrait_guard_40_devices_stays_within_command_budget(self, _sleep):
        controller = ADBController(adb_path="adb")
        commands = []
        controller.execute_adb = portrait_execute_recorder(commands)

        for index in range(40):
            controller.lock_portrait(f"device-{index:02d}")

        self.assertLessEqual(
            len(commands),
            80,
            "Một vòng khóa dọc 40 máy phải dùng tối đa 2 lệnh/máy.",
        )

    def test_adb_process_concurrency_is_bounded(self):
        controller = ADBController(
            adb_path="adb", max_parallel_commands=4
        )
        active = 0
        peak = 0
        guard = threading.Lock()

        def fake_run(*_args, **_kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("adb_controller.subprocess.run", side_effect=fake_run):
            with ThreadPoolExecutor(max_workers=20) as executor:
                list(executor.map(lambda _index: controller._run_cmd(["devices"]), range(20)))

        self.assertLessEqual(peak, 4)

    def test_background_portrait_guard_skips_active_workflows(self):
        app = GUIApp.__new__(GUIApp)
        app.run_in_thread = lambda action, *args: action(*args)

        with (
            patch("gui_app.main.adb.is_device_workflow_active") as active,
            patch("gui_app.main.adb.device_workflow_scope") as scope,
            patch("gui_app.main.adb.lock_portrait", return_value=True) as lock,
        ):
            active.side_effect = lambda device_id: device_id == "device-1"
            scope.return_value.__enter__.return_value = None
            scope.return_value.__exit__.return_value = False
            app.bulk_disable_rotation(
                ["device-1", "device-2"], skip_busy=True
            )

        lock.assert_called_once_with("device-2")

    def test_background_guard_does_not_overlap_previous_bulk_lock(self):
        app = GUIApp.__new__(GUIApp)
        app.run_in_thread = lambda action, *args: action(*args)
        app._bulk_rotation_lock = threading.Lock()
        app._bulk_rotation_lock.acquire()

        try:
            with patch(
                "gui_app.main.adb.lock_portrait", return_value=True
            ) as lock:
                app.bulk_disable_rotation(
                    ["device-1"],
                    sync=True,
                    skip_if_running=True,
                )
        finally:
            app._bulk_rotation_lock.release()

        lock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

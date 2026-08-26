import unittest
from unittest.mock import call, patch

from adb_controller import ADBController
from gui_app import GUIApp


class OrientationLockTests(unittest.TestCase):
    def test_effective_screen_size_prefers_android_override(self):
        controller = ADBController(adb_path="adb")
        controller.execute_adb = lambda *_args, **_kwargs: (
            0,
            "Physical size: 1440x2560\nOverride size: 1080x1920",
            "",
        )

        self.assertEqual(
            (1080, 1920),
            controller.get_effective_screen_size("device-override"),
        )

    def test_lock_portrait_disables_sensor_and_verifies_portrait(self):
        controller = ADBController(adb_path="adb")
        commands = []

        def execute(_device_id, args, timeout=15):
            commands.append(args)
            if args[-3:] == ["system", "accelerometer_rotation", "0"]:
                return 0, "", ""
            if args[-3:] == ["system", "user_rotation", "0"]:
                return 0, "", ""
            if "get" in args and args[-1] == "accelerometer_rotation":
                return 0, "0", ""
            if "get" in args and args[-1] == "user_rotation":
                return 0, "0", ""
            return 0, "", ""

        controller.execute_adb = execute

        self.assertTrue(controller.lock_portrait("device-1"))
        self.assertTrue(
            any(
                "settings put secure show_rotation_suggestions 0"
                in " ".join(command)
                for command in commands
            )
        )

    def test_gui_locks_every_connected_device_in_portrait(self):
        app = GUIApp.__new__(GUIApp)
        app.run_in_thread = lambda action, *args: action(*args)

        with patch.object(
            __import__("gui_app").main.adb,
            "lock_portrait",
            return_value=True,
        ) as lock_mock:
            app.bulk_disable_rotation(["device-1", "device-2"])

        self.assertCountEqual(
            [call("device-1"), call("device-2")],
            lock_mock.call_args_list,
        )

    @patch("adb_controller.time.sleep", return_value=None)
    def test_launch_tiktok_relocks_portrait_during_app_transition(
        self, _sleep
    ):
        controller = ADBController(adb_path="adb")
        controller.execute_adb = (
            lambda _device_id, _args, timeout=15: (0, "", "")
        )
        controller.dismiss_tiktok_location_popup = lambda _device_id: False
        locks = []
        controller.lock_portrait = (
            lambda device_id, retries=2:
            locks.append((device_id, retries)) or True
        )

        controller.launch_tiktok("device-transition")

        self.assertGreaterEqual(
            len(locks),
            4,
            "Phải khóa dọc trước, trong và sau khi TikTok đổi activity",
        )
        self.assertTrue(
            all(device_id == "device-transition" for device_id, _ in locks)
        )


if __name__ == "__main__":
    unittest.main()

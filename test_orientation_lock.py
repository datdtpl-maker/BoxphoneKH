import unittest
from unittest.mock import call, patch

from adb_controller import ADBController
from gui_app import GUIApp


class OrientationLockTests(unittest.TestCase):
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
        self.assertIn(
            [
                "shell", "settings", "put", "secure",
                "show_rotation_suggestions", "0",
            ],
            commands,
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


if __name__ == "__main__":
    unittest.main()

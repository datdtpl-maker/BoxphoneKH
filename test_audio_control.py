import unittest
from unittest.mock import call, patch

from adb_controller import ADBController
from gui_app import GUIApp


class _FakeButton:
    def __init__(self):
        self.states = []

    def configure(self, **kwargs):
        self.states.append(kwargs)


class AudioControlTests(unittest.TestCase):
    def test_mute_media_sets_stream_to_zero_and_verifies(self):
        controller = ADBController(adb_path="adb")
        commands = []

        def execute(_device_id, args, timeout=15):
            commands.append(args)
            if "--get" in args:
                return 0, "[v] volume is 0 in range [0..15]", ""
            return 0, "", ""

        controller.execute_adb = execute

        self.assertTrue(controller.mute_media_volume("device-1"))
        self.assertEqual(
            [
                [
                    "shell", "media", "volume", "--stream", "3",
                    "--set", "0",
                ],
                [
                    "shell", "media", "volume", "--stream", "3",
                    "--get",
                ],
            ],
            commands,
        )

    def test_gui_mutes_every_connected_device_once(self):
        app = GUIApp.__new__(GUIApp)
        app.btn_mute_all = _FakeButton()
        app.run_in_thread = lambda action, *args: action(*args)
        app.after = lambda _delay, callback: callback()

        with (
            patch(
                "gui_app.main.get_ordered_devices",
                return_value=["device-1", "device-2"],
            ),
            patch(
                "gui_app.main.adb.mute_media_volume",
                return_value=True,
            ) as mute_mock,
        ):
            app.mute_all_devices_action()

        self.assertCountEqual(
            [call("device-1"), call("device-2")],
            mute_mock.call_args_list,
        )
        self.assertEqual(
            {"state": "normal", "text": "Tắt âm tất cả"},
            app.btn_mute_all.states[-1],
        )


if __name__ == "__main__":
    unittest.main()

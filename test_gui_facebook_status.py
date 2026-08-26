import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui_app import GUIApp


class _Entry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FacebookGuiStatusTests(unittest.TestCase):
    def test_sequential_facebook_passes_both_keyword_layers(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_fb_selection = _Entry("1")
        app.ent_fb_seed = _Entry("mụn, chăm sóc da")
        app.ent_fb_target = _Entry("Thương Hiệu Mẫu")
        app.parse_targets = lambda entry_widget=None: ["device-1"]
        app.bulk_disable_rotation = lambda target_devices=None, **_kwargs: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        calls = []
        cleared = []

        def workflow(device_id, **kwargs):
            calls.append((device_id, kwargs))
            kwargs["status_callback"](
                device_id, "[Facebook B1] Đang nuôi Feed..."
            )
            return True, "Thành công"

        fake_adb = SimpleNamespace(
            facebook_automation_workflow=workflow,
            clear_recent_apps=lambda device_id: cleared.append(device_id) or True,
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="1"),
            patch("builtins.print"),
        ):
            app.run_seq_facebook()

        self.assertEqual(1, len(calls))
        self.assertEqual("device-1", calls[0][0])
        self.assertEqual("mụn, chăm sóc da", calls[0][1]["seed_keywords"])
        self.assertEqual(
            "Thương Hiệu Mẫu", calls[0][1]["target_pages"]
        )
        self.assertEqual(["device-1"], cleared)

    def test_parallel_facebook_has_one_realtime_tracker_per_device(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_fb_selection = _Entry("1-2")
        app.ent_fb_seed = _Entry("mụn, chăm sóc da")
        app.ent_fb_target = _Entry("Thương Hiệu Mẫu")
        app.parse_targets = (
            lambda entry_widget=None: ["device-1", "device-2"]
        )
        app.bulk_disable_rotation = lambda target_devices=None, **_kwargs: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        trackers = []
        cleared = []

        class FakeTracker:
            def __init__(self, *_args, **_kwargs):
                self.device_name = None
                self.statuses = []
                trackers.append(self)

            def set_active_device(
                self,
                device_name,
                *_args,
                **_kwargs,
            ):
                self.device_name = device_name

            def render_progress_text(self):
                return "Facebook realtime"

            def start_dashboard(self, _text):
                return None

            def status_callback(self, _device_id, message):
                self.statuses.append(message)

            def finish_dashboard(self, _text):
                return None

        def workflow(device_id, **kwargs):
            kwargs["status_callback"](
                device_id, "[Facebook B2] Đang tìm từ khóa mồi"
            )
            return True, "Thành công"

        fake_adb = SimpleNamespace(
            facebook_automation_workflow=workflow,
            clear_recent_apps=lambda device_id: cleared.append(device_id) or True,
        )
        names = {"device-1": "1", "device-2": "2"}

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", [123]),
            patch("gui_app.main.adb", fake_adb),
            patch(
                "gui_app.main.get_device_name",
                side_effect=lambda device_id: names[device_id],
            ),
            patch(
                "gui_app.main.TelegramRealtimeTracker",
                side_effect=FakeTracker,
            ),
            patch("gui_app.main.safe_send_message"),
            patch("builtins.print"),
        ):
            app.run_par_facebook()

        self.assertCountEqual(["1", "2"], [t.device_name for t in trackers])
        self.assertTrue(all(tracker.statuses for tracker in trackers))
        self.assertCountEqual(["device-1", "device-2"], cleared)


if __name__ == "__main__":
    unittest.main()

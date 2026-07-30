import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from gui_app import GUIApp


class ShopeeTelegramLoggingTests(unittest.TestCase):
    def test_profile_tracker_finishes_as_detailed_report(self):
        sent_message = SimpleNamespace(message_id=77)

        with (
            patch("main.safe_send_message", return_value=sent_message),
            patch("main.safe_edit_message") as edit_mock,
        ):
            tracker = main.start_shopee_profile_tracker(
                123,
                "S5",
                "device-5",
                "từ khóa mẫu",
                5,
                13,
            )
            main.finish_shopee_profile_tracker(
                tracker,
                True,
                "",
                136,
            )

        report = edit_mock.call_args.args[0]
        self.assertIn("BÁO CÁO CHI TIẾT: PROFILE S5", report)
        self.assertIn("từ khóa mẫu", report)
        self.assertIn("2 phút 16 giây", report)
        self.assertIn("HOÀN THÀNH", report)

    @patch("main.time.sleep", return_value=None)
    @patch("main.random.randint", return_value=60)
    @patch("main.random.sample", return_value=["key-1", "key-2"])
    def test_sequential_starts_next_profile_log_after_previous_report(
        self,
        _sample,
        _randint,
        _sleep,
    ):
        events = []
        message = SimpleNamespace(chat=SimpleNamespace(id=123))
        fake_adb = SimpleNamespace(
            shopee_find_and_click_lamdong=(
                lambda *_args, **_kwargs: (True, "")
            )
        )

        def start_tracker(
            _chat_id,
            dev_name,
            _dev_id,
            _keyword,
            _current_idx,
            _total_devices,
            **_kwargs,
        ):
            events.append(f"start:{dev_name}")
            return SimpleNamespace(
                device_name=dev_name,
                status_callback=lambda *_args, **_kwargs: None,
            )

        def finish_tracker(tracker, *_args, **_kwargs):
            events.append(f"finish:{tracker.device_name}")

        with (
            patch("main.adb", fake_adb),
            patch(
                "main.get_device_name",
                side_effect=lambda dev: {
                    "device-1": "S1",
                    "device-2": "S2",
                }[dev],
            ),
            patch(
                "main.start_shopee_profile_tracker",
                side_effect=start_tracker,
            ),
            patch(
                "main.finish_shopee_profile_tracker",
                side_effect=finish_tracker,
            ),
            patch(
                "main.send_shopee_rest_countdown",
                side_effect=lambda _chat_id, next_name, *_args, **_kwargs:
                events.append(f"rest:{next_name}"),
            ),
            patch("main.safe_send_message"),
        ):
            main.run_sequential_shopee_search(
                message,
                ["key-1", "key-2"],
                ["device-1", "device-2"],
                use_ai=False,
            )

        self.assertEqual(
            [
                "start:S1",
                "finish:S1",
                "rest:S2",
                "start:S2",
                "finish:S2",
            ],
            events,
        )

    def test_parallel_creates_realtime_tracker_for_each_profile(self):
        app = GUIApp.__new__(GUIApp)
        app.keyword_mode = SimpleNamespace(get=lambda: "original")
        app.txt_main_keywords = SimpleNamespace(
            get=lambda *_args: "key-1\nkey-2"
        )
        app.ent_selection = SimpleNamespace()
        app.parse_targets = (
            lambda entry_widget=None: ["device-1", "device-2"]
        )
        app.run_in_thread = lambda action: action()

        started = []
        finished = []

        def start_tracker(
            _chat_id,
            dev_name,
            _dev_id,
            _keyword,
            _current_idx,
            _total_devices,
            **_kwargs,
        ):
            started.append(dev_name)
            return SimpleNamespace(
                device_name=dev_name,
                status_callback=lambda *_args, **_kwargs: None,
            )

        def run_workflow(
            device_id,
            _keyword,
            status_callback=None,
            **_kwargs,
        ):
            self.assertIsNotNone(status_callback)
            status_callback(device_id, "Đang chạy")
            return True, ""

        fake_adb = SimpleNamespace(
            shopee_find_and_click_lamdong=run_workflow
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", [123]),
            patch("gui_app.main.adb", fake_adb),
            patch(
                "gui_app.main.get_device_name",
                side_effect=lambda device_id: {
                    "device-1": "S1",
                    "device-2": "S2",
                }[device_id],
            ),
            patch(
                "gui_app.main.start_shopee_profile_tracker",
                side_effect=start_tracker,
            ),
            patch(
                "gui_app.main.finish_shopee_profile_tracker",
                side_effect=lambda tracker, *_args, **_kwargs:
                finished.append(tracker.device_name),
            ),
            patch("gui_app.main.safe_send_message"),
        ):
            app.run_par_search()

        self.assertCountEqual(["S1", "S2"], started)
        self.assertCountEqual(["S1", "S2"], finished)


if __name__ == "__main__":
    unittest.main()

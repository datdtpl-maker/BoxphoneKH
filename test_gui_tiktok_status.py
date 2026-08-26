import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gui_app import GUIApp


class _Entry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class TikTokGuiStatusTests(unittest.TestCase):
    def test_sequential_success_clears_recents_before_finishing(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_selection = _Entry("1")
        app.ent_tt_seed = _Entry("chăm sóc da")
        app.ent_tt_channel = _Entry("Kênh TikTok Mẫu")
        app.parse_targets = lambda entry_widget=None: ["device-1"]
        app.bulk_disable_rotation = lambda target_devices=None, **_kwargs: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None
        events = []

        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (
                events.append("workflow") or (True, "Thành công")
            ),
            clear_recent_apps=lambda device_id: events.append(
                ("clear", device_id)
            ) or True,
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="1"),
            patch("builtins.print"),
        ):
            app.run_seq_tiktok()

        self.assertEqual(["workflow", ("clear", "device-1")], events)

    def test_sequential_run_reports_failure_instead_of_completed(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_selection = _Entry("1")
        app.ent_tt_seed = _Entry("chăm sóc da phan thiết")
        app.ent_tt_channel = _Entry("Kênh TikTok Mẫu")
        app.parse_targets = lambda entry_widget=None: ["device-1"]
        app.bulk_disable_rotation = lambda target_devices=None, **_kwargs: None
        app.run_in_thread = lambda action: action()
        app.log_message = lambda _message: None

        fake_adb = SimpleNamespace(
            tiktok_automation_workflow=lambda *_args, **_kwargs: (
                False,
                "Không thể nhập chính xác từ khóa TikTok",
            )
        )

        with (
            patch("gui_app.config.ALLOWED_USER_IDS", []),
            patch("gui_app.main.adb", fake_adb),
            patch("gui_app.main.get_device_name", return_value="1"),
            patch("gui_app.main.TelegramRealtimeTracker") as tracker_mock,
            patch("gui_app.main.safe_send_message") as send_mock,
            patch.object(
                __import__("gui_app").main.bot,
                "send_message",
            ) as bot_send_mock,
            patch("builtins.print") as print_mock,
        ):
            app.run_seq_tiktok()

        tracker_mock.assert_not_called()
        send_mock.assert_not_called()
        bot_send_mock.assert_not_called()

        output = "\n".join(
            " ".join(str(part) for part in call.args)
            for call in print_mock.call_args_list
        )
        self.assertIn("THẤT BẠI", output)
        self.assertIn("KẾT THÚC CÓ LỖI", output)
        self.assertNotIn("Hoàn tất tiến trình chạy TikTok Tuần Tự!", output)


if __name__ == "__main__":
    unittest.main()

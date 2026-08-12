import unittest
from unittest.mock import patch

import gui_app
import main


class TelegramTaskRoutingTests(unittest.TestCase):
    def test_command_parser_selects_only_one_platform(self):
        shopee = main.parse_natural_command(
            "tìm tuần tự lâm đồng kem trị mụn"
        )
        tiktok = main.parse_natural_command(
            "/tiktok tuần tự từ khóa mẫu | Kênh TikTok Mẫu"
        )

        self.assertEqual("shopee_search_lamdong_sequential", shopee["action"])
        self.assertEqual("tiktok_automation", tiktok["action"])

    def test_gui_bot_startup_drops_pending_updates_only_once(self):
        app = gui_app.GUIApp.__new__(gui_app.GUIApp)
        background_calls = []
        app.run_in_thread = (
            lambda func, *args: background_calls.append((func, args))
        )
        app.start_bot_service()
        self.assertEqual(1, len(background_calls))

        polling_calls = []

        def fail_once_then_stop(*args, **kwargs):
            polling_calls.append((args, kwargs))
            if len(polling_calls) == 1:
                raise RuntimeError("mất mạng tạm thời")
            raise KeyboardInterrupt

        with (
            patch.object(gui_app.config, "TELEGRAM_BOT_TOKEN", "123:token"),
            patch.object(gui_app.time, "sleep", return_value=None),
            patch.object(
                gui_app.main.bot,
                "polling",
                side_effect=fail_once_then_stop,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                background_calls[0][0](*background_calls[0][1])

        self.assertTrue(
            polling_calls[0][1].get("skip_pending"),
            "Lần polling đầu phải bỏ lệnh tồn từ phiên trước",
        )
        self.assertFalse(
            polling_calls[1][1].get("skip_pending"),
            "Khi reconnect không được bỏ lệnh mới",
        )


if __name__ == "__main__":
    unittest.main()

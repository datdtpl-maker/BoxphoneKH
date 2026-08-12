import unittest
from unittest.mock import patch

import gui_app
import main


class _FakeButton:
    def __init__(self):
        self.state = {}

    def configure(self, **kwargs):
        self.state.update(kwargs)


class TelegramNotificationToggleTests(unittest.TestCase):
    def test_invalid_token_uses_disabled_bot_without_crashing(self):
        disabled_bot = main.create_telegram_bot("")

        self.assertEqual(main.TELEGRAM_DISABLED_BOT_TOKEN, disabled_bot.token)
        self.assertFalse(main.is_valid_telegram_token(""))
        self.assertFalse(main.is_valid_telegram_token("invalid"))
        self.assertTrue(main.is_valid_telegram_token("123:abc"))

    def test_disabled_notifications_do_not_call_telegram_api(self):
        with (
            patch.object(main.config, "TELEGRAM_NOTIFICATIONS_ENABLED", False),
            patch.object(main.bot, "send_message") as send_message,
        ):
            result = main.safe_send_message(123, "test")

        send_message.assert_not_called()
        self.assertEqual(0, result.message_id)

    def test_toggle_persists_state_updates_button_and_stops_polling(self):
        app = gui_app.GUIApp.__new__(gui_app.GUIApp)
        app.btn_telegram_notifications = _FakeButton()
        persisted = []
        app._persist_env_setting = lambda key, value: persisted.append(
            (key, value)
        )

        with (
            patch.object(
                gui_app.config, "TELEGRAM_NOTIFICATIONS_ENABLED", True
            ),
            patch.object(gui_app.main.bot, "stop_polling") as stop_polling,
        ):
            app.toggle_telegram_notifications()

            self.assertFalse(gui_app.config.TELEGRAM_NOTIFICATIONS_ENABLED)
            self.assertEqual(
                [("TELEGRAM_NOTIFICATIONS_ENABLED", "0")], persisted
            )
            self.assertEqual(
                "Telegram: TẮT",
                app.btn_telegram_notifications.state["text"],
            )
            stop_polling.assert_called_once_with()

    def test_bot_service_does_not_poll_while_notifications_are_disabled(self):
        app = gui_app.GUIApp.__new__(gui_app.GUIApp)
        background_calls = []
        app.run_in_thread = (
            lambda func, *args: background_calls.append((func, args))
        )
        app.start_bot_service()

        with (
            patch.object(
                gui_app.config, "TELEGRAM_NOTIFICATIONS_ENABLED", False
            ),
            patch.object(gui_app.config, "TELEGRAM_BOT_TOKEN", "token:valid"),
            patch.object(gui_app.main.bot, "polling") as polling,
            patch.object(gui_app.time, "sleep", side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                background_calls[0][0](*background_calls[0][1])

        polling.assert_not_called()

    def test_bot_service_does_not_poll_with_invalid_token(self):
        app = gui_app.GUIApp.__new__(gui_app.GUIApp)
        background_calls = []
        app.run_in_thread = (
            lambda func, *args: background_calls.append((func, args))
        )
        app.start_bot_service()

        with (
            patch.object(
                gui_app.config, "TELEGRAM_NOTIFICATIONS_ENABLED", True
            ),
            patch.object(gui_app.config, "TELEGRAM_BOT_TOKEN", "invalid"),
            patch.object(gui_app.main.bot, "polling") as polling,
            patch.object(gui_app.time, "sleep", side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                background_calls[0][0](*background_calls[0][1])

        polling.assert_not_called()

    def test_cannot_enable_notifications_with_invalid_token(self):
        app = gui_app.GUIApp.__new__(gui_app.GUIApp)
        app.btn_telegram_notifications = _FakeButton()
        persisted = []
        app._persist_env_setting = lambda key, value: persisted.append(
            (key, value)
        )
        app.start_bot_service = lambda: self.fail("must not start polling")

        with (
            patch.object(
                gui_app.config, "TELEGRAM_NOTIFICATIONS_ENABLED", False
            ),
            patch.object(gui_app.config, "TELEGRAM_BOT_TOKEN", "invalid"),
            patch("gui_app.messagebox.showwarning") as showwarning,
        ):
            app.toggle_telegram_notifications()

            self.assertFalse(gui_app.config.TELEGRAM_NOTIFICATIONS_ENABLED)
            self.assertEqual(
                [("TELEGRAM_NOTIFICATIONS_ENABLED", "0")], persisted
            )
            showwarning.assert_called_once()


if __name__ == "__main__":
    unittest.main()

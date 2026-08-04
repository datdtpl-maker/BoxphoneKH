from io import BytesIO
import unittest
import urllib.error
from unittest.mock import patch

import config
from gui_app import GUIApp


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"candidates": []}'


class GeminiApiHealthTests(unittest.TestCase):
    def test_health_check_uses_current_flash_alias(self):
        with patch("config.urllib.request.urlopen", return_value=_Response()) as call:
            ok, code, message = config.check_gemini_api("secret-key")

        self.assertTrue(ok)
        self.assertEqual("ok", code)
        self.assertIn("gemini-flash-latest", message)
        request = call.call_args.args[0]
        self.assertIn("gemini-flash-latest:generateContent", request.full_url)
        self.assertNotIn("gemini-1.5-flash", request.full_url)

    def test_health_check_explains_retired_model(self):
        error = urllib.error.HTTPError(
            "https://example.invalid",
            404,
            "Not Found",
            {},
            BytesIO(b"{}"),
        )
        self.addCleanup(error.close)
        with patch("config.urllib.request.urlopen", side_effect=error):
            ok, code, message = config.check_gemini_api("secret-key")

        self.assertFalse(ok)
        self.assertEqual("model_not_found", code)
        self.assertIn("ngừng hỗ trợ", message)

    def test_health_check_explains_quota_error(self):
        error = urllib.error.HTTPError(
            "https://example.invalid",
            429,
            "Too Many Requests",
            {},
            BytesIO(b"{}"),
        )
        self.addCleanup(error.close)
        with patch("config.urllib.request.urlopen", side_effect=error):
            ok, code, message = config.check_gemini_api("secret-key")

        self.assertFalse(ok)
        self.assertEqual("quota_exceeded", code)
        self.assertIn("quota", message)

    def test_health_check_rejects_empty_key_without_network(self):
        with patch("config.urllib.request.urlopen") as call:
            ok, code, _message = config.check_gemini_api("")

        self.assertFalse(ok)
        self.assertEqual("missing_key", code)
        call.assert_not_called()

    def test_gui_check_uses_key_currently_entered_in_field(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_gemini_key = type(
            "Entry", (), {"get": lambda self: "new-unsaved-key"}
        )()
        button_updates = []
        app.btn_check_gemini = type(
            "Button",
            (),
            {"configure": lambda self, **kwargs: button_updates.append(kwargs)},
        )()
        app.run_in_thread = lambda action: action()
        app.after = lambda _delay, callback: callback()

        with (
            patch(
                "gui_app.config.check_gemini_api",
                return_value=(True, "ok", "Gemini hoạt động"),
            ) as check,
            patch("gui_app.messagebox.showinfo") as show,
            patch("builtins.print"),
        ):
            app.check_gemini_api_action()

        check.assert_called_once_with("new-unsaved-key")
        self.assertEqual("disabled", button_updates[0]["state"])
        self.assertEqual("normal", button_updates[-1]["state"])
        show.assert_called_once()


if __name__ == "__main__":
    unittest.main()

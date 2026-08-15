import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import config
from gui_app import GUIApp


class _Entry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value = value


class ConfigPersistenceTests(unittest.TestCase):
    def test_import_env_copies_file_and_loads_supported_fields(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_token = _Entry("")
        app.ent_admins = _Entry("")
        app.ent_adb = _Entry("")
        app.ent_shops = _Entry("")
        app.ent_gemini_key = _Entry("")
        app.ent_notion_token = _Entry("")
        app.ent_notion_source_id = _Entry("")
        app.ent_tt_channel = _Entry("")
        app.ent_fb_target = _Entry("")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "incoming.env"
            target = root / "runtime" / ".env"
            source.write_text(
                "TELEGRAM_BOT_TOKEN=123:placeholder\n"
                "ALLOWED_USER_IDS=100,200\n"
                "ADB_PATH=D:/tools/adb.exe\n"
                "SHOPEE_SHOP_NAMES=Shop A,Shop B\n"
                "TIKTOK_TARGET_CHANNEL=Target TikTok\n"
                "FACEBOOK_TARGET_PAGE_EXACT=Target Facebook\n"
                "NOTION_API_TOKEN=notion-placeholder\n",
                encoding="utf-8",
            )

            with (
                patch.object(config, "ENV_PATH", target),
                patch("gui_app.main.adb") as adb,
                patch("gui_app.main.configure_telegram_bot_token"),
            ):
                count, saved_path = app._import_env_file(source)

            self.assertEqual(target.resolve(), saved_path)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertGreaterEqual(count, 7)
            self.assertEqual("123:placeholder", app.ent_token.value)
            self.assertEqual("100,200", app.ent_admins.value)
            self.assertEqual("D:/tools/adb.exe", app.ent_adb.value)
            self.assertEqual("Shop A,Shop B", app.ent_shops.value)
            self.assertEqual("Target TikTok", app.ent_tt_channel.value)
            self.assertEqual("Target Facebook", app.ent_fb_target.value)
            self.assertEqual("D:/tools/adb.exe", adb.adb_path)

    def test_frozen_app_stores_env_beside_executable_not_meipass(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "BoxPhoneControl.exe"
            bundled_module = Path(folder) / "_MEI12345" / "config.py"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
            ):
                base_dir = config.resolve_runtime_base_dir(bundled_module)

        self.assertEqual(executable.parent, base_dir)

    def test_source_app_stores_env_beside_config_module(self):
        module_file = Path("C:/project/phone_telegram_bot/config.py")
        with patch.object(sys, "frozen", False, create=True):
            base_dir = config.resolve_runtime_base_dir(module_file)

        self.assertEqual(module_file.parent, base_dir)

    def test_save_settings_persists_notion_fields_to_runtime_env(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_token = _Entry("123:telegram-placeholder")
        app.ent_admins = _Entry("123")
        app.ent_adb = _Entry("adb.exe")
        app.ent_shops = _Entry("")
        app.ent_gemini_key = _Entry("gemini-placeholder")
        app.ent_notion_token = _Entry("notion-placeholder")
        app.ent_notion_source_id = _Entry("source-placeholder")

        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder) / ".env"
            with (
                patch.object(config, "ENV_PATH", env_path),
                patch("gui_app.main.bot"),
                patch("telebot.TeleBot", return_value=object()),
                patch("gui_app.messagebox.showinfo"),
                patch("builtins.print"),
            ):
                app.save_settings()

            saved = env_path.read_text(encoding="utf-8")

        self.assertIn("NOTION_API_TOKEN=notion-placeholder", saved)
        self.assertIn("NOTION_DATA_SOURCE_ID=source-placeholder", saved)

    def test_save_settings_with_invalid_telegram_token_does_not_crash(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_token = _Entry("")
        app.ent_admins = _Entry("123")
        app.ent_adb = _Entry("adb.exe")
        app.ent_shops = _Entry("")
        app.ent_gemini_key = _Entry("gemini-placeholder")
        app.ent_notion_token = _Entry("notion-placeholder")
        app.ent_notion_source_id = _Entry("source-placeholder")

        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder) / ".env"
            with (
                patch.object(config, "ENV_PATH", env_path),
                patch.object(config, "TELEGRAM_NOTIFICATIONS_ENABLED", True),
                patch("gui_app.messagebox.showwarning") as showwarning,
                patch("builtins.print"),
            ):
                app.save_settings()

            saved = env_path.read_text(encoding="utf-8")

        self.assertIn("TELEGRAM_NOTIFICATIONS_ENABLED=0", saved)
        self.assertIn("NOTION_API_TOKEN=notion-placeholder", saved)
        self.assertIn("NOTION_DATA_SOURCE_ID=source-placeholder", saved)
        showwarning.assert_called_once()


if __name__ == "__main__":
    unittest.main()

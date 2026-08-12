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


class ConfigPersistenceTests(unittest.TestCase):
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
        app.ent_token = _Entry("telegram-placeholder")
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


if __name__ == "__main__":
    unittest.main()

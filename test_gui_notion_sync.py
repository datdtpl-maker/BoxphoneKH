from datetime import date
import unittest
from unittest.mock import patch

from gui_app import GUIApp
from notion_keyword_sync import NotionKeywordSchedule


class _Entry:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value = value


class _Button:
    def __init__(self):
        self.calls = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


class GuiNotionSyncTests(unittest.TestCase):
    def test_scan_displays_enabled_schedules_for_user_choice(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_notion_token = _Entry("local-token")
        app.ent_notion_source_id = _Entry("source-id")
        app.ent_tt_seed = _Entry()
        app.ent_tt_channel = _Entry()
        app.ent_fb_seed = _Entry()
        app.ent_fb_target = _Entry()
        app.btn_scan_notion = _Button()
        app.run_in_thread = lambda action: action()
        app.after = lambda _delay, callback: callback()
        app.log_message = lambda _message: None
        schedule = NotionKeywordSchedule(
            page_id="page-id",
            title="Tuần hiện tại",
            start_date=date(2026, 8, 12),
            end_date=date(2026, 8, 18),
            active=True,
            tiktok_seed_keywords="chăm sóc da, skincare",
            tiktok_target_channels="kenh-a, kenh-b",
            facebook_seed_keywords="da khỏe, trị mụn",
            facebook_target_pages="Page A, Page B",
            admin_note="",
        )

        with (
            patch(
                "gui_app.fetch_enabled_keyword_schedules",
                return_value=[schedule],
            ),
            patch("gui_app.mark_schedule_processing") as processing,
            patch.object(app, "_show_notion_schedule_picker") as picker,
        ):
            app.scan_notion_keywords_action()

        processing.assert_called_once_with("local-token", "page-id")
        picker.assert_called_once_with([schedule], "local-token")
        self.assertEqual("normal", app.btn_scan_notion.calls[-1]["state"])

    def test_selected_schedule_loads_tiktok_and_facebook_fields(self):
        app = GUIApp.__new__(GUIApp)
        app.ent_tt_seed = _Entry()
        app.ent_tt_channel = _Entry()
        app.ent_fb_seed = _Entry()
        app.ent_fb_target = _Entry()
        app.run_in_thread = lambda action: action()
        app.after = lambda _delay, callback: callback()
        app.log_message = lambda _message: None
        app.btn_complete_notion = _Button()
        schedule = NotionKeywordSchedule(
            page_id="page-id",
            title="Tuần hiện tại",
            start_date=date(2026, 8, 12),
            end_date=date(2026, 8, 18),
            active=True,
            tiktok_seed_keywords="chăm sóc da, skincare",
            tiktok_target_channels="kenh-a, kenh-b",
            facebook_seed_keywords="da khỏe, trị mụn",
            facebook_target_pages="Page A, Page B",
            admin_note="",
        )

        with (
            patch("gui_app.mark_schedule_scanned") as mark,
            patch("gui_app.messagebox.showinfo") as show,
        ):
            app._load_notion_schedule(schedule, "local-token")

        self.assertEqual("chăm sóc da, skincare", app.ent_tt_seed.value)
        self.assertEqual("kenh-a, kenh-b", app.ent_tt_channel.value)
        self.assertEqual("da khỏe, trị mụn", app.ent_fb_seed.value)
        self.assertEqual("Page A, Page B", app.ent_fb_target.value)
        mark.assert_called_once_with("local-token", "page-id")
        self.assertEqual(schedule, app._active_notion_schedule)
        self.assertEqual("normal", app.btn_complete_notion.calls[-1]["state"])
        show.assert_called_once()

    def test_complete_button_syncs_notion_and_disables_itself(self):
        app = GUIApp.__new__(GUIApp)
        schedule = NotionKeywordSchedule(
            page_id="page-id",
            title="Tuần hiện tại",
            start_date=date(2026, 8, 12),
            end_date=date(2026, 8, 18),
            active=True,
            tiktok_seed_keywords="b",
            tiktok_target_channels="c",
            facebook_seed_keywords="d",
            facebook_target_pages="e",
        )
        app._active_notion_schedule = schedule
        app._active_notion_token = "local-token"
        app.btn_complete_notion = _Button()
        app.run_in_thread = lambda action: action()
        app.after = lambda _delay, callback: callback()
        app.log_message = lambda _message: None

        with (
            patch("gui_app.messagebox.askyesno", return_value=True),
            patch("gui_app.messagebox.showinfo") as show,
            patch("gui_app.mark_schedule_completed") as complete,
        ):
            app.complete_notion_schedule_action()

        complete.assert_called_once_with("local-token", "page-id")
        self.assertIsNone(app._active_notion_schedule)
        self.assertEqual("disabled", app.btn_complete_notion.calls[-1]["state"])
        show.assert_called_once()


if __name__ == "__main__":
    unittest.main()

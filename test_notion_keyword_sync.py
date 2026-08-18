from datetime import date
from io import BytesIO
import unittest
import urllib.error
from unittest.mock import patch

from notion_keyword_sync import (
    NotionSyncError,
    parse_schedule_page,
    select_active_schedule,
    fetch_active_keyword_schedule,
    fetch_enabled_keyword_schedules,
)


def _page(title="Tuần 12/08", start="2026-08-12", end="2026-08-18", active=True):
    return {
        "id": "page-id",
        "properties": {
            "Tên lịch": {"title": [{"plain_text": title}]},
            "Thời gian áp dụng": {"date": {"start": start, "end": end}},
            "Đang áp dụng": {"checkbox": active},
            "Trạng thái bơm": {"select": None},
            "Google Maps - Từ khóa theo dõi": {"rich_text": [{"plain_text": "spa lấy mụn, chăm sóc da"}]},
            "TikTok - Từ khóa nhiệm vụ": {"rich_text": [{"plain_text": "chăm sóc da, skincare"}]},
            "TikTok - Kênh mục tiêu": {"rich_text": [{"plain_text": "kenh-a, kenh-b"}]},
            "Facebook - Từ khóa mồi": {"rich_text": [{"plain_text": "da khỏe, trị mụn"}]},
            "Facebook - Page mục tiêu": {"rich_text": [{"plain_text": "Page A, Page B"}]},
            "Ghi chú Admin": {"rich_text": []},
        },
    }


class _Response:
    def __init__(self, payload):
        import json
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class NotionKeywordSyncTests(unittest.TestCase):
    def test_parses_all_platform_fields(self):
        schedule = parse_schedule_page(_page())

        self.assertEqual("Tuần 12/08", schedule.title)
        self.assertEqual(date(2026, 8, 12), schedule.start_date)
        self.assertEqual("spa lấy mụn, chăm sóc da", schedule.google_maps_keywords)
        self.assertEqual("kenh-a, kenh-b", schedule.tiktok_target_channels)
        self.assertEqual("Page A, Page B", schedule.facebook_target_pages)
        self.assertEqual("", schedule.pump_status)

    def test_selects_latest_start_when_active_ranges_overlap(self):
        older = parse_schedule_page(_page(title="Cũ", start="2026-08-01"))
        newer = parse_schedule_page(_page(title="Mới", start="2026-08-10"))

        selected = select_active_schedule([older, newer], date(2026, 8, 12))

        self.assertEqual("Mới", selected.title)

    def test_ignores_unchecked_or_out_of_range_rows(self):
        unchecked = parse_schedule_page(_page(active=False))
        expired = parse_schedule_page(_page(start="2026-07-01", end="2026-07-07"))

        with self.assertRaisesRegex(NotionSyncError, "Không có lịch"):
            select_active_schedule([unchecked, expired], date(2026, 8, 12))

    def test_missing_required_property_is_clear(self):
        page = _page()
        del page["properties"]["Thời gian áp dụng"]

        with self.assertRaisesRegex(NotionSyncError, "Thời gian áp dụng"):
            parse_schedule_page(page)

    def test_api_query_uses_data_source_and_never_exposes_token(self):
        with patch(
            "notion_keyword_sync.urllib.request.urlopen",
            return_value=_Response({"results": [_page()], "has_more": False}),
        ) as call:
            schedule = fetch_active_keyword_schedule(
                "super-secret-token", "source-id", today=date(2026, 8, 12)
            )

        self.assertEqual("Tuần 12/08", schedule.title)
        request = call.call_args.args[0]
        self.assertEqual(
            "https://api.notion.com/v1/data_sources/source-id/query",
            request.full_url,
        )
        self.assertEqual("Bearer super-secret-token", request.headers["Authorization"])
        import json
        payload = json.loads(request.data.decode("utf-8"))
        filters = payload["filter"]["and"]
        self.assertTrue(filters[0]["checkbox"]["equals"])
        self.assertEqual("Hoàn thành", filters[1]["select"]["does_not_equal"])

    def test_completed_schedule_is_not_returned_by_api(self):
        complete = _page(title="Đã xong")
        complete["properties"]["Trạng thái bơm"] = {
            "select": {"name": "Hoàn thành"}
        }
        active = _page(title="Đang chạy")
        with patch(
            "notion_keyword_sync.urllib.request.urlopen",
            return_value=_Response({"results": [active], "has_more": False}),
        ):
            schedules = fetch_enabled_keyword_schedules("token", "source-id")

        self.assertEqual(["Đang chạy"], [item.title for item in schedules])

    def test_status_updates_use_notion_select_property(self):
        from notion_keyword_sync import mark_schedule_completed

        with patch(
            "notion_keyword_sync.urllib.request.urlopen",
            return_value=_Response({}),
        ) as call:
            mark_schedule_completed("token", "page-id")

        import json
        payload = json.loads(call.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(
            "Hoàn thành",
            payload["properties"]["Trạng thái bơm"]["select"]["name"],
        )

    def test_api_classifies_auth_error_without_leaking_token(self):
        error = urllib.error.HTTPError(
            "https://api.notion.com", 401, "Unauthorized", {}, BytesIO(b"{}")
        )
        self.addCleanup(error.close)
        with patch("notion_keyword_sync.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(NotionSyncError) as raised:
                fetch_active_keyword_schedule("super-secret-token", "source-id")

        self.assertEqual("invalid_token", raised.exception.code)
        self.assertNotIn("super-secret-token", str(raised.exception))

    def test_database_url_is_resolved_to_its_data_source(self):
        missing_source = urllib.error.HTTPError(
            "https://api.notion.com", 404, "Not Found", {}, BytesIO(b"{}")
        )
        self.addCleanup(missing_source.close)
        responses = [
            missing_source,
            _Response({"data_sources": [{"id": "resolved-source"}]}),
            _Response({"results": [_page()], "has_more": False}),
        ]
        with patch(
            "notion_keyword_sync.urllib.request.urlopen", side_effect=responses
        ) as call:
            schedule = fetch_active_keyword_schedule(
                "token",
                "https://app.notion.com/p/654a56cd7cf5416fb65f9b934a62ec45?v=view",
                today=date(2026, 8, 12),
            )

        self.assertEqual("Tuần 12/08", schedule.title)
        self.assertIn("/databases/654a56cd7cf5416fb65f9b934a62ec45", call.call_args_list[1].args[0].full_url)
        self.assertIn("/data_sources/resolved-source/query", call.call_args_list[2].args[0].full_url)

    def test_enabled_schedule_list_keeps_all_checked_rows_for_user_choice(self):
        first = _page(title="Tuần A", start="2026-08-10", end="2026-08-16")
        second = _page(title="Tuần B", start="2026-08-17", end="2026-08-23")
        with patch(
            "notion_keyword_sync.urllib.request.urlopen",
            return_value=_Response(
                {"results": [first, second], "has_more": False}
            ),
        ):
            schedules = fetch_enabled_keyword_schedules("token", "source-id")

        self.assertEqual(["Tuần B", "Tuần A"], [item.title for item in schedules])


if __name__ == "__main__":
    unittest.main()

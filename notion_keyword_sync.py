"""Đọc lịch từ khóa đa nền tảng từ Notion, độc lập với workflow ADB."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import socket
import re
import urllib.error
import urllib.parse
import urllib.request


NOTION_API_VERSION = "2025-09-03"
PROPERTY_NAMES = {
    "title": "Tên lịch",
    "date": "Thời gian áp dụng",
    "active": "Đang áp dụng",
    "shopee": "Shopee - Từ khóa gốc",
    "tiktok_seed": "TikTok - Từ khóa nhiệm vụ",
    "tiktok_target": "TikTok - Kênh mục tiêu",
    "facebook_seed": "Facebook - Từ khóa mồi",
    "facebook_target": "Facebook - Page mục tiêu",
    "note": "Ghi chú Admin",
    "last_scanned": "Lần quét gần nhất",
    "pump_status": "Trạng thái bơm",
}

PUMP_STATUS_PROCESSING = "Đang xử lý"
PUMP_STATUS_COMPLETED = "Hoàn thành"


class NotionSyncError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NotionKeywordSchedule:
    page_id: str
    title: str
    start_date: date
    end_date: date
    active: bool
    shopee_keywords: str
    tiktok_seed_keywords: str
    tiktok_target_channels: str
    facebook_seed_keywords: str
    facebook_target_pages: str
    admin_note: str = ""
    pump_status: str = ""


def _property(properties, name):
    if name not in properties:
        raise NotionSyncError(
            "invalid_schema", f"Bảng Notion thiếu cột bắt buộc: {name}."
        )
    return properties[name]


def _plain_text(prop, kind="rich_text"):
    fragments = prop.get(kind) or []
    return "".join(
        fragment.get("plain_text")
        or (fragment.get("text") or {}).get("content", "")
        for fragment in fragments
    ).strip()


def _parse_iso_date(value, property_name):
    if not value:
        raise NotionSyncError(
            "invalid_schema", f"Cột {property_name} chưa có ngày bắt đầu."
        )
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise NotionSyncError(
            "invalid_schema", f"Ngày trong cột {property_name} không hợp lệ."
        ) from exc


def parse_schedule_page(page):
    properties = page.get("properties") or {}
    title_prop = _property(properties, PROPERTY_NAMES["title"])
    date_prop = _property(properties, PROPERTY_NAMES["date"])
    active_prop = _property(properties, PROPERTY_NAMES["active"])
    date_value = date_prop.get("date") or {}
    start_date = _parse_iso_date(date_value.get("start"), PROPERTY_NAMES["date"])
    end_date = _parse_iso_date(
        date_value.get("end") or date_value.get("start"), PROPERTY_NAMES["date"]
    )

    return NotionKeywordSchedule(
        page_id=page.get("id", ""),
        title=_plain_text(title_prop, "title") or "Lịch không tên",
        start_date=start_date,
        end_date=end_date,
        active=bool(active_prop.get("checkbox")),
        shopee_keywords=_plain_text(
            _property(properties, PROPERTY_NAMES["shopee"])
        ),
        tiktok_seed_keywords=_plain_text(
            _property(properties, PROPERTY_NAMES["tiktok_seed"])
        ),
        tiktok_target_channels=_plain_text(
            _property(properties, PROPERTY_NAMES["tiktok_target"])
        ),
        facebook_seed_keywords=_plain_text(
            _property(properties, PROPERTY_NAMES["facebook_seed"])
        ),
        facebook_target_pages=_plain_text(
            _property(properties, PROPERTY_NAMES["facebook_target"])
        ),
        admin_note=_plain_text(properties.get(PROPERTY_NAMES["note"], {})),
        pump_status=(
            (properties.get(PROPERTY_NAMES["pump_status"], {}).get("select") or {})
            .get("name", "")
            .strip()
        ),
    )


def select_active_schedule(schedules, today=None):
    current_date = today or date.today()
    valid = [
        schedule
        for schedule in schedules
        if schedule.active
        and schedule.start_date <= current_date <= schedule.end_date
    ]
    if not valid:
        raise NotionSyncError(
            "no_active_schedule",
            "Không có lịch Notion nào được bật và áp dụng cho ngày hôm nay.",
        )
    return max(valid, key=lambda schedule: (schedule.start_date, schedule.page_id))


def _safe_http_error(exc):
    if exc.code in (401, 403):
        return NotionSyncError(
            "invalid_token",
            "Token Notion không hợp lệ hoặc integration chưa được chia sẻ vào bảng.",
        )
    if exc.code == 404:
        return NotionSyncError(
            "source_not_found",
            "Không tìm thấy bảng Notion. Hãy kiểm tra Data Source ID và quyền chia sẻ.",
        )
    if exc.code == 429:
        return NotionSyncError(
            "rate_limited", "Notion đang giới hạn tần suất. Hãy thử lại sau ít phút."
        )
    return NotionSyncError(
        "http_error", f"Notion API trả về lỗi HTTP {exc.code}."
    )


def _request_json(url, token, method="GET", payload=None, timeout=20):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token.strip()}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _safe_http_error(exc) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise NotionSyncError(
            "network_error",
            "Không thể kết nối Notion API. Hãy kiểm tra mạng và thử lại.",
        ) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NotionSyncError(
            "invalid_response", "Notion API trả về dữ liệu không hợp lệ."
        ) from None


def _extract_notion_id(value):
    raw = (value or "").strip()
    if not raw:
        return ""
    matches = re.findall(r"[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}", raw)
    return matches[-1].replace("-", "") if matches else raw


def _resolve_data_source_id(token, database_reference, timeout):
    database_id = _extract_notion_id(database_reference)
    url = (
        "https://api.notion.com/v1/databases/"
        f"{urllib.parse.quote(database_id, safe='')}"
    )
    response = _request_json(url, token, timeout=timeout)
    sources = response.get("data_sources") or []
    if not sources or not sources[0].get("id"):
        raise NotionSyncError(
            "source_not_found",
            "Database Notion chưa có Data Source mà tool có thể đọc.",
        )
    return sources[0]["id"]


def fetch_enabled_keyword_schedules(token, data_source_id, timeout=20):
    if not token or not token.strip():
        raise NotionSyncError("missing_token", "Chưa nhập Notion API Token.")
    if not data_source_id or not data_source_id.strip():
        raise NotionSyncError("missing_source", "Chưa nhập Notion Data Source ID.")

    source_reference = data_source_id.strip()
    source_id = _extract_notion_id(source_reference)
    url = (
        "https://api.notion.com/v1/data_sources/"
        f"{urllib.parse.quote(source_id, safe='')}/query"
    )
    pages = []
    cursor = None
    while True:
        payload = {
            "page_size": 100,
            "filter": {
                "and": [
                    {
                        "property": PROPERTY_NAMES["active"],
                        "checkbox": {"equals": True},
                    },
                    {
                        "property": PROPERTY_NAMES["pump_status"],
                        "select": {"does_not_equal": PUMP_STATUS_COMPLETED},
                    },
                ]
            },
        }
        if cursor:
            payload["start_cursor"] = cursor
        try:
            response = _request_json(url, token, "POST", payload, timeout)
        except NotionSyncError as exc:
            if exc.code != "source_not_found" or cursor:
                raise
            source_id = _resolve_data_source_id(token, source_reference, timeout)
            url = (
                "https://api.notion.com/v1/data_sources/"
                f"{urllib.parse.quote(source_id, safe='')}/query"
            )
            response = _request_json(url, token, "POST", payload, timeout)
        pages.extend(response.get("results") or [])
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
        if not cursor:
            break

    schedules = [parse_schedule_page(page) for page in pages]
    if not schedules:
        raise NotionSyncError(
            "no_enabled_schedule",
            "Không có lịch Notion nào được bật Đang áp dụng.",
        )
    return sorted(
        schedules,
        key=lambda schedule: (schedule.start_date, schedule.title),
        reverse=True,
    )


def fetch_active_keyword_schedule(token, data_source_id, today=None, timeout=20):
    schedules = fetch_enabled_keyword_schedules(
        token, data_source_id, timeout=timeout
    )
    return select_active_schedule(schedules, today=today)


def mark_schedule_scanned(token, page_id, timeout=20):
    """Ghi dấu quét thành công; lỗi ghi dấu không làm mất dữ liệu vừa tải."""
    if not token or not page_id:
        return False
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    url = f"https://api.notion.com/v1/pages/{urllib.parse.quote(page_id, safe='')}"
    _request_json(
        url,
        token,
        "PATCH",
        {
            "properties": {
                PROPERTY_NAMES["last_scanned"]: {"date": {"start": timestamp}}
            }
        },
        timeout,
    )
    return True


def _mark_schedule_status(token, page_id, status, timeout=20):
    if not token or not page_id:
        return False
    url = f"https://api.notion.com/v1/pages/{urllib.parse.quote(page_id, safe='')}"
    _request_json(
        url,
        token,
        "PATCH",
        {
            "properties": {
                PROPERTY_NAMES["pump_status"]: {"select": {"name": status}}
            }
        },
        timeout,
    )
    return True


def mark_schedule_processing(token, page_id, timeout=20):
    return _mark_schedule_status(
        token, page_id, PUMP_STATUS_PROCESSING, timeout=timeout
    )


def mark_schedule_completed(token, page_id, timeout=20):
    return _mark_schedule_status(
        token, page_id, PUMP_STATUS_COMPLETED, timeout=timeout
    )

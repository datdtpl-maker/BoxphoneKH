"""Đồng bộ bình luận Seeding 2 chiều với Notion API.

Hỗ trợ quét danh sách bình luận 'Chưa comment' và cập nhật 'Hoàn thành' kèm thời gian.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional
import config

NOTION_API_VERSION = "2022-06-28"
DEFAULT_COMMENT_TOKEN = getattr(config, "NOTION_COMMENT_SEEDING_TOKEN", "") or getattr(config, "NOTION_API_TOKEN", "")
DEFAULT_COMMENT_DATABASE_ID = getattr(config, "NOTION_COMMENT_SEEDING_DATABASE_ID", "1064bf0f819748a797c195247b2ea14e")


class NotionCommentSyncError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class NotionCommentTask:
    page_id: str
    stt: int = 0
    content: str = ""
    url: str = ""
    platform: str = ""
    status: str = "Chưa comment"
    completed_time: str = ""


def _build_headers(token: str) -> dict[str, str]:
    cleaned_token = (token or DEFAULT_COMMENT_TOKEN).strip()
    return {
        "Authorization": f"Bearer {cleaned_token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def _plain_text(prop: dict, kind: str = "rich_text") -> str:
    fragments = prop.get(kind) or []
    return "".join(
        fragment.get("plain_text")
        or (fragment.get("text") or {}).get("content", "")
        for fragment in fragments
    ).strip()


def detect_platform_from_url(url: str) -> str:
    """Tự động phát hiện nền tảng từ đường dẫn bài đăng."""
    lowered = (url or "").casefold()
    if "tiktok" in lowered:
        return "TikTok"
    if "facebook" in lowered or "fb.watch" in lowered or "fb.com" in lowered:
        return "Facebook"
    return "Khác"


def fetch_notion_comments(
    token: Optional[str] = None,
    database_id: Optional[str] = None,
    only_uncompleted: bool = True,
    timeout: float = 12.0,
) -> list[NotionCommentTask]:
    """Quét danh sách bình luận từ Notion Database."""
    tok = (token or DEFAULT_COMMENT_TOKEN).strip()
    db_id = (database_id or DEFAULT_COMMENT_DATABASE_ID).replace("-", "").strip()
    if not tok or not db_id:
        raise NotionCommentSyncError("missing_credentials", "Thiếu Notion Token hoặc Database ID.")

    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    query_body: dict = {
        "sorts": [
            {"timestamp": "created_time", "direction": "ascending"}
        ]
    }
    if only_uncompleted:
        query_body["filter"] = {
            "property": "Trạng thái",
            "select": {"does_not_equal": "Hoàn thành"}
        }

    req = urllib.request.Request(
        url,
        headers=_build_headers(tok),
        data=json.dumps(query_body).encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")
        raise NotionCommentSyncError(f"http_{exc.code}", f"Lỗi HTTP {exc.code}: {msg}") from exc
    except Exception as exc:
        raise NotionCommentSyncError("network_error", f"Lỗi kết nối Notion: {exc}") from exc

    results = data.get("results", [])
    tasks: list[NotionCommentTask] = []
    for idx, page in enumerate(results):
        page_id = page.get("id", "")
        props = page.get("properties", {})

        stt_val = props.get("STT", {}).get("number")
        stt_num = int(stt_val) if stt_val is not None else (idx + 1)
        content = _plain_text(props.get("Nội dung comment", {}), "title")
        post_url = props.get("Link bài đăng", {}).get("url") or ""

        # Nền tảng: lấy từ formula nếu có, nếu chưa thì tự detect từ URL
        formula_data = props.get("Nền tảng", {}).get("formula") or {}
        platform_str = formula_data.get("string") or detect_platform_from_url(post_url)

        status_data = props.get("Trạng thái", {}).get("select") or {}
        status_name = status_data.get("name") or "Chưa comment"
        time_done = _plain_text(props.get("Thời gian hoàn thành", {}), "rich_text")

        task = NotionCommentTask(
            page_id=page_id,
            stt=stt_num,
            content=content,
            url=post_url,
            platform=platform_str,
            status=status_name,
            completed_time=time_done,
        )
        tasks.append(task)

    return tasks


def mark_notion_comment_completed(
    page_id: str,
    device_name: str = "",
    token: Optional[str] = None,
    timeout: float = 12.0,
) -> bool:
    """Cập nhật trạng thái 'Hoàn thành' và ghi rõ thời gian thực hiện lên Notion."""
    tok = (token or DEFAULT_COMMENT_TOKEN).strip()
    clean_page_id = page_id.strip()
    if not clean_page_id:
        return False

    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    time_label = f"Máy {device_name} lúc {now_str}" if device_name else f"Lúc {now_str}"

    payload = {
        "properties": {
            "Trạng thái": {"select": {"name": "Hoàn thành"}},
            "Thời gian hoàn thành": {
                "rich_text": [{"text": {"content": time_label}}]
            },
        }
    }

    url = f"https://api.notion.com/v1/pages/{clean_page_id}"
    req = urllib.request.Request(
        url,
        headers=_build_headers(tok),
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

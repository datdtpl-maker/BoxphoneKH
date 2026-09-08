"""Đồng bộ bình luận Seeding 2 chiều với Notion API.

Hỗ trợ mô hình Bài viết chứa Bảng bình luận chi tiết (Nested Table Block),
tự động lọc bỏ các cmt đã hoàn thành khi quét và đồng bộ trạng thái tổng thể.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    page_id: str                      # ID của trang bài viết cha
    row_id: str = ""                  # ID của block table_row (nếu nằm trong bảng con)
    table_id: str = ""                # ID của block table
    stt: int = 0
    content: str = ""
    url: str = ""                     # URL bài viết (TikTok / Facebook)
    platform: str = ""                # TikTok / Facebook
    status: str = "Chưa comment"      # Trạng thái bình luận
    author: str = ""                  # Máy thực hiện
    completed_time: str = ""          # Thời gian hoàn thành
    campaign_title: str = ""          # Tiêu đề bài viết
    raw_cells: list = field(default_factory=list) # Dữ liệu cells gốc
    col_map: dict = field(default_factory=dict)   # Vị trí các cột trong bảng


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


def _cell_text(cell: list) -> str:
    return "".join(
        fragment.get("plain_text")
        or (fragment.get("text") or {}).get("content", "")
        for fragment in cell
    ).strip()


def detect_platform_from_url(url: str) -> str:
    """Tự động phát hiện nền tảng từ đường dẫn bài đăng."""
    lowered = (url or "").casefold()
    if "tiktok" in lowered:
        return "TikTok"
    if "facebook" in lowered or "fb.watch" in lowered or "fb.com" in lowered:
        return "Facebook"
    return "Khác"


def _parse_table_header(header_cells: list) -> dict[str, int]:
    """Tự động nhận diện chỉ số các cột trong bảng bình luận con."""
    names = [_cell_text(cell).casefold() for cell in header_cells]
    col_map = {
        "stt": 0,
        "content": 1,
        "status": 2,
        "author": 3,
        "time": 4,
    }
    for idx, name in enumerate(names):
        if "stt" in name or "số thứ tự" in name:
            col_map["stt"] = idx
        elif "nội dung" in name or "bình luận" in name or "comment" in name or "cmt" in name:
            col_map["content"] = idx
        elif "trạng thái" in name or "status" in name:
            col_map["status"] = idx
        elif "ai đăng" in name or "người" in name or "máy" in name or "bot" in name:
            col_map["author"] = idx
        elif "thời gian" in name or "hoàn thành" in name or "time" in name:
            col_map["time"] = idx

    return col_map


def fetch_notion_comments(
    token: Optional[str] = None,
    database_id: Optional[str] = None,
    only_uncompleted: bool = True,
    timeout: float = 12.0,
) -> list[NotionCommentTask]:
    """Quét danh sách bình luận từ Notion Database.
    
    Hỗ trợ mô hình Bài viết chứa Bảng con:
    - Quét các bài viết đang cần chạy.
    - Đọc các bình luận trong bảng con của từng bài viết.
    - Chỉ lấy những bình luận có trạng thái 'Chưa comment' (bỏ qua cmt đã Hoàn thành).
    """
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

    for page in results:
        page_id = page.get("id", "")
        props = page.get("properties", {})

        # 1. Lấy thông tin bài viết cha
        title_prop = props.get("Bài viết / video") or props.get("Nội dung comment") or {}
        campaign_title = _plain_text(title_prop, "title")
        post_url = props.get("Link bài đăng", {}).get("url") or ""

        formula_data = props.get("Nền tảng", {}).get("formula") or {}
        platform_str = formula_data.get("string") or detect_platform_from_url(post_url)

        status_data = props.get("Trạng thái", {}).get("select") or {}
        camp_status = status_data.get("name") or "Chưa chạy"

        # 2. Đọc các blocks con của bài viết để tìm bảng bình luận (Table block)
        table_found = False
        try:
            req_blocks = urllib.request.Request(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=_build_headers(tok),
            )
            with urllib.request.urlopen(req_blocks, timeout=timeout) as r_blk:
                blocks = json.loads(r_blk.read().decode("utf-8")).get("results", [])

            for b in blocks:
                if b.get("type") == "table":
                    t_id = b.get("id")
                    table_found = True

                    # Lấy danh sách hàng trong bảng
                    req_rows = urllib.request.Request(
                        f"https://api.notion.com/v1/blocks/{t_id}/children",
                        headers=_build_headers(tok),
                    )
                    with urllib.request.urlopen(req_rows, timeout=timeout) as r_rows:
                        rows = json.loads(r_rows.read().decode("utf-8")).get("results", [])

                    if not rows:
                        continue

                    # Header row
                    header_cells = rows[0].get("table_row", {}).get("cells", [])
                    col_map = _parse_table_header(header_cells)

                    # Đếm số comment thực tế có nội dung để tự động cập nhật Notion
                    valid_comment_rows = []
                    completed_count = 0
                    content_idx = col_map.get("content", 1)
                    status_idx = col_map.get("status", 2)
                    for r in rows[1:]:
                        c_cells = r.get("table_row", {}).get("cells", [])
                        c_text = _cell_text(c_cells[content_idx]) if content_idx < len(c_cells) else ""
                        if c_text.strip():
                            valid_comment_rows.append(r)
                            s_text = _cell_text(c_cells[status_idx]) if status_idx < len(c_cells) else ""
                            if s_text.casefold() in ["hoàn thành", "đã đăng", "done", "completed"]:
                                completed_count += 1

                    # Tự động cập nhật 'Số cmt dự kiến' & 'Đã đăng' ngoài bảng chính nếu người dùng vừa thêm cmt
                    expected_now = len(valid_comment_rows)
                    if expected_now > 0:
                        exp_cur = int(props.get("Số cmt dự kiến", {}).get("number") or 0)
                        post_cur = int(props.get("Đã đăng", {}).get("number") or 0)
                        if exp_cur != expected_now or post_cur != completed_count:
                            try:
                                sync_body = {
                                    "properties": {
                                        "Số cmt dự kiến": {"number": expected_now},
                                        "Đã đăng": {"number": completed_count},
                                    }
                                }
                                if completed_count >= expected_now and expected_now > 0:
                                    sync_body["properties"]["Trạng thái"] = {"select": {"name": "Hoàn thành"}}
                                elif completed_count > 0:
                                    sync_body["properties"]["Trạng thái"] = {"select": {"name": "Đang chạy"}}
                                req_sync = urllib.request.Request(
                                    f"https://api.notion.com/v1/pages/{page_id}",
                                    headers=_build_headers(tok),
                                    data=json.dumps(sync_body).encode("utf-8"),
                                    method="PATCH",
                                )
                                with urllib.request.urlopen(req_sync, timeout=timeout) as _:
                                    pass
                            except Exception:
                                pass

                    # Comment rows
                    for r_idx, r in enumerate(rows[1:], start=1):
                        row_id = r.get("id", "")
                        cells = r.get("table_row", {}).get("cells", [])

                        stt_idx = col_map.get("stt", 0)
                        content_idx = col_map.get("content", 1)
                        status_idx = col_map.get("status", 2)
                        author_idx = col_map.get("author", 3)
                        time_idx = col_map.get("time", 4)

                        content_txt = _cell_text(cells[content_idx]) if content_idx < len(cells) else ""
                        if not content_txt.strip():
                            continue

                        stt_val = _cell_text(cells[stt_idx]) if stt_idx < len(cells) else str(r_idx)
                        try:
                            stt_num = int(re.sub(r"[^\d]", "", stt_val)) if re.sub(r"[^\d]", "", stt_val) else r_idx
                        except Exception:
                            stt_num = r_idx

                        status_raw = _cell_text(cells[status_idx]) if status_idx < len(cells) else ""
                        author_raw = _cell_text(cells[author_idx]) if author_idx < len(cells) else ""
                        time_raw = _cell_text(cells[time_idx]) if time_idx < len(cells) else ""

                        needs_patch = False
                        status_txt = status_raw
                        if not status_txt.strip():
                            status_txt = "Chưa comment"
                            needs_patch = True

                        author_txt = author_raw
                        if not author_txt.strip():
                            author_txt = "—"
                            needs_patch = True

                        time_txt = time_raw
                        if not time_txt.strip():
                            time_txt = "—"
                            needs_patch = True

                        # Tự động điền 'Chưa comment', '—', '—' vào các ô trống trên Notion cho đồng bộ
                        if needs_patch and row_id:
                            try:
                                def _make_text_c(t: str):
                                    return [{"type": "text", "text": {"content": t}}]
                                patched_cells = list(cells)
                                while len(patched_cells) <= max(stt_idx, content_idx, status_idx, author_idx, time_idx):
                                    patched_cells.append([])
                                if not _cell_text(patched_cells[stt_idx]).strip():
                                    patched_cells[stt_idx] = _make_text_c(str(stt_num))
                                patched_cells[status_idx] = _make_text_c(status_txt)
                                patched_cells[author_idx] = _make_text_c(author_txt)
                                patched_cells[time_idx] = _make_text_c(time_txt)
                                req_fill = urllib.request.Request(
                                    f"https://api.notion.com/v1/blocks/{row_id}",
                                    headers=_build_headers(tok),
                                    data=json.dumps({"table_row": {"cells": patched_cells}}).encode("utf-8"),
                                    method="PATCH",
                                )
                                with urllib.request.urlopen(req_fill, timeout=timeout) as _:
                                    cells = patched_cells
                            except Exception:
                                pass

                        # BỘ LỌC QUAN TRỌNG: Nếu yêu cầu chỉ lấy uncompleted và cmt đã hoàn thành -> BỎ QUA
                        if only_uncompleted and status_txt.casefold() in ["hoàn thành", "đã đăng", "done", "completed"]:
                            continue

                        task = NotionCommentTask(
                            page_id=page_id,
                            row_id=row_id,
                            table_id=t_id,
                            stt=stt_num,
                            content=content_txt,
                            url=post_url,
                            platform=platform_str,
                            status=status_txt,
                            author=author_txt,
                            completed_time=time_txt,
                            campaign_title=campaign_title,
                            raw_cells=cells,
                            col_map=col_map,
                        )
                        tasks.append(task)
        except Exception:
            pass

        # 3. Fallback: nếu bài viết không có bảng con, hỗ trợ dạng dòng phẳng
        if not table_found:
            stt_val = props.get("STT", {}).get("number")
            stt_num = int(stt_val) if stt_val is not None else (len(tasks) + 1)
            time_done = _plain_text(props.get("Thời gian hoàn thành", {}), "rich_text")

            if only_uncompleted and camp_status.casefold() in ["hoàn thành", "đã đăng", "done"]:
                continue

            task = NotionCommentTask(
                page_id=page_id,
                stt=stt_num,
                content=campaign_title,
                url=post_url,
                platform=platform_str,
                status=camp_status,
                completed_time=time_done,
                campaign_title=campaign_title,
            )
            tasks.append(task)

    return tasks


def mark_notion_comment_completed(
    task_or_page_id: NotionCommentTask | str,
    device_name: str = "",
    token: Optional[str] = None,
    timeout: float = 12.0,
) -> bool:
    """Cập nhật trạng thái 'Hoàn thành' cho bình luận và cập nhật trạng thái tổng thể bài viết."""
    tok = (token or DEFAULT_COMMENT_TOKEN).strip()
    if not task_or_page_id:
        return False

    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    time_label = f"Máy {device_name} lúc {now_str}" if device_name else f"Lúc {now_str}"

    if isinstance(task_or_page_id, NotionCommentTask) and task_or_page_id.row_id:
        # Trường hợp 1: Bình luận nằm trong Bảng con (Table Block)
        task = task_or_page_id
        col_map = task.col_map or {"stt": 0, "content": 1, "status": 2, "author": 3, "time": 4}
        status_idx = col_map.get("status", 2)
        author_idx = col_map.get("author", 3)
        time_idx = col_map.get("time", 4)

        # Lấy cells hiện tại
        cells = list(task.raw_cells or [])
        while len(cells) <= max(status_idx, author_idx, time_idx):
            cells.append([])

        def _make_text_cell(text: str):
            return [{"type": "text", "text": {"content": text}}]

        new_cells = []
        for i, cell in enumerate(cells):
            if i == status_idx:
                new_cells.append(_make_text_cell("Hoàn thành"))
            elif i == author_idx:
                new_cells.append(_make_text_cell(f"Máy {device_name}" if device_name else "Tool"))
            elif i == time_idx:
                new_cells.append(_make_text_cell(now_str))
            else:
                new_cells.append(cell)

        patch_url = f"https://api.notion.com/v1/blocks/{task.row_id}"
        req_patch = urllib.request.Request(
            patch_url,
            headers=_build_headers(tok),
            data=json.dumps({"table_row": {"cells": new_cells}}).encode("utf-8"),
            method="PATCH",
        )
        row_updated = False
        try:
            with urllib.request.urlopen(req_patch, timeout=timeout) as resp:
                row_updated = resp.status == 200
        except Exception:
            return False

        # Đồng bộ trạng thái tổng thể của bài viết cha
        if row_updated and task.page_id:
            try:
                # Cập nhật số lượng 'Đã đăng' và kiểm tra trạng thái tổng thể
                req_page = urllib.request.Request(
                    f"https://api.notion.com/v1/pages/{task.page_id}",
                    headers=_build_headers(tok),
                )
                with urllib.request.urlopen(req_page, timeout=timeout) as r_p:
                    page_data = json.loads(r_p.read().decode("utf-8"))
                    props = page_data.get("properties", {})
                    posted_cur = int(props.get("Đã đăng", {}).get("number") or 0)
                    expected_cur = int(props.get("Số cmt dự kiến", {}).get("number") or 0)

                new_posted = posted_cur + 1
                new_status = "Hoàn thành" if (expected_cur > 0 and new_posted >= expected_cur) else "Đang chạy"

                page_update_payload = {
                    "properties": {
                        "Đã đăng": {"number": new_posted},
                        "Trạng thái": {"select": {"name": new_status}},
                    }
                }
                req_update_page = urllib.request.Request(
                    f"https://api.notion.com/v1/pages/{task.page_id}",
                    headers=_build_headers(tok),
                    data=json.dumps(page_update_payload).encode("utf-8"),
                    method="PATCH",
                )
                with urllib.request.urlopen(req_update_page, timeout=timeout) as r_up:
                    pass
            except Exception:
                pass

        return row_updated

    # Trường hợp 2: Page ID trực tiếp (Fallback)
    clean_page_id = task_or_page_id if isinstance(task_or_page_id, str) else task_or_page_id.page_id
    payload = {
        "properties": {
            "Trạng thái": {"select": {"name": "Hoàn thành"}},
            "Thời gian hoàn thành": {
                "rich_text": [{"text": {"content": time_label}}]
            },
        }
    }
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{clean_page_id}",
        headers=_build_headers(tok),
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


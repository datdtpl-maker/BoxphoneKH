"""Phân hệ Điều Khiển Bơm Bình Luận (Comment Seeding Controller) đa nền tảng.

Hỗ trợ TikTok và Facebook qua cơ chế Android Deep Link Intent tàng hình,
kết hợp giả lập hành vi người dùng tự nhiên (dwell, jitter, gõ tiếng Việt Unicode).
"""

from __future__ import annotations

import os
import random
import re
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Optional

PLATFORM_TIKTOK = "TikTok"
PLATFORM_FACEBOOK = "Facebook"
PLATFORM_CHOICES = [PLATFORM_TIKTOK, PLATFORM_FACEBOOK]

DEFAULT_STEALTH_REFERRER = "android-app://com.zing.zalo"
TIKTOK_PRIMARY_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_ALT_PACKAGE = "com.zhiliaoapp.musically"
FACEBOOK_PACKAGE = "com.facebook.katana"


def resolve_canonical_url(url: str, timeout: float = 8.0) -> str:
    """Phân giải link rút gọn (vt.tiktok.com, fb.watch, bit.ly,...) về link chuẩn."""
    if not url or not url.strip().startswith("http"):
        return url.strip()

    clean_url = url.strip()
    try:
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; Mobile) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            if final_url:
                return final_url
    except Exception:
        pass
    return clean_url


def open_url_via_intent(
    adb,
    device_id: str,
    url: str,
    platform: str,
    referrer: str = DEFAULT_STEALTH_REFERRER,
) -> bool:
    """Mở link bài viết/video bằng Android Intent kèm cờ Referrer tàng hình."""
    canonical_url = resolve_canonical_url(url)
    clean_platform = (platform or "").strip().casefold()

    if "tiktok" in clean_platform:
        # Thử mở bằng package TikTok chính
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", canonical_url,
            "-p", TIKTOK_PRIMARY_PACKAGE,
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code, _, _ = adb.execute_adb(device_id, cmd)
        if code != 0:
            # Thử mở bằng package TikTok alt
            cmd_alt = [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", canonical_url,
                "-p", TIKTOK_ALT_PACKAGE,
                "--es", "android.intent.extra.REFERRER_NAME", referrer,
            ]
            code_alt, _, _ = adb.execute_adb(device_id, cmd_alt)
            if code_alt != 0:
                # Fallback Intent không gắn cố định package
                cmd_fallback = [
                    "shell", "am", "start",
                    "-a", "android.intent.action.VIEW",
                    "-d", canonical_url,
                ]
                code_fb, _, _ = adb.execute_adb(device_id, cmd_fallback)
                return code_fb == 0
        return True

    elif "facebook" in clean_platform:
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", canonical_url,
            "-p", FACEBOOK_PACKAGE,
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code, _, _ = adb.execute_adb(device_id, cmd)
        if code != 0:
            cmd_fallback = [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", canonical_url,
            ]
            code_fb, _, _ = adb.execute_adb(device_id, cmd_fallback)
            return code_fb == 0
        return True

    else:
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", canonical_url,
        ]
        code, _, _ = adb.execute_adb(device_id, cmd)
        return code == 0


def post_tiktok_comment(
    adb,
    device_id: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> bool:
    """Quy trình mở link video TikTok, xem tự nhiên và đăng bình luận."""
    def log(msg: str):
        if status_callback:
            status_callback(f"[Device {device_id}][TikTok Seeding] {msg}")

    if is_cancelled and is_cancelled():
        log("Đã hủy tác vụ.")
        return False

    width, height = adb.get_effective_screen_size(device_id)
    log("Đang mở link video qua Intent Zalo Referrer...")
    success = open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
    if not success:
        log("Lỗi không thể mở link video.")
        return False

    # Dwell time: Xem video tự nhiên 10-25s
    dwell_target = max(8, int(dwell_time)) + random.randint(-2, 3)
    log(f"Đang xem video tự nhiên trong {dwell_target}s trước khi bình luận...")
    for elapsed in range(dwell_target):
        if is_cancelled and is_cancelled():
            log("Dừng xem do người dùng yêu cầu.")
            return False
        time.sleep(1.0)

    # 1. Bấm nút Mở khung bình luận
    log("Mở khung bình luận...")
    comment_coords = None
    try:
        comment_coords = adb.find_element_coords_by_text(device_id, "bình luận")
    except Exception:
        comment_coords = None

    if comment_coords:
        adb.tap(device_id, comment_coords[0], comment_coords[1])
    else:
        # Tọa độ icon comment chuẩn trên thanh điều hướng bên phải video TikTok
        icon_x = int(width * 0.92)
        icon_y = int(height * 0.63)
        adb.tap(device_id, icon_x, icon_y)

    time.sleep(random.uniform(1.8, 2.5))
    if is_cancelled and is_cancelled():
        return False

    # 2. Chạm vào ô nhập bình luận
    log("Chạm vào ô nhập bình luận...")
    input_x = int(width * 0.40)
    input_y = int(height * 0.95)
    adb.tap(device_id, input_x, input_y)
    time.sleep(random.uniform(1.0, 1.5))

    # 3. Gõ nội dung bình luận (Unicode Tiếng Việt qua XwIME)
    log(f"Đang nhập nội dung: '{comment_text}'...")
    adb.input_text(device_id, comment_text)
    time.sleep(random.uniform(1.2, 1.8))

    if is_cancelled and is_cancelled():
        return False

    # 4. Bấm nút Gửi
    log("Tìm nút Gửi bình luận...")
    send_x, send_y = find_send_button_coords(adb, device_id, PLATFORM_TIKTOK, width, height)
    log(f"Chạm nút Gửi TikTok tại ({send_x}, {send_y})...")
    adb.tap(device_id, send_x, send_y)
    time.sleep(0.4)
    # Kích hoạt phím Enter / Action Send
    adb.execute_adb(device_id, ["shell", "input", "keyevent", "66"])
    time.sleep(0.4)
    adb.tap(device_id, send_x, send_y)
    time.sleep(random.uniform(2.5, 3.2))

    # 5. Đóng khung comment để giữ màn hình an toàn (Phím Back an toàn)
    log("Đóng khung bình luận...")
    adb.keyevent(device_id, 4)
    time.sleep(1.0)

    log("Đã đăng bình luận TikTok thành công!")
    return True


def post_facebook_comment(
    adb,
    device_id: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> bool:
    """Quy trình mở link bài viết/Reels Facebook, đọc tự nhiên và đăng bình luận."""
    def log(msg: str):
        if status_callback:
            status_callback(f"[Device {device_id}][Facebook Seeding] {msg}")

    if is_cancelled and is_cancelled():
        log("Đã hủy tác vụ.")
        return False

    width, height = adb.get_effective_screen_size(device_id)
    log("Đang mở link bài viết/Reel qua Intent Zalo Referrer...")
    success = open_url_via_intent(adb, device_id, url, PLATFORM_FACEBOOK)
    if not success:
        log("Lỗi không thể mở link Facebook.")
        return False

    dwell_target = max(8, int(dwell_time)) + random.randint(-2, 3)
    log(f"Đang đọc bài/xem Reel trong {dwell_target}s trước khi bình luận...")
    for elapsed in range(dwell_target):
        if is_cancelled and is_cancelled():
            log("Dừng xem do người dùng yêu cầu.")
            return False
        time.sleep(1.0)

    # 1. Bấm nút Mở khung bình luận
    log("Mở khung bình luận Facebook...")
    coords = None
    try:
        coords = adb.find_element_coords_by_text(device_id, "bình luận")
    except Exception:
        coords = None

    if coords:
        adb.tap(device_id, coords[0], coords[1])
    else:
        # Nếu là Reels, icon bình luận nằm bên phải tương tự TikTok
        # Nếu là post thường, nút bình luận nằm ở 80-85% chiều cao màn hình
        is_reel = "reel" in url.casefold() or "watch" in url.casefold()
        if is_reel:
            btn_x = int(width * 0.92)
            btn_y = int(height * 0.60)
        else:
            btn_x = int(width * 0.50)
            btn_y = int(height * 0.82)
        adb.tap(device_id, btn_x, btn_y)

    time.sleep(random.uniform(1.8, 2.5))
    if is_cancelled and is_cancelled():
        return False

    # 2. Chạm vào ô nhập bình luận
    log("Chạm vào ô nhập bình luận...")
    input_x = int(width * 0.35)
    input_y = int(height * 0.95)
    adb.tap(device_id, input_x, input_y)
    time.sleep(random.uniform(1.0, 1.5))

    # 3. Gõ nội dung bình luận
    log(f"Đang nhập nội dung: '{comment_text}'...")
    adb.input_text(device_id, comment_text)
    time.sleep(random.uniform(1.2, 1.8))

    if is_cancelled and is_cancelled():
        return False

    # 4. Bấm nút Gửi bình luận
    log("Tìm nút Gửi bình luận...")
    send_x, send_y = find_send_button_coords(adb, device_id, PLATFORM_FACEBOOK, width, height)
    log(f"Chạm nút Gửi Facebook tại ({send_x}, {send_y})...")
    adb.tap(device_id, send_x, send_y)
    time.sleep(0.4)
    adb.execute_adb(device_id, ["shell", "input", "keyevent", "66"])
    time.sleep(0.4)
    adb.tap(device_id, send_x, send_y)
    time.sleep(random.uniform(2.5, 3.2))

    # 5. Thoát khung bình luận (phím Back an toàn)
    log("Thoát khung bình luận...")
    adb.keyevent(device_id, 4)
    time.sleep(1.0)

    log("Đã đăng bình luận Facebook thành công!")
    return True


def find_send_button_coords(
    adb, device_id: str, platform: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ nút Gửi bình luận qua UI dump hoặc tọa độ đã hiệu chuẩn thực tế."""
    xml_file = f"/sdcard/dump_cmt_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_cmt_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", xml_file]
        )
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml):
                tree = ET.parse(local_xml)
                root = tree.getroot()
                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    if cy < height * 0.55:
                        continue

                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()

                    is_send = any(
                        keyword in desc or keyword in txt or keyword in rid
                        for keyword in (
                            "gửi", "send", "submit", "publish", "post",
                            "btn_send", "send_btn", "iv_send"
                        )
                    )
                    if is_send:
                        return cx, cy
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    clean_p = (platform or "").strip().casefold()
    if "tiktok" in clean_p:
        # Tọa độ nút tròn đỏ gửi TikTok: x=89.3%, y=92.8%
        return int(width * 0.893), int(height * 0.928)
    else:
        # Tọa độ nút gửi Facebook: x=90.5%, y=92.8%
        return int(width * 0.905), int(height * 0.928)


def parse_comment_devices(selection_text: str, total_tasks: int, all_devices: list) -> list:
    """Xác định danh sách thiết bị chạy bình luận lần lượt.
    - Nếu để trống: Lấy lần lượt Máy 1, Máy 2, ... tương ứng với số câu bình luận.
    - Nếu nhập số lượng (VD: '3' hoặc '3 máy'): Lấy 3 máy đầu tiên (Máy 1, 2, 3).
    - Nếu nhập dải (VD: '1-3' hoặc '1, 2, 3'): Lấy đúng danh sách chỉ định.
    """
    if not all_devices:
        return []

    raw = (selection_text or "").strip()
    needed = max(1, min(total_tasks, len(all_devices)))
    if not raw:
        return all_devices[:needed]

    digit_match = re.match(r"^(\d+)\s*(?:máy|may|device|devices)?$", raw, re.IGNORECASE)
    if digit_match:
        qty = int(digit_match.group(1))
        if 1 < qty <= len(all_devices):
            return all_devices[:qty]
        elif qty == 1:
            return [all_devices[0]]

    selected_indices = set()
    tokens = re.split(r"[,;\s]+", raw)
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            try:
                s, e = map(int, token.split("-"))
                for i in range(min(s, e), max(s, e) + 1):
                    selected_indices.add(i)
            except ValueError:
                pass
        elif token.isdigit():
            selected_indices.add(int(token))

    result = []
    for idx in sorted(selected_indices):
        if 1 <= idx <= len(all_devices):
            result.append(all_devices[idx - 1])

    if not result:
        return all_devices[:needed]

    return result


def execute_comment_task(
    adb: ADBManager,
    device_id: str,
    platform: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> bool:
    """Điều phối thực hiện tác vụ bình luận theo đúng nền tảng."""
    plat = (platform or "").strip().casefold()
    if "tiktok" in plat:
        return post_tiktok_comment(
            adb,
            device_id,
            url,
            comment_text,
            dwell_time=dwell_time,
            status_callback=status_callback,
            is_cancelled=is_cancelled,
        )
    elif "facebook" in plat:
        return post_facebook_comment(
            adb,
            device_id,
            url,
            comment_text,
            dwell_time=dwell_time,
            status_callback=status_callback,
            is_cancelled=is_cancelled,
        )
    else:
        if status_callback:
            status_callback(f"[Device {device_id}] Nền tảng '{platform}' chưa hỗ trợ seeding.")
        return False


def filter_tasks_for_platform(tasks: list, platform: str) -> list:
    """Lọc danh sách task bình luận theo nền tảng chỉ định."""
    clean_p = (platform or "").strip().casefold()
    return [
        t for t in tasks
        if (getattr(t, "platform", "") or "").strip().casefold() == clean_p
    ]


def get_campaign_options(tasks: list, platform: str) -> list[dict]:
    """Lấy danh sách các bài viết/video theo nền tảng kèm URL và danh sách task con."""
    clean_p = (platform or "").strip().casefold()
    camps: dict[str, dict] = {}
    for t in tasks:
        p = (getattr(t, "platform", "") or "").strip().casefold()
        if p == clean_p:
            key = (getattr(t, "page_id", "") or "") + "::" + (getattr(t, "url", "") or "")
            if key not in camps:
                title = getattr(t, "campaign_title", "") or getattr(t, "url", "") or "Bài viết"
                camps[key] = {
                    "key": key,
                    "title": title,
                    "url": getattr(t, "url", ""),
                    "platform": getattr(t, "platform", ""),
                    "tasks": [],
                }
            camps[key]["tasks"].append(t)
    return list(camps.values())


def build_execution_tasks(
    scanned_tasks: list,
    platform: str,
    url: str,
    comment_lines: list[str],
) -> list:
    """Chuẩn bị danh sách task thực thi theo đúng nội dung trong ô nhập bình luận.
    Ưu tiên ghép với các task Notion đã quét để giữ nguyên page_id/row_id nhằm cập nhật Notion.
    Tuyệt đối không lẫn lộn giữa các nền tảng khác nhau.
    """
    clean_p = (platform or "").strip().casefold()
    pool = [
        t for t in scanned_tasks
        if (getattr(t, "platform", "") or "").strip().casefold() == clean_p
    ]
    used_ids = set()
    result = []

    from notion_comment_sync import NotionCommentTask

    for idx, text in enumerate(comment_lines):
        clean_text = text.strip()
        if not clean_text:
            continue
        found = None
        for cand in pool:
            cand_id = getattr(cand, "row_id", "") or id(cand)
            if cand_id not in used_ids and getattr(cand, "content", "").strip() == clean_text:
                found = cand
                used_ids.add(cand_id)
                break

        if found:
            if url and getattr(found, "url", "") != url:
                found.url = url
            result.append(found)
        else:
            fallback_cand = None
            for cand in pool:
                cand_id = getattr(cand, "row_id", "") or id(cand)
                if cand_id not in used_ids:
                    fallback_cand = cand
                    used_ids.add(cand_id)
                    break

            if fallback_cand:
                fallback_cand.content = clean_text
                if url:
                    fallback_cand.url = url
                result.append(fallback_cand)
            else:
                result.append(
                    NotionCommentTask(
                        page_id="",
                        stt=idx + 1,
                        content=clean_text,
                        url=url,
                        platform=platform,
                        status="Chưa comment",
                    )
                )

    return result

"""Phân hệ Điều Khiển Bơm Bình Luận (Comment Seeding Controller) đa nền tảng.

Hỗ trợ TikTok và Facebook qua cơ chế Android Deep Link Intent tàng hình,
kết hợp giả lập hành vi người dùng tự nhiên (dwell, jitter, gõ tiếng Việt Unicode).
"""

from __future__ import annotations

import random
import re
import time
import urllib.parse
import urllib.request
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
    log("Bấm nút Gửi bình luận...")
    send_x = int(width * 0.92)
    send_y = int(height * 0.95)
    adb.tap(device_id, send_x, send_y)
    time.sleep(random.uniform(2.0, 3.0))

    # 5. Đóng khung comment để giữ màn hình an toàn
    log("Đóng khung bình luận...")
    backdrop_x = int(width * 0.50)
    backdrop_y = int(height * 0.12)
    adb.tap(device_id, backdrop_x, backdrop_y)
    time.sleep(0.8)

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
    log("Bấm nút Gửi bình luận...")
    send_x = int(width * 0.92)
    send_y = int(height * 0.95)
    adb.tap(device_id, send_x, send_y)
    time.sleep(random.uniform(2.0, 3.0))

    # 5. Thoát khung bình luận (phím Back an toàn)
    log("Thoát khung bình luận...")
    adb.keyevent(device_id, 4)
    time.sleep(0.8)

    log("Đã đăng bình luận Facebook thành công!")
    return True


def execute_comment_task(
    adb,
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

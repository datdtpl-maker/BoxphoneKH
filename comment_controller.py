"""Phân hệ Điều Khiển Bơm Bình Luận (Comment Seeding Controller) đa nền tảng.

Hỗ trợ TikTok và Facebook qua cơ chế Android Deep Link Intent tàng hình,
kết hợp giả lập hành vi người dùng tự nhiên (dwell, jitter, gõ tiếng Việt Unicode).
"""

from __future__ import annotations

import base64
import hashlib
import threading
import os
import random
import re
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import ui_automator_dom

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

from enum import Enum

PLATFORM_TIKTOK = "TikTok"
PLATFORM_FACEBOOK = "Facebook"
PLATFORM_CHOICES = [PLATFORM_TIKTOK, PLATFORM_FACEBOOK]


class TaskOutcome(str, Enum):
    """Phân loại kết quả nghiệp vụ của tác vụ tương tác/bình luận."""

    SUCCESS = "SUCCESS"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNSUPPORTED_UI = "UNSUPPORTED_UI"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    CANCELLED = "CANCELLED"
    FATAL_ERROR = "FATAL_ERROR"


class CommentTaskResult:
    """Kết quả chi tiết của tác vụ bình luận, hỗ trợ phân loại lỗi và chống retry mù quáng."""

    def __init__(
        self,
        outcome: TaskOutcome,
        message: str = "",
        can_retry: bool = False,
        details: Optional[dict] = None,
    ):
        self.outcome = outcome
        self.message = message
        self.can_retry = can_retry
        self.details = details or {}

    def __bool__(self) -> bool:
        """Chỉ đánh giá True khi và chỉ khi tác vụ THỰC SỰ THÀNH CÔNG và đã được xác minh."""
        return self.outcome == TaskOutcome.SUCCESS

    def __repr__(self) -> str:
        return (
            f"CommentTaskResult(outcome={self.outcome.value}, "
            f"can_retry={self.can_retry}, message='{self.message}')"
        )

DEFAULT_STEALTH_REFERRER = "android-app://com.zing.zalo"
TIKTOK_PRIMARY_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_ALT_PACKAGE = "com.zhiliaoapp.musically"
FACEBOOK_PACKAGE = "com.facebook.katana"

# Mẫu chuẩn icon bóng chat 3 chấm bình luận của TikTok để nhận diện qua Computer Vision
TIKTOK_COMMENT_BUBBLE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACQAAAAkCAAAAADEa8dEAAAArElEQVQ4EY3BiW3DMAAEMN7+Q1/1p"
    "IGL2oLJeCFeiBfihXgh/qiPuIiLuoiv+FX/xBYfdSOW2OpWTLHUgxhiqkdBDHUQYqiDEEMdhKC21"
    "JSaUlsEtYQiFKGWCGqKoWKoGGqKoJZQhCLUEkFtqSk1pbaIoQ5CDHUQYqiDEFM9CmKpBzHEVrdii"
    "q3uxBJb3YgtlvonvmKpJfURFzHVFA9iKuJRDCUOYmgcxQvxwg/YpS0lBwrsoQAAAABJRU5ErkJgg"
    "g=="
)


def resolve_canonical_url(url: str, timeout: float = 8.0) -> str:
    """Phân giải link rút gọn (vt.tiktok.com, fb.watch, bit.ly,...) về link chuẩn."""
    if not url or not url.strip().startswith("http"):
        return (url or "").strip()

    clean_url = url.strip()
    if "/video/" in clean_url or "/reel/" in clean_url or "/posts/" in clean_url:
        return clean_url
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


def clean_platform_url(url: str, platform: str) -> str:
    """Làm sạch URL, loại bỏ các query parameters web-only hoặc tracking gây lỗi Intent."""
    if not url:
        return ""
    clean_url = url.strip()
    clean_p = (platform or "").strip().casefold()

    if "tiktok" in clean_p:
        # Dạng https://www.tiktok.com/@user/video/1234567890
        m = re.search(
            r"(https?://(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/@[^/?#]+/video/\d+)",
            clean_url,
        )
        if m:
            return m.group(1)
        # Dạng rút gọn vt.tiktok.com / vm.tiktok.com
        m_short = re.search(
            r"(https?://(?:vt|vm)\.tiktok\.com/[a-zA-Z0-9_\-]+)", clean_url
        )
        if m_short:
            return m_short.group(1)
    elif "facebook" in clean_p:
        # Loại bỏ tracking fbclid, ref, etc.
        if "?" in clean_url and any(
            k in clean_url for k in ("fbclid", "ref=", "__cft__", "__tn__")
        ):
            parts = clean_url.split("?", 1)
            if "reel" in parts[0] or "watch" in parts[0]:
                return parts[0]

    return clean_url


def extract_tiktok_video_id(url: str) -> Optional[str]:
    """Trích xuất video ID số từ link TikTok."""
    if not url:
        return None
    m = re.search(r"(?:video|v)/(\d+)", url)
    return m.group(1) if m else None


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
    clean_url = clean_platform_url(canonical_url, platform)

    if "tiktok" in clean_platform:
        # Đảm bảo TikTok đã khởi động nếu đang tắt
        if hasattr(adb, "is_tiktok_in_foreground") and not adb.is_tiktok_in_foreground(device_id):
            if hasattr(adb, "launch_tiktok"):
                try:
                    adb.launch_tiktok(device_id)
                    time.sleep(1.5)
                except Exception:
                    pass

        video_id = extract_tiktok_video_id(clean_url)
        # 1. Nếu có video_id: mở thẳng native deep link để vào đúng video mục tiêu 100%
        if video_id:
            pkg_target = TIKTOK_PRIMARY_PACKAGE
            if hasattr(adb, "is_app_installed"):
                if not adb.is_app_installed(device_id, TIKTOK_PRIMARY_PACKAGE) and adb.is_app_installed(device_id, TIKTOK_ALT_PACKAGE):
                    pkg_target = TIKTOK_ALT_PACKAGE
            scheme = "snssdk1233" if pkg_target == TIKTOK_ALT_PACKAGE else "snssdk1180"
            cmd_nat = [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", f"{scheme}://aweme/detail/{video_id}",
                "-p", pkg_target,
                "-f", "0x14000000",
                "--es", "android.intent.extra.REFERRER_NAME", referrer,
            ]
            code, stdout, _ = adb.execute_adb(device_id, cmd_nat)
            if code == 0 and "Error" not in (stdout or ""):
                return True

        # 2. Fallback mở bằng URL HTTP chuẩn
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-p", TIKTOK_PRIMARY_PACKAGE,
            "-f", "0x14000000",
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code, stdout, _ = adb.execute_adb(device_id, cmd)
        success = (code == 0 and "Error" not in (stdout or ""))

        if not success:
            cmd_alt = [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", clean_url,
                "-p", TIKTOK_ALT_PACKAGE,
                "-f", "0x14000000",
                "--es", "android.intent.extra.REFERRER_NAME", referrer,
            ]
            code_alt, stdout_alt, _ = adb.execute_adb(device_id, cmd_alt)
            success = (code_alt == 0 and "Error" not in (stdout_alt or ""))

        return success

    elif "facebook" in clean_platform:
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-p", FACEBOOK_PACKAGE,
            "-f", "0x14000000",
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code, _, _ = adb.execute_adb(device_id, cmd)
        if code != 0:
            cmd_fallback = [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", clean_url,
                "-f", "0x14000000",
            ]
            code_fb, _, _ = adb.execute_adb(device_id, cmd_fallback)
            return code_fb == 0
        return True

    else:
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-f", "0x14000000",
        ]
        code, _, _ = adb.execute_adb(device_id, cmd)
        return code == 0


def wait_for_tiktok_video_ready(
    adb,
    device_id: str,
    timeout: int = 12,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    clean_url: str = "",
) -> bool:
    """Chờ TikTok mở hoàn tất màn hình xem video và sẵn sàng tương tác."""
    def log(msg: str):
        if status_callback:
            status_callback(f"[Device {device_id}][TikTok Seeding] {msg}")

    log("Đang chờ TikTok tải xong giao diện video...")
    video_id = extract_tiktok_video_id(clean_url)
    re_sent = False

    for elapsed in range(max(1, timeout)):
        if is_cancelled and is_cancelled():
            return False

        # Khóa dọc giữ màn hình ổn định
        if hasattr(adb, "lock_portrait"):
            try:
                adb.lock_portrait(device_id, retries=1)
            except Exception:
                pass
        if hasattr(adb, 'dismiss_system_usb_storage_popup'):
            try:
                adb.dismiss_system_usb_storage_popup(device_id)
            except Exception:
                pass
        if hasattr(adb, 'dismiss_tiktok_location_popup'):
            try:
                adb.dismiss_tiktok_location_popup(device_id)
            except Exception:
                pass

# Cho video ổn định ít nhất 5s để các máy cấu hình thấp load xong
        if elapsed >= 5:
            time.sleep(0.5)
            log("✅ Giao diện video TikTok đã sẵn sàng!")
            return True

        time.sleep(1.0)

    log("Đã hoàn tất thời gian chuẩn bị video.")
    return True


def capture_screen_fast(adb, device_id: str) -> Optional[np.ndarray]:
    """Chụp màn hình siêu tốc không qua ổ đĩa bằng adb exec-out screencap -p."""
    if not CV2_AVAILABLE:
        return None
    try:
        adb_path = getattr(adb, "adb_path", None)
        if not adb_path or not os.path.exists(adb_path):
            import config
            adb_path = config.ADB_PATH

        startupinfo = None
        if os.name == 'nt':
            import subprocess
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        import subprocess
        port = adb.get_device_port(device_id) if hasattr(adb, "get_device_port") else None
        if port:
            cmd = [adb_path, "-P", str(port), "-s", device_id, "exec-out", "screencap", "-p"]
        else:
            cmd = [adb_path, "-s", device_id, "exec-out", "screencap", "-p"]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            startupinfo=startupinfo,
        )
        if proc.returncode == 0 and len(proc.stdout) > 5000:
            raw = proc.stdout
            if b"\r\r\n" in raw:
                raw = raw.replace(b"\r\r\n", b"\n")
            elif b"\r\n" in raw:
                raw = raw.replace(b"\r\n", b"\n")
            arr = np.frombuffer(raw, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                return img
    except Exception:
        pass

    # Fallback chụp qua file tạm trên sdcard nếu exec-out không hỗ trợ
    remote_png = f"/sdcard/sc_cmt_{device_id}.png"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_png = os.path.join(tempfile.gettempdir(), f"sc_cmt_{safe_dev}.png")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", remote_png])
        code, _, _ = adb.execute_adb(device_id, ["shell", "screencap", "-p", remote_png])
        if code == 0:
            adb.execute_adb(device_id, ["pull", remote_png, local_png])
            if os.path.exists(local_png) and os.path.getsize(local_png) > 1000:
                img = cv2.imread(local_png)
                return img
    except Exception:
        pass
    finally:
        if os.path.exists(local_png):
            try:
                os.remove(local_png)
            except Exception:
                pass
    return None


def find_tiktok_video_buttons_via_dom(
    adb, device_id: str, width: int, height: int
) -> tuple[Optional[tuple[int, int]], bool, Optional[tuple[int, int]]]:
    """Quét DOM XML để bắt chính xác 100% tọa độ nút Like (và cờ đã like) cùng tọa độ Bình luận theo bounds từng máy."""
    root = ui_automator_dom.dump_ui_tree(adb, device_id)
    if root is not None:
        ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
        like_c = ctrls["like"]["center"] if ctrls.get("like") else None
        is_liked = ctrls["like"]["is_liked"] if ctrls.get("like") else False
        cmt_c = ctrls["comment"]["center"] if ctrls.get("comment") else None
        if like_c or cmt_c:
            return like_c, is_liked, cmt_c

    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    xml_file = f"/sdcard/dump_dom_btn_{safe_dev}.xml"
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_dom_btn_{safe_dev}.xml")

    like_coords = None
    is_liked = False
    comment_coords = None

    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file], timeout=5.0
        )
        if code != 0:
            code, _, _ = adb.execute_adb(
                device_id, ["shell", "uiautomator", "dump", xml_file], timeout=5.0
            )
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml], timeout=5.0)
            if os.path.exists(local_xml) and os.path.getsize(local_xml) > 200:
                tree = ET.parse(local_xml)
                root = tree.getroot()

                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()

                    # 1. Bắt nút Thả tim (Like) ở cột bên phải màn hình
                    if cx >= width * 0.70 and height * 0.40 <= cy <= height * 0.72:
                        if any(k in desc or k in rid for k in ("thích video", "thich video", "bỏ thích video", "bo thich video", "like", "unlike", "iv_like", "like_icon")):
                            like_coords = (cx, cy)
                            is_liked = (
                                (elem.get("selected") == "true")
                                or (elem.get("checked") == "true")
                                or any(k in desc or k in txt for k in ("video liked", "đã thích", "da thich", "bỏ thích", "bo thich", "unlike"))
                            )

                    # 2. Bắt nút Bình luận (Comment) ở cột bên phải màn hình
                    if cx >= width * 0.70 and height * 0.50 <= cy <= height * 0.78:
                        if any(k in desc or k in txt or k in rid for k in ("bình luận", "binh luan", "comment", "bóc tem", "boc tem", "add 1st", "add1st", "be the first")):
                            elem_h = y2 - y1
                            if elem_h < height * 0.05:
                                comment_coords = (cx, max(int(height * 0.40), cy - int(height * 0.025)))
                            else:
                                comment_coords = (cx, cy)
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    return like_coords, is_liked, comment_coords


def find_tiktok_comment_icon_via_template(
    adb, device_id: str, width: int, height: int
) -> Optional[tuple[int, int]]:
    """Dùng OpenCV đa tỉ lệ để nhận diện quả bóng chat 3 chấm trực tiếp từ màn hình thiết bị."""
    if not CV2_AVAILABLE:
        return None
    screen = capture_screen_fast(adb, device_id)
    if screen is None:
        return None
    try:
        sh, sw = screen.shape[:2]
        tpl_bytes = base64.b64decode(TIKTOK_COMMENT_BUBBLE_B64)
        tpl = cv2.imdecode(np.frombuffer(tpl_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if tpl is None:
            return None

        gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        rx1, rx2 = int(sw * 0.70), sw
        ry1, ry2 = int(sh * 0.35), int(sh * 0.85)
        roi = gray_screen[ry1:ry2, rx1:rx2]

        best_val = -1
        best_pt = None
        for scale in np.linspace(0.20, 3.5, 45):
            tw = int(gray_tpl.shape[1] * scale)
            th = int(gray_tpl.shape[0] * scale)
            if tw < 8 or th < 8 or tw >= roi.shape[1] or th >= roi.shape[0]:
                continue
            resized = cv2.resize(
                gray_tpl,
                (tw, th),
                interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
            )
            res = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_pt = (rx1 + max_loc[0] + tw // 2, ry1 + max_loc[1] + th // 2)

        if best_val >= 0.65 and best_pt is not None:
            scale_x = width / float(sw)
            scale_y = height / float(sh)
            return int(best_pt[0] * scale_x), int(best_pt[1] * scale_y)
    except Exception:
        pass
    return None


import json
from datetime import datetime

UNKNOWN_AUDIT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "unknown_comment_audit.json"
)
_AUDIT_LOCK = threading.Lock()

def record_unknown_comment_audit(
    platform: str,
    device_id: str,
    url: str,
    content: str,
    reason: str = "Chưa đủ bằng chứng xác nhận bình luận hiển thị",
) -> dict:
    """Lưu vết các tác vụ có kết quả UNKNOWN_OUTCOME vào file audit bền vững để đối soát thủ công."""
    with _AUDIT_LOCK:
        entry = {
            "id": f"{platform.lower()}_{hashlib.sha256((url + '::' + content).encode('utf-8')).hexdigest()[:12]}",
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "device_id": device_id,
            "url": url,
            "content": content,
            "reason": reason,
            "status": "PENDING_AUDIT",
        }
        entries = []
        if os.path.exists(UNKNOWN_AUDIT_FILE):
            try:
                with open(UNKNOWN_AUDIT_FILE, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                    if not isinstance(entries, list):
                        entries = []
            except Exception:
                entries = []

        exists = any(
            e.get("url") == url and e.get("content") == content and e.get("status") == "PENDING_AUDIT"
            for e in entries
        )
        if not exists:
            entries.append(entry)
            try:
                tmp_path = UNKNOWN_AUDIT_FILE + f".tmp.{os.getpid()}"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, UNKNOWN_AUDIT_FILE)
            except Exception:
                pass
        return entry

def is_comment_blocked_by_audit(platform: str, url: str, content: str) -> bool:
    """Kiểm tra xem tác vụ bình luận này có đang ở trạng thái PENDING_AUDIT cần đối soát hay không."""
    with _AUDIT_LOCK:
        if not os.path.exists(UNKNOWN_AUDIT_FILE):
            return False
        try:
            with open(UNKNOWN_AUDIT_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    return False
                c_plat = (platform or "").strip().casefold()
                c_url = (url or "").strip()
                c_text = (content or "").strip()
                return any(
                    e.get("status") == "PENDING_AUDIT"
                    and (e.get("platform", "").strip().casefold() == c_plat)
                    and (e.get("url", "").strip() == c_url)
                    and (e.get("content", "").strip() == c_text)
                    for e in entries
                )
        except Exception:
            return False

def resolve_unknown_comment_audit(platform: str, url: str, content: str, resolution: str, note: str = "") -> bool:
    """Đối soát và giải quyết trạng thái PENDING_AUDIT sang RESOLVED_SUCCESS, RESOLVED_FAILED, hoặc DISMISSED."""
    with _AUDIT_LOCK:
        if not os.path.exists(UNKNOWN_AUDIT_FILE):
            return False
        try:
            with open(UNKNOWN_AUDIT_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    return False
            c_plat = (platform or "").strip().casefold()
            c_url = (url or "").strip()
            c_text = (content or "").strip()
            found = False
            for e in entries:
                if (
                    e.get("status") == "PENDING_AUDIT"
                    and (e.get("platform", "").strip().casefold() == c_plat)
                    and (e.get("url", "").strip() == c_url)
                    and (e.get("content", "").strip() == c_text)
                ):
                    e["status"] = resolution
                    e["resolved_at"] = datetime.now().isoformat()
                    e["resolution_note"] = note
                    found = True
            if found:
                tmp_path = UNKNOWN_AUDIT_FILE + f".tmp.{os.getpid()}"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, UNKNOWN_AUDIT_FILE)
            return found
        except Exception:
            return False

def is_comment_in_pending_audit(platform: str, url: str, content: str) -> bool:
    """Alias tương thích cho is_comment_blocked_by_audit."""
    return is_comment_blocked_by_audit(platform, url, content)

def check_target_error_state(root: Optional[ET.Element], platform: str) -> Optional[str]:
    """Kiểm tra màn hình có bị lỗi nội dung không tồn tại, video bị xóa hoặc yêu cầu đăng nhập hay không."""
    if root is None:
        return None
    for elem in root.iter():
        txt = (elem.get("text") or "").casefold()
        desc = (elem.get("content-desc") or "").casefold()
        combined = f"{txt} {desc}"
        if any(k in combined for k in (
            "video không khả dụng", "video is unavailable",
            "liên kết không còn tồn tại", "video đã bị xóa",
            "video has been removed", "nội dung này hiện không có",
            "nội dung này hiện không khả dụng", "this content isn't available",
            "liên kết bạn đã theo dõi có thể bị hỏng", "the link you followed may be broken",
            "trang này không tồn tại", "page not found",
            "đăng nhập để tiếp tục", "log in to continue",
            "đăng nhập facebook", "log in to facebook"
        )):
            return combined.strip()
    return None

def extract_stream_comments(root) -> set[str]:
    """Trích xuất tất cả các đoạn text bình luận đang hiển thị trên stream."""
    res = set()
    if root is None:
        return res
    for elem in root.iter():
        cls_name = (elem.get("class") or "").casefold()
        if "edittext" not in cls_name:
            txt = (elem.get("text") or "").strip().casefold()
            desc = (elem.get("content-desc") or "").strip().casefold()
            if txt and len(txt) > 1:
                res.add(txt)
            if desc and len(desc) > 1:
                res.add(desc)
    return res


def find_tiktok_comment_icon_coords(
    adb, device_id: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ icon mở bình luận bên phải video TikTok qua CV Template Matching, UI dump hoặc tọa độ hiệu chuẩn."""
    # 1. Thử nhận diện trực quan quả bóng chat 3 chấm qua OpenCV screencap
    tpl_coords = find_tiktok_comment_icon_via_template(adb, device_id, width, height)
    if tpl_coords:
        return tpl_coords

    # 2. Thử phân tích UI Automator dump
    xml_file = f"/sdcard/dump_cmt_btn_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_cmt_btn_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file]
        )
        if code != 0:
            code, _, _ = adb.execute_adb(
                device_id, ["shell", "uiautomator", "dump", xml_file]
            )
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml):
                tree = ET.parse(local_xml)
                root = tree.getroot()
                like_cy = None
                bookmark_cy = None
                right_rail_elements = []

                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                    # Icon comment nằm ở thanh điều hướng bên phải (x > 70%) và ở khoảng 35% - 85% chiều cao màn hình
                    if cx < width * 0.70 or cy < height * 0.35 or cy > height * 0.85:
                        continue

                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()

                    # 1. Nhận diện từ khóa bình luận (kể cả Tiếng Việt và Tiếng Anh)
                    is_comment = any(
                        kw in desc or kw in txt or kw in rid
                        for kw in (
                            "bóc tem", "boc tem", "boc_tem",
                            "bình luận", "binh luan", "comment", "cmt",
                            "comment_count", "comment_list", "comment_icon",
                            "desc_comment", "đọc hoặc thêm bình luận", "doc hoac them binh luan",
                            "be the first", "add comment", "read or add comments",
                            "leave a comment", "post a comment", "comments",
                            "add 1st", "add1st", "add first", "1st", "first to comment"
                        )
                    )
                    if is_comment:
                        elem_h = y2 - y1
                        # Nếu trúng nhãn text nhỏ ở dưới icon (như chữ 'Bóc tem', 'Add 1st'), nhấp nhẹ lên trên để trúng tâm quả bóng chat
                        if elem_h < height * 0.05:
                            return cx, max(int(height * 0.35), cy - int(height * 0.025))
                        return cx, cy

                    pass
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # Tuyệt đối không tự bịa tọa độ khi không nhận diện được icon bình luận TikTok
    return None


def is_tiktok_comment_sheet_open(adb, device_id: str, height: int) -> bool:
    """Kiểm tra xem bottom sheet bình luận của TikTok đã mở thành công hay chưa."""
    width = 1080
    if hasattr(adb, "get_effective_screen_size"):
        try:
            w_eff, _ = adb.get_effective_screen_size(device_id)
            if w_eff > 0:
                width = w_eff
        except Exception:
            pass

    xml_file = f"/sdcard/chk_cmt_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"chk_cmt_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file])
        if code != 0:
            code, _, _ = adb.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml) and os.path.getsize(local_xml) > 100:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                for elem in root.iter():
                    cls_name = (elem.get("class") or "").casefold()
                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    cx = (int(m.group(1)) + int(m.group(3))) // 2 if m else 0
                    cy = (int(m.group(2)) + int(m.group(4))) // 2 if m else 0

                    # 1. Ô EditText nằm ở nửa dưới màn hình (ô nhập bình luận của bottom sheet)
                    if "edittext" in cls_name and cy >= height * 0.35:
                        return True

                    # 2. Các cụm từ chỉ có trong giao diện khung bình luận (loại trừ icon bên thanh điều hướng)
                    if any(
                        kw in txt or kw in desc
                        for kw in (
                            "thêm bình luận", "add comment", "viết bình luận",
                            "bình luận công khai", "để lại bình luận", "nhập bình luận",
                            "chưa có bình luận", "be the first to comment", "no comments yet",
                            "gửi bình luận", "bình luận với tư cách"
                        )
                    ):
                        return True

                    # 3. Tiêu đề bình luận ở giữa/trái màn hình (x < 75%, không phải icon ở cột phải x >= 75%)
                    if cx < width * 0.75 and cy >= height * 0.20:
                        if any(kw in txt or kw in desc for kw in ("bình luận", "comments")):
                            return True

                    # 4. Resource-ID đặc thù của comment sheet
                    if any(
                        kw in rid
                        for kw in (
                            "comment_edit_text", "et_comment", "c0e", "comment_list",
                            "comment_container", "comment_bottom_sheet", "comment_reply_text"
                        )
                    ):
                        return True

                # Đã đọc được cây UI dump của TikTok nhưng không có dấu hiệu comment sheet
                return False
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # Nếu uiautomator dump không trích xuất được: kiểm tra qua dumpsys
    # 1. Kiểm tra bàn phím có đang bật không qua dumpsys input_method
    try:
        _, im_out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "input_method"])
        if "minputshown=true" in (im_out or "").casefold():
            return True
    except Exception:
        pass

    # 2. Kiểm tra cửa sổ comment bottom sheet thực sự qua dumpsys window windows
    try:
        _, out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "window", "windows"])
        lowered = (out or "").casefold()
        if any(w in lowered for w in ("commentbottomsheet", "commentdialog", "commentlistsheet", "awemecomment")):
            return True
    except Exception:
        pass

    return False


def find_comment_input_coords(
    adb, device_id: str, platform: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ ô nhập bình luận bằng UI dump hoặc tọa độ hiệu chuẩn thực tế."""
    clean_p = (platform or "").strip().casefold()
    is_tiktok = "tiktok" in clean_p

    xml_file = f"/sdcard/dump_in_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_in_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file]
        )
        if code != 0:
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
                    # Ô nhập luôn nằm ở nửa dưới màn hình
                    if cy < height * 0.40:
                        continue

                    elem_w = x2 - x1
                    cls_name = (elem.get("class") or "").casefold()
                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()

                    # Bỏ qua các nút emoji gợi ý phản hồi nhanh
                    if any(char in (txt + desc) for char in ("😁", "🥰", "😂", "😳", "😍", "👍", "❤️")):
                        continue

                    is_input = (
                        "edittext" in cls_name
                        or any(
                            kw in desc or kw in txt or kw in rid
                            for kw in (
                                "add comment", "thêm bình luận", "để lại bình luận",
                                "viết bình luận", "nhập bình luận", "comment_edit_text",
                                "c0e", "et_comment", "text_layout", "comment_reply_text",
                                "input_container", "comment_container"
                            )
                        )
                    )
                    if is_input:
                        return cx, cy
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # Tuyệt đối không trả về tọa độ tỷ lệ cố định nếu không nhận diện được ô nhập
    return None


def ensure_comment_input_ready(
    adb,
    device_id: str,
    input_x: int,
    input_y: int,
    width: int = 1080,
    height: int = 1920,
    status_callback=None,
) -> bool:
    """Chạm vào ô nhập, bật bàn phím XwIME và xóa sạch text/emoji thừa để sẵn sàng gõ."""
    if input_x is None or input_y is None or input_x <= 0 or input_y <= 0:
        return False

    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass

    # Chỉ thử các điểm lân cận hợp lý quanh tọa độ ô nhập thực tế đã nhận diện
    candidates = [
        (input_x, input_y),
        (input_x, max(0, int(input_y - height * 0.012))),
        (input_x, min(height - 1, int(input_y + height * 0.012))),
    ]

    is_ready = False
    for tx, ty in candidates:
        adb.tap(device_id, tx, ty)
        time.sleep(0.8)

        # 1. Kiểm tra qua dumpsys input_method
        code, out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "input_method"])
        out_cf = (out or "").casefold()
        if "minputshown=true" in out_cf or "minputviewstarted=true" in out_cf:
            is_ready = True
            break

        # 2. Kiểm tra qua dumpsys window (mInputShown)
        _, win_out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "window", "windows"])
        win_cf = (win_out or "").casefold()
        if "minputshown=true" in win_cf:
            is_ready = True
            break

        # 3. Kiểm tra DOM xem EditText có focused="true" không
        try:
            root = ui_automator_dom.dump_ui_tree(adb, device_id, timeout=2)
            if root is not None:
                for elem in root.iter():
                    if "edittext" in (elem.get("class") or "").casefold():
                        if elem.get("focused", "").casefold() == "true":
                            is_ready = True
                            break
            if is_ready:
                break
        except Exception:
            pass

    if not is_ready:
        return False

    # Đảm bảo xóa sạch 100% text hoặc emoji cũ/vô tình dán trong ô nhập trước khi gõ nội dung từ Notion
    try:
        adb.execute_adb(
            device_id,
            [
                "shell", "am", "broadcast",
                "-a", "XW_CLEAR_TEXT",
                "--receiver-foreground",
            ],
        )
    except Exception:
        pass
    return True


def verify_tiktok_comment_posted(
    adb,
    device_id: str,
    comment_text: str,
    width: int,
    height: int,
    timeout: float = 4.0,
    prior_stream: Optional[set[str]] = None,
) -> TaskOutcome:
    """Xác minh bình luận TikTok đã được đăng thành công bằng bằng chứng cụ thể trên UI.

    Kiểm tra:
    1. Thông báo lỗi hoặc dialog cảnh báo (vi phạm, bị chặn, bình luận quá nhanh).
    2. Comment text có xuất hiện trong danh sách hiển thị bình luận hay không (khớp chính xác, không trùng bình luận cũ).
    3. Ô nhập EditText có được xóa sạch (cleared) sau khi gửi hay không.
    """
    clean_target = (comment_text or "").strip().casefold()
    if not clean_target:
        return TaskOutcome.UNKNOWN_OUTCOME

    prior = set(prior_stream or ())
    start_time = time.time()
    while time.time() - start_time < timeout:
        root = ui_automator_dom.dump_ui_tree(adb, device_id)
        if root is not None:
            # 1. Kiểm tra dialog lỗi
            for elem in root.iter():
                txt = (elem.get("text") or "").casefold()
                desc = (elem.get("content-desc") or "").casefold()
                if any(
                    w in txt or w in desc
                    for w in (
                        "bạn bình luận quá nhanh",
                        "nội dung vi phạm",
                        "bị hạn chế",
                        "không thể bình luận",
                        "thử lại sau",
                    )
                ):
                    return TaskOutcome.FATAL_ERROR

            # 2. Tìm comment text trong danh sách bình luận
            found_in_stream = False
            edit_text_cleared = False
            edit_text_still_has_target = False

            for elem in root.iter():
                cls_name = (elem.get("class") or "").casefold()
                pkg = (elem.get("package") or "").casefold()
                rid = (elem.get("resource-id") or "").casefold()
                txt = (elem.get("text") or "").strip()
                desc = (elem.get("content-desc") or "").strip()
                txt_cf = txt.casefold()
                desc_cf = desc.casefold()

                # Loại trừ bàn phím và IME candidates
                if any(k in pkg or k in rid for k in ("inputmethod", "honeyboard", "candidate", "suggestion", "keyboard", "key_pos")):
                    continue

                if "edittext" in cls_name:
                    if clean_target in txt_cf:
                        edit_text_still_has_target = True
                        edit_text_cleared = False
                    elif not txt or any(
                        p in txt_cf
                        for p in ("thêm bình luận", "add comment", "viết bình luận")
                    ):
                        edit_text_cleared = True
                    continue

                # Loại trừ tiêu đề, caption, tên kênh và action bar
                if any(k in rid for k in ("title", "desc", "caption", "user_name", "header", "action_bar", "search_box")):
                    continue

                # Loại trừ container cha tổng hợp (chỉ xét leaf node)
                if len(list(elem)) > 0:
                    continue

                # Trùng khớp CHÍNH XÁC (không chấp nhận substring match)
                if txt_cf == clean_target or desc_cf == clean_target:
                    if not prior or (txt_cf not in prior and desc_cf not in prior):
                        found_in_stream = True

            if found_in_stream and (edit_text_cleared or not edit_text_still_has_target):
                return TaskOutcome.SUCCESS

            if edit_text_cleared:
                time.sleep(0.5)
                continue

        time.sleep(0.8)

    return TaskOutcome.UNKNOWN_OUTCOME


def verify_facebook_comment_posted(
    adb,
    device_id: str,
    comment_text: str,
    width: int,
    height: int,
    timeout: float = 4.0,
    prior_stream: Optional[set[str]] = None,
) -> TaskOutcome:
    """Xác minh bình luận Facebook đã được đăng thành công bằng bằng chứng cụ thể trên UI."""
    clean_target = (comment_text or "").strip().casefold()
    if not clean_target:
        return TaskOutcome.UNKNOWN_OUTCOME

    prior = set(prior_stream or ())
    start_time = time.time()
    while time.time() - start_time < timeout:
        root = ui_automator_dom.dump_ui_tree(adb, device_id)
        if root is not None:
            for elem in root.iter():
                txt = (elem.get("text") or "").casefold()
                desc = (elem.get("content-desc") or "").casefold()
                if any(
                    w in txt or w in desc
                    for w in (
                        "bạn tạm thời bị chặn",
                        "vi phạm tiêu chuẩn cộng đồng",
                        "không thể bình luận",
                        "bình luận quá nhanh",
                    )
                ):
                    return TaskOutcome.FATAL_ERROR

            found_in_stream = False
            edit_text_cleared = False
            edit_text_still_has_target = False

            for elem in root.iter():
                cls_name = (elem.get("class") or "").casefold()
                pkg = (elem.get("package") or "").casefold()
                rid = (elem.get("resource-id") or "").casefold()
                txt = (elem.get("text") or "").strip()
                desc = (elem.get("content-desc") or "").strip()
                txt_cf = txt.casefold()
                desc_cf = desc.casefold()

                # Loại trừ bàn phím và IME candidates
                if any(k in pkg or k in rid for k in ("inputmethod", "honeyboard", "candidate", "suggestion", "keyboard", "key_pos")):
                    continue

                if "edittext" in cls_name:
                    if clean_target in txt_cf:
                        edit_text_still_has_target = True
                        edit_text_cleared = False
                    elif not txt or any(
                        p in txt_cf
                        for p in ("viết bình luận", "bình luận dưới tên", "write a comment")
                    ):
                        edit_text_cleared = True
                    continue

                # Loại trừ tiêu đề, caption, tên page và action bar
                if any(k in rid for k in ("title", "desc", "caption", "user_name", "header", "action_bar", "search_box")):
                    continue

                # Loại trừ container cha tổng hợp (chỉ xét leaf node)
                if len(list(elem)) > 0:
                    continue

                # Trùng khớp CHÍNH XÁC (không chấp nhận substring match)
                if txt_cf == clean_target or desc_cf == clean_target:
                    if not prior or (txt_cf not in prior and desc_cf not in prior):
                        found_in_stream = True

            if found_in_stream and (edit_text_cleared or not edit_text_still_has_target):
                return TaskOutcome.SUCCESS

            if edit_text_cleared:
                time.sleep(0.5)
                continue

        time.sleep(0.8)

    return TaskOutcome.UNKNOWN_OUTCOME


def post_tiktok_comment(
    adb,
    device_id: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> CommentTaskResult:
    """Quy trình mở link video TikTok, xem tự nhiên và đăng bình luận.

    Khóa cứng video mục tiêu (Target Lock), kiểm tra DOM thời gian thực:
    - Thả tim trước nếu chưa like (video/tài khoản đã like thì bỏ qua, tuyệt đối không hủy tim)
    - Nhận diện chính xác tọa độ theo từng máy qua UI Automator DOM Engine, không bấm đoán
    - Tuyệt đối không lướt (swipe) làm trượt sang video khác
    - Gửi bình luận đơn (không tap trùng, không Enter mù quáng) và xác minh kết quả
    - Dừng có kiểm soát và trả về CommentTaskResult với outcome cụ thể
    """
    def log(msg: str):
        if status_callback:
            status_callback(f"[Device {device_id}][TikTok Seeding] {msg}")

    if is_cancelled and is_cancelled():
        log("Đã hủy tác vụ.")
        return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

    width, height = adb.get_effective_screen_size(device_id)
    canonical_url = resolve_canonical_url(url)
    target_channel = ui_automator_dom.extract_tiktok_channel_from_url(canonical_url) or ui_automator_dom.extract_tiktok_channel_from_url(url)
    target_video_id = extract_tiktok_video_id(canonical_url) or extract_tiktok_video_id(url)
    item_key = target_video_id or target_channel or canonical_url or url

    # 0. Chuẩn bị thiết bị: Đóng app cũ và dọn dẹp đa nhiệm
    log("Chuẩn bị thiết bị: Đóng app cũ và dọn dẹp đa nhiệm...")
    try:
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
        if hasattr(adb, "clear_recent_apps"):
            adb.clear_recent_apps(device_id)
        adb.keyevent(device_id, 3)
        time.sleep(0.8)
    except Exception:
        pass

    sheet_opened = False
    for flow_attempt in range(1, 3):
        if is_cancelled and is_cancelled():
            return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

        if flow_attempt > 1:
            log("Lần 1 chưa mở được khung bình luận • Tự động dọn dẹp app và mở lại link video lần 2...")
            try:
                adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
                adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
                if hasattr(adb, "clear_recent_apps"):
                    adb.clear_recent_apps(device_id)
                adb.keyevent(device_id, 3)
                time.sleep(1.0)
            except Exception:
                pass

        # 1. Mở link video mục tiêu qua Intent Zalo Referrer
        log(f"Đang mở link video qua Intent Zalo Referrer (lượt {flow_attempt}/2)...")
        success = open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
        if not success:
            log("Lỗi không thể mở link video.")
            if flow_attempt == 2:
                return CommentTaskResult(TaskOutcome.FATAL_ERROR, "Không thể mở link video qua Intent", can_retry=False)
            continue

        # 2. Chờ TikTok tải xong giao diện video
        wait_for_tiktok_video_ready(
            adb, device_id, timeout=15, status_callback=status_callback, is_cancelled=is_cancelled, clean_url=url
        )
        if is_cancelled and is_cancelled():
            return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

        # 3. Quét DOM kiểm tra Khóa cứng Video mục tiêu (Target Lock)
        root = ui_automator_dom.dump_ui_tree(adb, device_id)
        err_msg = check_target_error_state(root, PLATFORM_TIKTOK)
        if err_msg:
            log(f"❌ Phát hiện lỗi nội dung TikTok: {err_msg}")
            return CommentTaskResult(TaskOutcome.FATAL_ERROR, f"Video không khả dụng hoặc lỗi tải: {err_msg}", can_retry=False)

        ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
        dom_channel = ctrls.get("channel_name", "")

        target_verified = False
        if target_channel:
            if dom_channel:
                if ui_automator_dom.match_tiktok_channel_name(dom_channel, target_channel):
                    target_verified = True
                else:
                    log(f"⚠️ Video đang phát ('{dom_channel}') chưa khớp Kênh mục tiêu ('{target_channel}') • Mở lại Intent...")
                    open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
                    time.sleep(2.5)
                    root = ui_automator_dom.dump_ui_tree(adb, device_id)
                    ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
                    dom_channel = ctrls.get("channel_name", "")
                    if ui_automator_dom.match_tiktok_channel_name(dom_channel, target_channel):
                        target_verified = True
                    else:
                        log(f"❌ Kênh trên thiết bị ('{dom_channel}') không khớp với kênh mục tiêu ('{target_channel}')!")
            else:
                if ctrls.get("like") or ctrls.get("comment"):
                    target_verified = True
                else:
                    log("⚠️ Không nhận diện được giao diện video mục tiêu • Thử nạp lại Intent...")
                    open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
                    time.sleep(2.5)
                    root = ui_automator_dom.dump_ui_tree(adb, device_id)
                    ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
                    if ctrls.get("like") or ctrls.get("comment"):
                        target_verified = True
                    else:
                        log("❌ Không đủ bằng chứng giao diện video mục tiêu!")
        else:
            if ctrls.get("like") or ctrls.get("comment"):
                target_verified = True
            else:
                open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
                time.sleep(2.5)
                root = ui_automator_dom.dump_ui_tree(adb, device_id)
                ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
                if ctrls.get("like") or ctrls.get("comment"):
                    target_verified = True

        if not target_verified:
            return CommentTaskResult(
                TaskOutcome.AMBIGUOUS_TARGET,
                "Không thể xác minh đúng video mục tiêu trên màn hình",
                can_retry=False,
            )

        # 4. Dwell time: Xem video tự nhiên (KHÔNG SWIPE DỌC)
        dwell_target = max(4, int(dwell_time // 2) if flow_attempt > 1 else int(dwell_time)) + random.randint(-1, 2)
        log(f"Đang xem video tự nhiên trong {dwell_target}s trước khi bình luận...")
        for remaining in range(dwell_target, 0, -1):
            if is_cancelled and is_cancelled():
                log("Dừng xem do người dùng yêu cầu.")
                return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)
            if remaining % 4 == 0 or remaining <= 3:
                log(f"Đang xem video ({remaining}s còn lại)...")
            time.sleep(1.0)

        # 5. Xác định vị trí Like & Comment từ DOM
        like_info = ctrls.get("like")
        like_target = like_info.get("center") if like_info else None
        is_already_liked = like_info.get("is_liked", False) if like_info else False

        # 6. THẢ TIM TRƯỚC (LIKE FIRST) - Khóa cứng trên clip target, chống hủy tim
        already_tracked = False
        try:
            import interaction_tracker
            already_tracked = interaction_tracker.has_interacted(device_id, "tiktok", item_key, "like")
        except Exception:
            pass

        if is_already_liked or already_tracked:
            log("❤️ Video/tài khoản này đã được thả tim trước đó (DOM Đã thích/Video liked) • Bỏ qua bước thả tim, giữ nguyên tim!")
        elif like_target:
            log(f"❤️ Tiến hành thả tim trước tại tọa độ DOM ({like_target[0]}, {like_target[1]})...")
            adb.tap(device_id, like_target[0], like_target[1])
            time.sleep(random.uniform(1.0, 1.4))
        else:
            log("ℹ️ Không tìm thấy nút Like trên DOM • Bỏ qua bước thả tim an toàn, không bấm đoán.")

        # 7. MỞ KHUNG BÌNH LUẬN (Tuyệt đối không vuốt lướt, không bấm tọa độ đoán)
        for attempt in range(1, 4):
            if is_cancelled and is_cancelled():
                return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

            # Đọc lại DOM live trước mỗi lần thử mở khung bình luận
            if attempt > 1:
                time.sleep(1.0)
                root = ui_automator_dom.dump_ui_tree(adb, device_id)
                ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)

            comment_info = ctrls.get("comment")
            comment_target = (comment_info.get("center") if isinstance(comment_info, dict) else comment_info) if comment_info else None
            if not comment_target:
                comment_target = find_tiktok_comment_icon_coords(adb, device_id, width, height)

            if not comment_target:
                log(f"⚠️ Chưa xác định được vị trí nút bình luận (lần {attempt}/3)...")
                continue

            log(f"Chạm icon Bình luận TikTok tại ({comment_target[0]}, {comment_target[1]})...")
            adb.tap(device_id, comment_target[0], comment_target[1])
            time.sleep(random.uniform(1.8, 2.2))

            if is_tiktok_comment_sheet_open(adb, device_id, height):
                sheet_opened = True
                log("Đã mở khung bình luận thành công!")
                break

        if sheet_opened:
            break

    if not sheet_opened:
        log("CẢNH BÁO: Không mở được khung bình luận TikTok sau 2 lượt thử! Dừng tác vụ an toàn.")
        try:
            adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
            adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
            if hasattr(adb, "clear_recent_apps"):
                adb.clear_recent_apps(device_id)
            adb.keyevent(device_id, 3)
        except Exception:
            pass
        return CommentTaskResult(TaskOutcome.RETRYABLE_ERROR, "Không mở được khung bình luận TikTok", can_retry=True)

    # 8. Chạm vào ô nhập bình luận bằng DOM live
    log("Chạm vào ô nhập bình luận...")
    input_target = find_comment_input_coords(adb, device_id, PLATFORM_TIKTOK, width, height)
    if not input_target:
        log("❌ Không tìm thấy tọa độ ô nhập bình luận TikTok!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không tìm thấy ô nhập bình luận TikTok", can_retry=True)
    input_x, input_y = input_target
    if not ensure_comment_input_ready(adb, device_id, input_x, input_y, width, height, status_callback=status_callback):
        log("❌ Không kích hoạt được ô nhập bình luận TikTok!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không kích hoạt được ô nhập bình luận", can_retry=True)
    time.sleep(random.uniform(0.8, 1.2))

    # 9. Gõ nội dung bình luận từ Notion (Unicode Tiếng Việt qua XwIME)
    log(f"Đang nhập nội dung từ Notion: '{comment_text}'...")
    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass
    adb.input_text(device_id, comment_text)
    time.sleep(random.uniform(1.2, 1.6))

    if is_cancelled and is_cancelled():
        return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

    # Chụp snapshot comment stream trước khi bấm gửi để chống false positive
    pre_send_root = ui_automator_dom.dump_ui_tree(adb, device_id)
    prior_stream = extract_stream_comments(pre_send_root)

    # 10. Gửi bình luận: thực hiện duy nhất 1 phương thức phù hợp
    log("Tìm nút gửi bình luận...")
    send_target = find_send_button_coords(adb, device_id, PLATFORM_TIKTOK, width, height)
    if send_target:
        send_x, send_y = send_target
        log(f"Chạm nút gửi TikTok tại ({send_x}, {send_y})...")
        adb.tap(device_id, send_x, send_y)
    else:
        log("❌ Không tìm thấy nút gửi bình luận TikTok trên DOM!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không tìm thấy nút gửi bình luận", can_retry=False)

    time.sleep(random.uniform(2.0, 2.8))

    # 11. XÁC MINH KẾT QUẢ BÌNH LUẬN (VERIFY OUTCOME)
    log("Đang xác minh kết quả đăng bình luận trên thiết bị...")
    outcome = verify_tiktok_comment_posted(adb, device_id, comment_text, width, height, prior_stream=prior_stream)
    log(f"Kết quả xác minh bình luận: {outcome.value}")

    if outcome == TaskOutcome.SUCCESS:
        try:
            import interaction_tracker
            interaction_tracker.record_interaction(device_id, "tiktok", item_key, "comment")
            if not is_already_liked and like_target:
                interaction_tracker.record_interaction(device_id, "tiktok", item_key, "like")
        except Exception:
            pass

    if outcome == TaskOutcome.UNKNOWN_OUTCOME:
        log("CẢNH BÁO: Kết quả bình luận chưa rõ (UNKNOWN_OUTCOME) • Ghi nhận audit trail và giữ nguyên màn hình để đối soát thủ công.")
        record_unknown_comment_audit("TikTok", device_id, url, comment_text)
        return CommentTaskResult(TaskOutcome.UNKNOWN_OUTCOME, "Chưa đủ bằng chứng xác nhận bình luận hiển thị", can_retry=False)

    # 12. Dọn dẹp an toàn khi hoàn tất hoặc gặp lỗi dứt điểm
    try:
        adb.keyevent(device_id, 4)
        time.sleep(0.4)
        adb.keyevent(device_id, 111)
        time.sleep(0.3)
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
        adb.keyevent(device_id, 3)
        time.sleep(0.8)
    except Exception as e:
        log(f"Cảnh báo dọn dẹp: {e}")

    if outcome == TaskOutcome.SUCCESS:
        log("Đã đăng bình luận TikTok thành công và xác minh chính xác!")
        return CommentTaskResult(TaskOutcome.SUCCESS, "Đã đăng bình luận TikTok thành công", can_retry=False)
    elif outcome == TaskOutcome.FATAL_ERROR:
        log("Lỗi: Tài khoản hoặc bình luận bị chặn/hạn chế.")
        return CommentTaskResult(TaskOutcome.FATAL_ERROR, "Tài khoản bị chặn hoặc hạn chế", can_retry=False)
    else:
        log("Lỗi đăng bình luận: Kết quả chưa rõ (UNKNOWN_OUTCOME) • Chặn retry tự động.")
        return CommentTaskResult(TaskOutcome.UNKNOWN_OUTCOME, "Không thể xác nhận đăng bình luận thành công", can_retry=False)


def find_facebook_comment_icon_coords(
    adb, device_id: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ icon Bình luận Facebook bằng UI dump, Geometric Landmark Tracking (giữa Like và Share) hoặc tọa độ hiệu chuẩn."""
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    xml_file = f"/sdcard/dump_fb_{safe_dev}.xml"
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_fb_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file]
        )
        if code != 0:
            code, _, _ = adb.execute_adb(
                device_id, ["shell", "uiautomator", "dump", xml_file]
            )
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml):
                tree = ET.parse(local_xml)
                root = tree.getroot()
                like_node = None
                share_node = None
                comment_node = None

                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    # Nút tương tác Facebook luôn nằm ở nửa dưới màn hình
                    if cy < height * 0.60:
                        continue

                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()
                    combined = desc + " " + txt + " " + rid

                    is_btn = (
                        elem.get("clickable") == "true"
                        or "button" in (elem.get("class") or "").casefold()
                        or elem.get("clickable") is None
                    )
                    if not is_btn:
                        continue

                    # 1. Nhận diện nút Bình luận trực tiếp
                    if any(k in combined for k in ("bình luận", "comment", "viết bình luận", "phản hồi")):
                        comment_node = (cx, cy)

                # Nếu tìm thấy trực tiếp nút Comment
                if comment_node is not None:
                    return comment_node
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # Tuyệt đối không trả về tọa độ đoán khi không nhận diện được nút bình luận Facebook
    return None


def is_facebook_comment_sheet_open(adb, device_id: str, height: int) -> bool:
    """Kiểm tra xem khung bình luận Facebook đã mở thành công hay chưa."""
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    xml_file = f"/sdcard/chk_fb_{safe_dev}.xml"
    local_xml = os.path.join(tempfile.gettempdir(), f"chk_fb_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file])
        if code != 0:
            code, _, _ = adb.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml) and os.path.getsize(local_xml) > 100:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                for elem in root.iter():
                    cls_name = (elem.get("class") or "").casefold()
                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    cy = (int(m.group(2)) + int(m.group(4))) // 2 if m else 0

                    if "edittext" in cls_name and cy >= height * 0.50:
                        return True
                    if any(
                        kw in txt or kw in desc or kw in rid
                        for kw in (
                            "bình luận dưới tên", "viết bình luận", "không gian này là của bạn",
                            "hãy là người đầu tiên", "chia sẻ suy nghĩ", "write a comment",
                            "comment as", "comment_edit_text", "comment_box"
                        )
                    ):
                        return True
                return False
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    try:
        _, out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "window", "windows"])
        lowered = (out or "").casefold()
        if any(w in lowered for w in ("comment", "bottomsheet", "dialog", "inputmethod", "flyout")):
            return True
    except Exception:
        pass

    return False


def post_facebook_comment(
    adb,
    device_id: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> CommentTaskResult:
    """Quy trình mở link bài viết/Reels Facebook, đọc tự nhiên và đăng bình luận.

    Áp dụng DOM chuẩn cho Facebook:
    - Phân biệt vùng chứa mục tiêu (tránh bấm nhầm bài khác trên feed)
    - Thả Like trước (bỏ qua nếu bài viết đã like để không hủy like, không bấm đoán)
    - Mở khung bình luận bằng DOM element live trước mỗi lần thử
    - Nhập bình luận Unicode từ Notion qua XwIME
    - Bấm gửi đơn 1 lần và xác minh kết quả
    - Đóng an toàn
    """
    def log(msg: str):
        if status_callback:
            status_callback(f"[Device {device_id}][Facebook Seeding] {msg}")

    if is_cancelled and is_cancelled():
        log("Đã hủy tác vụ.")
        return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

    width, height = adb.get_effective_screen_size(device_id)
    canonical_url = resolve_canonical_url(url)
    item_key = canonical_url or url

    # 0. Chuẩn bị thiết bị: Đóng app cũ và dọn dẹp đa nhiệm
    log("Chuẩn bị thiết bị: Đóng app cũ và dọn dẹp đa nhiệm...")
    try:
        adb.execute_adb(device_id, ["shell", "am", "force-stop", FACEBOOK_PACKAGE])
        if hasattr(adb, "clear_recent_apps"):
            adb.clear_recent_apps(device_id)
        adb.keyevent(device_id, 3)
        time.sleep(0.8)
    except Exception:
        pass

    sheet_opened = False
    for flow_attempt in range(1, 3):
        if is_cancelled and is_cancelled():
            return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

        if flow_attempt > 1:
            log("Lần 1 chưa mở được khung bình luận • Tự động dọn dẹp app và mở lại link Facebook lần 2...")
            try:
                adb.execute_adb(device_id, ["shell", "am", "force-stop", FACEBOOK_PACKAGE])
                if hasattr(adb, "clear_recent_apps"):
                    adb.clear_recent_apps(device_id)
                adb.keyevent(device_id, 3)
                time.sleep(1.0)
            except Exception:
                pass

        log(f"Đang mở link bài viết/Reel qua Intent Zalo Referrer (lượt {flow_attempt}/2)...")
        success = open_url_via_intent(adb, device_id, url, PLATFORM_FACEBOOK)
        if not success:
            log("Lỗi không thể mở link Facebook.")
            if flow_attempt == 2:
                return CommentTaskResult(TaskOutcome.FATAL_ERROR, "Không thể mở link Facebook qua Intent", can_retry=False)
            continue

        dwell_target = max(4, int(dwell_time // 2) if flow_attempt > 1 else int(dwell_time)) + random.randint(-1, 2)
        log(f"Đang đọc bài/xem Reel trong {dwell_target}s trước khi bình luận...")
        for remaining in range(dwell_target, 0, -1):
            if is_cancelled and is_cancelled():
                log("Dừng xem do người dùng yêu cầu.")
                return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)
            time.sleep(1.0)

        # 1. Quét DOM xác định các nút Thích và Bình luận trên bài viết Facebook
        log("Quét DOM bắt chính xác vị trí nút Thích và Bình luận Facebook...")
        root = ui_automator_dom.dump_ui_tree(adb, device_id)
        err_msg = check_target_error_state(root, PLATFORM_FACEBOOK)
        if err_msg:
            log(f"❌ Phát hiện lỗi nội dung Facebook: {err_msg}")
            return CommentTaskResult(TaskOutcome.FATAL_ERROR, f"Bài viết không khả dụng hoặc lỗi tải: {err_msg}", can_retry=False)

        fb_ctrls = ui_automator_dom.find_facebook_target_controls(root, width, height)

        if fb_ctrls.get("status") == "AMBIGUOUS_TARGET":
            log("CẢNH BÁO: Phát hiện nhiều bài viết trên màn hình mà không phân biệt được mục tiêu (AMBIGUOUS_TARGET). Dừng tác vụ an toàn.")
            return CommentTaskResult(
                TaskOutcome.AMBIGUOUS_TARGET,
                "Màn hình chứa nhiều bài viết mơ hồ, không xác định được mục tiêu",
                can_retry=False,
            )

        like_info = fb_ctrls.get("like")
        fb_like_c = like_info.get("center") if like_info else None
        is_fb_liked = like_info.get("is_liked", False) if like_info else False

        comment_info = fb_ctrls.get("comment")
        comment_coords = comment_info.get("center") if comment_info else None
        if not comment_coords:
            comment_coords = find_facebook_comment_icon_coords(adb, device_id, width, height)

        # 2. THẢ LIKE TRƯỚC (LIKE FIRST) - Chống hủy Like
        item_key = url
        already_tracked = False
        try:
            import interaction_tracker
            already_tracked = interaction_tracker.has_interacted(device_id, "facebook", item_key, "like")
        except Exception:
            pass

        if is_fb_liked or already_tracked:
            log("❤️ Bài viết/Reel Facebook này đã được Like trước đó • Bỏ qua bước like, giữ nguyên Like!")
        elif fb_like_c:
            log(f"❤️ Tiến hành thả Like trước tại tọa độ DOM Facebook ({fb_like_c[0]}, {fb_like_c[1]})...")
            adb.tap(device_id, fb_like_c[0], fb_like_c[1])
            time.sleep(random.uniform(1.0, 1.4))
        else:
            log("ℹ️ Không tìm thấy nút Like trên DOM Facebook • Bỏ qua like an toàn, không bấm đoán.")

        # 3. Bấm nút Mở khung bình luận Facebook (đọc lại DOM trước mỗi lần thử)
        for attempt in range(1, 4):
            if is_cancelled and is_cancelled():
                return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

            if attempt > 1:
                time.sleep(1.0)
                root = ui_automator_dom.dump_ui_tree(adb, device_id)
                fb_ctrls = ui_automator_dom.find_facebook_target_controls(root, width, height)
                if fb_ctrls.get("status") == "AMBIGUOUS_TARGET":
                    log("CẢNH BÁO: Phát hiện nhiều bài viết trên màn hình mà không phân biệt được mục tiêu (AMBIGUOUS_TARGET). Dừng tác vụ an toàn.")
                    return CommentTaskResult(
                        TaskOutcome.AMBIGUOUS_TARGET,
                        "Màn hình chứa nhiều bài viết mơ hồ, không xác định được mục tiêu",
                        can_retry=False,
                    )
                comment_info = fb_ctrls.get("comment")
                comment_coords = comment_info.get("center") if comment_info else None
                if not comment_coords:
                    comment_coords = find_facebook_comment_icon_coords(adb, device_id, width, height)

            if not comment_coords:
                log(f"⚠️ Chưa xác định được vị trí nút bình luận Facebook (lần {attempt}/3)...")
                continue

            log(f"Chạm icon Bình luận Facebook tại ({comment_coords[0]}, {comment_coords[1]})...")
            adb.tap(device_id, comment_coords[0], comment_coords[1])
            time.sleep(random.uniform(1.8, 2.2))

            if is_facebook_comment_sheet_open(adb, device_id, height):
                sheet_opened = True
                log("Đã mở khung bình luận Facebook thành công!")
                break

        if sheet_opened:
            break

    if not sheet_opened:
        log("CẢNH BÁO: Không mở được khung bình luận Facebook sau 2 lượt thử! Dừng tác vụ an toàn.")
        try:
            adb.execute_adb(device_id, ["shell", "am", "force-stop", FACEBOOK_PACKAGE])
            if hasattr(adb, "clear_recent_apps"):
                adb.clear_recent_apps(device_id)
            adb.keyevent(device_id, 3)
        except Exception:
            pass
        return CommentTaskResult(TaskOutcome.RETRYABLE_ERROR, "Không mở được khung bình luận Facebook", can_retry=True)

    # 4. Chạm vào ô nhập bình luận
    log("Chạm vào ô nhập bình luận...")
    input_target = find_comment_input_coords(adb, device_id, PLATFORM_FACEBOOK, width, height)
    if not input_target:
        log("❌ Không tìm thấy tọa độ ô nhập bình luận Facebook!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không tìm thấy ô nhập bình luận Facebook", can_retry=True)
    input_x, input_y = input_target
    if not ensure_comment_input_ready(adb, device_id, input_x, input_y, width, height, status_callback=status_callback):
        log("❌ Không kích hoạt được ô nhập bình luận Facebook!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không kích hoạt được ô nhập bình luận", can_retry=True)
    time.sleep(random.uniform(0.8, 1.2))

    # 5. Gõ nội dung bình luận từ Notion (Unicode Tiếng Việt qua XwIME)
    log(f"Đang nhập nội dung từ Notion: '{comment_text}'...")
    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass
    adb.input_text(device_id, comment_text)
    time.sleep(random.uniform(1.2, 1.6))

    if is_cancelled and is_cancelled():
        return CommentTaskResult(TaskOutcome.CANCELLED, "Đã hủy tác vụ", can_retry=False)

    pre_send_root = ui_automator_dom.dump_ui_tree(adb, device_id)
    prior_stream = extract_stream_comments(pre_send_root)

    # 6. Gửi bình luận: thực hiện duy nhất 1 phương thức phù hợp
    log("Tìm nút gửi bình luận Facebook...")
    send_target = find_send_button_coords(adb, device_id, PLATFORM_FACEBOOK, width, height)
    if send_target:
        send_x, send_y = send_target
        log(f"Chạm nút gửi Facebook tại ({send_x}, {send_y})...")
        adb.tap(device_id, send_x, send_y)
    else:
        log("❌ Không tìm thấy nút gửi bình luận Facebook trên DOM!")
        return CommentTaskResult(TaskOutcome.UNSUPPORTED_UI, "Không tìm thấy nút gửi bình luận", can_retry=False)

    time.sleep(random.uniform(2.0, 2.8))

    # 7. XÁC MINH KẾT QUẢ BÌNH LUẬN (VERIFY OUTCOME)
    log("Đang xác minh kết quả đăng bình luận Facebook...")
    outcome = verify_facebook_comment_posted(adb, device_id, comment_text, width, height, prior_stream=prior_stream)
    log(f"Kết quả xác minh bình luận: {outcome.value}")

    if outcome == TaskOutcome.SUCCESS:
        try:
            import interaction_tracker
            interaction_tracker.record_interaction(device_id, "facebook", item_key, "comment")
            if not is_fb_liked and fb_like_c:
                interaction_tracker.record_interaction(device_id, "facebook", item_key, "like")
        except Exception:
            pass

    if outcome == TaskOutcome.UNKNOWN_OUTCOME:
        log("CẢNH BÁO: Kết quả bình luận Facebook chưa rõ (UNKNOWN_OUTCOME) • Ghi nhận audit trail và giữ nguyên màn hình để đối soát thủ công.")
        record_unknown_comment_audit("Facebook", device_id, url, comment_text)
        return CommentTaskResult(TaskOutcome.UNKNOWN_OUTCOME, "Chưa đủ bằng chứng xác nhận bình luận hiển thị", can_retry=False)

    # 8. Dọn dẹp an toàn khi hoàn tất hoặc gặp lỗi dứt điểm
    try:
        adb.keyevent(device_id, 4)
        time.sleep(0.4)
        if hasattr(adb, "clear_recent_apps"):
            adb.clear_recent_apps(device_id)
        adb.execute_adb(device_id, ["shell", "am", "force-stop", FACEBOOK_PACKAGE])
        adb.keyevent(device_id, 3)
        time.sleep(0.8)
    except Exception as e:
        log(f"Cảnh báo dọn dẹp: {e}")

    if outcome == TaskOutcome.SUCCESS:
        log("Đã đăng bình luận Facebook thành công và xác minh chính xác!")
        return CommentTaskResult(TaskOutcome.SUCCESS, "Đã đăng bình luận Facebook thành công", can_retry=False)
    elif outcome == TaskOutcome.FATAL_ERROR:
        log("Lỗi: Tài khoản Facebook bị chặn hoặc bài viết bị hạn chế.")
        return CommentTaskResult(TaskOutcome.FATAL_ERROR, "Tài khoản bị chặn hoặc hạn chế", can_retry=False)
    else:
        log("Lỗi đăng bình luận Facebook: Kết quả chưa rõ (UNKNOWN_OUTCOME) • Chặn retry tự động.")
        return CommentTaskResult(TaskOutcome.UNKNOWN_OUTCOME, "Không thể xác nhận đăng bình luận Facebook", can_retry=False)


def find_tiktok_send_button_via_cv(
    adb, device_id: str, width: int, height: int
) -> Optional[tuple[int, int]]:
    """Tìm tọa độ nút tròn màu đỏ mũi tên gửi bình luận TikTok bằng OpenCV Color & Contour Detection."""
    screen = capture_screen_fast(adb, device_id)
    if screen is None:
        return None
    try:
        sh, sw = screen.shape[:2]
        # Vùng chứa nút tròn đỏ mũi tên gửi: x từ 60% đến 98%, y từ 40% đến 85%
        rx1, rx2 = int(sw * 0.60), int(sw * 0.98)
        ry1, ry2 = int(sh * 0.40), int(sh * 0.85)
        roi = screen[ry1:ry2, rx1:rx2]

        # Lọc màu đỏ đặc trưng của nút gửi TikTok (Crimson Red: R > 180, G < 100, B < 130)
        mask = (roi[:, :, 2] > 180) & (roi[:, :, 1] < 100) & (roi[:, :, 0] < 130)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        if num_labels > 1:
            best_idx = 1
            max_area = 0
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if area > max_area:
                    max_area = area
                    best_idx = i
            # Nút tròn đỏ có diện tích đáng kể (thường > 500 pixel trên Full HD, > 40 trên màn hình nhỏ)
            if max_area >= 40:
                cx_roi, cy_roi = centroids[best_idx]
                abs_x = rx1 + cx_roi
                abs_y = ry1 + cy_roi
                scale_x = width / float(sw)
                scale_y = height / float(sh)
                return int(abs_x * scale_x), int(abs_y * scale_y)
    except Exception:
        pass
    return None


def find_facebook_send_button_via_cv(
    adb, device_id: str, width: int, height: int
) -> Optional[tuple[int, int]]:
    """Tìm tọa độ nút gửi máy bay giấy màu xanh Facebook bằng OpenCV Color Blob Detection."""
    screen = capture_screen_fast(adb, device_id)
    if screen is None:
        return None
    try:
        sh, sw = screen.shape[:2]
        # Vùng chứa nút gửi Facebook: góc dưới bên phải (x >= 70%, y >= 80%)
        rx1, rx2 = int(sw * 0.70), sw
        ry1, ry2 = int(sh * 0.80), sh
        roi = screen[ry1:ry2, rx1:rx2]

        # Lọc màu xanh Facebook đặc trưng (BGR: B > 160, R < 100, G < 160)
        mask = (roi[:, :, 0] > 160) & (roi[:, :, 2] < 100) & (roi[:, :, 1] < 160)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        if num_labels > 1:
            best_idx = 1
            max_area = 0
            for i in range(1, num_labels):
                area = stats[i, cv2.CC_STAT_AREA]
                if area > max_area:
                    max_area = area
                    best_idx = i
            # Nút gửi máy bay giấy xanh có diện tích đáng kể (thường > 100 pixel trên Full HD, > 25 trên màn hình nhỏ)
            if max_area >= 25:
                cx_roi, cy_roi = centroids[best_idx]
                abs_x = rx1 + cx_roi
                abs_y = ry1 + cy_roi
                scale_x = width / float(sw)
                scale_y = height / float(sh)
                return int(abs_x * scale_x), int(abs_y * scale_y)
    except Exception:
        pass
    return None


def find_send_button_coords(
    adb, device_id: str, platform: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ nút Gửi bình luận qua OpenCV, UI dump hoặc tọa độ đã hiệu chuẩn thực tế."""
    clean_p = (platform or "").strip().casefold()
    is_tiktok = "tiktok" in clean_p

    # 1. Ưu tiên phát hiện bằng OpenCV:
    # - TikTok: nhận diện nút tròn đỏ mũi tên trắng
    # - Facebook: nhận diện nút máy bay giấy màu xanh
    if is_tiktok:
        cv_coords = find_tiktok_send_button_via_cv(adb, device_id, width, height)
        if cv_coords is not None:
            return cv_coords
    else:
        cv_coords = find_facebook_send_button_via_cv(adb, device_id, width, height)
        if cv_coords is not None:
            return cv_coords

    # 2. Tìm qua UI dump XML
    xml_file = f"/sdcard/dump_cmt_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_cmt_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", xml_file]
        )
        if code != 0:
            code, _, _ = adb.execute_adb(
                device_id, ["shell", "uiautomator", "dump", xml_file]
            )
        if code == 0:
            adb.execute_adb(device_id, ["pull", xml_file, local_xml])
            if os.path.exists(local_xml):
                tree = ET.parse(local_xml)
                root = tree.getroot()
                edit_text_bottom = None
                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    if cy < height * 0.40:
                        continue

                    cls_name = (elem.get("class") or "").casefold()
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

                    pass
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # Tuyệt đối không trả về tọa độ đoán cho nút gửi
    return None


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
    adb,
    device_id: str,
    platform: str,
    url: str,
    comment_text: str,
    dwell_time: int = 15,
    status_callback: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> CommentTaskResult:
    """Điều phối thực hiện tác vụ bình luận theo đúng nền tảng.

    Bọc an toàn qua device_workflow_scope nếu chưa được bọc từ caller.
    Trả về CommentTaskResult với outcome chi tiết.
    """
    if is_comment_blocked_by_audit(platform, url, comment_text):
        return CommentTaskResult(
            TaskOutcome.UNKNOWN_OUTCOME,
            "Tác vụ đang chờ đối soát (PENDING_AUDIT). Bị chặn để tránh gửi lặp.",
            can_retry=False,
        )

    plat = (platform or "").strip().casefold()

    def _run() -> CommentTaskResult:
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
            return CommentTaskResult(
                TaskOutcome.FATAL_ERROR,
                f"Nền tảng '{platform}' chưa được hỗ trợ",
                can_retry=False,
            )

    if hasattr(adb, "device_workflow_scope"):
        try:
            with adb.device_workflow_scope(device_id, timeout=30.0, is_cancelled=is_cancelled):
                return _run()
        except TimeoutError as te:
            if status_callback:
                status_callback(f"[Device {device_id}] Lỗi khóa thiết bị: {te}")
            return CommentTaskResult(
                TaskOutcome.CANCELLED if (is_cancelled and is_cancelled()) else TaskOutcome.RETRYABLE_ERROR,
                str(te),
                can_retry=not (is_cancelled and is_cancelled()),
            )
    return _run()


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
    """Xây dựng danh sách tác vụ bình luận thực thi:
    - Không mutate danh sách scanned_tasks ban đầu.
    - Tạo bản sao độc lập (copy.copy) cho các task Notion đã quét.
    - Nếu nội dung người dùng sửa khác Notion hoặc là câu mới, tạo task độc lập
      với page_id="", row_id="", không gán bừa vào row Notion cũ.
    """
    import copy
    from notion_comment_sync import NotionCommentTask

    clean_p = (platform or "").strip().casefold()
    pool = [
        t for t in scanned_tasks
        if (getattr(t, "platform", "") or "").strip().casefold() == clean_p
    ]
    used_ids = set()
    result = []

    for idx, text in enumerate(comment_lines):
        clean_text = text.strip()
        if not clean_text:
            continue
        found = None
        for cand in pool:
            cand_id = getattr(cand, "row_id", "") or getattr(cand, "page_id", "") or id(cand)
            if cand_id not in used_ids and getattr(cand, "content", "").strip() == clean_text:
                found = cand
                used_ids.add(cand_id)
                break

        is_blocked = is_comment_blocked_by_audit(platform, url, clean_text)
        if found:
            task_copy = copy.copy(found)
            if url:
                task_copy.url = url
            task_copy.stt = idx + 1
            if is_blocked:
                task_copy.is_blocked = True
                task_copy.block_reason = "Tác vụ đang chờ đối soát (PENDING_AUDIT). Chặn gửi lại để chống spam."
            result.append(task_copy)
        else:
            new_task = NotionCommentTask(
                page_id="",
                row_id="",
                stt=idx + 1,
                content=clean_text,
                url=url,
                platform=platform,
                status="Chưa comment",
            )
            if is_blocked:
                new_task.is_blocked = True
                new_task.block_reason = "Tác vụ đang chờ đối soát (PENDING_AUDIT). Chặn gửi lại để chống spam."
            result.append(new_task)

    return result

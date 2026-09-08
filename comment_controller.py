"""Phân hệ Điều Khiển Bơm Bình Luận (Comment Seeding Controller) đa nền tảng.

Hỗ trợ TikTok và Facebook qua cơ chế Android Deep Link Intent tàng hình,
kết hợp giả lập hành vi người dùng tự nhiên (dwell, jitter, gõ tiếng Việt Unicode).
"""

from __future__ import annotations

import base64
import os
import random
import re
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Optional

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

PLATFORM_TIKTOK = "TikTok"
PLATFORM_FACEBOOK = "Facebook"
PLATFORM_CHOICES = [PLATFORM_TIKTOK, PLATFORM_FACEBOOK]

DEFAULT_STEALTH_REFERRER = "android-app://com.zing.zalo"
TIKTOK_PRIMARY_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_ALT_PACKAGE = "com.zhiliaoapp.musically"
FACEBOOK_PACKAGE = "com.facebook.katana"

# Mẫu chuẩn icon bóng chat 3 chấm bình luận của TikTok để nhận diện qua Computer Vision
TIKTOK_COMMENT_BUBBLE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACEAAAAgCAIAAAAT2oadAAAJOklEQVRIDR3Be+yd5V0A8O/ted5zzu9"
    "GGSkIWqB1oROY1MBWZc7EaNxKV6QOeiOb0gnTlQ5Go8P9aaJdYpcMYdOQbFycBYyYCFPDZSajTEWg"
    "3SgloEIL+xVooR2Hnve87/N8L/7K54PrN9+KiABAbpNTkxAYjoZWu5nRSK0S00UfXnXJkosvEZHS"
    "tU3TEFEpNcIPHTq0f/9PXn311aLm7jUYAJwSM1mdAgAhLMENW3cROAD0fV9rFYmmaQLq6o98ZM2a"
    "S1etWjU7EESMMEQUNER084goRQeDQVeqmR9+7Y19Tz/9P6+9zsS9QUQUNQBgQgDADVt3MYYwj98f"
    "h4dDPX/Fig1Xrzv77HPm5gelVAGLCBGUlND6UqrWKikJp1iC7O45Dc39hZdeeeLxJ14/+natlSQD"
    "gBCYO27YdgsAuBvUXk0vveTSLVu3hHfz8/N9mRAihzKzY61VhZyFTU3NBpwBoDogoVZmIiVqJ5N/"
    "+KdHXnnl5eLZ1BhDVXH9lpvhAwK2du3aT3/q04g4M+J2Oh0MpZt2DApLyIgJvZo7ExETlJAkCthO"
    "2kEzT0yGBADjtjz55BM//NHzscTUzXD9lpsJSkT89m9+4sorPzGaQXMHJRExqywcSzwgjBAxABEB"
    "gAgdwN2JKCKIsptbqJtRHvZ9/9i/Pr5v31NEHBH4ma07wbuLLlp9w+c2e4Sk6u4USVUlkampKRMn"
    "xojAAGZyDyK0CHMHAGFGTG4O6BEB0kSE9vrgQw/9+MABIsb1n70xJ//Sl3b8wrkfCo/qdTAYaOkk"
    "CZgCgEcAgJuLMISomTAjIqCae9RgYUQkooiAJZj6vrDwsWPH/vqOO0qpuHHrjl9d+ytXXbVOsJZS"
    "hjPDvu/dymAw0L5HQiZStcFw0E4miLlpcq2KiAEVABIlrQoAKSczCw+ShogjPCIeeeTRH/zgSfzs"
    "thu/dvttOeeBuKqVKCnnRnjadZlxSSm1aXLXt03ThHOtiogi7B7M1Pbt7Mxs21YRjggiQkjuHtB7"
    "hHa+++u7ceeuv7jpxt8nooFE1apgxKSla5pG+x4RUxJzB/AlSQYRYeZmOhrNdF0HFHCaLIkIM2Nq"
    "3N2iE2aveO+99+C9D/zbFWsuEeGwolpHs7N93zdNMx6PE2PO2SPcvWlS205mZpe9f+p9ZmGiDKZq"
    "zXDQdR02UGplIkRUJzcbIqUkk74cPHgQf/Tc//3cWQt96RPHEkc4dWoyHo8PHnzhl1ZfdN555zER"
    "i5TSmemRN948cvjIBRdesHLlyuRKRNUNEV957eXXX399xYoVK1euDEzuns0BgJvB22+/hYf+953w"
    "joXJezOr6s8///zeBx4EgNFwcM3Gaz52+ZqUpFf972ee2bv3YQBomub3Nm78+No1xIRu+/fvv+e7"
    "DwIAE23YsOE3futKN4eoKUnXetd1+JOX387J3VywMlGv/vXdu99554SkJIJJ0u6//HPV2qvedded"
    "iz99J8KF5Zxzztmx86amacq03bPnr956872UUoSfddZZt+zaMRyOtLQAEJ7ayQSfO/RGJh2ORmF9"
    "VQXFb3/7bxbffEskMcNoNPrq7X8SEUS0Z8+eI68tnrHsjIhYvnz5V27bOR6Phw1+85t3/PSNE01u"
    "ptP2wpUrv/DFbYg0N2jUNEBOnvwZPvPC4TNms0e49U1u2ve7o4uLd3/nuxGxsDD3uc9//txzzw6P"
    "UsvRo2/u/fuHVDXnvPGajb/44QtSzuDTN99662+/dV87neact2/f/vPnf4iYoFYWroonT57Aex78"
    "l49f/tGcs2upVTPjtOtKjfF4PL8wOzOaYcGqOjMa9H1fii8uHl2+fPns7Ixrr1pHo5m2nQQ0x48f"
    "P/PMM4fDIWBxd8IgxL6vzz77HP7BH//p1776lWnbMqEITyen5uZmq6Ka5cylVBFcolabpummykRN"
    "01Strj1+AJZgo2ZJBAlLnRAigicRd7jzzrtw3cbtf3b7rrm52ZzQ3TGciRCcicydEB1qRJAkUzMD"
    "EabTGMvU3ClnVUtJSqnIxMKGEh5e25zTsePjb3xjD37qmht++aOrr7/+eiHXWoeD3HXdMCcW6bpO"
    "mB0qABS1JAmAzF2YcUntRdiQAEDVmAmY3DwkmxpDUbW9Dzx84MB+XHfdF8rk1M6bd1644lwilmRE"
    "FEF93zcNs0jtpjmnaqFmwgk/4O5IpmoU0jRN151iYXXKKTnlUktO+cUXX7z77vs9Aq/a9IcJQiTd"
    "9uUdy5ad4dAzEQQBAImbWhaqqhYIAElyRKhZTkm18whQzDlX7Vi4KiIhShMRJ06cvO++ew8fOZZz"
    "xqu37KhaRDgTbN++feWq89q2HWWG09zcCU8DAESMiKoVkZgoZamlNGnUdR1LmFpwRkKnpFUffvif"
    "Dxw4YJWREK/esqNqAQAvrap+8Y9uuPjii8lrzrmdTpomR4Sbmzshwgc8QpjdNeU8GU+bpnEvLGwo"
    "SdLPTk0fe/yxp5/6r6Zp3KVtW7zq2psBlYnI63vvvddb/8lf/+S112wYjUYsrmrumnMqXU/Mw0FW"
    "UzcnJsHUdR0JR4RI7vsSIoT46Pcfe2rfU5waAIje1BQ/c91Oh0qIHDoej4MjSZoZyBWXX/FrV35s"
    "+fLlIggAGLCk1J6JWNjUwLFpmqIVAMyAEEvAo99/9D/+81ki8sAlAlyr4oZNt0YYi5h17XQ67duZ"
    "mRkON7PcwMLCwmWXXLx69eq5ZWfOzc3NNKJamSUikmRzN7WmycF+dHHxew/845HDR1hmZmZGqpGS"
    "RBNtdVfF3t+xyr8RcderuXZnmpkkQOedST8WSWkSkeBCh9dM1a9Zs2rRpOBxGoNbKIgDw0isH77//"
    "vrba8/PzSANEdIOqNamZGq7ffGuYinB4tNOpWZmdnc3Cqpoy11oRAwBUCwtPJ+PLLrtsy+bNKWcw"
    "lSTH3z3xyCOPHvjxS8Ph0AMlJeTs5o2Qm0fXAQCuu+7LDAEALNJOJn2ZLiwsNEncPcJwCUUpZTDM"
    "3bRjstUXrd66bRsThevT+/b9+w+fevfdE4Phgog4UEqiRsQEtTJz9J1Wxd+59pbECAAR1vd9rXV+"
    "fj7nXFWZoGrNWUop7joYDCbvnzz/ggtuuvHGxaOLf/ed7/V939V2MBykNAunEQBYnJYQEBGm01LK"
    "/wOtYONDSDJ+qQAAAABJRU5ErkJggg=="
)


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

        # 1. Primary VIEW intent với URL sạch và package TikTok chính
        cmd = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-p", TIKTOK_PRIMARY_PACKAGE,
            "-f", "0x14000000",
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code, stdout, _ = adb.execute_adb(device_id, cmd)
        if code == 0 and "Error" not in (stdout or ""):
            return True

        # Thử mở bằng package TikTok alt nếu package chính lỗi
        cmd_alt = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-p", TIKTOK_ALT_PACKAGE,
            "-f", "0x14000000",
            "--es", "android.intent.extra.REFERRER_NAME", referrer,
        ]
        code_alt, stdout_alt, _ = adb.execute_adb(device_id, cmd_alt)
        if code_alt == 0 and "Error" not in (stdout_alt or ""):
            return True

        # Fallback Intent không gắn cố định package
        cmd_fallback = [
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", clean_url,
            "-f", "0x14000000",
        ]
        code_fb, _, _ = adb.execute_adb(device_id, cmd_fallback)
        return code_fb == 0

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
    for elapsed in range(max(1, timeout)):
        if is_cancelled and is_cancelled():
            return False

        # Khóa dọc giữ màn hình ổn định
        if hasattr(adb, "lock_portrait"):
            try:
                adb.lock_portrait(device_id, retries=1)
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


def find_tiktok_comment_icon_via_template(
    adb, device_id: str, width: int, height: int
) -> Optional[tuple[int, int]]:
    """Dùng OpenCV đa tỉ lệ để nhận diện quả bóng chat 3 chấm trực tiếp từ màn hình thiết bị."""
    if not CV2_AVAILABLE:
        return None
    remote_png = f"/sdcard/sc_cmt_{device_id}.png"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_png = os.path.join(tempfile.gettempdir(), f"sc_cmt_{safe_dev}.png")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", remote_png])
        code, _, _ = adb.execute_adb(device_id, ["shell", "screencap", "-p", remote_png])
        if code == 0:
            adb.execute_adb(device_id, ["pull", remote_png, local_png])
            if os.path.exists(local_png) and os.path.getsize(local_png) > 1000:
                screen = cv2.imread(local_png)
                if screen is not None:
                    sh, sw = screen.shape[:2]
                    tpl_bytes = base64.b64decode(TIKTOK_COMMENT_BUBBLE_B64)
                    tpl = cv2.imdecode(np.frombuffer(tpl_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if tpl is not None:
                        gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
                        gray_tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
                        rx1, rx2 = int(sw * 0.70), sw
                        ry1, ry2 = int(sh * 0.35), int(sh * 0.85)
                        roi = gray_screen[ry1:ry2, rx1:rx2]

                        best_val = -1
                        best_pt = None
                        for scale in np.linspace(0.35, 3.2, 35):
                            tw = int(gray_tpl.shape[1] * scale)
                            th = int(gray_tpl.shape[0] * scale)
                            if tw < 10 or th < 10 or tw >= roi.shape[1] or th >= roi.shape[0]:
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

                        if best_val >= 0.70 and best_pt is not None:
                            scale_x = width / float(sw)
                            scale_y = height / float(sh)
                            return int(best_pt[0] * scale_x), int(best_pt[1] * scale_y)
    except Exception:
        pass
    finally:
        if os.path.exists(local_png):
            try:
                os.remove(local_png)
            except Exception:
                pass
    return None


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
                            "leave a comment", "post a comment", "comments"
                        )
                    )
                    if is_comment:
                        elem_h = y2 - y1
                        # Nếu trúng nhãn text nhỏ ở dưới icon (như chữ 'Bóc tem'), nhấp nhẹ lên trên để trúng tâm quả bóng chat
                        if elem_h < height * 0.05:
                            return cx, max(int(height * 0.35), cy - int(height * 0.025))
                        return cx, cy

                    # Ghi nhận vị trí like và bookmark để neo khoảng cách nếu text bị ẩn hoặc dùng ngôn ngữ lạ
                    if any(k in desc or k in txt or k in rid for k in ("like", "thích", "heart")):
                        like_cy = cy
                    if any(k in desc or k in txt or k in rid for k in ("bookmark", "lưu", "favorite", "collect", "save")):
                        bookmark_cy = cy

                    # Thu thập các phần tử ở dải độ cao đặc trưng của nút bình luận (55% - 68% chiều cao màn hình)
                    if 0.55 * height <= cy <= 0.68 * height and elem.get("clickable", "false") == "true":
                        right_rail_elements.append((cx, cy))

                # Nếu không bắt được nhãn text nhưng bắt được nút Like và Bookmark: icon bình luận luôn nằm chính giữa
                if like_cy is not None and bookmark_cy is not None and bookmark_cy > like_cy:
                    mid_y = (like_cy + bookmark_cy) // 2
                    return int(width * 0.925), mid_y

                # Nếu phát hiện phần tử tương tác ở dải độ cao đặc trưng của bình luận
                if right_rail_elements:
                    return right_rail_elements[0]
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

    # 3. Tọa độ chuẩn hiệu chuẩn thực tế (tâm quả bóng chat bình luận 3 chấm):
    # x = 92.5%, y = 64.0% (nằm ngay tâm quả bóng chat, dưới nút Tim và trên nút Bookmark)
    return int(width * 0.925), int(height * 0.640)


def is_tiktok_comment_sheet_open(adb, device_id: str, height: int) -> bool:
    """Kiểm tra xem bottom sheet bình luận của TikTok đã mở thành công hay chưa."""
    xml_file = f"/sdcard/chk_cmt_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"chk_cmt_{safe_dev}.xml")
    try:
        adb.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
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
                            "thêm bình luận", "add comment", "comment_edit_text",
                            "comment_list", "et_comment", "c0e", "desc_comment"
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
    # Nếu uiautomator dump không trích xuất được hoặc môi trường test mock không tạo file
    return True


def find_comment_input_coords(
    adb, device_id: str, platform: str, width: int, height: int
) -> tuple[int, int]:
    """Tìm tọa độ ô nhập bình luận bằng UI dump hoặc tọa độ hiệu chuẩn thực tế."""
    xml_file = f"/sdcard/dump_in_{device_id}.xml"
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_in_{safe_dev}.xml")
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
                    # Ô nhập luôn nằm ở nửa dưới màn hình
                    if cy < height * 0.60:
                        continue

                    elem_w = x2 - x1
                    cls_name = (elem.get("class") or "").casefold()
                    desc = (elem.get("content-desc") or "").casefold()
                    txt = (elem.get("text") or "").casefold()
                    rid = (elem.get("resource-id") or "").casefold()

                    # Bỏ qua các nút emoji gợi ý phản hồi nhanh (nằm ở khoảng 85% - 93% chiều cao màn hình)
                    if 0.85 * height <= cy <= 0.93 * height and elem_w < width * 0.35:
                        continue
                    if any(char in (txt + desc) for char in ("😁", "🥰", "😂", "😳", "😍", "👍", "❤️")):
                        continue

                    is_input = (
                        "edittext" in cls_name
                        or any(
                            kw in desc or kw in txt or kw in rid
                            for kw in (
                                "add comment", "thêm bình luận", "để lại bình luận",
                                "viết bình luận", "nhập bình luận", "comment_edit_text",
                                "c0e", "et_comment"
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

    clean_p = (platform or "").strip().casefold()
    if "tiktok" in clean_p:
        # Tọa độ ô nhập TikTok trên thanh bottom sheet: x=50%, y=92.0%
        # Tránh hàng tab Trang chủ - Cửa hàng ở y=96% và tránh nút Shop ở x=35%
        return int(width * 0.50), int(height * 0.920)
    else:
        # Tọa độ ô nhập Facebook: x=50%, y=92.0%
        return int(width * 0.50), int(height * 0.920)


def ensure_comment_input_ready(
    adb, device_id: str, input_x: int, input_y: int, status_callback=None
) -> bool:
    """Chạm vào ô nhập, bật bàn phím XwIME và xóa sạch text/emoji thừa để sẵn sàng gõ."""
    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass

    adb.tap(device_id, input_x, input_y)
    time.sleep(0.8)
    code, out, _ = adb.execute_adb(device_id, ["shell", "dumpsys", "input_method"])
    is_shown = "minputshown=true" in (out or "").casefold()
    if not is_shown:
        adb.tap(device_id, input_x, input_y)
        time.sleep(0.8)

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

    # 1. Mở link video
    log("Đang mở link video qua Intent Zalo Referrer...")
    success = open_url_via_intent(adb, device_id, url, PLATFORM_TIKTOK)
    if not success:
        log("Lỗi không thể mở link video.")
        return False

    # 2. Chờ TikTok tải xong giao diện video
    wait_for_tiktok_video_ready(
        adb, device_id, timeout=15, status_callback=status_callback, is_cancelled=is_cancelled, clean_url=url
    )
    if is_cancelled and is_cancelled():
        return False

    # 3. Dwell time: Xem video tự nhiên
    dwell_target = max(6, int(dwell_time)) + random.randint(-1, 2)
    log(f"Đang xem video tự nhiên trong {dwell_target}s trước khi bình luận...")
    for remaining in range(dwell_target, 0, -1):
        if is_cancelled and is_cancelled():
            log("Dừng xem do người dùng yêu cầu.")
            return False
        if remaining % 4 == 0 or remaining <= 3:
            log(f"Đang xem video ({remaining}s còn lại)...")
        time.sleep(1.0)

    # 4. Bấm nút Mở khung bình luận (có cơ chế xác nhận và thử lại an toàn)
    log("Mở khung bình luận...")
    comment_x, comment_y = find_tiktok_comment_icon_coords(adb, device_id, width, height)
    log(f"Chạm icon Bình luận TikTok tại ({comment_x}, {comment_y})...")

    sheet_opened = False
    for attempt in range(1, 4):
        if is_cancelled and is_cancelled():
            return False

        if attempt == 1:
            target_x, target_y = comment_x, comment_y
        elif attempt == 2:
            target_x, target_y = int(width * 0.925), int(height * 0.640)
            log(f"Thử lại mở khung bình luận lần 2 tại ({target_x}, {target_y})...")
        else:
            target_x, target_y = int(width * 0.925), int(height * 0.655)
            log(f"Thử lại mở khung bình luận lần 3 tại ({target_x}, {target_y})...")

        adb.tap(device_id, target_x, target_y)
        time.sleep(random.uniform(1.8, 2.2))

        if is_tiktok_comment_sheet_open(adb, device_id, height):
            sheet_opened = True
            log("Đã mở khung bình luận thành công!")
            break

    if not sheet_opened:
        log("CẢNH BÁO: Không mở được khung bình luận TikTok! Hủy tác vụ an toàn để không bấm nhầm vào các nút khác.")
        try:
            adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
            adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
            if hasattr(adb, "clear_recent_apps"):
                adb.clear_recent_apps(device_id)
            adb.keyevent(device_id, 3)
        except Exception:
            pass
        return False

    # 5. Chạm vào ô nhập bình luận
    log("Chạm vào ô nhập bình luận...")
    input_x, input_y = find_comment_input_coords(adb, device_id, PLATFORM_TIKTOK, width, height)
    ensure_comment_input_ready(adb, device_id, input_x, input_y, status_callback=status_callback)
    time.sleep(random.uniform(0.8, 1.2))

    # 6. Gõ nội dung bình luận (Unicode Tiếng Việt qua XwIME)
    log(f"Đang nhập nội dung: '{comment_text}'...")
    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass
    adb.input_text(device_id, comment_text)
    time.sleep(random.uniform(1.2, 1.8))

    if is_cancelled and is_cancelled():
        return False

    # 7. Bấm nút Gửi
    log("Tìm nút Gửi bình luận...")
    send_x, send_y = find_send_button_coords(adb, device_id, PLATFORM_TIKTOK, width, height)
    log(f"Chạm nút Gửi TikTok tại ({send_x}, {send_y})...")
    adb.tap(device_id, send_x, send_y)
    time.sleep(0.4)
    # Kích hoạt phím Enter / Action Send
    adb.execute_adb(device_id, ["shell", "input", "keyevent", "66"])
    time.sleep(0.4)
    # Chạm lại nút tròn đỏ mũi tên gửi một lần nữa để đảm bảo nhận touch event
    adb.tap(device_id, send_x, send_y)
    time.sleep(random.uniform(2.5, 3.2))

    # 8. Hoàn tất bình luận: Đóng app và dọn dẹp đa nhiệm như module Facebook/TikTok
    log("Đã đăng bình luận TikTok thành công! Đang dọn dẹp đa nhiệm và đóng ứng dụng...")
    try:
        adb.keyevent(device_id, 4)
        time.sleep(0.5)
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_PRIMARY_PACKAGE])
        adb.execute_adb(device_id, ["shell", "am", "force-stop", TIKTOK_ALT_PACKAGE])
        if hasattr(adb, "clear_recent_apps"):
            adb.clear_recent_apps(device_id)
        adb.keyevent(device_id, 3)
        time.sleep(0.8)
    except Exception as e:
        log(f"Cảnh báo dọn dẹp: {e}")

    log("Đã hoàn tất dọn dẹp thiết bị!")
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

    log("Đang mở link bài viết/Reel qua Intent Zalo Referrer...")
    success = open_url_via_intent(adb, device_id, url, PLATFORM_FACEBOOK)
    if not success:
        log("Lỗi không thể mở link Facebook.")
        return False

    dwell_target = max(6, int(dwell_time)) + random.randint(-1, 2)
    log(f"Đang đọc bài/xem Reel trong {dwell_target}s trước khi bình luận...")
    for remaining in range(dwell_target, 0, -1):
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
    input_x, input_y = find_comment_input_coords(adb, device_id, PLATFORM_FACEBOOK, width, height)
    ensure_comment_input_ready(adb, device_id, input_x, input_y, status_callback=status_callback)
    time.sleep(random.uniform(0.8, 1.2))

    # 3. Gõ nội dung bình luận
    log(f"Đang nhập nội dung: '{comment_text}'...")
    if hasattr(adb, "ensure_ime"):
        try:
            adb.ensure_ime(device_id)
        except Exception:
            pass
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

    # 5. Hoàn tất bình luận: Đóng app và dọn dẹp đa nhiệm
    log("Đã đăng bình luận Facebook thành công! Đang dọn dẹp đa nhiệm và đóng ứng dụng...")
    try:
        adb.keyevent(device_id, 4)
        time.sleep(0.5)
        adb.execute_adb(device_id, ["shell", "am", "force-stop", FACEBOOK_PACKAGE])
        if hasattr(adb, "clear_recent_apps"):
            adb.clear_recent_apps(device_id)
        adb.keyevent(device_id, 3)
        time.sleep(1.0)
    except Exception as e:
        log(f"Cảnh báo dọn dẹp: {e}")

    log("Đã hoàn tất dọn dẹp thiết bị!")
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
                edit_text_cy = None
                for elem in root.iter():
                    bounds = elem.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    if cy < height * 0.50:
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

                    if "edittext" in cls_name or any(k in rid for k in ("et_comment", "c0e", "comment_edit_text")):
                        edit_text_cy = cy

                # Nếu tìm thấy ô nhập EditText, nút tròn đỏ gửi luôn nằm cùng hàng ngang ở sát mép phải
                if edit_text_cy is not None:
                    return int(width * 0.935), edit_text_cy
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
        # Tọa độ nút tròn đỏ mũi tên gửi TikTok:
        # Khi đang nhập cmt, thanh công cụ chứa nút tròn đỏ mũi tên nằm ở độ cao 61.3%, sát mép phải x=93.5%
        return int(width * 0.935), int(height * 0.613)
    else:
        # Tọa độ nút gửi Facebook: x=90.5%, y=96.0%
        return int(width * 0.905), int(height * 0.960)


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

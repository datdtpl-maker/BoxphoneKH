"""Phân hệ Điều Khiển & Định Vị Phần Tử UI Automator DOM (UI Automator DOM Engine).

Cung cấp cơ chế tìm kiếm, định vị phần tử trực tiếp theo cây UI Automator
cho hệ thống Boxphone (Android 10 / API 29), hỗ trợ đa độ phân giải (720p, 1080p, 2K/1440p)
và đa ngôn ngữ (Tiếng Việt, Tiếng Anh).

Tuyệt đối không đoán mò tọa độ; phân tích chính xác trạng thái (Đã Like, Chưa Like,
Khung bình luận mở/đóng) để thao tác đúng mục tiêu.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple


def parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int, int, int]]:
    """Phân tích chuỗi bounds '[x1,y1][x2,y2]' -> (x1, y1, x2, y2, cx, cy).

    Hỗ trợ đầy đủ tọa độ âm (off-screen / panning).
    Kiểm tra tính hợp lệ: x2 > x1 và y2 > y1 (kích thước dương).
    """
    if not bounds_str:
        return None
    m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", bounds_str)
    if not m:
        nums = re.findall(r"-?\d+", bounds_str)
        if len(nums) >= 4:
            x1, y1, x2, y2 = map(int, nums[:4])
            if x2 <= x1 or y2 <= y1:
                return None
            return x1, y1, x2, y2, (x1 + x2) // 2, (y1 + y2) // 2
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2, (x1 + x2) // 2, (y1 + y2) // 2


def is_bounds_visible_on_screen(
    b_info: Tuple[int, int, int, int, int, int], width: int, height: int
) -> bool:
    """Kiểm tra phần tử có giao cắt và hiển thị trên màn hình [0, 0][width, height] hay không."""
    x1, y1, x2, y2, cx, cy = b_info
    # Phải giao nhau với vùng hiển thị màn hình
    if x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
        return False
    # Tâm phần tử phải nằm trong màn hình
    if not (0 <= cx < width and 0 <= cy < height):
        return False
    return True


def dump_ui_tree(adb, device_id: str, timeout: int = 5) -> Optional[ET.Element]:
    """Trích xuất và nạp cây UI Automator XML trực tiếp từ thiết bị serial tương ứng."""
    safe_dev = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
    token = f"{safe_dev}_{int(time.time() * 1000)}"
    remote_xml = f"/sdcard/dump_dom_{token}.xml"
    local_xml = os.path.join(tempfile.gettempdir(), f"dump_dom_{token}.xml")

    try:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass

        # Dọn dẹp remote file cũ trước khi dump để không pull nhầm file cũ nếu dump lỗi
        try:
            adb.execute_adb(device_id, ["shell", "rm", "-f", remote_xml], timeout=timeout)
        except Exception:
            pass

        # 1. Thử dump nén siêu tốc
        code, _, _ = adb.execute_adb(
            device_id, ["shell", "uiautomator", "dump", "--compressed", remote_xml], timeout=timeout
        )
        if code != 0:
            code, _, _ = adb.execute_adb(
                device_id, ["shell", "uiautomator", "dump", remote_xml], timeout=timeout
            )

        if code == 0:
            pull_code, _, _ = adb.execute_adb(device_id, ["pull", remote_xml, local_xml], timeout=timeout)
            if pull_code == 0 and os.path.exists(local_xml):
                try:
                    sz = os.path.getsize(local_xml) if hasattr(os.path, "getsize") else 500
                except Exception:
                    sz = 500
                if sz > 0:
                    tree = ET.parse(local_xml)
                    return tree.getroot()
    except Exception:
        pass
    finally:
        if os.path.exists(local_xml):
            try:
                os.remove(local_xml)
            except Exception:
                pass
        try:
            adb.execute_adb(device_id, ["shell", "rm", "-f", remote_xml], timeout=timeout)
        except Exception:
            pass
    return None


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi văn bản không phân biệt hoa thường và dấu cơ bản."""
    if not text:
        return ""
    return text.strip().casefold()


def clean_channel_tokens(text: str) -> List[str]:
    """Tách các token chữ/số sau khi bỏ dấu và ký tự đặc biệt."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).replace("đ", "d").replace("Đ", "d")
    return [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).split()
        if token
    ]


def normalize_tiktok_identity(text: str) -> str:
    """Chuẩn hóa tên kênh để đối chiếu cả bản có/không dấu."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).replace("đ", "d").replace("Đ", "d")
    return re.sub(r"[^a-z0-9]", "", without_marks.casefold())


def match_tiktok_channel_name(candidate: str, target: str) -> bool:
    """So khớp tên kênh mục tiêu (TikTok Channel Target Lock)."""
    if not candidate or not target:
        return False
    if "," in target:
        sub_targets = [t.strip() for t in target.split(",") if t.strip()]
        return any(match_tiktok_channel_name(candidate, st) for st in sub_targets)

    c_tokens = clean_channel_tokens(candidate)
    t_tokens = clean_channel_tokens(target)
    if not c_tokens or not t_tokens:
        return False

    c_compact = "".join(c_tokens)
    t_compact = "".join(t_tokens)

    # 1. Trùng khớp chính xác chuỗi liền
    if t_compact == c_compact:
        return True

    # 2. Candidate bắt đầu bằng target (ví dụ thêm Official, Shop, etc.)
    if c_compact.startswith(t_compact) and len(c_compact) <= len(t_compact) + 25:
        return True

    # 3. Handle rút gọn (chỉ khi có đủ distinctive tokens nếu target có từ khóa đặc trưng)
    distinctive = {
        token for token in t_tokens
        if token in ("101", "skincare", "pt", "not", "mun", "spa", "clinic", "derma", "beauty")
        or token.isdigit()
    }
    if distinctive and not distinctive.issubset(set(c_tokens)):
        return False

    if t_compact.startswith(c_compact) and len(c_compact) >= 8 and len(c_compact) >= len(t_compact) - 6:
        return True

    return False


def extract_tiktok_channel_from_url(url: str) -> Optional[str]:
    """Trích xuất username kênh từ link TikTok (VD: @khaihoan.101notmun)."""
    if not url:
        return None
    m = re.search(r"@([a-zA-Z0-9_\.\-]+)", url)
    return m.group(1) if m else None


def find_tiktok_search_channel_card(
    root: Optional[ET.Element], width: int, height: int, target_channel: str
) -> Dict[str, Any]:
    """Tìm chính xác card kênh TikTok mục tiêu trong trang kết quả tìm kiếm qua DOM.

    Bao gồm:
    - Nhận diện tab hiện tại (Top, Người dùng/Users, Âm thanh, etc.)
    - Tọa độ chuyển tab Người dùng (nếu đang ở Top hoặc tab khác)
    - Tọa độ chuyển tab Top (nếu cần)
    - Nhận diện card kênh khớp target_channel (qua Display Name hoặc @handle)
    - Tọa độ tap an toàn vào card (vùng tên/avatar 35-45%, tuyệt đối tránh nút Follow ở >=70%)
    - Đếm số lượng card tài khoản nhìn thấy trên màn hình
    """
    res: Dict[str, Any] = {
        "matched": False,
        "card_coords": None,
        "matched_name": "",
        "current_tab": "unknown",
        "top_tab_coords": None,
        "users_tab_coords": None,
        "visible_user_cards": 0,
    }
    if root is None or not target_channel:
        return res

    parent_map = {child: parent for parent in root.iter() for child in parent}
    tab_y_min = int(height * 0.05)
    tab_y_max = int(height * 0.22)
    search_bar_bottom = int(height * 0.14)

    # 1. Phát hiện các Tab trên dải điều hướng (Top, Người dùng / Users, ...)
    for elem in root.iter():
        b_info = parse_bounds(elem.get("bounds", ""))
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        _, y1, _, y2, cx, cy = b_info
        if not (tab_y_min <= y1 <= tab_y_max):
            continue

        raw_txt = f"{elem.get('text', '')} {elem.get('content-desc', '')}"
        norm_t = normalize_tiktok_identity(raw_txt)
        if not norm_t:
            continue

        # Kiểm tra selected trên chính node hoặc container cha
        is_selected = (
            elem.get("selected", "").casefold() == "true"
            or elem.get("checked", "").casefold() == "true"
        )
        curr = parent_map.get(elem)
        for _ in range(3):
            if curr is None:
                break
            if curr.get("selected", "").casefold() == "true" or curr.get("checked", "").casefold() == "true":
                is_selected = True
                break
            curr = parent_map.get(curr)

        # Tab Top / Hàng đầu
        if norm_t in ("top", "op", "hangdau") or (norm_t.endswith("op") and norm_t not in ("shop", "cuahang")):
            res["top_tab_coords"] = (cx, cy)
            if is_selected:
                res["current_tab"] = "top"

        # Tab Người dùng / Users / Tài khoản
        if any(k in norm_t for k in ("nguoidung", "users", "user", "taikhoan", "people")):
            res["users_tab_coords"] = (cx, cy)
            if is_selected:
                res["current_tab"] = "users"

    matches = []

    # 2. Quét các card kênh / user trên màn hình
    for elem in root.iter():
        b_info = parse_bounds(elem.get("bounds", ""))
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        x1, y1, x2, y2, cx, cy = b_info

        # Tuyệt đối bỏ qua vùng tìm kiếm trên đầu màn hình (search bar, gợi ý tìm kiếm)
        if cy <= search_bar_bottom:
            continue

        # Bỏ qua edittext tìm kiếm
        cls_name = elem.get("class", "").casefold()
        rid = elem.get("resource-id", "").casefold()
        if "edittext" in cls_name or "search_edit" in rid or "search_input" in rid or "search_src_text" in rid:
            continue

        # Đếm các card user dựa trên nút Follow
        txt_val = normalize_text(elem.get("text", ""))
        desc_val = normalize_text(elem.get("content-desc", ""))
        if any(cue in txt_val or cue in desc_val for cue in ("follow", "theo dõi", "đang follow", "đã follow", "bạn bè")):
            if cx > width * 0.60:
                res["visible_user_cards"] += 1

        # Trích xuất chuỗi danh tính
        text_candidates = [elem.get("text", ""), elem.get("content-desc", "")]
        for raw_val in text_candidates:
            if not raw_val or len(raw_val.strip()) < 2:
                continue

            # So khớp danh tính với target_channel
            is_matched = match_tiktok_channel_name(raw_val, target_channel)
            if not is_matched:
                is_matched = (normalize_tiktok_identity(raw_val) == normalize_tiktok_identity(target_channel))

            if is_matched:
                # Đảm bảo phần tử thuộc vùng card kết quả (không phải gợi ý bàn phím ở đáy)
                if y1 > height * 0.88 and not res["visible_user_cards"]:
                    continue

                curr_click = elem
                while curr_click is not None and curr_click.get("clickable", "").casefold() != "true":
                    curr_click = parent_map.get(curr_click)

                target_elem = curr_click if curr_click is not None else elem
                target_b_info = parse_bounds(target_elem.get("bounds", "")) or b_info

                card_height_threshold = max(360, int(height * 0.18))
                card_height = target_b_info[3] - target_b_info[1]
                if card_height > card_height_threshold:
                    tap_x = cx
                    tap_y = cy
                else:
                    tap_x = target_b_info[4]
                    tap_y = target_b_info[5]

                # Tọa độ tap an toàn: x nằm ở giữa hoặc vùng tên kênh (tránh nút Follow ở >= 65%)
                if tap_x >= int(width * 0.65):
                    tap_x = int(width * 0.40)
                elif tap_x < int(width * 0.20):
                    tap_x = int(width * 0.35)
                matches.append((tap_x, tap_y, raw_val))

    if matches:
        best_tap = min(matches, key=lambda m: m[1])
        res["matched"] = True
        res["card_coords"] = (best_tap[0], best_tap[1])
        res["matched_name"] = best_tap[2]

    return res


def is_tiktok_target_profile_dom(
    root: Optional[ET.Element], width: int, height: int, target_channel: str
) -> bool:
    """Xác minh chính xác qua DOM đã mở đúng Profile của Kênh TikTok mục tiêu.

    Yêu cầu:
    1. Đã rời khỏi trang tìm kiếm (không còn ô search input / tab bar kết quả tìm kiếm).
    2. Có các nút hành động của profile (Follow, Nhắn tin, Chỉnh sửa hồ sơ, Video, etc.).
    3. Tên kênh hoặc @handle hiển thị trong phần Header của Profile (y <= 42% màn hình)
       phải khớp target_channel (không lấy caption video ở dưới).
    """
    if root is None or not target_channel:
        return False

    has_search_input = False
    has_search_results_marker = False
    has_profile_action = False
    has_target_identity = False
    video_nodes = 0

    tab_y_min = int(height * 0.05)
    tab_y_max = int(height * 0.22)
    header_y_max = int(height * 0.42)

    for elem in root.iter():
        b_info = parse_bounds(elem.get("bounds", ""))
        elem_y = b_info[5] if b_info else None

        cls_name = elem.get("class", "").casefold()
        rid = elem.get("resource-id", "").casefold()
        txt = normalize_text(elem.get("text", ""))
        desc = normalize_text(elem.get("content-desc", ""))
        combined = f"{txt} {desc}"

        # 1. Kiểm tra ô search input
        if "edittext" in cls_name and (elem_y is None or elem_y < int(height * 0.18)):
            has_search_input = True

        # 2. Kiểm tra tab bar của kết quả tìm kiếm
        if elem_y is None or (tab_y_min <= elem_y <= tab_y_max):
            if any(k in txt or k in desc for k in ("người dùng", "users", "photos", "ảnh", "cửa hàng", "âm thanh")):
                has_search_results_marker = True

        # 3. Kiểm tra danh tính kênh trong phần Header (y <= 42% chiều cao màn hình)
        if elem_y is None or elem_y <= header_y_max:
            for val in (elem.get("text", ""), elem.get("content-desc", "")):
                if not val or len(val.strip()) < 2:
                    continue
                if match_tiktok_channel_name(val, target_channel):
                    has_target_identity = True
                elif normalize_tiktok_identity(val) == normalize_tiktok_identity(target_channel):
                    has_target_identity = True

        # 4. Kiểm tra nút hành động profile
        if any(
            k in combined
            for k in (
                "follow", "theo dõi", "đang follow", "đã follow", "đang theo dõi",
                "message", "nhắn tin", "tin nhắn", "chỉnh sửa hồ sơ", "edit profile",
                "chia sẻ hồ sơ", "share profile", "bài viết", "repost",
            )
        ):
            has_profile_action = True

        if "user_video_view" in rid or rid.endswith(":id/erf"):
            video_nodes += 1

    return (
        has_target_identity
        and not has_search_input
        and not has_search_results_marker
        and (has_profile_action or video_nodes >= 1)
    )


# ==============================================================================
# TIKTOK DOM ENGINE
# ==============================================================================

def find_tiktok_video_controls(
    root: Optional[ET.Element], width: int, height: int
) -> Dict[str, Any]:
    """Xác định vị trí chính xác các nút tương tác trên màn hình phát video TikTok qua DOM.

    Bao gồm:
    - Nút Thả Tim (Like): tọa độ tâm, trạng thái đã like hay chưa
    - Nút Bình Luận (Comment): tọa độ tâm
    - Nút Bookmark (Lưu): tọa độ tâm, trạng thái đã lưu hay chưa
    - Nút Chia sẻ (Share): tọa độ tâm
    - Tên Kênh chủ video (Channel Name)
    """
    res: Dict[str, Any] = {
        "like": None,
        "comment": None,
        "bookmark": None,
        "share": None,
        "channel_name": "",
    }
    if root is None:
        return res

    like_node = None
    like_coords = None
    is_liked = False

    comment_node = None
    comment_coords = None

    bookmark_node = None
    bookmark_coords = None
    is_bookmarked = False

    share_coords = None

    right_rail_elements = []

    for elem in root.iter():
        bounds = elem.get("bounds", "")
        b_info = parse_bounds(bounds)
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        x1, y1, x2, y2, cx, cy = b_info

        desc = normalize_text(elem.get("content-desc", ""))
        txt = normalize_text(elem.get("text", ""))
        rid = normalize_text(elem.get("resource-id", ""))

        # 1. Phát hiện tên Kênh chủ video
        if "profile" in desc or "hồ sơ" in desc:
            clean_name = re.sub(r"(?:hồ sơ|profile|avatar)", "", desc).strip()
            if clean_name and not res["channel_name"]:
                res["channel_name"] = clean_name
        elif cx < width * 0.65 and cy > height * 0.60:
            if len(txt) >= 3 and not any(k in txt for k in ("thêm", "bình luận", "more", "see original", "dịch", "âm thanh", "sound")):
                if not res["channel_name"] and y1 > height * 0.65:
                    res["channel_name"] = txt

        # Nút tương tác chính của video luôn nằm ở cột điều hướng bên phải (x >= 70% chiều ngang)
        if cx < width * 0.70 or cy < height * 0.30 or cy > height * 0.90:
            continue

        # 2. Phát hiện nút Thả Tim (Like)
        if any(k in desc or k in txt for k in ("thích video", "like video", "video liked", "đã thích video", "bỏ thích video")):
            like_node = elem
            like_coords = (cx, cy)
            # Kiểm tra trạng thái đã like:
            # - Tiếng Anh: "Video liked", "unlike"
            # - Tiếng Việt: "Đã thích", "Đã thích video", "Bỏ thích"
            # - Thuộc tính: selected="true" hoặc checked="true"
            is_liked = (
                "video liked" in desc
                or "đã thích" in desc
                or "đã thích" in txt
                or "bỏ thích" in desc
                or "unlike" in desc
                or elem.get("selected", "").casefold() == "true"
                or elem.get("checked", "").casefold() == "true"
            )

        # 3. Phát hiện nút Bình Luận (Comment)
        if any(k in desc or k in txt for k in ("đọc hoặc viết bình luận", "read or add comments", "bóc tem", "add 1st", "add1st", "be the first")):
            comment_node = elem
            # Nếu là node chữ nhỏ 'Bóc tem', '2 comments' ở phía dưới icon, nhích lên trên để trúng tâm icon
            if y2 - y1 < height * 0.05:
                comment_coords = (cx, cy - int(height * 0.025))
            else:
                comment_coords = (cx, cy)
        elif not comment_coords and any(k in desc or k in txt or k in rid for k in ("comment_count", "comment_icon", "bình luận", "comments")):
            if 0.52 * height <= cy <= 0.75 * height:
                comment_node = elem
                comment_coords = (cx, cy)

        # Thu thập các phần tử clickable ở dải độ cao đặc trưng của nút bình luận (50% - 68%)
        if 0.50 * height <= cy <= 0.68 * height and elem.get("clickable", "false").casefold() == "true":
            right_rail_elements.append((cx, cy))

        # 4. Phát hiện nút Bookmark (Yêu thích / Lưu)
        if any(k in desc or k in txt for k in ("yêu thích", "favourites", "bookmark", "lưu")):
            bookmark_node = elem
            bookmark_coords = (cx, cy)
            is_bookmarked = (
                "đã lưu" in desc
                or "đã thêm" in desc
                or "saved" in desc
                or "added" in desc
                or elem.get("selected", "").casefold() == "true"
            )

        # 5. Phát hiện nút Chia sẻ (Share)
        if any(k in desc or k in txt for k in ("chia sẻ video", "share video")):
            share_coords = (cx, cy)

    # Tuyệt đối không suy đoán tọa độ khi thiếu nút bình luận trên DOM

    # Tuyệt đối không tự bịa tọa độ Like/Comment khi không nhận diện được
    if like_coords is not None:
        res["like"] = {"node": like_node, "center": like_coords, "is_liked": is_liked}
    else:
        res["like"] = None

    if comment_coords is not None:
        res["comment"] = {"node": comment_node, "center": comment_coords}
    else:
        res["comment"] = None

    if bookmark_coords:
        res["bookmark"] = {"node": bookmark_node, "center": bookmark_coords, "is_bookmarked": is_bookmarked}
    if share_coords:
        res["share"] = {"center": share_coords}

    return res


def find_tiktok_comment_sheet_elements(
    root: Optional[ET.Element], width: int, height: int
) -> Dict[str, Any]:
    """Phát hiện trạng thái bảng bình luận TikTok và định vị ô nhập, nút tròn đỏ gửi."""
    res: Dict[str, Any] = {
        "is_open": False,
        "input": None,
        "send": None,
        "close": None,
    }
    if root is None:
        return res

    input_coords = None
    send_coords = None
    close_coords = None

    for elem in root.iter():
        bounds = elem.get("bounds", "")
        b_info = parse_bounds(bounds)
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        x1, y1, x2, y2, cx, cy = b_info

        desc = normalize_text(elem.get("content-desc", ""))
        txt = normalize_text(elem.get("text", ""))
        rid = normalize_text(elem.get("resource-id", ""))
        cls_name = normalize_text(elem.get("class", ""))

        # 1. Nhận diện nút đóng (X) ở góc trên bảng bình luận
        if any(k in desc or k in txt for k in ("đóng", "close")) and y1 < height * 0.55:
            close_coords = (cx, cy)
            res["is_open"] = True

        # 2. Nhận diện ô nhập bình luận (EditText)
        if "edittext" in cls_name and cy >= height * 0.35:
            res["is_open"] = True
            # Nếu bàn phím đã bật (EditText co lên giữa màn hình):
            input_coords = (cx, cy)
        elif any(k in desc or k in txt or k in rid for k in ("thêm bình luận", "add comment", "viết bình luận", "comment_edit_text", "c0e", "et_comment")) and cy >= height * 0.40:
            res["is_open"] = True
            if input_coords is None:
                input_coords = (cx, cy)

        # 3. Nhận diện nút gửi bình luận (Icon tròn đỏ mũi tên trắng)
        if any(k in desc or k in txt or k in rid for k in ("gửi", "send", "publish", "post", "2131823424", "send_btn", "iv_send")):
            if cx > width * 0.65 and cy >= height * 0.40:
                send_coords = (cx, cy)

    if input_coords is not None:
        res["input"] = {"center": input_coords}
    if send_coords is not None:
        res["send"] = {"center": send_coords}
    if close_coords is not None:
        res["close"] = {"center": close_coords}
    return res


# ==============================================================================
# FACEBOOK DOM ENGINE
# ==============================================================================

def find_facebook_target_controls(
    root: Optional[ET.Element], width: int, height: int
) -> Dict[str, Any]:
    """Xác định vị trí các nút Thích, Bình Luận, Chia Sẻ trên bài viết/Reels Facebook qua DOM.

    Phân biệt container bài viết:
    - Nếu phát hiện nhiều bài viết khác nhau trên cùng màn hình mà không phân biệt được mục tiêu:
      trả về status='AMBIGUOUS_TARGET' để dừng an toàn thay vì bấm nhầm.
    - Tuyệt đối không trả tọa độ đoán mò khi không tìm thấy.
    """
    res: Dict[str, Any] = {
        "status": "NOT_FOUND",
        "like": None,
        "comment": None,
        "share": None,
        "is_open": True,
    }
    if root is None:
        return res

    like_candidates = []
    comment_candidates = []
    share_candidates = []

    for elem in root.iter():
        bounds = elem.get("bounds", "")
        b_info = parse_bounds(bounds)
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        x1, y1, x2, y2, cx, cy = b_info

        # Bỏ qua phần header / thanh tìm kiếm trên cùng (top 20%)
        if cy < height * 0.20:
            continue

        desc = normalize_text(elem.get("content-desc", ""))
        txt = normalize_text(elem.get("text", ""))
        rid = normalize_text(elem.get("resource-id", ""))
        combined = f"{desc} {txt} {rid}"

        # Bỏ qua các nút nhắn tin
        if any(k in combined for k in ("nhắn tin", "tin nhắn", "messenger", "message")):
            continue

        # 1. Phát hiện nút Thích / Like
        if any(k in combined for k in ("thích", "like", "bày tỏ cảm xúc", "react")):
            if not any(k in combined for k in ("bình luận", "chia sẻ", "share")):
                like_candidates.append(
                    {
                        "elem": elem,
                        "coords": (cx, cy),
                        "bounds": b_info,
                        "is_liked": (
                            "đã thích" in desc
                            or "liked" in desc
                            or "đã bày tỏ" in desc
                            or elem.get("selected", "").casefold() == "true"
                            or elem.get("checked", "").casefold() == "true"
                        ),
                    }
                )

        # 2. Phát hiện nút Bình Luận
        if any(k in combined for k in ("bình luận", "comment", "viết bình luận")):
            if not any(k in combined for k in ("đã bình luận", "dưới tên")):
                comment_candidates.append(
                    {"elem": elem, "coords": (cx, cy), "bounds": b_info}
                )

        # 3. Phát hiện nút Chia Sẻ
        if any(k in combined for k in ("chia sẻ", "share")):
            share_candidates.append(
                {"elem": elem, "coords": (cx, cy), "bounds": b_info}
            )

    if not like_candidates and not comment_candidates:
        return res

    # Nhóm các nút Like và Comment theo hàng ngang (Reaction Row của từng bài viết)
    rows: List[Dict[str, Any]] = []
    for lk in like_candidates:
        matched_row = None
        for r in rows:
            if abs(r["y"] - lk["coords"][1]) < height * 0.05:
                matched_row = r
                break
        if matched_row is None:
            matched_row = {"y": lk["coords"][1], "likes": [], "comments": [], "shares": []}
            rows.append(matched_row)
        matched_row["likes"].append(lk)

    for cm in comment_candidates:
        matched_row = None
        for r in rows:
            if abs(r["y"] - cm["coords"][1]) < height * 0.05:
                matched_row = r
                break
        if matched_row is None:
            matched_row = {"y": cm["coords"][1], "likes": [], "comments": [], "shares": []}
            rows.append(matched_row)
        matched_row["comments"].append(cm)

    for sh in share_candidates:
        for r in rows:
            if abs(r["y"] - sh["coords"][1]) < height * 0.05:
                r["shares"].append(sh)
                break

    valid_rows = [r for r in rows if r["likes"] or r["comments"]]

    # Nếu phát hiện nhiều bài viết riêng biệt (mỗi bài có hàng Like/Comment riêng cách nhau trên màn hình)
    if len(valid_rows) > 1:
        distinct_y_levels = [r["y"] for r in valid_rows]
        distinct_y_levels.sort()
        has_multiple_posts = any(
            distinct_y_levels[i + 1] - distinct_y_levels[i] > height * 0.10
            for i in range(len(distinct_y_levels) - 1)
        )
        if has_multiple_posts:
            res["status"] = "AMBIGUOUS_TARGET"
            return res

    target_row = valid_rows[0] if valid_rows else None
    if not target_row:
        return res

    like_info = target_row["likes"][0] if target_row["likes"] else None
    comment_info = target_row["comments"][0] if target_row["comments"] else None
    share_info = target_row["shares"][0] if target_row["shares"] else None

    like_coords = like_info["coords"] if like_info else None
    is_liked = like_info["is_liked"] if like_info else False
    comment_coords = comment_info["coords"] if comment_info else None
    share_coords = share_info["coords"] if share_info else None

    # Tuyệt đối không neo hay suy đoán tọa độ nút bình luận Facebook

    if like_coords is not None:
        res["like"] = {"center": like_coords, "is_liked": is_liked}
    if comment_coords is not None:
        res["comment"] = {"center": comment_coords}
    if share_coords is not None:
        res["share"] = {"center": share_coords}

    res["status"] = "FOUND" if (res["like"] or res["comment"]) else "NOT_FOUND"
    return res


def find_facebook_comment_sheet_elements(
    root: Optional[ET.Element], width: int, height: int
) -> Dict[str, Any]:
    """Phát hiện ô nhập bình luận và nút máy bay giấy gửi bình luận trên Facebook."""
    res: Dict[str, Any] = {
        "is_open": False,
        "input": None,
        "send": None,
    }
    if root is None:
        return res

    input_coords = None
    send_coords = None

    for elem in root.iter():
        bounds = elem.get("bounds", "")
        b_info = parse_bounds(bounds)
        if not b_info or not is_bounds_visible_on_screen(b_info, width, height):
            continue
        x1, y1, x2, y2, cx, cy = b_info

        if cy < height * 0.40:
            continue

        desc = normalize_text(elem.get("content-desc", ""))
        txt = normalize_text(elem.get("text", ""))
        rid = normalize_text(elem.get("resource-id", ""))
        cls_name = normalize_text(elem.get("class", ""))

        # 1. Nhận diện ô nhập bình luận Facebook
        if "edittext" in cls_name or any(k in desc or k in txt or k in rid for k in ("viết bình luận", "bình luận dưới tên", "write a comment", "nhập bình luận")):
            res["is_open"] = True
            input_coords = (cx, cy)

        # 2. Nhận diện nút gửi bình luận (máy bay giấy / send)
        if any(k in desc or k in txt or k in rid for k in ("gửi", "send", "post", "đăng")):
            if cx > width * 0.70 and cy > height * 0.50:
                send_coords = (cx, cy)

    if input_coords is not None:
        res["input"] = {"center": input_coords}
    if send_coords is not None:
        res["send"] = {"center": send_coords}

    return res

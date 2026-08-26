import subprocess
import base64
import time
import os
import xml.etree.ElementTree as ET
import re
import random
import unicodedata
import threading
from contextlib import contextmanager
from functools import wraps
import config
from concurrent.futures import ThreadPoolExecutor
from config import ADB_PATH


def serialized_device_workflow(method):
    """Prevent two platform workflows from controlling one phone concurrently."""
    @wraps(method)
    def wrapper(self, device_id, *args, **kwargs):
        with self.device_workflow_scope(device_id):
            return method(self, device_id, *args, **kwargs)

    wrapper._serialized_device_workflow = True
    return wrapper

class ADBController:
    def __init__(
        self,
        adb_path=ADB_PATH,
        max_parallel_commands=8,
        portrait_cache_seconds=5.0,
    ):
        self.adb_path = adb_path
        self.max_parallel_commands = max(
            1, min(16, int(max_parallel_commands))
        )
        self._adb_command_slots = threading.BoundedSemaphore(
            self.max_parallel_commands
        )
        self._device_workflow_locks = {}
        self._active_device_workflows = {}
        self._device_workflow_locks_guard = threading.Lock()
        self._portrait_cache_seconds = max(
            0.5, float(portrait_cache_seconds)
        )
        self._portrait_confirmed_at = {}
        self._portrait_device_locks = {}
        self._portrait_state_guard = threading.Lock()
        self._screen_size_cache = {}
        self._screen_size_cache_seconds = 300.0
        self._screen_size_cache_guard = threading.Lock()

    @contextmanager
    def device_workflow_scope(self, device_id):
        """Grant exclusive in-process control of a device to one workflow."""
        with self._device_workflow_locks_guard:
            lock = self._device_workflow_locks.setdefault(
                device_id, threading.RLock()
            )
        with lock:
            with self._device_workflow_locks_guard:
                self._active_device_workflows[device_id] = (
                    self._active_device_workflows.get(device_id, 0) + 1
                )
            try:
                yield
            finally:
                with self._device_workflow_locks_guard:
                    remaining = (
                        self._active_device_workflows.get(device_id, 1) - 1
                    )
                    if remaining > 0:
                        self._active_device_workflows[device_id] = remaining
                    else:
                        self._active_device_workflows.pop(device_id, None)

    def is_device_workflow_active(self, device_id):
        """Cho tác vụ nền biết thiết bị đang được một workflow điều khiển."""
        with self._device_workflow_locks_guard:
            return self._active_device_workflows.get(device_id, 0) > 0

    def _run_cmd(self, cmd_args, timeout=15):
        """Chạy lệnh hệ thống với ADB"""
        full_cmd = [self.adb_path] + cmd_args
        
        # Thiết lập ẩn cửa sổ CMD đen của tiến trình con trên Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # 0 tương ứng với SW_HIDE
            
        try:
            # ADB dùng chung một server. Phát hàng chục subprocess đồng thời
            # làm server nghẽn và tăng độ trễ cho toàn bộ 40 thiết bị.
            with self._adb_command_slots:
                result = subprocess.run(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=timeout,
                    startupinfo=startupinfo
                )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)

    def execute_adb(self, device_id, cmd_args, timeout=15):
        """Thực thi lệnh ADB trên một thiết bị cụ thể"""
        # Nếu có device_id thì thêm cờ -s
        if device_id:
            device_args = ["-s", device_id] + cmd_args
        else:
            device_args = cmd_args
        return self._run_cmd(device_args, timeout)

    def _get_portrait_device_lock(self, device_id):
        with self._portrait_state_guard:
            return self._portrait_device_locks.setdefault(
                device_id, threading.RLock()
            )

    def _read_portrait_lock_state(self, device_id):
        state_script = (
            "printf 'ACCELEROMETER_ROTATION='; "
            "settings get system accelerometer_rotation; "
            "printf 'USER_ROTATION='; "
            "settings get system user_rotation; "
            "dumpsys input | grep SurfaceOrientation || true"
        )
        code, output, _ = self.execute_adb(
            device_id, ["shell", "sh", "-c", state_script]
        )
        if code != 0:
            return None
        accelerometer = re.search(
            r"ACCELEROMETER_ROTATION=\s*([01])", output
        )
        user_rotation = re.search(r"USER_ROTATION=\s*([0-3])", output)
        orientation = re.search(r"SurfaceOrientation:\s*([0-3])", output)
        if not accelerometer or not user_rotation:
            return None
        return (
            accelerometer.group(1) == "0"
            and user_rotation.group(1) == "0"
            and (orientation is None or orientation.group(1) == "0")
        )

    def lock_portrait(self, device_id, retries=2, force=False):
        """Khóa dọc với tối đa hai lệnh ADB và gom các lần gọi sát nhau."""
        device_lock = self._get_portrait_device_lock(device_id)
        with device_lock:
            now = time.monotonic()
            with self._portrait_state_guard:
                confirmed_at = self._portrait_confirmed_at.get(device_id)
            if (
                not force
                and confirmed_at is not None
                and now - confirmed_at < self._portrait_cache_seconds
            ):
                return True

            if not force and confirmed_at is not None:
                state = self._read_portrait_lock_state(device_id)
                if state is True:
                    with self._portrait_state_guard:
                        self._portrait_confirmed_at[device_id] = now
                    return True

            apply_script = (
                "settings put system accelerometer_rotation 0; "
                "settings put system user_rotation 0; "
                "settings put secure show_rotation_suggestions 0; "
                "content insert --uri content://settings/system "
                "--bind name:s:accelerometer_rotation --bind value:i:0; "
                "content insert --uri content://settings/system "
                "--bind name:s:user_rotation --bind value:i:0; "
                "wm set-user-rotation lock 0 >/dev/null 2>&1 || true"
            )
            attempts = max(1, int(retries))
            applied = False
            for attempt in range(attempts):
                code, _, _ = self.execute_adb(
                    device_id, ["shell", "sh", "-c", apply_script]
                )
                applied = code == 0
                state = self._read_portrait_lock_state(device_id)
                if state is True or (state is None and applied):
                    with self._portrait_state_guard:
                        self._portrait_confirmed_at[device_id] = (
                            time.monotonic()
                        )
                    return True
                if attempt < attempts - 1:
                    time.sleep(0.1)
            return applied

    def get_devices(self):
        """Lấy danh sách các thiết bị đang kết nối dạng list các serial ID"""
        code, stdout, stderr = self._run_cmd(["devices"])
        if code != 0:
            print(f"Loi khi lay danh sach thiet bi: {stderr}")
            return []
        
        devices = []
        lines = stdout.splitlines()
        for line in lines[1:]: # Bỏ qua dòng đầu "List of devices attached"
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def ensure_ime(self, device_id):
        """Đảm bảo bàn phím XwIME đã được bật và chọn làm mặc định để gõ được Tiếng Việt"""
        ime_name = "com.android.xwkeyboard/.XwIME"
        self.execute_adb(device_id, ["shell", "ime", "enable", ime_name])
        self.execute_adb(device_id, ["shell", "ime", "set", ime_name])

    def tap(self, device_id, x, y):
        """Click vào tọa độ (x, y) trên màn hình"""
        return self.execute_adb(device_id, ["shell", "input", "tap", str(x), str(y)])

    def swipe(self, device_id, x1, y1, x2, y2, duration=300):
        """Vuốt từ (x1, y1) tới (x2, y2) trong khoảng thời gian duration (ms)"""
        return self.execute_adb(device_id, ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)])

    def mute_media_volume(self, device_id):
        """Đưa âm lượng media về 0 và xác minh lại trên thiết bị."""
        set_code, _, _ = self.execute_adb(
            device_id,
            ["shell", "media", "volume", "--stream", "3", "--set", "0"],
        )
        if set_code != 0:
            return False

        get_code, stdout, _ = self.execute_adb(
            device_id,
            ["shell", "media", "volume", "--stream", "3", "--get"],
        )
        return get_code == 0 and re.search(
            r"volume\s+is\s+0(?:\D|$)", stdout, re.IGNORECASE
        ) is not None

    def swipe_curved(self, device_id, x1, y1, x2, y2, duration=800):
        """Giả lập vuốt cong nhẹ bằng cách chia làm 2 đoạn vuốt liên tục nhanh với tọa độ trung gian lệch nhẹ"""
        x_mid = (x1 + x2) // 2 + random.randint(-40, 40)
        y_mid = (y1 + y2) // 2 + random.randint(-30, 30)
        dur1 = int(duration * 0.4)
        dur2 = duration - dur1
        # Thực hiện vuốt đoạn 1 và đoạn 2 liên tiếp trong cùng một phiên shell để giảm độ trễ
        shell_cmd = f"input swipe {x1} {y1} {x_mid} {y_mid} {dur1} && input swipe {x_mid} {y_mid} {x2} {y2} {dur2}"
        return self.execute_adb(device_id, ["shell", shell_cmd])

    def keyevent(self, device_id, keycode):
        """Gửi mã phím hệ thống (ví dụ: 3=Home, 4=Back, 66=Enter)"""
        return self.execute_adb(device_id, ["shell", "input", "keyevent", str(keycode)])

    def clear_recent_apps(self, device_id, max_scrolls=6):
        """Mở màn hình đa nhiệm và bấm Xóa tất cả trên nhiều launcher."""
        self.lock_portrait(device_id, retries=3)
        self.keyevent(device_id, 187)  # KEYCODE_APP_SWITCH
        time.sleep(0.8)
        width, height = self.get_effective_screen_size(device_id)
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_recents_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_recents_{safe_device_id}.xml",
        )
        clear_markers = (
            "clear all",
            "close all",
            "remove all",
            "clear all apps",
            "xoa tat ca",
            "dong tat ca",
            "don dep",
            "don sach",
        )
        empty_markers = (
            "no recent items",
            "no recent apps",
            "khong co ung dung gan day",
            "khong co muc gan day",
        )
        chinese_clear_markers = (
            "全部清除",
            "清除全部",
            "一键清理",
            "清理全部",
            "全部关闭",
        )

        for attempt in range(max(0, max_scrolls) + 1):
            root = None
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
            dump_code, _, _ = self.execute_adb(
                device_id, ["shell", "uiautomator", "dump", remote_xml]
            )
            if dump_code == 0:
                pull_code, _, _ = self.execute_adb(
                    device_id, ["pull", remote_xml, local_xml]
                )
                if pull_code == 0 and os.path.exists(local_xml):
                    try:
                        root = ET.parse(local_xml).getroot()
                    except Exception:
                        root = None

            try:
                if root is not None:
                    parent_map = {
                        child: parent
                        for parent in root.iter()
                        for child in parent
                    }
                    screen_text = []
                    clear_candidates = []
                    for node in root.iter():
                        raw_label = " ".join(
                            part
                            for part in (
                                node.get("text", ""),
                                node.get("content-desc", ""),
                            )
                            if part
                        ).strip()
                        normalized = self._normalize_facebook_text(raw_label)
                        if normalized:
                            screen_text.append(normalized)
                        is_clear = any(
                            marker in normalized for marker in clear_markers
                        ) or any(
                            marker in raw_label for marker in chinese_clear_markers
                        )
                        if not is_clear:
                            continue
                        clickable = node
                        while (
                            clickable is not None
                            and clickable.get("clickable", "false") != "true"
                        ):
                            clickable = parent_map.get(clickable)
                        click_node = clickable if clickable is not None else node
                        coords = self._element_center(click_node)
                        if coords:
                            clear_candidates.append(coords)

                    if clear_candidates:
                        x, y = clear_candidates[0]
                        self.tap(device_id, x, y)
                        time.sleep(0.8)
                        self.keyevent(device_id, 3)
                        self.lock_portrait(device_id, retries=2)
                        return True

                    combined_text = " ".join(screen_text)
                    if any(marker in combined_text for marker in empty_markers):
                        self.keyevent(device_id, 3)
                        self.lock_portrait(device_id, retries=2)
                        return True
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
                self.execute_adb(
                    device_id, ["shell", "rm", "-f", remote_xml]
                )

            if attempt < max(0, max_scrolls):
                # Pixel đặt Clear all ở mép trái của carousel. Vuốt ngón tay
                # sang phải nhiều lượt để đưa nút này vào vùng hiển thị.
                self.swipe(
                    device_id,
                    int(width * 0.18),
                    int(height * 0.52),
                    int(width * 0.86),
                    int(height * 0.52),
                    duration=560,
                )
                time.sleep(0.4)

        self.keyevent(device_id, 3)
        self.lock_portrait(device_id, retries=2)
        return False

    def launch_app(self, device_id, package_name):
        """Khởi chạy một ứng dụng bằng package name"""
        # Sử dụng monkey để khởi chạy nhanh app từ launcher
        return self.execute_adb(device_id, ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    def clear_input_field(self, device_id, max_chars=40):
        """Xóa toàn bộ ký tự trong ô input đang focus."""
        self.execute_adb(
            device_id,
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "XW_CLEAR_TEXT",
                "--receiver-foreground",
            ],
        )
        num = min(max(max_chars, 20), 60)
        backspaces = " ".join(["67"] * num)
        self.execute_adb(device_id, ["shell", f"input keyevent {backspaces}"])
        time.sleep(0.3)

    def input_text(self, device_id, text):
        """Nhập text Tiếng Việt qua XwIME broadcast hoặc fallback input text."""
        if not text:
            return True
        self.ensure_ime(device_id)
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code, _, _ = self.execute_adb(
            device_id,
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "XW_INPUT_B64",
                "--es",
                "msg",
                encoded,
                "--receiver-foreground",
            ],
        )
        if code == 0:
            return True
        escaped = text.replace(" ", "%s")
        self.execute_adb(device_id, ["shell", "input", "text", escaped])
        return True

    def is_shopee_in_foreground(self, device_id):
        """Xác định Shopee thật sự đang foreground, không dựa vào recents."""
        for dumpsys_target in (
            ["shell", "dumpsys", "window", "windows"],
            ["shell", "dumpsys", "activity", "activities"],
        ):
            code, stdout, _ = self.execute_adb(device_id, dumpsys_target)
            if code != 0:
                continue
            focus_lines = [
                line.casefold()
                for line in stdout.splitlines()
                if "mcurrentfocus" in line.casefold()
                or "mfocusedapp" in line.casefold()
                or "mresumedactivity" in line.casefold()
            ]
            if any(SHOPEE_PACKAGE.casefold() in line for line in focus_lines):
                return True
        return False

    def is_facebook_in_foreground(self, device_id):
        """Xác định Facebook đang là ứng dụng foreground trên thiết bị."""
        for dumpsys_target in (
            ["shell", "dumpsys", "window", "windows"],
            ["shell", "dumpsys", "activity", "activities"],
        ):
            code, stdout, _ = self.execute_adb(device_id, dumpsys_target)
            if code == 0 and config.FACEBOOK_PACKAGE in stdout.casefold():
                focus_lines = [
                    line.casefold()
                    for line in stdout.splitlines()
                    if "mcurrentfocus" in line.casefold()
                    or "mfocusedapp" in line.casefold()
                    or "mresumedactivity" in line.casefold()
                ]
                if any(config.FACEBOOK_PACKAGE in line for line in focus_lines):
                    return True
        return False

    def wait_for_facebook_foreground(self, device_id, checks=3, delay=0.35):
        """Chờ ngắn khi dumpsys mất một nhịp dưới tải nhiều thiết bị."""
        total_checks = max(1, checks)
        for index in range(total_checks):
            if self.is_facebook_in_foreground(device_id):
                return True
            if index + 1 < total_checks:
                time.sleep(delay)
        return False

    def ensure_facebook_ready(self, device_id):
        """Giữ Facebook hiện tại hoặc mở app nếu chưa ở foreground."""
        self.lock_portrait(device_id)
        if self.is_facebook_in_foreground(device_id):
            ready = self.ensure_facebook_home(device_id)
            self.lock_portrait(device_id, retries=3)
            return ready
        self.launch_app(device_id, config.FACEBOOK_PACKAGE)
        # Facebook có thể ghi đè orientation khi activity vừa xuất hiện.
        self.lock_portrait(device_id, retries=3)
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        time.sleep(1.7)
        self.lock_portrait(device_id, retries=3)
        if not self.is_facebook_in_foreground(device_id):
            return False
        ready = self.ensure_facebook_home(device_id)
        self.lock_portrait(device_id, retries=3)
        return ready

    def is_facebook_home(self, device_id):
        """Xác minh giao diện Home/Feed Facebook qua các marker đang hiển thị."""
        focus_code, focus_stdout, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "window", "windows"]
        )
        if focus_code == 0:
            focused_lines = " ".join(
                line.casefold()
                for line in focus_stdout.splitlines()
                if "mcurrentfocus" in line.casefold()
                or "mfocusedapp" in line.casefold()
            )
            non_home_activities = (
                "immersiveactivity",
                "storyvieweractivity",
                "stories.viewer",
                "reel",
            )
            if config.FACEBOOK_PACKAGE in focused_lines and any(
                marker in focused_lines for marker in non_home_activities
            ):
                return False

        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_home_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_home_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            visible_text = self._normalize_facebook_text(
                " ".join(
                    " ".join(
                        (
                            node.get("text", ""),
                            node.get("content-desc", ""),
                            node.get("resource-id", ""),
                        )
                    )
                    for node in root.iter()
                )
            )
            strong_markers = (
                "ban dang nghi gi",
                "create story",
                "tao tin",
                "news feed",
                "bang feed",
            )
            has_feed_marker = any(
                marker in visible_text for marker in strong_markers
            )
            has_facebook_header = "facebook" in visible_text
            has_home_marker = any(
                marker in visible_text
                for marker in ("trang chu", "home tab", "home")
            )
            header_control_groups = (
                ("menu",),
                ("tao", "create"),
                ("tim kiem", "search"),
                ("nhan tin", "messaging"),
            )
            header_control_score = sum(
                any(marker in visible_text for marker in marker_group)
                for marker_group in header_control_groups
            )
            return has_feed_marker or (
                has_facebook_header and has_home_marker
            ) or header_control_score >= 3
        except (OSError, ET.ParseError):
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def get_facebook_feed_signature(self, device_id):
        """Return visible Feed content used to detect a white/stalled surface."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_feed_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_feed_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            signature = []
            ignored = {
                "facebook", "home", "trang chu", "menu", "search",
                "tim kiem", "notifications", "thong bao", "messaging",
                "nhan tin", "create", "tao",
            }
            for node in root.iter():
                bounds = node.get("bounds", "")
                match = re.match(
                    r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds
                )
                if not match:
                    continue
                _x1, y1, _x2, y2 = map(int, match.groups())
                if y2 < 180:
                    continue
                text = self._normalize_facebook_text(
                    f"{node.get('text', '')} {node.get('content-desc', '')}"
                )
                if not text or text in ignored:
                    continue
                signature.append((text, y1, y2))
            return tuple(signature) if len(signature) >= 2 else None
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def ensure_facebook_home(self, device_id):
        """Thoát viewer/Page cũ để bắt đầu đúng tại Home Feed Facebook."""
        # Khi nhiều máy dump UI cùng lúc, uiautomator có thể tạm trả về None.
        # Không được coi trạng thái chưa xác định là đang ở viewer rồi bấm Back,
        # vì Back tại Home sẽ thoát/thu nhỏ Facebook thay vì bắt đầu đọc Feed.
        home_checks = []
        for check_index in range(2):
            home_state = self.is_facebook_home(device_id)
            home_checks.append(home_state)
            if home_state is True:
                return True
            if check_index == 0:
                time.sleep(0.35)
                self.lock_portrait(device_id, retries=3)

        # Chỉ Back khi hai lần kiểm tra liên tiếp đều xác nhận chắc chắn không
        # phải Home. Nếu dump UI bận giữa chừng, chuyển sang deep link an toàn.
        if all(state is False for state in home_checks):
            for _ in range(4):
                self.keyevent(device_id, 4)
                self.lock_portrait(device_id, retries=3)
                time.sleep(0.8)
                self.lock_portrait(device_id, retries=3)
                home_state = self.is_facebook_home(device_id)
                if home_state is True:
                    return True
                if home_state is None:
                    break

        # Deep link feed là phương án có kiểm soát, tránh tap mù lên giao diện.
        self.execute_adb(
            device_id,
            [
                "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", "fb://feed",
                "-p", config.FACEBOOK_PACKAGE,
            ],
        )
        self.lock_portrait(device_id, retries=3)
        time.sleep(2.0)
        self.lock_portrait(device_id, retries=3)
        home_state = self.is_facebook_home(device_id)
        if home_state is True:
            return True
        # Deep link đã mở đúng package nhưng XML vẫn bận: cho phép bước Feed
        # thực hiện swipe thật và tự kiểm tra foreground thay vì Back lặp.
        return home_state is None and self.is_facebook_in_foreground(device_id)

    def restart_facebook_home(self, device_id):
        """Khởi động sạch tiến trình Facebook, giữ nguyên dữ liệu tài khoản."""
        self.lock_portrait(device_id, retries=3)
        self.execute_adb(
            device_id,
            ["shell", "am", "force-stop", config.FACEBOOK_PACKAGE],
        )
        time.sleep(0.4)
        self.launch_app(device_id, config.FACEBOOK_PACKAGE)
        self.lock_portrait(device_id, retries=3)
        for _ in range(8):
            time.sleep(1.0)
            self.lock_portrait(device_id, retries=3)
            if (
                self.is_facebook_in_foreground(device_id)
                and self.is_facebook_home(device_id)
                and self.get_facebook_feed_signature(device_id) is not None
            ):
                return True
        return False

    @staticmethod
    def _normalize_facebook_text(value):
        """Chuẩn hóa chữ Facebook để so khớp không phân biệt dấu/hoa thường."""
        normalized = unicodedata.normalize("NFKD", value or "")
        without_marks = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).split()
        )

    def prepare_facebook_target_results(self, device_id):
        """Đưa kết quả target về đầu và ưu tiên bộ lọc Page/Trang."""
        self.lock_portrait(device_id, retries=3)
        if not self.is_facebook_in_foreground(device_id):
            return False

        width, height = self.get_effective_screen_size(device_id)
        # B2 có lướt kết quả mồi nên Facebook đôi lúc giữ nguyên offset khi
        # tìm target. Vuốt ngón tay xuống trong vùng nội dung để trở về đầu;
        # tuyệt đối không bắt đầu sát status bar để tránh kéo notification.
        for swipe_duration in (620, 700, 660):
            self.swipe(
                device_id,
                width // 2,
                int(height * 0.32),
                width // 2,
                int(height * 0.82),
                duration=swipe_duration,
            )
            time.sleep(0.45)
        self.lock_portrait(device_id, retries=3)

        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_target_tabs_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_target_tabs_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                # Đã hoàn tất phần bắt buộc là đưa danh sách về đầu; Facebook
                # có phiên bản không xuất tab Trang vào cây accessibility.
                return True
            root = ET.parse(local_xml).getroot()
            parent_map = {
                child: parent for parent in root.iter() for child in parent
            }
            page_tabs = []
            for node in root.iter():
                label = self._normalize_facebook_text(
                    " ".join(
                        part
                        for part in (
                            node.get("text", ""),
                            node.get("content-desc", ""),
                        )
                        if part
                    )
                )
                if label not in {"trang", "page", "pages"}:
                    continue
                clickable = node
                while (
                    clickable is not None
                    and clickable.get("clickable", "false") != "true"
                ):
                    clickable = parent_map.get(clickable)
                click_node = clickable if clickable is not None else node
                match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    click_node.get("bounds", ""),
                )
                if not match:
                    continue
                x1, y1, x2, y2 = map(int, match.groups())
                cy = (y1 + y2) // 2
                if int(height * 0.05) <= cy <= int(height * 0.30):
                    page_tabs.append((cy, (x1 + x2) // 2))
            if page_tabs:
                tab_y, tab_x = min(page_tabs)
                self.tap(device_id, tab_x, tab_y)
                time.sleep(2.0)
                self.lock_portrait(device_id, retries=3)
            return True
        except Exception as exc:
            print(
                f"[Device {device_id[:6]}] Không đọc được tab Trang "
                f"Facebook, tiếp tục từ đầu kết quả: {exc}"
            )
            return True
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def find_and_click_facebook_page(
        self,
        device_id,
        target_phrase,
        max_swipes=4,
        exact_page_name=None,
    ):
        """Tìm và bấm Page có tên chứa đầy đủ cụm target đã nhập."""
        target_normalized = self._normalize_facebook_text(target_phrase)
        desired_normalized = self._normalize_facebook_text(
            exact_page_name or target_phrase
        )
        target_tokens = [token for token in target_normalized.split() if token]
        desired_tokens = [token for token in desired_normalized.split() if token]
        if not target_tokens:
            return False

        width, height = self.get_effective_screen_size(device_id)
        for attempt in range(max(1, max_swipes)):
            remote_xml = f"/sdcard/dump_facebook_page_{device_id}.xml"
            local_xml = os.path.join(
                os.path.dirname(__file__),
                f"temp_facebook_page_{device_id}.xml",
            )
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
            self.execute_adb(
                device_id, ["shell", "uiautomator", "dump", remote_xml]
            )
            pull_code, _, _ = self.execute_adb(
                device_id, ["pull", remote_xml, local_xml]
            )

            try:
                if pull_code == 0 and os.path.exists(local_xml):
                    root = ET.parse(local_xml).getroot()
                    parent_map = {
                        child: parent
                        for parent in root.iter()
                        for child in parent
                    }
                    candidates = []
                    for node in root.iter():
                        if node.get("class", "").endswith("EditText"):
                            continue
                        label = " ".join(
                            part
                            for part in (
                                node.get("text", ""),
                                node.get("content-desc", ""),
                            )
                            if part
                        ).strip()
                        label_normalized = self._normalize_facebook_text(label)
                        if not label_normalized or not all(
                            token in label_normalized.split()
                            for token in target_tokens
                        ):
                            continue

                        clickable = node
                        while (
                            clickable is not None
                            and clickable.get("clickable", "false") != "true"
                        ):
                            clickable = parent_map.get(clickable)
                        click_node = clickable if clickable is not None else node
                        bounds = click_node.get("bounds", "")
                        match = re.match(
                            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds
                        )
                        if not match:
                            continue
                        x1, y1, x2, y2 = map(int, match.groups())
                        if y2 <= int(height * 0.08):
                            continue
                        exact_match = bool(desired_tokens) and all(
                            token in label_normalized.split()
                            for token in desired_tokens
                        )
                        contiguous = desired_normalized in label_normalized
                        candidates.append(
                            (
                                0 if exact_match or contiguous else 1,
                                -len(label_normalized),
                                (x1 + x2) // 2,
                                (y1 + y2) // 2,
                            )
                        )

                    if candidates:
                        _, _, x, y = min(candidates)
                        self.tap(device_id, x, y)
                        time.sleep(3.0)
                        return True
            except Exception as exc:
                print(
                    f"[Device {device_id[:6]}] Lỗi đọc kết quả Page "
                    f"Facebook: {exc}"
                )
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
                self.execute_adb(
                    device_id, ["shell", "rm", "-f", remote_xml]
                )

            if attempt < max(1, max_swipes) - 1:
                self.swipe(
                    device_id,
                    width // 2,
                    int(height * 0.78),
                    width // 2,
                    int(height * 0.30),
                    duration=random.randint(650, 950),
                )
                time.sleep(1.5)
        return False

    def _get_facebook_search_input_state(self, device_id):
        """Đọc ô Search Facebook ở vùng header."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_input_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_input_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        if pull_code != 0 or not os.path.exists(local_xml):
            return None

        candidates = []
        try:
            root = ET.parse(local_xml).getroot()
            for node in root.iter():
                class_name = node.get("class", "").casefold()
                resource_id = node.get("resource-id", "").casefold()
                description = node.get("content-desc", "").casefold()
                editable = node.get("editable", "false") == "true"
                searchable = "search" in f"{resource_id} {description}"
                if not (editable or "edittext" in class_name or searchable):
                    continue
                match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    node.get("bounds", ""),
                )
                if not match:
                    continue
                x1, y1, x2, y2 = map(int, match.groups())
                cy = (y1 + y2) // 2
                if cy > 360:
                    continue
                focused = node.get("focused", "false") == "true"
                candidates.append(
                    {
                        "score": (
                            int(focused) * 8
                            + int(editable) * 4
                            + int("edittext" in class_name) * 2
                            + int(searchable)
                        ),
                        "text": node.get("text", ""),
                        "focused": focused,
                        "coords": ((x1 + x2) // 2, cy),
                    }
                )
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

        if not candidates:
            return None
        best = max(candidates, key=lambda item: item["score"])
        best.pop("score", None)
        return best

    def _focus_facebook_search_input(self, device_id):
        width, height = self.get_effective_screen_size(device_id)
        state = self._get_facebook_search_input_state(device_id)
        coords = state["coords"] if state else (
            int(width * 0.45),
            int(height * 0.055),
        )
        self.tap(device_id, coords[0], coords[1])
        time.sleep(0.4)
        return True

    def _get_facebook_header_search_coords(self, device_id):
        """Đọc đúng tọa độ Search trên header, không chạm vùng nội dung."""
        width, height = self.get_effective_screen_size(device_id)
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_search_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_search_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            for node in root.iter():
                haystack = " ".join(
                    (
                        node.get("text", ""),
                        node.get("content-desc", ""),
                        node.get("resource-id", ""),
                    )
                ).casefold()
                if not any(
                    marker in haystack
                    for marker in (
                        "search", "tìm kiếm", "tim kiem", "search_button",
                    )
                ):
                    continue
                match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    node.get("bounds", ""),
                )
                if not match:
                    continue
                x1, y1, x2, y2 = map(int, match.groups())
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                if cy <= int(height * 0.18) and cx >= int(width * 0.65):
                    return cx, cy
            return None
        except (OSError, ET.ParseError):
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def _recover_facebook_search_with_one_back(self, device_id):
        """Back đúng một lần; nếu Facebook rơi nền thì mở lại, không lặp Back."""
        if not self.wait_for_facebook_foreground(device_id):
            return False
        self.keyevent(device_id, 4)
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        if self.wait_for_facebook_foreground(device_id):
            return True
        self.launch_app(device_id, config.FACEBOOK_PACKAGE)
        time.sleep(1.4)
        self.lock_portrait(device_id, retries=3)
        return self.wait_for_facebook_foreground(device_id)

    def find_and_click_facebook_search(self, device_id):
        """Mở Search; nếu header ẩn thì Back đúng một lần rồi thử lại."""
        self.lock_portrait(device_id)
        if not self.wait_for_facebook_foreground(device_id):
            return False

        # Ở bước 3, ô Search có thể đã hiện sẵn trên trang kết quả. Dùng đúng
        # EditText này trước để không cuộn hoặc reset trang không cần thiết.
        current_input = self._get_facebook_search_input_state(device_id)
        if current_input is not None:
            input_x, input_y = current_input["coords"]
            self.tap(device_id, input_x, input_y)
            time.sleep(0.4)
            return True

        width, height = self.get_effective_screen_size(device_id)
        if self.is_facebook_home(device_id) is True:
            # Đây chỉ là nỗ lực nhẹ. Nếu header vẫn ẩn, vòng dưới sẽ dùng Back
            # đúng một lần theo yêu cầu rồi xác minh lại đúng ứng dụng.
            self.reveal_facebook_header(device_id)

        recovered_with_back = False
        for attempt in range(2):
            if not self.wait_for_facebook_foreground(device_id):
                return False
            coords = self._get_facebook_header_search_coords(device_id)

            if coords is None:
                input_state = self._get_facebook_search_input_state(device_id)
                if input_state:
                    coords = input_state["coords"]
                elif (
                    recovered_with_back
                    and self.is_facebook_home(device_id) is True
                ):
                    # Sau Back và xác minh Home, đây là đúng vùng Search header.
                    # Tọa độ này giúp nhóm máy UIAutomator đang bận vẫn tiếp tục.
                    coords = (int(width * 0.83), int(height * 0.055))

            if coords is not None:
                self.tap(device_id, coords[0], coords[1])
                time.sleep(1.0)
                self.lock_portrait(device_id)
                for verify_attempt in range(2):
                    input_state = self._get_facebook_search_input_state(device_id)
                    if input_state is not None:
                        if not input_state.get("focused"):
                            input_x, input_y = input_state["coords"]
                            self.tap(device_id, input_x, input_y)
                            time.sleep(0.4)
                        return True
                    if verify_attempt == 0:
                        time.sleep(0.35)

                # Khi 40 máy dump đồng thời, XML có thể bận dù tap Search đã
                # được Android nhận. Nếu vẫn xác minh đang ở Home thì tap chưa
                # mở Search: phải đi qua nhánh Back một lần ở dưới. Trạng thái
                # False/None cho thấy đã rời Home hoặc XML bận, lúc đó để bước
                # nhập XwIME tiếp tục xác minh chính xác nội dung.
                home_after_tap = self.is_facebook_home(device_id)
                if (
                    home_after_tap is not True
                    and self.wait_for_facebook_foreground(device_id)
                ):
                    return True

            if attempt == 0:
                if not self._recover_facebook_search_with_one_back(device_id):
                    return False
                recovered_with_back = True
                continue
            return False
        return False

    def replace_facebook_search_text(self, device_id, text):
        """Xóa sạch từ khóa Facebook cũ rồi nhập nguyên cụm mới một lần."""
        expected = self._normalize_facebook_text(text)
        for attempt in range(2):
            if not self.wait_for_facebook_foreground(device_id):
                raise RuntimeError(
                    "Facebook không còn ở foreground; đã chặn nhập từ khóa"
                )
            self.ensure_ime(device_id)
            self._focus_facebook_search_input(device_id)
            if not self.wait_for_facebook_foreground(device_id):
                raise RuntimeError(
                    "Facebook không còn ở foreground; đã chặn xóa từ khóa"
                )
            clear_code, _, _ = self.execute_adb(
                device_id,
                [
                    "shell", "am", "broadcast",
                    "-a", "XW_CLEAR_TEXT",
                    "--receiver-foreground",
                ],
            )
            if clear_code != 0:
                continue
            if not self.wait_for_facebook_foreground(device_id):
                raise RuntimeError(
                    "Facebook không còn ở foreground; đã chặn nhập từ khóa"
                )
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            input_code, _, _ = self.execute_adb(
                device_id,
                [
                    "shell", "am", "broadcast",
                    "-a", "XW_INPUT_B64",
                    "--es", "msg", encoded,
                    "--receiver-foreground",
                ],
            )
            if input_code != 0:
                continue
            time.sleep(0.5)
            state = self._get_facebook_search_input_state(device_id)
            if state is not None and (
                self._normalize_facebook_text(state["text"]) == expected
            ):
                return True
            if attempt == 0:
                time.sleep(0.3)
        raise RuntimeError(
            f"Không thể nhập chính xác từ khóa Facebook: '{text}'"
        )

    def submit_facebook_search(self, device_id):
        """Gửi tìm kiếm Facebook bằng Enter của bàn phím."""
        if not self.wait_for_facebook_foreground(device_id):
            raise RuntimeError(
                "Facebook không còn ở foreground; đã chặn gửi tìm kiếm"
            )
        return self.press_enter(device_id)

    def facebook_loading_delay(
        self, device_id, context, status_callback=None, is_cancelled=None
    ):
        """Chờ Facebook tải nội dung trước khi vuốt hoặc bấm."""
        delay = random.uniform(5.0, 10.0)
        labels = {
            "seed_results": "kết quả từ khóa mồi",
            "target_results": "kết quả Page mục tiêu",
            "target_page": "Page mục tiêu",
        }
        if status_callback:
            status_callback(
                device_id,
                f"Chờ {delay:.1f} giây để {labels.get(context, context)} tải...",
            )
        remaining = delay
        while remaining > 0:
            if is_cancelled and is_cancelled():
                raise RuntimeError("Bị dừng bởi người dùng")
            step = min(0.25, remaining)
            time.sleep(step)
            remaining -= step
        return delay

    def advance_facebook_feed(self, device_id):
        """Vuốt Feed ngay một lần và xác minh nội dung đã đổi khi có thể."""
        if not self.is_facebook_in_foreground(device_id):
            return False

        width, height = self.get_effective_screen_size(device_id)
        before = self.get_facebook_feed_signature(device_id)
        x = width // 2 + random.randint(-80, 80)
        swipe_result = self.swipe(
            device_id,
            x,
            int(height * 0.78) + random.randint(-45, 45),
            x + random.randint(-30, 30),
            int(height * 0.28) + random.randint(-45, 45),
            duration=random.randint(650, 1050),
        )
        swipe_code = (
            swipe_result[0]
            if isinstance(swipe_result, tuple) and swipe_result
            else None
        )
        time.sleep(1.0)
        self.lock_portrait(device_id, retries=3)
        if not self.is_facebook_in_foreground(device_id):
            return False

        after = self.get_facebook_feed_signature(device_id)
        if before is not None and after is not None:
            if after != before:
                return True
            # Bài ảnh/video thường giữ nguyên accessibility text sau khi đã
            # cuộn. Nếu Android nhận swipe và Facebook vẫn ở Home/foreground,
            # không được kết luận sai là Feed đứng rồi phát sinh lệnh Back.
            if swipe_code == 0:
                return self.is_facebook_home(device_id) is not False
            return False

        # Một số Android cũ không dump được UI khi video đang phát. Khi ADB đã
        # nhận swipe thành công và Facebook vẫn foreground, coi thao tác là đạt.
        return swipe_code == 0

    def ensure_facebook_feed_motion(
        self, device_id, label_name="Facebook Feed", status_callback=None
    ):
        """Swipe Feed; retry tại chỗ khi cần và không Back khỏi Home."""
        if self.advance_facebook_feed(device_id):
            return True
        if status_callback:
            status_callback(
                device_id,
                f"[{label_name}] Chưa xác minh được chuyển động • "
                "đang vuốt lại tại Feed...",
            )
        if not self.is_facebook_in_foreground(device_id):
            return False
        return self.advance_facebook_feed(device_id)

    def browse_facebook_surface(
        self,
        device_id,
        total_seconds,
        label,
        status_callback=None,
        is_cancelled=None,
    ):
        """Lướt feed/kết quả/Page theo nhịp ngẫu nhiên giống người dùng."""
        width, height = self.get_effective_screen_size(device_id)
        deadline = time.monotonic() + max(0, total_seconds)
        item_index = 1
        label_names = {
            "feed": "Feed Facebook",
            "seed_results": "kết quả từ khóa mồi",
            "target_page": "Page mục tiêu",
            "facebook_cross_warmup": "Facebook Feed nuôi chéo",
        }
        label_name = label_names.get(label, label)
        feed_surface = label in ("facebook_cross_warmup", "feed")

        def ensure_safe_foreground():
            if self.is_facebook_in_foreground(device_id):
                return True
            if label != "facebook_cross_warmup":
                return False
            if status_callback:
                status_callback(
                    device_id,
                    "[Nuôi chéo] Facebook tạm mất foreground • đang mở lại Feed...",
                )
            if not self.ensure_facebook_ready(device_id):
                return False
            self.lock_portrait(device_id, retries=3)
            return self.is_facebook_in_foreground(device_id)

        # Facebook Home phải có chuyển động ngay sau khi sẵn sàng. Không chờ
        # 6-15 giây ở bài đầu vì người vận hành sẽ tưởng máy bị treo.
        if feed_surface and time.monotonic() < deadline:
            if not ensure_safe_foreground():
                raise RuntimeError(
                    f"{label_name}: Facebook không ở foreground; "
                    "đã dừng để tránh thao tác nhầm ứng dụng"
                )
            if not self.ensure_facebook_feed_motion(
                device_id,
                label_name=label_name,
                status_callback=status_callback,
            ):
                raise RuntimeError(
                    f"{label_name}: Không thể vuốt Feed sau hai lần thử tại chỗ"
                )

        while time.monotonic() < deadline:
            self.lock_portrait(device_id, retries=3)
            if is_cancelled and is_cancelled():
                raise RuntimeError("Bị dừng bởi người dùng")
            if not ensure_safe_foreground():
                raise RuntimeError(
                    f"{label_name}: Facebook không ở foreground; "
                    "đã dừng để tránh thao tác nhầm ứng dụng"
                )
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            dwell = min(float(random.randint(6, 15)), remaining)
            if status_callback:
                status_callback(
                    device_id,
                    f"Xem {label_name} lượt {item_index} ({int(dwell)}s) • "
                    f"còn {int(remaining)}s...",
                )
            dwell_remaining = dwell
            while dwell_remaining > 0 and time.monotonic() < deadline:
                sleep_step = min(
                    1.0,
                    dwell_remaining,
                    max(0.0, deadline - time.monotonic()),
                )
                if sleep_step <= 0:
                    break
                time.sleep(sleep_step)
                dwell_remaining -= sleep_step
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Bị dừng bởi người dùng")
            if time.monotonic() < deadline:
                if not ensure_safe_foreground():
                    raise RuntimeError(
                        f"{label_name}: Facebook không ở foreground; "
                        "không thực hiện swipe"
                    )
                if feed_surface:
                    if not self.ensure_facebook_feed_motion(
                        device_id,
                        label_name=label_name,
                        status_callback=status_callback,
                    ):
                        raise RuntimeError(
                            f"{label_name}: Không thể vuốt Feed sau hai lần "
                            "thử tại chỗ"
                        )
                else:
                    x = width // 2 + random.randint(-80, 80)
                    self.swipe(
                        device_id,
                        x,
                        int(height * 0.78) + random.randint(-45, 45),
                        x + random.randint(-30, 30),
                        int(height * 0.28) + random.randint(-45, 45),
                        duration=random.randint(650, 1050),
                    )
                    self.lock_portrait(device_id, retries=3)
                item_index += 1
        self.lock_portrait(device_id, retries=3)
        return True

    def warmup_facebook_before_tiktok(
        self, device_id, status_callback=None, is_cancelled=None
    ):
        """Nuôi Facebook Feed ngắn trước khi chuyển sang TikTok."""
        if status_callback:
            status_callback(
                device_id,
                "[Nuôi chéo] Mở Facebook trước khi chạy TikTok...",
            )
        if not self.ensure_facebook_ready(device_id):
            raise RuntimeError(
                "Không mở được Facebook cho bước nuôi chéo trước TikTok"
            )
        self.lock_portrait(device_id, retries=3)
        total_seconds = random.randint(
            config.SOCIAL_CROSS_WARMUP_MIN,
            config.SOCIAL_CROSS_WARMUP_MAX,
        )
        if status_callback:
            status_callback(
                device_id,
                f"[Nuôi chéo] Lướt Facebook Feed trong "
                f"{total_seconds // 60} phút {total_seconds % 60:02d} giây...",
            )
        result = self.browse_facebook_surface(
            device_id,
            total_seconds,
            "facebook_cross_warmup",
            status_callback=status_callback,
            is_cancelled=is_cancelled,
        )
        self.lock_portrait(device_id, retries=3)
        return result

    def is_tiktok_home_feed(self, device_id, root=None):
        """Xác minh TikTok đang ở Home/For You, không phải Search/Profile."""
        if root is None:
            root = self._get_tiktok_ui_root(device_id, "tt_home_check")
        if root is None:
            return False

        texts = []
        for node in root.iter():
            for value in (
                node.get("text", ""),
                node.get("content-desc", ""),
            ):
                text = self._normalize_tiktok_text(value)
                if text:
                    texts.append(text)

        has_home_navigation = any(
            text in ("home", "trang chu", "trang chủ") for text in texts
        )
        has_feed_action = any(
            marker in text
            for text in texts
            for marker in (
                "like video",
                "thich video",
                "thích video",
                "like photo",
                "thich bai viet",
                "thích bài viết",
                "read or add comments",
                "doc hoac viet binh luan",
                "đọc hoặc viết bình luận",
            )
        )
        blocked_screen = any(
            marker in text
            for text in texts
            for marker in (
                "no more results",
                "khong con ket qua",
                "không còn kết quả",
                "search results",
                "ket qua tim kiem",
                "kết quả tìm kiếm",
            )
        )
        return has_home_navigation and has_feed_action and not blocked_screen

    def _find_tiktok_home_navigation(self, root):
        """Lấy tọa độ tab Home/Trang chủ qua clickable ancestor."""
        parent_map = {
            child: parent for parent in root.iter() for child in parent
        }
        for node in root.iter():
            labels = {
                self._normalize_tiktok_text(node.get("text", "")),
                self._normalize_tiktok_text(
                    node.get("content-desc", "")
                ),
            }
            if not labels.intersection(("home", "trang chu", "trang chủ")):
                continue
            clickable = node
            while (
                clickable is not None
                and clickable.get("clickable", "false") != "true"
            ):
                clickable = parent_map.get(clickable)
            coords = self._element_center(
                clickable if clickable is not None else node
            )
            if coords:
                return coords
        return None

    def ensure_tiktok_home_feed(self, device_id, force_refresh=False):
        """Thoát Search/Profile và đưa TikTok về Home/For You có xác minh."""
        self.dismiss_tiktok_blocking_popup(device_id)
        refresh_pending = bool(force_refresh)
        missing_root_attempts = 0
        fallback_home_taps = 0
        for _ in range(6):
            self.lock_portrait(device_id, retries=3)
            root = self._get_tiktok_ui_root(device_id, "tt_home_ready")
            if root is None:
                missing_root_attempts += 1
                time.sleep(1.0)
                self.lock_portrait(device_id, retries=3)
                if missing_root_attempts < 3:
                    continue

                # Không bấm Back khi chưa đọc được UI: ở Home, nhiều lần Back
                # sẽ thoát TikTok. Tab Home dùng tọa độ theo wm override nên
                # vẫn hoạt động trên nhóm máy 1440x2560 -> 1080x1920.
                if self.is_tiktok_in_foreground(device_id):
                    width, height = self.get_effective_screen_size(device_id)
                    self.tap(device_id, int(width * 0.10), int(height * 0.96))
                    fallback_home_taps += 1
                    time.sleep(0.8)
                    self.lock_portrait(device_id, retries=3)
                    if missing_root_attempts >= 5:
                        return True
                    continue
            else:
                missing_root_attempts = 0
                on_feed = self.is_tiktok_home_feed(device_id, root=root)
                if on_feed and not refresh_pending:
                    return True

                home_coords = self._find_tiktok_home_navigation(root)
                if home_coords:
                    self.tap(device_id, home_coords[0], home_coords[1])
                    time.sleep(0.8)
                    self.lock_portrait(device_id, retries=3)
                    time.sleep(0.7)
                    self.lock_portrait(device_id, retries=3)
                    refresh_pending = False
                    continue

            self.keyevent(device_id, 4)
            time.sleep(0.5)
            self.lock_portrait(device_id, retries=3)
            time.sleep(0.5)
            self.lock_portrait(device_id, retries=3)

        root = self._get_tiktok_ui_root(device_id, "tt_home_final")
        if root is None and fallback_home_taps:
            return self.is_tiktok_in_foreground(device_id)
        return root is not None and self.is_tiktok_home_feed(
            device_id, root=root
        )

    def is_tiktok_in_foreground(self, device_id):
        """Xác minh một trong hai package TikTok đang ở foreground."""
        packages = (
            config.TIKTOK_PACKAGE.casefold(),
            config.TIKTOK_PACKAGE_ALT.casefold(),
        )
        for dumpsys_target in (
            ["shell", "dumpsys", "window", "windows"],
            ["shell", "dumpsys", "activity", "activities"],
        ):
            code, stdout, _ = self.execute_adb(device_id, dumpsys_target)
            if code != 0:
                continue
            focus_lines = " ".join(
                line.casefold()
                for line in stdout.splitlines()
                if "mcurrentfocus" in line.casefold()
                or "mfocusedapp" in line.casefold()
                or "mresumedactivity" in line.casefold()
            )
            if any(package in focus_lines for package in packages):
                return True
        return False

    def wait_for_tiktok_foreground(self, device_id, checks=3, delay=0.6):
        """Cho activity TikTok thời gian lấy lại focus trước khi kết luận mất app."""
        for index in range(max(1, checks)):
            if self.is_tiktok_in_foreground(device_id):
                return True
            if index + 1 < max(1, checks):
                time.sleep(delay)
        return False

    def ensure_tiktok_foreground_ready(
        self, device_id, attempts=3, status_callback=None
    ):
        """Ổn định TikTok sau khi chuyển app và xác minh Home trước thao tác."""
        for attempt in range(max(1, attempts)):
            self.lock_portrait(device_id, retries=3)
            if not self.wait_for_tiktok_foreground(device_id):
                if status_callback:
                    status_callback(
                        device_id,
                        f"[TikTok] Đang ổn định ứng dụng sau chuyển cảnh "
                        f"({attempt + 1}/{max(1, attempts)})...",
                    )
                self.launch_tiktok(device_id)
                self.lock_portrait(device_id, retries=3)
                time.sleep(1.0)
            if not self.wait_for_tiktok_foreground(device_id):
                continue
            if not self.ensure_tiktok_home_feed(device_id):
                continue
            self.lock_portrait(device_id, retries=3)
            if self.wait_for_tiktok_foreground(device_id):
                return True
        return False

    def ensure_tiktok_feed_motion(
        self, device_id, status_callback=None, home_ready=False
    ):
        """Swipe Home ngay; nếu đứng thì Back, mở lại TikTok và swipe lại."""
        if home_ready and not self.is_tiktok_in_foreground(device_id):
            home_ready = False
        if not home_ready:
            if not self.ensure_tiktok_foreground_ready(
                device_id, status_callback=status_callback
            ):
                return False
        if self.advance_tiktok_feed(device_id):
            return True
        if status_callback:
            status_callback(
                device_id,
                "[TikTok] Feed đứng • Back và mở lại TikTok để thử lại...",
            )
        if not self.is_tiktok_in_foreground(device_id):
            return False

        self.keyevent(device_id, 4)
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        self.launch_tiktok(device_id)
        if not self.ensure_tiktok_foreground_ready(
            device_id, status_callback=status_callback
        ):
            return False
        return self.advance_tiktok_feed(device_id)

    def warmup_tiktok_before_facebook(
        self, device_id, status_callback=None, is_cancelled=None
    ):
        """Xem video TikTok ngắn trước khi chuyển sang Facebook."""
        if status_callback:
            status_callback(
                device_id,
                "[Nuôi chéo] Mở TikTok trước khi chạy Facebook...",
            )
        self.launch_tiktok(device_id)
        total_seconds = random.randint(
            config.SOCIAL_CROSS_WARMUP_MIN,
            config.SOCIAL_CROSS_WARMUP_MAX,
        )
        if status_callback:
            status_callback(
                device_id,
                f"[Nuôi chéo] Xem video TikTok trong "
                f"{total_seconds // 60} phút {total_seconds % 60:02d} giây...",
            )

        deadline = time.monotonic() + max(0, total_seconds)
        if not self.ensure_tiktok_feed_motion(
            device_id, status_callback=status_callback
        ):
            raise RuntimeError(
                "TikTok đứng màn hình và không thể phục hồi bằng Back/mở lại"
            )
        self.lock_portrait(device_id, retries=3)
        video_index = 1
        while time.monotonic() < deadline:
            self.lock_portrait(device_id, retries=3)
            if is_cancelled and is_cancelled():
                raise RuntimeError("Bị dừng bởi người dùng")
            if not self.is_tiktok_in_foreground(device_id):
                raise RuntimeError(
                    "TikTok không ở foreground; đã dừng nuôi chéo để "
                    "tránh thao tác nhầm ứng dụng"
                )
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            dwell = min(float(random.randint(8, 18)), remaining)
            if status_callback:
                status_callback(
                    device_id,
                    f"[Nuôi chéo] Xem video TikTok {video_index} "
                    f"({int(dwell)}s) • còn {int(remaining)}s...",
                )
            dwell_remaining = dwell
            while dwell_remaining > 0 and time.monotonic() < deadline:
                sleep_step = min(
                    1.0,
                    dwell_remaining,
                    max(0.0, deadline - time.monotonic()),
                )
                if sleep_step <= 0:
                    break
                time.sleep(sleep_step)
                dwell_remaining -= sleep_step
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Bị dừng bởi người dùng")
            if time.monotonic() < deadline:
                if not self.is_tiktok_in_foreground(device_id):
                    raise RuntimeError(
                        "TikTok không ở foreground trước khi swipe; "
                        "đã dừng an toàn"
                    )
                if not self.ensure_tiktok_feed_motion(
                    device_id,
                    status_callback=status_callback,
                    home_ready=True,
                ):
                    raise RuntimeError(
                        "TikTok không đổi video sau khi Back và mở lại Home"
                    )
                self.lock_portrait(device_id, retries=3)
                video_index += 1
        self.lock_portrait(device_id, retries=3)
        return True

    def reveal_facebook_header(self, device_id):
        """Hiện header bằng một swipe xuống trong Feed, không Back khỏi Home."""
        if (
            not self.is_facebook_in_foreground(device_id)
            or not self.is_facebook_home(device_id)
        ):
            return False

        self.lock_portrait(device_id, retries=3)
        width, height = self.get_effective_screen_size(device_id)
        swipe_result = self.swipe(
            device_id,
            width // 2,
            int(height * 0.32),
            width // 2,
            int(height * 0.72),
            duration=520,
        )
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        swipe_code = (
            swipe_result[0]
            if isinstance(swipe_result, tuple) and swipe_result
            else None
        )
        return (
            swipe_code in (None, 0)
            and self.is_facebook_in_foreground(device_id)
            and self.is_facebook_home(device_id) is not False
        )

    def is_facebook_target_page_open(
        self, device_id, target_phrase, exact_page_name=None
    ):
        """Xác minh đã vào profile Page, không còn ở danh sách kết quả."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_profile_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_fb_profile_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return False
            root = ET.parse(local_xml).getroot()
            all_text = self._normalize_facebook_text(
                " ".join(
                    " ".join(
                        (node.get("text", ""), node.get("content-desc", ""))
                    )
                    for node in root.iter()
                )
            )
            # Header Page có thể bị rút gọn khác nhau giữa các phiên bản
            # Facebook. Tên đầy đủ dùng để ưu tiên lúc chọn kết quả; khi xác
            # minh chỉ bắt buộc cụm target do người dùng cấu hình.
            target_tokens = self._normalize_facebook_text(
                target_phrase
            ).split()
            has_target = all(token in all_text.split() for token in target_tokens)
            profile_markers = (
                "theo doi",
                "nhan tin",
                "bai viet",
                "chi tiet",
                "luot nhac",
                "follow",
                "message",
                "posts",
                "about",
                "details",
                "likes",
            )
            return has_target and any(marker in all_text for marker in profile_markers)
        except Exception:
            return False
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    @serialized_device_workflow
    def facebook_automation_workflow(
        self,
        device_id,
        seed_keywords,
        target_pages,
        status_callback=None,
        is_cancelled=None,
    ):
        """Nuôi feed, tìm từ khóa mồi rồi vào đúng Page mục tiêu."""
        def update_status(message):
            print(f"[Device {device_id[:6]}] {message}")
            if status_callback:
                status_callback(device_id, message)

        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise RuntimeError("Bị dừng bởi người dùng")

        def ensure_facebook_action_context(step_name):
            """Phục hồi Facebook trước khi thao tác nhập liệu của từng bước."""
            self.lock_portrait(device_id, retries=3)
            if self.is_facebook_in_foreground(device_id):
                return
            update_status(
                f"[{step_name}] Facebook bị chuyển nền • đang mở lại an toàn..."
            )
            if not self.ensure_facebook_ready(device_id):
                raise RuntimeError(
                    f"{step_name}: Không thể đưa Facebook về foreground"
                )
            if not self.is_facebook_in_foreground(device_id):
                raise RuntimeError(
                    f"{step_name}: Facebook vẫn không ở foreground"
                )

        seeds = (
            [item.strip() for item in seed_keywords.split(",") if item.strip()]
            if isinstance(seed_keywords, str)
            else [str(item).strip() for item in seed_keywords if str(item).strip()]
        )
        targets = (
            [item.strip() for item in target_pages.split(",") if item.strip()]
            if isinstance(target_pages, str)
            else [str(item).strip() for item in target_pages if str(item).strip()]
        )

        try:
            if not seeds:
                raise RuntimeError("Chưa nhập từ khóa mồi Facebook")
            if not targets:
                raise RuntimeError("Chưa nhập Page target Facebook")
            seed_keyword = random.choice(seeds)
            target_phrase = random.choice(targets)
            configured_exact_page = (
                config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT.strip()
            )
            target_tokens = self._normalize_facebook_text(
                target_phrase
            ).split()
            exact_page_name = None
            if configured_exact_page:
                configured_tokens = self._normalize_facebook_text(
                    configured_exact_page
                ).split()
                if all(token in configured_tokens for token in target_tokens):
                    exact_page_name = configured_exact_page
            self.lock_portrait(device_id)

            check_cancelled()
            self.warmup_tiktok_before_facebook(
                device_id,
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()
            update_status("[Facebook B1] Kiểm tra và mở Facebook...")
            if not self.ensure_facebook_ready(device_id):
                raise RuntimeError("Không mở được ứng dụng Facebook")
            feed_total = random.randint(
                config.FACEBOOK_STEP1_FEED_MIN,
                config.FACEBOOK_STEP1_FEED_MAX,
            )
            update_status(
                f"[Facebook B1] Nuôi Feed trong {feed_total}s (10-20s)..."
            )
            self.browse_facebook_surface(
                device_id,
                feed_total,
                "feed",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )

            check_cancelled()
            ensure_facebook_action_context("Facebook B2")
            self.reveal_facebook_header(device_id)
            update_status(
                f"[Facebook B2] Tìm từ khóa mồi '{seed_keyword}'..."
            )
            if not self.find_and_click_facebook_search(device_id):
                raise RuntimeError("Không mở được ô Search Facebook")
            self.replace_facebook_search_text(device_id, seed_keyword)
            self.submit_facebook_search(device_id)
            self.facebook_loading_delay(
                device_id,
                "seed_results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            seed_result_total = random.randint(
                config.FACEBOOK_STEP2_RESULTS_MIN,
                config.FACEBOOK_STEP2_RESULTS_MAX,
            )
            update_status(
                f"[Facebook B2] Lướt kết quả trong {seed_result_total}s "
                "(10-15s)..."
            )
            self.browse_facebook_surface(
                device_id,
                seed_result_total,
                "seed_results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )

            check_cancelled()
            ensure_facebook_action_context("Facebook B3")
            update_status(
                f"[Facebook B3] Xóa sạch từ khóa mồi và tìm Page "
                f"'{target_phrase}'..."
            )
            if not self.find_and_click_facebook_search(device_id):
                raise RuntimeError("Không mở lại được ô Search Facebook")
            self.replace_facebook_search_text(device_id, target_phrase)
            self.submit_facebook_search(device_id)
            self.facebook_loading_delay(
                device_id,
                "target_results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            update_status(
                "[Facebook B3] Đưa kết quả về đầu và ưu tiên tab Trang..."
            )
            if not self.prepare_facebook_target_results(device_id):
                raise RuntimeError(
                    "Facebook rời foreground khi chuẩn bị kết quả Page target"
                )
            page_clicked = False
            for target_attempt in range(2):
                if self.find_and_click_facebook_page(
                    device_id,
                    target_phrase,
                    exact_page_name=exact_page_name,
                ):
                    page_clicked = True
                    break
                if target_attempt == 0:
                    check_cancelled()
                    update_status(
                        "[Facebook B3] Chưa thấy Page ở lượt đầu • "
                        "tải lại kết quả và thử thêm một lần..."
                    )
                    ensure_facebook_action_context("Facebook B3 retry")
                    if self.find_and_click_facebook_search(device_id):
                        self.replace_facebook_search_text(
                            device_id, target_phrase
                        )
                        self.submit_facebook_search(device_id)
                    self.facebook_loading_delay(
                        device_id,
                        "target_results",
                        status_callback=status_callback,
                        is_cancelled=is_cancelled,
                    )
                    if not self.prepare_facebook_target_results(device_id):
                        raise RuntimeError(
                            "Facebook rời foreground khi tải lại Page target"
                        )
            if not page_clicked:
                raise RuntimeError(
                    f"Không tìm thấy Page Facebook chứa đủ cụm '{target_phrase}'"
                )
            self.facebook_loading_delay(
                device_id,
                "target_page",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            target_verified = False
            for verify_attempt in range(3):
                if self.is_facebook_target_page_open(
                    device_id,
                    target_phrase,
                    exact_page_name=exact_page_name,
                ):
                    target_verified = True
                    break
                if verify_attempt < 2:
                    check_cancelled()
                    update_status(
                        "[Facebook B3] Page đang mở nhưng header chưa tải đủ • "
                        f"xác minh lại ({verify_attempt + 2}/3)..."
                    )
                    time.sleep(1.5)
                    self.lock_portrait(device_id, retries=3)
            if not target_verified:
                raise RuntimeError(
                    f"Đã bấm kết quả nhưng chưa vào đúng Page '{target_phrase}'"
                )

            target_total = random.randint(
                config.FACEBOOK_STEP3_PAGE_MIN,
                config.FACEBOOK_STEP3_PAGE_MAX,
            )
            update_status(
                f"[Facebook B3] Đã vào đúng Page • lướt trong "
                f"{target_total // 60} phút {target_total % 60:02d} giây..."
            )
            self.browse_facebook_surface(
                device_id,
                target_total,
                "target_page",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            update_status("Hoàn thành tác vụ Bơm Facebook!")
            return True, "Thành công"
        except Exception as exc:
            message = str(exc)
            update_status(f"Lỗi Facebook: {message}")
            return False, message

    def is_shopee_home_activity(self, device_id):
        """Xác minh cửa sổ đang focus chính xác là HomeActivity của Shopee."""
        code, stdout, _ = self.execute_adb(
            device_id,
            ["shell", "dumpsys", "window", "windows"],
        )
        if code != 0:
            return False

        focus_lines = [
            line.casefold()
            for line in stdout.splitlines()
            if "mcurrentfocus" in line.casefold()
            or "mfocusedapp" in line.casefold()
        ]
        return any(
            "com.shopee.vn/" in line and "homeactivity" in line
            for line in focus_lines
        )

    def is_on_shopee_homepage(self, device_id):
        """Kiểm tra xem thiết bị có đang ở màn hình chính Shopee hay không"""
        # 1. Kiểm tra tiến trình Shopee đang ở foreground
        if not self.is_shopee_in_foreground(device_id):
            return False

        xml_file = f"/sdcard/check_home_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        
        code, stdout, stderr = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_check_home_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        is_home = False
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                with open(local_xml, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Các chỉ báo rộng hơn cho trang chủ Shopee (bao gồm cả content-desc và text)
                keywords = [
                    "Trang chủ", "Trang Chủ", "Home", "Mall", "Live", "Video", "Shopee",
                    "Thông báo", "Notifications", "Tôi", "Me", "Tìm kiếm", "Search",
                    "inputSearchBar", "search", "com.shopee.vn"
                ]
                
                content_lower = content.lower()
                matches = sum(1 for kw in keywords if kw.lower() in content_lower)
                
                # Nếu tìm thấy từ 2 chỉ báo trở lên trong XML hoặc chứa resource-id shopee
                if matches >= 2 or "com.shopee.vn" in content:
                    is_home = True
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        else:
            # Nếu uiautomator dump gặp lỗi/idle state nhưng Shopee vẫn đang hiển thị ở mảng chính
            print(f"[Device {device_id[:6]}] Shopee đang chạy ở foreground -> Xác nhận đang ở màn hình chính Shopee.")
            return True
                
        return is_home

    def ensure_shopee_homepage(self, device_id, status_callback=None):
        """Đảm bảo đưa Shopee về trang chủ và dọn sạch popup quảng cáo"""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        update_status("Khởi chạy & đưa Shopee về trang chủ...")
        self.launch_app(device_id, "com.shopee.vn")
        time.sleep(2.0)
        
        # Thử kiểm tra và dọn popup 2 lần
        for attempt in range(3):
            update_status(f"Xác thực màn hình chính & dọn popup (Lần {attempt + 1}/3)...")
            self.bypass_shopee_popup(device_id)
            
            if self.is_on_shopee_homepage(device_id):
                update_status("Đã ở màn hình chính Shopee.")
                return True
                
            update_status("Tắt popup / Nhấn Back 1 lần...")
            self.keyevent(device_id, 4)
            time.sleep(1.2)
            self.launch_app(device_id, "com.shopee.vn")
            time.sleep(1.0)
                
        # Giả định an toàn nếu Shopee vẫn ở mảng chính
        if self.is_shopee_in_foreground(device_id):
            update_status("Đã xác thực Shopee đang hiển thị trên màn hình chính.")
            return True
            
        update_status("Khởi động lại ứng dụng Shopee...")
        self.stop_app(device_id, "com.shopee.vn")
        time.sleep(1.5)
        self.launch_app(device_id, "com.shopee.vn")
        time.sleep(3.0)
        self.bypass_shopee_popup(device_id)
        return True

    def stop_app(self, device_id, package_name):
        """Buộc dừng một ứng dụng và xóa khỏi danh sách đa nhiệm mà không mất dữ liệu"""
        self.execute_adb(device_id, ["shell", "am", "force-stop", package_name])
        self.execute_adb(device_id, ["shell", "pm", "disable-user", package_name])
        return self.execute_adb(device_id, ["shell", "pm", "enable", package_name])

    def bypass_shopee_popup(self, device_id):
        """
        Quét giao diện XML để phát hiện và click nút đóng popup quảng cáo (nếu có),
        hoặc gửi phím Back dự phòng để đóng các Dialog quảng cáo đè trên trang chủ.
        """
        xml_file = f"/sdcard/dump_popup_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        
        # Dump giao diện
        code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        if code != 0:
            # Nếu không dump được, gửi phím Back dự phòng
            self.keyevent(device_id, 4)
            time.sleep(1.0)
            return
            
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_dump_popup_{device_id}.xml")
        code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        closed = False
        if os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                
                # Danh sách các từ khóa nhận dạng nút Đóng popup
                close_keywords = ["đóng", "close", "tắt", "dismiss", "cancel", "không, cảm ơn", "để sau", "lần sau"]
                close_patterns = [re.compile(rf"\b{k}\b", re.IGNORECASE) for k in close_keywords]
                
                for elem in root.iter():
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    res_id = elem.get('resource-id', '')
                    
                    # 1. Kiểm tra text hoặc content-desc khớp với từ khóa đóng
                    matched = False
                    for pattern in close_patterns:
                        if pattern.search(text) or pattern.search(desc):
                            matched = True
                            break
                            
                    # 2. Hoặc resource-id chứa các hậu tố đóng quen thuộc
                    if not matched and res_id:
                        res_id_lower = res_id.lower()
                        if any(x in res_id_lower for x in ["close", "dismiss", "cancel", "btn_close", "iv_close"]):
                            matched = True
                            
                    if matched:
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            cx = (x1 + x2) // 2
                            cy = (y1 + y2) // 2
                            # Đảm bảo tọa độ hợp lệ
                            if cx > 0 and cy > 0:
                                print(f"[Device {device_id[:6]}] Phát hiện nút đóng popup tại ({cx}, {cy}) [Text: '{text}', ID: '{res_id}']")
                                self.tap(device_id, cx, cy)
                                closed = True
                                time.sleep(1.0)
                                break
            except Exception as e:
                print(f"[Device {device_id[:6]}] Lỗi phân tích XML popup: {e}")
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
                # Xóa file XML trên thiết bị
                self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
                    
        # Nếu quét XML không chủ động click được nút nào, gửi phím Back dự phòng để đóng Dialog
        if not closed:
            print(f"[Device {device_id[:6]}] Gửi phím Back dự phòng để tắt popup Dialog...")
            self.keyevent(device_id, 4)
            time.sleep(1.0)

    def shopee_loading_delay(
        self,
        device_id,
        context,
        status_callback=None,
        is_cancelled=None,
    ):
        """Delay ngẫu nhiên 5-10 giây trước khi Shopee lướt hoặc bấm."""
        context_labels = {
            "home": "trang chủ",
            "results": "kết quả sau khi Enter",
            "shop": "trang Shop",
            "product": "trang sản phẩm",
        }
        delay = random.uniform(5.0, 10.0)
        context_label = context_labels.get(context, context)
        if status_callback:
            status_callback(
                device_id,
                f"Chờ {delay:.1f} giây cho {context_label} tải ổn định "
                "trước khi tương tác...",
            )

        remaining = delay
        while remaining > 0:
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")
            sleep_step = min(0.25, remaining)
            time.sleep(sleep_step)
            remaining -= sleep_step
        return delay

    def input_text(self, device_id, text):
        """Nhập chữ tiếng Việt thông qua bàn phím XwIME bằng Base64 broadcast"""
        # Đảm bảo IME đã bật
        self.ensure_ime(device_id)
        
        # Mã hóa base64 UTF-8 chuỗi văn bản cần nhập
        b64_bytes = base64.b64encode(text.encode('utf-8'))
        b64_str = b64_bytes.decode('utf-8')
        
        # Gửi broadcast tới XwIME
        cmd = [
            "shell", "am", "broadcast", 
            "-a", "XW_INPUT_B64", 
            "--es", "msg", b64_str, 
            "--receiver-foreground"
        ]
        return self.execute_adb(device_id, cmd)

    def remove_vietnamese_accents(self, text):
        """Chuyển đổi chuỗi tiếng Việt có dấu thành không dấu để gửi an toàn qua ADB shell input text"""
        s1 = u'ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯưẠạẢảẤấẦầẨẩẪẫẬậẮắẰằẲẳẴẵẶặẸẹẺẻẼẽẾếỀềỂểỄễỆệỈỉỊịỌọỎỏỐốỒồỔổỖỗỘộỚớỜờỞởỠỡỢợỤụỦủỨứỪừỬửỮữỰựỲỳỴỵỶỷỸỹ'
        s0 = u'AAAAEEEIIOOOOUUYaaaaeeeiioooouuyAdDIiOoUuAaAaAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIiOoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYy'
        s = ''
        for c in text:
            if c in s1:
                s += s0[s1.index(c)]
            else:
                s += c
        return s

    def input_text_naturally(self, device_id, text):
        """Mô phỏng gõ chữ từ app truyền sang từng từ một chuẩn 100% bằng ADB keyevents"""
        self.ensure_ime(device_id)
        
        # 1. Thử gửi Tiếng Việt có dấu qua XwIME Base64 broadcast
        try:
            b64_bytes = base64.b64encode(text.encode('utf-8'))
            b64_str = b64_bytes.decode('utf-8')
            self.execute_adb(device_id, [
                "shell", "am", "broadcast", 
                "-a", "XW_INPUT_B64", 
                "--es", "msg", b64_str, 
                "--receiver-foreground"
            ])
        except Exception:
            pass
        time.sleep(0.3)
        
        # 2. Phương án bảo đảm 100%: Chuyển thành không dấu & gõ từng từ một qua ADB text + space (62)
        try:
            ascii_text = self.remove_vietnamese_accents(text)
            words = [re.sub(r'[^a-zA-Z0-9]', '', w) for w in ascii_text.split() if w.strip()]
            for idx, w in enumerate(words):
                if w:
                    self.execute_adb(device_id, ["shell", "input", "text", w])
                    time.sleep(0.15)
                    if idx < len(words) - 1:
                        # Phím cách (Space keyevent 62)
                        self.execute_adb(device_id, ["shell", "input", "keyevent", "62"])
                        time.sleep(0.15)
        except Exception:
            pass
        time.sleep(0.5)


    def press_enter(self, device_id):
        """Gửi lệnh enter thông qua bàn phím XwIME và Android keyevent"""
        # Cách 1: Gửi qua broadcast của XwIME (Mã code 13 = Enter)
        self.execute_adb(device_id, ["shell", "am", "broadcast", "-a", "XW_INPUT_CODE", "--ei", "code", "13", "--receiver-foreground"])
        # Cách 2: Lệnh keyevent ENTER chuẩn của Android (66)
        self.keyevent(device_id, 66)
        # Cách 3: Lệnh keyevent SEARCH của Android (84)
        self.keyevent(device_id, 84)

    def submit_tiktok_search(self, device_id):
        """Gửi đúng một phím Enter cho ô tìm kiếm TikTok."""
        if not self.wait_for_tiktok_foreground(device_id):
            raise RuntimeError(
                "TikTok không còn ở foreground; đã chặn gửi tìm kiếm"
            )
        result = self.keyevent(device_id, 66)
        if isinstance(result, tuple):
            return bool(result) and result[0] == 0
        return result is not False

    def clear_input_field(self, device_id, max_chars=40):
        """Xóa sạch văn bản cũ trong ô tìm kiếm một cách triệt để"""
        try:
            for _ in range(max_chars):
                self.execute_adb(device_id, ["shell", "input", "keyevent", "67"])
        except Exception:
            pass

    def replace_shopee_search_text(self, device_id, text):
        """Xóa sạch ô tìm kiếm Shopee rồi nhập đúng một từ khóa đúng một lần."""
        if not self.is_shopee_in_foreground(device_id):
            raise RuntimeError(
                "Shopee không còn ở foreground; đã chặn nhập từ khóa"
            )
        clear_code, _, _ = self.execute_adb(
            device_id,
            [
                "shell", "am", "broadcast",
                "-a", "XW_CLEAR_TEXT",
                "--receiver-foreground",
            ],
        )
        if clear_code != 0:
            return False
        time.sleep(0.3)
        if not self.is_shopee_in_foreground(device_id):
            raise RuntimeError(
                "Shopee không còn ở foreground; đã chặn bơm từ khóa"
            )

        b64_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        input_code, _, _ = self.execute_adb(
            device_id,
            [
                "shell", "am", "broadcast",
                "-a", "XW_INPUT_B64",
                "--es", "msg", b64_text,
                "--receiver-foreground",
            ],
        )
        return input_code == 0

    def submit_shopee_search(self, device_id):
        """Chỉ gửi Enter khi Shopee vẫn là ứng dụng foreground."""
        if not self.is_shopee_in_foreground(device_id):
            raise RuntimeError(
                "Shopee không còn ở foreground; đã chặn gửi tìm kiếm"
            )
        return self.press_enter(device_id)

    def take_screenshot(self, device_id, local_path):
        """Chụp màn hình điện thoại và tải về máy tính"""
        remote_path = f"/sdcard/screen_{device_id}.png"
        
        # 1. Chụp màn hình trên thiết bị
        code, stdout, stderr = self.execute_adb(device_id, ["shell", "screencap", "-p", remote_path])
        if code != 0:
            return False, f"screencap error: {stderr}"
        
        # 2. Kéo file về máy tính
        code, stdout, stderr = self.execute_adb(device_id, ["pull", remote_path, local_path])
        if code != 0:
            return False, f"adb pull error: {stderr}"
        
        # 3. Xóa file tạm trên thiết bị
        self.execute_adb(device_id, ["shell", "rm", remote_path])
        return True, local_path

    def _get_wm_size_output(self, device_id):
        now = time.monotonic()
        with self._screen_size_cache_guard:
            cached = self._screen_size_cache.get(device_id)
            if cached and now - cached[0] < self._screen_size_cache_seconds:
                return cached[1]

        code, output, _ = self.execute_adb(
            device_id, ["shell", "wm", "size"]
        )
        if code != 0:
            return ""
        with self._screen_size_cache_guard:
            self._screen_size_cache[device_id] = (now, output)
        return output

    def get_screen_size(self, device_id):
        """Lấy độ phân giải màn hình của thiết bị (width, height)"""
        output = self._get_wm_size_output(device_id)
        physical = re.search(
            r"Physical size:\s*(\d+)x(\d+)", output, re.IGNORECASE
        )
        if physical:
            return int(physical.group(1)), int(physical.group(2))
        size = re.search(r"size:\s*(\d+)x(\d+)", output)
        if size:
            return int(size.group(1)), int(size.group(2))
        return 1080, 1920 # Mặc định nếu lỗi

    def get_effective_screen_size(self, device_id):
        """Lấy kích thước tọa độ đang được Android dùng sau khi áp dụng wm override."""
        output = self._get_wm_size_output(device_id)
        override = re.search(
            r"Override size:\s*(\d+)x(\d+)", output, re.IGNORECASE
        )
        if override:
            return int(override.group(1)), int(override.group(2))
        physical = re.search(
            r"Physical size:\s*(\d+)x(\d+)", output, re.IGNORECASE
        )
        if physical:
            return int(physical.group(1)), int(physical.group(2))
        size = re.search(r"size:\s*(\d+)x(\d+)", output)
        if size:
            return int(size.group(1)), int(size.group(2))
        return 1080, 1920

    def find_element_coords_by_text(self, device_id, target_text):
        """Dump XML và tìm tọa độ của phần tử khớp với target_text"""
        xml_file = f"/sdcard/dump_text_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        
        code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        if code != 0:
            return None
            
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_dump_text_{device_id}.xml")
        code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        coords = None
        if os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                for elem in root.iter():
                    text = elem.get('text', '')
                    if target_text.lower() in text.lower():
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                            break
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        return coords

    def ensure_shopee_search_box_click(self, device_id, status_callback=None):
        """
        Mở tìm kiếm Shopee an toàn ở cả Trang chủ và trang chi tiết:
        1. Ưu tiên ô tìm kiếm thật trên Trang chủ.
        2. Nếu đang ở trang chi tiết, bấm đúng kính lúp trên header.
        3. Nếu không thấy kính lúp, Back ra ngoài rồi quét lại ô tìm kiếm.

        Tuyệt đối không bấm mù vùng Home/giỏ hàng.
        """
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        def tap_search_target(x, y):
            # Search/IME là thời điểm một số máy Samsung dễ đọc cảm biến và
            # đổi sang landscape. Khóa dọc cả trước lẫn ngay sau cú chạm.
            self.lock_portrait(device_id)
            self.tap(device_id, x, y)
            self.lock_portrait(device_id)

        width, height = self.get_screen_size(device_id)

        def scan_search_targets():
            xml_file = f"/sdcard/dump_search_click_{device_id}.xml"
            local_xml = os.path.join(
                os.path.dirname(__file__),
                f"temp_dump_search_click_{device_id}.xml",
            )
            self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
            dump_code, dump_stdout, dump_stderr = self.execute_adb(
                device_id, ["shell", "uiautomator", "dump", xml_file]
            )
            dump_message = f"{dump_stdout} {dump_stderr}".casefold()
            ui_busy = "could not get idle state" in dump_message
            if dump_code != 0 or ui_busy:
                return None, None, ui_busy

            pull_code, _, _ = self.execute_adb(
                device_id, ["pull", xml_file, local_xml]
            )
            if pull_code != 0 or not os.path.exists(local_xml):
                return None, None, False

            home_search_coords = None
            header_search_coords = None
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()

                for elem in root.iter():
                    res_id = elem.get('resource-id', '')
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    class_name = elem.get('class', '').lower()
                    editable = elem.get('editable', '').lower() == 'true'
                    val = " ".join((res_id, text, desc)).lower()
                    bounds = elem.get('bounds', '')
                    match = re.match(
                        r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',
                        bounds,
                    )
                    if not match:
                        continue

                    x1, y1, x2, y2 = map(int, match.groups())
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    if not (30 < cy < 250):
                        continue

                    home_markers = (
                        "inputsearchbar",
                        "search_text",
                        "search_bar",
                        "search_prefill_click",
                        "pre_search_label",
                    )
                    excluded_markers = (
                        "cart",
                        "giỏ",
                        "chat",
                        "share",
                        "filter",
                        "more",
                    )
                    generic_top_input = (
                        (editable or "edittext" in class_name)
                        and (x2 - x1) >= int(width * 0.35)
                        and x1 < int(width * 0.25)
                        and x2 < int(width * 0.90)
                    )
                    if (
                        (
                            any(marker in val for marker in home_markers)
                            or generic_top_input
                        )
                        and not any(marker in val for marker in excluded_markers)
                    ):
                        home_search_coords = (cx, cy)
                        continue

                    header_markers = (
                        "search_icon",
                        "search_btn",
                        "btn_search",
                        "action_search",
                        "iv_search",
                    )
                    desc_is_search = desc.strip().casefold() in {
                        "search",
                        "tìm kiếm",
                    }
                    if (
                        (
                            any(marker in val for marker in header_markers)
                            or desc_is_search
                        )
                        and not any(marker in val for marker in excluded_markers)
                        and int(width * 0.55) < cx < int(width * 0.90)
                    ):
                        header_search_coords = (cx, cy)
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
                self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
            return home_search_coords, header_search_coords, False

        def click_guarded_home_search():
            if not self.is_shopee_home_activity(device_id):
                return False
            guarded_x = int(width * 0.40)
            guarded_y = int(height * 0.08)
            update_status(
                "Shopee Home đang bận animation • bấm vùng search "
                "đã xác minh an toàn..."
            )
            tap_search_target(guarded_x, guarded_y)
            time.sleep(1.2)
            return True

        home_coords, header_coords, ui_busy = scan_search_targets()
        if ui_busy and click_guarded_home_search():
            return True

        if home_coords:
            print(
                f"[Device {device_id[:6]}] Phát hiện ô tìm kiếm Trang chủ "
                f"tại ({home_coords[0]}, {home_coords[1]})."
            )
            tap_search_target(home_coords[0], home_coords[1])
            time.sleep(1.0)
            return True

        if header_coords:
            update_status("Đang ở trang chi tiết • bấm kính lúp trên header...")
            tap_search_target(header_coords[0], header_coords[1])
            time.sleep(1.0)
            return True

        # Không có mục tiêu chắc chắn: dùng Back để thoát trang chi tiết,
        # tuyệt đối không chạm vào vùng nút mua hàng ở cuối màn hình.
        for attempt in range(2):
            update_status(
                f"Không thấy kính lúp • thoát trang chi tiết "
                f"({attempt + 1}/2) rồi tìm lại..."
            )
            self.keyevent(device_id, 4)
            time.sleep(1.2)
            home_coords, header_coords, ui_busy = scan_search_targets()
            if ui_busy and click_guarded_home_search():
                return True
            target_coords = home_coords or header_coords
            if target_coords:
                tap_search_target(target_coords[0], target_coords[1])
                time.sleep(1.0)
                return True

        # Trạng thái Shopee trên một số máy có thể chưa tải xong hoặc đang ở
        # màn hình trung gian. Phục hồi có kiểm soát về Trang chủ rồi quét lại;
        # vẫn tuyệt đối không dùng tọa độ mù.
        update_status(
            "Chưa nhận diện được ô tìm kiếm • phục hồi Trang chủ và thử lại..."
        )
        self.ensure_shopee_homepage(
            device_id,
            status_callback=status_callback,
        )
        self.bypass_shopee_popup(device_id)
        time.sleep(2.0)

        for attempt in range(3):
            home_coords, header_coords, ui_busy = scan_search_targets()
            if ui_busy and click_guarded_home_search():
                return True
            target_coords = home_coords or header_coords
            if target_coords:
                update_status(
                    f"Đã nhận diện ô tìm kiếm sau phục hồi "
                    f"({attempt + 1}/3)."
                )
                tap_search_target(target_coords[0], target_coords[1])
                time.sleep(1.0)
                return True
            if attempt < 2:
                time.sleep(1.0)

        # Một số máy Shopee luôn chạy animation ở Home khiến uiautomator báo
        # "could not get idle state" và không tạo XML. Chỉ dùng tọa độ dự phòng
        # sau khi dumpsys xác nhận chính xác cửa sổ đang focus là HomeActivity.
        if click_guarded_home_search():
            return True

        update_status("Không xác định được ô tìm kiếm Shopee an toàn.")
        return False

    @serialized_device_workflow
    def shopee_search_sequence(self, device_id, keyword, status_callback=None, is_cancelled=None):
        """Quy trình tự động tìm kiếm trên Shopee cho 1 thiết bị"""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")

        try:
            check_cancelled()
            self.lock_portrait(device_id)
            
            check_cancelled()
            update_status("Đang đưa Shopee về trang chủ...")
            self.ensure_shopee_homepage(device_id, status_callback=status_callback)
            
            # Tự động phát hiện và tắt popup quảng cáo trang chủ nếu có (dự phòng)
            check_cancelled()
            update_status("Kiểm tra và tắt popup quảng cáo...")
            self.bypass_shopee_popup(device_id)

            self.shopee_loading_delay(
                device_id,
                "home",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
                
            # Lấy kích thước màn hình động
            width, height = self.get_screen_size(device_id)
            swipe_x = int(width * 0.25)

            # Dạo trang chủ Shopee ở dải lề trái tránh chạm các ô Video ở giữa
            update_status("Dạo trang chủ Shopee...")
            for _ in range(random.randint(2, 3)):
                check_cancelled()
                y_start = int(height * 0.75) + random.randint(-50, 50)
                y_end = int(height * 0.3) + random.randint(-50, 50)
                self.swipe(device_id, swipe_x, y_start, swipe_x, y_end, duration=random.randint(600, 900))
                time.sleep(random.uniform(2.0, 3.0))
            
            update_status("Bấm vào thanh tìm kiếm...")
            if not self.ensure_shopee_search_box_click(
                device_id,
                status_callback=status_callback,
            ):
                raise RuntimeError("Không mở được ô tìm kiếm Shopee an toàn")
            time.sleep(1.0)
            check_cancelled()
            
            # Click lại vào ô nhập liệu để chắc chắn bàn phím xuất hiện
            self.tap(device_id, int(width * 0.45), int(height * 0.055))
            time.sleep(1.0)
            check_cancelled()
            
            update_status(f"Đang nhập từ khóa '{keyword}'...")
            if not self.replace_shopee_search_text(device_id, keyword):
                raise RuntimeError("Không thể xóa và nhập từ khóa Shopee")
            time.sleep(1.5)
            check_cancelled()
            
            update_status("Gửi lệnh tìm kiếm...")
            self.submit_shopee_search(device_id)
            self.shopee_loading_delay(
                device_id,
                "results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()
            
            update_status("Hoàn thành tìm kiếm!")
            return True, "Thành công"
        except Exception as e:
            msg = str(e)
            update_status(f"Lỗi: {msg}")
            return False, msg

    def check_and_bypass_captcha(self, device_id, max_retries=3, status_callback=None):
        """
        [Đã vô hiệu hóa theo yêu cầu] Luôn trả về True để người dùng tự giải tay Captcha trên xiaowei.
        """
        return True

    def extract_lamdong_product_candidates(self, root, limit=10):
        """Lấy tối đa ``limit`` card sản phẩm có nhãn địa chỉ Lâm Đồng."""
        candidates = []
        seen = set()
        for elem in root.iter():
            normalized_text = self.remove_vietnamese_accents(
                elem.get("text", "")
            ).casefold()
            if "lam dong" not in normalized_text:
                continue

            bounds = elem.get("bounds", "")
            match = re.match(
                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                bounds,
            )
            if not match:
                continue

            x1, y1, x2, y2 = map(int, match.groups())
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            # Loại thanh tìm kiếm/bộ lọc và thanh điều hướng cuối màn hình.
            if cx <= 0 or not 220 < cy < 1800:
                continue

            product_coords = (cx, cy)
            if product_coords in seen:
                continue
            seen.add(product_coords)
            candidates.append(product_coords)
            if len(candidates) >= limit:
                break
        return candidates

    def choose_lamdong_product_candidate(self, candidates):
        """Chọn ngẫu nhiên một card Lâm Đồng đã xác minh."""
        return random.choice(candidates) if candidates else None

    def is_shopee_product_detail(self, device_id):
        """Xác minh màn hình hiện tại vẫn là trang chi tiết sản phẩm Shopee."""
        remote_xml = f"/sdcard/shopee_product_state_{device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_shopee_product_state_{device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id,
            ["shell", "uiautomator", "dump", remote_xml],
        )
        if dump_code != 0:
            return False
        pull_code, _, _ = self.execute_adb(
            device_id,
            ["pull", remote_xml, local_xml],
        )
        if pull_code != 0 or not os.path.exists(local_xml):
            return None

        try:
            root = ET.parse(local_xml).getroot()
            markers = (
                "labelproductpageproductname",
                "buttonproductaddcart",
                "sectionproductimages",
                "buttonproductbuynow",
            )
            return any(
                any(marker in elem.get("resource-id", "").casefold()
                    for marker in markers)
                for elem in root.iter()
            )
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def return_to_shopee_product_after_shop(
        self,
        device_id,
        product_coords,
        status_callback=None,
        is_cancelled=None,
    ):
        """Back khỏi Shop và tự mở lại card nếu Shopee rơi về kết quả tìm kiếm."""
        def update_status(message):
            if status_callback:
                status_callback(device_id, message)

        def verify_product_state():
            state = self.is_shopee_product_detail(device_id)
            for _ in range(2):
                if state is not None:
                    break
                time.sleep(0.5)
                state = self.is_shopee_product_detail(device_id)
            return state

        self.keyevent(device_id, 4)
        self.shopee_loading_delay(
            device_id,
            "product",
            status_callback=status_callback,
            is_cancelled=is_cancelled,
        )
        product_state = verify_product_state()
        if product_state is True:
            return True
        if product_state is None:
            update_status(
                "Chưa đọc được trạng thái Shopee sau khi rời Shop • "
                "dừng an toàn, không bấm mù."
            )
            return False

        update_status(
            "Back từ Shop rơi về kết quả tìm kiếm • tự mở lại sản phẩm đã chọn..."
        )
        for _ in range(2):
            if is_cancelled and is_cancelled():
                return False
            self.tap(device_id, product_coords[0], product_coords[1])
            self.shopee_loading_delay(
                device_id,
                "product",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            product_state = verify_product_state()
            if product_state is True:
                return True
            if product_state is None:
                update_status(
                    "Không xác minh được trang Shopee • dừng an toàn."
                )
                return False
        update_status("Không thể mở lại trang chi tiết sản phẩm sau khi rời Shop.")
        return False

    @serialized_device_workflow
    def shopee_find_and_click_lamdong(self, device_id, keyword, max_swipes=10, status_callback=None, is_cancelled=None, click_first_item=False):
        """Kịch bản tìm kiếm từ khóa và tự động vuốt màn hình để tìm + click vào shop có nhãn 'Tỉnh Lâm Đồng' (hoặc bài đăng đầu tiên nếu bật click_first_item)"""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")

        try:
            check_cancelled()
            self.lock_portrait(device_id)
            
            check_cancelled()
            update_status("Đang đưa Shopee về trang chủ...")
            self.ensure_shopee_homepage(device_id, status_callback=status_callback)
            
            # Kiểm tra Captcha lần 1 sau khi mở ứng dụng
            if not self.check_and_bypass_captcha(device_id, max_retries=3, status_callback=status_callback):
                return False, "Bị chặn bởi Captcha (Không thể tự giải sau khi mở Shopee)"
                
            # Tự động phát hiện và tắt popup quảng cáo trang chủ nếu có (dự phòng)
            check_cancelled()
            update_status("Kiểm tra và tắt popup quảng cáo...")
            self.bypass_shopee_popup(device_id)

            self.shopee_loading_delay(
                device_id,
                "home",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
                
            # Lấy kích thước màn hình động
            width, height = self.get_screen_size(device_id)
            cx = width // 2
            swipe_x = int(width * 0.25)

            # Dạo trang chủ Shopee ở dải lề trái tránh chạm các ô Video ở giữa
            update_status("Dạo trang chủ Shopee...")
            for _ in range(random.randint(2, 3)):
                check_cancelled()
                y_start = int(height * 0.75) + random.randint(-50, 50)
                y_end = int(height * 0.3) + random.randint(-50, 50)
                self.swipe(device_id, swipe_x, y_start, swipe_x, y_end, duration=random.randint(600, 900))
                time.sleep(random.uniform(2.0, 3.0))
            
            check_cancelled()
            update_status("Bấm ô tìm kiếm...")
            if not self.ensure_shopee_search_box_click(
                device_id,
                status_callback=status_callback,
            ):
                raise RuntimeError("Không mở được ô tìm kiếm Shopee an toàn")
            time.sleep(1.0)
            self.tap(device_id, int(width * 0.45), int(height * 0.055))
            time.sleep(1.0)
            check_cancelled()
            
            # Xóa sạch và nhập đúng một từ khóa duy nhất qua XwIME.
            update_status(f"Xóa sạch & nhập một từ khóa '{keyword}'...")
            if not self.replace_shopee_search_text(device_id, keyword):
                raise RuntimeError("Không thể xóa và nhập từ khóa Shopee")
            time.sleep(1.5)
            check_cancelled()
            
            update_status("Gửi lệnh tìm kiếm...")
            self.submit_shopee_search(device_id)
            self.shopee_loading_delay(
                device_id,
                "results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()
            
            # Kiểm tra Captcha lần 2 sau khi bấm tìm kiếm
            if not self.check_and_bypass_captcha(device_id, max_retries=3, status_callback=status_callback):
                return False, "Bị chặn bởi Captcha (Không thể tự giải sau khi nhấn tìm kiếm)"
            
            # Vòng lặp cuộn màn hình và quét tìm địa chỉ Lâm Đồng
            for swipe_count in range(max_swipes):
                check_cancelled()
                # Kiểm tra Captcha lần 3 trong lúc cuộn trang
                if not self.check_and_bypass_captcha(device_id, max_retries=2, status_callback=status_callback):
                    return False, "Bị chặn bởi Captcha trong quá trình cuộn tìm kiếm"

                update_status(f"Quét màn hình lần {swipe_count + 1}...")
                
                # Chụp XML dump cấu trúc giao diện
                xml_file = f"/sdcard/dump_{device_id}.xml"
                self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
                
                check_cancelled()
                code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
                if code != 0:
                    update_status("Cảnh báo: Không thể dump giao diện, thử vuốt tiếp...")
                    self.swipe(device_id, cx, int(height * 0.75), cx, int(height * 0.28), duration=800)
                    time.sleep(2.0)
                    continue
                
                # Pull file XML về máy tính để phân tích
                local_xml = os.path.join(os.path.dirname(__file__), f"temp_dump_{device_id}.xml")
                code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
                
                check_cancelled()
                found_coords = None
                if os.path.exists(local_xml):
                    try:
                        tree = ET.parse(local_xml)
                        root = tree.getroot()
                        
                        # LOGIC CLICK SẢN PHẨM ĐẦU TIÊN (Nếu được bật và đang ở trang kết quả đầu tiên)
                        if click_first_item and swipe_count == 0:
                            update_status("[Chế độ Đầu tiên] Đang phân tích tìm bài đăng đầu tiên...")
                            best_elem = None
                            min_y = 99999
                            
                            # Chuẩn hóa từ khóa tìm kiếm (lấy các từ chính dài hơn 1 ký tự)
                            kw_clean = keyword.lower().strip()
                            kw_words = [w for w in kw_clean.split() if len(w) > 1]
                            if not kw_words:
                                kw_words = [kw_clean]
                                
                            # Bước 1: Quét tìm node có text chứa từ khóa tìm kiếm ở vùng trên (Y > 350)
                            for elem in root.iter():
                                text = elem.get('text', '').lower()
                                bounds = elem.get('bounds', '')
                                if not bounds:
                                    continue
                                    
                                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                if not m:
                                    continue
                                x1, y1, x2, y2 = map(int, m.groups())
                                
                                # Bỏ qua các thành phần thuộc thanh tìm kiếm/bộ lọc
                                if y1 < 350 or y1 > 1700:
                                    continue
                                    
                                if any(word in text for word in kw_words):
                                    if y1 < min_y:
                                        min_y = y1
                                        best_elem = elem
                                        
                            # Bước 2: Dự phòng nếu không khớp từ khóa (ví dụ video chỉ hiển thị text mô tả lạ)
                            if best_elem is None:
                                min_y = 99999
                                for elem in root.iter():
                                    text = elem.get('text', '')
                                    bounds = elem.get('bounds', '')
                                    if not bounds or len(text) < 12:
                                        continue
                                        
                                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                    if not m:
                                        continue
                                    x1, y1, x2, y2 = map(int, m.groups())
                                    
                                    # Lấy TextView có Y nhỏ nhất trong vùng chứa bài đăng đầu tiên
                                    if 350 < y1 < 1200:
                                        if y1 < min_y:
                                            min_y = y1
                                            best_elem = elem
                                            
                            if best_elem is not None:
                                bounds = best_elem.get('bounds', '')
                                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                if m:
                                    x1, y1, x2, y2 = map(int, m.groups())
                                    cx_elem = (x1 + x2) // 2
                                    cy_elem = (y1 + y2) // 2
                                    
                                    # Dịch lên trên tiêu đề 130px để chắc chắn click trúng hình ảnh/vùng card sản phẩm
                                    click_y = cy_elem - 130
                                    if click_y < 350:
                                        click_y = cy_elem
                                    found_coords = (cx_elem, click_y)
                                    update_status(f"[Chế độ Đầu tiên] Phát hiện bài đầu tiên '{best_elem.get('text')[:25]}...' tại ({cx_elem}, {cy_elem}).")
                                    
                        # LOGIC QUÉT LÂM ĐỒNG THƯỜNG (Nếu không bật click_first_item hoặc không tìm thấy bài đăng đầu tiên bằng dự phòng)
                        if not found_coords:
                            lamdong_candidates = (
                                self.extract_lamdong_product_candidates(root)
                            )
                            if lamdong_candidates:
                                found_coords = (
                                    self.choose_lamdong_product_candidate(
                                        lamdong_candidates
                                    )
                                )
                                update_status(
                                    f"Tìm thấy {len(lamdong_candidates)} sản phẩm "
                                    f"Lâm Đồng (tối đa 10) • chọn ngẫu nhiên: "
                                    f"({found_coords[0]}, {found_coords[1]})."
                                )
                    except Exception as e:
                        print(f"Loi phan tich XML tren may {device_id}: {e}")
                    finally:
                        try:
                            os.remove(local_xml)
                        except Exception:
                            pass
                
                if found_coords:
                    cx, cy = found_coords
                    click_y = max(0, cy - 120)
                    selected_product_coords = (cx, click_y)
                    update_status(f"Tìm thấy nhãn Lâm Đồng tại ({cx}, {cy}). Tiến hành click vào sản phẩm...")
                    self.tap(
                        device_id,
                        selected_product_coords[0],
                        selected_product_coords[1],
                    )
                    self.shopee_loading_delay(
                        device_id,
                        "product",
                        status_callback=status_callback,
                        is_cancelled=is_cancelled,
                    )
                    
                    # 1. Vuốt xem album ảnh sản phẩm (Swipe Image Carousel - 2-4 ảnh)
                    update_status("Vuốt xem album ảnh sản phẩm chi tiết...")
                    for _ in range(random.randint(2, 4)):
                        check_cancelled()
                        x_start = int(width * 0.85) + random.randint(-20, 20)
                        x_end = int(width * 0.15) + random.randint(-20, 20)
                        y_img = int(height * 0.25) + random.randint(-30, 30)
                        self.swipe(device_id, x_start, y_img, x_end, y_img, duration=random.randint(500, 700))
                        time.sleep(random.uniform(2.5, 4.0))

                    # 2. Vòng lặp cuộn xuống tìm "Xem Shop" từng bước nhỏ (Incremental Scrolling & đọc nội dung)
                    update_status("Đang cuộn tìm nút Xem Shop & đọc thông tin...")
                    shop_coords = None
                    # Ta cuộn tối đa 6 lần để tìm nút
                    for find_attempt in range(6):
                        check_cancelled()
                        # Quét tìm nút Xem Shop ở màn hình hiện tại với nhiều biến thể ngôn ngữ
                        for shop_btn_text in ["Xem Shop", "View Shop", "Ghé Shop", "Xem Cửa Hàng", "Visit Shop", "Visit Store"]:
                            shop_coords = self.find_element_coords_by_text(device_id, shop_btn_text)
                            if shop_coords:
                                break
                        if shop_coords:
                            break
                        
                        # Vuốt xuống một khoảng vừa phải (35% chiều cao màn hình) tránh bị trôi qua quá nhanh
                        y_start = int(height * 0.7) + random.randint(-30, 30)
                        y_end = int(height * 0.35) + random.randint(-30, 30)
                        self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(750, 1000))
                        
                        # Đợi ngẫu nhiên 3.5 đến 5.5 giây để đọc thông tin bài đăng tự nhiên
                        read_delay = random.uniform(3.5, 5.5)
                        temp_start = time.time()
                        while time.time() - temp_start < read_delay:
                            time.sleep(0.25)
                            check_cancelled()

                    # 3. Tương tác ngẫu nhiên (Thả tim hoặc Thêm giỏ hàng với tỷ lệ 15%)
                    if random.random() < 0.15:
                        check_cancelled()
                        update_status("Tương tác ngẫu nhiên (Bỏ giỏ hàng)...")
                        cart_coords = self.find_element_coords_by_text(device_id, "Thêm vào giỏ hàng")
                        if cart_coords:
                            self.tap(device_id, cart_coords[0], cart_coords[1])
                            time.sleep(3.0) # Đợi bảng chọn phân loại hiện lên
                            check_cancelled()
                            
                            # Click chọn một tùy chọn ngẫu nhiên ở vùng thuộc tính
                            self.tap(device_id, int(width * 0.3) + random.randint(-50, 50), int(height * 0.5) + random.randint(-50, 50))
                            time.sleep(1.5)
                            check_cancelled()
                            
                            # Nhấn Back để đóng bảng chọn
                            self.keyevent(device_id, 4)
                            time.sleep(2.0)

                    # 4. Vào dạo Shop kỹ lưỡng (30 - 45 giây)
                    if shop_coords:
                        update_status("Đang truy cập cửa hàng...")
                        self.tap(device_id, shop_coords[0], shop_coords[1])
                        self.shopee_loading_delay(
                            device_id,
                            "shop",
                            status_callback=status_callback,
                            is_cancelled=is_cancelled,
                        )
                        
                        # Dạo trang chủ Shop trong 30 - 45 giây
                        shop_duration = random.randint(30, 45)
                        shop_start = time.time()
                        update_status(f"Đang dạo trang chủ Shop trong {shop_duration} giây...")
                        while time.time() - shop_start < shop_duration:
                            check_cancelled()
                            y_start = int(height * 0.75) + random.randint(-40, 40)
                            y_end = int(height * 0.3) + random.randint(-40, 40)
                            self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                            
                            read_delay = random.uniform(3.5, 6.0)
                            temp_s = time.time()
                            while time.time() - temp_s < read_delay:
                                time.sleep(0.25)
                                check_cancelled()
                                
                        update_status(
                            "Hoàn thành dạo Shop • quay lại đúng sản phẩm đã chọn..."
                        )
                        if not self.return_to_shopee_product_after_shop(
                            device_id,
                            product_coords=selected_product_coords,
                            status_callback=status_callback,
                            is_cancelled=is_cancelled,
                        ):
                            return (
                                False,
                                "Không thể quay lại trang chi tiết sản phẩm sau khi dạo Shop",
                            )

                    # 5. Dạo xem thêm chi tiết sản phẩm & Đánh giá sau khi quay lại (30 - 45 giây)
                    view_duration = random.randint(30, 45)
                    start_time = time.time()
                    update_status(f"Tiếp tục lướt xem thông tin sản phẩm & Đánh giá trong {view_duration} giây...")
                    while time.time() - start_time < view_duration:
                        check_cancelled()
                        y_start = int(height * 0.7) + random.randint(-40, 40)
                        y_end = int(height * 0.35) + random.randint(-40, 40)
                        self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                        
                        read_delay = random.uniform(3.5, 6.0)
                        temp_start = time.time()
                        while time.time() - temp_start < read_delay:
                            time.sleep(0.25)
                            check_cancelled()
                            
                    update_status("Hoàn thành quy trình lướt xem sản phẩm!")
                    return True, "Thành công"
                
                # Nếu không tìm thấy, vuốt cuộn xuống dưới
                update_status("Chưa thấy Lâm Đồng, đang vuốt xuống dưới...")
                self.swipe_curved(device_id, cx, int(height * 0.75), cx, int(height * 0.28), duration=800)
                
                for _ in range(10):
                    time.sleep(0.25)
                    check_cancelled()
                
            if config.SHOPEE_SHOP_NAMES:
                update_status("Không tìm thấy shop Lâm Đồng trực tiếp. Chuyển sang tìm theo tên Shop dự phòng...")
                return self.shopee_fallback_by_shop_name(device_id, keyword, status_callback, is_cancelled)
            return False, f"Đã vuốt {max_swipes} lần nhưng không tìm thấy sản phẩm nào có nhãn Tỉnh Lâm Đồng."
        except Exception as e:
            msg = str(e)
            update_status(f"Thất bại: {msg}")
            return False, msg

    def find_and_click_view_shop(self, device_id, shop_name=""):
        xml_file = f"/sdcard/dump_view_shop_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        coords = None
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_view_shop_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                
                # 0. Nếu lỡ dính bảng "Bộ lọc tìm kiếm", bấm Back để đóng ngay
                for elem in root.iter():
                    text = elem.get('text', '')
                    if "Bộ lọc tìm kiếm" in text or "Thiết lập lại" in text:
                        print(f"[Device {device_id[:6]}] Phát hiện bảng Bộ lọc tìm kiếm đang mở -> Nhấn Back để đóng.")
                        self.keyevent(device_id, 4)
                        time.sleep(1.0)
                        break

                # 1. Các từ khóa ưu tiên tìm nút hoặc thẻ đại diện Shop
                keywords = [
                    "thêm kết quả", "them ket qua", "xem shop", "xem cửa hàng", 
                    "ghé shop", "view shop", "visit shop", "visit store", "khám phá"
                ]
                if shop_name:
                    keywords.append(shop_name.lower())
                    clean_sn = shop_name.replace(".", " ").replace("_", " ").lower()
                    keywords.append(clean_sn)
                
                for elem in root.iter():
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    val = (text or desc).strip()
                    if val and any(k in val.lower() for k in keywords):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            cy = (y1 + y2) // 2
                            cx = (x1 + x2) // 2
                            # Đảm bảo vị trí nằm dưới header tìm kiếm (y > 200) và không chạm vùng phễu lọc góc trên bên phải
                            if 200 < cy < 1600:
                                coords = (cx, cy)
                                print(f"[Device {device_id[:6]}] Tìm thấy nút/thẻ Shop '{val}' tại ({cx}, {cy}).")
                                break
            except Exception as e:
                print(f"[Device {device_id[:6]}] Lỗi phân tích XML Shop: {e}")
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        return coords

    def find_shop_search_box(self, device_id):
        xml_file = f"/sdcard/dump_shop_home_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        coords = None
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_shop_home_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                
                # 0. Nếu lỡ rớt vào trang "Chi tiết Shop", bấm Back 1 lần để quay ra trang Shop chính
                for elem in root.iter():
                    text = elem.get('text', '')
                    if "Chi tiết Shop" in text or "Tỉ lệ phản hồi" in text or "Mô tả Shop" in text:
                        print(f"[Device {device_id[:6]}] Phát hiện đang ở trang Chi tiết Shop -> Nhấn Back để thoát ra trang chính của Shop.")
                        self.keyevent(device_id, 4)
                        time.sleep(1.2)
                        break

                keywords = [
                    "tìm kiếm sản phẩm trong shop", "tìm trong shop", "tìm kiếm trong shop", 
                    "tìm ở cửa hàng", "tìm kiếm trong cửa hàng", "tìm sản phẩm", 
                    "search in shop", "search this shop", "search in store"
                ]
                for elem in root.iter():
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    res_id = elem.get('resource-id', '')
                    val = (text or desc or res_id).lower()
                    if val and any(k in val for k in keywords):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            cy = (y1 + y2) // 2
                            cx = (x1 + x2) // 2
                            # Ô tìm kiếm trong Shop luôn nằm ở vùng thanh tiêu đề đỉnh (y < 200)
                            if 30 < cy < 200:
                                coords = (cx, cy)
                                print(f"[Device {device_id[:6]}] Phát hiện ô tìm kiếm trong Shop tại ({cx}, {cy}).")
                                break
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        return coords

    def find_random_product_in_shop(self, device_id):
        """Chọn ngẫu nhiên một card sản phẩm đang hiển thị trong lưới Shop."""
        width, height = self.get_screen_size(device_id)
        grid_fallbacks = [
            (int(width * 0.25), int(height * 0.58)),
            (int(width * 0.75), int(height * 0.58)),
            (int(width * 0.25), int(height * 0.76)),
            (int(width * 0.75), int(height * 0.76)),
        ]
        safe_device_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', device_id)
        remote_xml = f"/sdcard/dump_shop_products_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_shop_products_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, dump_stdout, dump_stderr = self.execute_adb(
            device_id,
            ["shell", "uiautomator", "dump", remote_xml],
        )
        dump_message = f"{dump_stdout} {dump_stderr}".casefold()
        if "could not get idle state" in dump_message:
            return random.choice(grid_fallbacks)
        if dump_code != 0:
            return None

        pull_code, _, _ = self.execute_adb(
            device_id,
            ["pull", remote_xml, local_xml],
        )
        if pull_code != 0 or not os.path.exists(local_xml):
            return None

        candidates = []
        excluded_markers = (
            "shop_page_shop_tab",
            "shop_page_product_tab",
            "shop_page_category_tab",
            "category",
            "see-more",
            "back_to_top",
            "buttonactionbar",
            "search",
            "cart",
            "chat",
            "filter",
            "more",
        )
        try:
            root = ET.parse(local_xml).getroot()
            for elem in root.iter():
                if elem.get("clickable", "").lower() != "true":
                    continue

                marker_text = " ".join(
                    (
                        elem.get("resource-id", ""),
                        elem.get("content-desc", ""),
                        elem.get("text", ""),
                    )
                ).casefold()
                if any(marker in marker_text for marker in excluded_markers):
                    continue

                bounds = elem.get("bounds", "")
                match = re.match(
                    r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',
                    bounds,
                )
                if not match:
                    continue

                x1, y1, x2, y2 = map(int, match.groups())
                card_width = x2 - x1
                card_height = y2 - y1
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                if not (
                    int(width * 0.28) <= card_width <= int(width * 0.60)
                    and card_height >= int(height * 0.16)
                    and int(height * 0.22) < cy < int(height * 0.92)
                ):
                    continue
                candidates.append((cx, cy))
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

        if not candidates:
            return None
        return random.choice(candidates)

    def find_first_product_in_shop(self, device_id, keyword):
        xml_file = f"/sdcard/dump_shop_results_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        code, _, _ = self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        coords = None
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_shop_results_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                
                kw_words = [w for w in keyword.lower().split() if len(w) > 1]
                if not kw_words:
                    kw_words = [keyword.lower()]
                    
                best_elem = None
                min_y = 99999
                
                for elem in root.iter():
                    text = elem.get('text', '').lower()
                    bounds = elem.get('bounds', '')
                    if not bounds:
                        continue
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    
                    if y1 < 300 or y1 > 1700:
                        continue
                        
                    if any(w in text for w in kw_words):
                        if y1 < min_y:
                            min_y = y1
                            best_elem = elem
                            
                if best_elem is None:
                    min_y = 99999
                    for elem in root.iter():
                        text = elem.get('text', '')
                        bounds = elem.get('bounds', '')
                        if not bounds or len(text) < 8:
                            continue
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if not m:
                            continue
                        x1, y1, x2, y2 = map(int, m.groups())
                        if 300 < y1 < 1000:
                            if y1 < min_y:
                                min_y = y1
                                best_elem = elem
                                
                if best_elem is not None:
                    bounds = best_elem.get('bounds', '')
                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        click_y = y1 - 100
                        if click_y < 300:
                            click_y = (y1 + y2) // 2
                        coords = ((x1 + x2) // 2, click_y)
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        return coords

    def shopee_fallback_by_shop_name(self, device_id, keyword, status_callback=None, is_cancelled=None):
        """Kịch bản dự phòng: vào Shop theo tên, dạo Shop và mở ngẫu nhiên một sản phẩm."""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)
        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")

        if not config.SHOPEE_SHOP_NAMES:
            return False, "Không có danh sách shop để chạy dự phòng."

        shop_name = random.choice(config.SHOPEE_SHOP_NAMES)
        update_status(f"[Dự phòng] Bắt đầu tìm kiếm shop '{shop_name}'...")

        try:
            check_cancelled()
            # 1. Đưa về trang chủ
            self.ensure_shopee_homepage(device_id, status_callback=status_callback)
            self.bypass_shopee_popup(device_id)
            time.sleep(1.0)
            
            # 2. Bấm tìm kiếm trên trang chủ
            update_status("[Dự phòng] Bấm ô tìm kiếm để tìm shop...")
            if not self.ensure_shopee_search_box_click(
                device_id,
                status_callback=status_callback,
            ):
                raise RuntimeError(
                    "Không mở được ô tìm kiếm Shopee an toàn ở nhánh dự phòng"
                )
            time.sleep(1.5)
            check_cancelled()
            
            self.tap(device_id, SHOPEE_INPUT_BOX_COORDS[0], SHOPEE_INPUT_BOX_COORDS[1])
            time.sleep(1.0)
            check_cancelled()
            
            update_status(f"[Dự phòng] Nhập tên shop '{shop_name}'...")
            if not self.replace_shopee_search_text(device_id, shop_name):
                raise RuntimeError(
                    "Không thể xóa và nhập chính xác tên shop dự phòng"
                )
            time.sleep(1.5)
            check_cancelled()
            
            update_status("[Dự phòng] Gửi lệnh tìm kiếm shop...")
            self.submit_shopee_search(device_id)
            self.shopee_loading_delay(
                device_id,
                "results",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()

            # 3. Tìm nút "Xem Shop" / "Thêm kết quả >" / Thẻ đại diện Shop
            update_status(f"[Dự phòng] Tìm nút Thêm kết quả / Xem Shop cho '{shop_name}'...")
            view_shop_coords = self.find_and_click_view_shop(device_id, shop_name=shop_name)
            
            width, height = self.get_screen_size(device_id)
            if not view_shop_coords:
                # Tọa độ dự phòng chuẩn xác vào khu vực nút 'Thêm kết quả >' bên phải Card Shop (x=72% width, y=28% height)
                fallback_x = int(width * 0.72)
                fallback_y = int(height * 0.28)
                update_status(f"[Dự phòng] Click vùng nút 'Thêm kết quả' tại ({fallback_x}, {fallback_y})...")
                self.tap(device_id, fallback_x, fallback_y)
            else:
                update_status(f"[Dự phòng] Click nút/thẻ Shop tại {view_shop_coords}...")
                self.tap(device_id, view_shop_coords[0], view_shop_coords[1])
            
            self.shopee_loading_delay(
                device_id,
                "shop",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()

            # 4. Dạo trang Shop trước khi chọn sản phẩm.
            cx = width // 2
            shop_swipes = random.randint(2, 4)
            update_status(
                f"[Dự phòng] Đã vào Shop • dạo Shop {shop_swipes} lượt..."
            )
            for shop_index in range(shop_swipes):
                check_cancelled()
                read_delay = random.uniform(2.5, 4.5)
                update_status(
                    f"[Dự phòng] Xem Shop lượt "
                    f"{shop_index + 1}/{shop_swipes} ({read_delay:.1f}s)..."
                )
                time.sleep(read_delay)
                self.swipe_curved(
                    device_id,
                    cx,
                    int(height * 0.76) + random.randint(-35, 35),
                    cx,
                    int(height * 0.32) + random.randint(-35, 35),
                    duration=random.randint(700, 950),
                )

            # 5. Chọn ngẫu nhiên một card sản phẩm đang hiển thị.
            product_coords = None
            for attempt in range(4):
                check_cancelled()
                product_coords = self.find_random_product_in_shop(device_id)
                if product_coords:
                    break
                update_status(
                    f"[Dự phòng] Chưa thấy card sản phẩm • lướt thêm "
                    f"({attempt + 1}/4)..."
                )
                self.swipe_curved(
                    device_id,
                    cx,
                    int(height * 0.76),
                    cx,
                    int(height * 0.30),
                    duration=800,
                )
                time.sleep(2.0)

            if not product_coords:
                raise RuntimeError(
                    "Không nhận diện được card sản phẩm trong Shop dự phòng"
                )

            update_status(
                f"[Dự phòng] Chọn ngẫu nhiên sản phẩm tại {product_coords}..."
            )
            self.tap(device_id, product_coords[0], product_coords[1])
            self.shopee_loading_delay(
                device_id,
                "product",
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()

            # 6. Lướt album ảnh của sản phẩm.
            update_status("[Dự phòng] Vuốt xem album ảnh sản phẩm chi tiết...")
            for _ in range(random.randint(2, 4)):
                check_cancelled()
                x_start = int(width * 0.85) + random.randint(-20, 20)
                x_end = int(width * 0.15) + random.randint(-20, 20)
                y_img = int(height * 0.25) + random.randint(-30, 30)
                self.swipe(device_id, x_start, y_img, x_end, y_img, duration=random.randint(500, 700))
                time.sleep(random.uniform(2.5, 4.0))

            # 7. Lướt xem thông tin và đánh giá rồi kết thúc quy trình.
            detail_swipes = random.randint(4, 6)
            update_status(
                f"[Dự phòng] Lướt xem chi tiết & đánh giá "
                f"{detail_swipes} lượt..."
            )
            for detail_index in range(detail_swipes):
                check_cancelled()
                y_start = int(height * 0.7) + random.randint(-40, 40)
                y_end = int(height * 0.35) + random.randint(-40, 40)
                self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                read_delay = random.uniform(3.5, 6.0)
                update_status(
                    f"[Dự phòng] Đọc chi tiết lượt "
                    f"{detail_index + 1}/{detail_swipes} ({read_delay:.1f}s)..."
                )
                time.sleep(read_delay)

            update_status(
                "[Dự phòng] Hoàn thành xem sản phẩm ngẫu nhiên • kết thúc quy trình!"
            )
            return True, "Thành công (Dạo Shop và xem sản phẩm ngẫu nhiên)"
        except Exception as e:
            return False, f"Lỗi dự phòng: {str(e)}"

    # ================= AUTOMATION BƠM TIKTOK 3 BƯỚC =================
    def dismiss_tiktok_location_popup(self, device_id):
        """
        Tự động phát hiện và xử lý Bảng thông báo Quyền Truy Cập Vị Trí của Android/TikTok:
        1. Bấm checkbox "Không hỏi lại" (Don't ask again).
        2. Bấm nút "Từ chối" (Deny / Don't allow).
        """
        width, height = self.get_effective_screen_size(device_id)
        xml_file = f"/sdcard/dump_loc_popup_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_dump_loc_popup_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        found_popup = False
        dont_ask_coords = None
        deny_coords = None
        
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                
                # Kiểm tra xem có popup hỏi quyền vị trí không
                for elem in root.iter():
                    text = (elem.get('text', '') or elem.get('content-desc', '')).lower()
                    if any(k in text for k in ["vị trí", "location", "truy cập vào vị trí", "thiết bị này"]):
                        found_popup = True
                    
                    if any(k in text for k in ["không hỏi lại", "don't ask again", "remember choice"]):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            dont_ask_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

                    if any(k in text for k in ["từ chối", "deny", "don't allow"]):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            deny_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass

        if found_popup or dont_ask_coords or deny_coords:
            print(f"[Device {device_id[:6]}] Phát hiện Popup hỏi quyền Vị trí! Tiến hành Từ chối...")
            # 1. Bấm Không hỏi lại
            if not dont_ask_coords:
                dont_ask_coords = (int(width * 0.25), int(height * 0.54))
            self.tap(device_id, dont_ask_coords[0], dont_ask_coords[1])
            time.sleep(0.5)

            # 2. Bấm Từ chối
            if not deny_coords:
                deny_coords = (int(width * 0.58), int(height * 0.60))
            self.tap(device_id, deny_coords[0], deny_coords[1])
            time.sleep(1.0)
            return True
        return False

    def dismiss_tiktok_blocking_popup(self, device_id):
        """Close account/security prompts before TikTok Home automation."""
        if not self.is_tiktok_in_foreground(device_id):
            return False
        root = self._get_tiktok_ui_root(device_id, "tt_blocking_popup")
        if root is None:
            return False

        parent_map = {
            child: parent for parent in root.iter() for child in parent
        }
        popup_markers = (
            "them so dien thoai",
            "add phone number",
            "cap nhat so dien thoai",
            "update phone number",
            "bat thong bao",
            "turn on notifications",
            "dong bo danh ba",
            "sync contacts",
        )
        close_markers = {
            "close", "dong", "not now", "de sau", "later", "skip",
            "bo qua", "cancel", "huy",
        }
        popup_found = False
        close_coords = None
        for node in root.iter():
            label = self._normalize_facebook_text(
                f"{node.get('text', '')} {node.get('content-desc', '')}"
            )
            if (
                any(marker in label for marker in popup_markers)
                or (
                    "thoai" in label
                    and any(marker in label for marker in ("them", "cap nhat"))
                )
            ):
                popup_found = True
            if label not in close_markers:
                continue
            clickable = node
            while (
                clickable is not None
                and clickable.get("clickable", "false") != "true"
            ):
                clickable = parent_map.get(clickable)
            close_coords = self._element_center(
                clickable if clickable is not None else node
            )
            if close_coords:
                break

        if close_coords:
            self.tap(device_id, close_coords[0], close_coords[1])
        elif popup_found:
            self.keyevent(device_id, 4)
        else:
            return False
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        return True

    def launch_tiktok(self, device_id):
        """Mở ứng dụng TikTok (thử com.ss.android.ugc.trill trước, dự phòng com.zhiliaoapp.musically)"""
        self.lock_portrait(device_id, retries=3)
        code, stdout, stderr = self.execute_adb(device_id, ["shell", "monkey", "-p", config.TIKTOK_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"])
        if code != 0 or "Error" in stdout:
            self.execute_adb(device_id, ["shell", "monkey", "-p", config.TIKTOK_PACKAGE_ALT, "-c", "android.intent.category.LAUNCHER", "1"])
        # TikTok bật lại accelerometer_rotation khi Splash/Main activity đổi.
        self.lock_portrait(device_id, retries=3)
        time.sleep(1.0)
        self.lock_portrait(device_id, retries=3)
        time.sleep(2.5)
        self.lock_portrait(device_id, retries=3)
        # Tự động từ chối popup vị trí nếu hiển thị lúc mở app
        self.dismiss_tiktok_location_popup(device_id)
        self.dismiss_tiktok_blocking_popup(device_id)
        self.lock_portrait(device_id, retries=3)

    def get_tiktok_foreground_activity(self, device_id):
        """Return the focused TikTok activity even when UIAutomator is busy."""
        packages = (
            config.TIKTOK_PACKAGE.casefold(),
            config.TIKTOK_PACKAGE_ALT.casefold(),
        )
        for dumpsys_target in (
            ["shell", "dumpsys", "window", "windows"],
            ["shell", "dumpsys", "activity", "activities"],
        ):
            code, stdout, _ = self.execute_adb(device_id, dumpsys_target)
            if code != 0:
                continue
            for line in stdout.splitlines():
                folded = line.casefold()
                if not any(
                    marker in folded
                    for marker in (
                        "mcurrentfocus",
                        "mfocusedapp",
                        "mresumedactivity",
                    )
                ):
                    continue
                for package in packages:
                    match = re.search(
                        rf"{re.escape(package)}/([^\s}}]+)",
                        folded,
                    )
                    if match:
                        return match.group(1)
        return None

    def _get_tiktok_search_icon_coords(self, device_id):
        """Đọc tọa độ Search TikTok ở header; trả None nếu XML đang bận."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_tiktok_search_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_dump_tt_search_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            for elem in root.iter():
                desc = " ".join(
                    (
                        elem.get("content-desc", ""),
                        elem.get("text", ""),
                        elem.get("resource-id", ""),
                    )
                ).casefold()
                if not any(
                    marker in desc
                    for marker in (
                        "search", "tìm kiếm", "et_search",
                        "search_btn", "img_search",
                    )
                ):
                    continue
                match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    elem.get("bounds", ""),
                )
                if not match:
                    continue
                x1, y1, x2, y2 = map(int, match.groups())
                cy = (y1 + y2) // 2
                if cy < 300:
                    return (x1 + x2) // 2, cy
            return None
        except (OSError, ET.ParseError):
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def _recover_tiktok_search_with_one_back(self, device_id):
        """Back đúng một lần khỏi Search lỗi và giữ TikTok ở foreground."""
        if not self.is_tiktok_in_foreground(device_id):
            return False
        self.keyevent(device_id, 4)
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        if self.is_tiktok_in_foreground(device_id):
            return True
        self.launch_tiktok(device_id)
        time.sleep(1.2)
        self.lock_portrait(device_id, retries=3)
        return self.is_tiktok_in_foreground(device_id)

    def find_and_click_tiktok_search(self, device_id):
        """Mở Search; nếu kẹt Search cũ thì Back đúng một lần rồi mở lại."""
        for attempt in range(2):
            self.dismiss_tiktok_location_popup(device_id)

            # Trên trang kết quả, ưu tiên focus đúng EditText; không chạm nút
            # ba chấm/Filters ở góc phải.
            existing_input = self.get_tiktok_search_input_state(device_id)
            if existing_input is not None:
                if self.focus_tiktok_search_input(device_id):
                    return True

            activity = self.get_tiktok_foreground_activity(device_id)
            # Ảnh thực tế có thể đã ở đúng trang Search nhưng UIAutomator bị
            # nghẽn khi 40 máy dump đồng thời. SearchActivity là bằng chứng đủ
            # mạnh để focus trực tiếp ô trên cùng; không Back khỏi trang này.
            if activity and "search" in activity.casefold():
                if self.focus_tiktok_search_input(device_id):
                    return True
                coords = None
            else:
                coords = self._get_tiktok_search_icon_coords(device_id)
            if coords is None and activity and "search" not in activity.casefold():
                # UI dump video Android 8 có thể bận, nhưng dumpsys đã xác minh
                # đúng TikTok Home nên vùng kính lúp này là an toàn.
                width, height = self.get_effective_screen_size(device_id)
                coords = (int(width * 0.94), int(height * 0.065))

            if coords is not None:
                self.tap(device_id, coords[0], coords[1])
                time.sleep(1.2)
                if activity and "search" not in activity.casefold():
                    focused = self._focus_tiktok_search_input_provisionally(
                        device_id
                    )
                else:
                    focused = (
                        self.focus_tiktok_search_input(device_id)
                        or self._focus_tiktok_search_input_provisionally(
                            device_id
                        )
                    )
                if focused:
                    return True

            if attempt == 0:
                if not self._recover_tiktok_search_with_one_back(device_id):
                    return False
                continue
            return False
        return False

    def get_tiktok_search_input_state(self, device_id):
        """Đọc tọa độ, nội dung và trạng thái focus của ô Search TikTok."""
        safe_device_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', device_id)
        xml_file = f"/sdcard/dump_tt_input_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_dump_tt_input_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", xml_file]
        )
        if dump_code != 0:
            return None

        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        if pull_code != 0 or not os.path.exists(local_xml):
            return None

        candidates = []
        try:
            root = ET.parse(local_xml).getroot()
            for elem in root.iter():
                class_name = elem.get("class", "").lower()
                resource_id = elem.get("resource-id", "").lower()
                content_desc = elem.get("content-desc", "").lower()
                editable = elem.get("editable", "").lower() == "true"
                searchable = any(
                    marker in f"{resource_id} {content_desc}"
                    for marker in ("search", "et_search", "search_input")
                )
                if not (editable or "edittext" in class_name or searchable):
                    continue

                bounds = elem.get("bounds", "")
                match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                if not match:
                    continue

                x1, y1, x2, y2 = map(int, match.groups())
                cy = (y1 + y2) // 2
                if cy > 350:
                    continue

                focused = elem.get("focused", "").lower() == "true"
                score = (
                    int(focused) * 8
                    + int(editable) * 4
                    + int("edittext" in class_name) * 2
                    + int(searchable)
                )
                candidates.append(
                    {
                        "score": score,
                        "text": elem.get("text", ""),
                        "focused": focused,
                        "coords": ((x1 + x2) // 2, cy),
                    }
                )
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])

        if not candidates:
            return None
        best = max(candidates, key=lambda item: item["score"])
        best.pop("score", None)
        return best

    def focus_tiktok_search_input(self, device_id):
        """Focus EditText; dùng SearchActivity khi XML tạm bận dưới tải lớn."""
        width, height = self.get_effective_screen_size(device_id)
        state = self.get_tiktok_search_input_state(device_id)
        coords = state["coords"] if state else (
            int(width * 0.45),
            int(height * 0.055),
        )
        self.tap(device_id, coords[0], coords[1])
        if state is None:
            # SearchActivity + tap vào vùng EditText là fallback rẻ và ổn định
            # hơn việc phát thêm ba UI dump cho mỗi máy khi chạy đồng thời 40 máy.
            time.sleep(0.35)
            activity = self.get_tiktok_foreground_activity(device_id)
            if (
                self.is_tiktok_in_foreground(device_id)
                and activity
                and "search" in activity.casefold()
            ):
                return True
        for _ in range(3):
            time.sleep(0.5)
            verified = self.get_tiktok_search_input_state(device_id)
            if verified and verified["focused"]:
                return True
            if verified:
                self.tap(
                    device_id,
                    verified["coords"][0],
                    verified["coords"][1],
                )
        activity = self.get_tiktok_foreground_activity(device_id)
        return bool(
            self.is_tiktok_in_foreground(device_id)
            and activity
            and "search" in activity.casefold()
        )

    def _focus_tiktok_search_input_provisionally(self, device_id):
        """Focus vùng input khi TikTok dùng activity chung và XML đang bận.

        Chỉ dùng sau khi luồng đã chạm Search. Việc nhập vẫn bị khóa theo
        foreground và kết quả sau Enter vẫn phải được xác minh.
        """
        if not self.wait_for_tiktok_foreground(device_id):
            return False
        width, height = self.get_effective_screen_size(device_id)
        state = self.get_tiktok_search_input_state(device_id)
        coords = state["coords"] if state else (
            int(width * 0.45),
            int(height * 0.055),
        )
        self.tap(device_id, coords[0], coords[1])
        time.sleep(0.35)
        return self.wait_for_tiktok_foreground(device_id, checks=2, delay=0.25)

    def clear_tiktok_search_input(self, device_id):
        """
        BẮT BUỘC: Xóa sạch 100% toàn bộ từ khóa cũ trong ô tìm kiếm TikTok trước khi nhập từ khóa mới.
        """
        if not self.wait_for_tiktok_foreground(device_id):
            raise RuntimeError(
                "TikTok không còn ở foreground; đã chặn xóa từ khóa"
            )
        self.ensure_ime(device_id)
        for _ in range(2):
            activity = self.get_tiktok_foreground_activity(device_id)
            if activity and "search" not in activity.casefold():
                focused = self._focus_tiktok_search_input_provisionally(
                    device_id
                )
            else:
                focused = (
                    self.focus_tiktok_search_input(device_id)
                    or self._focus_tiktok_search_input_provisionally(device_id)
                )
            if not focused:
                continue

            # XwIME trên dàn Android 8 có action xóa chuyên dụng. Keyevent
            # Backspace (kể cả gửi từng phím) không tác động vào EditText TikTok.
            code, _, _ = self.execute_adb(
                device_id,
                [
                    "shell", "am", "broadcast",
                    "-a", "XW_CLEAR_TEXT",
                    "--receiver-foreground",
                ],
            )
            if code != 0:
                continue

            # TikTok có thể trả text cũ trong UI XML ngay sau CLEAR dù input
            # connection đã rỗng. Điều kiện pass chính xác là nội dung cuối
            # sau CLEAR + INPUT, được kiểm tra trong replace_tiktok_search_text.
            time.sleep(0.25)
            return True

        return False

    def input_tiktok_search_text(self, device_id, text):
        """Nhập đúng một lần qua XwIME mà không reset IME sau khi vừa xóa."""
        if not self.wait_for_tiktok_foreground(device_id):
            raise RuntimeError(
                "TikTok không còn ở foreground; đã chặn nhập từ khóa"
            )
        b64_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code, _, _ = self.execute_adb(
            device_id,
            [
                "shell", "am", "broadcast",
                "-a", "XW_INPUT_B64",
                "--es", "msg", b64_text,
                "--receiver-foreground",
            ],
        )
        return code == 0

    def replace_tiktok_search_text(self, device_id, text):
        """Xóa nội dung cũ, nhập đúng một lần và xác minh từ khóa mới."""
        if not self.wait_for_tiktok_foreground(device_id):
            raise RuntimeError(
                "TikTok không còn ở foreground; đã chặn nhập từ khóa"
            )
        for attempt in range(2):
            if not self.clear_tiktok_search_input(device_id):
                continue

            if not self.input_tiktok_search_text(device_id, text):
                continue
            time.sleep(0.5)
            state = self.get_tiktok_search_input_state(device_id)
            if (
                state is not None
                and self._normalize_tiktok_text(state["text"])
                == self._normalize_tiktok_text(text)
            ):
                return True

            # XwIME đã nhận CLEAR + INPUT và TikTok vẫn ở SearchActivity. Khi
            # XML tạm bận, cho phép gửi Enter; wait_for_tiktok_search_results
            # ngay sau đó vẫn bắt buộc xác minh đúng keyword/kết quả trước B3.
            if state is None:
                # Một số máy dùng Splash/MainActivity ngay cả khi Search mở.
                # CLEAR + INPUT chỉ được tin tạm khi TikTok còn foreground;
                # kết quả đúng keyword sau Enter vẫn là cổng xác minh cuối.
                if self.wait_for_tiktok_foreground(device_id):
                    return True

            print(
                f"[Device {device_id[:6]}] Nội dung Search chưa đúng "
                f"(lần {attempt + 1}/2), đang nhập lại..."
            )

        raise RuntimeError(
            f"Không thể nhập chính xác từ khóa TikTok: '{text}'"
        )

    def _normalize_tiktok_text(self, value):
        """Chuẩn hóa text TikTok, loại ký tự điều hướng RTL/LTR vô hình."""
        value = unicodedata.normalize("NFKC", value or "")
        value = "".join(ch for ch in value if unicodedata.category(ch) != "Cf")
        return re.sub(r"\s+", " ", value).strip().casefold()

    def is_tiktok_search_results_for(self, device_id, keyword):
        """Xác minh TikTok đã mở kết quả đúng từ khóa trước khi sang B3."""
        if not self.is_tiktok_in_foreground(device_id):
            return False
        root = self._get_tiktok_ui_root(device_id, "tt_search_results")
        if root is None:
            return False

        expected = self._normalize_tiktok_text(keyword)
        query_matches = False
        marker_hits = set()
        result_content_seen = False
        result_markers = {
            "top", "người dùng", "users", "people", "video", "videos",
            "ảnh", "photos", "cửa hàng", "shop", "shops",
        }
        parent_map = {
            child: parent
            for parent in root.iter()
            for child in parent
        }
        for elem in root.iter():
            class_name = elem.get("class", "").casefold()
            resource_id = elem.get("resource-id", "").casefold()
            text = self._normalize_tiktok_text(
                f"{elem.get('text', '')} {elem.get('content-desc', '')}"
            )
            bounds_match = re.match(
                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                elem.get("bounds", ""),
            )
            in_top_search_bar = bool(
                bounds_match
                and int(bounds_match.group(2)) < 180
                and int(bounds_match.group(4)) <= 320
                and (
                    "textview" in class_name
                    or elem.get("clickable", "").casefold() == "true"
                )
            )
            if (
                expected
                and expected in text
                and (
                    "edittext" in class_name
                    or "search" in resource_id
                    or in_top_search_bar
                )
            ):
                query_matches = True
            for marker in result_markers:
                if text == marker:
                    marker_hits.add(marker)

            if (
                text
                and text != expected
                and text not in result_markers
                and "edittext" not in class_name
                and len(text) >= 3
            ):
                bounds_node = elem
                match = None
                while bounds_node is not None and match is None:
                    match = re.match(
                        r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                        bounds_node.get("bounds", ""),
                    )
                    bounds_node = parent_map.get(bounds_node)
                if match and int(match.group(2)) >= 180:
                    result_content_seen = True

        return query_matches and (
            len(marker_hits) >= 2
            or (len(marker_hits) >= 1 and result_content_seen)
        )

    def wait_for_tiktok_search_results(self, device_id, keyword, checks=8):
        """Chờ UI kết quả đúng từ khóa; không coi keyevent thành công là đủ."""
        for attempt in range(max(1, checks)):
            if self.is_tiktok_search_results_for(device_id, keyword):
                return True
            if attempt < checks - 1:
                time.sleep(1.0)
        return False

    def _get_tiktok_ui_root(self, device_id, prefix="state"):
        """Dump UI TikTok và trả về XML root đã parse."""
        safe_device_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', device_id)
        remote_xml = f"/sdcard/{prefix}_{safe_device_id}.xml"
        local_xml = os.path.join(
            os.path.dirname(__file__),
            f"temp_{prefix}_{safe_device_id}.xml",
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            return None

        pull_code, _, _ = self.execute_adb(device_id, ["pull", remote_xml, local_xml])
        if pull_code != 0 or not os.path.exists(local_xml):
            return None

        try:
            return ET.parse(local_xml).getroot()
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def _element_center(self, elem):
        bounds = elem.get("bounds", "")
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if not match:
            return None
        x1, y1, x2, y2 = map(int, match.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2

    def get_tiktok_feed_signature(self, device_id):
        """Lấy dấu vân tay UI để biết thao tác vuốt đã đổi bài hay chưa."""
        root = self._get_tiktok_ui_root(device_id, "tt_feed_signature")
        if root is None:
            return None

        signature = []
        for elem in root.iter():
            coords = self._element_center(elem)
            if coords is None or coords[1] < 180:
                continue
            text = self._normalize_tiktok_text(elem.get("text", ""))
            desc = self._normalize_tiktok_text(elem.get("content-desc", ""))
            resource_id = elem.get("resource-id", "").lower()
            if text or desc:
                signature.append((resource_id, text, desc))
        return tuple(signature)

    def advance_tiktok_feed(self, device_id):
        """
        Vuốt sang bài tiếp theo và xác minh UI đã đổi.

        Bài ảnh/carousel có thể giữ cú vuốt chậm đầu tiên, vì vậy thử lại bằng
        cú fling nhanh và dài hơn ở vị trí ngang khác.
        """
        if not self.wait_for_tiktok_foreground(device_id):
            return False

        width, height = self.get_effective_screen_size(device_id)
        before = self.get_tiktok_feed_signature(device_id)
        gestures = [
            (0.50, 0.80, 0.50, 0.20, 450),
            (0.34, 0.86, 0.38, 0.14, 220),
            (0.66, 0.88, 0.62, 0.12, 160),
        ]

        for x1_ratio, y1_ratio, x2_ratio, y2_ratio, duration in gestures:
            self.lock_portrait(device_id, retries=3)
            if not self.wait_for_tiktok_foreground(device_id):
                return False
            swipe_result = self.swipe(
                device_id,
                int(width * x1_ratio),
                int(height * y1_ratio),
                int(width * x2_ratio),
                int(height * y2_ratio),
                duration=duration,
            )
            swipe_code = (
                swipe_result[0]
                if isinstance(swipe_result, tuple) and swipe_result
                else None
            )
            time.sleep(1.2)
            self.lock_portrait(device_id, retries=3)
            time.sleep(0.2)

            after = self.get_tiktok_feed_signature(device_id)
            if before is not None and after is not None and after != before:
                return True

            # Older Android versions can fail to dump the hierarchy while a
            # video is playing (uiautomator: "could not get idle state").
            # Home/For You is checked before this method, so a successful
            # gesture with TikTok still foreground is the safe fallback.
            if (
                swipe_code == 0
                and (before is None or after is None)
                and self.is_tiktok_in_foreground(device_id)
            ):
                return True

        return False

    def is_on_tiktok_target_profile(self, device_id, channel_name, root=None):
        """Xác minh đã rời trang Search và đang ở profile đúng kênh."""
        if root is None:
            root = self._get_tiktok_ui_root(device_id, "tt_profile_check")
        if root is None:
            return False

        target = self._normalize_tiktok_text(channel_name)
        has_target = False
        has_search_input = False
        has_search_results_marker = False
        has_profile_action = False
        video_nodes = 0

        for elem in root.iter():
            class_name = elem.get("class", "")
            text_values = {
                self._normalize_tiktok_text(elem.get("text", "")),
                self._normalize_tiktok_text(elem.get("content-desc", "")),
            }
            text_values.discard("")
            resource_id = elem.get("resource-id", "").lower()
            # Tên target phải xuất hiện như một trường danh tính hoàn chỉnh.
            # Không dùng phép "contains" vì caption/bio của kênh khác có thể
            # nhắc tên target và khiến tool xác minh nhầm profile.
            if target and target in text_values:
                has_target = True
            if "edittext" in class_name.lower():
                has_search_input = True
            if any(
                value in (
                    "top", "người dùng", "users", "cửa hàng", "shop",
                    "xem tất cả", "see all",
                )
                for value in text_values
            ):
                has_search_results_marker = True
            if any(
                value in (
                    "message",
                    "following",
                    "follow",
                    "nhắn tin",
                    "đang follow",
                    "đã follow",
                    "theo dõi",
                )
                for value in text_values
            ):
                has_profile_action = True
            if (
                "user_video_view" in resource_id
                or resource_id.endswith(":id/erf")
            ):
                video_nodes += 1

        return (
            has_target
            and not has_search_input
            and not has_search_results_marker
            and (has_profile_action or video_nodes >= 2)
        )

    def find_and_click_tiktok_channel(self, device_id, channel_name):
        """Click đúng card kênh, rồi xác minh đã vào profile mục tiêu."""
        target = self._normalize_tiktok_text(channel_name)
        screen_width, screen_height = self.get_effective_screen_size(device_id)
        search_bar_bottom = int(screen_height * 0.12)
        max_scan_attempts = 5

        for attempt in range(max_scan_attempts):
            root = self._get_tiktok_ui_root(device_id, f"tt_channel_{attempt}")
            if root is None:
                time.sleep(1.0)
                continue

            # Có máy đã nhận tap ở lần trước nhưng UI profile tải chậm hơn
            # nhịp xác minh. Nếu đúng profile đã mở thì hoàn tất ngay, không
            # tiếp tục tìm/tap lại trên giao diện profile.
            if self.is_on_tiktok_target_profile(
                device_id, channel_name, root=root
            ):
                return True

            parent_map = {child: parent for parent in root.iter() for child in parent}
            matches = []
            for elem in root.iter():
                class_name = elem.get("class", "").lower()
                resource_id = elem.get("resource-id", "").lower()
                if (
                    "edittext" in class_name
                    or "search_edit" in resource_id
                    or "search_input" in resource_id
                    or "search_src_text" in resource_id
                ):
                    continue

                text_values = {
                    self._normalize_tiktok_text(elem.get("text", "")),
                    self._normalize_tiktok_text(
                        elem.get("content-desc", "")
                    ),
                }
                text_values.discard("")
                exact_identity = target in text_values
                prefixed_identity = any(
                    value.startswith(target) for value in text_values
                )
                if not target or not (exact_identity or prefixed_identity):
                    continue

                clickable = elem
                while (
                    clickable is not None
                    and clickable.get("clickable", "").lower() != "true"
                ):
                    clickable = parent_map.get(clickable)
                target_elem = clickable if clickable is not None else elem
                target_class = target_elem.get("class", "").lower()
                target_resource_id = target_elem.get("resource-id", "").lower()
                coords = self._element_center(target_elem)
                identity_markers = (
                    "username", "user_name", "nickname", "profile",
                    "account", "author", "title",
                )
                has_identity_resource = any(
                    marker in resource_id or marker in target_resource_id
                    for marker in identity_markers
                )
                subtree_texts = {
                    self._normalize_tiktok_text(
                        f"{node.get('text', '')} "
                        f"{node.get('content-desc', '')}"
                    )
                    for node in target_elem.iter()
                }
                profile_row_cues = (
                    "follow", "following", "theo dõi", "đang follow",
                    "đã follow", "account", "tài khoản", "user",
                )
                has_profile_row_cue = any(
                    any(cue in value for cue in profile_row_cues)
                    for value in subtree_texts
                )
                bounds_match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    target_elem.get("bounds", ""),
                )
                compact_identity_card = bool(
                    bounds_match
                    and int(bounds_match.group(4))
                    - int(bounds_match.group(2)) <= 360
                )
                if (
                    coords
                    and coords[1] > search_bar_bottom
                    and "edittext" not in target_class
                    and "search" not in target_resource_id
                    and (has_identity_resource or compact_identity_card)
                    # Text gộp như "Tên, @handle, Follow" chỉ được nhận khi
                    # card có dấu hiệu hàng tài khoản. Nhờ vậy caption video
                    # của kênh khác dù nhắc tên target vẫn bị loại.
                    and (
                        exact_identity
                        or has_identity_resource
                        or has_profile_row_cue
                    )
                ):
                    score = 14 if has_identity_resource else 10
                    if has_profile_row_cue:
                        score += 3
                    matches.append((score, coords, target))

            if not matches:
                if attempt >= max_scan_attempts - 1:
                    break
                if not self.wait_for_tiktok_foreground(device_id):
                    return False
                # Một số tài khoản hiển thị Shopping/Video trước và đẩy hàng
                # Người dùng xuống dưới. Vuốt kết quả từng nhịp, rồi dump lại
                # để chỉ click khi đã đọc thấy đúng tên target.
                print(
                    f"[Device {device_id[:6]}] Chưa thấy Kênh target ở vùng "
                    f"hiện tại • cuộn kết quả tìm kiếm ({attempt + 1}/"
                    f"{max_scan_attempts - 1})..."
                )
                self.swipe(
                    device_id,
                    screen_width // 2,
                    int(screen_height * 0.78),
                    screen_width // 2,
                    int(screen_height * 0.32),
                    duration=650,
                )
                time.sleep(1.2)
                continue

            _, coords, matched_text = max(matches, key=lambda item: item[0])
            print(
                f"[Device {device_id[:6]}] Click card Kênh TikTok "
                f"'{matched_text[:40]}' tại {coords}."
            )
            self.tap(device_id, coords[0], coords[1])
            time.sleep(3.0)

            if self.is_on_tiktok_target_profile(device_id, channel_name):
                return True

        return False

    def click_random_tiktok_profile_video(self, device_id, channel_name):
        """Tìm một clip trên profile, kể cả khi phải cuộn mới thấy lưới."""
        width, height = self.get_effective_screen_size(device_id)
        max_scan_attempts = 5
        profile_confirmed = False
        for attempt in range(max_scan_attempts):
            root = self._get_tiktok_ui_root(device_id, f"tt_profile_videos_{attempt}")
            if root is None:
                time.sleep(0.8)
                continue
            if not profile_confirmed:
                profile_confirmed = self.is_on_tiktok_target_profile(
                    device_id, channel_name, root=root
                )
                if not profile_confirmed:
                    time.sleep(0.8)
                    continue

            candidates = []
            candidate_set = set()
            parent_map = {child: parent for parent in root.iter() for child in parent}

            # TikTok dùng resource-id khác nhau theo phiên bản/thiết bị:
            # S2: GridView hwz + item eti; S1: GridView hui + item erf.
            # Ưu tiên các item clickable trực tiếp trong GridView để không phụ
            # thuộc tên resource-id đã bị TikTok làm rối.
            for grid in root.iter():
                if not grid.get("class", "").lower().endswith("gridview"):
                    continue
                for item in list(grid):
                    if item.get("clickable", "").lower() != "true":
                        continue
                    coords = self._element_center(item)
                    if coords and 0 < coords[1] < height and coords not in candidate_set:
                        candidates.append(coords)
                        candidate_set.add(coords)

            for elem in root.iter():
                resource_id = elem.get("resource-id", "").lower()
                desc = self._normalize_tiktok_text(elem.get("content-desc", ""))
                is_known_video = (
                    "user_video_view" in resource_id
                    or resource_id.endswith(":id/eti")
                    or resource_id.endswith(":id/erf")
                    or resource_id.endswith(":id/cover")
                    or "video_tile" in resource_id
                    or "video_item" in resource_id
                    or desc.startswith("video by ")
                )
                if not is_known_video:
                    continue

                clickable = elem
                while (
                    clickable is not None
                    and clickable.get("clickable", "").lower() != "true"
                ):
                    clickable = parent_map.get(clickable)
                target_elem = clickable if clickable is not None else elem
                coords = self._element_center(target_elem)
                if (
                    coords
                    and int(height * 0.20) < coords[1] < height
                    and coords not in candidate_set
                ):
                    candidates.append(coords)
                    candidate_set.add(coords)

            if not candidates:
                if attempt >= max_scan_attempts - 1:
                    break
                if not self.wait_for_tiktok_foreground(device_id):
                    return False
                print(
                    f"[Device {device_id[:6]}] Profile đúng Kênh nhưng lưới "
                    f"clip chưa hiện • cuộn tìm clip ({attempt + 1}/"
                    f"{max_scan_attempts - 1})..."
                )
                self.swipe(
                    device_id,
                    width // 2,
                    int(height * 0.78),
                    width // 2,
                    int(height * 0.35),
                    duration=650,
                )
                time.sleep(1.2)
                continue

            coords = random.choice(candidates)
            self.tap(device_id, coords[0], coords[1])
            time.sleep(2.5)

            if self.is_tiktok_video_player(device_id):
                return True

            self.keyevent(device_id, 4)
            time.sleep(1.0)

        return False

    def is_tiktok_video_player(self, device_id):
        """Xác minh TikTok đã mở màn hình DetailActivity của một clip."""
        code, stdout, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "window", "windows"]
        )
        if code != 0:
            return False
        output = stdout.lower()
        return (
            "com.ss.android.ugc.trill" in output
            and (
                "detailactivity" in output
                or "aweme.detail" in output
                or "detail.ui" in output
            )
        )

    @serialized_device_workflow
    def tiktok_automation_workflow(self, device_id, seed_keywords=None, target_channel=None, min_delay=5, max_delay=10, status_callback=None, is_cancelled=None):
        """
        Quy trình TikTok cố định:
        B1 dạo For You 10-20 giây; B2 lướt kết quả 10-15 giây;
        B3 vào đúng profile, xem 3-5 phút và đổi clip mỗi 15-30 giây.
        min_delay/max_delay được giữ để tương thích lời gọi cũ nhưng không còn sử dụng.
        """
        def update_status(msg):
            print(f"[Device {device_id[:6]}] {msg}")
            if status_callback:
                status_callback(device_id, msg)

        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")

        if not seed_keywords:
            seed_keywords = [k.strip() for k in config.TIKTOK_SEED_KEYWORDS_DEFAULT.split(",") if k.strip()]
        elif isinstance(seed_keywords, str):
            seed_keywords = [k.strip() for k in seed_keywords.split(",") if k.strip()]

        if not target_channel:
            target_channel = config.TIKTOK_TARGET_CHANNEL_DEFAULT
        if isinstance(target_channel, str):
            target_channels = [
                channel.strip()
                for channel in target_channel.split(",")
                if channel.strip()
            ]
        else:
            target_channels = [
                str(channel).strip()
                for channel in target_channel
                if str(channel).strip()
            ]

        try:
            check_cancelled()
            if not target_channels:
                raise RuntimeError("Chưa nhập tên Kênh TikTok mục tiêu")
            target_channel = random.choice(target_channels)
            if len(target_channels) > 1:
                update_status(
                    f"[TikTok] Chọn ngẫu nhiên Kênh mục tiêu "
                    f"'{target_channel}' (1/{len(target_channels)} kênh)..."
                )
            width, height = self.get_effective_screen_size(device_id)
            cx = width // 2

            # Dam bao tat xoay man hinh
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "user_rotation", "0"])

            # Nuôi chéo Facebook trước khi bắt đầu nguyên luồng TikTok cũ.
            self.warmup_facebook_before_tiktok(
                device_id,
                status_callback=status_callback,
                is_cancelled=is_cancelled,
            )
            check_cancelled()

            # ================= BƯỚC 1: DẠO TRANG CHỦ TIKTOK =================
            update_status("[TikTok B1] Mở ứng dụng TikTok...")
            self.launch_tiktok(device_id)
            check_cancelled()
            if not self.ensure_tiktok_feed_motion(
                device_id, status_callback=status_callback
            ):
                raise RuntimeError(
                    "TikTok B1 không thể swipe Home sau khi Back/mở lại"
                )

            step1_total = random.randint(
                config.TIKTOK_STEP1_TOTAL_MIN,
                config.TIKTOK_STEP1_TOTAL_MAX,
            )
            update_status(
                f"[TikTok B1] Dạo Trang chủ trong {step1_total}s "
                f"(mặc định 10-20s)..."
            )
            step1_elapsed = 0
            step1_video = 1
            while step1_elapsed < step1_total:
                check_cancelled()
                dwell = min(
                    random.randint(5, 12),
                    step1_total - step1_elapsed,
                )
                update_status(
                    f"[TikTok B1] Xem bài {step1_video} ({dwell}s) • "
                    f"còn {step1_total - step1_elapsed}s..."
                )
                for _ in range(dwell):
                    time.sleep(1.0)
                    check_cancelled()
                step1_elapsed += dwell
                if step1_elapsed < step1_total:
                    if not self.ensure_tiktok_feed_motion(
                        device_id,
                        status_callback=status_callback,
                        home_ready=True,
                    ):
                        raise RuntimeError(
                            "TikTok B1 không thể phục hồi Feed bằng Back/mở lại"
                        )
                    step1_video += 1

            # ================= BƯỚC 2: TÌM TỪ KHÓA NHIỆM VỤ / MỒI KÊNH =================
            check_cancelled()
            seed_kw = random.choice(seed_keywords)
            update_status(f"[TikTok B2] Mở Kính lúp & Tìm từ khóa mồi '{seed_kw}'...")
            if not self.ensure_tiktok_foreground_ready(
                device_id, status_callback=status_callback
            ):
                raise RuntimeError(
                    "TikTok B2 không ở foreground; không mở ô tìm kiếm"
                )
            
            if not self.find_and_click_tiktok_search(device_id):
                raise RuntimeError(
                    "TikTok B2 không mở/focus được ô tìm kiếm từ khóa mồi"
                )
            check_cancelled()

            # Xóa nội dung cũ, nhập đúng từ khóa nhiệm vụ từ ô ent_tt_seed và xác minh.
            if not self.replace_tiktok_search_text(device_id, seed_kw):
                raise RuntimeError(
                    "TikTok B2 chưa nhập chính xác từ khóa mồi"
                )
            time.sleep(1.0)
            # TikTok hiện dùng Enter để gửi tìm kiếm. Không tap góc phải vì
            # vị trí đó là nút ba chấm và sẽ mở bảng Filters.
            if not self.submit_tiktok_search(device_id):
                raise RuntimeError(
                    "TikTok B2 chưa gửi được tìm kiếm từ khóa mồi"
                )
            time.sleep(3.5)
            check_cancelled()
            # Enter thành công là cổng hoàn tất B2. Không dump/chờ UI XML ở
            # đây: khi chạy nhiều máy, UIAutomator thường chậm dù kết quả đã
            # hiển thị, khiến code cũ nhập lại từ khóa mồi và dừng sai. Chỉ
            # kiểm tra đúng TikTok còn foreground trước khi bắt đầu swipe.
            if not self.wait_for_tiktok_foreground(device_id):
                raise RuntimeError(
                    "TikTok B2 mất foreground sau khi Enter từ khóa mồi"
                )
            seed_search_completed = True
            update_status(
                "[TikTok B2] Đã Enter từ khóa mồi • tiếp tục lướt kết quả, "
                "không nhập lại lần hai..."
            )

            step2_total = random.randint(
                config.TIKTOK_STEP2_TOTAL_MIN,
                config.TIKTOK_STEP2_TOTAL_MAX,
            )
            update_status(
                f"[TikTok B2] Lướt kết quả '{seed_kw}' trong {step2_total}s "
                f"(mặc định 10-15s)..."
            )
            step2_elapsed = 0
            result_index = 1
            while step2_elapsed < step2_total:
                check_cancelled()
                dwell = min(
                    random.randint(4, 8),
                    step2_total - step2_elapsed,
                )
                update_status(
                    f"[TikTok B2] Xem nhóm kết quả {result_index} ({dwell}s)..."
                )
                for _ in range(dwell):
                    time.sleep(1.0)
                    check_cancelled()
                step2_elapsed += dwell
                if step2_elapsed < step2_total:
                    if not self.wait_for_tiktok_foreground(device_id):
                        raise RuntimeError(
                            "TikTok B2 mất foreground; đã dừng trước khi swipe"
                        )
                    self.swipe(
                        device_id,
                        cx,
                        int(height * 0.75) + random.randint(-40, 40),
                        cx,
                        int(height * 0.30) + random.randint(-40, 40),
                        duration=random.randint(600, 900),
                    )
                    result_index += 1

            # ================= BƯỚC 3: TÌM & VÀO KÊNH MỤC TIÊU =================
            check_cancelled()
            if not seed_search_completed:
                raise RuntimeError(
                    "TikTok B2 chưa hoàn tất; đã chặn chuyển sang B3"
                )
            update_status(f"[TikTok B3] Bắt buộc XÓA SẠCH từ khóa mồi '{seed_kw}' & Tìm Kênh mục tiêu '{target_channel}'...")
            # Giữ nguyên trang kết quả B2. Hàm ensure_tiktok_foreground_ready
            # chủ động đưa TikTok về Home nên không dùng ở ranh giới B2 -> B3.
            if not self.wait_for_tiktok_foreground(device_id):
                raise RuntimeError(
                    "TikTok B3 không ở foreground; không thao tác tìm kiếm"
                )
            
            # 1. Bấm vào Kính lúp / Ô tìm kiếm ở đầu trang
            if not self.find_and_click_tiktok_search(device_id):
                raise RuntimeError(
                    "TikTok B3 không mở/focus được ô tìm kiếm trên kết quả B2"
                )
            check_cancelled()

            # 2-3. XÓA SẠCH từ khóa Bước 2 rồi mới nhập tên Kênh mục tiêu.
            if not self.replace_tiktok_search_text(device_id, target_channel):
                raise RuntimeError(
                    "TikTok B3 chưa xóa sạch từ khóa mồi hoặc chưa nhập đúng tên Kênh"
                )
            time.sleep(1.0)
            # Áp dụng cùng cơ chế cho bước 3: chỉ Enter, không chạm nút ba chấm.
            if not self.submit_tiktok_search(device_id):
                raise RuntimeError(
                    "TikTok B3 chưa gửi được tìm kiếm Kênh mục tiêu"
                )
            time.sleep(3.5)
            check_cancelled()

            # Click vào card kênh mục tiêu đã cấu hình.
            update_status(f"[TikTok B3] Click vào Kênh '{target_channel}'...")
            if not self.find_and_click_tiktok_channel(device_id, target_channel):
                raise RuntimeError(
                    f"Không mở được Kênh TikTok mục tiêu '{target_channel}'"
                )
            check_cancelled()

            update_status(
                "[TikTok B3] Đã xác minh đúng profile • mở ngẫu nhiên một clip..."
            )
            if not self.click_random_tiktok_profile_video(device_id, target_channel):
                raise RuntimeError(
                    f"Đã vào Kênh nhưng không mở được clip của '{target_channel}'"
                )
            check_cancelled()

            step3_total = random.randint(
                config.TIKTOK_STEP3_TOTAL_MIN,
                config.TIKTOK_STEP3_TOTAL_MAX,
            )
            update_status(
                f"[TikTok B3] Ở lại Kênh {step3_total // 60} phút "
                f"{step3_total % 60:02d} giây • đổi clip mỗi 15-30s..."
            )
            step3_elapsed = 0
            channel_video = 1
            while step3_elapsed < step3_total:
                check_cancelled()
                watch_duration = min(
                    random.randint(
                        config.TIKTOK_STEP3_VIDEO_MIN,
                        config.TIKTOK_STEP3_VIDEO_MAX,
                    ),
                    step3_total - step3_elapsed,
                )
                update_status(
                    f"[TikTok B3] Xem clip {channel_video} ({watch_duration}s) • "
                    f"đã ở Kênh {step3_elapsed}/{step3_total}s..."
                )
                for _ in range(watch_duration):
                    time.sleep(1.0)
                    check_cancelled()
                step3_elapsed += watch_duration
                if step3_elapsed < step3_total:
                    update_status(
                        f"[TikTok B3] Vuốt sang clip ngẫu nhiên tiếp theo "
                        f"(còn {step3_total - step3_elapsed}s)..."
                    )
                    if not self.wait_for_tiktok_foreground(device_id):
                        raise RuntimeError(
                            "TikTok B3 mất foreground; đã dừng trước khi đổi clip"
                        )
                    self.swipe(
                        device_id,
                        cx,
                        int(height * 0.80) + random.randint(-25, 25),
                        cx,
                        int(height * 0.25) + random.randint(-25, 25),
                        duration=random.randint(450, 700),
                    )
                    channel_video += 1

            update_status("Hoàn thành tác vụ Bơm TikTok!")
            return True, "Thành công"

        except Exception as e:
            msg = str(e)
            update_status(f"Lỗi TikTok: {msg}")
            return False, msg

# Chạy thử nghiệm trực tiếp nếu chạy độc lập file này
if __name__ == "__main__":
    controller = ADBController()
    devices = controller.get_devices()
    print(f"Tim thay {len(devices)} thiet bi:")
    for idx, d in enumerate(devices):
        print(f"  [{idx + 1}] {d}")
        
    if devices:
        test_device = devices[0]
        print(f"\nChay thu nghiem tren thiet bi dau tien ({test_device}):")
        # Thu dam bao bat IME
        controller.ensure_ime(test_device)
        print("IME da duoc cau hinh thanh cong!")

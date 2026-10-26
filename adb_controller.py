import sys
import gc
import ctypes
import tempfile
import subprocess
import base64
import time
import os
import xml.etree.ElementTree as ET
import re
import random
import unicodedata
import threading
import socket
from contextlib import contextmanager
from functools import wraps
import config
from concurrent.futures import ThreadPoolExecutor
from config import ADB_PATH
import hashlib
import interaction_tracker
import ui_automator_dom

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class WorkflowCancelledException(BaseException):
    """Ngoại lệ dừng khẩn cấp kế thừa BaseException để không bị nuốt bởi except Exception:"""
    pass


def _handle_workflow_exception(args):
    if issubclass(args.exc_type, WorkflowCancelledException):
        return
    if hasattr(threading, "__default_excepthook__"):
        threading.__default_excepthook__(args)
    elif hasattr(sys, "__excepthook__"):
        sys.__excepthook__(args.exc_type, args.exc_value, args.exc_traceback)


if hasattr(threading, "excepthook"):
    threading.excepthook = _handle_workflow_exception


def serialized_device_workflow(method):
    """Prevent two platform workflows from controlling one phone concurrently."""
    @wraps(method)
    def wrapper(self, device_id, *args, **kwargs):
        with self.device_workflow_scope(device_id):
            return method(self, device_id, *args, **kwargs)

    wrapper._serialized_device_workflow = True
    return wrapper

DEFAULT_ADB_PORTS = (5037, 5038)


class ADBController:
    def __init__(
        self,
        adb_path=ADB_PATH,
        max_parallel_commands=32,
        portrait_cache_seconds=5.0,
    ):
        self._adb_path = (
            config.resolve_adb_path(adb_path)
            if hasattr(config, "resolve_adb_path")
            else adb_path
        )
        self.max_parallel_commands = max(
            1, min(64, int(max_parallel_commands))
        )
        self._adb_command_slots = threading.BoundedSemaphore(
            self.max_parallel_commands
        )
        self._use_socket_transport = True
        self._server_checked = False
        self._server_check_lock = threading.Lock()
        adb_ports = getattr(config, "ADB_PORTS", DEFAULT_ADB_PORTS)
        self._adb_ports = list(adb_ports) if adb_ports else list(DEFAULT_ADB_PORTS)
        self._device_ports = {}
        self._device_ports_lock = threading.Lock()
        self._server_checked_ports = set()
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
        self._recent_tiktok_target_taps = {}
        self._emergency_stopped = False
        self._emergency_stop_lock = threading.Lock()
        self._cleanup_local = threading.local()

    @contextmanager
    def emergency_cleanup_scope(self):
        self._cleanup_local.active = True
        try:
            yield
        finally:
            self._cleanup_local.active = False

    def is_emergency_stopped(self):
        with self._emergency_stop_lock:
            return getattr(self, "_emergency_stopped", False)

    def set_emergency_stopped(self, state=True):
        with self._emergency_stop_lock:
            self._emergency_stopped = bool(state)

    def interruptible_sleep(self, seconds, check_cancelled=None, step=0.05):
        """Ngủ ngắt được ngay lập tức nếu có lệnh dừng khẩn cấp hoặc hủy."""
        if seconds <= 0:
            return
        deadline = time.monotonic() + float(seconds)
        while True:
            if self.is_emergency_stopped():
                raise WorkflowCancelledException("EMERGENCY_STOP_ACTIVE: Dừng khẩn cấp ngắt thời gian chờ")
            if check_cancelled and check_cancelled():
                raise WorkflowCancelledException("CANCELLED: Tác vụ đã bị hủy")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(step, remaining))

    def get_device_port(self, device_id):
        """Lấy port ADB tương ứng của thiết bị (mặc định 5037 nếu chưa nhận diện)."""
        if not device_id:
            return self._adb_ports[0] if self._adb_ports else 5037
        with self._device_ports_lock:
            return self._device_ports.get(device_id, self._adb_ports[0] if self._adb_ports else 5037)

    def set_device_port(self, device_id, port):
        """Cập nhật port ADB cho thiết bị."""
        if device_id and port:
            with self._device_ports_lock:
                self._device_ports[device_id] = int(port)

    @property
    def adb_path(self):
        if hasattr(config, "resolve_adb_path"):
            return config.resolve_adb_path(self._adb_path)
        return self._adb_path

    @adb_path.setter
    def adb_path(self, value):
        self._adb_path = (
            config.resolve_adb_path(value)
            if hasattr(config, "resolve_adb_path")
            else value
        )

    @contextmanager
    def device_workflow_scope(self, device_id, timeout=30.0, is_cancelled=None):
        """Grant exclusive in-process control of a device to one workflow.

        Bảo vệ tranh chấp giữa các luồng/workflow, có timeout và kiểm tra cờ hủy
        để chống deadlock khi thiết bị bị khóa hoặc bị hủy ngang.
        """
        with self._device_workflow_locks_guard:
            if not hasattr(self, "_device_workflow_locks"):
                self._device_workflow_locks = {}
            lock = self._device_workflow_locks.setdefault(
                device_id, threading.RLock()
            )

        start_time = time.time()
        acquired = False
        while not acquired:
            if is_cancelled and is_cancelled():
                raise TimeoutError(f"Tác vụ bị hủy trong khi chờ khóa thiết bị {device_id}")
            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Hết thời gian chờ ({timeout}s) để lấy khóa thiết bị {device_id}")
            acquired = lock.acquire(timeout=0.2)

        try:
            with self._device_workflow_locks_guard:
                self._active_device_workflows[device_id] = (
                    self._active_device_workflows.get(device_id, 0) + 1
                )
            yield
        finally:
            try:
                with self._device_workflow_locks_guard:
                    remaining = (
                        self._active_device_workflows.get(device_id, 1) - 1
                    )
                    if remaining > 0:
                        self._active_device_workflows[device_id] = remaining
                    else:
                        self._active_device_workflows.pop(device_id, None)
            finally:
                lock.release()

    def is_device_workflow_active(self, device_id):
        """Cho tác vụ nền biết thiết bị đang được một workflow điều khiển."""
        with self._device_workflow_locks_guard:
            return self._active_device_workflows.get(device_id, 0) > 0

    def _run_cmd(self, cmd_args, timeout=15, port=None):
        """Chạy lệnh hệ thống với ADB"""
        if port is not None and not (cmd_args and cmd_args[0] == "-P"):
            full_cmd = [self.adb_path, "-P", str(port)] + cmd_args
        else:
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

    def _ensure_adb_server(self, port=None):
        """Khởi động daemon ADB Server trên cổng chỉ định nếu chưa chạy."""
        ports = [port] if port is not None else list(self._adb_ports)
        for p in ports:
            with self._server_check_lock:
                if p in self._server_checked_ports:
                    continue
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)
                try:
                    s.connect(("127.0.0.1", p))
                    s.close()
                    self._server_checked_ports.add(p)
                    self._server_checked = True
                    continue
                except Exception:
                    pass

                startupinfo = None
                creationflags = 0
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

                try:
                    subprocess.Popen(
                        [self.adb_path, "-P", str(p), "nodaemon", "server"],
                        startupinfo=startupinfo,
                        creationflags=creationflags,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(0.4)
                    self._server_checked_ports.add(p)
                    self._server_checked = True
                except Exception:
                    pass

    def _execute_adb_socket(self, device_id, shell_args, timeout=15):
        """Thực thi lệnh shell ADB trực tiếp qua TCP Socket port tương ứng (5037/5038).
        Loại bỏ overhead tạo process của subprocess.run (giảm độ trễ từ 40ms xuống 1-3ms).
        Trả về (returncode, stdout, stderr) hoặc None nếu cần fallback về subprocess.
        """
        if not device_id or not shell_args:
            return None

        # Định dạng chuỗi lệnh shell
        if len(shell_args) == 1:
            shell_cmd_str = str(shell_args[0])
        elif len(shell_args) == 3 and shell_args[0] == "sh" and shell_args[1] == "-c":
            shell_cmd_str = str(shell_args[2])
        else:
            shell_cmd_str = " ".join(str(a) for a in shell_args)

        primary_port = self.get_device_port(device_id)
        candidate_ports = [primary_port] + [p for p in self._adb_ports if p != primary_port]

        for port in candidate_ports:
            self._ensure_adb_server(port)

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(max(1.0, float(timeout)))
            try:
                s.connect(("127.0.0.1", port))

                # 1. Chuyển context transport sang thiết bị mục tiêu
                transport_req = f"host:transport:{device_id}".encode("utf-8")
                s.sendall(f"{len(transport_req):04x}".encode("ascii") + transport_req)
                status = s.recv(4)
                if status != b"OKAY":
                    s.close()
                    continue

                if port != primary_port:
                    self.set_device_port(device_id, port)

                # 2. Gửi lệnh shell
                cmd_payload = f"shell:{shell_cmd_str}".encode("utf-8")
                s.sendall(f"{len(cmd_payload):04x}".encode("ascii") + cmd_payload)
                cmd_status = s.recv(4)
                if cmd_status != b"OKAY":
                    s.close()
                    return None

                # 3. Đọc dữ liệu stream từ socket
                chunks = []
                timed_out = False
                while True:
                    try:
                        chunk = s.recv(8192)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    except socket.timeout:
                        timed_out = True
                        break
                    except BlockingIOError:
                        break

                raw_bytes = b"".join(chunks)
                stdout = (
                    raw_bytes.decode("utf-8", errors="ignore")
                    .replace("\r\r\n", "\n")
                    .replace("\r\n", "\n")
                    .strip()
                )
                if timed_out:
                    return -1, stdout, "Command timed out"
                return 0, stdout, ""
            except socket.timeout:
                return -1, "", "Command timed out"
            except Exception:
                pass
            finally:
                try:
                    s.close()
                except Exception:
                    pass

        return None

    def execute_adb(self, device_id, cmd_args, timeout=15, **kwargs):
        """Thực thi lệnh ADB trên một thiết bị cụ thể"""
        if getattr(self, "_emergency_stopped", False):
            bypass_emergency = kwargs.get("bypass_emergency", False) or getattr(self._cleanup_local, "active", False)
            is_safe_cleanup_key = (
                cmd_args
                and len(cmd_args) >= 4
                and cmd_args[0] == "shell"
                and cmd_args[1] == "input"
                and cmd_args[2] == "keyevent"
                and str(cmd_args[3]) in ("3", "187")
            )
            if not bypass_emergency and not is_safe_cleanup_key:
                raise WorkflowCancelledException("EMERGENCY_STOP_ACTIVE: Dừng khẩn cấp đang kích hoạt")
        # Thử thực thi siêu tốc qua TCP Socket nếu là lệnh shell trên thiết bị cụ thể
        if (
            device_id
            and cmd_args
            and cmd_args[0] == "shell"
            and getattr(self, "_use_socket_transport", True)
        ):
            res = self._execute_adb_socket(device_id, cmd_args[1:], timeout)
            if res is not None:
                return res

        # Fallback an toàn tuyệt đối về subprocess.run chuẩn
        port = self.get_device_port(device_id) if device_id else None
        if device_id:
            device_args = ["-s", device_id] + cmd_args
        else:
            device_args = cmd_args

        res = self._run_cmd(device_args, timeout, port=port)
        if (
            device_id
            and res[0] != 0
            and len(self._adb_ports) > 1
            and any(err_msg in res[2].lower() for err_msg in ("device not found", "error: device", "cannot connect"))
        ):
            for alt_port in self._adb_ports:
                if alt_port != port:
                    alt_res = self._run_cmd(device_args, timeout, port=alt_port)
                    if alt_res[0] == 0:
                        self.set_device_port(device_id, alt_port)
                        return alt_res
        return res

    def _get_portrait_device_lock(self, device_id):
        with self._portrait_state_guard:
            return self._portrait_device_locks.setdefault(
                device_id, threading.RLock()
            )

    def is_screen_landscape(self, device_id):
        """Kiểm tra màn hình thiết bị có đang bị xoay ngang (Landscape) hay không."""
        code, output, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "window", "displays"]
        )
        if code == 0 and output:
            cur_match = re.search(r"cur=(\d+)x(\d+)", output)
            if cur_match:
                w, h = int(cur_match.group(1)), int(cur_match.group(2))
                if w > h:
                    return True
            rot_match = re.search(r"mRotation=([0-3])", output)
            if rot_match and rot_match.group(1) in ("1", "3"):
                return True

        code_in, out_in, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "input"]
        )
        if code_in == 0 and out_in:
            orient_match = re.search(r"SurfaceOrientation:\s*([0-3])", out_in)
            if orient_match and orient_match.group(1) in ("1", "3"):
                return True
        return False

    def _read_portrait_lock_state(self, device_id):
        state_script = (
            "printf 'ACCELEROMETER_ROTATION='; "
            "settings get system accelerometer_rotation; "
            "printf 'USER_ROTATION='; "
            "settings get system user_rotation; "
            "dumpsys window displays | grep -E 'mRotation|cur=' | head -n 3 || true; "
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
        win_rot = re.search(r"m(?:Current)?Rotation=(?:ROTATION_)?([0-3])", output)
        cur_match = re.search(r"cur=(\d+)x(\d+)", output)
        if not accelerometer or not user_rotation:
            return None
        acc_ok = accelerometer.group(1) == "0"
        user_ok = user_rotation.group(1) == "0"
        orient_ok = orientation is None or orientation.group(1) == "0"
        win_ok = win_rot is None or win_rot.group(1) == "0"
        cur_ok = True
        if cur_match:
            cur_ok = int(cur_match.group(1)) <= int(cur_match.group(2))
        return acc_ok and user_ok and orient_ok and win_ok and cur_ok

    def lock_portrait(self, device_id, retries=2, force=False):
        """Khóa cứng màn hình dọc (Portrait), vô hiệu hóa hoàn toàn tự động xoay."""
        device_lock = self._get_portrait_device_lock(device_id)
        with device_lock:
            now = time.monotonic()
            with self._portrait_state_guard:
                confirmed_at = self._portrait_confirmed_at.get(device_id)

            if (
                not force
                and confirmed_at is not None
                and now - confirmed_at < min(5.0, self._portrait_cache_seconds)
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
                "settings put system hide_rotation_lock_toggle_for_accessibility 0 2>/dev/null || true; "
                "settings put system lock_screen_allow_rotation 0 2>/dev/null || true; "
                "settings put system call_auto_rotation 0 2>/dev/null || true; "
                "content insert --uri content://settings/system "
                "--bind name:s:accelerometer_rotation --bind value:i:0 2>/dev/null || true; "
                "content insert --uri content://settings/system "
                "--bind name:s:user_rotation --bind value:i:0 2>/dev/null || true; "
                "cmd window set-user-rotation lock 0 2>/dev/null || wm set-user-rotation lock 0 2>/dev/null || wm user-rotation lock 0 2>/dev/null || true; "
                "cmd window set-fixed-to-user-rotation enabled 2>/dev/null || cmd window set-ignore-orientation-request true 2>/dev/null || true"
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
                if state is False:
                    # Nếu màn hình vẫn bị xoay do video/activity xoay ngang, gửi phím Back / Escape
                    self.keyevent(device_id, 4)
                    time.sleep(0.3)
                    self.execute_adb(device_id, ["shell", "sh", "-c", apply_script])
                if attempt < attempts - 1:
                    time.sleep(0.1)
            return applied

    def get_devices(self):
        """Lấy danh sách các thiết bị đang kết nối từ tất cả các cổng ADB (5037, 5038...)"""
        devices = []
        for port in self._adb_ports:
            code, stdout, stderr = self._run_cmd(["devices"], port=port)
            if code != 0:
                continue
            lines = stdout.splitlines()
            for line in lines[1:]: # Bỏ qua dòng đầu "List of devices attached"
                line_str = line.strip()
                if not line_str:
                    continue
                parts = line_str.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    self.set_device_port(serial, port)
                    if serial not in devices:
                        devices.append(serial)
        return devices

    def get_devices_status_detail(self):
        """Quét và phân loại chi tiết trạng thái của toàn bộ thiết bị trên các cổng ADB:
        online (device), offline, unauthorized, other.
        """
        status_map = {
            "online": [],
            "offline": [],
            "unauthorized": [],
            "other": [],
        }
        seen = set()

        for port in self._adb_ports:
            code, stdout, stderr = self._run_cmd(["devices"], port=port)
            if code != 0:
                continue
            lines = stdout.splitlines()
            for line in lines[1:]:
                line_str = line.strip()
                if not line_str:
                    continue
                parts = line_str.split()
                if len(parts) >= 2:
                    serial = parts[0]
                    st = parts[1].lower()
                    self.set_device_port(serial, port)
                    if serial in seen:
                        continue
                    seen.add(serial)
                    if st == "device":
                        status_map["online"].append(serial)
                    elif st == "offline":
                        status_map["offline"].append(serial)
                    elif st == "unauthorized":
                        status_map["unauthorized"].append(serial)
                    else:
                        status_map["other"].append((serial, st))
        return status_map

    def get_memory_status(self):
        """Đọc dung lượng RAM của tiến trình hiện tại (MB) và RAM trống hệ thống (GB)."""
        proc_mb = 0.0
        free_gb = 0.0
        total_gb = 0.0
        if os.name == "nt":
            try:
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    free_gb = stat.ullAvailPhys / (1024 ** 3)
                    total_gb = stat.ullTotalPhys / (1024 ** 3)

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]
                pmc = PROCESS_MEMORY_COUNTERS()
                pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                k32 = ctypes.windll.kernel32
                k32.GetCurrentProcess.restype = ctypes.c_void_p
                h_proc = k32.GetCurrentProcess()
                fn = getattr(k32, "K32GetProcessMemoryInfo", ctypes.windll.psapi.GetProcessMemoryInfo)
                fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), ctypes.c_ulong]
                fn.restype = ctypes.c_int
                if fn(h_proc, ctypes.byref(pmc), pmc.cb):
                    proc_mb = pmc.WorkingSetSize / (1024 ** 2)
            except Exception:
                pass
        return round(proc_mb, 1), round(free_gb, 2), round(total_gb, 1)

    def cleanup_system_resources(self, deep=False, max_file_age_sec=90):
        """Tự động dọn dẹp file tạm XML/PNG, thu hồi bộ nhớ phân mảnh và giải phóng WorkingSet RAM."""
        before_mb, _, _ = self.get_memory_status()
        files_removed = 0
        now = time.time()
        age_limit = 0 if deep else max(10, int(max_file_age_sec))

        # 1. Dọn file tạm XML/PNG trên PC (%TEMP%, thư mục temp/, thư mục gốc)
        candidate_dirs = [
            tempfile.gettempdir(),
            os.path.join(os.path.dirname(__file__), "temp"),
            os.path.dirname(__file__),
        ]
        temp_prefixes = (
            "temp_fb_",
            "temp_facebook_",
            "temp_recents_",
            "temp_dump_",
            "temp_state_",
            "temp_check_",
            "temp_view_",
            "temp_shop_",
            "temp_shopee_",
            "screenshot_",
        )
        for folder in candidate_dirs:
            if not folder or not os.path.isdir(folder):
                continue
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if not entry.is_file():
                            continue
                        name_lower = entry.name.lower()
                        if not (name_lower.endswith(".xml") or name_lower.endswith(".png")):
                            continue
                        if not any(name_lower.startswith(p) for p in temp_prefixes):
                            continue
                        try:
                            if age_limit > 0 and (now - entry.stat().st_mtime) < age_limit:
                                continue
                            os.remove(entry.path)
                            files_removed += 1
                        except OSError:
                            pass
            except OSError:
                pass

        # 2. Thu gọn các bộ nhớ đệm nội bộ để không phình to sau 24h
        try:
            if hasattr(self, "_recent_tiktok_target_taps") and isinstance(self._recent_tiktok_target_taps, dict):
                if len(self._recent_tiktok_target_taps) > 80:
                    self._recent_tiktok_target_taps.clear()
            with self._screen_size_cache_guard:
                if len(self._screen_size_cache) > 120:
                    self._screen_size_cache.clear()
        except Exception:
            pass

        # 3. Dọn file dump tồn đọng trên /sdcard/ của các máy đang rảnh (nếu deep=True)
        if deep:
            try:
                devices = self.get_devices()
                for dev_id in devices:
                    if not self.is_device_workflow_active(dev_id):
                        self.execute_adb(
                            dev_id,
                            ["shell", "rm -f /sdcard/dump_*.xml /sdcard/fb_*.xml /sdcard/state_*.xml /sdcard/screen_*.png >/dev/null 2>&1 || true"],
                            timeout=3,
                        )
            except Exception:
                pass

        # 4. Chạy Python Garbage Collector + ép Windows thu hồi WorkingSet RAM
        try:
            gc.collect()
            if os.name == "nt":
                k32 = ctypes.windll.kernel32
                k32.GetCurrentProcess.restype = ctypes.c_void_p
                h_proc = k32.GetCurrentProcess()
                k32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
                k32.SetProcessWorkingSetSize(
                    h_proc, ctypes.c_size_t(-1), ctypes.c_size_t(-1)
                )
                try:
                    ctypes.windll.psapi.EmptyWorkingSet(h_proc)
                except Exception:
                    pass
        except Exception:
            pass

        after_mb, free_gb, total_gb = self.get_memory_status()
        return {
            "files_removed": files_removed,
            "ram_before_mb": before_mb,
            "ram_after_mb": after_mb,
            "free_sys_gb": free_gb,
            "total_sys_gb": total_gb,
        }

    def reconnect_devices(self):
        """Tự động khôi phục kết nối các máy offline hoặc bị nghẽn ADB stack trên tất cả các port."""
        try:
            for port in self._adb_ports:
                if port == 5037:
                    self._run_cmd(["reconnect", "offline"])
                    self._run_cmd(["reconnect"])
                else:
                    self._run_cmd(["reconnect", "offline"], port=port)
                    self._run_cmd(["reconnect"], port=port)
        except Exception:
            pass

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
        self.lock_portrait(device_id, retries=2)
        # 1. Mở màn hình đa nhiệm duy nhất một lần
        self.keyevent(device_id, 187)  # KEYCODE_APP_SWITCH
        time.sleep(0.6)
        width, height = self.get_effective_screen_size(device_id)
        w_portrait = min(width, height)
        h_portrait = max(width, height)
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_recents_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_recents_{safe_device_id}.xml")
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
        clear_resource_markers = (
            "clear_all",
            "clearall",
            "close_all",
            "closeall",
            "remove_all",
            "dismiss_all",
            "recents_clear",
            "recent_clear",
            "clear_all_button",
            "recents_close_all_button",
            "recents_close_all_container",
        )
        empty_markers = (
            "no recent items",
            "no recent apps",
            "no recently used apps",
            "no recently",
            "khong co ung dung gan day",
            "khong co ung dung da dung gan day",
            "khong co ung dung",
            "khong co muc gan day",
            "khong co muc",
            "da dung gan day",
            "gan day",
            "không có ứng dụng",
            "không có mục",
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
                device_id, ["shell", "uiautomator", "dump", remote_xml], timeout=4.0
            )
            if dump_code == 0:
                pull_code, _, _ = self.execute_adb(
                    device_id, ["pull", remote_xml, local_xml], timeout=4.0
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
                    is_rotated = root.attrib.get("rotation") in ("1", "3")
                    for node in root.iter():
                        raw_label = " ".join(
                            part
                            for part in (
                                node.get("text", ""),
                                node.get("content-desc", ""),
                            )
                            if part
                        ).strip()
                        # NFKD không chuyển chữ đ/Đ thành d/D. Chuẩn hóa riêng
                        # nhãn hệ thống để nhận đúng "Đóng tất cả" trên máy
                        # dùng tiếng Việt mà không thay đổi logic Facebook.
                        normalized = self._normalize_facebook_text(
                            raw_label.replace("Đ", "D").replace("đ", "d")
                        )
                        resource_id = node.get("resource-id", "").casefold()
                        is_clear_resource = any(
                            marker in resource_id
                            for marker in clear_resource_markers
                        )
                        if normalized:
                            screen_text.append(normalized)
                        is_clear = is_clear_resource or any(
                            marker in normalized for marker in clear_markers
                        ) or any(
                            marker in raw_label for marker in chinese_clear_markers
                        )
                        if not is_clear:
                            continue

                        # Nếu XML xoay ngang nhưng màn hình là dọc (như Samsung S7/G935F)
                        if is_rotated and ("recents_close_all" in resource_id or "clear_all" in resource_id):
                            if "recents_close_all" in resource_id:
                                coords = (w_portrait // 2, int(h_portrait * 0.958))
                            else:
                                coords = (w_portrait // 2, int(h_portrait * 0.80))
                        else:
                            coords = self._element_center(node)
                            if coords is None:
                                clickable = node
                                while (
                                    clickable is not None
                                    and clickable.get("clickable", "false") != "true"
                                ):
                                    clickable = parent_map.get(clickable)
                                if clickable is not None:
                                    coords = self._element_center(clickable)

                        if coords:
                            exact_vietnamese = normalized == "dong tat ca"
                            exact_supported = (
                                normalized in clear_markers
                                or raw_label in chinese_clear_markers
                            )
                            priority = (
                                0 if exact_vietnamese
                                else 1 if is_clear_resource
                                else 2 if exact_supported
                                else 3
                            )
                            clear_candidates.append((priority, coords))

                    if clear_candidates:
                        clear_candidates.sort(key=lambda item: item[0])
                        x, y = clear_candidates[0][1]
                        tap_result = self.tap(device_id, x, y)
                        tap_code = (
                            tap_result[0]
                            if isinstance(tap_result, tuple) and tap_result
                            else None
                        )
                        if tap_code not in (None, 0):
                            continue
                        time.sleep(0.6)
                        self.keyevent(device_id, 3)
                        self.lock_portrait(device_id, retries=1)
                        return True

                    combined_text = " ".join(screen_text)
                    if any(marker in combined_text for marker in empty_markers):
                        self.keyevent(device_id, 3)
                        self.lock_portrait(device_id, retries=1)
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

        # Fallback bấm vị trí Đóng tất cả chuẩn Samsung ngay trên màn hình Recents:
        # Launcher Samsung One UI / Exp (0.80) và SystemUI Recents (0.958)
        self.tap(device_id, w_portrait // 2, int(h_portrait * 0.80))
        time.sleep(0.25)
        self.tap(device_id, w_portrait // 2, int(h_portrait * 0.958))
        time.sleep(0.6)
        self.keyevent(device_id, 3)
        self.lock_portrait(device_id, retries=1)
        return True

    def emergency_stop_and_clear_recents(self, device_id):
        """Dừng khẩn cấp tức thì: Cưỡng chế đóng toàn bộ ứng dụng và xóa sạch đa nhiệm trên máy."""
        with self.emergency_cleanup_scope():
            packages_to_stop = [
                "com.ss.android.ugc.trill",
                "com.zhiliaoapp.musically",
                "com.facebook.katana",
                "com.facebook.lite",
                "com.facebook.orca",
                "com.android.chrome",
                "com.google.android.apps.chrome",
                "com.sec.android.app.sbrowser",
                "com.shopee.vn",
            ]
            # 1. Force stop tất cả app mục tiêu
            for pkg in packages_to_stop:
                try:
                    self.execute_adb(device_id, ["shell", "am", "force-stop", pkg], timeout=2.0)
                except Exception:
                    pass

            # 2. Kill background processes
            try:
                self.execute_adb(device_id, ["shell", "am", "kill-all"], timeout=2.0)
            except Exception:
                pass

            # 3. Mở đa nhiệm và bấm Đóng tất cả (gọi clear_recent_apps trực tiếp - không gửi keyevent kép)
            try:
                self.clear_recent_apps(device_id, max_scrolls=0)
            except Exception:
                self.keyevent(device_id, 187)
                time.sleep(0.5)
                width, height = self.get_effective_screen_size(device_id)
                w, h = min(width, height), max(width, height)
                self.tap(device_id, w // 2, int(h * 0.80))
                time.sleep(0.25)
                self.tap(device_id, w // 2, int(h * 0.958))
                time.sleep(0.6)
                self.keyevent(device_id, 3)

            self.lock_portrait(device_id, retries=1)
            return True

    def launch_facebook(self, device_id):
        """Mở ứng dụng Facebook (thử com.facebook.katana trước, dự phòng com.facebook.lite)"""
        self.dismiss_system_usb_storage_popup(device_id)
        self.lock_portrait(device_id, retries=2, force=True)
        code, stdout, stderr = self.launch_app(device_id, config.FACEBOOK_PACKAGE)
        if code != 0 or "Error" in (stdout or ""):
            self.launch_app(device_id, "com.facebook.lite")
        self.lock_portrait(device_id, retries=2, force=True)
        time.sleep(1.0)
        self.dismiss_system_usb_storage_popup(device_id)
        self.lock_portrait(device_id, retries=2, force=True)
        if self.is_screen_landscape(device_id):
            self.keyevent(device_id, 4)
            time.sleep(0.3)
            self.lock_portrait(device_id, retries=2, force=True)
        return True

    def launch_app(self, device_id, package_name):
        """Khởi chạy một ứng dụng bằng package name an toàn, không kích hoạt sự kiện xoay màn hình ngẫu nhiên."""
        self.lock_portrait(device_id, retries=2, force=True)
        known_components = {
            config.FACEBOOK_PACKAGE: f"{config.FACEBOOK_PACKAGE}/.LoginActivity",
            "com.facebook.lite": "com.facebook.lite/.MainActivity",
            config.TIKTOK_PACKAGE: f"{config.TIKTOK_PACKAGE}/com.ss.android.ugc.aweme.splash.SplashActivity",
            config.TIKTOK_PACKAGE_ALT: f"{config.TIKTOK_PACKAGE_ALT}/com.ss.android.ugc.aweme.splash.SplashActivity",
        }
        target_cmp = known_components.get(package_name)
        if target_cmp:
            code, stdout, stderr = self.execute_adb(
                device_id,
                [
                    "shell", "am", "start",
                    "-n", target_cmp,
                    "-a", "android.intent.action.MAIN",
                    "-c", "android.intent.category.LAUNCHER",
                ],
            )
            if code == 0 and "Error" not in (stdout or ""):
                self.lock_portrait(device_id, retries=2, force=True)
                return code, stdout, stderr

        code, resolve_out, _ = self.execute_adb(
            device_id,
            [
                "shell", "cmd", "package", "resolve-activity",
                "--brief", "-c", "android.intent.category.LAUNCHER", package_name,
            ],
        )
        if code == 0 and resolve_out:
            lines = [
                l.strip()
                for l in resolve_out.splitlines()
                if "/" in l and not l.startswith("priority=")
            ]
            if lines:
                cmp_name = lines[-1]
                code, stdout, stderr = self.execute_adb(
                    device_id,
                    [
                        "shell", "am", "start",
                        "-n", cmp_name,
                        "-a", "android.intent.action.MAIN",
                        "-c", "android.intent.category.LAUNCHER",
                    ],
                )
                if code == 0 and "Error" not in (stdout or ""):
                    self.lock_portrait(device_id, retries=2, force=True)
                    return code, stdout, stderr

        res = self.execute_adb(
            device_id,
            [
                "shell", "monkey", "-p", package_name,
                "-c", "android.intent.category.LAUNCHER",
                "--pct-rotation", "0",
                "--pct-syskeys", "0",
                "--pct-appswitch", "0",
                "--pct-anyevent", "0",
                "1",
            ],
        )
        self.lock_portrait(device_id, retries=2, force=True)
        return res

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

    def dismiss_system_usb_storage_popup(self, device_id, status_callback=None, force=False):
        """Phát hiện và tự động xử lý popup 'Cho phép / Không cho phép' (Samsung MTP prompt, USB debug, System permissions).
        Tự động bấm 'CHO PHÉP' / 'ALLOW' / 'OK' để hoàn tất cấp quyền và đóng dialog,
        đồng thời hỗ trợ bấm ra vùng nền ngoài và phím Back để giải phóng màn hình và bảo toàn kết nối ADB.
        """
        try:
            has_mtp_dialog = force
            if not has_mtp_dialog:
                code, stdout, _ = self.execute_adb(
                    device_id, ["shell", "dumpsys", "window", "windows"]
                )
                if code == 0 and stdout:
                    markers = (
                        "mtpapplication",
                        "usbauthorization",
                        "usbstorage",
                        "mtpreceiver",
                        "usbpopup",
                        "allow access to phone data",
                        "truy cap du lieu",
                        "access to phone data",
                        "mtp",
                        "grantpermissions",
                        "packageinstaller",
                        "permissioncontroller",
                        "alertdialog",
                        "usbdebuggingactivity",
                    )
                    lower_out = stdout.casefold()
                    for line in lower_out.splitlines():
                        if any(f in line for f in ("mcurrentfocus", "mfusedapp", "focusedapplication", "mresumedactivity")):
                            if any(m in line for m in markers):
                                has_mtp_dialog = True
                                break

            if has_mtp_dialog:
                self._safe_status_callback(
                    status_callback,
                    device_id,
                    "[Xử lý Popup] Phát hiện Popup yêu cầu Cho phép • Đang tự động bấm 'Cho phép' và giải phóng màn hình...",
                )
                width, height = self.get_effective_screen_size(device_id)

                # 1. Bấm vào nút 'CHO PHÉP' / 'ALLOW' (nút positive ở góc phải dưới của hộp thoại Samsung)
                btn_allow_x = int(width * 0.76)
                btn_allow_y = int(height * 0.585)
                self.tap(device_id, btn_allow_x, btn_allow_y)
                time.sleep(0.15)

                # 2. Gửi phím điều hướng Android DPAD_RIGHT + ENTER để kích hoạt nút Positive
                self.keyevent(device_id, 22)
                self.keyevent(device_id, 66)
                time.sleep(0.15)

                # 3. Bấm vào vùng nền phía trên popup (khoảng 25% chiều cao) và gửi phím Back dự phòng
                self.tap(device_id, width // 2, int(height * 0.25))
                time.sleep(0.15)
                self.keyevent(device_id, 4)
                time.sleep(0.15)
                return True
        except Exception:
            pass
        return False

    def bulk_dismiss_system_usb_storage_popups(self, target_devices=None, status_callback=None, force=False):
        """Đóng popup USB MTP đồng loạt trên toàn bộ thiết bị chỉ định bằng đa luồng song song."""
        devices = target_devices or self.get_devices()
        if not devices:
            return []
        with ThreadPoolExecutor(max_workers=min(len(devices), self.max_parallel_commands)) as executor:
            results = list(executor.map(
                lambda dev: (dev, self.dismiss_system_usb_storage_popup(dev, status_callback, force=force)),
                devices
            ))
        return results

    def ensure_facebook_ready(self, device_id):
        """Giữ Facebook hiện tại hoặc mở app nếu chưa ở foreground."""
        self.dismiss_system_usb_storage_popup(device_id)
        self.lock_portrait(device_id, retries=2)
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
        if self.is_screen_landscape(device_id):
            self.keyevent(device_id, 4)
            time.sleep(0.3)
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
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_home_{safe_device_id}.xml")
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
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_feed_{safe_device_id}.xml")
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
        without_marks = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).split()
        )

    def _resolve_facebook_exact_page_name(self, target_phrase):
        """Chọn tên Page đầy đủ tương ứng với cụm target đang tìm."""
        target_tokens = self._normalize_facebook_text(target_phrase).split()
        if not target_tokens:
            return None

        configured_names = []
        for raw in (
            config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT,
            config.FACEBOOK_CANONICAL_PAGE_NAME,
        ):
            if raw:
                configured_names.extend(
                    [p.strip() for p in raw.split(",") if p.strip()]
                )
        matching_names = []
        for candidate in configured_names:
            candidate = (candidate or "").strip()
            candidate_tokens = self._normalize_facebook_text(candidate).split()
            if candidate_tokens and all(
                token in candidate_tokens for token in target_tokens
            ):
                matching_names.append((len(candidate_tokens), candidate))

        if not matching_names:
            return None
        return max(matching_names)[1]

    def prepare_facebook_target_results(self, device_id):
        """Đưa kết quả target về đầu và ưu tiên bộ lọc Page/Trang."""
        self.lock_portrait(device_id, retries=3)
        self.collapse_statusbar_if_expanded(device_id)
        self.dismiss_facebook_messenger_if_present(device_id)
        if not self.is_facebook_in_foreground(device_id):
            return False

        width, height = self.get_effective_screen_size(device_id)
        # Vuốt nhẹ trong vùng an toàn giữa màn hình (45%-65%), không chạm nửa trên để tránh thanh thông báo
        for swipe_duration in (500, 520):
            self.swipe(
                device_id,
                width // 2,
                int(height * 0.45),
                width // 2,
                int(height * 0.65),
                duration=swipe_duration,
            )
            time.sleep(0.35)
        self.collapse_statusbar_if_expanded(device_id)
        self.lock_portrait(device_id, retries=3)

        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_target_tabs_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_target_tabs_{safe_device_id}.xml")
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
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
            else:
                # Nếu tab Trang nằm khuất bên phải, vuốt nhẹ thanh tab sang trái rồi tìm lại
                self.swipe(
                    device_id,
                    int(width * 0.85),
                    int(height * 0.12),
                    int(width * 0.20),
                    int(height * 0.12),
                    duration=380,
                )
                time.sleep(0.8)
                self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
                self.execute_adb(
                    device_id, ["shell", "uiautomator", "dump", remote_xml]
                )
                pull_code, _, _ = self.execute_adb(
                    device_id, ["pull", remote_xml, local_xml]
                )
                if pull_code == 0 and os.path.exists(local_xml):
                    r_scrolled = ET.parse(local_xml).getroot()
                    p_map = {
                        child: parent
                        for parent in r_scrolled.iter()
                        for child in parent
                    }
                    for node in r_scrolled.iter():
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
                        if label in {"trang", "page", "pages"}:
                            clickable = node
                            while (
                                clickable is not None
                                and clickable.get("clickable", "false") != "true"
                            ):
                                clickable = p_map.get(clickable)
                            click_node = (
                                clickable if clickable is not None else node
                            )
                            match = re.match(
                                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                                click_node.get("bounds", ""),
                            )
                            if match:
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

    def _is_facebook_personal_profile(self, device_id):
        """Kiểm tra màn hình hiện tại có phải tài khoản cá nhân Facebook (không phải Page) hay không."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_verify_profile_{safe_device_id}.xml"
        local_xml = os.path.join(
            tempfile.gettempdir(), f"temp_fb_verify_profile_{safe_device_id}.xml"
        )
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        self.execute_adb(device_id, ["shell", "uiautomator", "dump", remote_xml])
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return False
            root = ET.parse(local_xml).getroot()
            for elem in root.iter():
                text = self._normalize_facebook_text(
                    f"{elem.get('text', '')} {elem.get('content-desc', '')}"
                )
                if not text:
                    continue
                # Dấu hiệu chắc chắn 100% của tài khoản cá nhân:
                if any(
                    marker in text
                    for marker in (
                        "them ban be",
                        "add friend",
                        "ban be",
                        "ban chung",
                        "mutual friend",
                        "huy loi moi",
                        "thong tin ca nhan",
                    )
                ):
                    return True
            return False
        except Exception:
            return False
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
        randomize_matching_pages=False,
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
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_facebook_page_{safe_device_id}.xml"
        local_xml = os.path.join(
            tempfile.gettempdir(),
            f"temp_facebook_page_{safe_device_id}.xml",
        )

        for attempt in range(max(1, max_swipes)):
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
                        
                        # Gom nhãn từ chính node và các con trực tiếp nếu là ViewGroup nhỏ
                        node_text_parts = [
                            node.get("text", ""),
                            node.get("content-desc", ""),
                        ]
                        for sub in node.iter():
                            if sub is not node:
                                node_text_parts.extend([
                                    sub.get("text", ""),
                                    sub.get("content-desc", ""),
                                ])
                        
                        label = " ".join(p for p in node_text_parts if p).strip()
                        label_normalized = self._normalize_facebook_text(label)
                        if not label_normalized:
                            continue

                        # 1. Bỏ qua nếu có dấu hiệu của tài khoản cá nhân (Thêm bạn bè, Bạn bè, Bạn chung, v.v.)
                        personal_markers = (
                            "them ban be",
                            "add friend",
                            "ban be",
                            "friends",
                            "ban chung",
                            "mutual friend",
                            "huy loi moi",
                            "cancel request",
                            "dang theo doi",
                            "thong tin ca nhan",
                        )
                        if any(pm in label_normalized for pm in personal_markers):
                            continue

                        # 2. Bắt buộc: Tên chính (Primary Title) của card phải chứa thương hiệu target
                        primary_title = ""
                        for p in node_text_parts:
                            p_norm = self._normalize_facebook_text(p)
                            if (
                                p_norm
                                and len(p_norm) >= 3
                                and not any(pm in p_norm for pm in personal_markers)
                            ):
                                primary_title = p_norm
                                break

                        if not primary_title:
                            primary_title = label_normalized
                        primary_title_tokens = set(primary_title.split())
                        label_token_set = set(label_normalized.split())
                        # Từ chối dứt khoát các thương hiệu ngoại lai / trang không liên quan
                        unrelated_brands = (
                            "sony", "samsung", "apple", "xiaomi", "honda", "yamaha",
                            "toyota", "mercedes", "oto", "xe", "dien may", "the gioi di dong"
                        )
                        if any(
                            ub in primary_title_tokens or ub in label_token_set or ub in label_normalized
                            for ub in unrelated_brands
                        ):
                            continue

                        # Nếu target có 'khai' và 'hoan', candidate title BẮT BUỘC phải có 'khai' và 'hoan', và 'khai' đứng trước 'hoan'
                        if "khai" in target_tokens and "hoan" in target_tokens:
                            if "khai" not in primary_title_tokens or "hoan" not in primary_title_tokens:
                                continue
                            if primary_title.find("khai") > primary_title.find("hoan"):
                                # Tên đảo 'Hoàn khải' -> TỪ CHỐI
                                continue
                            has_target_in_title = True
                        else:
                            has_target_in_title = any(
                                t in primary_title_tokens for t in target_tokens
                            )
                        if not has_target_in_title:
                            continue

                        # Kiểm tra khớp target: chứa tất cả target_tokens hoặc khớp core brand hoặc khớp địa điểm canonical
                        has_all_target = all(
                            token in label_token_set for token in target_tokens
                        )
                        target_overlap = sum(
                            1 for token in target_tokens if token in label_token_set
                        )
                        has_core_brand = (
                            "khai" in label_token_set
                            and "hoan" in label_token_set
                            and label_normalized.find("khai") < label_normalized.find("hoan")
                        )
                        has_desired_loc = (
                            bool(desired_tokens)
                            and ("phan" in label_token_set or "thiet" in label_token_set)
                            and has_core_brand
                        )

                        if not (has_all_target or has_desired_loc or (has_core_brand and target_overlap >= min(2, len(target_tokens)))):
                            continue

                        node_bounds = node.get("bounds", "")
                        node_match = re.match(
                            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node_bounds
                        )
                        if not node_match:
                            continue
                        nx1, ny1, nx2, ny2 = map(int, node_match.groups())
                        if ny2 <= int(height * 0.08) or ny1 >= int(height * 0.95):
                            continue
                        # Bỏ qua nếu node bao toàn bộ màn hình
                        if (ny2 - ny1) > int(height * 0.35):
                            continue

                        # Tìm clickable container hợp lệ: CHỈ nhận container có chiều cao hợp lý (thẻ card <= 28% màn hình).
                        # Tuyệt đối không duyệt lên RecyclerView/ViewGroup toàn màn hình để tránh lệch tọa độ giữa màn hình.
                        click_node = node
                        curr = node
                        while curr is not None:
                            if curr.get("clickable", "false") == "true":
                                cbounds = curr.get("bounds", "")
                                cmatch = re.match(
                                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", cbounds
                                )
                                if cmatch:
                                    cx1, cy1, cx2, cy2 = map(int, cmatch.groups())
                                    c_height = cy2 - cy1
                                    if c_height <= int(height * 0.28) and cy1 <= ny1 and cy2 >= ny2:
                                        click_node = curr
                                        break
                            curr = parent_map.get(curr)

                        bounds = click_node.get("bounds", "")
                        match = re.match(
                            r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds
                        )
                        if not match:
                            continue
                        x1, y1, x2, y2 = map(int, match.groups())
                        if y2 <= int(height * 0.08) or y1 >= int(height * 0.95):
                            continue

                        desired_overlap = sum(
                            1 for token in desired_tokens if token in label_token_set
                        ) if desired_tokens else 0
                        exact_canonical = (
                            bool(desired_tokens)
                            and (
                                all(token in label_token_set for token in desired_tokens)
                                or (has_desired_loc and desired_overlap >= len(desired_tokens) * 0.6)
                            )
                        )
                        contiguous_desired = (
                            bool(desired_normalized)
                            and desired_normalized in label_normalized
                        )
                        contiguous_target = (
                            bool(target_normalized)
                            and target_normalized in label_normalized
                        )

                        # Phân cấp ưu tiên:
                        # Tier 0: Khớp canonical page name (Phan Thiết)
                        # Tier 1: Khớp target_phrase
                        # Tier 2: Khớp core brand
                        if exact_canonical or contiguous_desired or has_desired_loc:
                            tier = 0
                        elif has_all_target or contiguous_target:
                            tier = 1
                        else:
                            tier = 2

                        tap_x = (x1 + x2) // 2
                        tap_y = (y1 + y2) // 2
                        candidates.append(
                            (
                                tier,
                                -desired_overlap,
                                -target_overlap,
                                -len(label_normalized),
                                tap_x,
                                tap_y,
                                label,
                            )
                        )

                    if candidates:
                        min_tier = min(c[0] for c in candidates)
                        top_tier_candidates = [
                            c for c in candidates if c[0] == min_tier
                        ]
                        top_tier_candidates.sort()

                        if randomize_matching_pages:
                            # Gom cụm theo vị trí thẻ card (tọa độ Y cách nhau theo tỷ lệ chiều cao màn hình để phân biệt chính xác giữa 1080p và 1440p)
                            card_separation_y = max(60, int(height * 0.03))
                            distinct_cards = []
                            for c in top_tier_candidates:
                                if not any(
                                    abs(c[5] - d[5]) < card_separation_y for d in distinct_cards
                                ):
                                    distinct_cards.append(c)

                            if len(distinct_cards) > 1:
                                chosen = random.choice(distinct_cards)
                                try:
                                    print(
                                        f"[Device {device_id[:6]}][Facebook] "
                                        f"Phát hiện {len(distinct_cards)} Page phù hợp trên màn hình • "
                                        f"Bốc ngẫu nhiên Page '{chosen[6]}' tại ({chosen[4]}, {chosen[5]})..."
                                    )
                                except Exception:
                                    pass
                            else:
                                chosen = top_tier_candidates[0]
                        else:
                            chosen = top_tier_candidates[0]

                        x, y = chosen[4], chosen[5]
                        self.tap(device_id, x, y)
                        time.sleep(2.0)
                        self.dismiss_facebook_messenger_if_present(device_id)
                        self.dismiss_facebook_blocking_popups(device_id)
                        time.sleep(1.0)
                        if self._is_facebook_personal_profile(device_id):
                            print(
                                f"[Device {device_id[:6]}][Facebook] "
                                f"Phát hiện mở nhầm tài khoản cá nhân • Bấm Back quay lại tìm Page..."
                            )
                            self.keyevent(device_id, 4)
                            time.sleep(1.5)
                            continue
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
                if attempt == 0:
                    time.sleep(0.6)
                self.swipe(
                    device_id,
                    width // 2,
                    int(height * 0.78),
                    width // 2,
                    int(height * 0.30),
                    duration=random.randint(650, 950),
                )
                self.collapse_statusbar_if_expanded(device_id)
                time.sleep(1.5)
        return False

    def _get_facebook_search_input_state(self, device_id):
        """Đọc ô Search Facebook ở vùng header."""
        width, height = self.get_effective_screen_size(device_id)
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_input_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_input_{safe_device_id}.xml")
        self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", remote_xml]
        )
        if dump_code != 0:
            return None
        pull_code, _, _ = self.execute_adb(
            device_id, ["pull", remote_xml, local_xml]
        )

        candidates = []
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            for node in root.iter():
                class_name = node.get("class", "").casefold()
                resource_id = node.get("resource-id", "").casefold()
                description = node.get("content-desc", "").casefold()
                editable = node.get("editable", "false") == "true"
                match = re.match(
                    r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                    node.get("bounds", ""),
                )
                if not match:
                    continue
                x1, y1, x2, y2 = map(int, match.groups())
                cy = (y1 + y2) // 2
                normalized_identity = self._normalize_facebook_text(
                    f"{resource_id} {description} {node.get('text', '')}"
                )
                searchable = any(
                    marker in normalized_identity
                    for marker in ("search", "tim kiem")
                )
                wide_search_field = (
                    searchable and (x2 - x1) >= int(width * 0.25)
                )
                if not (
                    editable
                    or "edittext" in class_name
                    or wide_search_field
                ):
                    continue
                if cy > int(height * 0.20):
                    continue
                focused = node.get("focused", "false") == "true"
                candidates.append(
                    {
                        "score": (
                            int(focused) * 8
                            + int(editable) * 4
                            + int("edittext" in class_name) * 2
                            + int(searchable)
                            + int(wide_search_field) * 2
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
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_search_{safe_device_id}.xml")
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
            parent_map = {
                child: parent
                for parent in root.iter()
                for child in parent
            }
            candidates = []
            for node in root.iter():
                haystack = " ".join(
                    (
                        node.get("text", ""),
                        node.get("content-desc", ""),
                        node.get("resource-id", ""),
                    )
                ).casefold()
                if any(
                    neg in haystack
                    for neg in (
                        "messaging", "messenger", "nhan tin", "chat", "tin nhan",
                    )
                ):
                    continue
                if not any(
                    marker in haystack
                    for marker in (
                        "search", "tìm kiếm", "tim kiem", "search_button",
                    )
                ):
                    continue

                # Trên màn “Mới đây”, Facebook đặt chữ “Tìm kiếm” trong một
                # TextView hẹp nhưng vùng nhận tap thật là container cha rộng.
                # Đi ngược cây để lấy đúng vùng bấm, không dùng tâm node chữ.
                ancestors = []
                current = node
                while current is not None:
                    ancestors.append(current)
                    current = parent_map.get(current)

                for depth, candidate in enumerate(ancestors):
                    match = re.match(
                        r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                        candidate.get("bounds", ""),
                    )
                    if not match:
                        continue
                    x1, y1, x2, y2 = map(int, match.groups())
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    candidate_width = x2 - x1
                    if cy > int(height * 0.18):
                        continue

                    wide_field = (
                        int(width * 0.25)
                        <= candidate_width
                        <= int(width * 0.95)
                    )
                    # Kính lúp Home nằm trong khoảng 65%-84% bề ngang (không được vượt quá 84% để tránh icon Messenger)
                    right_header_icon = (
                        depth == 0
                        and int(width * 0.65) <= cx <= int(width * 0.84)
                        and candidate_width < int(width * 0.25)
                    )
                    if wide_field:
                        candidates.append((0, depth, cx, cy))
                    elif right_header_icon:
                        candidates.append((1, depth, cx, cy))

            if not candidates:
                return None
            _priority, _depth, x, y = min(candidates)
            return x, y
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
        back_result = self.keyevent(device_id, 4)
        back_code = (
            back_result[0]
            if isinstance(back_result, tuple) and back_result
            else None
        )
        if back_code not in (None, 0):
            return False
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)
        if self.wait_for_facebook_foreground(device_id):
            return True
        self.launch_app(device_id, config.FACEBOOK_PACKAGE)
        time.sleep(1.4)
        self.lock_portrait(device_id, retries=3)
        return self.wait_for_facebook_foreground(device_id)

    def return_facebook_home_before_search(self, device_id):
        """Back một lần sau khi nuôi Feed và xác minh lại đúng Facebook Home."""
        self.lock_portrait(device_id, retries=3)
        if not self.wait_for_facebook_foreground(device_id):
            return False

        self.keyevent(device_id, 4)
        time.sleep(0.8)
        self.lock_portrait(device_id, retries=3)

        if not self.wait_for_facebook_foreground(device_id):
            return self.ensure_facebook_ready(device_id)
        if self.is_facebook_home(device_id) is True:
            return True

        # Một số phiên bản Facebook giữ lại viewer hoặc tab con sau Back.
        # Phục hồi bằng luồng Home có kiểm chứng, không tap mù lên bài viết.
        return self.ensure_facebook_ready(device_id)

    def find_and_click_facebook_search(
        self, device_id, allow_recent_fallback=False
    ):
        """Mở Search; B3 được phép đi tiếp khi probe ADB tạm nghẽn."""
        self.lock_portrait(device_id)
        if (
            not self.wait_for_facebook_foreground(device_id)
            and not allow_recent_fallback
        ):
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

        for attempt in range(2):
            if (
                not self.wait_for_facebook_foreground(device_id)
                and not allow_recent_fallback
            ):
                return False
            coords = self._get_facebook_header_search_coords(device_id)
            xml_verified_coords = coords is not None
            used_home_fallback = False
            used_recent_fallback = False

            if coords is None:
                input_state = self._get_facebook_search_input_state(device_id)
                if input_state:
                    coords = input_state["coords"]
                    xml_verified_coords = True
                else:
                    home_state = self.is_facebook_home(device_id)
                    if home_state is False:
                        # Một dump XML rỗng/thiếu node dưới tải cao không đủ
                        # để kết luận đã rời Home. Đọc thêm một nhịp trước khi
                        # cho phép nhánh Back phục hồi.
                        time.sleep(0.25)
                        retry_home_state = self.is_facebook_home(device_id)
                        if retry_home_state is not False:
                            home_state = retry_home_state
                    if home_state is not False:
                        # Khi Home trả về True hoặc tạm thời chưa xác định
                        # (XML đang bận), foreground vẫn là Facebook và ảnh
                        # thực tế cho thấy kính lúp ở vùng header này.
                        # Không được Back/thoát app chỉ vì dump chậm.
                        # Tọa độ an toàn giúp nhóm máy UIAutomator đang bận
                        # vẫn chạy; bước nhập sẽ xác minh lại nội dung.
                        coords = (int(width * 0.83), int(height * 0.055))
                        used_home_fallback = True

            if coords is None and allow_recent_fallback:
                # B3 vừa lướt kết quả từ khóa mồi và caller đã xác nhận
                # Facebook. Ở màn “Mới đây”, ô Search là dải xám rộng bên trái.
                # Khi 40 máy dump đồng thời, XML/dumpsys có thể cùng trống dù
                # ô này vẫn hiện; tap tâm dải nhập thay vì báo lỗi giả.
                coords = (int(width * 0.45), int(height * 0.055))
                used_recent_fallback = True

            if coords is not None:
                verified_wide_search_field = bool(
                    xml_verified_coords
                    and coords[0] < int(width * 0.65)
                )
                tap_result = self.tap(device_id, coords[0], coords[1])
                tap_code = (
                    tap_result[0]
                    if isinstance(tap_result, tuple) and tap_result
                    else None
                )
                if tap_code not in (None, 0):
                    if attempt == 0:
                        time.sleep(0.35)
                        continue
                    return False
                time.sleep(0.8)
                self.dismiss_facebook_messenger_if_present(device_id)
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

                # Ô Search xám rộng ở màn “Mới đây” đã là vùng nhập thật. Khi
                # tọa độ này được XML xác minh, không Back/báo lỗi chỉ vì
                # dumpsys trống một nhịp. Riêng icon kính lúp nhỏ bên phải Home
                # vẫn phải đi qua nhánh phục hồi nếu tap chưa mở được input.
                if verified_wide_search_field:
                    return True

                if allow_recent_fallback and (
                    used_recent_fallback or xml_verified_coords
                ):
                    # Bước thay thế từ khóa kế tiếp sẽ xóa, nhập và xác minh
                    # theo broadcast XwIME. Không Back khỏi màn Search chỉ vì
                    # UIAutomator chưa kịp expose EditText sau lần tap này.
                    return True

                # Khi 40 máy dump đồng thời, XML có thể bận ngay sau khi ADB đã
                # chạm đúng kính lúp trên Home. Không Back về Home ở tình huống
                # này: bước replace_facebook_search_text kế tiếp sẽ focus ô
                # nhập, bơm từ khóa và xác minh chính xác nội dung. Nếu tap thực
                # sự không mở Search, bước đó retry rồi báo lỗi nhập cụ thể.
                if (
                    used_home_fallback
                    and self.wait_for_facebook_foreground(device_id)
                ):
                    return True

                home_after_tap = self.is_facebook_home(device_id)
                if (
                    home_after_tap is not True
                    and self.wait_for_facebook_foreground(device_id)
                ):
                    return True

            if attempt == 0:
                if not self._recover_facebook_search_with_one_back(device_id):
                    return False
                continue
            return False
        return False

    def replace_facebook_search_text(
        self, device_id, text, allow_transient_foreground=False
    ):
        """Xóa sạch từ khóa Facebook cũ rồi nhập nguyên cụm mới một lần."""
        expected = self._normalize_facebook_text(text)
        input_broadcast_succeeded = False
        for attempt in range(2):
            if (
                not self.wait_for_facebook_foreground(device_id)
                and not allow_transient_foreground
            ):
                raise RuntimeError(
                    "Facebook không còn ở foreground; đã chặn nhập từ khóa"
                )
            self.ensure_ime(device_id)
            self._focus_facebook_search_input(device_id)
            if (
                not self.wait_for_facebook_foreground(device_id)
                and not allow_transient_foreground
            ):
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
            if (
                not self.wait_for_facebook_foreground(device_id)
                and not allow_transient_foreground
            ):
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
            # XwIME có một lỗi không ổn định trên một số profile: chữ đã được
            # Facebook nhận và hiển thị nhưng `am broadcast` vẫn trả mã khác 0.
            # Vì vậy phải đọc trạng thái ô nhập trước khi coi lệnh là thất bại.
            time.sleep(0.5)
            state = self._get_facebook_search_input_state(device_id)
            if state is not None and (
                self._normalize_facebook_text(state["text"]) == expected
            ):
                return True
            if input_code == 0:
                input_broadcast_succeeded = True
                # UIAutomator thường bận trong lúc bảng gợi ý mở. Broadcast đã
                # được Android nhận thì giữ focus để bước Enter tiếp tục, thay
                # vì gõ lại lần hai làm nhân đôi từ khóa trên màn hình.
                if state is None and (
                    allow_transient_foreground
                    or self.wait_for_facebook_foreground(device_id)
                ):
                    return True
                if attempt == 0:
                    time.sleep(0.3)
                    continue

            # Khi broadcast báo lỗi và trạng thái vẫn chưa đúng, làm sạch lại
            # rồi dùng `input text` ASCII làm đường lui. Cách này chỉ chạy sau
            # khi lệnh broadcast thất bại nên không thể nối đuôi vào chữ đã có.
            if input_code != 0:
                self.execute_adb(
                    device_id,
                    [
                        "shell", "am", "broadcast",
                        "-a", "XW_CLEAR_TEXT",
                        "--receiver-foreground",
                    ],
                )
                fallback_text = self.remove_vietnamese_accents(text)
                escaped = fallback_text.replace(" ", "%s")
                fallback_code, _, _ = self.execute_adb(
                    device_id,
                    ["shell", "input", "text", escaped],
                )
                time.sleep(0.35)
                fallback_state = self._get_facebook_search_input_state(
                    device_id
                )
                if fallback_state is not None and (
                    self._normalize_facebook_text(fallback_state["text"])
                    == self._normalize_facebook_text(fallback_text)
                ):
                    return True
                if (
                    fallback_code == 0
                    and (
                        allow_transient_foreground
                        or self.wait_for_facebook_foreground(device_id)
                    )
                ):
                    return True
            if attempt == 0:
                time.sleep(0.3)
        # Facebook thường hiển thị bảng gợi ý ngay sau khi nhập. Ở một số
        # thiết bị, UIAutomator lúc đó trả XML thiếu/không đọc được dù chữ đã
        # hiện đúng trên màn hình. Broadcast XwIME trả mã 0 là tín hiệu ADB đã
        # nhận toàn bộ từ khóa; giữ focus và để bước submit gửi Enter thay vì
        # dừng sai trước khi tìm kiếm.
        if input_broadcast_succeeded and (
            allow_transient_foreground
            or self.wait_for_facebook_foreground(device_id)
        ):
            return True
        raise RuntimeError(
            f"Không thể nhập chính xác từ khóa Facebook: '{text}'"
        )

    def submit_facebook_search(
        self, device_id, allow_transient_foreground=False
    ):
        """Gửi tìm kiếm Facebook bằng Enter của bàn phím."""
        if (
            not self.wait_for_facebook_foreground(device_id)
            and not allow_transient_foreground
        ):
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

    def _get_facebook_ui_root(self, device_id, prefix="fb_ui"):
        """Dump UI Facebook và trả về XML root để parse."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/{prefix}_{safe_device_id}.xml"
        local_xml = os.path.join(
            tempfile.gettempdir(), f"temp_{prefix}_{safe_device_id}.xml"
        )
        # 1. Thử cơ chế One-shot Streaming trực tiếp qua RAM (không tạo file trên PC, không spawn adb pull)
        fast_cmd = f"uiautomator dump {remote_xml} >/dev/null 2>&1 && cat {remote_xml} && rm -f {remote_xml}"
        code, stdout, _ = self.execute_adb(device_id, ["shell", fast_cmd])
        if code == 0 and stdout and "<hierarchy" in stdout:
            try:
                start_idx = stdout.find("<hierarchy")
                end_idx = stdout.find("</hierarchy>")
                if start_idx != -1 and end_idx != -1:
                    clean_xml = stdout[start_idx : end_idx + len("</hierarchy>")]
                    fb_root = ET.fromstring(clean_xml)
                    if fb_root is not None and fb_root.attrib.get("rotation") in ("1", "3"):
                        print(f"[Device {device_id[:6]}][Facebook] Màn hình bị xoay ngang ({fb_root.attrib.get('rotation')}) • Ép khóa dọc ngay lập tức...")
                        self.lock_portrait(device_id, retries=3, force=True)
                        self.keyevent(device_id, 4)
                        time.sleep(0.5)
                    return fb_root
            except Exception:
                pass

        # 2. Fallback an toàn (rm -> dump -> pull -> finally xóa file tạm)
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
            return ET.parse(local_xml).getroot()
        except Exception:
            return None
        finally:
            try:
                os.remove(local_xml)
            except Exception:
                pass
            self.execute_adb(device_id, ["shell", "rm", "-f", remote_xml])

    def dismiss_facebook_blocking_popups(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động tắt các hộp thoại, popup cản trở trên Facebook (Lưu thông tin đăng nhập, Bật thông báo, Đồng bộ danh bạ...)."""
        root = self._get_facebook_ui_root(device_id, "fb_popup_chk")
        if root is None:
            return False

        parent_map = {
            child: parent for parent in root.iter() for child in parent
        }
        popup_markers = (
            "luu thong tin dang nhap",
            "save login info",
            "bat thong bao",
            "turn on notifications",
            "thong bao",
            "dong bo danh ba",
            "sync contacts",
            "tim ban be",
            "find friends",
            "cap nhat facebook",
            "update facebook",
            "phien ban moi",
            "new version",
            "them vao man hinh",
            "add to home screen",
            "cho phep facebook",
            "allow facebook",
            "danh gia",
            "rate us",
            "luc khac",
            "not now",
            "de sau",
            "bao cao",
            "report",
            "ban muon bao cao dieu gi",
            "van de ve trang nay",
            "bai viet cu the",
            "tim su giup do",
        )
        dismiss_labels = {
            "luc khac",
            "not now",
            "de sau",
            "later",
            "khong",
            "no",
            "khong phai bay gio",
            "khong cam on",
            "no thanks",
            "bo qua",
            "skip",
            "huy",
            "cancel",
            "dong",
            "close",
            "tu choi",
            "deny",
            "dont allow",
            "tro lai",
            "back",
        }

        has_popup = False
        dismiss_node = None

        for node in root.iter():
            label = self._normalize_facebook_text(
                f"{node.get('text', '')} {node.get('content-desc', '')}"
            )
            resource_id = node.get("resource-id", "").casefold()

            if any(marker in label for marker in popup_markers):
                has_popup = True

            if label in dismiss_labels or any(
                k in label for k in ("luc khac", "not now", "de sau", "khong phai bay gio")
            ):
                clickable = node
                while clickable is not None and clickable.get("clickable", "false") != "true":
                    clickable = parent_map.get(clickable)
                dismiss_node = clickable if clickable is not None else node
                has_popup = True
                break

            if any(k in resource_id for k in ("cancel", "dismiss", "close", "negative")):
                clickable = node
                while clickable is not None and clickable.get("clickable", "false") != "true":
                    clickable = parent_map.get(clickable)
                dismiss_node = clickable if clickable is not None else node
                has_popup = True
                break

        if has_popup and dismiss_node is not None:
            coords = self._element_center(dismiss_node)
            if coords:
                if status_callback:
                    status_callback(
                        device_id,
                        f"[Facebook] Tự động đóng popup cản trở tại {coords}...",
                    )
                self.tap(device_id, coords[0], coords[1])
                time.sleep(1.0)
                return True
        elif has_popup:
            self.keyevent(device_id, 4)
            time.sleep(0.8)
            return True

        return False

    def dismiss_facebook_composer_if_present(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động thoát màn hình 'Bài viết mới' / 'Bạn đang nghĩ gì?'."""
        root = self._get_facebook_ui_root(device_id, "fb_composer_chk")
        if root is None:
            return False
        found_composer = False
        close_coords = None
        for elem in root.iter():
            text = self._normalize_facebook_text(elem.get("text", ""))
            desc = self._normalize_facebook_text(elem.get("content-desc", ""))
            if (
                "bai viet moi" in text
                or "bai viet moi" in desc
                or "tao bai viet" in text
                or "tao bai viet" in desc
                or "ban dang nghi gi" in text
                or "ban dang nghi gi" in desc
                or "create post" in text
                or "create post" in desc
                or "what's on your mind" in text
                or "what's on your mind" in desc
            ):
                found_composer = True
            if "dong" in desc or "close" in desc or "tro lai" in desc or "back" in desc:
                bounds = elem.get("bounds", "")
                m = re.findall(r"\d+", bounds)
                if len(m) >= 4:
                    x1, y1, x2, y2 = map(int, m[:4])
                    close_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

        if found_composer:
            if status_callback:
                status_callback(
                    device_id,
                    "[Facebook] Phát hiện ô bài viết mới • Đang tự động thoát ra...",
                )
            if close_coords:
                self.tap(device_id, close_coords[0], close_coords[1])
            else:
                width, height = self.get_effective_screen_size(device_id)
                self.tap(device_id, int(width * 0.08), int(height * 0.06))
            time.sleep(0.5)
            self.keyevent(device_id, 4)
            time.sleep(0.5)
            root2 = self._get_facebook_ui_root(device_id, "fb_discard_chk")
            if root2 is not None:
                for elem in root2.iter():
                    t = self._normalize_facebook_text(elem.get("text", ""))
                    d = self._normalize_facebook_text(elem.get("content-desc", ""))
                    if "bo" in t or "discard" in t or "bo bai viet" in t or "bo" in d:
                        bounds = elem.get("bounds", "")
                        m = re.findall(r"\d+", bounds)
                        if len(m) >= 4:
                            x1, y1, x2, y2 = map(int, m[:4])
                            self.tap(device_id, (x1 + x2) // 2, (y1 + y2) // 2)
                            time.sleep(0.5)
                            break
            return True
        return False

    def dismiss_facebook_messenger_if_present(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động thoát khỏi màn hình Messenger / Cài đặt Messenger nếu bị mở nhầm."""
        try:
            # 1. Kiểm tra nếu app Messenger độc lập (com.facebook.orca) đang chiếm foreground
            dumpsys_code, stdout, _ = self.execute_adb(
                device_id, ["shell", "dumpsys", "window", "windows"]
            )
            if dumpsys_code == 0 and "com.facebook.orca" in stdout.casefold():
                if status_callback:
                    status_callback(
                        device_id,
                        "[Facebook] Phát hiện ứng dụng Messenger mở nhầm • Đang thoát về Facebook...",
                    )
                self.keyevent(device_id, 4)
                time.sleep(0.4)
                self.launch_app(device_id, config.FACEBOOK_PACKAGE)
                time.sleep(0.8)
                self.lock_portrait(device_id, retries=3)
                return True

            # 2. Kiểm tra màn hình nội bộ Facebook (com.facebook.katana) bị dẫn sang Cài đặt Messenger / Chat
            root = self._get_facebook_ui_root(device_id, "fb_messenger_chk")
            if root is None:
                return False

            found_messenger = False
            back_coords = None
            width, height = self.get_effective_screen_size(device_id)

            for elem in root.iter():
                text = self._normalize_facebook_text(elem.get("text", ""))
                desc = self._normalize_facebook_text(elem.get("content-desc", ""))
                combined = f"{text} {desc}"

                if any(
                    marker in combined
                    for marker in (
                        "cai dat messenger",
                        "install messenger",
                        "nhan tin hoac goi cho ban be",
                        "mo trong messenger",
                        "open in messenger",
                        "nhan tin tren messenger",
                        "tai messenger",
                        "get messenger",
                    )
                ):
                    found_messenger = True

                if any(
                    back_marker in desc
                    for back_marker in ("tro lai", "back", "dong", "close", "dieu huong len", "navigate up")
                ):
                    bounds = elem.get("bounds", "")
                    m = re.findall(r"\d+", bounds)
                    if len(m) >= 4:
                        x1, y1, x2, y2 = map(int, m[:4])
                        if y1 < int(height * 0.15):
                            back_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

            if found_messenger:
                if status_callback:
                    status_callback(
                        device_id,
                        "[Facebook] Phát hiện màn hình Messenger/Cài đặt Messenger • Đang tự động thoát ra...",
                    )
                if back_coords:
                    self.tap(device_id, back_coords[0], back_coords[1])
                else:
                    self.tap(device_id, int(width * 0.08), int(height * 0.055))
                time.sleep(0.5)
                self.keyevent(device_id, 4)
                time.sleep(0.5)
                self.lock_portrait(device_id, retries=3)
                return True
        except Exception:
            pass
        return False

    def dismiss_facebook_media_viewer_if_present(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động thoát khỏi màn hình xem ảnh toàn màn hình (Photo Viewer)."""
        try:
            root = self._get_facebook_ui_root(device_id, "fb_media_chk")
            if root is None:
                return False

            is_viewer = False
            for elem in root.iter():
                text = (elem.get("text", "") or "").strip()
                desc = (elem.get("content-desc", "") or "").strip()
                combined = f"{text} {desc}".lower()
                if re.search(r"\b\d+\s+(?:of|trong|trên)\s+\d+\b", combined):
                    is_viewer = True
                    break
                if any(
                    marker in combined
                    for marker in (
                        "xem anh", "view photo", "fullscreen", "media_viewer",
                        "dong trinh xem anh", "close photo viewer", "anh 1 tren"
                    )
                ):
                    is_viewer = True
                    break

            if is_viewer:
                if status_callback:
                    status_callback(
                        device_id,
                        "[Facebook] Phát hiện đang ở màn hình xem ảnh • Thoát về trang...",
                    )
                print(f"[Device {device_id[:6]}] Facebook đang ở màn hình xem ảnh • Bấm Back thoát...")
                self.keyevent(device_id, 4)
                time.sleep(0.8)
                return True
        except Exception:
            pass
        return False

    def collapse_statusbar_if_expanded(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động thu gọn thanh thông báo (Notification Shade / Status Bar) nếu bị kéo xuống."""
        try:
            # 1. Gọi lệnh hệ thống Android để thu gọn statusbar/notification shade
            self.execute_adb(device_id, ["shell", "service", "call", "statusbar", "2"])
            self.execute_adb(device_id, ["shell", "cmd", "statusbar", "collapse"])

            # 2. Kiểm tra nếu NotificationShade / StatusBar đang chiếm focus
            code, stdout, _ = self.execute_adb(
                device_id, ["shell", "dumpsys", "window", "windows"]
            )
            if code == 0:
                stdout_lower = stdout.casefold()
                for line in stdout_lower.splitlines():
                    if "mcurrentfocus" in line and any(
                        s in line
                        for s in (
                            "notificationshade",
                            "statusbar",
                            "quick_settings",
                            "trackingview",
                            "com.android.systemui",
                        )
                    ):
                        # Gửi phím Back để ép đóng thanh thông báo
                        self.keyevent(device_id, 4)
                        time.sleep(0.3)
                        self.execute_adb(
                            device_id,
                            ["shell", "service", "call", "statusbar", "2"],
                        )
                        if status_callback:
                            status_callback(
                                device_id,
                                "[Hệ thống] Phát hiện thanh thông báo bị kéo xuống • Đã tự động thu gọn!",
                            )
                        return True
        except Exception:
            pass
        return False

    def perform_facebook_micro_interactions(
        self, device_id, width, height, status_callback=None
    ):
        """Thực hiện vi tương tác Facebook (Like, Click 'Xem thêm' bài viết)."""
        interacted = False
        # 1. Bấm 'Xem thêm' (See more) để mở rộng bài viết dài (tăng Dwell Time)
        if random.random() < 0.35:
            root = self._get_facebook_ui_root(device_id, "fb_seemore")
            if root is not None:
                for elem in root.iter():
                    desc = self._normalize_facebook_text(
                        elem.get("content-desc", "")
                    )
                    text = self._normalize_facebook_text(elem.get("text", ""))
                    if "xem them" in text or "see more" in text or "xem them" in desc:
                        bounds = elem.get("bounds", "")
                        m = re.findall(r"\d+", bounds)
                        if len(m) >= 4:
                            x1, y1, x2, y2 = map(int, m[:4])
                            # Chỉ bấm Xem thêm ở vùng nội dung (y1 > 25% chiều cao) để tránh bấm nhầm ô Bạn đang nghĩ gì
                            if y1 > int(height * 0.25) and y2 < int(height * 0.88):
                                self.tap(
                                    device_id,
                                    (x1 + x2) // 2,
                                    (y1 + y2) // 2,
                                )
                                if status_callback:
                                    status_callback(
                                        device_id,
                                        "[FB Vi tương tác] 📖 Bấm 'Xem thêm' bài viết dài...",
                                    )
                                time.sleep(0.8)
                                interacted = True
                                break

        # 2. Thả Like ngẫu nhiên (tỷ lệ cấu hình)
        if random.random() < config.INTERACTION_LIKE_RATE:
            root = self._get_facebook_ui_root(device_id, "fb_like")
            if root is not None:
                for elem in root.iter():
                    desc = self._normalize_facebook_text(
                        elem.get("content-desc", "")
                    )
                    text = self._normalize_facebook_text(elem.get("text", ""))
                    if "thich" in desc or "like" in desc or "thich" in text or "like" in text:
                        # Tuyệt đối không bấm nếu là nút Nhắn tin / Messenger / Gửi / Bình luận / Chia sẻ
                        if any(
                            k in desc or k in text
                            for k in (
                                "nhan tin", "tin nhan", "messenger", "message",
                                "gui", "binh luan", "comment", "chia se", "share"
                            )
                        ):
                            continue
                        bounds = elem.get("bounds", "")
                        m = re.findall(r"\d+", bounds)
                        if len(m) >= 4:
                            x1, y1, x2, y2 = map(int, m[:4])
                            cx = (x1 + x2) // 2
                            # Nút Thích bài viết chuẩn luôn ở 40% bề ngang bên trái
                            if (
                                y1 > int(height * 0.25)
                                and y2 < int(height * 0.88)
                                and cx < int(width * 0.40)
                            ):
                                # Trích xuất chữ ký bài viết từ các đoạn text nằm phía trên nút Thích
                                post_texts = []
                                reaction_bar_liked = False
                                for other_elem in root.iter():
                                    other_bounds = other_elem.get("bounds", "")
                                    om = re.findall(r"\d+", other_bounds)
                                    if len(om) >= 4:
                                        _ox1, oy1, _ox2, oy2 = map(int, om[:4])
                                        if y1 - int(height * 0.40) <= oy1 < y1:
                                            otext = other_elem.get("text", "").strip()
                                            odesc = other_elem.get("content-desc", "").strip()
                                            content = otext or odesc
                                            if content and len(content) > 3:
                                                norm_c = self._normalize_facebook_text(content)
                                                # Kiểm tra thanh cảm xúc ngay trên nút Thích có "Bạn và..." / "You and..."
                                                if y1 - int(height * 0.12) <= oy1 < y1:
                                                    if (
                                                        norm_c.startswith("ban va ")
                                                        or " ban va " in norm_c
                                                        or norm_c.startswith("you and ")
                                                        or " you and " in norm_c
                                                    ):
                                                        reaction_bar_liked = True
                                                # Lọc bỏ các con số đếm lượt thích/bình luận động để post_sig luôn cố định
                                                if not any(
                                                    dyn in norm_c
                                                    for dyn in (
                                                        "nguoi khac", "luot thich", "binh luan",
                                                        "luot chia se", "others", "comments", "shares"
                                                    )
                                                ):
                                                    post_texts.append(content)

                                if post_texts:
                                    combined = " ".join(post_texts[:5])
                                    post_sig = hashlib.md5(combined.encode("utf-8", errors="ignore")).hexdigest()[:16]
                                else:
                                    post_sig = f"post_y_{y1 // 50}"

                                # Bảo vệ chống hủy Like: Nếu nút đã ở trạng thái Đã thích -> Bỏ qua ngay
                                is_already_liked = (
                                    reaction_bar_liked
                                    or elem.get("selected", "").lower() == "true"
                                    or elem.get("checked", "").lower() == "true"
                                    or any(
                                        k in desc or k in text
                                        for k in (
                                            "da thich", "đã thích", "liked",
                                            "bo thich", "bỏ thích", "go thich", "gỡ thích", "unlike",
                                            "da bay to", "reacted", "nhan dup de bo thich", "double tap to unlike"
                                        )
                                    )
                                )
                                if is_already_liked:
                                    interaction_tracker.record_interaction(
                                        device_id, "facebook", post_sig, "like"
                                    )
                                    if status_callback:
                                        status_callback(
                                            device_id,
                                            "[FB Vi tương tác] ⏭️ Bài viết đã Thích trước đó • Bỏ qua, tránh hủy Like.",
                                        )
                                    continue

                                # Kiểm tra bộ nhớ lịch sử tương tác của thiết bị
                                if interaction_tracker.has_interacted(
                                    device_id, "facebook", post_sig, "like"
                                ):
                                    if status_callback:
                                        status_callback(
                                            device_id,
                                            "[FB Vi tương tác] ⏭️ Thiết bị đã từng Like bài viết này • Bỏ qua.",
                                        )
                                    continue

                                self.tap(
                                    device_id,
                                    cx,
                                    (y1 + y2) // 2,
                                )
                                interaction_tracker.record_interaction(
                                    device_id, "facebook", post_sig, "like"
                                )
                                if status_callback:
                                    status_callback(
                                        device_id,
                                        "[FB Vi tương tác] 👍 Thả Like bài viết mới trên Page...",
                                    )
                                time.sleep(0.8)
                                return True
        return interacted

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
            if self.is_screen_landscape(device_id):
                self.keyevent(device_id, 4)
                time.sleep(0.3)
                self.lock_portrait(device_id, retries=2, force=True)
            # Tự động thu gọn thanh thông báo và thoát Messenger/Bài viết mới nếu bị mở nhầm
            try:
                self.collapse_statusbar_if_expanded(
                    device_id, status_callback=status_callback
                )
            except Exception:
                pass
            try:
                self.dismiss_facebook_messenger_if_present(
                    device_id, status_callback=status_callback
                )
            except Exception:
                pass
            try:
                self.dismiss_facebook_composer_if_present(
                    device_id, status_callback=status_callback
                )
            except Exception:
                pass
            try:
                self.dismiss_facebook_media_viewer_if_present(
                    device_id, status_callback=status_callback
                )
            except Exception:
                pass
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
            if label == "target_page":
                d_min = getattr(config, "FACEBOOK_STEP3_POST_DWELL_MIN", 15)
                d_max = getattr(config, "FACEBOOK_STEP3_POST_DWELL_MAX", 30)
                dwell = min(float(random.randint(d_min, d_max)), remaining)
            else:
                dwell = min(float(random.randint(6, 15)), remaining)
            if status_callback:
                status_callback(
                    device_id,
                    f"Xem {label_name} lượt {item_index} ({int(dwell)}s) • "
                    f"còn {int(remaining)}s...",
                )
            # Kích hoạt vi tương tác khi đang ở Page mục tiêu
            if label == "target_page":
                try:
                    self.perform_facebook_micro_interactions(
                        device_id, width, height, status_callback=status_callback
                    )
                except Exception:
                    pass

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
                try:
                    self.collapse_statusbar_if_expanded(
                        device_id, status_callback=status_callback
                    )
                except Exception:
                    pass
                try:
                    self.dismiss_facebook_messenger_if_present(
                        device_id, status_callback=status_callback
                    )
                except Exception:
                    pass
                try:
                    self.dismiss_facebook_composer_if_present(
                        device_id, status_callback=status_callback
                    )
                except Exception:
                    pass
                try:
                    self.dismiss_facebook_media_viewer_if_present(
                        device_id, status_callback=status_callback
                    )
                except Exception:
                    pass
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
            self.lock_portrait(device_id, retries=3, force=True)
            if not self.wait_for_tiktok_foreground(device_id):
                if status_callback:
                    status_callback(
                        device_id,
                        f"[TikTok] Đang ổn định ứng dụng sau chuyển cảnh "
                        f"({attempt + 1}/{max(1, attempts)})...",
                    )
                self.launch_tiktok(device_id)
                self.lock_portrait(device_id, retries=3, force=True)
                time.sleep(1.0)
            if not self.wait_for_tiktok_foreground(device_id):
                continue
            if not self.ensure_tiktok_home_feed(device_id):
                continue
            self.lock_portrait(device_id, retries=3, force=True)
            if self.is_screen_landscape(device_id):
                self.keyevent(device_id, 4)
                time.sleep(0.3)
                self.lock_portrait(device_id, retries=3, force=True)
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
        self.recover_tiktok_if_blocked_by_captcha_or_link(
            device_id, status_callback=status_callback
        )
        if self.advance_tiktok_feed(device_id):
            return True
        if status_callback:
            status_callback(
                device_id,
                "[TikTok] Feed đứng • Back và mở lại TikTok để thử lại...",
            )
        self.recover_tiktok_if_blocked_by_captcha_or_link(
            device_id, status_callback=status_callback
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
            if self.is_screen_landscape(device_id):
                self.keyevent(device_id, 4)
                time.sleep(0.3)
                self.lock_portrait(device_id, retries=2, force=True)
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
        """Xác minh đã vào đúng profile Page mục tiêu, không còn ở danh sách kết quả hay trang khác."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_fb_profile_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_fb_profile_{safe_device_id}.xml")
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

            # Các thương hiệu ngoại lai / không liên quan tuyệt đối từ chối
            unrelated_brands = (
                "sony", "samsung", "apple", "xiaomi", "honda", "yamaha",
                "toyota", "mercedes", "oto", "xe", "dien may", "the gioi di dong"
            )

            # Thu thập nhãn từ các node KHÔNG PHẢI EditText (để loại bỏ ô search bar vẫn lưu truy vấn)
            non_edit_texts = []
            has_unrelated_brand = False

            for node in root.iter():
                cls = node.get("class", "")
                if cls.endswith("EditText") or "edittext" in cls.lower():
                    continue
                txt = (node.get("text") or "").strip()
                desc = (node.get("content-desc") or "").strip()
                combined = f"{txt} {desc}".strip()
                if not combined:
                    continue
                norm = self._normalize_facebook_text(combined)
                if not norm:
                    continue
                non_edit_texts.append(norm)

                norm_tokens = set(norm.split())
                if any(ub in norm_tokens for ub in unrelated_brands):
                    has_unrelated_brand = True

            if has_unrelated_brand:
                return False

            all_non_edit_text = " ".join(non_edit_texts)
            target_norm = self._normalize_facebook_text(target_phrase)
            target_tokens = target_norm.split()

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
                "thich",
                "like",
                "danh gia",
                "reviews",
                "gioi thieu",
                "anh",
                "photos",
                "video",
                "videos",
                "trang chu",
                "home",
            )
            has_profile_marker = any(marker in all_non_edit_text for marker in profile_markers)
            if not has_profile_marker:
                return False

            # Kiểm tra tên Page mục tiêu:
            # 1. Nếu target có 'khai' và 'hoan':
            if "khai" in target_tokens and "hoan" in target_tokens:
                # Bắt buộc phải có ít nhất 1 node chứa cả 'khai' và 'hoan', với 'khai' đứng trước 'hoan'
                has_khai_hoan_node = False
                for t in non_edit_texts:
                    t_tokens = set(t.split())
                    if "khai" in t_tokens and "hoan" in t_tokens:
                        if t.find("khai") < t.find("hoan"):
                            has_khai_hoan_node = True
                            break
                if not has_khai_hoan_node:
                    return False
                return True

            # 2. Nếu target là thương hiệu khác:
            # Bắt buộc ít nhất 1 node phải chứa core tokens của target
            core_tokens = [t for t in target_tokens if t not in ("spa", "clinic", "cham", "soc", "da", "y", "khoa")]
            if not core_tokens:
                core_tokens = target_tokens

            has_target_node = False
            for t in non_edit_texts:
                t_tokens = set(t.split())
                if all(ct in t_tokens for ct in core_tokens):
                    has_target_node = True
                    break
                overlap = sum(1 for token in target_tokens if token in t_tokens)
                if len(target_tokens) >= 2 and overlap >= len(target_tokens) * 0.6:
                    has_target_node = True
                    break

            if has_target_node:
                return True

            # Fallback kiểm tra qua exact_page_name nếu có
            if exact_page_name:
                exact_norm = self._normalize_facebook_text(exact_page_name)
                exact_tokens = exact_norm.split()
                for t in non_edit_texts:
                    t_tokens = set(t.split())
                    if sum(1 for et in exact_tokens if et in t_tokens) >= max(2, int(len(exact_tokens) * 0.5)):
                        return True

            return False
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
            try:
                print(f"[Device {device_id[:6]}] {message}")
            except Exception:
                pass
            if status_callback:
                status_callback(device_id, message)

        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise RuntimeError("Bị dừng bởi người dùng")

        def ensure_facebook_action_context(step_name):
            """Phục hồi Facebook trước khi thao tác nhập liệu của từng bước."""
            self.lock_portrait(device_id, retries=3)
            self.collapse_statusbar_if_expanded(device_id, status_callback=status_callback)
            self.dismiss_facebook_messenger_if_present(device_id, status_callback=status_callback)
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

        if not seeds:
            update_status("Lỗi Facebook: Chưa nhập từ khóa mồi Facebook")
            return False, "Chưa nhập từ khóa mồi Facebook"
        if not targets:
            update_status("Lỗi Facebook: Chưa nhập Page target Facebook")
            return False, "Chưa nhập Page target Facebook"

        max_flow_attempts = 2
        for flow_attempt in range(1, max_flow_attempts + 1):
            try:
                if flow_attempt > 1:
                    check_cancelled()
                    update_status(
                        f"[Facebook] Tự động thử lại quy trình chịu lỗi (Lần {flow_attempt}/{max_flow_attempts})..."
                    )
                    self.keyevent(device_id, 4)
                    time.sleep(1.0)
                    self.dismiss_facebook_blocking_popups(device_id, status_callback=update_status)
                    self.return_facebook_home_before_search(device_id)

                seed_keyword = random.choice(seeds)
                target_phrase = random.choice(targets)
                if len(targets) > 1:
                    update_status(
                        f"[Facebook] Chọn ngẫu nhiên Page mục tiêu "
                        f"'{target_phrase}' (1/{len(targets)} page)..."
                    )
                exact_page_name = self._resolve_facebook_exact_page_name(
                    target_phrase
                )
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
                self.dismiss_facebook_blocking_popups(device_id, status_callback=update_status)
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
                if not self.return_facebook_home_before_search(device_id):
                    update_status("[Facebook B2] Đang khôi phục về Home...")
                    self.keyevent(device_id, 4)
                    time.sleep(0.8)
                    self.return_facebook_home_before_search(device_id)
                update_status(
                    f"[Facebook B2] Tìm từ khóa mồi '{seed_keyword}'..."
                )
                if not self.find_and_click_facebook_search(device_id):
                    update_status("[Facebook B2] Thử mở lại ô Search Facebook lần 2...")
                    self.keyevent(device_id, 4)
                    time.sleep(0.5)
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
                if not self.find_and_click_facebook_search(
                    device_id, allow_recent_fallback=True
                ):
                    update_status("[Facebook B3] Thử mở lại ô Search Facebook lần 2...")
                    self.keyevent(device_id, 4)
                    time.sleep(0.5)
                    if not self.find_and_click_facebook_search(
                        device_id, allow_recent_fallback=True
                    ):
                        raise RuntimeError("Không mở lại được ô Search Facebook")
                self.replace_facebook_search_text(
                    device_id,
                    target_phrase,
                    allow_transient_foreground=True,
                )
                self.submit_facebook_search(
                    device_id, allow_transient_foreground=True
                )
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
                for target_attempt in range(3):
                    if self.find_and_click_facebook_page(
                        device_id,
                        target_phrase,
                        exact_page_name=exact_page_name,
                        randomize_matching_pages=True,
                    ):
                        page_clicked = True
                        break
                    if target_attempt < 2:
                        check_cancelled()
                        update_status(
                            f"[Facebook B3] Chưa thấy Page ở lượt {target_attempt + 1} • "
                            "cuộn kết quả tìm kiếm và thử lại..."
                        )
                        ensure_facebook_action_context("Facebook B3 retry")
                        if target_attempt == 0:
                            if self.find_and_click_facebook_search(
                                device_id, allow_recent_fallback=True
                            ):
                                self.replace_facebook_search_text(
                                    device_id,
                                    target_phrase,
                                    allow_transient_foreground=True,
                                )
                                self.submit_facebook_search(
                                    device_id, allow_transient_foreground=True
                                )
                            self.facebook_loading_delay(
                                device_id,
                                "target_results",
                                status_callback=status_callback,
                                is_cancelled=is_cancelled,
                            )
                        else:
                            width_fb, height_fb = self.get_effective_screen_size(device_id)
                            self.swipe(
                                device_id,
                                width_fb // 2,
                                int(height_fb * 0.75),
                                width_fb // 2,
                                int(height_fb * 0.35),
                                duration=600,
                            )
                            time.sleep(1.5)
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
                    update_status(
                        f"[Facebook B3] Chưa vào đúng Page '{target_phrase}' "
                        f"hoặc mở nhầm trang khác • Bấm Back thoát ra..."
                    )
                    self.keyevent(device_id, 4)
                    time.sleep(1.0)
                    self.dismiss_facebook_blocking_popups(device_id, status_callback=update_status)
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
                if is_cancelled and is_cancelled():
                    message = str(exc)
                    update_status(f"Dừng Facebook: {message}")
                    return False, message
                if "Bị dừng bởi người dùng" in str(exc):
                    return False, str(exc)
                if flow_attempt < max_flow_attempts:
                    update_status(
                        f"[Facebook] Gặp lỗi ở lượt {flow_attempt}: {exc} • "
                        f"Đang phục hồi và tự động thử lại chịu lỗi..."
                    )
                    self.keyevent(device_id, 4)
                    time.sleep(1.0)
                    self.dismiss_facebook_blocking_popups(device_id, status_callback=update_status)
                    continue
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
        """Lấy kích thước tọa độ đang được Android dùng sau khi áp dụng wm override (luôn đảm bảo chiều dọc)."""
        output = self._get_wm_size_output(device_id)
        override = re.search(
            r"Override size:\s*(\d+)x(\d+)", output, re.IGNORECASE
        )
        if override:
            w, h = int(override.group(1)), int(override.group(2))
        else:
            physical = re.search(
                r"Physical size:\s*(\d+)x(\d+)", output, re.IGNORECASE
            )
            if physical:
                w, h = int(physical.group(1)), int(physical.group(2))
            else:
                size = re.search(r"size:\s*(\d+)x(\d+)", output)
                if size:
                    w, h = int(size.group(1)), int(size.group(2))
                else:
                    w, h = 1080, 1920
        if w > h:
            try:
                self.lock_portrait(device_id, force=True)
            except Exception:
                pass
            w, h = min(w, h), max(w, h)
        return w, h

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
            width, height = self.get_effective_screen_size(device_id)
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
                    if not (30 < cy < max(250, int(height * 0.14))):
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
            # Loại thanh tìm kiếm/bộ lọc và thanh điều hướng cuối màn hình (thích ứng 1080p và 1440p).
            if cx <= 0 or not 220 < cy < 2400:
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
                            _w, _h = self.get_effective_screen_size(device_id)
                            # Đảm bảo vị trí nằm dưới header tìm kiếm (y > 200) và không chạm vùng phễu lọc góc trên bên phải
                            if 200 < cy < max(1600, int(_h * 0.85)):
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
                            _w, _h = self.get_effective_screen_size(device_id)
                            # Ô tìm kiếm trong Shop luôn nằm ở vùng thanh tiêu đề đỉnh (y < 200)
                            if 30 < cy < max(200, int(_h * 0.12)):
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
                
                # Kiểm tra xem có popup hỏi quyền vị trí hệ thống thực tế không
                for elem in root.iter():
                    text = (elem.get('text', '') or elem.get('content-desc', '')).lower()
                    pkg = (elem.get('package', '') or '').lower()
                    is_perm_pkg = any(p in pkg for p in ["permissioncontroller", "packageinstaller"])
                    if is_perm_pkg or any(k in text for k in ["truy cập vào vị trí", "cho phép truy cập vị trí", "allow location access"]):
                        found_popup = True

                    if any(k in text for k in ["không hỏi lại", "don't ask again", "remember choice"]):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            if x2 > x1 and y2 > y1:
                                dont_ask_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

                    if any(k in text for k in ["từ chối", "deny", "don't allow"]):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            if x2 > x1 and y2 > y1:
                                deny_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass

        # Tuyệt đối KHÔNG bấm đoán tọa độ nếu không tìm thấy nút thực tế trên DOM!
        if (found_popup and deny_coords) or deny_coords or dont_ask_coords:
            print(f"[Device {device_id[:6]}] Phát hiện Popup hỏi quyền Vị trí! Tiến hành Từ chối...")
            if dont_ask_coords:
                self.tap(device_id, dont_ask_coords[0], dont_ask_coords[1])
                time.sleep(0.5)

            if deny_coords:
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
            "cap nhat tiktok",
            "update tiktok",
            "phien ban moi",
            "new version",
            "luu thong tin dang nhap",
            "save login info",
            "bat thong bao",
            "turn on notifications",
            "dong bo danh ba",
            "sync contacts",
            "tim ban be",
            "find friends",
            "verify to continue",
            "drag the puzzle",
            "puzzle piece",
            "puzzle",
            "xac minh de tiep tuc",
            "keo manh ghep",
            "keo thanh truot",
            "xac minh",
            "xac thuc",
            "verification",
            "dang tren tiktok",
            "mo tiktok",
            "kham pha them",
            "www.tiktok.com",
            "tiktok.com",
        )
        close_markers = {
            "close", "dong", "not now", "de sau", "later", "skip",
            "bo qua", "cancel", "huy", "mo tiktok", "open tiktok",
            "luc khac", "khong", "khong phai bay gio", "khong cam on", "no thanks",
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

    def _safe_status_callback(self, callback, device_id, message):
        """Gọi callback an toàn bất kể nhận 1 tham số (message) hay 2 tham số (device_id, message)."""
        if not callback:
            return
        try:
            callback(device_id, message)
        except TypeError:
            try:
                callback(message)
            except Exception:
                pass
        except Exception:
            pass

    def recover_tiktok_if_blocked_by_captcha_or_link(
        self, device_id, status_callback=None
    ):
        """
        Tự động phát hiện và xử lý màn hình kẹt theo đúng kích thước từng thiết bị:
        1. Popup Vị trí ('Xem nội dung phù hợp và địa điểm lân cận'): Bấm ngay nút 'Hủy'.
        2. Captcha kéo mảnh ghép ('Xác minh để tiếp tục:'): Bấm dấu 'X' góc trên bên phải khung captcha, thoát Live nếu dính, tiếp tục luồng bơm.
        3. Nhảy link ra ngoài (Chrome, Browser, Webview 'www.tiktok.com'): Bấm 'Mở TikTok' hoặc force-stop trình duyệt ngoài và đưa app native về lại.
        """
        width, height = self.get_effective_screen_size(device_id)
        browser_pkgs = [
            "com.android.chrome",
            "com.google.android.apps.chrome",
            "com.sec.android.app.sbrowser",
            "com.android.browser",
            "org.chromium.webview_shell",
            "com.opera.browser",
            "com.opera.mini.native",
            "com.brave.browser",
            "com.duckduckgo.mobile.android",
            "com.microsoft.emmx",
            "com.heytap.browser",
            "com.vivo.browser",
            "com.coloros.browser",
            "com.mi.globalbrowser",
        ]
        fg_pkg = self.get_current_foreground_package(device_id)
        if fg_pkg and fg_pkg.casefold() not in (
            config.TIKTOK_PACKAGE.casefold(),
            config.TIKTOK_PACKAGE_ALT.casefold(),
        ):
            if fg_pkg not in browser_pkgs:
                browser_pkgs.append(fg_pkg)

        # 1. Kiểm tra nếu app bị văng ra trình duyệt ngoài hoặc app khác
        if not self.is_tiktok_in_foreground(device_id):
            self._safe_status_callback(
                status_callback,
                device_id,
                "[TikTok Recovery] Phát hiện bị nhảy link ra ngoài ứng dụng! Đang mở lại TikTok...",
            )
            for b_pkg in browser_pkgs:
                self.execute_adb(device_id, ["shell", "am", "force-stop", b_pkg])
            time.sleep(0.3)
            self.keyevent(device_id, 4)
            time.sleep(0.3)
            self.launch_tiktok(device_id)
            time.sleep(1.5)
            self.ensure_tiktok_home_feed(device_id)
            return True

        # 2. Kiểm tra foreground activity (nếu đang ở Webview / CrossPlatformActivity)
        activity = (self.get_tiktok_foreground_activity(device_id) or "").casefold()
        is_webview = any(
            kw in activity
            for kw in (
                "crossplatform",
                "webview",
                "browser",
                "secshare",
                "compliance",
            )
        )

        # 3. Đọc UI hierarchy để phân loại chính xác các trường hợp
        root = self._get_tiktok_ui_root(device_id, "tt_block_check")
        has_location_popup = False
        cancel_location_node = None
        has_age_or_reward_popup = False
        cancel_age_node = None
        has_captcha = False
        has_webview_content = is_webview
        close_node = None
        open_tiktok_node = None
        later_node = None

        if root is not None:
            location_popup_markers = (
                "dia diem lan can",
                "xem noi dung phu hop",
                "truy cap vi tri",
                "vi tri > trong khi su dung",
                "tim kiem noi dung o gan",
                "cho phep truy cap vi tri",
                "ket qua tot hon",
                "dia diem va bai dang pho bien",
                "khong bao gio",
                "hoi vao lan sau",
                "mo cai dat",
            )
            age_or_reward_markers = (
                "du 18 tuoi",
                "18 tuoi tro len",
                "phan thuong tiktok",
                "xac nhan rang ban du 18 tuoi",
                "dieu khoan va dieu kien",
            )
            captcha_markers = (
                "verify to continue",
                "drag the puzzle",
                "puzzle piece",
                "puzzle",
                "xac minh de tiep tuc",
                "keo manh ghep",
                "keo thanh truot",
                "xac minh",
                "xac thuc",
                "verification",
            )
            webview_markers = (
                "www.tiktok.com",
                "tiktok.com",
                "dang tren tiktok",
                "mo tiktok",
                "kham pha them",
                "de sau",
                "tan huong trai nghiem",
            )

            parent_map = {
                child: parent for parent in root.iter() for child in parent
            }

            for node in root.iter():
                text_raw = f"{node.get('text', '')} {node.get('content-desc', '')}"
                label = self._normalize_tiktok_identity(text_raw)
                resource_id = node.get("resource-id", "").casefold()

                # Kiểm tra Popup Vị trí
                if any(marker in label for marker in location_popup_markers):
                    has_location_popup = True

                # Kiểm tra Popup 18+ / Phần thưởng TikTok
                if any(marker in label for marker in age_or_reward_markers):
                    has_age_or_reward_popup = True

                if label in ("huy", "cancel", "de sau", "khong phai bay gio", "khong bao gio", "hoi vao lan sau", "luc khac", "bo qua", "skip"):
                    if not cancel_location_node:
                        cancel_location_node = node
                    if not cancel_age_node:
                        cancel_age_node = node

                # Kiểm tra Captcha
                if any(marker in label for marker in captcha_markers) or "captcha" in resource_id:
                    has_captcha = True

                # Kiểm tra Webview / Nhảy link
                if any(marker in label for marker in webview_markers):
                    has_webview_content = True

                if "mo tiktok" in label and not open_tiktok_node:
                    clickable = node
                    while clickable is not None and clickable.get("clickable", "false") != "true":
                        clickable = parent_map.get(clickable)
                    open_tiktok_node = clickable if clickable is not None else node

                if "de sau" in label and not later_node:
                    clickable = node
                    while clickable is not None and clickable.get("clickable", "false") != "true":
                        clickable = parent_map.get(clickable)
                    later_node = clickable if clickable is not None else node

                is_close_label = any(
                    c in label for c in ("close", "dong", "cancel", "huy", "skip", "bo qua")
                )
                is_close_id = any(
                    c in resource_id for c in ("close", "btn_close", "cancel", "dismiss")
                )
                bounds = node.get("bounds", "")
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    node_w = x2 - x1
                    node_h = y2 - y1
                    if (is_close_label or is_close_id or label == "x") and node_w < int(width * 0.20) and node_h < int(height * 0.12):
                        close_node = node

        # 4. TRƯỜNG HỢP 1: Xử lý Popup Vị trí (Ảnh 2, Ảnh 3, Ảnh 4) -> Bấm HỦY hoặc dấu X hoặc Back
        if has_location_popup:
            self._safe_status_callback(
                status_callback,
                device_id,
                "[TikTok Recovery] Phát hiện Popup vị trí 'Địa điểm lân cận / Ở gần' • Tự động đóng...",
            )
            closed = False
            if cancel_location_node is not None:
                coords = self._element_center(cancel_location_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                    closed = True
            elif close_node is not None:
                coords = self._element_center(close_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                    closed = True
            if not closed:
                # Tọa độ dấu X trên popup trắng (Ảnh 3, Ảnh 4): x = 78.5% width, y = 40.5% height
                self.tap(device_id, int(width * 0.785), int(height * 0.405))
            time.sleep(0.5)
            self.keyevent(device_id, 4)
            time.sleep(0.8)
            return True

        # 5. TRƯỜNG HỢP 2: Xử lý Popup Giới hạn 18 tuổi / Phần thưởng TikTok (Ảnh 5)
        if has_age_or_reward_popup:
            self._safe_status_callback(
                status_callback,
                device_id,
                "[TikTok Recovery] Phát hiện Popup 'Đủ 18 tuổi / Phần thưởng TikTok' • Tự động bấm HỦY và thoát...",
            )
            if cancel_age_node is not None:
                coords = self._element_center(cancel_age_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                else:
                    self.tap(device_id, int(width * 0.35), int(height * 0.63))
            else:
                self.tap(device_id, int(width * 0.35), int(height * 0.63))
            time.sleep(0.8)
            self.keyevent(device_id, 4)
            time.sleep(0.8)
            return True

        # 5. TRƯỜNG HỢP 2: Xử lý Captcha xác minh (Puzzle) -> Bấm dấu X góc trên phải khung captcha
        if has_captcha:
            self._safe_status_callback(
                status_callback,
                device_id,
                "[TikTok Recovery] Phát hiện Captcha kéo mảnh ghép • Tự động bấm dấu X để tắt...",
            )
            # Ưu tiên tìm node nút đóng hoặc dùng tọa độ chuẩn xác theo tỷ lệ màn hình thiết bị
            captcha_x_tapped = False
            if close_node is not None:
                coords = self._element_center(close_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                    captcha_x_tapped = True
            elif root is not None:
                for n in root.iter():
                    bounds = n.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        if (int(width * 0.70) <= cx <= int(width * 0.96)) and (int(height * 0.10) <= cy <= int(height * 0.45)):
                            if (x2 - x1) < int(width * 0.22) and (y2 - y1) < int(height * 0.15):
                                self.tap(device_id, cx, cy)
                                captcha_x_tapped = True
                                break
            if not captcha_x_tapped:
                # Tọa độ dấu X trên khung Captcha TikTok chuẩn xác theo kích thước từng thiết bị (x=83.5%, y=33.8%)
                self.tap(device_id, int(width * 0.835), int(height * 0.338))

            self.keyevent(device_id, 4)
            time.sleep(1.0)
            self.lock_portrait(device_id, retries=3)

            # Kiểm tra xem Captcha đã tắt chưa
            root_after = self._get_tiktok_ui_root(device_id, "tt_captcha_recheck")
            still_captcha = False
            if root_after is not None:
                for node in root_after.iter():
                    label = self._normalize_tiktok_identity(
                        f"{node.get('text', '')} {node.get('content-desc', '')}"
                    )
                    if any(marker in label for marker in ("verify to continue", "drag the puzzle", "puzzle", "xac minh de tiep tuc", "keo manh ghep")):
                        still_captcha = True
                        break

            if still_captcha:
                self._safe_status_callback(
                    status_callback,
                    device_id,
                    "[TikTok Recovery] Captcha bắt buộc không tắt được • Khởi động lại TikTok...",
                )
                self.execute_adb(device_id, ["shell", "am", "force-stop", config.TIKTOK_PACKAGE])
                self.execute_adb(device_id, ["shell", "am", "force-stop", config.TIKTOK_PACKAGE_ALT])
                time.sleep(1.0)
                self.launch_tiktok(device_id)
            else:
                # Nếu đã tắt captcha thành công, kiểm tra nếu màn hình đằng sau đang là Live -> Back thoát Live về luồng
                is_live = False
                if root_after is not None:
                    for n in root_after.iter():
                        lbl = self._normalize_tiktok_identity(f"{n.get('text', '')} {n.get('content-desc', '')}")
                        if any(k in lbl for k in ("chu phong", "tha tim", "live thinh hanh", "top phong live")):
                            is_live = True
                            break
                if is_live:
                    self._safe_status_callback(
                        status_callback,
                        device_id,
                        "[TikTok Recovery] Đang ở màn hình Live • Bấm Back thoát Live về lại luồng...",
                    )
                    self.keyevent(device_id, 4)
                    time.sleep(0.8)

            return True

        # 6. TRƯỜNG HỢP 3: Xử lý Webview / Nhảy link ra ngoài (www.tiktok.com / popup 'Mở TikTok')
        if has_webview_content:
            self._safe_status_callback(
                status_callback,
                device_id,
                "[TikTok Recovery] Phát hiện nhảy link/Webview 'www.tiktok.com' • Đang đưa về ứng dụng native...",
            )
            # Thử bấm Mở TikTok hoặc Đóng nếu có nút
            if open_tiktok_node is not None:
                coords = self._element_center(open_tiktok_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                    time.sleep(0.8)
            elif close_node is not None:
                coords = self._element_center(close_node)
                if coords:
                    self.tap(device_id, coords[0], coords[1])
                    time.sleep(0.5)

            # Ép đóng sạch toàn bộ trình duyệt ngoài
            for b_pkg in browser_pkgs:
                self.execute_adb(device_id, ["shell", "am", "force-stop", b_pkg])
            self.keyevent(device_id, 4)
            time.sleep(0.4)
            self.lock_portrait(device_id, retries=3)

            new_activity = (self.get_tiktok_foreground_activity(device_id) or "").casefold()
            if any(kw in new_activity for kw in ("crossplatform", "webview", "browser")) or not self.is_tiktok_in_foreground(device_id):
                self.keyevent(device_id, 4)
                time.sleep(0.5)
                self.launch_tiktok(device_id)
                time.sleep(1.0)

            self.ensure_tiktok_home_feed(device_id)
            return True

        return False

    def launch_tiktok(self, device_id):
        """Mở ứng dụng TikTok (thử com.ss.android.ugc.trill trước, dự phòng com.zhiliaoapp.musically)"""
        self.dismiss_system_usb_storage_popup(device_id)
        self.lock_portrait(device_id, retries=3, force=True)
        code, stdout, stderr = self.launch_app(device_id, config.TIKTOK_PACKAGE)
        if code != 0 or "Error" in (stdout or ""):
            self.launch_app(device_id, config.TIKTOK_PACKAGE_ALT)
        # TikTok bật lại accelerometer_rotation khi Splash/Main activity đổi.
        self.lock_portrait(device_id, retries=3, force=True)
        time.sleep(1.0)
        self.lock_portrait(device_id, retries=3, force=True)
        time.sleep(2.5)
        self.lock_portrait(device_id, retries=3, force=True)
        # Tự động từ chối popup USB MTP và vị trí nếu hiển thị lúc mở app
        self.dismiss_system_usb_storage_popup(device_id)
        self.dismiss_tiktok_location_popup(device_id)
        self.dismiss_tiktok_blocking_popup(device_id)
        self.lock_portrait(device_id, retries=3, force=True)
        if self.is_screen_landscape(device_id):
            self.keyevent(device_id, 4)
            time.sleep(0.3)
            self.lock_portrait(device_id, retries=3, force=True)

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

    def get_current_foreground_package(self, device_id):
        """Lấy package đang chiếm foreground màn hình (bất kể app/trình duyệt nào)."""
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
                match = re.search(r"([a-zA-Z0-9._]+)/[^\s}]+", line)
                if match:
                    pkg = match.group(1).strip()
                    if pkg and not pkg.startswith("android") and "systemui" not in pkg.lower():
                        return pkg
        return None

    def _get_tiktok_search_icon_coords(self, device_id):
        """Đọc tọa độ Search TikTok ở header; trả None nếu XML đang bận."""
        safe_device_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", device_id)
        remote_xml = f"/sdcard/dump_tiktok_search_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_dump_tt_search_{safe_device_id}.xml")
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
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                width, height = self.get_effective_screen_size(device_id)
                if cy < max(300, int(height * 0.15)) and cx >= int(width * 0.65):
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
        """Mở Search; nếu kẹt Search cũ, Captcha hoặc Webview thì tự động thoát và mở lại."""
        for attempt in range(2):
            self.dismiss_tiktok_location_popup(device_id)
            self.dismiss_tiktok_blocking_popup(device_id)
            self.recover_tiktok_if_blocked_by_captcha_or_link(device_id)

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
                self.recover_tiktok_if_blocked_by_captcha_or_link(device_id)
                if not self._recover_tiktok_search_with_one_back(device_id):
                    return False
                continue
            return False
        return False

    def get_tiktok_search_input_state(self, device_id):
        """Đọc tọa độ, nội dung và trạng thái focus của ô Search TikTok."""
        width, _height = self.get_effective_screen_size(device_id)
        safe_device_id = re.sub(r'[^a-zA-Z0-9_.-]', '_', device_id)
        xml_file = f"/sdcard/dump_tt_input_{safe_device_id}.xml"
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_dump_tt_input_{safe_device_id}.xml")
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        dump_code, _, _ = self.execute_adb(
            device_id, ["shell", "uiautomator", "dump", xml_file]
        )
        if dump_code != 0:
            return None

        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])

        candidates = []
        try:
            if pull_code != 0 or not os.path.exists(local_xml):
                return None
            root = ET.parse(local_xml).getroot()
            for elem in root.iter():
                class_name = elem.get("class", "").lower()
                resource_id = elem.get("resource-id", "").lower()
                content_desc = elem.get("content-desc", "").lower()
                identity = f"{resource_id} {content_desc}"
                if any(
                    marker in identity
                    for marker in (
                        "search_more", "more_options", "more options",
                        "filter", "feedback", "overflow", "menu_more",
                    )
                ):
                    continue
                editable = elem.get("editable", "").lower() == "true"
                searchable = any(
                    marker in identity
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
                if cy > max(350, int(_height * 0.16)):
                    continue
                # Nút ba chấm nằm sát mép phải và cũng có thể chứa chữ
                # "search" trong resource-id. Ô nhập thật luôn bắt đầu ở nửa
                # trái và đủ rộng để chứa query.
                if x1 >= int(width * 0.78):
                    continue
                if (
                    not editable
                    and "edittext" not in class_name
                    and (x2 - x1) < int(width * 0.30)
                ):
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

    def dismiss_tiktok_search_filter_panel(self, device_id):
        """Đóng bảng Filters nếu còn sót từ phiên lỗi, không tap mù."""
        root = self._get_tiktok_ui_root(device_id, "tt_filter_panel")
        if root is None:
            return False
        labels = {
            self._normalize_tiktok_text(
                f"{node.get('text', '')} {node.get('content-desc', '')}"
            )
            for node in root.iter()
        }
        labels.discard("")
        has_filters = any(
            label in ("filters", "filter", "bộ lọc", "bo loc")
            for label in labels
        )
        has_feedback = any(
            "share feedback" in label or "phản hồi" in label
            for label in labels
        )
        if not (has_filters and has_feedback):
            return False
        self.keyevent(device_id, 4)
        time.sleep(0.6)
        return True

    def focus_tiktok_existing_search_bar(self, device_id):
        """Focus query B2 để nhập target; tuyệt đối tránh nút ba chấm phải."""
        if not self.wait_for_tiktok_foreground(device_id):
            return False
        self.dismiss_tiktok_search_filter_panel(device_id)
        width, height = self.get_effective_screen_size(device_id)
        state = self.get_tiktok_search_input_state(device_id)
        coords = state["coords"] if state else (
            int(width * 0.45), int(height * 0.055)
        )
        # Cổng an toàn cuối: mọi tọa độ phía nút ba chấm đều bị loại bỏ.
        if coords[0] >= int(width * 0.78):
            coords = (int(width * 0.45), int(height * 0.055))
        self.tap(device_id, coords[0], coords[1])
        time.sleep(0.4)
        verified = self.get_tiktok_search_input_state(device_id)
        if verified and verified.get("focused"):
            return True
        # UIAutomator thường bận khi 40 máy chạy đồng thời; tap an toàn vào
        # vùng query cộng với TikTok foreground là đủ để XwIME CLEAR + INPUT.
        return self.wait_for_tiktok_foreground(device_id)

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

    def _normalize_tiktok_identity(self, value):
        """Chuẩn hóa tên kênh để đối chiếu cả bản có/không dấu."""
        value = unicodedata.normalize(
            "NFKD", self._normalize_tiktok_text(value)
        )
        return "".join(
            ch for ch in value if unicodedata.category(ch) != "Mn"
        )

    @staticmethod
    def _clean_channel_tokens(text):
        """Tách các token chữ/số sau khi bỏ dấu và ký tự đặc biệt."""
        normalized = unicodedata.normalize("NFKD", text or "")
        without_marks = "".join(
            char for char in normalized if not unicodedata.combining(char)
        ).replace("đ", "d").replace("Đ", "d")
        return [
            token
            for token in re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).split()
            if token
        ]

    def _match_tiktok_channel_name(self, candidate, target):
        """So khớp tên kênh thông minh qua UI Automator DOM Engine, tuyệt đối không nhầm người khác."""
        return ui_automator_dom.match_tiktok_channel_name(candidate, target)

    def _remember_tiktok_target_tap(self, device_id, channel_name):
        self._recent_tiktok_target_taps[device_id] = (
            self._normalize_tiktok_identity(channel_name),
            time.monotonic(),
        )

    def _has_recent_tiktok_target_tap(self, device_id, channel_name):
        remembered = self._recent_tiktok_target_taps.get(device_id)
        if not remembered:
            return False
        remembered_target, tapped_at = remembered
        target = self._normalize_tiktok_identity(channel_name)
        same_target = bool(
            target
            and remembered_target
            and (
                target == remembered_target
                or target.startswith(f"{remembered_target} ")
                or remembered_target.startswith(f"{target} ")
                or self._match_tiktok_channel_name(target, remembered_target)
            )
        )
        return same_target and time.monotonic() - tapped_at <= 60.0

    def _tap_tiktok_target_name_fallback(
        self, device_id, channel_name, coords=None
    ):
        """Tuyệt đối không đoán mò tọa độ khi UI Automator không nhận diện được card kênh."""
        print(
            f"[Device {device_id[:6]}] Không tìm thấy card kênh TikTok '{channel_name}' qua DOM • "
            f"từ chối tap mù tọa độ để tránh bấm nhầm người khác."
        )
        return False

    def _tap_tiktok_profile_clip_fallback(self, device_id):
        """Mở clip ở vùng lưới thấp và bắt buộc xác minh player."""
        if not self.wait_for_tiktok_foreground(device_id):
            return False
        width, height = self.get_effective_screen_size(device_id)
        columns = (
            int(width * 0.18), int(width * 0.50), int(width * 0.82)
        )
        # 48% có thể trúng thanh sort Latest/Popular ở profile có header dài.
        # Các mức dưới đây nằm sâu trong lưới clip ở những layout đã quan sát.
        for attempt, y_ratio in enumerate((0.68, 0.76, 0.62), start=1):
            col_x = columns[(attempt - 1) % len(columns)]
            coords = (col_x, int(height * y_ratio))
            print(
                f"[Device {device_id[:6]}] Mở clip profile target tại "
                f"{coords} (lần {attempt}/3)."
            )
            self.tap(device_id, coords[0], coords[1])
            time.sleep(2.5)
            if self.is_tiktok_video_player(device_id):
                return True

            if attempt < 3:
                # Chưa phải player: vuốt phần profile lên để lưới clip hiện
                # sâu hơn, rồi thử một ô khác. Không coi foreground là đủ.
                self.swipe(
                    device_id,
                    width // 2,
                    int(height * 0.82),
                    width // 2,
                    int(height * 0.42),
                    duration=550,
                )
                time.sleep(1.0)
                if not self.wait_for_tiktok_foreground(device_id):
                    return False
        return False

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
            screen_width, screen_height = self.get_effective_screen_size(device_id)
            top_bar_y_max = max(320, int(screen_height * 0.18))
            top_bar_y_min = max(180, int(screen_height * 0.10))
            bounds_match = re.match(
                r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                elem.get("bounds", ""),
            )
            in_top_search_bar = bool(
                bounds_match
                and int(bounds_match.group(2)) < top_bar_y_min
                and int(bounds_match.group(4)) <= top_bar_y_max
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
                if match and int(match.group(2)) >= max(180, int(screen_height * 0.09)):
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
        local_xml = os.path.join(tempfile.gettempdir(), f"temp_{prefix}_{safe_device_id}.xml")

        # 1. Thử cơ chế One-shot Streaming trực tiếp qua RAM (nhanh gấp 3-4 lần, không tạo file trên PC)
        fast_cmd = f"uiautomator dump {remote_xml} >/dev/null 2>&1 && cat {remote_xml} && rm -f {remote_xml}"
        code, stdout, _ = self.execute_adb(device_id, ["shell", fast_cmd])
        if code == 0 and stdout and "<hierarchy" in stdout:
            try:
                start_idx = stdout.find("<hierarchy")
                end_idx = stdout.find("</hierarchy>")
                if start_idx != -1 and end_idx != -1:
                    clean_xml = stdout[start_idx : end_idx + len("</hierarchy>")]
                    return ET.fromstring(clean_xml)
            except Exception:
                pass

        # 2. Fallback về quy trình chuẩn nếu stream gặp lỗi (rm -> dump -> pull -> rm)
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

        screen_width, screen_height = self.get_effective_screen_size(device_id)

        # 1. Thử xác minh trước qua UI Automator DOM Engine
        try:
            if ui_automator_dom.is_tiktok_target_profile_dom(
                root, screen_width, screen_height, channel_name
            ):
                return True
        except Exception:
            pass

        target = self._normalize_tiktok_identity(channel_name)
        has_target = False
        has_search_input = False
        has_search_results_marker = False
        has_profile_action = False
        video_nodes = 0

        tab_y_min = int(screen_height * 0.05)
        tab_y_max = int(screen_height * 0.22)
        header_y_max = int(screen_height * 0.42)

        for elem in root.iter():
            class_name = elem.get("class", "")
            text_values = {
                self._normalize_tiktok_text(elem.get("text", "")),
                self._normalize_tiktok_text(elem.get("content-desc", "")),
            }
            text_values.discard("")
            identity_values = {
                self._normalize_tiktok_identity(elem.get("text", "")),
                self._normalize_tiktok_identity(elem.get("content-desc", "")),
            }
            identity_values.discard("")
            resource_id = elem.get("resource-id", "").lower()

            bounds = elem.get("bounds", "")
            m = re.findall(r"\d+", bounds)
            elem_y = (int(m[1]) + int(m[3])) // 2 if len(m) >= 4 else None

            # Tên target phải xuất hiện trong phần Header Profile (y <= 42%).
            # Tuyệt đối không dùng caption/bio của video ở dưới để tránh nhận nhầm profile khác.
            target_clean = target.replace(" ", "")
            has_wrong_identity = False
            for v in identity_values:
                v_clean = v.replace(" ", "").lstrip("@")
                if "hoankhai" in v_clean and "khaihoan" not in v_clean:
                    has_wrong_identity = True

            if (elem_y is None or elem_y <= header_y_max) and target and not has_wrong_identity and any(
                value == target
                or value.startswith(f"{target} ")
                or (target_clean and value.replace(" ", "").lstrip("@") == target_clean)
                or self._match_tiktok_channel_name(value, channel_name)
                for value in identity_values
            ):
                has_target = True

            if "edittext" in class_name.lower():
                if elem_y is None or elem_y < int(screen_height * 0.18):
                    has_search_input = True

            # Chỉ coi là Search Results nếu marker nằm ở dải thanh tab tìm kiếm trên cùng (hoặc mock không có bounds)
            if elem_y is None or (tab_y_min <= elem_y <= tab_y_max):
                if any(
                    value in (
                        "người dùng", "users", "photos", "ảnh", "cửa hàng", "cua hang"
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
                    "tin nhắn",
                    "đang follow",
                    "đã follow",
                    "theo dõi",
                    "đang theo dõi",
                    "chỉnh sửa hồ sơ",
                    "edit profile",
                    "chia sẻ hồ sơ",
                    "share profile",
                    "bài viết",
                    "video",
                    "repost",
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
            and (has_profile_action or video_nodes >= 1)
        )

    def ensure_tiktok_search_top_tab(self, device_id, root=None, force=False):
        """
        BẮT BUỘC: Đảm bảo kết quả tìm kiếm luôn ở tab 'Top' (hoặc 'Hàng đầu').
        Tuyệt đối không để kẹt ở tab Photos (Ảnh), Users (Người dùng), Videos...
        Nhận diện chính xác vị trí chữ 'Top' và bấm chuyển tab.
        """
        if root is None:
            root = self._get_tiktok_ui_root(device_id, "tt_top_tab")
        if root is None:
            return False

        screen_width, screen_height = self.get_effective_screen_size(device_id)
        tab_y_min = int(screen_height * 0.05)
        tab_y_max = int(screen_height * 0.22)

        top_elem = None
        top_coords = None
        top_selected = False
        any_other_tab_detected = False
        other_tab_selected = None
        other_tab_name = ""
        detected_tab_ys = []
        hoi_coords = None

        tab_names_other = (
            "photos", "videos", "users", "sounds", "shop", "places",
            "anh", "video", "nguoi dung", "tai khoan", "am thanh", "cua hang", "dia diem",
        )

        parent_map = {child: parent for parent in root.iter() for child in parent}
        for elem in root.iter():
            text_raw = (elem.get("text") or "").strip()
            desc_raw = (elem.get("content-desc") or "").strip()
            norm_t = self._normalize_tiktok_identity(text_raw)
            norm_d = self._normalize_tiktok_identity(desc_raw)

            bounds = elem.get("bounds", "")
            m = re.findall(r"\d+", bounds)
            if len(m) < 4:
                continue
            x1, y1, x2, y2 = map(int, m[:4])
            if not (tab_y_min <= y1 <= tab_y_max):
                continue

            detected_tab_ys.append((y1 + y2) // 2)

            # Kiểm tra trạng thái selected trên chính node hoặc container cha
            elem_selected = (elem.get("selected") or "").lower() == "true" or (elem.get("checked") or "").lower() == "true"
            curr = elem
            for _ in range(4):
                if curr is None:
                    break
                if (curr.get("selected") or "").lower() == "true" or (curr.get("checked") or "").lower() == "true":
                    elem_selected = True
                    break
                curr = parent_map.get(curr)

            # Phát hiện tab Hỏi (Ask AI) nằm bên trái tab Top
            if norm_t in ("hoi", "ask") or norm_d in ("hoi", "ask"):
                hoi_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

            is_top = (
                norm_t in ("top", "op", "hang dau")
                or norm_d in ("top", "op", "hang dau")
                or (norm_t.endswith("op") and norm_t not in ("shop", "cua hang"))
                or (norm_d.endswith("op") and norm_d not in ("shop", "cua hang"))
                or any(w in ("top", "hang dau") for w in norm_t.split())
                or any(w in ("top", "hang dau") for w in norm_d.split())
            )

            if is_top:
                top_elem = elem
                top_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                if elem_selected:
                    top_selected = True

            is_other = any(
                k == norm_t or norm_t.startswith(k) or k == norm_d or norm_d.startswith(k)
                for k in tab_names_other
            )
            if is_other:
                any_other_tab_detected = True
            if elem_selected and is_other:
                other_tab_selected = elem
                other_tab_name = text_raw or desc_raw

        # Nếu tab Top đã được chọn rõ ràng thì không chạm
        if top_selected and not force:
            return False

        # Nếu không force và không có tab nào khác đang được chọn, coi như đã ở Top
        if not force and other_tab_selected is None:
            return False

        if top_coords is None:
            if top_elem is not None:
                top_coords = self._element_center(top_elem)
            else:
                other_coords = self._element_center(other_tab_selected) if other_tab_selected is not None else None
                tab_y = other_coords[1] if other_coords else (detected_tab_ys[0] if detected_tab_ys else int(screen_height * 0.11))
                if hoi_coords:
                    top_coords = (hoi_coords[0] + int(screen_width * 0.14), tab_y)
                else:
                    top_coords = (int(screen_width * 0.16), tab_y)

        if top_coords:
            reason = f"Đang ở tab '{other_tab_name}'" if other_tab_selected is not None else "Bắt buộc chọn tab Top"
            print(
                f"[Device {device_id[:6]}][TikTok] {reason} • "
                f"Bấm chọn lại tab 'Top' tại {top_coords}..."
            )
            self.tap(device_id, top_coords[0], top_coords[1])
            time.sleep(1.8)
            return True

        return False

    def _switch_to_tiktok_users_tab(self, device_id, root=None):
        """Chuyển sang tab Người dùng (Users) để tìm kiếm danh sách tài khoản."""
        if root is None:
            root = self._get_tiktok_ui_root(device_id, "tt_switch_users_tab")
        if root is None:
            return False
        screen_width, screen_height = self.get_effective_screen_size(device_id)
        card_info = ui_automator_dom.find_tiktok_search_channel_card(
            root, screen_width, screen_height, ""
        )
        if card_info.get("users_tab_coords"):
            ux, uy = card_info["users_tab_coords"]
            print(f"[Device {device_id[:6]}][TikTok] Bấm chọn tab 'Người dùng' tại ({ux}, {uy})...")
            self.tap(device_id, ux, uy)
            time.sleep(1.8)
            return True
        return False

    def find_and_click_tiktok_channel(self, device_id, channel_name):
        """Click đúng card kênh qua UI Automator DOM, rồi xác minh đã vào profile mục tiêu."""
        target = self._normalize_tiktok_identity(channel_name)
        screen_width, screen_height = self.get_effective_screen_size(device_id)
        search_bar_bottom = int(screen_height * 0.14)
        max_scan_attempts = 7

        for attempt in range(max_scan_attempts):
            root = self._get_tiktok_ui_root(device_id, f"tt_channel_{attempt}")
            if root is None:
                # Tuyệt đối không tap mù tọa độ khi dump thất bại; thử lại hoặc dừng
                time.sleep(1.0)
                continue

            # 1. Nếu đúng profile đã mở thì hoàn tất ngay, không tap lại
            if self.is_on_tiktok_target_profile(
                device_id, channel_name, root=root
            ):
                self._remember_tiktok_target_tap(device_id, channel_name)
                return True

            # 2. Sử dụng phân hệ UI Automator DOM Engine quét chính xác card kênh
            dom_card = ui_automator_dom.find_tiktok_search_channel_card(
                root, screen_width, screen_height, channel_name
            )

            # Trường hợp 2A: Tìm thấy card kênh khớp chuẩn xác mục tiêu qua DOM
            if dom_card.get("matched") and dom_card.get("card_coords"):
                tap_x, tap_y = dom_card["card_coords"]
                print(
                    f"[Device {device_id[:6]}][UI Automator] Tìm thấy card Kênh '{dom_card['matched_name']}' "
                    f"khớp '{channel_name}' tại ({tap_x}, {tap_y})."
                )
                self.tap(device_id, tap_x, tap_y)
                time.sleep(3.0)

                if self.is_on_tiktok_target_profile(device_id, channel_name):
                    self._remember_tiktok_target_tap(device_id, channel_name)
                    return True

                # Thêm 1.5s chờ mạng tải chậm
                time.sleep(1.5)
                if self.is_on_tiktok_target_profile(device_id, channel_name):
                    self._remember_tiktok_target_tap(device_id, channel_name)
                    return True

                # Nếu sau khi tap mà không phải profile mục tiêu, lập tức quay lại tìm kiếm ngay
                print(
                    f"[Device {device_id[:6]}] Chưa xác nhận đúng profile '{channel_name}' • "
                    f"lập tức quay lại tìm kiếm..."
                )
                self.keyevent(device_id, 4)
                time.sleep(1.5)
                continue

            # Trường hợp 2B: Chưa thấy card kênh ở lần đầu, nhưng đang ở tab Top
            # -> Chuyển sang tab Người dùng (Users) để quét danh sách tài khoản đầy đủ
            if attempt == 0 and dom_card.get("current_tab") == "top" and dom_card.get("users_tab_coords"):
                ux, uy = dom_card["users_tab_coords"]
                print(
                    f"[Device {device_id[:6]}][TikTok] Chưa thấy card Kênh trên tab Top • "
                    f"Chuyển sang tab 'Người dùng' tại ({ux}, {uy})..."
                )
                self.tap(device_id, ux, uy)
                time.sleep(2.0)
                continue

            # Trường hợp 2C: Quét card tương thích ngược nếu DOM engine chưa gom đủ cấu trúc
            parent_map = {child: parent for parent in root.iter() for child in parent}
            matches = []
            profile_row_cues = (
                "follow", "following", "theo dõi", "đang follow",
                "đã follow", "account", "tài khoản", "user",
            )
            cue_centers = []
            for cue_elem in root.iter():
                cue_text = self._normalize_tiktok_text(
                    f"{cue_elem.get('text', '')} "
                    f"{cue_elem.get('content-desc', '')}"
                )
                if not any(cue in cue_text for cue in profile_row_cues):
                    continue
                cue_coords = self._element_center(cue_elem)
                if cue_coords:
                    cue_centers.append(cue_coords)

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
                    self._normalize_tiktok_identity(elem.get("text", "")),
                    self._normalize_tiktok_identity(
                        elem.get("content-desc", "")
                    ),
                }
                text_values.discard("")
                exact_identity = target in text_values
                prefixed_identity = any(
                    value.startswith(target) for value in text_values
                )
                fuzzy_identity = any(
                    self._match_tiktok_channel_name(value, channel_name)
                    for value in text_values
                )
                if not target or not (exact_identity or prefixed_identity or fuzzy_identity):
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
                identity_coords = self._element_center(elem)
                if identity_coords is None and cue_centers:
                    viable_cues = [
                        (cue_x, cue_y)
                        for cue_x, cue_y in cue_centers
                        if search_bar_bottom < cue_y < int(screen_height * 0.72)
                    ]
                    if viable_cues:
                        _, cue_y = min(viable_cues, key=lambda point: point[1])
                        identity_coords = (int(screen_width * 0.38), cue_y)

                coords = identity_coords or self._element_center(target_elem)
                if coords is None:
                    continue

                is_search_bar = any(k in target_resource_id for k in ("search_edit", "search_input", "search_src_text", "search_box", "search_bar")) or "edittext" in target_class
                if coords[1] <= search_bar_bottom or is_search_bar:
                    continue

                score = 25 if exact_identity else (20 if fuzzy_identity else 0)
                if score == 0:
                    continue
                final_coords = (int(screen_width * 0.38), coords[1])
                matches.append((score, final_coords, target))

            if not matches:
                if attempt >= max_scan_attempts - 1:
                    break
                if not self.wait_for_tiktok_foreground(device_id):
                    return False
                print(
                    f"[Device {device_id[:6]}] Chưa thấy Kênh '{channel_name}' ở vùng "
                    f"hiện tại • cuộn kết quả tìm kiếm ({attempt + 1}/"
                    f"{max_scan_attempts - 1})..."
                )
                # Vuốt ở vùng giữa màn hình (y từ 72% lên 35%), cách ly hoàn toàn với thanh tab trên đầu (y < 25%)
                self.swipe(
                    device_id,
                    screen_width // 2,
                    int(screen_height * 0.72),
                    screen_width // 2,
                    int(screen_height * 0.35),
                    duration=600,
                )
                time.sleep(1.2)
                continue

            _, coords, matched_text = max(matches, key=lambda item: item[0])
            tap_x = int(screen_width * 0.38)
            tap_y = coords[1]
            print(
                f"[Device {device_id[:6]}] Click card Kênh TikTok "
                f"'{matched_text[:40]}' tại ({tap_x}, {tap_y})."
            )
            self.tap(device_id, tap_x, tap_y)
            time.sleep(3.0)

            if self.is_on_tiktok_target_profile(device_id, channel_name):
                self._remember_tiktok_target_tap(device_id, channel_name)
                return True

            time.sleep(1.5)
            if self.is_on_tiktok_target_profile(device_id, channel_name):
                self._remember_tiktok_target_tap(device_id, channel_name)
                return True

            if not self.is_tiktok_in_foreground(device_id):
                self.recover_tiktok_if_blocked_by_captcha_or_link(device_id)
            else:
                print(
                    f"[Device {device_id[:6]}] Chưa xác nhận đúng profile '{channel_name}' • "
                    f"lập tức quay lại tìm kiếm..."
                )
                self.keyevent(device_id, 4)
                time.sleep(1.5)

        return False

    def _extract_tiktok_profile_video_candidates(self, root, width, height):
        """Trích xuất danh sách tọa độ các ô video trên profile qua UI Automator DOM Engine, ưu tiên video mới nhất."""
        if root is None:
            return [], False

        dom_res = ui_automator_dom.find_tiktok_profile_first_video_adaptive(root, width, height)
        if dom_res.get("method") == "dom_exact_tile" and dom_res.get("candidates"):
            return dom_res["candidates"], dom_res.get("has_unpinned", False)

        return [], False

    def click_random_tiktok_profile_video(self, device_id, channel_name):
        """Tìm và mở ưu tiên video mới nhất trên đầu profile kênh (bắt buộc xác minh đúng profile)."""
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
                    print(
                        f"[Device {device_id[:6]}] Cảnh báo: Chưa xác nhận đúng profile '{channel_name}' • "
                        f"không mở clip nhầm người khác ({attempt + 1}/{max_scan_attempts})."
                    )
                    time.sleep(0.8)
                    continue

            candidates, has_unpinned = self._extract_tiktok_profile_video_candidates(
                root, width, height
            )

            # Chỉ cuộn nhẹ 1 lần nếu phần tiểu sử/header dài đang che mất lưới video
            # hoặc hàng đầu tiên chỉ toàn video Đã ghim (cần lộ hàng video mới nhất ngay bên dưới)
            if not candidates or (not has_unpinned and attempt == 0):
                print(
                    f"[Device {device_id[:6]}][TikTok] Cuộn nhẹ để lộ hàng video mới nhất trên đầu Kênh..."
                )
                self.swipe(
                    device_id,
                    width // 2,
                    int(height * 0.72),
                    width // 2,
                    int(height * 0.40),
                    duration=500,
                )
                time.sleep(0.8)
                scrolled_root = self._get_tiktok_ui_root(
                    device_id, "tt_profile_videos_scrolled"
                )
                if scrolled_root is not None:
                    root = scrolled_root
                    candidates, has_unpinned = self._extract_tiktok_profile_video_candidates(
                        root, width, height
                    )

            if not candidates:
                # Sử dụng tính toán hình học tự thích nghi theo từng thiết bị từ UI Automator DOM
                adaptive_res = ui_automator_dom.find_tiktok_profile_first_video_adaptive(root, width, height)
                candidates = adaptive_res.get("candidates") or []

            if not candidates:
                col_w = max(1, width // 3)
                tile_h = max(1, int(col_w * 1.33))
                header_y = int(height * 0.45)
                row_1_cy = header_y + int(tile_h * 0.45)
                candidates = [
                    (col_w // 2, row_1_cy),
                    (col_w + col_w // 2, row_1_cy),
                    (2 * col_w + col_w // 2, row_1_cy),
                ]

            # Kiểm tra và đóng mọi popup/link/chat nếu có trước khi tap
            self.recover_tiktok_if_blocked_by_captcha_or_link(device_id)

            # Luôn ưu tiên click vào video mới nhất đầu danh sách để dòng chảy đi qua trọn vẹn các video mới nhất
            coords = candidates[0]
            print(
                f"[Device {device_id[:6]}][TikTok] Click ưu tiên vào video mới nhất tại tọa độ {coords}..."
            )
            self.tap(device_id, coords[0], coords[1])
            time.sleep(2.5)

            if self.is_tiktok_video_player(device_id):
                return True

            # Kiểm tra xem có bị mở nhầm Chat / Tin nhắn hoặc Share không, nếu có thì Back về Profile
            cur_root = self._get_tiktok_ui_root(device_id, "tt_misclick_chk")
            if cur_root is not None:
                combined_txt = " ".join(
                    f"{e.get('text', '')} {e.get('content-desc', '')}"
                    for e in cur_root.iter()
                ).lower()
                if any(m in combined_txt for m in ("gửi tin nhắn", "send message", "chia sẻ với", "share to", "soạn tin")):
                    print(f"[Device {device_id[:6]}][TikTok] Phát hiện mở nhầm Chat/Share • Thoát về Profile ngay...")
                    self.keyevent(device_id, 111)
                    self.keyevent(device_id, 4)
                    time.sleep(1.0)

            # Thử tap lần 2 với video kế tiếp trong hàng đầu
            retry_coords = candidates[1] if len(candidates) > 1 else candidates[0]
            self.tap(device_id, retry_coords[0], retry_coords[1])
            time.sleep(2.5)
            if self.is_tiktok_video_player(device_id):
                return True

        return False

    def is_tiktok_video_player(self, device_id):
        """Xác minh đã mở player bằng Activity hoặc cụm điều khiển video."""
        code, stdout, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "window", "windows"]
        )
        output = stdout.lower() if code == 0 else ""
        tiktok_packages = (
            config.TIKTOK_PACKAGE.casefold(),
            config.TIKTOK_PACKAGE_ALT.casefold(),
        )
        if (
            any(package in output for package in tiktok_packages)
            and any(
                marker in output
                for marker in (
                    "detailactivity", "aweme.detail", "detail.ui",
                )
            )
        ):
            return True

        # Kiểm tra nhanh luồng phát AudioTrack Media của Android (khi video đang phát thì AudioTrack luôn started)
        try:
            code_audio, stdout_audio, _ = self.execute_adb(
                device_id, ["shell", "dumpsys", "audio"], timeout=3
            )
            if code_audio == 0:
                audio_lower = stdout_audio.lower()
                if "state:started" in audio_lower and (
                    "usage_media" in audio_lower
                    or "audiotrack" in audio_lower
                    or "content_type_music" in audio_lower
                ):
                    if self.is_tiktok_in_foreground(device_id):
                        return True
        except Exception:
            pass

        root = self._get_tiktok_ui_root(device_id, "tt_player_check")
        if root is None:
            return False
        action_hits = set()
        has_profile_grid = False
        action_markers = {
            "like", "likes", "thich", "comment", "comments", "binh luan",
            "share", "chia se", "favorite", "favourite", "save", "luu",
        }
        profile_exclusive_markers = {
            "sua ho so", "edit profile", "tin nhan", "lienhe.khaihoanskincare.com",
            "chuyen san pham", "dia chi", "address",
        }
        has_profile_exclusive = False
        for elem in root.iter():
            cls = elem.get("class", "").casefold()
            if cls.endswith("gridview"):
                has_profile_grid = True
            value = self._normalize_tiktok_identity(
                f"{elem.get('text', '')} {elem.get('content-desc', '')}"
            )
            for marker in action_markers:
                if marker in value:
                    action_hits.add(marker)
            for p_marker in profile_exclusive_markers:
                if p_marker in value:
                    has_profile_exclusive = True

        if has_profile_exclusive:
            return False

        return not has_profile_grid and len(action_hits) >= 1
        code, stdout, _ = self.execute_adb(
            device_id, ["shell", "dumpsys", "window", "windows"]
        )
        output = stdout.lower() if code == 0 else ""
        tiktok_packages = (
            config.TIKTOK_PACKAGE.casefold(),
            config.TIKTOK_PACKAGE_ALT.casefold(),
        )
        if (
            any(package in output for package in tiktok_packages)
            and any(
                marker in output
                for marker in (
                    "detailactivity", "aweme.detail", "detail.ui",
                )
            )
        ):
            return True

        root = self._get_tiktok_ui_root(device_id, "tt_player_check")
        if root is None:
            return False
        action_hits = set()
        has_profile_grid = False
        action_markers = {
            "like", "likes", "thich", "comment", "comments", "binh luan",
            "share", "chia se", "favorite", "favourite", "save", "luu",
        }
        profile_exclusive_markers = {
            "sua ho so", "edit profile", "tin nhan", "lienhe.khaihoanskincare.com",
            "chuyen san pham", "dia chi", "address",
        }
        has_profile_exclusive = False
        for elem in root.iter():
            cls = elem.get("class", "").casefold()
            if cls.endswith("gridview"):
                has_profile_grid = True
            value = self._normalize_tiktok_identity(
                f"{elem.get('text', '')} {elem.get('content-desc', '')}"
            )
            for marker in action_markers:
                if marker in value:
                    action_hits.add(marker)
            for p_marker in profile_exclusive_markers:
                if p_marker in value:
                    has_profile_exclusive = True

        if has_profile_exclusive:
            return False

        return not has_profile_grid and len(action_hits) >= 1

    def dismiss_tiktok_comment_sheet_if_present(
        self, device_id, status_callback=None
    ):
        """Phát hiện và tự động đóng bảng bình luận / bàn phím TikTok nếu còn mở."""
        width, height = self.get_effective_screen_size(device_id)
        # 1. Luôn gửi phím Escape để đóng bàn phím mềm nếu đang mở
        self.keyevent(device_id, 111)

        # 2. Kiểm tra nhanh qua dumpsys input_method nếu bàn phím đang hiển thị
        try:
            code_ime, stdout_ime, _ = self.execute_adb(
                device_id, ["shell", "dumpsys", "input_method"], timeout=4
            )
            if code_ime == 0 and "minputshown=true" in stdout_ime.casefold():
                self.keyevent(device_id, 111)
                self.keyevent(device_id, 4)
                self.tap(device_id, width // 2, int(height * 0.12))
        except Exception:
            pass

        # 3. Quét XML UI xem có bảng bình luận hay không
        root = self._get_tiktok_ui_root(device_id, "tt_cm_chk")
        found_sheet = False
        close_coords = None
        if root is not None:
            for elem in root.iter():
                cls_name = (elem.get("class") or "").casefold()
                rid = (elem.get("resource-id") or "").casefold()
                raw = f"{elem.get('text', '')} {elem.get('content-desc', '')}"
                norm = self._normalize_facebook_text(raw.replace("đ", "d").replace("Đ", "d"))
                bounds = elem.get("bounds", "")
                m = re.findall(r"\d+", bounds)
                cy = (int(m[1]) + int(m[3])) // 2 if len(m) >= 4 else 0

                # Chỉ tính là bảng bình luận mở khi có EditText ở nửa dưới màn hình hoặc resource-id đặc trưng
                if "edittext" in cls_name and cy >= height * 0.35:
                    found_sheet = True
                elif any(k in rid for k in ("comment_edit_text", "et_comment", "c0e", "comment_bottom_sheet", "comment_container", "comment_list")):
                    found_sheet = True
                elif any(k in norm for k in ("them binh luan", "add comment", "viet binh luan", "binh luan cong khai", "de lai binh luan")) and cy >= height * 0.40:
                    found_sheet = True
                if any(k in norm for k in ("dong", "close")):
                    bounds = elem.get("bounds", "")
                    m = re.findall(r"\d+", bounds)
                    if len(m) >= 4:
                        x1, y1, x2, y2 = map(int, m[:4])
                        if y1 < int(height * 0.55):
                            close_coords = ((x1 + x2) // 2, (y1 + y2) // 2)

        if found_sheet:
            if status_callback:
                status_callback(
                    device_id,
                    "[TikTok] Phát hiện bảng bình luận • Đang tự động đóng lại...",
                )
            if close_coords:
                self.tap(device_id, close_coords[0], close_coords[1])
                time.sleep(0.3)
            # Đóng bảng an toàn bằng phím Back, Escape và tap backdrop phía trên (TUYỆT ĐỐI KHÔNG SWIPE DỌC)
            self.keyevent(device_id, 4)
            time.sleep(0.2)
            self.keyevent(device_id, 111)
            time.sleep(0.2)
            self.tap(device_id, width // 2, int(height * 0.12))
            time.sleep(0.3)
            return True
        return False

    def _extract_tiktok_clip_interaction_state(self, root, width, height):
        """Trích xuất chữ ký nội dung clip (content_sig), trạng thái Đã thả tim (ui_liked), Đã lưu Bookmark (ui_bookmarked) và tọa độ DOM các nút tương tác từ UI TikTok."""
        if root is None:
            return None, False, False, {}

        ui_liked = False
        ui_bookmarked = False
        button_coords = {}
        caption_parts = []

        try:
            ctrls = ui_automator_dom.find_tiktok_video_controls(root, width, height)
            if ctrls.get("like") and ctrls["like"].get("center"):
                button_coords["like"] = ctrls["like"]["center"]
                if ctrls["like"].get("is_liked"):
                    ui_liked = True
            if ctrls.get("comment") and ctrls["comment"].get("center"):
                button_coords["comment"] = ctrls["comment"]["center"]
            if ctrls.get("bookmark") and ctrls["bookmark"].get("center"):
                button_coords["bookmark"] = ctrls["bookmark"]["center"]
                if ctrls["bookmark"].get("is_bookmarked"):
                    ui_bookmarked = True
            if ctrls.get("share") and ctrls["share"].get("center"):
                button_coords["share"] = ctrls["share"]["center"]
        except Exception:
            pass

        for elem in root.iter():
            bounds = elem.get("bounds", "")
            m = re.findall(r"\d+", bounds)
            if len(m) < 4:
                continue
            x1, y1, x2, y2 = map(int, m[:4])
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            desc_raw = (elem.get("content-desc") or "").strip()
            txt_raw = (elem.get("text") or "").strip()
            rid_raw = (elem.get("resource-id") or "").strip()
            desc = desc_raw.casefold()
            txt = txt_raw.casefold()
            rid = rid_raw.casefold()
            norm_desc = self._normalize_tiktok_text(desc_raw)
            norm_txt = self._normalize_tiktok_text(txt_raw)
            is_selected = (
                elem.get("selected", "").lower() == "true"
                or elem.get("checked", "").lower() == "true"
            )

            # 1. Cột nút tương tác bên phải (x >= 70% bề ngang màn hình, y từ 28% đến 92%)
            if cx >= int(width * 0.70) and int(height * 0.28) <= cy <= int(height * 0.92):
                if any(
                    k in desc or k in txt or k in rid or k in norm_desc or k in norm_txt
                    for k in ("like", "thích", "thich", "heart", "tim")
                ):
                    button_coords["like"] = (cx, cy)
                    if is_selected or any(
                        k in desc or k in txt or k in norm_desc or k in norm_txt
                        for k in (
                            "đã thích", "da thich", "liked",
                            "bỏ thích", "bo thich", "gỡ thích", "go thich", "unlike"
                        )
                    ):
                        ui_liked = True

                if any(
                    k in desc or k in txt or k in rid or k in norm_desc or k in norm_txt
                    for k in ("bookmark", "lưu", "luu", "yêu thích", "yeu thich", "favorite", "collect", "save")
                ):
                    button_coords["bookmark"] = (cx, cy)
                    if is_selected or any(
                        k in desc or k in txt or k in norm_desc or k in norm_txt
                        for k in (
                            "đã lưu", "da luu", "saved",
                            "bỏ lưu", "bo luu", "added to favorites", "remove from favorites"
                        )
                    ):
                        ui_bookmarked = True

                if any(
                    k in desc or k in txt or k in rid or k in norm_desc or k in norm_txt
                    for k in ("comment", "bình luận", "binh luan")
                ):
                    button_coords["comment"] = (cx, cy)

                if any(
                    k in desc or k in txt or k in rid or k in norm_desc or k in norm_txt
                    for k in ("share", "chia sẻ", "chia se")
                ):
                    button_coords["share"] = (cx, cy)

            # 2. Vùng mô tả/caption bên trái phía dưới để tạo chữ ký bài đăng cố định
            elif cx < int(width * 0.72) and int(height * 0.50) <= cy <= int(height * 0.90):
                content = txt_raw or desc_raw
                if content and len(content) > 4:
                    norm_c = norm_txt or norm_desc
                    if not any(
                        nav in norm_c
                        for nav in (
                            "trang chu", "danh cho ban", "ban be", "hop thu", "ho so",
                            "home", "for you", "friends", "inbox", "profile", "following"
                        )
                    ):
                        caption_parts.append(content)

        content_sig = None
        if caption_parts:
            combined = " ".join(caption_parts[:4])
            content_sig = "tt_post_" + hashlib.md5(combined.encode("utf-8", errors="ignore")).hexdigest()[:16]

        return content_sig, ui_liked, ui_bookmarked, button_coords

    def perform_tiktok_micro_interactions(
        self,
        device_id,
        width,
        height,
        status_callback=None,
        is_cancelled=None,
        clip_signature=None,
        is_newest_clip=False,
    ):
        """Thực hiện ma trận vi tương tác (Thả tim, Bookmark, Share, Comment) trên clip TikTok, ưu tiên mạnh cho video mới nhất."""
        cx = width // 2
        ui_checked = False
        content_sig = None
        ui_liked = False
        ui_bookmarked = False
        button_coords = {}

        like_rate = (
            max(config.INTERACTION_LIKE_RATE, getattr(config, "TIKTOK_NEWEST_LIKE_RATE", 0.90))
            if is_newest_clip
            else config.INTERACTION_LIKE_RATE
        )
        bookmark_rate = (
            max(config.INTERACTION_BOOKMARK_RATE, getattr(config, "TIKTOK_NEWEST_BOOKMARK_RATE", 0.35))
            if is_newest_clip
            else config.INTERACTION_BOOKMARK_RATE
        )
        share_rate = (
            max(config.INTERACTION_SHARE_RATE, getattr(config, "TIKTOK_NEWEST_SHARE_RATE", 0.15))
            if is_newest_clip
            else config.INTERACTION_SHARE_RATE
        )
        comment_rate = (
            max(config.INTERACTION_COMMENT_RATE, getattr(config, "TIKTOK_NEWEST_COMMENT_RATE", 0.30))
            if is_newest_clip
            else config.INTERACTION_COMMENT_RATE
        )

        def ensure_ui_state():
            nonlocal ui_checked, content_sig, ui_liked, ui_bookmarked, button_coords
            if not ui_checked:
                ui_checked = True
                try:
                    root = self._get_tiktok_ui_root(device_id, "tt_micro")
                    if root is not None:
                        state_res = self._extract_tiktok_clip_interaction_state(root, width, height)
                        if len(state_res) == 4:
                            content_sig, ui_liked, ui_bookmarked, button_coords = state_res
                        else:
                            content_sig, ui_liked, ui_bookmarked = state_res[:3]
                except Exception:
                    pass

        # 1. Thả Tim / Like (Double-Tap vào giữa màn hình)
        if random.random() < like_rate:
            ensure_ui_state()
            if ui_liked:
                already_liked = True
            elif content_sig:
                already_liked = interaction_tracker.has_interacted(
                    device_id, "tiktok", content_sig, "like"
                )
            elif clip_signature:
                already_liked = interaction_tracker.has_interacted(
                    device_id, "tiktok", clip_signature, "like"
                )
            else:
                already_liked = False

            if already_liked:
                if clip_signature:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", clip_signature, "like"
                    )
                if content_sig:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", content_sig, "like"
                    )
                if status_callback:
                    status_callback(
                        device_id,
                        f"[TikTok Vi tương tác] ⏭️ Clip '{content_sig or clip_signature}' đã từng thả tim trước đây • Bỏ qua, tránh mất tim.",
                    )
            else:
                like_x = cx + random.randint(-40, 40)
                like_y = int(height * 0.48) + random.randint(-40, 40)
                self.tap(device_id, like_x, like_y)
                time.sleep(0.08)
                self.tap(device_id, like_x, like_y)
                if clip_signature:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", clip_signature, "like"
                    )
                if content_sig:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", content_sig, "like"
                    )
                if status_callback:
                    status_callback(
                        device_id,
                        "[TikTok Vi tương tác] ❤️ Ưu tiên thả tim vào video mới nhất..."
                        if is_newest_clip
                        else "[TikTok Vi tương tác] ❤️ Thả tim ngẫu nhiên vào clip...",
                    )
                time.sleep(0.5)

        # 2. Lưu Bookmark / Yêu thích (Tín hiệu thuật toán SEO mạnh nhất)
        if random.random() < bookmark_rate:
            ensure_ui_state()
            if ui_bookmarked:
                already_bookmarked = True
            elif content_sig:
                already_bookmarked = interaction_tracker.has_interacted(
                    device_id, "tiktok", content_sig, "bookmark"
                )
            elif clip_signature:
                already_bookmarked = interaction_tracker.has_interacted(
                    device_id, "tiktok", clip_signature, "bookmark"
                )
            else:
                already_bookmarked = False

            if already_bookmarked:
                if clip_signature:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", clip_signature, "bookmark"
                    )
                if content_sig:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", content_sig, "bookmark"
                    )
                if status_callback:
                    status_callback(
                        device_id,
                        f"[TikTok Vi tương tác] ⏭️ Clip '{content_sig or clip_signature}' đã lưu Bookmark trước đây • Bỏ qua, tránh mất Bookmark.",
                    )
            else:
                bm_coords = button_coords.get("bookmark") if button_coords else None
                if bm_coords:
                    bm_x, bm_y = bm_coords
                else:
                    bm_x = int(width * 0.91) + random.randint(-10, 10)
                    bm_y = int(height * 0.74) + random.randint(-15, 15)
                self.tap(device_id, bm_x, bm_y)
                if clip_signature:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", clip_signature, "bookmark"
                    )
                if content_sig:
                    interaction_tracker.record_interaction(
                        device_id, "tiktok", content_sig, "bookmark"
                    )
                if status_callback:
                    status_callback(
                        device_id,
                        "[TikTok Vi tương tác] ⭐ Bấm Lưu Bookmark / Yêu thích clip...",
                    )
                time.sleep(0.6)

        # 3. Chia sẻ ➔ Copy Link (Kích hoạt đề xuất Viral)
        if random.random() < share_rate:
            ensure_ui_state()
            share_coords = button_coords.get("share") if button_coords else None
            if share_coords:
                share_x, share_y = share_coords
            else:
                share_x = int(width * 0.91) + random.randint(-10, 10)
                share_y = int(height * 0.84) + random.randint(-15, 15)
            self.tap(device_id, share_x, share_y)
            time.sleep(1.2)
            # Bấm icon Copy Link
            self.tap(
                device_id,
                int(width * 0.20) + random.randint(-15, 15),
                int(height * 0.78) + random.randint(-15, 15),
            )
            time.sleep(0.5)
            self.keyevent(device_id, 4)
            if status_callback:
                status_callback(
                    device_id,
                    "[TikTok Vi tương tác] 🔗 Bấm Chia sẻ ➔ Sao chép liên kết video...",
                )
            time.sleep(0.5)

        # 4. Đọc bình luận (Tăng Dwell Time) - Chỉ mở xem lướt 1.5-2.5s rồi ĐÓNG NGAY, tuyệt đối không gửi bình luận
        if random.random() < comment_rate:
            ensure_ui_state()
            cm_coords = button_coords.get("comment") if button_coords else None
            if cm_coords:
                cm_x, cm_y = cm_coords
            else:
                cm_x = int(width * 0.92)
                cm_y = int(height * 0.63)
            self.tap(device_id, cm_x, cm_y)
            time.sleep(random.uniform(1.8, 2.5))
            
            # ĐÓNG BẢNG BÌNH LUẬN AN TOÀN TUYỆT ĐỐI (DÙNG BACK/ESCAPE/BACKDROP, TUYỆT ĐỐI KHÔNG SWIPE DỌC):
            self.keyevent(device_id, 111)
            time.sleep(0.2)
            self.keyevent(device_id, 4)
            time.sleep(0.3)
            self.tap(device_id, width // 2, int(height * 0.12))
            time.sleep(0.3)
            if status_callback:
                status_callback(
                    device_id, "[TikTok Vi tương tác] 💬 Xem lướt bình luận và đã đóng về video toàn màn hình..."
                )
            time.sleep(0.5)

    def try_tiktok_search_click_channel_video(
        self, device_id, target_channel, status_callback=None
    ):
        """Tìm và click video của kênh mục tiêu ngay trong danh sách kết quả tìm kiếm để kích hoạt CTR Search."""
        if not config.TIKTOK_SEARCH_CLICK_VIDEO_ENABLED:
            return False
        root = self._get_tiktok_ui_root(device_id, "tt_search_ctr")
        if root is None:
            return False
        width, height = self.get_effective_screen_size(device_id)
        for node in root.iter():
            text = f"{node.get('text', '')} {node.get('content-desc', '')}"
            if ui_automator_dom.match_tiktok_channel_name(text, target_channel):
                bounds = node.get("bounds", "")
                m = re.findall(r"\d+", bounds)
                if len(m) >= 4:
                    x1, y1, x2, y2 = map(int, m[:4])
                    if y1 > int(height * 0.15) and y2 < int(height * 0.90):
                        tap_x = (x1 + x2) // 2
                        tap_y = (y1 + y2) // 2
                        self.tap(device_id, tap_x, tap_y)
                        time.sleep(2.5)
                        if self.is_tiktok_video_player(device_id):
                            if status_callback:
                                status_callback(
                                    device_id,
                                    f"[TikTok CTR Boost] Đã click video từ kết quả Search của '{target_channel}'!",
                                )
                            return True
        return False

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
            self.collapse_statusbar_if_expanded(device_id, status_callback=status_callback)
            update_status("[TikTok B1] Mở ứng dụng TikTok...")
            self.launch_tiktok(device_id)
            self.collapse_statusbar_if_expanded(device_id, status_callback=status_callback)
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
                self.recover_tiktok_if_blocked_by_captcha_or_link(
                    device_id, status_callback=status_callback
                )
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
            self.collapse_statusbar_if_expanded(device_id, status_callback=status_callback)
            self.recover_tiktok_if_blocked_by_captcha_or_link(
                device_id, status_callback=status_callback
            )
            seed_kw = random.choice(seed_keywords)
            update_status(f"[TikTok B2] Mở Kính lúp & Tìm từ khóa mồi '{seed_kw}'...")
            if not self.ensure_tiktok_foreground_ready(
                device_id, status_callback=status_callback
            ):
                raise RuntimeError(
                    "TikTok B2 không ở foreground; không mở ô tìm kiếm"
                )
            
            search_opened = False
            for _ in range(2):
                check_cancelled()
                if self.find_and_click_tiktok_search(device_id):
                    search_opened = True
                    break
                time.sleep(0.8)

            if not search_opened:
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
            if not self.submit_tiktok_search(device_id):
                raise RuntimeError(
                    "TikTok B2 chưa gửi được tìm kiếm từ khóa mồi"
                )
            time.sleep(3.5)
            check_cancelled()
            self.recover_tiktok_if_blocked_by_captcha_or_link(
                device_id, status_callback=status_callback
            )
            if not self.wait_for_tiktok_foreground(device_id):
                raise RuntimeError(
                    "TikTok B2 mất foreground sau khi Enter từ khóa mồi"
                )
            seed_search_completed = True

            update_status(
                "[TikTok B2] Đã Enter từ khóa mồi • tiếp tục lướt kết quả, "
                "không nhập lại lần hai..."
            )

            # Thử click video của Kênh ngay từ kết quả Search (CTR Boost)
            self.try_tiktok_search_click_channel_video(
                device_id, target_channel, status_callback=update_status
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
                self.recover_tiktok_if_blocked_by_captcha_or_link(
                    device_id, status_callback=status_callback
                )
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
            self.collapse_statusbar_if_expanded(device_id, status_callback=status_callback)
            self.recover_tiktok_if_blocked_by_captcha_or_link(
                device_id, status_callback=status_callback
            )
            if not seed_search_completed:
                raise RuntimeError(
                    "TikTok B2 chưa hoàn tất; đã chặn chuyển sang B3"
                )
            update_status(f"[TikTok B3] Bắt buộc XÓA SẠCH từ khóa mồi '{seed_kw}' & Tìm Kênh mục tiêu '{target_channel}'...")
            if not self.wait_for_tiktok_foreground(device_id):
                raise RuntimeError(
                    "TikTok B3 không ở foreground; không thao tác tìm kiếm"
                )
            
            # 1-3. Focus ô tìm kiếm, xóa từ khóa mồi, nhập tên Kênh và click Kênh (tự động thử lại)
            channel_opened = False
            for b3_attempt in range(3):
                check_cancelled()
                if b3_attempt > 0:
                    update_status(
                        f"[TikTok B3] Chưa mở được Kênh '{target_channel}' (lần {b3_attempt + 1}/3) • "
                        f"quay lại và thử tìm kiếm lại..."
                    )
                    self.keyevent(device_id, 4)
                    time.sleep(1.0)

                # Focus vào Kính lúp / Ô tìm kiếm ở đầu trang
                if not self.focus_tiktok_existing_search_bar(device_id):
                    if not self.find_and_click_tiktok_search(device_id):
                        if b3_attempt < 2:
                            continue
                        raise RuntimeError(
                            "TikTok B3 không mở/focus được ô tìm kiếm trên kết quả B2"
                        )
                check_cancelled()

                # XÓA SẠCH từ khóa Bước 2 rồi mới nhập tên Kênh mục tiêu.
                if not self.replace_tiktok_search_text(device_id, target_channel):
                    if b3_attempt < 2:
                        continue
                    raise RuntimeError(
                        "TikTok B3 chưa xóa sạch từ khóa mồi hoặc chưa nhập đúng tên Kênh"
                    )
                time.sleep(1.0)
                if not self.submit_tiktok_search(device_id):
                    if b3_attempt < 2:
                        continue
                    raise RuntimeError(
                        "TikTok B3 chưa gửi được tìm kiếm Kênh mục tiêu"
                    )
                time.sleep(3.5)
                check_cancelled()

                # Quét tìm card Kênh mục tiêu thông minh qua UI Automator DOM (Top & Người dùng)
                update_status(f"[TikTok B3] Tìm Kênh mục tiêu '{target_channel}' qua UI Automator DOM...")
                try:
                    self.ensure_tiktok_search_top_tab(device_id)
                except Exception:
                    pass
                time.sleep(1.0)
                check_cancelled()

                # Click vào card kênh mục tiêu đã cấu hình.
                if self.find_and_click_tiktok_channel(device_id, target_channel):
                    channel_opened = True
                    break

            if not channel_opened:
                raise RuntimeError(
                    f"Không mở được Kênh TikTok mục tiêu '{target_channel}' sau 3 lần thử"
                )
            check_cancelled()

            update_status(
                f"[TikTok B3] Đã xác minh đúng profile '{target_channel}' • ưu tiên mở video mới nhất..."
            )
            clip_opened = False
            for clip_attempt in range(3):
                if self.click_random_tiktok_profile_video(device_id, target_channel):
                    clip_opened = True
                    break
                if clip_attempt < 2:
                    update_status(
                        f"[TikTok B3] Đang tải lưới video profile • "
                        f"cuộn nhẹ và thử lại ({clip_attempt + 2}/3)..."
                    )
                    self.swipe(
                        device_id,
                        cx,
                        int(height * 0.65),
                        cx,
                        int(height * 0.45),
                        duration=400,
                    )
                    time.sleep(1.5)

            if not clip_opened:
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
                f"{step3_total % 60:02d} giây • đổi clip mỗi {config.TIKTOK_STEP3_VIDEO_MIN}-{config.TIKTOK_STEP3_VIDEO_MAX}s..."
            )
            step3_elapsed = 0
            channel_video = 1
            priority_newest_count = getattr(
                config, "TIKTOK_NEWEST_VIDEO_PRIORITY_COUNT", 6
            )
            session_day = time.strftime("%Y%m%d")
            while step3_elapsed < step3_total:
                check_cancelled()
                if self.recover_tiktok_if_blocked_by_captcha_or_link(
                    device_id, status_callback=status_callback
                ):
                    update_status(
                        f"[TikTok B3] Khôi phục sau Captcha/Link • Mở lại Kênh mục tiêu '{target_channel}'..."
                    )
                    if self.find_and_click_tiktok_search(device_id):
                        if self.replace_tiktok_search_text(device_id, target_channel):
                            if self.submit_tiktok_search(device_id):
                                time.sleep(3.0)
                                if self.find_and_click_tiktok_channel(device_id, target_channel):
                                    self.click_random_tiktok_profile_video(device_id, target_channel)

                is_newest_clip = channel_video <= priority_newest_count
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
                
                # 1. Ưu tiên xem video trên Kênh trước (3-6s)
                initial_watch = min(random.randint(3, 6), watch_duration)
                for _ in range(initial_watch):
                    time.sleep(1.0)
                    check_cancelled()

                # Xác thực video hiện tại vẫn thuộc Kênh mục tiêu; nếu lướt lạc sang kênh khác, tự quay lại Kênh
                try:
                    cur_root = self._get_tiktok_ui_root(device_id, "tt_target_verify")
                    if cur_root is not None:
                        is_target_clip = False
                        target_clean = self._normalize_tiktok_identity(target_channel)
                        for elem in cur_root.iter():
                            node_text = self._normalize_tiktok_identity(f"{elem.get('text', '')} {elem.get('content-desc', '')}")
                            if target_clean in node_text:
                                is_target_clip = True
                                break
                        if not is_target_clip and not self.is_on_tiktok_target_profile(device_id, target_channel, root=cur_root):
                            update_status(f"[TikTok B3] Phát hiện video không thuộc Kênh '{target_channel}' • Quay lại mở đúng video của Kênh...")
                            self.keyevent(device_id, 4)
                            time.sleep(1.2)
                            if not self.is_on_tiktok_target_profile(device_id, target_channel):
                                self.find_and_click_tiktok_channel(device_id, target_channel)
                            self.click_random_tiktok_profile_video(device_id, target_channel)
                except Exception:
                    pass

                # 2. Thực hiện vi tương tác (Thả tim, Bookmark, Share, Xem lướt bình luận) - ưu tiên cao cho các video mới nhất
                try:
                    self.perform_tiktok_micro_interactions(
                        device_id,
                        width,
                        height,
                        status_callback=update_status,
                        is_cancelled=check_cancelled,
                        clip_signature=f"{target_channel}_{session_day}_clip_{channel_video}",
                        is_newest_clip=is_newest_clip,
                    )
                except Exception:
                    pass

                # 3. Xem tiếp phần thời lượng còn lại của video toàn màn hình
                remaining_watch = max(0, watch_duration - initial_watch)
                for _ in range(remaining_watch):
                    time.sleep(1.0)
                    check_cancelled()

                # Tăng Loop Rate (ưu tiên cao hơn cho các video mới nhất)
                loop_rate = (
                    max(config.INTERACTION_LOOP_RATE, getattr(config, "TIKTOK_NEWEST_LOOP_RATE", 0.35))
                    if is_newest_clip
                    else config.INTERACTION_LOOP_RATE
                )
                if random.random() < loop_rate:
                    loop_delay = random.randint(6, 12)
                    update_status(f"[TikTok B3] 🔁 Xem lặp lại clip {channel_video} (+{loop_delay}s Loop Rate)...")
                    for _ in range(loop_delay):
                        time.sleep(1.0)
                        check_cancelled()
                    step3_elapsed += loop_delay

                step3_elapsed += watch_duration
                if step3_elapsed < step3_total:
                    self.recover_tiktok_if_blocked_by_captcha_or_link(
                        device_id, status_callback=status_callback
                    )
                    if not self.wait_for_tiktok_foreground(device_id):
                        update_status("[TikTok B3] Ứng dụng bị mất foreground • Tự động kích hoạt lại...")
                        self.launch_tiktok(device_id)
                        time.sleep(2.0)
                        if not self.wait_for_tiktok_foreground(device_id):
                            raise RuntimeError(
                                "TikTok B3 mất foreground; không thể phục hồi ứng dụng"
                            )
                    try:
                        self.dismiss_tiktok_comment_sheet_if_present(
                            device_id, status_callback=update_status
                        )
                    except Exception:
                        pass
                    # BẢO VỆ CHUYỂN CLIP: Luôn gửi Escape và tap backdrop phía trên để chắc chắn đóng mọi popup/bàn phím
                    self.keyevent(device_id, 111)
                    self.tap(device_id, width // 2, int(height * 0.12))
                    time.sleep(0.2)

                    # Đi thẳng qua trọn vẹn nhóm video trên Kênh mục tiêu bắt đầu từ clip đầu tiên
                    update_status(
                        f"[TikTok B3] 🎬 Lướt sang video tiếp theo trên Kênh '{target_channel}' ({channel_video + 1}) • {step3_total - step3_elapsed}s còn lại..."
                    )
                    self.swipe(
                        device_id,
                        width // 2,
                        int(height * 0.78),
                        width // 2,
                        int(height * 0.22),
                        duration=random.randint(350, 500),
                    )
                    channel_video += 1
                    time.sleep(1.2)
                    self.recover_tiktok_if_blocked_by_captcha_or_link(
                        device_id, status_callback=status_callback
                    )

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

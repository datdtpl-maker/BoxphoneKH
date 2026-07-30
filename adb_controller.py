import subprocess
import base64
import time
import os
import xml.etree.ElementTree as ET
import re
import random
import unicodedata
import config
from concurrent.futures import ThreadPoolExecutor
from config import ADB_PATH, SHOPEE_PACKAGE, SHOPEE_SEARCH_BOX_COORDS, SHOPEE_INPUT_BOX_COORDS, SHOPEE_SEARCH_BTN_COORDS

class ADBController:
    def __init__(self, adb_path=ADB_PATH):
        self.adb_path = adb_path

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

    def launch_app(self, device_id, package_name):
        """Khởi chạy một ứng dụng bằng package name"""
        # Sử dụng monkey để khởi chạy nhanh app từ launcher
        return self.execute_adb(device_id, ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    def is_shopee_in_foreground(self, device_id):
        """Kiểm tra xem ứng dụng Shopee (com.shopee.vn) có đang chạy ở mảng chính (Foreground) hay không"""
        code, stdout, _ = self.execute_adb(device_id, ["shell", "dumpsys", "window", "displays"])
        if "com.shopee.vn" in stdout:
            return True
        code2, stdout2, _ = self.execute_adb(device_id, ["shell", "dumpsys", "activity", "recents"])
        if "com.shopee.vn" in stdout2:
            return True
        return False

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
        return self.keyevent(device_id, 66)

    def clear_input_field(self, device_id, max_chars=40):
        """Xóa sạch văn bản cũ trong ô tìm kiếm một cách triệt để"""
        try:
            for _ in range(max_chars):
                self.execute_adb(device_id, ["shell", "input", "keyevent", "67"])
        except Exception:
            pass

    def replace_shopee_search_text(self, device_id, text):
        """Xóa sạch ô tìm kiếm Shopee rồi nhập đúng một từ khóa đúng một lần."""
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

    def get_screen_size(self, device_id):
        """Lấy độ phân giải màn hình của thiết bị (width, height)"""
        code, stdout, stderr = self.execute_adb(device_id, ["shell", "wm", "size"])
        if code == 0:
            m = re.search(r"size:\s*(\d+)x(\d+)", stdout)
            if m:
                return int(m.group(1)), int(m.group(2))
        return 1080, 1920 # Mặc định nếu lỗi

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
            self.tap(device_id, guarded_x, guarded_y)
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
            self.tap(device_id, home_coords[0], home_coords[1])
            time.sleep(1.0)
            return True

        if header_coords:
            update_status("Đang ở trang chi tiết • bấm kính lúp trên header...")
            self.tap(device_id, header_coords[0], header_coords[1])
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
                self.tap(device_id, target_coords[0], target_coords[1])
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
                self.tap(device_id, target_coords[0], target_coords[1])
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
            # Dam bao tat xoay man hinh va khoa huong doc mac dinh
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "user_rotation", "0"])
            
            check_cancelled()
            update_status("Đang đưa Shopee về trang chủ...")
            self.ensure_shopee_homepage(device_id, status_callback=status_callback)
            
            # Tự động phát hiện và tắt popup quảng cáo trang chủ nếu có (dự phòng)
            check_cancelled()
            update_status("Kiểm tra và tắt popup quảng cáo...")
            self.bypass_shopee_popup(device_id)
                
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
            self.press_enter(device_id)
            time.sleep(3.5)
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
            # Dam bao tat xoay man hinh va khoa huong doc mac dinh
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "user_rotation", "0"])
            
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
            self.press_enter(device_id)
            
            # Đợi trang kết quả tải xong
            for _ in range(4):
                time.sleep(1.0)
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
                            kw_clean = keyword.lower().strip()
                            kw_words = [w for w in kw_clean.split() if len(w) > 1]
                            if not kw_words:
                                kw_words = [kw_clean]

                            # 1. Tìm các tiêu đề sản phẩm chứa từ khóa trên màn hình
                            product_title_nodes = []
                            for elem in root.iter():
                                text = elem.get('text', '').lower()
                                if any(w in text for w in kw_words):
                                    bounds = elem.get('bounds', '')
                                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                    if m:
                                        x1, y1, x2, y2 = map(int, m.groups())
                                        product_title_nodes.append(((x1 + x2) // 2, (y1 + y2) // 2, text))

                            # 2. Lọc nhãn Lâm Đồng thuộc đúng sản phẩm cần tìm
                            lamdong_candidates = []
                            for elem in root.iter():
                                text = elem.get('text', '')
                                if 'Lâm Đồng' in text or 'Tỉnh Lâm Đồng' in text:
                                    bounds = elem.get('bounds', '')
                                    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                    if m:
                                        x1, y1, x2, y2 = map(int, m.groups())
                                        cx = (x1 + x2) // 2
                                        cy = (y1 + y2) // 2
                                        if cx > 0 and cy > 0:
                                            # Đối chiếu nhãn địa điểm với tiêu đề sản phẩm ngay phía trên nó (cùng cột, Y chênh lệch < 280px)
                                            is_valid = False
                                            for tx, ty, t_text in product_title_nodes:
                                                if 0 < (cy - ty) < 280 and abs(tx - cx) < 300:
                                                    is_valid = True
                                                    break
                                            
                                            if is_valid:
                                                if (cx, cy) not in lamdong_candidates:
                                                    lamdong_candidates.append((cx, cy))
                            if lamdong_candidates:
                                found_coords = random.choice(lamdong_candidates)
                                update_status(f"Tìm thấy {len(lamdong_candidates)} shop Lâm Đồng trên màn hình. Chọn ngẫu nhiên: ({found_coords[0]}, {found_coords[1]}).")
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
                    update_status(f"Tìm thấy nhãn Lâm Đồng tại ({cx}, {cy}). Tiến hành click vào sản phẩm...")
                    self.tap(device_id, cx, click_y)
                    time.sleep(4.0) # Đợi trang sản phẩm mở ra
                    
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
                        time.sleep(4.5) # Đợi trang Shop tải
                        
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
                                
                        # Nhấn nút Back để quay lại trang sản phẩm
                        update_status("Hoàn thành dạo Shop. Quay lại sản phẩm...")
                        self.keyevent(device_id, 4) # Quay lại sản phẩm
                        time.sleep(3.0)

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
        """Kịch bản dự phòng: Tìm kiếm tên shop, truy cập vào shop qua thẻ shop / nút Thêm kết quả, và tìm sản phẩm"""
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
            
            # Xóa sạch chữ cũ
            self.clear_input_field(device_id)
            time.sleep(0.5)
            
            update_status(f"[Dự phòng] Nhập tên shop '{shop_name}'...")
            self.input_text(device_id, shop_name)
            time.sleep(1.5)
            check_cancelled()
            
            update_status("[Dự phòng] Gửi lệnh tìm kiếm shop...")
            self.press_enter(device_id)
            time.sleep(3.5)
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
            
            time.sleep(4.0) # Đợi trang Shop tải
            check_cancelled()

            # 4. Tìm ô tìm kiếm trong Shop (Ô kính lúp ở Đỉnh trang Shop: x=50% width, y=5.5% height)
            update_status("[Dự phòng] Tìm ô tìm kiếm trong Shop...")
            shop_search_x = int(width * 0.5)
            shop_search_y = int(height * 0.055)
            
            shop_search_coords = self.find_shop_search_box(device_id)
            if not shop_search_coords:
                update_status(f"[Dự phòng] Click ô 'Tìm kiếm sản phẩm trong Shop' tại ({shop_search_x}, {shop_search_y})...")
                self.tap(device_id, shop_search_x, shop_search_y)
            else:
                update_status(f"[Dự phòng] Click ô tìm kiếm trong Shop tại {shop_search_coords}...")
                self.tap(device_id, shop_search_coords[0], shop_search_coords[1])
                
            time.sleep(1.5)
            check_cancelled()
            
            # Click lại vào chính ô search ở đỉnh trang để chắc chắn bàn phím xuất hiện (tuyệt đối KHÔNG click y=0.14)
            self.tap(device_id, shop_search_x, shop_search_y)
            time.sleep(1.0)
            check_cancelled()
            time.sleep(1.0)
            check_cancelled()

            # 5. Xóa sạch và nhập đúng một từ khóa sản phẩm trong Shop.
            # Không dùng input_text_naturally vì hàm đó còn gõ thêm bản không dấu.
            update_status(
                f"[Dự phòng] Xóa sạch & nhập một từ khóa '{keyword}' trong Shop..."
            )
            if not self.replace_shopee_search_text(device_id, keyword):
                raise RuntimeError(
                    "Không thể xóa và nhập từ khóa sản phẩm trong Shop"
                )
            time.sleep(1.5)
            check_cancelled()
            
            update_status("[Dự phòng] Tìm kiếm sản phẩm trong Shop...")
            self.press_enter(device_id)
            time.sleep(3.5)
            check_cancelled()

            # 6. Tìm sản phẩm đầu tiên hiện ra trong kết quả tìm kiếm của Shop
            update_status("[Dự phòng] Tìm sản phẩm đầu tiên trong Shop...")
            product_coords = self.find_first_product_in_shop(device_id, keyword)
            if not product_coords:
                update_status("[Dự phòng] Không tìm thấy sản phẩm qua XML, thử click tọa độ dự phòng...")
                self.tap(device_id, 300, 600)
            else:
                update_status(f"[Dự phòng] Click sản phẩm tại {product_coords}...")
                self.tap(device_id, product_coords[0], product_coords[1])
                
            time.sleep(4.0) # Đợi trang sản phẩm tải
            check_cancelled()

            # 7. Tiến hành lướt xem album ảnh, thông tin sản phẩm và dạo Shop (giống hệt quy trình chính)
            width, height = self.get_screen_size(device_id)
            cx = width // 2
            
            update_status("[Dự phòng] Vuốt xem album ảnh sản phẩm chi tiết...")
            for _ in range(random.randint(2, 4)):
                check_cancelled()
                x_start = int(width * 0.85) + random.randint(-20, 20)
                x_end = int(width * 0.15) + random.randint(-20, 20)
                y_img = int(height * 0.25) + random.randint(-30, 30)
                self.swipe(device_id, x_start, y_img, x_end, y_img, duration=random.randint(500, 700))
                time.sleep(random.uniform(2.5, 4.0))

            update_status("[Dự phòng] Đang cuộn xem thông tin chi tiết & Đánh giá...")
            view_duration = random.randint(30, 45)
            start_time = time.time()
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

            # 8. Tương tác ngẫu nhiên (Thêm giỏ hàng 15% tỉ lệ)
            if random.random() < 0.15:
                check_cancelled()
                update_status("[Dự phòng] Tương tác ngẫu nhiên (Thêm vào giỏ hàng)...")
                cart_coords = self.find_element_coords_by_text(device_id, "Thêm vào giỏ hàng")
                if cart_coords:
                    self.tap(device_id, cart_coords[0], cart_coords[1])
                    time.sleep(3.0)
                    check_cancelled()
                    self.tap(device_id, int(width * 0.3) + random.randint(-50, 50), int(height * 0.5) + random.randint(-50, 50))
                    time.sleep(1.5)
                    check_cancelled()
                    self.keyevent(device_id, 4)
                    time.sleep(2.0)

            # 9. Dạo shop
            update_status("[Dự phòng] Tìm nút Xem Shop...")
            shop_coords = None
            for shop_btn_text in ["Xem Shop", "View Shop", "Ghé Shop", "Xem Cửa Hàng", "Visit Shop", "Visit Store"]:
                shop_coords = self.find_element_coords_by_text(device_id, shop_btn_text)
                if shop_coords:
                    break
            if shop_coords:
                update_status("[Dự phòng] Đang truy cập cửa hàng để dạo...")
                self.tap(device_id, shop_coords[0], shop_coords[1])
                time.sleep(4.5)
                
                shop_duration = random.randint(30, 45)
                shop_start = time.time()
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
                        
                update_status("[Dự phòng] Hoàn thành dạo Shop. Quay lại sản phẩm...")
                self.keyevent(device_id, 4)
                time.sleep(3.0)

            update_status("[Dự phòng] Hoàn thành quy trình tương tác sản phẩm!")
            return True, "Thành công (Dự phòng qua tên Shop)"
        except Exception as e:
            return False, f"Lỗi dự phòng: {str(e)}"

    # ================= AUTOMATION BƠM TIKTOK 3 BƯỚC =================
    def dismiss_tiktok_location_popup(self, device_id):
        """
        Tự động phát hiện và xử lý Bảng thông báo Quyền Truy Cập Vị Trí của Android/TikTok:
        1. Bấm checkbox "Không hỏi lại" (Don't ask again).
        2. Bấm nút "Từ chối" (Deny / Don't allow).
        """
        width, height = self.get_screen_size(device_id)
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

    def launch_tiktok(self, device_id):
        """Mở ứng dụng TikTok (thử com.ss.android.ugc.trill trước, dự phòng com.zhiliaoapp.musically)"""
        code, stdout, stderr = self.execute_adb(device_id, ["shell", "monkey", "-p", config.TIKTOK_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"])
        if code != 0 or "Error" in stdout:
            self.execute_adb(device_id, ["shell", "monkey", "-p", config.TIKTOK_PACKAGE_ALT, "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(3.5)
        # Tự động từ chối popup vị trí nếu hiển thị lúc mở app
        self.dismiss_tiktok_location_popup(device_id)

    def find_and_click_tiktok_search(self, device_id):
        """Tìm và bấm vào biểu tượng Kính Lúp (Search Icon) trên TikTok"""
        # Kiểm tra xử lý popup vị trí trước khi click search
        self.dismiss_tiktok_location_popup(device_id)
        
        width, height = self.get_screen_size(device_id)
        xml_file = f"/sdcard/dump_tiktok_search_{device_id}.xml"
        self.execute_adb(device_id, ["shell", "rm", "-f", xml_file])
        self.execute_adb(device_id, ["shell", "uiautomator", "dump", xml_file])
        
        local_xml = os.path.join(os.path.dirname(__file__), f"temp_dump_tt_search_{device_id}.xml")
        pull_code, _, _ = self.execute_adb(device_id, ["pull", xml_file, local_xml])
        
        coords = None
        if pull_code == 0 and os.path.exists(local_xml):
            try:
                tree = ET.parse(local_xml)
                root = tree.getroot()
                for elem in root.iter():
                    desc = (elem.get('content-desc', '') or elem.get('text', '') or elem.get('resource-id', '')).lower()
                    if any(k in desc for k in ["search", "tìm kiếm", "et_search", "search_btn", "img_search"]):
                        bounds = elem.get('bounds', '')
                        m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if m:
                            x1, y1, x2, y2 = map(int, m.groups())
                            cy = (y1 + y2) // 2
                            cx = (x1 + x2) // 2
                            if cy < 300:
                                coords = (cx, cy)
                                break
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        if not coords:
            # Tọa độ dự phòng góc Kính Lúp TikTok (x=90% width, y=5.5% height)
            coords = (int(width * 0.90), int(height * 0.055))
            
        self.tap(device_id, coords[0], coords[1])
        time.sleep(2.0)

        # Chỉ focus đúng EditText; không chạm theo tọa độ mù vào vùng gợi ý.
        self.focus_tiktok_search_input(device_id)

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
        """Focus đúng EditText của TikTok, có tọa độ dự phòng khi XML không đọc được."""
        width, height = self.get_screen_size(device_id)
        state = self.get_tiktok_search_input_state(device_id)
        coords = state["coords"] if state else (
            int(width * 0.45),
            int(height * 0.055),
        )
        self.tap(device_id, coords[0], coords[1])
        time.sleep(0.5)

        verified = self.get_tiktok_search_input_state(device_id)
        if verified and not verified["focused"]:
            self.tap(device_id, verified["coords"][0], verified["coords"][1])
            time.sleep(0.4)
            verified = self.get_tiktok_search_input_state(device_id)
        return verified is None or verified["focused"]

    def clear_tiktok_search_input(self, device_id):
        """
        BẮT BUỘC: Xóa sạch 100% toàn bộ từ khóa cũ trong ô tìm kiếm TikTok trước khi nhập từ khóa mới.
        """
        self.ensure_ime(device_id)
        for _ in range(2):
            if not self.focus_tiktok_search_input(device_id):
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
        width, height = self.get_screen_size(device_id)
        before = self.get_tiktok_feed_signature(device_id)
        gestures = [
            (0.50, 0.80, 0.50, 0.20, 450),
            (0.34, 0.86, 0.38, 0.14, 220),
            (0.66, 0.88, 0.62, 0.12, 160),
        ]

        for x1_ratio, y1_ratio, x2_ratio, y2_ratio, duration in gestures:
            self.swipe(
                device_id,
                int(width * x1_ratio),
                int(height * y1_ratio),
                int(width * x2_ratio),
                int(height * y2_ratio),
                duration=duration,
            )
            time.sleep(1.2)

            after = self.get_tiktok_feed_signature(device_id)
            if before is None or after is None or after != before:
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
        has_profile_action = False
        video_nodes = 0

        for elem in root.iter():
            class_name = elem.get("class", "")
            text = self._normalize_tiktok_text(
                f"{elem.get('text', '')} {elem.get('content-desc', '')}"
            )
            resource_id = elem.get("resource-id", "").lower()
            if target and target in text:
                has_target = True
            if "edittext" in class_name.lower():
                has_search_input = True
            if text in (
                "message",
                "following",
                "follow",
                "nhắn tin",
                "đang follow",
                "đã follow",
                "theo dõi",
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
            and (has_profile_action or video_nodes >= 2)
        )

    def find_and_click_tiktok_channel(self, device_id, channel_name):
        """Click đúng card kênh, rồi xác minh đã vào profile mục tiêu."""
        target = self._normalize_tiktok_text(channel_name)
        _, screen_height = self.get_screen_size(device_id)
        search_bar_bottom = int(screen_height * 0.12)

        for attempt in range(3):
            root = self._get_tiktok_ui_root(device_id, f"tt_channel_{attempt}")
            if root is None:
                time.sleep(1.0)
                continue

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

                text = self._normalize_tiktok_text(
                    f"{elem.get('text', '')} {elem.get('content-desc', '')}"
                )
                if not target or target not in text:
                    continue

                score = 10 if text == target else 5
                if "username" in resource_id:
                    score += 4

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
                if (
                    coords
                    and coords[1] > search_bar_bottom
                    and "edittext" not in target_class
                    and "search" not in target_resource_id
                ):
                    matches.append((score, coords, text))

            if not matches:
                time.sleep(1.0)
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
        """Chọn một clip đang hiển thị trên profile và xác minh đã mở player."""
        width, height = self.get_screen_size(device_id)
        for attempt in range(3):
            root = self._get_tiktok_ui_root(device_id, f"tt_profile_videos_{attempt}")
            if root is None or not self.is_on_tiktok_target_profile(
                device_id, channel_name, root=root
            ):
                return False

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
                    and 0 < coords[1] < height
                    and coords not in candidate_set
                ):
                    candidates.append(coords)
                    candidate_set.add(coords)

            if not candidates:
                return False

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

    def tiktok_automation_workflow(self, device_id, seed_keywords=None, target_channel=None, min_delay=5, max_delay=10, status_callback=None, is_cancelled=None):
        """
        Quy trình TikTok cố định:
        B1 dạo For You 15-60 giây; B2 lướt kết quả 15-30 giây;
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
            width, height = self.get_screen_size(device_id)
            cx = width // 2

            # Dam bao tat xoay man hinh
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            self.execute_adb(device_id, ["shell", "settings", "put", "system", "user_rotation", "0"])

            # ================= BƯỚC 1: DẠO TRANG CHỦ TIKTOK =================
            update_status("[TikTok B1] Mở ứng dụng TikTok...")
            self.launch_tiktok(device_id)
            check_cancelled()

            step1_total = random.randint(
                config.TIKTOK_STEP1_TOTAL_MIN,
                config.TIKTOK_STEP1_TOTAL_MAX,
            )
            update_status(
                f"[TikTok B1] Dạo Trang chủ trong {step1_total}s "
                f"(mặc định 15-60s)..."
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
                    if not self.advance_tiktok_feed(device_id):
                        update_status(
                            "[TikTok B1] Bài ảnh chưa đổi sau 3 lần vuốt • "
                            "tiếp tục thử ở lượt kế tiếp..."
                        )
                    step1_video += 1

            # ================= BƯỚC 2: TÌM TỪ KHÓA NHIỆM VỤ / MỒI KÊNH =================
            check_cancelled()
            seed_kw = random.choice(seed_keywords)
            update_status(f"[TikTok B2] Mở Kính lúp & Tìm từ khóa mồi '{seed_kw}'...")
            
            self.find_and_click_tiktok_search(device_id)
            check_cancelled()

            # Xóa nội dung cũ, nhập đúng từ khóa nhiệm vụ từ ô ent_tt_seed và xác minh.
            self.replace_tiktok_search_text(device_id, seed_kw)
            time.sleep(1.0)
            # TikTok hiện dùng Enter để gửi tìm kiếm. Không tap góc phải vì
            # vị trí đó là nút ba chấm và sẽ mở bảng Filters.
            self.submit_tiktok_search(device_id)
            time.sleep(3.5)
            check_cancelled()

            step2_total = random.randint(
                config.TIKTOK_STEP2_TOTAL_MIN,
                config.TIKTOK_STEP2_TOTAL_MAX,
            )
            update_status(
                f"[TikTok B2] Lướt kết quả '{seed_kw}' trong {step2_total}s "
                f"(mặc định 15-30s)..."
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
            update_status(f"[TikTok B3] Bắt buộc XÓA SẠCH từ khóa mồi '{seed_kw}' & Tìm Kênh mục tiêu '{target_channel}'...")
            
            # 1. Bấm vào Kính lúp / Ô tìm kiếm ở đầu trang
            self.find_and_click_tiktok_search(device_id)
            check_cancelled()

            # 2-3. XÓA SẠCH từ khóa Bước 2 rồi mới nhập tên Kênh mục tiêu.
            self.replace_tiktok_search_text(device_id, target_channel)
            time.sleep(1.0)
            # Áp dụng cùng cơ chế cho bước 3: chỉ Enter, không chạm nút ba chấm.
            self.submit_tiktok_search(device_id)
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

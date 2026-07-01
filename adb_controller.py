import subprocess
import base64
import time
import os
import xml.etree.ElementTree as ET
import re
import random
from concurrent.futures import ThreadPoolExecutor
from config import ADB_PATH, SHOPEE_PACKAGE, SHOPEE_SEARCH_BOX_COORDS, SHOPEE_INPUT_BOX_COORDS, SHOPEE_SEARCH_BTN_COORDS, SHOPEE_SHOP_NAMES

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

    def is_on_shopee_homepage(self, device_id):
        """Kiểm tra xem thiết bị có đang ở màn hình chính Shopee hay không bằng cách dump XML và tìm bottom bar tabs"""
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
                
                # Chỉ báo tab bottom bar (thêm các biến thể như Live & Video, Live &amp; Video):
                vi_indicators = ["Mall", "Live", "Thông báo", "Tôi", "Live &amp; Video", "Live & Video"]
                en_indicators = ["Mall", "Live", "Notifications", "Me", "Live &amp; Video", "Live & Video"]
                
                vi_match = sum(1 for ind in vi_indicators if f'text="{ind}"' in content)
                en_match = sum(1 for ind in en_indicators if f'text="{ind}"' in content)
                
                # Đồng thời kiểm tra sự hiện diện của SearchBar
                has_search = "inputSearchBar" in content or "SearchBar" in content or "search" in content.lower()
                
                if vi_match >= 3 or en_match >= 3 or (vi_match >= 2 and has_search):
                    is_home = True
            except Exception:
                pass
            finally:
                try:
                    os.remove(local_xml)
                except Exception:
                    pass
        else:
            # Nếu không pull được XML, kiểm tra lỗi idle state để giả định trang chủ
            if code != 0 and ("idle state" in stderr or "idle state" in stdout):
                print(f"[Device {device_id[:6]}] Dump gặp lỗi idle state và không có XML -> Giả định đang ở Trang chủ Shopee.")
                return True
                
        return is_home

    def ensure_shopee_homepage(self, device_id, status_callback=None):
        """Đảm bảo đưa Shopee về trang chủ và xác thực màn hình chính bằng uiautomator XML"""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        update_status("Khởi chạy Shopee...")
        self.launch_app(device_id, "com.shopee.vn")
        time.sleep(2.0)
        
        is_home = False
        # Thử nhấn Back để quay về và dọn popup
        for attempt in range(5):
            update_status(f"Xác thực màn hình chính (Lần {attempt + 1}/5)...")
            if self.is_on_shopee_homepage(device_id):
                is_home = True
                update_status("Đã ở màn hình chính Shopee.")
                break
            else:
                update_status("Chưa thấy màn hình chính. Nhấn Back 1 lần...")
                self.keyevent(device_id, 4)
                time.sleep(1.5)
                self.launch_app(device_id, "com.shopee.vn")
                time.sleep(1.0)
                
        # Nếu vẫn không được, khởi động lại ứng dụng
        if not is_home:
            update_status("Không thể về trang chủ, đang khởi động lại Shopee...")
            self.stop_app(device_id, "com.shopee.vn")
            time.sleep(1.5)
            self.launch_app(device_id, "com.shopee.vn")
            time.sleep(3.5)
            
            # Kiểm tra lại
            if self.is_on_shopee_homepage(device_id):
                is_home = True
                update_status("Xác thực màn hình chính thành công sau khi khởi động lại.")
            else:
                update_status("Nhấn Back 1 lần dọn popup khởi động...")
                self.keyevent(device_id, 4)
                time.sleep(2.0)
                if self.is_on_shopee_homepage(device_id):
                    is_home = True
                    update_status("Xác thực màn hình chính thành công.")
        
        # Nhấn Back thêm 1 lần nữa để đảm bảo dọn popup ẩn
        if is_home:
            update_status("Nhấn Back 1 lần để chắc chắn tắt popup quảng cáo...")
            self.keyevent(device_id, 4)
            time.sleep(2.0)
            return True
            
        update_status("Không thể xác thực màn hình chính Shopee.")
        return False

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

    def input_text_naturally(self, device_id, text):
        """Mô phỏng gõ chữ tự nhiên từng từ một với độ trễ ngẫu nhiên"""
        self.ensure_ime(device_id)
        words = text.split(" ")
        for idx, word in enumerate(words):
            word_to_send = word + (" " if idx < len(words) - 1 else "")
            b64_bytes = base64.b64encode(word_to_send.encode('utf-8'))
            b64_str = b64_bytes.decode('utf-8')
            self.execute_adb(device_id, [
                "shell", "am", "broadcast", 
                "-a", "XW_INPUT_B64", 
                "--es", "msg", b64_str, 
                "--receiver-foreground"
            ])
            time.sleep(random.uniform(0.2, 0.4))


    def press_enter(self, device_id):
        """Gửi lệnh enter thông qua bàn phím XwIME"""
        # Cách 1: Gửi qua broadcast của XwIME (Mã code 13 = Enter)
        self.execute_adb(device_id, ["shell", "am", "broadcast", "-a", "XW_INPUT_CODE", "--ei", "code", "13", "--receiver-foreground"])
        # Cách 2 (Dự phòng): Lệnh keyevent chuẩn của Android
        self.keyevent(device_id, 66)

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
            cx = width // 2

            # Dạo trang chủ Shopee trước khi tìm kiếm để tăng độ tự nhiên
            update_status("Dạo trang chủ Shopee...")
            for _ in range(random.randint(2, 3)):
                check_cancelled()
                y_start = int(height * 0.75) + random.randint(-50, 50)
                y_end = int(height * 0.3) + random.randint(-50, 50)
                self.swipe(device_id, cx, y_start, cx, y_end, duration=random.randint(600, 900))
                time.sleep(random.uniform(2.0, 3.0))
            
            update_status("Bấm vào thanh tìm kiếm...")
            # Click vào thanh search trên trang chủ
            self.tap(device_id, SHOPEE_SEARCH_BOX_COORDS[0], SHOPEE_SEARCH_BOX_COORDS[1])
            time.sleep(1.5)
            check_cancelled()
            
            # Click lại vào ô nhập liệu để chắc chắn bàn phím xuất hiện
            self.tap(device_id, SHOPEE_INPUT_BOX_COORDS[0], SHOPEE_INPUT_BOX_COORDS[1])
            time.sleep(1.0)
            check_cancelled()
            
            update_status(f"Đang nhập từ khóa '{keyword}'...")
            self.input_text(device_id, keyword)
            time.sleep(1.5)
            check_cancelled()
            
            update_status("Gửi lệnh tìm kiếm...")
            self.press_enter(device_id)
            time.sleep(2.0)
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
            
            # Lọc popup xong, sẵn sàng tiếp tục các bước tìm kiếm
            pass
                
            # Lấy kích thước màn hình động
            width, height = self.get_screen_size(device_id)
            cx = width // 2

            # Dạo trang chủ Shopee trước khi tìm kiếm để tăng độ tự nhiên
            update_status("Dạo trang chủ Shopee...")
            for _ in range(random.randint(2, 3)):
                check_cancelled()
                y_start = int(height * 0.75) + random.randint(-50, 50)
                y_end = int(height * 0.3) + random.randint(-50, 50)
                self.swipe(device_id, cx, y_start, cx, y_end, duration=random.randint(600, 900))
                time.sleep(random.uniform(2.0, 3.0))
            
            check_cancelled()
            update_status("Bấm ô tìm kiếm...")
            self.tap(device_id, SHOPEE_SEARCH_BOX_COORDS[0], SHOPEE_SEARCH_BOX_COORDS[1])
            time.sleep(1.5)
            self.tap(device_id, SHOPEE_INPUT_BOX_COORDS[0], SHOPEE_INPUT_BOX_COORDS[1])
            time.sleep(1.0)
            check_cancelled()
            
            update_status(f"Nhập từ khóa '{keyword}' (gõ tự nhiên)...")
            self.input_text_naturally(device_id, keyword)
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
                    
                    # 1. Vuốt xem album ảnh sản phẩm (Swipe Image Carousel)
                    update_status("Vuốt xem album ảnh sản phẩm...")
                    for _ in range(random.randint(1, 2)):
                        check_cancelled()
                        x_start = int(width * 0.85) + random.randint(-20, 20)
                        x_end = int(width * 0.15) + random.randint(-20, 20)
                        y_img = int(height * 0.25) + random.randint(-30, 30)
                        self.swipe(device_id, x_start, y_img, x_end, y_img, duration=random.randint(500, 700))
                        time.sleep(random.uniform(1.5, 2.5))

                    # 2. Vòng lặp cuộn xuống tìm "Xem Shop" từng bước nhỏ (Incremental Scrolling)
                    update_status("Đang cuộn tìm nút Xem Shop...")
                    shop_coords = None
                    # Ta cuộn tối đa 6 lần để tìm nút
                    for find_attempt in range(6):
                        check_cancelled()
                        # Quét tìm nút Xem Shop ở màn hình hiện tại
                        shop_coords = self.find_element_coords_by_text(device_id, "Xem Shop")
                        if shop_coords:
                            break
                        
                        # Nếu chưa thấy, vuốt xuống một khoảng vừa phải (35% chiều cao màn hình) tránh bị trôi qua quá nhanh
                        y_start = int(height * 0.7) + random.randint(-30, 30)
                        y_end = int(height * 0.35) + random.randint(-30, 30)
                        self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(750, 1000))
                        
                        # Đợi ngẫu nhiên 2.0 đến 3.5 giây để đọc thông tin
                        read_delay = random.uniform(2.0, 3.5)
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
                            time.sleep(2.5) # Đợi bảng chọn phân loại hiện lên
                            check_cancelled()
                            
                            # Click chọn một tùy chọn ngẫu nhiên ở vùng thuộc tính
                            self.tap(device_id, int(width * 0.3) + random.randint(-50, 50), int(height * 0.5) + random.randint(-50, 50))
                            time.sleep(1.0)
                            check_cancelled()
                            
                            # Nhấn Back để đóng bảng chọn
                            self.keyevent(device_id, 4)
                            time.sleep(1.5)

                    # 4. Vào dạo Shop
                    if shop_coords:
                        update_status("Đang truy cập cửa hàng...")
                        self.tap(device_id, shop_coords[0], shop_coords[1])
                        time.sleep(4.0) # Đợi trang Shop tải
                        
                        # Dạo trang chủ Shop trong 10-15 giây
                        shop_duration = random.randint(10, 15)
                        shop_start = time.time()
                        update_status(f"Đang dạo trang chủ Shop trong {shop_duration} giây...")
                        while time.time() - shop_start < shop_duration:
                            check_cancelled()
                            y_start = int(height * 0.75) + random.randint(-40, 40)
                            y_end = int(height * 0.3) + random.randint(-40, 40)
                            self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                            
                            read_delay = random.uniform(2.0, 3.5)
                            temp_s = time.time()
                            while time.time() - temp_s < read_delay:
                                time.sleep(0.2)
                                check_cancelled()
                                
                        # Nhấn nút Back để quay lại trang sản phẩm
                        update_status("Hoàn thành dạo Shop. Quay lại sản phẩm...")
                        self.keyevent(device_id, 4) # Quay lại sản phẩm
                        time.sleep(2.5)

                    # 5. Dạo xem thêm chi tiết sản phẩm ở phần dưới sau khi quay lại (10-15 giây)
                    view_duration = random.randint(10, 15)
                    start_time = time.time()
                    update_status(f"Tiếp tục lướt xem thông tin sản phẩm trong {view_duration} giây...")
                    while time.time() - start_time < view_duration:
                        check_cancelled()
                        y_start = int(height * 0.7) + random.randint(-40, 40)
                        y_end = int(height * 0.35) + random.randint(-40, 40)
                        self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                        
                        read_delay = random.uniform(2.0, 3.5)
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
                
            if SHOPEE_SHOP_NAMES:
                update_status("Không tìm thấy shop Lâm Đồng trực tiếp. Chuyển sang tìm theo tên Shop dự phòng...")
                return self.shopee_fallback_by_shop_name(device_id, keyword, status_callback, is_cancelled)
            return False, f"Đã vuốt {max_swipes} lần nhưng không tìm thấy sản phẩm nào có nhãn Tỉnh Lâm Đồng."
        except Exception as e:
            msg = str(e)
            update_status(f"Thất bại: {msg}")
            return False, msg

    def find_and_click_view_shop(self, device_id):
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
                for elem in root.iter():
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    val = text or desc
                    if val and any(k in val.lower() for k in ["xem shop", "xem cửa hàng", "view shop", "visit shop"]):
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
                for elem in root.iter():
                    text = elem.get('text', '')
                    desc = elem.get('content-desc', '')
                    val = text or desc
                    keywords = ["tìm trong shop", "tìm kiếm trong shop", "tìm ở cửa hàng", "tìm kiếm trong cửa hàng", "tìm sản phẩm", "search in shop", "search this shop", "search in store"]
                    if val and any(k in val.lower() for k in keywords):
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
        """Kịch bản dự phòng: Tìm kiếm tên shop, truy cập vào shop, tìm kiếm sản phẩm trong shop và lướt tương tác"""
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)
        def check_cancelled():
            if is_cancelled and is_cancelled():
                raise Exception("Bị dừng bởi người dùng")

        if not SHOPEE_SHOP_NAMES:
            return False, "Không có danh sách shop để chạy dự phòng."

        shop_name = random.choice(SHOPEE_SHOP_NAMES)
        update_status(f"[Dự phòng] Bắt đầu tìm kiếm shop '{shop_name}'...")

        try:
            check_cancelled()
            # 1. Đưa về trang chủ
            self.ensure_shopee_homepage(device_id, status_callback=status_callback)
            self.bypass_shopee_popup(device_id)
            time.sleep(1.0)
            
            # 2. Bấm tìm kiếm trên trang chủ
            update_status("[Dự phòng] Bấm ô tìm kiếm để tìm shop...")
            self.tap(device_id, SHOPEE_SEARCH_BOX_COORDS[0], SHOPEE_SEARCH_BOX_COORDS[1])
            time.sleep(1.5)
            check_cancelled()
            
            self.tap(device_id, SHOPEE_INPUT_BOX_COORDS[0], SHOPEE_INPUT_BOX_COORDS[1])
            time.sleep(1.0)
            check_cancelled()
            
            update_status(f"[Dự phòng] Nhập tên shop '{shop_name}'...")
            self.input_text(device_id, shop_name)
            time.sleep(1.5)
            check_cancelled()
            
            update_status("[Dự phòng] Gửi lệnh tìm kiếm shop...")
            self.press_enter(device_id)
            time.sleep(3.5)
            check_cancelled()

            # 3. Tìm nút "Xem Shop" trên trang kết quả
            update_status("[Dự phòng] Tìm nút Xem Shop...")
            view_shop_coords = self.find_and_click_view_shop(device_id)
            if not view_shop_coords:
                update_status("[Dự phòng] Không tìm thấy nút Xem Shop qua XML, thử click tọa độ dự phòng banner Shop...")
                self.tap(device_id, 500, 380)
            else:
                update_status(f"[Dự phòng] Click vào Xem Shop tại {view_shop_coords}...")
                self.tap(device_id, view_shop_coords[0], view_shop_coords[1])
            
            time.sleep(4.0) # Đợi trang Shop tải
            check_cancelled()

            # 4. Tìm ô tìm kiếm trong Shop
            update_status("[Dự phòng] Tìm ô tìm kiếm trong Shop...")
            shop_search_coords = self.find_shop_search_box(device_id)
            if not shop_search_coords:
                update_status("[Dự phòng] Không tìm thấy ô tìm kiếm trong Shop qua XML, thử click tọa độ dự phòng...")
                self.tap(device_id, 500, 140)
            else:
                update_status(f"[Dự phòng] Click ô tìm kiếm trong Shop tại {shop_search_coords}...")
                self.tap(device_id, shop_search_coords[0], shop_search_coords[1])
                
            time.sleep(1.5)
            check_cancelled()
            
            # Click lại để chắc chắn hiện bàn phím
            self.tap(device_id, 500, 140)
            time.sleep(1.0)
            check_cancelled()

            # 5. Nhập từ khóa sản phẩm và tìm kiếm trong Shop
            update_status(f"[Dự phòng] Nhập từ khóa '{keyword}' trong Shop...")
            self.input_text_naturally(device_id, keyword)
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
            
            update_status("[Dự phòng] Vuốt xem album ảnh sản phẩm...")
            for _ in range(random.randint(1, 2)):
                check_cancelled()
                x_start = int(width * 0.85) + random.randint(-20, 20)
                x_end = int(width * 0.15) + random.randint(-20, 20)
                y_img = int(height * 0.25) + random.randint(-30, 30)
                self.swipe(device_id, x_start, y_img, x_end, y_img, duration=random.randint(500, 700))
                time.sleep(random.uniform(1.5, 2.5))

            update_status("[Dự phòng] Đang cuộn xem thông tin chi tiết...")
            view_duration = random.randint(10, 15)
            start_time = time.time()
            while time.time() - start_time < view_duration:
                check_cancelled()
                y_start = int(height * 0.7) + random.randint(-40, 40)
                y_end = int(height * 0.35) + random.randint(-40, 40)
                self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                
                read_delay = random.uniform(2.0, 3.5)
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
                    time.sleep(2.5)
                    check_cancelled()
                    self.tap(device_id, int(width * 0.3) + random.randint(-50, 50), int(height * 0.5) + random.randint(-50, 50))
                    time.sleep(1.0)
                    check_cancelled()
                    self.keyevent(device_id, 4)
                    time.sleep(1.5)

            # 9. Dạo shop
            update_status("[Dự phòng] Tìm nút Xem Shop...")
            shop_coords = self.find_element_coords_by_text(device_id, "Xem Shop")
            if shop_coords:
                update_status("[Dự phòng] Đang truy cập cửa hàng để dạo...")
                self.tap(device_id, shop_coords[0], shop_coords[1])
                time.sleep(4.0)
                
                shop_duration = random.randint(8, 12)
                shop_start = time.time()
                while time.time() - shop_start < shop_duration:
                    check_cancelled()
                    y_start = int(height * 0.75) + random.randint(-40, 40)
                    y_end = int(height * 0.3) + random.randint(-40, 40)
                    self.swipe_curved(device_id, cx, y_start, cx, y_end, duration=random.randint(700, 1000))
                    
                    read_delay = random.uniform(2.0, 3.5)
                    temp_s = time.time()
                    while time.time() - temp_s < read_delay:
                        time.sleep(0.2)
                        check_cancelled()
                        
                update_status("[Dự phòng] Hoàn thành dạo Shop. Quay lại sản phẩm...")
                self.keyevent(device_id, 4)
                time.sleep(2.5)

            update_status("[Dự phòng] Hoàn thành quy trình tương tác sản phẩm!")
            return True, "Thành công (Dự phòng qua tên Shop)"
        except Exception as e:
            return False, f"Lỗi dự phòng: {str(e)}"





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

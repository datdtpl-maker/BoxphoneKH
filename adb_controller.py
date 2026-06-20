import subprocess
import base64
import time
import os
import xml.etree.ElementTree as ET
import re
import random
import cv2
from concurrent.futures import ThreadPoolExecutor
from config import ADB_PATH, SHOPEE_PACKAGE, SHOPEE_SEARCH_BOX_COORDS, SHOPEE_INPUT_BOX_COORDS, SHOPEE_SEARCH_BTN_COORDS
from captcha_solver import CaptchaSolver

class ADBController:
    def __init__(self, adb_path=ADB_PATH):
        self.adb_path = adb_path
        self.solver = CaptchaSolver(debug_dir=os.path.join(os.path.dirname(__file__), 'debug'))

    def _run_cmd(self, cmd_args, timeout=15):
        """Chạy lệnh hệ thống với ADB"""
        full_cmd = [self.adb_path] + cmd_args
        try:
            result = subprocess.run(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=timeout
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

    def keyevent(self, device_id, keycode):
        """Gửi mã phím hệ thống (ví dụ: 3=Home, 4=Back, 66=Enter)"""
        return self.execute_adb(device_id, ["shell", "input", "keyevent", str(keycode)])

    def launch_app(self, device_id, package_name):
        """Khởi chạy một ứng dụng bằng package name"""
        # Sử dụng monkey để khởi chạy nhanh app từ launcher
        return self.execute_adb(device_id, ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])

    def stop_app(self, device_id, package_name):
        """Buộc dừng một ứng dụng"""
        return self.execute_adb(device_id, ["shell", "am", "force-stop", package_name])

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
            update_status("Đang mở Shopee...")
            self.launch_app(device_id, SHOPEE_PACKAGE)
            
            # Đợi Shopee tải (khoảng 7 giây)
            for _ in range(7):
                time.sleep(1.0)
                check_cancelled()
            
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
        Tự động kiểm tra xem thiết bị có bị kẹt Captcha hay không.
        Nếu phát hiện bị kẹt, tiến hành chụp màn hình và gọi module OpenCV để tự động kéo giải Captcha.
        """
        def update_status(msg):
            if status_callback:
                status_callback(device_id, msg)

        temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        screenshot_path = os.path.join(temp_dir, f"captcha_check_{device_id}.png")

        for attempt in range(max_retries):
            # 1. Chụp ảnh màn hình hiện tại
            success, _ = self.take_screenshot(device_id, screenshot_path)
            if not success:
                time.sleep(1.0)
                continue

            # 2. Phân tích ảnh tìm mảnh ghép captcha
            distance = self.solver.find_slider_distance(screenshot_path, device_id)
            
            # Xóa file chụp màn hình tạm
            try:
                os.remove(screenshot_path)
            except Exception:
                pass

            # 3. Nếu tìm thấy mảnh ghép, tiến hành kéo
            if distance:
                update_status(f"[Captcha] Phát hiện dính Captcha. Đang giải lần {attempt + 1}/{max_retries}...")
                
                # Tọa độ Y tương đối của thanh kéo thường ở khoảng 62% chiều cao màn hình (ví dụ 1190px trên 1920px)
                img_path = os.path.join(os.path.dirname(__file__), 'debug', f"result_solved_{device_id}.png")
                if os.path.exists(img_path):
                    try:
                        img = cv2.imread(img_path)
                        h_img = img.shape[0]
                        y_slider = int(h_img * 0.62)
                    except Exception:
                        y_slider = 1190
                else:
                    y_slider = 1190
                
                # Tọa độ X bắt đầu của slider handle thường ở khoảng X=160
                x_start = 160
                x_end = x_start + distance
                
                # Giả lập thao tác vuốt với quỹ đạo người dùng (thời gian kéo ngẫu nhiên, lệch trục Y nhẹ)
                y_end = y_slider + random.randint(-4, 4)
                duration = random.randint(1200, 1600)
                
                # Thực hiện kéo
                self.swipe(device_id, x_start, y_slider, x_end, y_end, duration)
                time.sleep(5.0) # Đợi trang phản hồi sau khi kéo
                continue
            else:
                # Nếu không tìm thấy mảnh ghép nào, coi như màn hình hiện tại Sạch (Không có Captcha)
                if attempt == 0:
                    return True
                else:
                    update_status("[Captcha] Giải Captcha thành công! Tiếp tục quy trình...")
                    return True

        # Đã thử hết số lần quy định nhưng vẫn dính Captcha
        update_status("[Captcha] Không thể tự giải Captcha sau nhiều lần thử.")
        return False

    def shopee_find_and_click_lamdong(self, device_id, keyword, max_swipes=10, status_callback=None, is_cancelled=None):
        """Kịch bản tìm kiếm từ khóa và tự động vuốt màn hình để tìm + click vào shop có nhãn 'Tỉnh Lâm Đồng'"""
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
            update_status("Đang mở Shopee...")
            self.launch_app(device_id, SHOPEE_PACKAGE)
            
            # Đợi Shopee tải (khoảng 7 giây)
            for _ in range(7):
                time.sleep(1.0)
                check_cancelled()
            
            # Kiểm tra Captcha lần 1 sau khi mở ứng dụng
            if not self.check_and_bypass_captcha(device_id, max_retries=3, status_callback=status_callback):
                return False, "Bị chặn bởi Captcha (Không thể tự giải sau khi mở Shopee)"
            
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
                    self.swipe(device_id, 540, 1400, 540, 500, duration=800)
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
                        for elem in root.iter():
                            text = elem.get('text', '')
                            if 'Lâm Đồng' in text or 'Tỉnh Lâm Đồng' in text:
                                bounds = elem.get('bounds', '')
                                m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                                if m:
                                    x1, y1, x2, y2 = map(int, m.groups())
                                    found_coords = ((x1 + x2) // 2, (y1 + y2) // 2)
                                    break
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
                    
                    # Thực hiện lướt xem ngẫu nhiên 10 - 20 giây
                    view_duration = random.randint(10, 20)
                    start_time = time.time()
                    update_status(f"Đã mở sản phẩm. Đang lướt xem ngẫu nhiên trong {view_duration} giây...")
                    
                    while time.time() - start_time < view_duration:
                        check_cancelled()
                        self.swipe(device_id, 540, 1300, 540, 600, duration=random.randint(600, 900))
                        
                        for _ in range(12):
                            time.sleep(random.uniform(0.2, 0.3))
                            check_cancelled()
                        
                        if random.random() < 0.3:
                            self.swipe(device_id, 540, 600, 540, 1200, duration=random.randint(600, 900))
                            for _ in range(10):
                                time.sleep(random.uniform(0.2, 0.3))
                                check_cancelled()
                            
                    update_status("Hoàn thành quy trình lướt xem sản phẩm!")
                    return True, "Thành công"
                
                # Nếu không tìm thấy, vuốt cuộn xuống dưới
                update_status("Chưa thấy Lâm Đồng, đang vuốt xuống dưới...")
                self.swipe(device_id, 540, 1400, 540, 500, duration=800)
                
                for _ in range(10):
                    time.sleep(0.25)
                    check_cancelled()
                
            return False, f"Đã vuốt {max_swipes} lần nhưng không tìm thấy sản phẩm nào có nhãn Tỉnh Lâm Đồng."
        except Exception as e:
            msg = str(e)
            update_status(f"Thất bại: {msg}")
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

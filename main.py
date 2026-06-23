import os
import re
import time
import sys
import telebot
from concurrent.futures import ThreadPoolExecutor
import threading
import random
import config
from adb_controller import ADBController

# Reconfigure stdout/stderr to use UTF-8 encoding to prevent charmap errors on Windows
if sys.platform.startswith('win'):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')


# Khởi tạo Bot Telegram và ADB Controller
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
adb = ADBController()

# Các biến toàn cục điều khiển chạy tuần tự và hủy bỏ tác vụ
cancel_sequential = False
cancel_flag = False
sequential_thread = None

def is_cancelled():
    global cancel_flag
    return cancel_flag

# Caching mapping thiết bị toàn cục để tra cứu nhanh
cached_mapping = {}

def get_ordered_devices():
    global cached_mapping
    raw_devices = adb.get_devices()
    search_dirs = [
        r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\Local Storage\leveldb",
        r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb",
        r"C:\Users\datdt\AppData\Local\com.xiaowei.android\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb"
    ]
    
    # 1. Thu thập tất cả file leveldb cùng mtime của chúng
    db_files = []
    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for root, _, files in os.walk(sdir):
            for file in files:
                filepath = os.path.join(root, file)
                if os.path.isfile(filepath):
                    db_files.append((filepath, os.path.getmtime(filepath)))
                    
    # Sắp xếp file theo mtime tăng dần để file mới được ghi sau cùng (ghi đè lên)
    db_files.sort(key=lambda x: x[1])
    
    mapping = {}
    for filepath, _ in db_files:
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            for serial in raw_devices:
                serial_bytes = serial.encode('utf-8')
                idx = 0
                while True:
                    idx = data.find(serial_bytes, idx)
                    if idx == -1:
                        break
                    chunk = data[idx:idx+350]
                    name_idx = chunk.find(b'name')
                    if name_idx != -1:
                        subchunk = chunk[name_idx + 4 : name_idx + 30]
                        m = re.search(b'[a-zA-Z0-9_\\-\\+]+', subchunk)
                        if m:
                            name_val = m.group(0).decode('utf-8')
                            if name_val not in ['name', 'onlySerial', 'serial', 'sort']:
                                # Ghi đè liên tục để lấy giá trị cuối cùng (mới nhất)
                                mapping[serial] = name_val
                    idx += len(serial_bytes)
        except Exception:
            pass

    # Lưu trữ mapping vào cache toàn cục
    cached_mapping = mapping

    # Nhóm các serial theo tên chuẩn hóa (ví dụ "s10")
    grouped = {}  # name_lower -> list of serials
    unmapped = [] # list of serials
    
    for serial in raw_devices:
        name = mapping.get(serial, "")
        m = re.match(r'^s(\d+)$', name.lower())
        if m:
            name_lower = name.lower()
            if name_lower not in grouped:
                grouped[name_lower] = []
            grouped[name_lower].append(serial)
        else:
            unmapped.append(serial)
            
    # Lọc trùng lặp: Với mỗi tên máy, chỉ giữ lại 1 serial tốt nhất (ưu tiên kết nối USB)
    filtered_devices = []
    
    # Sắp xếp các tên từ s1 đến s20
    sorted_names = sorted(grouped.keys(), key=lambda x: int(re.match(r'^s(\d+)$', x).group(1)))
    
    for name in sorted_names:
        serials = grouped[name]
        if len(serials) == 1:
            filtered_devices.append(serials[0])
        else:
            # Ưu tiên serial kết nối USB (không chứa dấu ':' của Wifi IP)
            usb_serials = [s for s in serials if ":" not in s]
            if usb_serials:
                filtered_devices.append(usb_serials[0])
            else:
                filtered_devices.append(serials[0])
                
    # Thêm các thiết bị không map được vào cuối
    filtered_devices.extend(unmapped)
    
    return filtered_devices

def get_device_name(serial):
    """Lấy tên map thực tế của thiết bị (ví dụ: S1, S10) hoặc rút gọn serial nếu không có"""
    global cached_mapping
    # Nếu chưa có cache, chạy quét nhanh dựng mapping
    if not cached_mapping:
        raw_devices = adb.get_devices()
        db_files = []
        search_dirs = [
            r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\Local Storage\leveldb",
            r"C:\Users\datdt\AppData\Local\xiaowei\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb",
            r"C:\Users\datdt\AppData\Local\com.xiaowei.android\EBWebView\Default\IndexedDB\https_tauri.localhost_0.indexeddb.leveldb"
        ]
        for sdir in search_dirs:
            if not os.path.exists(sdir):
                continue
            for root, _, files in os.walk(sdir):
                for file in files:
                    filepath = os.path.join(root, file)
                    if os.path.isfile(filepath):
                        db_files.append((filepath, os.path.getmtime(filepath)))
        db_files.sort(key=lambda x: x[1])
        for filepath, _ in db_files:
            try:
                with open(filepath, 'rb') as f:
                    data = f.read()
                for s in raw_devices:
                    s_bytes = s.encode('utf-8')
                    idx = 0
                    while True:
                        idx = data.find(s_bytes, idx)
                        if idx == -1:
                            break
                        chunk = data[idx:idx+350]
                        name_idx = chunk.find(b'name')
                        if name_idx != -1:
                            subchunk = chunk[name_idx + 4 : name_idx + 30]
                            m = re.search(b'[a-zA-Z0-9_\\-\\+]+', subchunk)
                            if m:
                                name_val = m.group(0).decode('utf-8')
                                if name_val not in ['name', 'onlySerial', 'serial', 'sort']:
                                    cached_mapping[s] = name_val
                        idx += len(s_bytes)
            except Exception:
                pass
                
    name = cached_mapping.get(serial, "")
    if name:
        if name.lower().startswith("s") and name[1:].isdigit():
            return f"S{name[1:]}"
        return name
        
    if ":" in serial:
        return f"Wifi_{serial.split(':')[0].split('.')[-1]}"
    if len(serial) > 8:
        return f"{serial[:8].upper()}"
    return serial

def run_sequential_shopee_search(message, keywords, devices, click_first_item=False):
    global cancel_sequential, cancel_flag
    cancel_sequential = False
    cancel_flag = False
    
    keyword_str = ", ".join(keywords)
    
    # Tạo nút dừng dạng Inline Keyboard đính kèm trực tiếp dưới tin nhắn
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
    
    start_msg = bot.send_message(
        message.chat.id, 
        f"⏳ **BẮT ĐẦU CHẠY TUẦN TỰ**\n\n"
        f"Danh sách từ khóa: `{keyword_str}`\n"
        f"Tổng số máy: {len(devices)} máy\n"
        f"Nghỉ giữa mỗi phiên: **60 - 90 giây**.\n\n"
        f"*(Bạn có thể bấm nút dừng ở bên dưới bất kỳ lúc nào)*",
        parse_mode="Markdown",
        reply_markup=markup
    )
    
    success_count = 0
    for idx, dev in enumerate(devices):
        if cancel_sequential or cancel_flag:
            try:
                bot.edit_message_reply_markup(message.chat.id, start_msg.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(message.chat.id, "⏹️ **ĐÃ DỪNG CHẠY TUẦN TỰ** theo yêu cầu của bạn.")
            break
            
        dev_name = get_device_name(dev)
        current_keyword = random.choice(keywords)
        bot.send_message(message.chat.id, f"📱 **Máy {dev_name}/{len(devices)}** ({dev}): Bắt đầu tìm với từ khóa `{current_keyword}`...")
        
        success, err = adb.shopee_find_and_click_lamdong(dev, current_keyword, is_cancelled=is_cancelled, click_first_item=click_first_item)
        
        if cancel_sequential or cancel_flag:
            try:
                bot.edit_message_reply_markup(message.chat.id, start_msg.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(message.chat.id, "⏹️ **ĐÃ DỪNG CHẠY TUẦN TỰ** theo yêu cầu của bạn.")
            break
            
        if success:
            success_count += 1
            bot.send_message(message.chat.id, f"✅ **Máy {dev_name}**: Đã hoàn thành trọn vẹn quy trình (Lướt sản phẩm & dạo Shop) với từ khóa `{current_keyword}`!")
        else:
            bot.send_message(message.chat.id, f"❌ **Máy {dev_name}**: {err}")
            if "Captcha" in err or "bị chặn" in err.lower():
                temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                screenshot_path = os.path.join(temp_dir, f"captcha_alert_{dev_name}.png")
                sc_success, _ = adb.take_screenshot(dev, screenshot_path)
                if sc_success:
                    with open(screenshot_path, 'rb') as photo:
                        bot.send_photo(
                            message.chat.id, 
                            photo, 
                            caption=f"🚨 **CẢNH BÁO CAPTCHA - MÁY {dev_name}**\n\nHệ thống đã thử tự động giải bằng OpenCV nhưng thất bại. Vui lòng giải tay máy này trên phần mềm xiaowei!"
                        )
                    try:
                        os.remove(screenshot_path)
                    except Exception:
                        pass
            
        if idx < len(devices) - 1:
            delay = random.randint(60, 90)
            bot.send_message(message.chat.id, f"⏳ Đợi **{delay} giây** trước khi sang máy tiếp theo...")
            
            for _ in range(delay):
                if cancel_sequential or cancel_flag:
                    break
                time.sleep(1)
                
    if not cancel_sequential and not cancel_flag:
        try:
            bot.edit_message_reply_markup(message.chat.id, start_msg.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(
            message.chat.id, 
            f"🏁 **HOÀN THÀNH QUY TRÌNH CHẠY TUẦN TỰ**\n\n"
            f"Đã xử lý xong: **{len(devices)}/{len(devices)} máy**\n"
            f"Thành công: **{success_count} máy**",
            parse_mode="Markdown"
        )



# Hàm cập nhật ALLOWED_USER_IDS vào file .env để lưu cấu hình bảo mật lâu dài
def save_admin_to_env(user_id):
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("ALLOWED_USER_IDS="):
            new_lines.append(f"ALLOWED_USER_IDS={user_id}\n")
            updated = True
        else:
            new_lines.append(line)
            
    if not updated:
        new_lines.append(f"ALLOWED_USER_IDS={user_id}\n")
        
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    # Cập nhật trực tiếp vào cấu hình đang chạy
    config.ALLOWED_USER_IDS = [user_id]

# Middleware kiểm tra quyền truy cập (chỉ cho phép admin đã cấu hình)
def check_auth(message):
    user_id = message.from_user.id
    
    # Nếu danh sách admin đang trống (lần đầu tiên sử dụng bot)
    if not config.ALLOWED_USER_IDS:
        save_admin_to_env(user_id)
        bot.reply_to(
            message, 
            f"🔒 **BẢO MẬT HỆ THỐNG**\n\n"
            f"Hệ thống đã nhận diện tài khoản của bạn (ID: `{user_id}`) là tài khoản gửi lệnh đầu tiên.\n"
            f"Tài khoản của bạn đã được lưu làm **Quản trị viên duy nhất** điều khiển Box Phone.\n"
            f"Các tài khoản khác gửi tin nhắn đến bot này từ nay sẽ bị chặn để an toàn."
        )
        return True
        
    # Nếu đã cấu hình admin, kiểm tra xem ID gửi lệnh có khớp không
    if user_id not in config.ALLOWED_USER_IDS:
        bot.reply_to(message, "❌ Bạn không có quyền truy cập hệ thống này.")
        return False
        
    return True

# Hàm phân tích lệnh từ ngôn ngữ tự nhiên tiếng Việt
def parse_natural_command(text):
    text = text.lower().strip()
    
    # 1. Trạng thái / Danh sách máy
    if any(k in text for k in ["danh sách", "liệt kê", "trạng thái", "devices", "status", "list"]):
        return {"action": "list_devices"}
        
    # 2. Chụp màn hình điện thoại
    # Định dạng: "chụp màn hình máy 5", "chụp ảnh máy số 12", "chụp máy 1"
    m_screenshot = re.search(r"(?:chụp màn hình|chụp ảnh|chụp)\s*(?:máy|máy số|số|device)?\s*(\d+)", text)
    if m_screenshot:
        return {"action": "screenshot", "device_idx": int(m_screenshot.group(1))}
        
    # 3. Phím Quay lại (Back)
    if any(k in text for k in ["quay lại", "nút quay lại", "back", "trở về"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m.group(1)) if m else None
        return {"action": "back", "device_idx": device_idx}
        
    # 4. Phím Trang chủ (Home)
    if any(k in text for k in ["trang chủ", "nút home", "home", "màn hình chính"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m.group(1)) if m else None
        return {"action": "home", "device_idx": device_idx}
        
    # 5. Mở ứng dụng Shopee
    if "mở shopee" in text or "mở ứng dụng shopee" in text or "chạy shopee" in text:
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m.group(1)) if m else None
        return {"action": "open_shopee", "device_idx": device_idx}
        
    # 6. Đóng ứng dụng Shopee
    if "đóng shopee" in text or "tắt shopee" in text or "đóng ứng dụng shopee" in text:
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m.group(1)) if m else None
        return {"action": "close_shopee", "device_idx": device_idx}

    # 7. Tìm kiếm sản phẩm trên Shopee
    # Các mẫu: "tìm áo thun trên shopee", "mở shopee tìm áo khoác máy 3", "shopee tìm giày thể thao"
    shopee_keywords = ["shopee", "tìm", "tìm kiếm"]
    if any(k in text for k in shopee_keywords):
        # Xác định máy chỉ định (nếu có)
        m_device = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m_device.group(1)) if m_device else None
        
        # Trích xuất từ khóa tìm kiếm
        keyword = ""
        # Trích xuất dạng "tìm kiếm [từ khóa] trên shopee" hoặc "tìm [từ khóa] ở shopee"
        m_search = re.search(r"(?:tìm kiếm|tìm)\s+(.+?)\s+(?:trên|ở)\s+shopee", text)
        if m_search:
            keyword = m_search.group(1)
        else:
            # Trích xuất dạng "shopee tìm [từ khóa]" hoặc "mở shopee tìm [từ khóa]"
            m_search = re.search(r"shopee\s+(?:tìm kiếm|tìm)\s+(.+)", text)
            if m_search:
                keyword = m_search.group(1)
            else:
                # Trích xuất dạng "tìm shopee [từ khóa]"
                m_search = re.search(r"(?:tìm kiếm|tìm)\s+shopee\s+(.+)", text)
                if m_search:
                    keyword = m_search.group(1)
                else:
                    # Trích xuất dạng mặc định "tìm [từ khóa]"
                    m_search = re.search(r"(?:tìm kiếm|tìm)\s+(.+)", text)
                    if m_search:
                        keyword = m_search.group(1)
        
        # Dọn dẹp từ khóa tìm kiếm (bỏ phần chỉ định máy)
        if keyword:
            keyword = re.sub(r"(?:cho|ở|trên)?\s*(?:máy|máy số|số|device)\s*\d+", "", keyword)
            keyword = keyword.strip()
            
            # Kiểm tra xem có yêu cầu tìm shop Lâm Đồng hay không
            if "lâm đồng" in text or "lam dong" in text:
                # Phát hiện hậu tố click sản phẩm đầu tiên
                click_first_item = False
                first_item_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
                if any(ind in text for ind in first_item_indicators):
                    click_first_item = True
                
                # Làm sạch từ khóa
                keyword_clean = re.sub(r"(?:tỉnh\s+)?(?:lâm\s+đồng|lam\s+dong)", "", keyword, flags=re.IGNORECASE)
                keyword_clean = re.sub(r"(?:tuần\s+tự|tuan\s+tu|lần\s+lượt|lan\s+luot)", "", keyword_clean, flags=re.IGNORECASE)
                
                # Loại bỏ các từ khóa chỉ định click sản phẩm đầu tiên khỏi từ khóa chính
                for ind in first_item_indicators:
                    keyword_clean = re.sub(r"\b" + re.escape(ind) + r"\b", "", keyword_clean, flags=re.IGNORECASE)
                
                keyword_clean = re.sub(r"\s+", " ", keyword_clean).strip()
                
                # Tách nhiều từ khóa bằng dấu phẩy, chấm phẩy hoặc gạch đứng
                keywords = [k.strip() for k in re.split(r'[,;|]', keyword_clean) if k.strip()]
                if not keywords:
                    keywords = [keyword_clean]
                
                if any(k in text for k in ["tuần tự", "tuan tu", "lần lượt", "lan luot"]):
                    return {
                        "action": "shopee_search_lamdong_sequential", 
                        "keywords": keywords, 
                        "device_idx": device_idx,
                        "click_first_item": click_first_item
                    }
                return {
                    "action": "shopee_search_lamdong", 
                    "keywords": keywords, 
                    "device_idx": device_idx,
                    "click_first_item": click_first_item
                }
                
            keywords = [k.strip() for k in re.split(r'[,;|]', keyword) if k.strip()]
            if not keywords:
                keywords = [keyword]
            return {"action": "shopee_search", "keywords": keywords, "device_idx": device_idx}
            
    # 8. Lệnh Click tọa độ thủ công: "click 500 600 máy 1" hoặc "click 500 600" (tất cả máy)
    m_click = re.search(r"click\s+(\d+)\s+(\d+)(?:\s+(?:máy|máy số|số|device)?\s*(\d+))?", text)
    if m_click:
        x, y = int(m_click.group(1)), int(m_click.group(2))
        device_idx = int(m_click.group(3)) if m_click.group(3) else None
        return {"action": "click", "x": x, "y": y, "device_idx": device_idx}

    # 9. Lệnh Nhập text thủ công: "nhập hello world máy 1" hoặc "nhập xin chào" (tất cả máy)
    m_input = re.search(r"nhập\s+(.+?)(?:\s+(?:máy|máy số|số|device)\s*(\d+))?$", text)
    if m_input:
        input_text_val = m_input.group(1).strip()
        device_idx = int(m_input.group(2)) if m_input.group(2) else None
        return {"action": "input", "text": input_text_val, "device_idx": device_idx}

    # Lệnh Dừng tất cả các tác vụ đang chạy
    if any(k in text for k in ["dừng chạy", "dừng tất cả", "dừng", "hủy chạy", "dung chay", "huy chay", "stop"]):
        return {"action": "stop_all"}

    # 10. Tắt xoay màn hình
    if any(k in text for k in ["tắt xoay màn hình", "tắt xoay", "tắt tự động xoay", "khóa màn hình dọc"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text)
        device_idx = int(m.group(1)) if m else None
        return {"action": "disable_rotation", "device_idx": device_idx}

    return None

# Xử lý lệnh /start và /help để hiển thị hướng dẫn ngắn gọn
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not check_auth(message):
        return

    instructions = (
        "🤖 **BOX PHONE - SHOPEE KHẢI HOÀN** 📱\n\n"
        "Chào mừng Admin! Danh sách lệnh mẫu dễ sao chép:\n\n"
        "🔄 **1. Tìm kiếm & Click sản phẩm (Tự động hoàn toàn)**\n"
        "👉 **Chạy TUẦN TỰ (Khuyên dùng - Nghỉ 60-90s giữa các máy):**\n"
        "• Chế độ tìm Lâm Đồng: `tìm tuần tự lâm đồng deriva, son môi`\n"
        "• Chế độ click bài đầu tiên (Video): `tìm tuần tự lâm đồng deriva video` hoặc `tìm tuần tự lâm đồng deriva đầu tiên`\n\n"
        "👉 **Chạy SONG SONG (Tất cả các máy cùng chạy một lúc):**\n"
        "• Chế độ tìm Lâm Đồng: `tìm lâm đồng deriva`\n"
        "• Chế độ click bài đầu tiên (Video): `tìm lâm đồng deriva video`\n\n"
        "👉 **Chạy trên MỘT MÁY chỉ định (Ví dụ: Máy 5):**\n"
        "• Chế độ tìm Lâm Đồng: `máy 5 tìm lâm đồng deriva`\n"
        "• Chế độ click bài đầu tiên (Video): `máy 5 tìm lâm đồng deriva video`\n\n"
        "⏹️ **Dừng chạy khẩn cấp tất cả các máy:**\n"
        "• Bấm nút `🛑 DỪNG CHẠY KHẨN CẤP` đính kèm dưới tin nhắn chạy\n"
        "• Hoặc gửi lệnh chat: `dừng`, `stop` hoặc `/stop`\n\n"
        "📸 **2. Chụp ảnh màn hình kiểm tra (Giải Captcha):**\n"
        "• `chụp màn hình máy 1` (Thay số máy bạn muốn kiểm tra)\n\n"
        "📊 **3. Kiểm tra danh sách & Kết nối điện thoại:**\n"
        "• `trạng thái` hoặc `danh sách máy`\n\n"
        "⚙️ **4. Các phím điều khiển nhanh (Tất cả hoặc máy chỉ định):**\n"
        "• `quay lại` | `quay lại máy 5`\n"
        "• `trang chủ` | `trang chủ máy 5`\n"
        "• `tắt xoay` | `tắt xoay máy 5`\n"
        "• `mở shopee` | `đóng shopee` | `mở shopee máy 5`"
    )
    bot.reply_to(message, instructions, parse_mode="Markdown")

# Xử lý tất cả tin nhắn văn bản (Ngôn ngữ tự nhiên)
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if not check_auth(message):
        return

    text = message.text
    cmd = parse_natural_command(text)
    
    if not cmd:
        bot.reply_to(message, "❓ Bot chưa hiểu câu lệnh này của bạn. Bạn gõ `/help` để xem danh sách các câu lệnh mẫu nhé.")
        return

    # Lấy danh sách thiết bị
    devices = get_ordered_devices()
    if not devices:
        bot.reply_to(message, "❌ Không tìm thấy thiết bị điện thoại nào đang kết nối. Vui lòng kiểm tra lại dây cáp.")
        return

    action = cmd["action"]
    device_idx = cmd.get("device_idx")

    # Xác định các thiết bị sẽ chịu tác động của lệnh
    target_devices = []
    if device_idx is not None:
        # Số thứ tự user nhập là 1-indexed (1-20)
        idx = device_idx - 1
        if 0 <= idx < len(devices):
            target_devices = [devices[idx]]
        else:
            bot.reply_to(message, f"❌ Không tìm thấy máy số {device_idx}. Hiện tại chỉ có {len(devices)} máy (từ 1 đến {len(devices)}).")
            return
    else:
        target_devices = devices

    # Thực hiện hành động cụ thể
    if action == "list_devices":
        response = f"📊 **DANH SÁCH THIẾT BỊ ĐANG KẾT NỐI ({len(devices)} máy):**\n\n"
        for d in devices:
            response += f"📱 **Máy {get_device_name(d)}**: ID: `{d}`\n"
        bot.reply_to(message, response, parse_mode="Markdown")

    elif action == "screenshot":
        # Hành động chụp ảnh màn hình (chỉ hỗ trợ từng máy một để tránh spam ảnh)
        # Nếu user gõ "chụp ảnh" mà không nói máy nào, mặc định lấy máy 1
        tgt_dev = target_devices[0]
        tgt_name = get_device_name(tgt_dev)
        
        status_msg = bot.reply_to(message, f"📸 Đang chụp màn hình máy {tgt_name}...")
        
        # Tạo đường dẫn lưu ảnh tạm
        temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        local_path = os.path.join(temp_dir, f"screenshot_{tgt_name}.png")
        
        success, result = adb.take_screenshot(tgt_dev, local_path)
        
        if success:
            bot.delete_message(message.chat.id, status_msg.message_id)
            with open(local_path, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=f"🖼️ Ảnh chụp màn hình **Máy {tgt_name}**")
            # Xóa file tạm trên máy tính
            try:
                os.remove(local_path)
            except Exception:
                pass
        else:
            bot.edit_message_text(f"❌ Không thể chụp màn hình máy {tgt_name}. Lỗi: {result}", message.chat.id, status_msg.message_id)

    elif action == "shopee_search":
        keywords = cmd["keywords"]
        
        if len(target_devices) == 1:
            tgt_name = get_device_name(target_devices[0])
            current_keyword = random.choice(keywords)
            status_msg = bot.reply_to(message, f"🛒 **Máy {tgt_name}**: Bắt đầu mở Shopee và tìm kiếm '{current_keyword}'...")
            
            def cb(dev_id, msg):
                pass
                
            success, err = adb.shopee_search_sequence(target_devices[0], current_keyword, status_callback=cb, is_cancelled=is_cancelled)
            if success:
                bot.edit_message_text(f"✅ **Máy {tgt_name}**: Đã hoàn thành tìm kiếm '{current_keyword}'.", message.chat.id, status_msg.message_id)
            else:
                bot.edit_message_text(f"❌ **Máy {tgt_name}**: Thất bại. Lỗi: {err}", message.chat.id, status_msg.message_id)
        else:
            keyword_str = ", ".join(keywords)
            # Tạo nút dừng dạng Inline Keyboard đính kèm trực tiếp dưới tin nhắn
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
            status_msg = bot.reply_to(message, f"🚀 Đang khởi tạo tìm kiếm ngẫu nhiên từ khóa `{keyword_str}` trên {len(target_devices)} máy cùng lúc...", reply_markup=markup)
            
            def run_search_parallel(device_id):
                dev_name = get_device_name(device_id)
                current_keyword = random.choice(keywords)
                bot.send_message(message.chat.id, f"🔍 **Máy {dev_name}**: Bắt đầu tìm với từ khóa `{current_keyword}`...")
                success, err = adb.shopee_search_sequence(device_id, current_keyword, is_cancelled=is_cancelled)
                return dev_name, current_keyword, success, err
                
            results = []
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in target_devices]
                for future in futures:
                    results.append(future.result())
            
            success_count = sum(1 for r in results if r[2])
            fail_count = len(results) - success_count
            
            summary = f"🏁 **KẾT QUẢ TÌM KIẾM SHOPEE:**\n\n"
            summary += f"✅ Thành công: **{success_count}/{len(target_devices)} máy**\n"
            if fail_count > 0:
                summary += f"❌ Thất bại: **{fail_count} máy**\n"
                fails_list = [f"Máy {r[0]} ({r[1]}): {r[3]}" for r in results if not r[2]]
                summary += f"⚠️ Các máy lỗi:\n" + "\n".join(fails_list)
            
            # Cập nhật kết quả đồng thời gỡ nút bấm Inline bằng reply_markup=None
            bot.edit_message_text(summary, message.chat.id, status_msg.message_id, reply_markup=None)

    elif action == "shopee_search_lamdong":
        keywords = cmd["keywords"]
        click_first = cmd.get("click_first_item", False)
        
        if len(target_devices) == 1:
            tgt_name = get_device_name(target_devices[0])
            current_keyword = random.choice(keywords)
            status_msg = bot.reply_to(message, f"🔍 **Máy {tgt_name}**: Đang tìm kiếm '{current_keyword}' và quét tìm shop ở Lâm Đồng...")
            
            def cb(dev_id, msg):
                bot.edit_message_text(f"🔍 **Máy {tgt_name}**: {msg}", message.chat.id, status_msg.message_id)
                
            success, err = adb.shopee_find_and_click_lamdong(target_devices[0], current_keyword, status_callback=cb, is_cancelled=is_cancelled, click_first_item=click_first)
            if success:
                bot.edit_message_text(f"🎉 **Máy {tgt_name}**: Đã hoàn thành trọn vẹn quy trình (Lướt sản phẩm & dạo Shop) với từ khóa `{current_keyword}`!", message.chat.id, status_msg.message_id)
            else:
                bot.edit_message_text(f"❌ **Máy {tgt_name}**: Thất bại. Lỗi: {err}", message.chat.id, status_msg.message_id)
                if "Captcha" in err or "bị chặn" in err.lower():
                    temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
                    os.makedirs(temp_dir, exist_ok=True)
                    screenshot_path = os.path.join(temp_dir, f"captcha_alert_{tgt_name}.png")
                    sc_success, _ = adb.take_screenshot(target_devices[0], screenshot_path)
                    if sc_success:
                        with open(screenshot_path, 'rb') as photo:
                            bot.send_photo(
                                message.chat.id, 
                                photo, 
                                caption=f"🚨 **CẢNH BÁO CAPTCHA - MÁY {tgt_name}**\n\nHệ thống đã thử tự động giải bằng OpenCV nhưng thất bại. Vui lòng giải tay trên phần mềm xiaowei!"
                            )
                        try:
                            os.remove(screenshot_path)
                        except Exception:
                            pass
        else:
            keyword_str = ", ".join(keywords)
            # Tạo nút dừng dạng Inline Keyboard đính kèm trực tiếp dưới tin nhắn
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
            status_msg = bot.reply_to(message, f"🚀 Bắt đầu quét shop Lâm Đồng ngẫu nhiên từ khóa `{keyword_str}` trên tất cả {len(target_devices)} máy cùng lúc...", reply_markup=markup)
            
            def run_search_parallel(device_id):
                dev_name = get_device_name(device_id)
                current_keyword = random.choice(keywords)
                bot.send_message(message.chat.id, f"🔍 **Máy {dev_name}**: Bắt đầu quét từ khóa `{current_keyword}`...")
                success, err = adb.shopee_find_and_click_lamdong(device_id, current_keyword, is_cancelled=is_cancelled, click_first_item=click_first)
                return dev_name, current_keyword, success, err
                
            results = []
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in target_devices]
                for future in futures:
                    results.append(future.result())
            
            success_count = sum(1 for r in results if r[2])
            fail_count = len(results) - success_count
            
            summary = f"🏁 **KẾT QUẢ TÌM SHOP LÂM ĐỒNG:**\n\n"
            summary += f"✅ Hoàn thành trọn vẹn quy trình: **{success_count}/{len(target_devices)} máy**\n"
            if fail_count > 0:
                summary += f"❌ Thất bại (không thấy/lỗi): **{fail_count} máy**\n"
                fails_list = [f"Máy {r[0]} ({r[1]}): {r[3]}" for r in results if not r[2]]
                summary += f"⚠️ Chi tiết lỗi:\n" + "\n".join(fails_list)
            
            # Cập nhật kết quả đồng thời gỡ nút bấm Inline bằng reply_markup=None
            bot.edit_message_text(summary, message.chat.id, status_msg.message_id, reply_markup=None)

    elif action == "shopee_search_lamdong_sequential":
        keywords = cmd["keywords"]
        click_first = cmd.get("click_first_item", False)
        global sequential_thread
        if sequential_thread and sequential_thread.is_alive():
            bot.reply_to(message, "⚠️ Hiện đang có một tiến trình chạy tuần tự đang diễn ra. Vui lòng nhắn 'dừng' để hủy trước khi khởi chạy phiên mới.")
        else:
            sequential_thread = threading.Thread(
                target=run_sequential_shopee_search, 
                args=(message, keywords, target_devices, click_first)
            )
            sequential_thread.daemon = True
            sequential_thread.start()

    elif action == "stop_all":
        global cancel_sequential, cancel_flag
        cancel_sequential = True
        cancel_flag = True
        # Gửi kèm ReplyKeyboardRemove để ẩn nút dừng ngay lập tức
        markup_remove = telebot.types.ReplyKeyboardRemove(selective=False)
        status_msg = bot.send_message(message.chat.id, "🛑 **HỦY BỎ TÁC VỤ**\n\nĐang gửi lệnh dừng khẩn cấp cho tất cả các máy và các luồng chạy...", reply_markup=markup_remove)
        
        def reset_cancel_flags():
            time.sleep(3.5)
            global cancel_sequential, cancel_flag
            cancel_sequential = False
            cancel_flag = False
            try:
                bot.edit_message_text("⏹️ **HỦY BỎ THÀNH CÔNG**\n\nToàn bộ tiến trình tự động hóa đã dừng lại. Bot đã sẵn sàng nhận các câu lệnh mới.", message.chat.id, status_msg.message_id)
            except Exception:
                pass
                
        threading.Thread(target=reset_cancel_flags).start()

    elif action == "open_shopee":
        if len(target_devices) == 1:
            tgt_name = get_device_name(target_devices[0])
            adb.launch_app(target_devices[0], config.SHOPEE_PACKAGE)
            bot.reply_to(message, f"✅ Đang mở Shopee trên **Máy {tgt_name}**.")
        else:
            for dev in target_devices:
                adb.launch_app(dev, config.SHOPEE_PACKAGE)
            bot.reply_to(message, f"✅ Đang mở Shopee trên tất cả {len(target_devices)} máy.")

    elif action == "close_shopee":
        if len(target_devices) == 1:
            tgt_name = get_device_name(target_devices[0])
            adb.stop_app(target_devices[0], config.SHOPEE_PACKAGE)
            bot.reply_to(message, f"✅ Đã buộc dừng Shopee trên **Máy {tgt_name}**.")
        else:
            for dev in target_devices:
                adb.stop_app(dev, config.SHOPEE_PACKAGE)
            bot.reply_to(message, f"✅ Đã buộc dừng Shopee trên tất cả {len(target_devices)} máy.")

    elif action == "back":
        for dev in target_devices:
            adb.keyevent(dev, 4)
        if len(target_devices) == 1:
            tgt_name = get_device_name(target_devices[0])
            bot.reply_to(message, f"↩️ Đã gửi lệnh Quay lại trên **Máy {tgt_name}**.")
        else:
            bot.reply_to(message, f"↩️ Đã gửi lệnh Quay lại trên tất cả {len(target_devices)} máy.")

    elif action == "home":
        for dev in target_devices:
            adb.keyevent(dev, 3)
        if len(target_devices) == 1:
            tgt_idx = devices.index(target_devices[0]) + 1
            bot.reply_to(message, f"🏠 Đã gửi lệnh màn hình chính trên **Máy {tgt_idx}**.")
        else:
            bot.reply_to(message, f"🏠 Đã gửi lệnh màn hình chính trên tất cả {len(target_devices)} máy.")

    elif action == "click":
        x, y = cmd["x"], cmd["y"]
        if len(target_devices) == 1:
            tgt_idx = devices.index(target_devices[0]) + 1
            adb.tap(target_devices[0], x, y)
            bot.reply_to(message, f"👆 Đã click tọa độ ({x}, {y}) trên **Máy {tgt_idx}**.")
        else:
            for dev in target_devices:
                adb.tap(dev, x, y)
            bot.reply_to(message, f"👆 Đã click tọa độ ({x}, {y}) trên tất cả {len(target_devices)} máy.")

    elif action == "input":
        text_val = cmd["text"]
        if len(target_devices) == 1:
            tgt_idx = devices.index(target_devices[0]) + 1
            adb.input_text(target_devices[0], text_val)
            bot.reply_to(message, f"✍️ Đã nhập '{text_val}' trên **Máy {tgt_idx}**.")
        else:
            for dev in target_devices:
                adb.input_text(dev, text_val)
            bot.reply_to(message, f"✍️ Đã nhập '{text_val}' trên tất cả {len(target_devices)} máy.")

    elif action == "disable_rotation":
        if len(target_devices) == 1:
            tgt_idx = devices.index(target_devices[0]) + 1
            adb.execute_adb(target_devices[0], ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            adb.execute_adb(target_devices[0], ["shell", "settings", "put", "system", "user_rotation", "0"])
            bot.reply_to(message, f"📴 Đã tắt xoay màn hình và khóa hướng dọc trên **Máy {tgt_idx}**.")
        else:
            for dev in target_devices:
                adb.execute_adb(dev, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
                adb.execute_adb(dev, ["shell", "settings", "put", "system", "user_rotation", "0"])
            bot.reply_to(message, f"📴 Đã tắt xoay màn hình và khóa hướng dọc trên tất cả {len(target_devices)} máy.")

# Điểm khởi chạy của Bot
if __name__ == "__main__":
    print("--------------------------------------------------")
    print("Bot Telegram dieu khien Box Phone dang khoi dong...")
    if not config.TELEGRAM_BOT_TOKEN:
        print("ERROR: Chua co TELEGRAM_BOT_TOKEN trong file .env!")
        exit(1)
        
    print("Bot dang lang nghe tin nhan (Long Polling)...")
    print("Nguoi dung dau tien chat voi bot se duoc ghi nhan lam Admin.")
    print("Nhan Ctrl+C de dung bot.")
    print("--------------------------------------------------")
    
    # Khởi chạy bot
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"Bot bi loi mat ket noi, dang khoi dong lai sau 5s... Loi: {e}")
            time.sleep(5)

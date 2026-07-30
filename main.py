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
    global cancel_flag, cancel_sequential
    return cancel_flag or cancel_sequential

# Caching mapping thiết bị toàn cục để tra cứu nhanh
cached_mapping = {}

def safe_send_message(chat_id, text, parse_mode=None, reply_markup=None, reply_to_message_id=None):
    """Gửi tin nhắn Telegram an toàn, tự động retry nếu lỗi mạng để không làm sập luồng chính"""
    for attempt in range(3):
        try:
            return bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
                timeout=15
            )
        except Exception as e:
            print(f"[Telegram ERROR] Gửi tin nhắn thất bại (Lần {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2.0)
    return None

def safe_edit_message(text, chat_id, message_id, reply_markup=None, parse_mode=None):
    """Sửa tin nhắn Telegram an toàn, tự động retry nếu lỗi mạng"""
    for attempt in range(3):
        try:
            return bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                timeout=15
            )
        except Exception as e:
            print(f"[Telegram ERROR] Sửa tin nhắn thất bại (Lần {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2.0)
    return None

def safe_send_photo(chat_id, photo, caption=None, reply_to_message_id=None):
    """Gửi ảnh Telegram an toàn, tự động retry nếu lỗi mạng"""
    for attempt in range(3):
        try:
            return bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                timeout=20
            )
        except Exception as e:
            print(f"[Telegram ERROR] Gửi ảnh thất bại (Lần {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2.0)
    return None

# ================= THEME & TELEGRAM REAL-TIME TRACKER =================
class TelegramRealtimeTracker:
    def __init__(self, bot_obj, chat_id, reply_markup=None):
        self.bot = bot_obj
        self.chat_id = chat_id
        self.reply_markup = reply_markup
        self.live_msg_id = None
        self.last_edit_time = 0
        self.last_text = ""
        self.completed_steps = []
        self.current_step = ""
        self.device_name = ""
        self.device_serial = ""
        self.keyword = ""
        self.current_idx = 0
        self.total_devices = 0
        self.platform = "Shopee"

    def start_dashboard(self, initial_text):
        msg = safe_send_message(self.chat_id, initial_text, parse_mode="Markdown", reply_markup=self.reply_markup)
        if msg:
            self.live_msg_id = msg.message_id
            self.last_text = initial_text
            self.last_edit_time = time.time()

    def set_active_device(self, dev_name, dev_serial, keyword, current_idx, total_devices, platform="Shopee"):
        self.device_name = dev_name
        self.device_serial = dev_serial
        self.keyword = keyword
        self.current_idx = current_idx
        self.total_devices = total_devices
        self.platform = platform
        self.completed_steps = []
        self.current_step = f"Đang khởi động {platform}..."
        self._force_update()

    def status_callback(self, dev_id, msg):
        if not msg:
            return
        if self.current_step and self.current_step != msg and self.current_step not in self.completed_steps:
            self.completed_steps.append(self.current_step)
            if len(self.completed_steps) > 4:
                self.completed_steps = self.completed_steps[-4:]
        self.current_step = msg

        now = time.time()
        if now - self.last_edit_time < 1.2:
            return

        self._force_update()

    def _force_update(self):
        if not self.live_msg_id:
            return
        text = self.render_progress_text()
        if text != self.last_text:
            self.last_edit_time = time.time()
            self.last_text = text
            safe_edit_message(text, self.chat_id, self.live_msg_id, reply_markup=self.reply_markup, parse_mode="Markdown")

    def render_progress_text(self):
        text = f"🤖 **{self.platform} • Máy {self.device_name} ({self.current_idx}/{self.total_devices})**\n"
        text += f"📱 ID: `{self.device_serial[:10]}`\n"
        text += f"🔑 Từ khóa: `{self.keyword}`\n"
        text += "----------------------------------------\n"
        for step in self.completed_steps:
            text += f"🟢 {step}\n"
        if self.current_step:
            text += f"🔵 **{self.current_step}**...\n"
        text += "----------------------------------------\n"
        text += "_Cập nhật liên tục từ trình duyệt/thiết bị..._"
        return text

    def update_rest_countdown(self, next_dev_name, remaining_seconds):
        now = time.time()
        if now - self.last_edit_time < 3.0 and remaining_seconds > 0:
            return
        text = f"⏳ **THỜI GIAN TẠM NGHỊ GIỮA CÁC MÁY**\n\n"
        text += f"📱 Máy tiếp theo: **Máy {next_dev_name}**\n"
        text += f"⏱️ Đang nghỉ: **{remaining_seconds} giây** nữa...\n"
        text += "----------------------------------------\n"
        text += "_(Giãn khoảng thời gian tự nhiên giữa các phiên)_"
        if text != self.last_text and self.live_msg_id:
            self.last_edit_time = now
            self.last_text = text
            safe_edit_message(text, self.chat_id, self.live_msg_id, reply_markup=self.reply_markup, parse_mode="Markdown")

    def finish_dashboard(self, summary_text):
        if self.live_msg_id:
            try:
                self.bot.edit_message_reply_markup(self.chat_id, self.live_msg_id, reply_markup=None)
            except Exception:
                pass
            safe_edit_message(summary_text, self.chat_id, self.live_msg_id, parse_mode="Markdown")

def send_device_finished_card(chat_id, dev_name, dev_id, keyword, success, err, duration_sec):
    minutes = int(duration_sec // 60)
    seconds = int(duration_sec % 60)
    if minutes > 0:
        time_str = f"{minutes} phút {seconds} giây"
    else:
        time_str = f"{seconds} giây"
        
    if success:
        text = (
            f"🟢 **Kịch bản đã hoàn tất thành công!**\n"
            f"Profile: **{dev_name}** (ID: `{dev_id[:10]}`)\n"
            f"🔑 Từ khóa: `{keyword}`\n"
            f"⏳ Thời gian chạy: **{time_str}**"
        )
    else:
        text = (
            f"🔴 **KỊCH BẢN CHẠY THẤT BẠI**\n"
            f"Profile: **{dev_name}** (ID: `{dev_id[:10]}`)\n"
            f"🔑 Từ khóa: `{keyword}`\n"
            f"⚠️ Lỗi: `{err}`"
        )
    safe_send_message(chat_id, text, parse_mode="Markdown")


def get_xiaowei_leveldb_dirs():
    """Trả về các thư mục dữ liệu Xiaowei theo tài khoản Windows hiện tại."""
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if not local_app_data:
        return []
    return [
        os.path.join(
            local_app_data,
            "xiaowei",
            "EBWebView",
            "Default",
            "Local Storage",
            "leveldb",
        ),
        os.path.join(
            local_app_data,
            "xiaowei",
            "EBWebView",
            "Default",
            "IndexedDB",
            "https_tauri.localhost_0.indexeddb.leveldb",
        ),
        os.path.join(
            local_app_data,
            "com.xiaowei.android",
            "EBWebView",
            "Default",
            "IndexedDB",
            "https_tauri.localhost_0.indexeddb.leveldb",
        ),
    ]


def get_ordered_devices():
    global cached_mapping
    raw_devices = adb.get_devices()
    search_dirs = get_xiaowei_leveldb_dirs()
    
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
        search_dirs = get_xiaowei_leveldb_dirs()
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


def assign_shopee_keywords(keywords, devices):
    """Random từ khóa riêng cho từng máy, không lặp cho đến khi hết kho."""
    unique_keywords = []
    seen = set()
    for keyword in keywords:
        clean_keyword = str(keyword).strip()
        normalized = clean_keyword.casefold()
        if clean_keyword and normalized not in seen:
            seen.add(normalized)
            unique_keywords.append(clean_keyword)

    if not unique_keywords:
        return {}

    assignments = {}
    device_index = 0
    while device_index < len(devices):
        shuffled_batch = random.sample(
            unique_keywords,
            len(unique_keywords),
        )
        for keyword in shuffled_batch:
            if device_index >= len(devices):
                break
            assignments[devices[device_index]] = keyword
            device_index += 1
    return assignments


def run_sequential_shopee_search(message, keywords, devices, click_first_item=False, use_ai=True):
    global cancel_sequential, cancel_flag
    cancel_sequential = False
    cancel_flag = False
    
    if use_ai:
        def gemini_status(msg):
            safe_send_message(message.chat.id, f"🤖 [Gemini AI]: {msg}")
            
        expanded_keywords = config.generate_keywords_via_gemini(
            config.GEMINI_API_KEY, 
            keywords, 
            status_cb=gemini_status
        )
    else:
        expanded_keywords = keywords

    if not expanded_keywords:
        safe_send_message(
            message.chat.id,
            "❌ Không có từ khóa Shopee hợp lệ để chạy.",
        )
        return

    keyword_assignments = assign_shopee_keywords(
        expanded_keywords,
        devices,
    )
        
    # Tạo nút dừng dạng Inline Keyboard đính kèm trực tiếp dưới tin nhắn
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
    
    tracker = TelegramRealtimeTracker(bot, message.chat.id, reply_markup=markup)
    
    initial_text = (
        f"⏳ **BẮT ĐẦU CHẠY TUẦN TỰ**\n\n"
        f"Từ khóa chính: `{', '.join(keywords)}`\n"
        f"Từ khóa mở rộng (Gemini): Có {len(expanded_keywords)} từ khóa\n"
        f"Phân phối: Random riêng từng máy, không lặp khi kho còn đủ\n"
        f"Tổng số máy: {len(devices)} máy\n"
        f"Nghỉ giữa mỗi phiên: **60 - 90 giây**\n\n"
        f"_(Cập nhật tiến trình thời gian thực từng thiết bị ở bên dưới)_"
    )
    tracker.start_dashboard(initial_text)
    
    total_start_time = time.time()
    success_count = 0
    
    for idx, dev in enumerate(devices):
        if cancel_sequential or cancel_flag:
            safe_send_message(message.chat.id, "⏹️ **ĐÃ DỪNG CHẠY TUẦN TỰ** theo yêu cầu của bạn.")
            break
            
        dev_name = get_device_name(dev)
        current_keyword = keyword_assignments[dev]
        # Bắt đầu theo dõi thời gian thực cho máy hiện tại
        dev_start_time = time.time()
        tracker.set_active_device(dev_name, dev, current_keyword, idx + 1, len(devices))
        
        success, err = adb.shopee_find_and_click_lamdong(
            dev, 
            current_keyword, 
            status_callback=tracker.status_callback, 
            is_cancelled=is_cancelled, 
            click_first_item=click_first_item
        )
        
        dev_duration = time.time() - dev_start_time
        
        if cancel_sequential or cancel_flag:
            safe_send_message(message.chat.id, "⏹️ **ĐÃ DỪNG CHẠY TUẦN TỰ** theo yêu cầu của bạn.")
            break
            
        if success:
            success_count += 1
            send_device_finished_card(message.chat.id, dev_name, dev, current_keyword, True, "", dev_duration)
        else:
            send_device_finished_card(message.chat.id, dev_name, dev, current_keyword, False, err, dev_duration)
            if "Captcha" in err or "bị chặn" in err.lower():
                temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                screenshot_path = os.path.join(temp_dir, f"captcha_alert_{dev_name}.png")
                sc_success, _ = adb.take_screenshot(dev, screenshot_path)
                if sc_success:
                    try:
                        with open(screenshot_path, 'rb') as photo:
                            safe_send_photo(
                                message.chat.id, 
                                photo, 
                                caption=f"🚨 **CẢNH BÁO CAPTCHA - MÁY {dev_name}**\n\nVui lòng giải tay máy này trên phần mềm xiaowei!"
                            )
                    except Exception as pe:
                        print(f"Error sending photo: {pe}")
                    try:
                        os.remove(screenshot_path)
                    except Exception:
                        pass
            
        if idx < len(devices) - 1:
            next_dev_name = get_device_name(devices[idx + 1])
            delay = random.randint(60, 90)
            
            for rem in range(delay, 0, -1):
                if cancel_sequential or cancel_flag:
                    break
                tracker.update_rest_countdown(next_dev_name, rem)
                time.sleep(1)
                
    if not cancel_sequential and not cancel_flag:
        total_duration = time.time() - total_start_time
        total_min = int(total_duration // 60)
        total_sec = int(total_duration % 60)
        total_time_str = f"{total_min} phút {total_sec} giây" if total_min > 0 else f"{total_sec} giây"
        
        final_summary = (
            f"🏁 **HOÀN THÀNH QUY TRÌNH CHẠY TUẦN TỰ**\n"
            f"----------------------------------------\n"
            f"📊 Tổng xử lý: **{len(devices)}/{len(devices)} máy**\n"
            f"🟢 Thành công: **{success_count} máy**\n"
            f"⏱️ Tổng thời gian: **{total_time_str}**"
        )
        tracker.finish_dashboard(final_summary)


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

# Cập nhật cấu hình Shop dự phòng vào file .env
def save_env_shop_names(shop_names_list):
    """Cập nhật danh sách shop vào config và lưu xuống file .env"""
    shop_str = ", ".join(shop_names_list)
    config.SHOPEE_SHOP_NAMES = shop_names_list
    config.SHOPEE_SHOP_NAMES_RAW = shop_str
    
    env_path = config.BASE_DIR / ".env"
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.startswith("SHOPEE_SHOP_NAMES="):
                    new_lines.append(f'SHOPEE_SHOP_NAMES="{shop_str}"')
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f'SHOPEE_SHOP_NAMES="{shop_str}"')
            env_path.write_text("\n".join(new_lines), encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] Không thể lưu file .env: {e}")
    else:
        try:
            env_path.write_text(f'SHOPEE_SHOP_NAMES="{shop_str}"\n', encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] Không thể tạo file .env: {e}")

# Lưu trữ tạm thời các phiên sinh từ khóa AI để chạy bằng Inline Button
ai_keyword_jobs = {}

def create_job_id():
    return str(int(time.time() * 1000))[-6:]

# Hàm phân tích lệnh từ ngôn ngữ tự nhiên tiếng Việt
def parse_natural_command(text):
    text_lower = text.lower().strip()
    
    # 0. Lệnh Sinh từ khóa Tầng 1 / Tầng 2
    if text_lower.startswith("/t1 ") or text_lower.startswith("sinh tầng 1 ") or text_lower.startswith("tầng 1 "):
        kw_text = re.sub(r"^(?:/t1|sinh tầng 1|tầng 1)\s+", "", text, flags=re.IGNORECASE).strip()
        return {"action": "generate_t1", "raw_text": kw_text}

    if text_lower.startswith("/t2 ") or text_lower.startswith("sinh tầng 2 ") or text_lower.startswith("tầng 2 "):
        kw_text = re.sub(r"^(?:/t2|sinh tầng 2|tầng 2)\s+", "", text, flags=re.IGNORECASE).strip()
        return {"action": "generate_t2", "raw_text": kw_text}

    # Lệnh Cấu hình Shop dự phòng
    if text_lower.startswith("/setshop ") or text_lower.startswith("cấu hình shop ") or text_lower.startswith("đặt shop ") or text_lower.startswith("set shop "):
        shops_raw = re.sub(r"^(?:/setshop|cấu hình shop|đặt shop|set shop)\s+", "", text, flags=re.IGNORECASE).strip()
        return {"action": "set_shop", "shops_raw": shops_raw}

    if text_lower in ["/shop", "danh sách shop", "xem shop", "shop"]:
        return {"action": "get_shop"}

    # Lệnh Bơm TikTok 3 Bước
    if any(k in text_lower for k in ["/tiktok", "bơm tiktok", "chạy tiktok", "tiktok"]):
        is_seq = any(k in text_lower for k in ["tuần tự", "tuan tu", "lần lượt"])
        m_device = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m_device.group(1)) if m_device else None
        
        raw = re.sub(r"^(?:/tiktok_seq|/tiktok|bơm tiktok tuần tự|bơm tiktok|chạy tiktok tuần tự|chạy tiktok)\s*", "", text, flags=re.IGNORECASE).strip()
        raw = re.sub(r"(?:cho|ở|trên)?\s*(?:máy|máy số|số|device)\s*\d+", "", raw, flags=re.IGNORECASE).strip()
        
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        seed_kws = parts[0] if parts else config.TIKTOK_SEED_KEYWORDS_DEFAULT
        target_ch = parts[1] if len(parts) > 1 else config.TIKTOK_TARGET_CHANNEL_DEFAULT
        
        return {
            "action": "tiktok_automation",
            "is_sequential": is_seq,
            "seed_keywords": seed_kws,
            "target_channel": target_ch,
            "device_idx": device_idx
        }

    # 1. Trạng thái / Danh sách máy
    if any(k in text_lower for k in ["danh sách máy", "liệt kê", "trạng thái", "devices", "status", "list"]):
        return {"action": "list_devices"}
        
    # 2. Chụp màn hình điện thoại
    m_screenshot = re.search(r"(?:chụp màn hình|chụp ảnh|chụp)\s*(?:máy|máy số|số|device)?\s*(\d+)", text_lower)
    if m_screenshot:
        return {"action": "screenshot", "device_idx": int(m_screenshot.group(1))}
        
    # 3. Phím Quay lại (Back)
    if any(k in text_lower for k in ["quay lại", "nút quay lại", "back", "trở về"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m.group(1)) if m else None
        return {"action": "back", "device_idx": device_idx}
        
    # 4. Phím Trang chủ (Home)
    if any(k in text_lower for k in ["trang chủ", "nút home", "home", "màn hình chính"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m.group(1)) if m else None
        return {"action": "home", "device_idx": device_idx}
        
    # 5. Mở ứng dụng Shopee
    if "mở shopee" in text_lower or "mở ứng dụng shopee" in text_lower or "chạy shopee" in text_lower:
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m.group(1)) if m else None
        return {"action": "open_shopee", "device_idx": device_idx}
        
    # 6. Đóng ứng dụng Shopee
    if "đóng shopee" in text_lower or "tắt shopee" in text_lower or "đóng ứng dụng shopee" in text_lower:
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m.group(1)) if m else None
        return {"action": "close_shopee", "device_idx": device_idx}

    # 7. Tìm kiếm sản phẩm trên Shopee
    shopee_keywords = ["shopee", "tìm", "tìm kiếm"]
    if any(k in text_lower for k in shopee_keywords):
        m_device = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m_device.group(1)) if m_device else None
        
        keyword = ""
        m_search = re.search(r"(?:tìm kiếm|tìm)\s+(.+?)\s+(?:trên|ở)\s+shopee", text_lower)
        if m_search:
            keyword = m_search.group(1)
        else:
            m_search = re.search(r"shopee\s+(?:tìm kiếm|tìm)\s+(.+)", text_lower)
            if m_search:
                keyword = m_search.group(1)
            else:
                m_search = re.search(r"(?:tìm kiếm|tìm)\s+shopee\s+(.+)", text_lower)
                if m_search:
                    keyword = m_search.group(1)
                else:
                    m_search = re.search(r"(?:tìm kiếm|tìm)\s+(.+)", text_lower)
                    if m_search:
                        keyword = m_search.group(1)
        
        if keyword:
            keyword = re.sub(r"(?:cho|ở|trên)?\s*(?:máy|máy số|số|device)\s*\d+", "", keyword)
            keyword = keyword.strip()
            
            if "lâm đồng" in text_lower or "lam dong" in text_lower:
                click_first_item = False
                first_item_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
                if any(ind in text_lower for ind in first_item_indicators):
                    click_first_item = True
                
                keyword_clean = re.sub(r"(?:tỉnh\s+)?(?:lâm\s+đồng|lam\s+dong)", "", keyword, flags=re.IGNORECASE)
                keyword_clean = re.sub(r"(?:tuần\s+tự|tuan\s+tu|lần\s+lượt|lan\s+luot)", "", keyword_clean, flags=re.IGNORECASE)
                
                for ind in first_item_indicators:
                    keyword_clean = re.sub(r"\b" + re.escape(ind) + r"\b", "", keyword_clean, flags=re.IGNORECASE)
                
                keyword_clean = re.sub(r"\s+", " ", keyword_clean).strip()
                
                keywords = [k.strip() for k in re.split(r'[,;|]', keyword_clean) if k.strip()]
                if not keywords:
                    keywords = [keyword_clean]
                
                if any(k in text_lower for k in ["tuần tự", "tuan tu", "lần lượt", "lan luot"]):
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
            
    # 8. Lệnh Click tọa độ thủ công
    m_click = re.search(r"click\s+(\d+)\s+(\d+)(?:\s+(?:máy|máy số|số|device)?\s*(\d+))?", text_lower)
    if m_click:
        x, y = int(m_click.group(1)), int(m_click.group(2))
        device_idx = int(m_click.group(3)) if m_click.group(3) else None
        return {"action": "click", "x": x, "y": y, "device_idx": device_idx}

    # 9. Lệnh Nhập text thủ công
    m_input = re.search(r"nhập\s+(.+?)(?:\s+(?:máy|máy số|số|device)\s*(\d+))?$", text_lower)
    if m_input:
        input_text_val = m_input.group(1).strip()
        device_idx = int(m_input.group(2)) if m_input.group(2) else None
        return {"action": "input", "text": input_text_val, "device_idx": device_idx}

    # Lệnh Dừng tất cả các tác vụ đang chạy
    if any(k in text_lower for k in ["dừng chạy", "dừng tất cả", "dừng", "hủy chạy", "dung chay", "huy chay", "stop"]):
        return {"action": "stop_all"}

    # 10. Tắt xoay màn hình
    if any(k in text_lower for k in ["tắt xoay màn hình", "tắt xoay", "tắt tự động xoay", "khóa màn hình dọc"]):
        m = re.search(r"(?:máy|máy số|số|device)\s*(\d+)", text_lower)
        device_idx = int(m.group(1)) if m else None
        return {"action": "disable_rotation", "device_idx": device_idx}

    return None

# Xử lý lệnh /start, /help và /menu
@bot.message_handler(commands=['start', 'help', 'menu', 't1', 't2', 'setshop', 'shop'])
def handle_slash_commands(message):
    if not check_auth(message):
        return

    cmd = message.text.strip()
    cmd_lower = cmd.lower()

    if cmd_lower.startswith("/t1"):
        kw_text = cmd[3:].strip()
        if not kw_text:
            bot.reply_to(message, "⚠️ Vui lòng nhập từ khóa chính sau lệnh `/t1`, ví dụ:\n`/t1 Lotion Bôi Ghẻ Ngứa`", parse_mode="Markdown")
            return
        handle_t1_generation(message, kw_text)

    elif cmd_lower.startswith("/t2"):
        kw_text = cmd[3:].strip()
        if not kw_text:
            bot.reply_to(message, "⚠️ Vui lòng nhập tiêu đề thô sau lệnh `/t2`, ví dụ:\n`/t2 Lotion Bôi Ghẻ Ngứa Premiscab Permethrin, Giải Độc Gan Silymarin`", parse_mode="Markdown")
            return
        handle_t2_generation(message, kw_text)

    elif cmd_lower.startswith("/setshop"):
        shops_raw = cmd[8:].strip()
        if not shops_raw:
            bot.reply_to(message, "⚠️ Vui lòng nhập danh sách shop sau lệnh `/setshop`, ví dụ:\n`/setshop shop_a, shop_b`", parse_mode="Markdown")
            return
        handle_set_shop(message, shops_raw)

    elif cmd_lower.startswith("/shop"):
        handle_get_shop(message)

    elif cmd_lower in ["/start", "/help", "/menu"]:
        send_full_dashboard(message)

def send_full_dashboard(message):
    shops_str = ", ".join(config.SHOPEE_SHOP_NAMES) if config.SHOPEE_SHOP_NAMES else "Chưa cấu hình"
    instructions = (
        "🤖 **BOXPHONE AUTOMATION - BẢNG ĐIỀU KHIỂN & HƯỚNG DẪN BOT** 🤖\n\n"
        f"🏬 **Shop dự phòng hiện tại:** `{shops_str}`\n"
        "----------------------------------------\n\n"
        "📖 **HƯỚNG DẪN SỬ DỤNG CHI TIẾT TẤT CẢ LỆNH:**\n\n"

        "🪄 **1. SINH TỪ KHÓA BẰNG GEMINI AI:**\n"
        "• **Tầng 1 (SEO Expansion - Sinh từ khóa phụ):**\n"
        "  Cú pháp: `/t1 <tên sản phẩm>` hoặc `sinh tầng 1 <tên sản phẩm>`\n"
        "  _Ví dụ:_ `/t1 Lotion Bôi Ghẻ Ngứa Premiscab`\n\n"
        "• **Tầng 2 (Bóc tách Tiêu đề thô CoT):**\n"
        "  Cú pháp: `/t2 <tiêu đề 1>, <tiêu đề 2>` hoặc `sinh tầng 2 <tiêu đề>`\n"
        "  _Ví dụ:_ `/t2 Lotion Bôi Ghẻ Ngứa Premiscab Permethrin, Giải Độc Gan Silymarin`\n"
        "  *(Sau khi AI sinh từ khóa, bấm nút `▶️ Chạy Tuần Tự` hoặc `⚡ Chạy Song Song` ngay dưới tin nhắn để khởi chạy)*\n\n"

        "🛒 **2. LỆNH TÌM KIẾM & TƯƠNG TÁC SHOPEE:**\n"
        "• **Chạy Tuần Tự (Cập nhật Real-time 100%):**\n"
        "  `tìm tuần tự lâm đồng deriva, son môi`\n"
        "• **Chạy Lướt Top 1 / Shopee Video:**\n"
        "  `tìm tuần tự lâm đồng deriva video`\n"
        "• **Chạy Song Song Tất Cả Các Máy:**\n"
        "  `tìm lâm đồng deriva`\n"
        "• **Chạy Trên Một Máy Chỉ Định:**\n"
        "  `máy 1 tìm lâm đồng deriva`\n\n"

        "🎵 **3. LỆNH BƠM TIKTOK 3 BƯỚC:**\n"
        "• **Chạy TikTok Song Song (Tất cả máy):**\n"
        "  `/tiktok từ khóa 1, từ khóa 2 | kenh_a, kenh_b`\n"
        "  _(Mỗi máy chọn ngẫu nhiên đúng 1 kênh trong danh sách)_\n"
        "• **Chạy TikTok Tuần Tự:**\n"
        "  `/tiktok tuần tự từ khóa 1, từ khóa 2 | kenh_a, kenh_b`\n"
        "• **Chạy TikTok Trên Máy Chỉ Định:**\n"
        "  `máy 1 bơm tiktok từ khóa 1 | kenh_a, kenh_b`\n\n"

        "⚙️ **4. CẤU HÌNH SHOP DỰ PHÒNG:**\n"
        "• **Cài đặt danh sách shop mới:**\n"
        "  `/setshop shop_a, shop_b` hoặc `đặt shop shop_a, shop_b`\n"
        "• **Xem danh sách shop đang lưu:**\n"
        "  `/shop` hoặc `danh sách shop`\n\n"

        "📊 **4. THIẾT BỊ & GIÁM SÁT MÀN HÌNH:**\n"
        "• **Xem danh sách máy kết nối:** `danh sách máy` hoặc `trạng thái`\n"
        "• **Chụp ảnh màn hình:** `chụp màn hình máy 1`\n"
        "• **Điều khiển ứng dụng:** `mở shopee`, `đóng shopee`, `quay lại`, `trang chủ`\n\n"

        "🛑 **5. DỪNG TÁC VỤ KHẨN CẤP:**\n"
        "• Nhắn `dừng` / `stop` hoặc bấm nút **`🛑 DỪNG KHẨN CẤP`** bên dưới.\n"
    )
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("🪄 Sinh Tầng 1 (SEO)", callback_data="btn_t1_prompt"),
        telebot.types.InlineKeyboardButton("🧠 Sinh Tầng 2 (Tiêu đề)", callback_data="btn_t2_prompt"),
        telebot.types.InlineKeyboardButton("🏬 Danh sách Shop", callback_data="btn_shop"),
        telebot.types.InlineKeyboardButton("📊 Danh sách Máy", callback_data="btn_list"),
        telebot.types.InlineKeyboardButton("📸 Chụp màn hình S1", callback_data="btn_screenshot_1"),
        telebot.types.InlineKeyboardButton("🛑 DỪNG KHẨN CẤP", callback_data="stop_all")
    )
    bot.reply_to(message, instructions, parse_mode="Markdown", reply_markup=markup)

def handle_t1_generation(message, kw_text):
    status_msg = bot.reply_to(message, f"🪄 [Gemini AI] Đang bóc tách & sinh từ khóa **Tầng 1 (SEO)** cho: `{kw_text}`...", parse_mode="Markdown")
    
    titles = [k.strip() for k in re.split(r'[,;\n|]', kw_text) if k.strip()]
    generated_kws = config.generate_keywords_via_gemini(config.GEMINI_API_KEY, titles)
    
    if not generated_kws:
        safe_edit_message("❌ Gemini AI không sinh được từ khóa Tầng 1. Vui lòng kiểm tra lại GEMINI_API_KEY.", message.chat.id, status_msg.message_id)
        return

    job_id = create_job_id()
    ai_keyword_jobs[job_id] = {
        "tier": 1,
        "keywords": generated_kws,
        "raw_text": kw_text
    }

    kw_list_str = "\n".join([f"{idx+1}. `{kw}`" for idx, kw in enumerate(generated_kws[:15])])
    if len(generated_kws) > 15:
        kw_list_str += f"\n_... và {len(generated_kws) - 15} từ khóa khác._"

    res_text = (
        f"✅ **ĐÃ SINH {len(generated_kws)} TỪ KHÓA TẦNG 1 (SEO EXPANSION)**\n\n"
        f"{kw_list_str}\n\n"
        f"👇 **Bấm nút dưới đây để khởi chạy ngay trên Box Phone:**"
    )
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("▶️ Chạy Tuần Tự (Tầng 1)", callback_data=f"t1_seq:{job_id}"),
        telebot.types.InlineKeyboardButton("⚡ Chạy Song Song (Tầng 1)", callback_data=f"t1_par:{job_id}")
    )
    safe_edit_message(res_text, message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode="Markdown")

def handle_t2_generation(message, kw_text):
    status_msg = bot.reply_to(message, f"🧠 [Gemini AI] Đang phân tích CoT & sinh từ khóa **Tầng 2 (Bóc tách Tiêu đề)** cho:\n`{kw_text}`...", parse_mode="Markdown")
    
    titles = [k.strip() for k in re.split(r'[\n;]', kw_text) if k.strip()]
    if len(titles) == 1 and "," in kw_text:
        titles = [k.strip() for k in kw_text.split(",") if k.strip()]

    generated_kws = config.generate_keywords_tier2_via_gemini(config.GEMINI_API_KEY, titles)
    
    if not generated_kws:
        safe_edit_message("❌ Gemini AI không sinh được từ khóa Tầng 2. Vui lòng kiểm tra lại GEMINI_API_KEY.", message.chat.id, status_msg.message_id)
        return

    job_id = create_job_id()
    ai_keyword_jobs[job_id] = {
        "tier": 2,
        "keywords": generated_kws,
        "raw_text": kw_text
    }

    kw_list_str = "\n".join([f"{idx+1}. `{kw}`" for idx, kw in enumerate(generated_kws[:15])])
    if len(generated_kws) > 15:
        kw_list_str += f"\n_... và {len(generated_kws) - 15} từ khóa khác._"

    res_text = (
        f"✅ **ĐÃ SINH {len(generated_kws)} TỪ KHÓA TẦNG 2 (BÓC TÁCH TIÊU ĐỀ)**\n\n"
        f"{kw_list_str}\n\n"
        f"👇 **Bấm nút dưới đây để khởi chạy ngay trên Box Phone:**"
    )
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("▶️ Chạy Tuần Tự (Tầng 2)", callback_data=f"t2_seq:{job_id}"),
        telebot.types.InlineKeyboardButton("⚡ Chạy Song Song (Tầng 2)", callback_data=f"t2_par:{job_id}")
    )
    safe_edit_message(res_text, message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode="Markdown")

def handle_set_shop(message, shops_raw):
    shop_list = [s.strip() for s in re.split(r'[,;\n|]', shops_raw) if s.strip()]
    if not shop_list:
        bot.reply_to(message, "❌ Danh sách shop không hợp lệ.")
        return
    save_env_shop_names(shop_list)
    shops_str = ", ".join(shop_list)
    bot.reply_to(message, f"✅ **ĐÃ CẬP NHẬT DANH SÁCH SHOP DỰ PHÒNG!**\n\n🏬 Danh sách shop mới: `{shops_str}`\n\n_Đã lưu trực tiếp vào cấu hình hệ thống & file .env._", parse_mode="Markdown")

def handle_get_shop(message):
    if not config.SHOPEE_SHOP_NAMES:
        bot.reply_to(message, "⚠️ Chưa có shop dự phòng nào được cấu hình. Sử dụng `/setshop shop1, shop2` để thêm shop.", parse_mode="Markdown")
        return
    shops_str = "\n".join([f"• `{s}`" for s in config.SHOPEE_SHOP_NAMES])
    bot.reply_to(message, f"🏬 **DANH SÁCH SHOP DỰ PHÒNG HIỆN TẠI ({len(config.SHOPEE_SHOP_NAMES)} Shop):**\n\n{shops_str}", parse_mode="Markdown")

# Xử lý tất cả Inline Keyboard Callbacks
@bot.callback_query_handler(func=lambda call: True)
def handle_inline_callbacks(call):
    data = call.data
    chat_id = call.message.chat.id
    
    if data == "btn_t1_prompt":
        bot.answer_callback_query(call.id)
        safe_send_message(chat_id, "💡 **HƯỚNG DẪN SINH TỪ KHÓA TẦNG 1:**\n\nGõ theo cú pháp: `/t1 <tên sản phẩm>` hoặc `sinh tầng 1 <tên sản phẩm>`\n\n_Ví dụ:_ `/t1 Lotion Bôi Ghẻ Ngứa Premiscab`", parse_mode="Markdown")

    elif data == "btn_t2_prompt":
        bot.answer_callback_query(call.id)
        safe_send_message(chat_id, "💡 **HƯỚNG DẪN SINH TỪ KHÓA TẦNG 2:**\n\nGõ theo cú pháp: `/t2 <tiêu đề 1>, <tiêu đề 2>` hoặc `sinh tầng 2 <tiêu đề>`\n\n_Ví dụ:_ `/t2 Lotion Bôi Ghẻ Ngứa Premiscab Permethrin, Giải Độc Gan Silymarin`", parse_mode="Markdown")

    elif data == "btn_shop":
        bot.answer_callback_query(call.id)
        handle_get_shop(call.message)

    elif data == "btn_list":
        bot.answer_callback_query(call.id)
        devices = get_ordered_devices()
        res = f"📊 **DANH SÁCH THIẾT BỊ ĐANG KẾT NỐI ({len(devices)} máy):**\n\n"
        for d in devices:
            res += f"📱 **Máy {get_device_name(d)}**: ID: `{d}`\n"
        safe_send_message(chat_id, res, parse_mode="Markdown")

    elif data == "btn_screenshot_1":
        bot.answer_callback_query(call.id)
        devices = get_ordered_devices()
        if not devices:
            safe_send_message(chat_id, "❌ Không có máy nào đang kết nối.")
            return
        tgt_dev = devices[0]
        tgt_name = get_device_name(tgt_dev)
        temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        local_path = os.path.join(temp_dir, f"screenshot_{tgt_name}.png")
        success, result = adb.take_screenshot(tgt_dev, local_path)
        if success:
            with open(local_path, 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=f"🖼️ Ảnh chụp màn hình **Máy {tgt_name}**")
            try:
                os.remove(local_path)
            except Exception:
                pass

    elif data.startswith("t1_seq:") or data.startswith("t2_seq:"):
        bot.answer_callback_query(call.id)
        job_id = data.split(":")[1]
        if job_id not in ai_keyword_jobs:
            safe_send_message(chat_id, "⚠️ Phiên sinh từ khóa này đã hết hạn. Vui lòng gõ `/t1` hoặc `/t2` để sinh từ khóa mới.")
            return
        job = ai_keyword_jobs[job_id]
        kws = job["keywords"]
        tier_label = f"Tầng {job['tier']}"
        devices = get_ordered_devices()
        
        global sequential_thread
        if sequential_thread and sequential_thread.is_alive():
            safe_send_message(chat_id, "⚠️ Hiện đang có một tiến trình chạy tuần tự đang diễn ra. Vui lòng gõ 'dừng' trước.")
        else:
            safe_send_message(chat_id, f"🚀 **KHỞI CHẠY TUẦN TỰ {tier_label.upper()}**\n\nĐang quét trên {len(devices)} máy với {len(kws)} từ khóa AI...", parse_mode="Markdown")
            sequential_thread = threading.Thread(
                target=run_sequential_shopee_search, 
                args=(call.message, kws, devices, False)
            )
            sequential_thread.daemon = True
            sequential_thread.start()

    elif data.startswith("t1_par:") or data.startswith("t2_par:"):
        bot.answer_callback_query(call.id)
        job_id = data.split(":")[1]
        if job_id not in ai_keyword_jobs:
            safe_send_message(chat_id, "⚠️ Phiên sinh từ khóa này đã hết hạn. Vui lòng gõ `/t1` hoặc `/t2` để sinh từ khóa mới.")
            return
        job = ai_keyword_jobs[job_id]
        kws = job["keywords"]
        tier_label = f"Tầng {job['tier']}"
        devices = get_ordered_devices()
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
        status_msg = safe_send_message(chat_id, f"🚀 **KHỞI CHẠY SONG SONG {tier_label.upper()}**\n\nĐang chạy song song trên {len(devices)} máy với {len(kws)} từ khóa AI...", parse_mode="Markdown", reply_markup=markup)
        
        def run_search_parallel(device_id):
            dev_name = get_device_name(device_id)
            current_keyword = random.choice(kws)
            dev_start = time.time()
            success, err = adb.shopee_find_and_click_lamdong(device_id, current_keyword, is_cancelled=is_cancelled, click_first_item=False)
            dev_dur = time.time() - dev_start
            send_device_finished_card(chat_id, dev_name, device_id, current_keyword, success, err, dev_dur)
            return dev_name, current_keyword, success, err

        def run_par_bg():
            results = []
            with ThreadPoolExecutor(max_workers=len(devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in devices]
                for future in futures:
                    results.append(future.result())
            success_count = sum(1 for r in results if r[2])
            summary = f"🏁 **HOÀN THÀNH CHẠY SONG SONG {tier_label.upper()} ({success_count}/{len(devices)} MÁY THÀNH CÔNG)**"
            safe_edit_message(summary, chat_id, status_msg.message_id, reply_markup=None, parse_mode="Markdown")

        threading.Thread(target=run_par_bg, daemon=True).start()

    elif data == "stop_all":
        bot.answer_callback_query(call.id)
        global cancel_sequential, cancel_flag
        cancel_sequential = True
        cancel_flag = True
        status_msg = safe_send_message(chat_id, "🛑 **HỦY BỎ TÁC VỤ**\n\nĐang gửi lệnh dừng khẩn cấp cho tất cả các máy...")
        
        def reset_cancel_flags():
            time.sleep(3.5)
            global cancel_sequential, cancel_flag
            cancel_sequential = False
            cancel_flag = False
            try:
                safe_edit_message("⏹️ **HỦY BỎ THÀNH CÔNG**\n\nToàn bộ tiến trình tự động hóa đã dừng lại. Bot đã sẵn sàng nhận các câu lệnh mới.", chat_id, status_msg.message_id)
            except Exception:
                pass
                
        threading.Thread(target=reset_cancel_flags, daemon=True).start()

# Xử lý tất cả tin nhắn văn bản (Ngôn ngữ tự nhiên)
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    if not check_auth(message):
        return

    text = message.text
    cmd = parse_natural_command(text)
    
    if not cmd:
        bot.reply_to(message, "❓ Bot chưa hiểu câu lệnh này. Bạn gõ `/menu` hoặc `/help` để xem danh sách các câu lệnh nhé.")
        return

    action = cmd["action"]

    if action == "generate_t1":
        handle_t1_generation(message, cmd["raw_text"])
        return

    if action == "generate_t2":
        handle_t2_generation(message, cmd["raw_text"])
        return

    if action == "set_shop":
        handle_set_shop(message, cmd["shops_raw"])
        return

    if action == "get_shop":
        handle_get_shop(message)
        return

    devices = get_ordered_devices()
    if not devices:
        bot.reply_to(message, "❌ Không tìm thấy thiết bị điện thoại nào đang kết nối. Vui lòng kiểm tra lại dây cáp.")
        return

    device_idx = cmd.get("device_idx")

    target_devices = []
    if device_idx is not None:
        idx = device_idx - 1
        if 0 <= idx < len(devices):
            target_devices = [devices[idx]]
        else:
            bot.reply_to(message, f"❌ Không tìm thấy máy số {device_idx}. Hiện tại chỉ có {len(devices)} máy (từ 1 đến {len(devices)}).")
            return
    else:
        target_devices = devices

    if action == "tiktok_automation":
        is_seq = cmd.get("is_sequential", False)
        seed_kws = cmd.get("seed_keywords")
        target_ch = cmd.get("target_channel")
        
        if is_seq or len(target_devices) == 1:
            def run_seq_tt_thread():
                global cancel_sequential, cancel_flag
                cancel_sequential = False
                cancel_flag = False
                
                tracker = TelegramRealtimeTracker(bot, message.chat.id)
                tracker.start_dashboard(f"🎵 **BƠM TIKTOK TUẦN TỰ**\nKênh mục tiêu: `{target_ch}`\nĐang quét trên {len(target_devices)} máy...")

                success_count = 0
                for idx, dev in enumerate(target_devices):
                    if is_cancelled():
                        break
                    dev_name = get_device_name(dev)
                    tracker.set_active_device(
                        dev_name,
                        dev,
                        f"TikTok: {target_ch}",
                        idx + 1,
                        len(target_devices),
                        platform="TikTok",
                    )
                    dev_start = time.time()
                    success, err = adb.tiktok_automation_workflow(
                        dev,
                        seed_keywords=seed_kws,
                        target_channel=target_ch,
                        status_callback=tracker.status_callback,
                        is_cancelled=is_cancelled
                    )
                    dev_dur = time.time() - dev_start
                    send_device_finished_card(message.chat.id, dev_name, dev, f"TikTok: {target_ch}", success, err, dev_dur)
                    if success:
                        success_count += 1

                tracker.finish_dashboard(
                    f"🏁 **KẾT QUẢ TIKTOK TUẦN TỰ: "
                    f"{success_count}/{len(target_devices)} MÁY THÀNH CÔNG**"
                )

            threading.Thread(target=run_seq_tt_thread, daemon=True).start()
        else:
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
            status_msg = bot.reply_to(message, f"🎵 **BƠM TIKTOK SONG SONG** trên {len(target_devices)} máy...\nKênh mục tiêu: `{target_ch}`", reply_markup=markup)
            
            def run_tt_parallel(device_id):
                dev_name = get_device_name(device_id)
                tracker = TelegramRealtimeTracker(bot, message.chat.id)
                tracker.start_dashboard(
                    f"🎵 **TIKTOK SONG SONG • MÁY {dev_name}**\n"
                    f"Kênh mục tiêu: `{target_ch}`"
                )
                tracker.set_active_device(
                    dev_name,
                    device_id,
                    f"TikTok: {target_ch}",
                    1,
                    1,
                    platform="TikTok",
                )
                dev_start = time.time()
                success, err = adb.tiktok_automation_workflow(
                    device_id,
                    seed_keywords=seed_kws,
                    target_channel=target_ch,
                    status_callback=tracker.status_callback,
                    is_cancelled=is_cancelled
                )
                dev_dur = time.time() - dev_start
                if success:
                    tracker.finish_dashboard(
                        f"✅ **MÁY {dev_name} HOÀN THÀNH TIKTOK**\n"
                        f"Kênh: `{target_ch}`"
                    )
                else:
                    tracker.finish_dashboard(
                        f"❌ **MÁY {dev_name} TIKTOK THẤT BẠI**\n"
                        f"Lỗi: `{err}`"
                    )
                send_device_finished_card(message.chat.id, dev_name, device_id, f"TikTok: {target_ch}", success, err, dev_dur)
                return dev_name, success, err
                
            def run_par_tt_bg():
                results = []
                with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                    futures = [executor.submit(run_tt_parallel, dev) for dev in target_devices]
                    for future in futures:
                        results.append(future.result())
                success_count = sum(1 for r in results if r[1])
                summary = f"🏁 **HOÀN THÀNH BƠM TIKTOK SONG SONG ({success_count}/{len(target_devices)} MÁY THÀNH CÔNG)**"
                safe_edit_message(summary, message.chat.id, status_msg.message_id, reply_markup=None, parse_mode="Markdown")

            threading.Thread(target=run_par_tt_bg, daemon=True).start()
        return

    if action == "list_devices":
        response = f"📊 **DANH SÁCH THIẾT BỊ ĐANG KẾT NỐI ({len(devices)} máy):**\n\n"
        for d in devices:
            response += f"📱 **Máy {get_device_name(d)}**: ID: `{d}`\n"
        bot.reply_to(message, response, parse_mode="Markdown")

    elif action == "screenshot":
        tgt_dev = target_devices[0]
        tgt_name = get_device_name(tgt_dev)
        status_msg = bot.reply_to(message, f"📸 Đang chụp màn hình máy {tgt_name}...")
        
        temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        local_path = os.path.join(temp_dir, f"screenshot_{tgt_name}.png")
        
        success, result = adb.take_screenshot(tgt_dev, local_path)
        
        if success:
            bot.delete_message(message.chat.id, status_msg.message_id)
            with open(local_path, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=f"🖼️ Ảnh chụp màn hình **Máy {tgt_name}**")
            try:
                os.remove(local_path)
            except Exception:
                pass
        else:
            bot.edit_message_text(f"❌ Không thể chụp màn hình máy {tgt_name}. Lỗi: {result}", message.chat.id, status_msg.message_id)

    elif action == "shopee_search":
        keywords = cmd["keywords"]
        def gemini_status(msg):
            safe_send_message(message.chat.id, f"🤖 [Gemini AI]: {msg}")
        expanded_keywords = config.generate_keywords_via_gemini(
            config.GEMINI_API_KEY, 
            keywords, 
            status_cb=gemini_status
        )
        
        if len(target_devices) == 1:
            tgt_dev = target_devices[0]
            tgt_name = get_device_name(tgt_dev)
            current_keyword = random.choice(expanded_keywords)
            
            tracker = TelegramRealtimeTracker(bot, message.chat.id)
            tracker.start_dashboard(f"🛒 **Máy {tgt_name}**: Bắt đầu mở Shopee và tìm kiếm `{current_keyword}`...")
            tracker.set_active_device(tgt_name, tgt_dev, current_keyword, 1, 1)
            
            dev_start = time.time()
            success, err = adb.shopee_search_sequence(tgt_dev, current_keyword, status_callback=tracker.status_callback, is_cancelled=is_cancelled)
            duration = time.time() - dev_start
            
            tracker.finish_dashboard("🏁 Hoàn tất tác vụ tìm kiếm.")
            send_device_finished_card(message.chat.id, tgt_name, tgt_dev, current_keyword, success, err, duration)
        else:
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
            status_msg = bot.reply_to(message, f"🚀 Bắt đầu chạy song song trên {len(target_devices)} máy...", reply_markup=markup)
            keyword_assignments = assign_shopee_keywords(
                expanded_keywords,
                target_devices,
            )
            
            def run_search_parallel(device_id):
                dev_name = get_device_name(device_id)
                current_keyword = keyword_assignments[device_id]
                dev_start = time.time()
                success, err = adb.shopee_search_sequence(device_id, current_keyword, is_cancelled=is_cancelled)
                dev_dur = time.time() - dev_start
                send_device_finished_card(message.chat.id, dev_name, device_id, current_keyword, success, err, dev_dur)
                return dev_name, current_keyword, success, err
                
            results = []
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in target_devices]
                for future in futures:
                    results.append(future.result())
            
            success_count = sum(1 for r in results if r[2])
            summary = f"🏁 **HOÀN THÀNH TÌM KIẾM SONG SONG ({success_count}/{len(target_devices)} MÁY)**"
            safe_edit_message(summary, message.chat.id, status_msg.message_id, reply_markup=None, parse_mode="Markdown")

    elif action == "shopee_search_lamdong":
        keywords = cmd["keywords"]
        click_first = cmd.get("click_first_item", False)
        
        def gemini_status(msg):
            safe_send_message(message.chat.id, f"🤖 [Gemini AI]: {msg}")
        expanded_keywords = config.generate_keywords_via_gemini(
            config.GEMINI_API_KEY, 
            keywords, 
            status_cb=gemini_status
        )
        
        if len(target_devices) == 1:
            tgt_dev = target_devices[0]
            tgt_name = get_device_name(tgt_dev)
            current_keyword = random.choice(expanded_keywords)
            
            tracker = TelegramRealtimeTracker(bot, message.chat.id)
            tracker.start_dashboard(f"🔍 **Máy {tgt_name}**: Bắt đầu quét shop Lâm Đồng từ khóa `{current_keyword}`...")
            tracker.set_active_device(tgt_name, tgt_dev, current_keyword, 1, 1)
            
            dev_start = time.time()
            success, err = adb.shopee_find_and_click_lamdong(tgt_dev, current_keyword, status_callback=tracker.status_callback, is_cancelled=is_cancelled, click_first_item=click_first)
            duration = time.time() - dev_start
            
            tracker.finish_dashboard("🏁 Hoàn tất tác vụ tìm shop Lâm Đồng.")
            send_device_finished_card(message.chat.id, tgt_name, tgt_dev, current_keyword, success, err, duration)
        else:
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🛑 DỪNG CHẠY KHẨN CẤP", callback_data="stop_all"))
            status_msg = bot.reply_to(message, f"🚀 Bắt đầu quét shop Lâm Đồng song song trên {len(target_devices)} máy...", reply_markup=markup)
            keyword_assignments = assign_shopee_keywords(
                expanded_keywords,
                target_devices,
            )
            
            def run_search_parallel(device_id):
                dev_name = get_device_name(device_id)
                current_keyword = keyword_assignments[device_id]
                dev_start = time.time()
                success, err = adb.shopee_find_and_click_lamdong(device_id, current_keyword, is_cancelled=is_cancelled, click_first_item=click_first)
                dev_dur = time.time() - dev_start
                send_device_finished_card(message.chat.id, dev_name, device_id, current_keyword, success, err, dev_dur)
                return dev_name, current_keyword, success, err
                
            results = []
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in target_devices]
                for future in futures:
                    results.append(future.result())
            
            success_count = sum(1 for r in results if r[2])
            summary = f"🏁 **KẾT QUẢ QUÉT SHOP LÂM ĐỒNG SONG SONG ({success_count}/{len(target_devices)} MÁY THÀNH CÔNG)**"
            safe_edit_message(summary, message.chat.id, status_msg.message_id, reply_markup=None, parse_mode="Markdown")

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
        status_msg = bot.send_message(message.chat.id, "🛑 **HỦY BỎ TÁC VỤ**\n\nĐang gửi lệnh dừng khẩn cấp cho tất cả các máy...")
        
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
        for dev in target_devices:
            adb.launch_app(dev, config.SHOPEE_PACKAGE)
        bot.reply_to(message, f"✅ Đã mở Shopee trên {len(target_devices)} máy.")

    elif action == "close_shopee":
        for dev in target_devices:
            adb.stop_app(dev, config.SHOPEE_PACKAGE)
        bot.reply_to(message, f"✅ Đã buộc dừng Shopee trên {len(target_devices)} máy.")

    elif action == "back":
        for dev in target_devices:
            adb.keyevent(dev, 4)
        bot.reply_to(message, f"↩️ Đã gửi lệnh Quay lại trên {len(target_devices)} máy.")

    elif action == "home":
        for dev in target_devices:
            adb.keyevent(dev, 3)
        bot.reply_to(message, f"🏠 Đã gửi lệnh màn hình chính trên {len(target_devices)} máy.")

    elif action == "click":
        x, y = cmd["x"], cmd["y"]
        for dev in target_devices:
            adb.tap(dev, x, y)
        bot.reply_to(message, f"👆 Đã click tọa độ ({x}, {y}) trên {len(target_devices)} máy.")

    elif action == "input":
        text_val = cmd["text"]
        for dev in target_devices:
            adb.input_text(dev, text_val)
        bot.reply_to(message, f"✍️ Đã nhập '{text_val}' trên {len(target_devices)} máy.")

    elif action == "disable_rotation":
        for dev in target_devices:
            adb.execute_adb(dev, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
            adb.execute_adb(dev, ["shell", "settings", "put", "system", "user_rotation", "0"])
        bot.reply_to(message, f"📴 Đã tắt xoay màn hình trên {len(target_devices)} máy.")

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
    skip_pending_on_start = True
    while True:
        try:
            skip_pending = skip_pending_on_start
            skip_pending_on_start = False
            bot.polling(
                none_stop=True,
                skip_pending=skip_pending,
                interval=1,
                timeout=20,
            )
        except Exception as e:
            print(f"Bot bi loi mat ket noi, dang khoi dong lai sau 5s... Loi: {e}")
            time.sleep(5)

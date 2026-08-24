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
TELEGRAM_DISABLED_BOT_TOKEN = "0:disabled"


def is_valid_telegram_token(token):
    """Validate a token before startup/polling so the GUI cannot crash."""
    clean_token = (token or "").strip()
    if not re.fullmatch(r"\d+:[^\s:]+", clean_token):
        return False
    try:
        telebot.util.validate_token(clean_token)
    except (TypeError, ValueError):
        return False
    return True


def create_telegram_bot(token):
    """Create an offline-safe bot when Telegram has not been configured."""
    clean_token = (token or "").strip()
    effective_token = (
        clean_token
        if is_valid_telegram_token(clean_token)
        else TELEGRAM_DISABLED_BOT_TOKEN
    )
    return telebot.TeleBot(effective_token)


def configure_telegram_bot_token(token):
    """Update the existing bot so its registered handlers are preserved."""
    clean_token = (token or "").strip()
    valid = is_valid_telegram_token(clean_token)
    bot.token = clean_token if valid else TELEGRAM_DISABLED_BOT_TOKEN
    return valid


bot = create_telegram_bot(config.TELEGRAM_BOT_TOKEN)
adb = ADBController()

# Các biến toàn cục điều khiển chạy tuần tự và hủy bỏ tác vụ
cancel_sequential = False
cancel_flag = False
_workflow_session_lock = threading.Lock()
_workflow_session_id = 0


def start_workflow_session():
    """Bắt đầu phiên mới và vô hiệu hóa vĩnh viễn mọi worker phiên cũ."""
    global cancel_flag, cancel_sequential, _workflow_session_id
    with _workflow_session_lock:
        _workflow_session_id += 1
        cancel_flag = False
        cancel_sequential = False
        return _workflow_session_id


def cancel_all_workflows():
    """Dừng phiên hiện tại; worker cũ không thể sống lại ở phiên sau."""
    global cancel_flag, cancel_sequential, _workflow_session_id
    with _workflow_session_lock:
        _workflow_session_id += 1
        cancel_flag = True
        cancel_sequential = True
        return _workflow_session_id


def is_session_cancelled(session_id):
    with _workflow_session_lock:
        return (
            cancel_flag
            or cancel_sequential
            or session_id != _workflow_session_id
        )


def make_session_cancel_checker(session_id):
    return lambda: is_session_cancelled(session_id)

def is_cancelled():
    global cancel_flag, cancel_sequential
    return cancel_flag or cancel_sequential

# Caching mapping thiết bị toàn cục để tra cứu nhanh
cached_mapping = {}


class _TelegramNotificationsDisabled:
    """Gia lap ket qua gui de luong dang chay khong bi loi message_id."""

    message_id = 0


def telegram_notifications_enabled():
    return bool(
        getattr(config, "TELEGRAM_NOTIFICATIONS_ENABLED", True)
        and is_valid_telegram_token(getattr(config, "TELEGRAM_BOT_TOKEN", ""))
    )

def safe_send_message(chat_id, text, parse_mode=None, reply_markup=None, reply_to_message_id=None):
    if not telegram_notifications_enabled():
        return _TelegramNotificationsDisabled()
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
    if not telegram_notifications_enabled():
        return None
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
    if not telegram_notifications_enabled():
        return None
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
        self.platform = "System"

    def start_dashboard(self, initial_text):
        msg = safe_send_message(self.chat_id, initial_text, parse_mode="Markdown", reply_markup=self.reply_markup)
        if msg:
            self.live_msg_id = msg.message_id
            self.last_text = initial_text
            self.last_edit_time = time.time()

    def set_active_device(self, dev_name, dev_serial, keyword, current_idx, total_devices, platform="System"):
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


def save_admin_to_env(user_id):
    env_path = config.ENV_PATH
    lines = []
    if env_path.exists():
        with env_path.open('r', encoding='utf-8') as f:
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
        
    with env_path.open('w', encoding='utf-8') as f:
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
    text_lower = text.lower().strip()
    
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
@bot.message_handler(commands=["start", "help", "menu"])
def handle_slash_commands(message):
    if check_auth(message):
        send_full_dashboard(message)


def send_full_dashboard(message):
    instructions = (
        "🤖 **BOXPHONECONTROL • BẢNG ĐIỀU KHIỂN**\n\n"
        "🎵 **TikTok**\n"
        "/tiktok từ khóa 1, từ khóa 2 | kênh_a, kênh_b\n"
        "/tiktok tuần tự từ khóa | kênh_mục_tiêu\n\n"
        "📊 **Thiết bị**\n"
        "• danh sách máy\n"
        "• chụp màn hình máy 1\n"
        "• quay lại máy 1 / trang chủ máy 1\n\n"
        "🛑 Nhắn dừng hoặc bấm nút bên dưới để dừng tác vụ."
    )
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton(
            "📊 Danh sách Máy", callback_data="btn_list"
        ),
        telebot.types.InlineKeyboardButton(
            "📸 Chụp màn hình S1", callback_data="btn_screenshot_1"
        ),
        telebot.types.InlineKeyboardButton(
            "🛑 DỪNG KHẨN CẤP", callback_data="stop_all"
        ),
    )
    bot.reply_to(
        message,
        instructions,
        parse_mode="Markdown",
        reply_markup=markup,
    )


# Xử lý tất cả Inline Keyboard Callbacks
@bot.callback_query_handler(func=lambda call: True)
def handle_inline_callbacks(call):
    data = call.data
    chat_id = call.message.chat.id

    if data == "btn_list":
        bot.answer_callback_query(call.id)
        devices = get_ordered_devices()
        response = (
            f"📊 **DANH SÁCH THIẾT BỊ ĐANG KẾT NỐI "
            f"({len(devices)} máy):**\n\n"
        )
        for device in devices:
            response += (
                f"📱 **Máy {get_device_name(device)}**: ID: {device}\n"
            )
        safe_send_message(chat_id, response, parse_mode="Markdown")

    elif data == "btn_screenshot_1":
        bot.answer_callback_query(call.id)
        devices = get_ordered_devices()
        if not devices:
            safe_send_message(chat_id, "❌ Không có máy nào đang kết nối.")
            return
        device = devices[0]
        device_name = get_device_name(device)
        temp_dir = os.path.join(os.path.dirname(__file__), "temp")
        os.makedirs(temp_dir, exist_ok=True)
        local_path = os.path.join(
            temp_dir, f"screenshot_{device_name}.png"
        )
        success, _ = adb.take_screenshot(device, local_path)
        if success:
            with open(local_path, "rb") as photo:
                bot.send_photo(
                    chat_id,
                    photo,
                    caption=f"🖼️ Ảnh chụp màn hình Máy {device_name}",
                )
            try:
                os.remove(local_path)
            except OSError:
                pass

    elif data == "stop_all":
        bot.answer_callback_query(call.id)
        cancel_all_workflows()
        safe_send_message(
            chat_id,
            "⏹️ **ĐÃ DỪNG TẤT CẢ TÁC VỤ**",
            parse_mode="Markdown",
        )


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
        workflow_session = start_workflow_session()
        session_is_cancelled = make_session_cancel_checker(
            workflow_session
        )
        
        if is_seq or len(target_devices) == 1:
            def run_seq_tt_thread():
                tracker = TelegramRealtimeTracker(bot, message.chat.id)
                tracker.start_dashboard(f"🎵 **BƠM TIKTOK TUẦN TỰ**\nKênh mục tiêu: `{target_ch}`\nĐang quét trên {len(target_devices)} máy...")

                success_count = 0
                for idx, dev in enumerate(target_devices):
                    if session_is_cancelled():
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
                        is_cancelled=session_is_cancelled
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
                    is_cancelled=session_is_cancelled
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

    elif action == "stop_all":
        cancel_all_workflows()
        status_msg = bot.send_message(message.chat.id, "🛑 **HỦY BỎ TÁC VỤ**\n\nĐang gửi lệnh dừng khẩn cấp cho tất cả các máy...")
        
        def finish_stop_notice():
            time.sleep(3.5)
            try:
                bot.edit_message_text("⏹️ **HỦY BỎ THÀNH CÔNG**\n\nToàn bộ tiến trình tự động hóa đã dừng lại. Bot đã sẵn sàng nhận các câu lệnh mới.", message.chat.id, status_msg.message_id)
            except Exception:
                pass
                
        threading.Thread(target=finish_stop_notice).start()

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

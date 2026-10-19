import os
import shutil
import sys
from pathlib import Path
from dotenv import load_dotenv

APP_NAME = "BoxPhoneControl"


def resolve_runtime_base_dir(module_file=None):
    """Trả về thư mục cấu hình ghi được cho source và bản Windows đã cài."""
    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    return Path(module_file or __file__).resolve().parent


# Bản cài nằm trong Program Files (chỉ đọc), nên cấu hình người dùng phải nằm
# trong LocalAppData. Source vẫn dùng .env tại thư mục dự án như trước.
BASE_DIR = resolve_runtime_base_dir()
BASE_DIR.mkdir(parents=True, exist_ok=True)
ENV_PATH = BASE_DIR / ".env"

# Tự động tiếp nhận cấu hình của bản portable cũ nếu nó nằm cạnh EXE.
if getattr(sys, "frozen", False) and not ENV_PATH.exists():
    legacy_env_path = Path(sys.executable).resolve().parent / ".env"
    if legacy_env_path.is_file():
        try:
            shutil.copy2(legacy_env_path, ENV_PATH)
        except OSError:
            pass

load_dotenv(dotenv_path=ENV_PATH)
if not os.getenv("NOTION_API_TOKEN"):
    appdata_env = Path(os.getenv("LOCALAPPDATA", "")) / APP_NAME / ".env"
    if appdata_env.is_file():
        load_dotenv(dotenv_path=appdata_env)

def resolve_adb_path(raw_path):
    """Chuẩn hóa đường dẫn ADB: tự động thêm adb.exe nếu người dùng chỉ nhập thư mục."""
    if not raw_path:
        for cand in [
            r"C:\Program Files (x86)\xiaowei_android\tools\adb.exe",
            r"C:\Program Files (x86)\xiaowei\tools\adb.exe",
        ]:
            if os.path.isfile(cand):
                return cand
        return r"C:\Program Files (x86)\xiaowei_android\tools\adb.exe"
    p = str(raw_path).strip().strip('"').strip("'")
    if os.path.isdir(p):
        for candidate in [os.path.join(p, "adb.exe"), os.path.join(p, "adb")]:
            if os.path.isfile(candidate):
                return candidate
        return os.path.join(p, "adb.exe")
    if not p.lower().endswith(".exe") and not os.path.isfile(p):
        cand = p + ".exe"
        if os.path.isfile(cand):
            return cand
    return p


def parse_adb_ports(raw_ports):
    """Phân tích cấu hình các cổng ADB (vd: '5037,5038') thành tuple số nguyên."""
    if not raw_ports:
        return (5037, 5038)
    ports = []
    cleaned = str(raw_ports).replace("[", "").replace("]", "").replace(";", ",")
    for part in cleaned.split(","):
        part = part.strip()
        if part.isdigit():
            p = int(part)
            if 1 <= p <= 65535 and p not in ports:
                ports.append(p)
    return tuple(ports) if ports else (5037, 5038)


# Danh sách cổng ADB đa tiến trình (hỗ trợ Box 40 máy chạy song song trên cổng 5037 và 5038)
ADB_PORTS = parse_adb_ports(os.getenv("ADB_PORTS", "5037,5038"))


# Token Bot Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Cho phep tat toan bo ket noi va thong bao Telegram tu giao dien.
TELEGRAM_NOTIFICATIONS_ENABLED = os.getenv(
    "TELEGRAM_NOTIFICATIONS_ENABLED", "1"
).strip().lower() not in {"0", "false", "no", "off"}

# Danh sách ID người dùng được phép điều khiển bot (để trống nếu cho phép tất cả các tài khoản)
ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS_RAW.split(",") if uid.strip().isdigit()]

# Đường dẫn đến công cụ adb.exe của phần mềm xiaowei
ADB_PATH = resolve_adb_path(
    os.getenv("ADB_PATH", r"C:\Program Files (x86)\xiaowei_android\tools\adb.exe")
)

# Tên gói ứng dụng (package) của TikTok
TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_PACKAGE_ALT = "com.zhiliaoapp.musically"

# Cấu hình mặc định cho tự động hóa Bơm TikTok
TIKTOK_TARGET_CHANNEL_DEFAULT = os.getenv(
    "TIKTOK_TARGET_CHANNEL", "Khải Hoàn Skincare PT, Khải Hoàn & 101 Nốt Mụn"
)
TIKTOK_SEED_KEYWORDS_DEFAULT = os.getenv(
    "TIKTOK_SEED_KEYWORDS",
    (
        "chăm sóc da phan thiết, nặn mụn phan thiết, trị mụn phan thiết, "
        "spa mụn phan thiết, nặn mụn Phan Thiết, "
        "lấy nhân mụn chuẩn y khoa Phan Thiết, nặn mụn không đau Phan Thiết"
    ),
)
TIKTOK_WATCH_TIME_MIN_DEFAULT = 5
TIKTOK_WATCH_TIME_MAX_DEFAULT = 10
TIKTOK_STEP1_TOTAL_MIN = 10
TIKTOK_STEP1_TOTAL_MAX = 20
TIKTOK_STEP2_TOTAL_MIN = 10
TIKTOK_STEP2_TOTAL_MAX = 15
TIKTOK_STEP3_TOTAL_MIN = int(os.getenv("TIKTOK_STEP3_TOTAL_MIN", "300"))
TIKTOK_STEP3_TOTAL_MAX = int(os.getenv("TIKTOK_STEP3_TOTAL_MAX", "480"))
TIKTOK_STEP3_VIDEO_MIN = int(os.getenv("TIKTOK_STEP3_VIDEO_MIN", "30"))
TIKTOK_STEP3_VIDEO_MAX = int(os.getenv("TIKTOK_STEP3_VIDEO_MAX", "50"))

# Nuôi chéo social trước khi chạy workflow chính Facebook/TikTok.
SOCIAL_CROSS_WARMUP_MIN = 10
SOCIAL_CROSS_WARMUP_MAX = 20

# Cấu hình mặc định cho quy trình Bơm Facebook
FACEBOOK_PACKAGE = "com.facebook.katana"
FACEBOOK_STEP1_FEED_MIN = 10
FACEBOOK_STEP1_FEED_MAX = 20
FACEBOOK_STEP2_RESULTS_MIN = 10
FACEBOOK_STEP2_RESULTS_MAX = 15
FACEBOOK_STEP3_PAGE_MIN = int(os.getenv("FACEBOOK_STEP3_PAGE_MIN", "300"))
FACEBOOK_STEP3_PAGE_MAX = int(os.getenv("FACEBOOK_STEP3_PAGE_MAX", "480"))
FACEBOOK_STEP3_POST_DWELL_MIN = int(os.getenv("FACEBOOK_STEP3_POST_DWELL_MIN", "15"))
FACEBOOK_STEP3_POST_DWELL_MAX = int(os.getenv("FACEBOOK_STEP3_POST_DWELL_MAX", "30"))
FACEBOOK_SEED_KEYWORDS_DEFAULT = os.getenv(
    "FACEBOOK_SEED_KEYWORDS",
    (
        "chăm sóc da phan thiết, nặn mụn phan thiết, trị mụn phan thiết, "
        "spa mụn phan thiết, nặn mụn Phan Thiết, "
        "lấy nhân mụn chuẩn y khoa Phan Thiết, nặn mụn không đau Phan Thiết"
    ),
)
FACEBOOK_TARGET_PAGE_EXACT_DEFAULT = os.getenv(
    "FACEBOOK_TARGET_PAGE_EXACT", "Khải Hoàn Skincare, Nhà thuốc Khải Hoàn"
)
FACEBOOK_CANONICAL_PAGE_NAME = os.getenv(
    "FACEBOOK_CANONICAL_PAGE_NAME",
    (
        "Nhà thuốc Khải Hoàn Skincare - Chăm sóc da chuẩn y khoa "
        "Phan Thiết"
    ),
)

# Notion chỉ cung cấp dữ liệu đầu vào; token luôn được lưu cục bộ trong .env.
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN", "")
NOTION_DATA_SOURCE_ID = os.getenv(
    "NOTION_DATA_SOURCE_ID", "654a56cd7cf5416fb65f9b934a62ec45"
)

# Tỷ lệ Vi Tương Tác (Micro-Interactions Matrix) - Đảm bảo lượt tương tác tự nhiên ổn định
INTERACTION_LIKE_RATE = float(os.getenv("INTERACTION_LIKE_RATE", "0.25"))
INTERACTION_BOOKMARK_RATE = float(os.getenv("INTERACTION_BOOKMARK_RATE", "0.08"))
INTERACTION_SHARE_RATE = float(os.getenv("INTERACTION_SHARE_RATE", "0.02"))
INTERACTION_COMMENT_RATE = float(os.getenv("INTERACTION_COMMENT_RATE", "0.10"))
INTERACTION_LOOP_RATE = float(os.getenv("INTERACTION_LOOP_RATE", "0.15"))

# Tùy chọn Tăng Traffic Đột Phá - Mặc định tắt click video từ Search để tránh video ngoài kênh
TIKTOK_SEARCH_CLICK_VIDEO_ENABLED = os.getenv(
    "TIKTOK_SEARCH_CLICK_VIDEO_ENABLED", "0"
).strip().lower() not in {"0", "false", "no", "off"}

FACEBOOK_REELS_BOOST_ENABLED = os.getenv(
    "FACEBOOK_REELS_BOOST_ENABLED", "1"
).strip().lower() not in {"0", "false", "no", "off"}

# Cấu hình Bộ Lên Lịch Tự Động (Auto-Scheduler)
AUTO_SCHEDULE_ENABLED = os.getenv(
    "AUTO_SCHEDULE_ENABLED", "0"
).strip().lower() not in {"0", "false", "no", "off"}
AUTO_SCHEDULE_HOURS_DEFAULT = os.getenv(
    "AUTO_SCHEDULE_HOURS", "11:45, 19:30, 22:30"
)
AUTO_SCHEDULE_MODE_DEFAULT = os.getenv(
    "AUTO_SCHEDULE_MODE", "adaptive"
)

# Cấu hình lặp lại cả ngày & nghỉ giữa các lượt (tính theo từng máy)
SESSION_RUNS_DEFAULT = int(os.getenv("SESSION_RUNS_DEFAULT", "1"))
SESSION_DELAY_MIN_DEFAULT = int(os.getenv("SESSION_DELAY_MIN_DEFAULT", "30"))
SESSION_DELAY_MAX_DEFAULT = int(os.getenv("SESSION_DELAY_MAX_DEFAULT", "60"))

# Cấu hình Quản lý Bơm Bình Luận (Notion Seeding)
NOTION_COMMENT_SEEDING_TOKEN = os.getenv(
    "NOTION_COMMENT_SEEDING_TOKEN",
    os.getenv("NOTION_API_TOKEN", ""),
)
NOTION_COMMENT_SEEDING_DATABASE_ID = os.getenv(
    "NOTION_COMMENT_SEEDING_DATABASE_ID",
    "1064bf0f819748a797c195247b2ea14e",
)




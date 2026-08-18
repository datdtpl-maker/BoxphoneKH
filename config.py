import os
import sys
from pathlib import Path
from dotenv import load_dotenv

def resolve_runtime_base_dir(module_file=None):
    """Trả về thư mục cấu hình bền vững cho source và PyInstaller onefile."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(module_file or __file__).resolve().parent


# Trong bản onefile, __file__ nằm ở thư mục _MEI tạm và bị xóa khi đóng app.
# Luôn đọc/ghi .env cạnh EXE để cấu hình được giữ lại giữa các lần mở.
BASE_DIR = resolve_runtime_base_dir()
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

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
ADB_PATH = os.getenv(
    "ADB_PATH", r"C:\Program Files (x86)\xiaowei\tools\adb.exe"
)

# Cấu hình cho tự động hóa Bơm Google Maps qua Google Chrome
CHROME_PACKAGE = "com.android.chrome"
GOOGLE_MAPS_PACKAGE = "com.google.android.apps.maps"
GOOGLE_MAPS_TARGET_NAME_DEFAULT = "Nhà thuốc Khải Hoàn Skincare"
GOOGLE_MAPS_LOCATION_TEXT_DEFAULT = "Phan Thiết, Lâm Đồng"

GOOGLE_MAPS_TARGET_NAME = os.getenv(
    "GOOGLE_MAPS_TARGET_NAME", GOOGLE_MAPS_TARGET_NAME_DEFAULT
)
GOOGLE_MAPS_LOCATION_TEXT = os.getenv(
    "GOOGLE_MAPS_LOCATION_TEXT", GOOGLE_MAPS_LOCATION_TEXT_DEFAULT
)
GOOGLE_MAPS_DWELL_MIN = 120
GOOGLE_MAPS_DWELL_MAX = 180

# Tên gói ứng dụng (package) của TikTok
TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_PACKAGE_ALT = "com.zhiliaoapp.musically"

# Cấu hình mặc định cho tự động hóa Bơm TikTok
TIKTOK_TARGET_CHANNEL_DEFAULT = os.getenv("TIKTOK_TARGET_CHANNEL", "")
TIKTOK_SEED_KEYWORDS_DEFAULT = "skincare, trị mụn, nặn mụn, chăm sóc da"
TIKTOK_WATCH_TIME_MIN_DEFAULT = 5
TIKTOK_WATCH_TIME_MAX_DEFAULT = 10
TIKTOK_STEP1_TOTAL_MIN = 15
TIKTOK_STEP1_TOTAL_MAX = 60
TIKTOK_STEP2_TOTAL_MIN = 15
TIKTOK_STEP2_TOTAL_MAX = 30
TIKTOK_STEP3_TOTAL_MIN = 180
TIKTOK_STEP3_TOTAL_MAX = 300
TIKTOK_STEP3_VIDEO_MIN = 15
TIKTOK_STEP3_VIDEO_MAX = 30

# Nuôi chéo social trước khi chạy workflow chính Facebook/TikTok.
SOCIAL_CROSS_WARMUP_MIN = 180
SOCIAL_CROSS_WARMUP_MAX = 300

# Cấu hình mặc định cho quy trình Bơm Facebook
FACEBOOK_PACKAGE = "com.facebook.katana"
FACEBOOK_STEP1_FEED_MIN = 90
FACEBOOK_STEP1_FEED_MAX = 120
FACEBOOK_STEP2_RESULTS_MIN = 30
FACEBOOK_STEP2_RESULTS_MAX = 60
FACEBOOK_STEP3_PAGE_MIN = 120
FACEBOOK_STEP3_PAGE_MAX = 180
FACEBOOK_TARGET_PAGE_EXACT_DEFAULT = os.getenv(
    "FACEBOOK_TARGET_PAGE_EXACT", ""
)

# Notion chỉ cung cấp dữ liệu đầu vào; token luôn được lưu cục bộ trong .env.
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN", "")
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID", "")

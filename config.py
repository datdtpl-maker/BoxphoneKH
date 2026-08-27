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

# Tên gói ứng dụng (package) của TikTok
TIKTOK_PACKAGE = "com.ss.android.ugc.trill"
TIKTOK_PACKAGE_ALT = "com.zhiliaoapp.musically"

# Cấu hình mặc định cho tự động hóa Bơm TikTok
TIKTOK_TARGET_CHANNEL_DEFAULT = os.getenv("TIKTOK_TARGET_CHANNEL", "")
TIKTOK_SEED_KEYWORDS_DEFAULT = "skincare, trị mụn, nặn mụn, chăm sóc da"
TIKTOK_WATCH_TIME_MIN_DEFAULT = 5
TIKTOK_WATCH_TIME_MAX_DEFAULT = 10
TIKTOK_STEP1_TOTAL_MIN = 10
TIKTOK_STEP1_TOTAL_MAX = 20
TIKTOK_STEP2_TOTAL_MIN = 10
TIKTOK_STEP2_TOTAL_MAX = 15
TIKTOK_STEP3_TOTAL_MIN = 180
TIKTOK_STEP3_TOTAL_MAX = 300
TIKTOK_STEP3_VIDEO_MIN = 15
TIKTOK_STEP3_VIDEO_MAX = 30

# Nuôi chéo social trước khi chạy workflow chính Facebook/TikTok.
SOCIAL_CROSS_WARMUP_MIN = 10
SOCIAL_CROSS_WARMUP_MAX = 20

# Cấu hình mặc định cho quy trình Bơm Facebook
FACEBOOK_PACKAGE = "com.facebook.katana"
FACEBOOK_STEP1_FEED_MIN = 10
FACEBOOK_STEP1_FEED_MAX = 20
FACEBOOK_STEP2_RESULTS_MIN = 10
FACEBOOK_STEP2_RESULTS_MAX = 15
FACEBOOK_STEP3_PAGE_MIN = 180
FACEBOOK_STEP3_PAGE_MAX = 300
FACEBOOK_TARGET_PAGE_EXACT_DEFAULT = os.getenv(
    "FACEBOOK_TARGET_PAGE_EXACT", ""
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
NOTION_DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID", "")

import os
from pathlib import Path
from dotenv import load_dotenv

# Tải cấu hình từ file .env
load_dotenv()

# Đường dẫn tới thư mục gốc của project
BASE_DIR = Path(__file__).resolve().parent

# Token Bot Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Danh sách ID người dùng được phép điều khiển bot (để trống nếu cho phép tất cả các tài khoản)
ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS_RAW.split(",") if uid.strip().isdigit()]

# Đường dẫn đến công cụ adb.exe của phần mềm xiaowei
ADB_PATH = r"C:\Program Files (x86)\xiaowei\tools\adb.exe"

# Cấu hình tự động hóa Shopee (Cho màn hình 1080x1920)
# Tọa độ ô tìm kiếm trên trang chủ Shopee (x, y)
SHOPEE_SEARCH_BOX_COORDS = (540, 140)  # Thường nằm ở thanh header phía trên

# Tọa độ ô nhập liệu sau khi đã bấm vào thanh tìm kiếm
SHOPEE_INPUT_BOX_COORDS = (300, 140)

# Tọa độ nút "Tìm kiếm" trên bàn phím hoặc nút Tìm trên màn hình (nếu không bấm được Enter bằng ADB)
# Mặc định sử dụng phím ENTER của ADB (Keycode 66), nếu không hoạt động sẽ dùng nút click
SHOPEE_SEARCH_BTN_COORDS = (980, 140)

# Tên gói ứng dụng (package) của Shopee
SHOPEE_PACKAGE = "com.shopee.vn"
SHOPEE_ACTIVITY = "com.shopee.app.home.HomeActivity"

# Danh sách tên shop của bạn dùng để tìm kiếm dự phòng
SHOPEE_SHOP_NAMES_RAW = os.getenv("SHOPEE_SHOP_NAMES", "")
SHOPEE_SHOP_NAMES = [s.strip() for s in SHOPEE_SHOP_NAMES_RAW.split(",") if s.strip()]

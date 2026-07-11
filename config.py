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

# API Key Gemini dùng để sinh từ khóa
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

import urllib.request
import json

def generate_keywords_via_gemini(api_key, main_keywords, status_cb=None):
    """
    Sử dụng Gemini API để sinh ra các từ khóa liên quan từ các từ khóa chính.
    Mỗi từ khóa chính sinh ra 10 từ khóa liên quan.
    """
    def log(msg):
        print(f"[Gemini AI] {msg}")
        if status_cb:
            status_cb(msg)
            
    if not api_key:
        api_key = ""
        
    if isinstance(main_keywords, str):
        keywords_list = [k.strip() for k in main_keywords.split(",") if k.strip()]
    else:
        keywords_list = main_keywords

    if not keywords_list:
        return []

    log(f"Đang sinh từ khóa phụ cho các từ khóa chính: {keywords_list}...")
    
    # Tạo prompt chi tiết
    prompt = (
        "Bạn là chuyên gia SEO và thương mại điện tử Shopee.\n"
        f"Tôi có danh sách các từ khóa chính sau: {', '.join(keywords_list)}.\n"
        "Với mỗi từ khóa chính trong danh sách, hãy sinh ra đúng 10 từ khóa tìm kiếm liên quan (tổng cộng sẽ là "
        f"{len(keywords_list) * 10} từ khóa).\n"
        "Yêu cầu từ khóa được sinh ra:\n"
        "1. Phù hợp để tìm kiếm sản phẩm trên Shopee Việt Nam (ngắn gọn, thực tế, đúng hành vi người mua).\n"
        "2. Viết bằng tiếng Việt.\n"
        "3. Trả về kết quả DƯỚI DẠNG DANH SÁCH JSON là một mảng các chuỗi, ví dụ: [\"từ khóa 1\", \"từ khóa 2\", ...].\n"
        "Tuyệt đối không viết thêm lời giải thích hay bất kỳ ký tự nào ngoài định dạng JSON."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            text_response = res_data['candidates'][0]['content']['parts'][0]['text']
            
            # Parse JSON từ response text
            generated_list = json.loads(text_response.strip())
            if isinstance(generated_list, list):
                res = [str(item).strip() for item in generated_list if item]
                log(f"Đã dùng Gemini sinh ra {len(res)} từ khóa thành công!")
                return res
    except Exception as e:
        log(f"Lỗi gọi Gemini API ({e}). Đang tạo danh sách từ khóa phụ dự phòng...")
        
    # Luồng dự phòng nếu API lỗi: tự sinh từ khóa liên quan bằng các hậu tố phổ biến
    suffixes = [
        " chính hãng", " giá rẻ", " tốt nhất", " shopee", " cao cấp", 
        " trị mụn", " bôi da", " an toàn", " cho bé", " hiệu quả"
    ]
    fallback_list = []
    for kw in keywords_list:
        for s in suffixes:
            fallback_list.append(f"{kw}{s}")
    log(f"Đã tạo {len(fallback_list)} từ khóa phụ dự phòng.")
    return fallback_list

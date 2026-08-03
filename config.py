import os
from pathlib import Path
from dotenv import load_dotenv

# Tải cấu hình từ file .env
load_dotenv()

# Đường dẫn tới thư mục gốc của project
BASE_DIR = Path(__file__).resolve().parent

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

    suffixes = [
        " chính hãng", " giá rẻ", " tốt nhất", " shopee", " cao cấp",
        " trị mụn", " bôi da", " an toàn", " cho bé", " hiệu quả"
    ]
    fallback_list = [
        f"{keyword}{suffix}"
        for keyword in keywords_list
        for suffix in suffixes
    ]
    expected_count = len(keywords_list) * 10

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
                if len(res) == expected_count:
                    log(f"Đã dùng Gemini sinh ra đúng {len(res)} từ khóa thành công!")
                    return res
                log(
                    f"Gemini trả về {len(res)}/{expected_count} từ khóa; "
                    "dùng danh sách dự phòng để bảo đảm đúng 10 từ cho mỗi đầu vào."
                )
    except Exception as e:
        log(f"Lỗi gọi Gemini API ({e}). Đang tạo danh sách từ khóa phụ dự phòng...")
        
    # Luồng dự phòng nếu API lỗi: tự sinh từ khóa liên quan bằng các hậu tố phổ biến
    log(f"Đã tạo {len(fallback_list)} từ khóa phụ dự phòng.")
    return fallback_list

def generate_keywords_tier2_via_gemini(api_key, shopee_product_titles, status_cb=None):
    """
    Sử dụng Gemini API để sinh từ khóa Tầng 2 (bóc tách tiêu đề thô, suy luận hành vi người dùng)
    cho TẤT CẢ các tiêu đề sản phẩm được cung cấp (dạng list hoặc chuỗi nhiều dòng).
    """
    def log(msg):
        print(f"[Gemini Tầng 2] {msg}")
        if status_cb:
            status_cb(msg)
            
    if not api_key:
        api_key = ""
        
    if isinstance(shopee_product_titles, str):
        titles = [t.strip() for t in shopee_product_titles.split("\n") if t.strip()]
    elif isinstance(shopee_product_titles, list):
        titles = [str(t).strip() for t in shopee_product_titles if str(t).strip()]
    else:
        titles = []
        
    if not titles:
        return []

    log(f"Đang xử lý sinh từ khóa Tầng 2 cho {len(titles)} tiêu đề sản phẩm...")
    
    all_tier2_keywords = []
    
    # Mỗi tiêu đề luôn sinh đúng 10 từ khóa: 1 đầu vào -> 10, 10 đầu vào -> 100.
    count_per_title = 10
    fallback_suffixes = [
        " trị mụn", " bôi da", " tốt nhất", " hiệu quả", " chính hãng",
        " an toàn", " cho bé", " giá rẻ", " cao cấp", " tốt không"
    ]

    for idx, title in enumerate(titles):
        log(f"-> Phân tích tiêu đề [{idx+1}/{len(titles)}]: \"{title[:45]}...\"")
        
        prompt = (
            "Bạn là một Engine Phân tích Hành vi E-commerce (Shopee) xử lý ngôn ngữ tự nhiên.\n"
            f"Đầu vào của bạn là một tiêu đề sản phẩm thô trên Shopee: \"{title}\"\n\n"
            "Hãy thực hiện NGẦM quá trình suy luận (Chain of Thought) theo 4 bước sau, NHƯNG KHÔNG IN RA QUÁ TRÌNH NÀY:\n\n"
            "1. Bóc tách & Làm sạch (Parsing): Lọc bỏ các từ khóa rác/giật tít (như \"chính hãng\", \"freeship\", \"giá rẻ\", \"tuýp\", \"gram\"). Xác định chính xác \"Lõi sản phẩm\" (Core Product) và hoạt chất/vật liệu chính.\n"
            "2. Truy vấn Tri thức (Contextualizing): Phân tích công dụng thực sự của lõi sản phẩm này là gì? Ai là người cần nó? Nó giải quyết bài toán nào trong đời sống thực?\n"
            "3. Suy luận Hành vi (Behavioral Mapping): Nếu một người đang gặp vấn đề mà sản phẩm này có thể giải quyết, nhưng họ CHƯA BIẾT tên sản phẩm, họ sẽ gõ gì vào ô tìm kiếm?\n"
            "   - Y tế/Mỹ phẩm: Ánh xạ thành triệu chứng, nỗi đau, khuyết điểm, tên gọi dân gian.\n"
            "   - Thời trang: Ánh xạ thành bối cảnh sử dụng, cách phối đồ, form dáng.\n"
            "   - Công nghệ/Gia dụng: Ánh xạ thành vấn đề cần khắc phục, nhu cầu tự động hóa, tính năng mong muốn.\n"
            "   - Ngành khác: Ánh xạ thành mục đích sử dụng cuối cùng.\n"
            f"4. Tổng hợp Từ khóa Tầng 2: Tạo ra danh sách đúng {count_per_title} cụm từ tìm kiếm tự nhiên, bình dân, đúng văn phong người dùng Việt Nam. Tuyệt đối KHÔNG chứa tên thương hiệu, KHÔNG chứa lại tên sản phẩm gốc.\n\n"
            "YÊU CẦU ĐẦU RA KỸ THUẬT (STRICT REQUIREMENT):\n"
            "- Kết quả trả về DUY NHẤT một mảng JSON hợp lệ (Valid JSON Array) chứa các chuỗi từ khóa.\n"
            "- KHÔNG hiển thị quá trình suy luận, KHÔNG dùng markdown định dạng khác ngoài mảng, KHÔNG sinh thêm bất kỳ ký tự hoặc câu chữ giao tiếp nào.\n\n"
            "Ví dụ Output mong đợi: [\"tu khoa 1\", \"tu khoa 2\", \"tu khoa 3\"]"
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
                
                generated_list = json.loads(text_response.strip())
                if isinstance(generated_list, list):
                    res = []
                    for item in generated_list:
                        keyword = str(item).strip()
                        if keyword and keyword not in res:
                            res.append(keyword)
                        if len(res) == count_per_title:
                            break

                    if len(res) < count_per_title:
                        words = [w for w in title.split() if len(w) > 2][:3]
                        base_kw = " ".join(words) if words else title
                        for suffix in fallback_suffixes:
                            fallback_keyword = f"{base_kw}{suffix}"
                            if fallback_keyword not in res:
                                res.append(fallback_keyword)
                            if len(res) == count_per_title:
                                break

                    all_tier2_keywords.extend(res)
                    log(f"   + Đã sinh đủ {len(res)} từ khóa Tầng 2 cho tiêu đề #{idx+1}")
                    continue
        except Exception as e:
            log(f"   + Lỗi gọi Gemini API cho tiêu đề #{idx+1} ({e}). Dùng luồng dự phòng...")
            
        # Luồng dự phòng nếu API lỗi: tự sinh từ khóa liên quan bằng các hậu tố phổ biến
        words = [w for w in title.split() if len(w) > 2][:3]
        base_kw = " ".join(words) if words else title
        for s in fallback_suffixes:
            all_tier2_keywords.append(f"{base_kw}{s}")

    log(f"✅ Đã sinh tổng cộng {len(all_tier2_keywords)} từ khóa Tầng 2 từ {len(titles)} tiêu đề sản phẩm!")
    return all_tier2_keywords

# BoxPhone Automation

Ứng dụng Windows điều khiển nhiều điện thoại Android qua ADB, hỗ trợ quy trình tự động hóa Shopee, TikTok, Facebook và báo cáo tiến trình theo thời gian thực qua Telegram.

Repository công khai không chứa token, ID Telegram, serial thiết bị, tên shop hoặc tên kênh thực tế. Toàn bộ thông tin vận hành phải được cấu hình cục bộ.

## Tính năng

### Shopee

- Chạy tuần tự hoặc song song trên nhiều thiết bị.
- Chọn ngẫu nhiên đúng một từ khóa cho mỗi lượt chạy.
- Ba chế độ từ khóa: gốc, mở rộng AI và tầng 2 AI.
- Mỗi đầu vào AI sinh đúng 10 từ khóa dự phòng khi API lỗi.
- Tự mở đúng ô tìm kiếm, tránh bấm nhầm giỏ hàng.
- Nếu đang ở trang chi tiết sản phẩm, ứng dụng dùng kính lúp hoặc quay lại Trang chủ trước khi tìm kiếm.
- Hỗ trợ danh sách shop dự phòng, phân cách bằng dấu phẩy.

### TikTok

- Trước workflow chính, mở Facebook và nuôi Feed ngẫu nhiên 3–5 phút.
- Quy trình ba bước: lướt Trang chủ, tìm từ khóa nhiệm vụ, tìm và vào kênh mục tiêu.
- Xóa sạch nội dung cũ trước khi nhập từ khóa mới.
- Mở clip trong kênh và chuyển clip theo khoảng thời gian cấu hình sẵn.
- Chạy tuần tự hoặc song song.

### Facebook

- Trước workflow chính, mở TikTok và xem video ngẫu nhiên 3–5 phút.
- Nuôi Feed, tìm từ khóa mồi và vào đúng Page mục tiêu.
- Hỗ trợ giao diện Facebook tiếng Việt và tiếng Anh.
- Tự phục hồi về Home nếu đang ở Story, Reels hoặc Page cũ.
- Chạy tuần tự hoặc song song.

### Telegram

- Báo cáo trạng thái theo thời gian thực cho từng thiết bị.
- Tách riêng thông báo Shopee, TikTok và Facebook.
- Bỏ lệnh tồn đọng đúng một lần khi bot khởi động.
- Hỗ trợ dừng tác vụ khẩn cấp.

## Yêu cầu

- Windows 10/11.
- Python 3.10 trở lên nếu chạy từ mã nguồn.
- ADB và thiết bị Android đã bật USB debugging.
- Bàn phím ADB tương thích với broadcast `XW_INPUT_B64` và `XW_CLEAR_TEXT`.
- Telegram Bot Token.
- Gemini API Key nếu muốn sinh từ khóa bằng AI.

## Chạy từ mã nguồn

```powershell
git clone https://github.com/datdtpl-maker/BoxphoneKH.git
cd BoxphoneKH
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python gui_app.py
```

## Cấu hình

### Đồng bộ lịch từ khóa Notion

Tool có nút **Quét từ khóa Notion** để nạp dữ liệu vào các ô Shopee, TikTok và
Facebook. Mỗi dòng Notion là một lịch chạy theo tuần và cần có các cột:

- `Tên lịch`, `Thời gian áp dụng`, `Đang áp dụng`, `Trạng thái bơm`
- `Shopee - Từ khóa gốc`
- `TikTok - Từ khóa nhiệm vụ`, `TikTok - Kênh mục tiêu`
- `Facebook - Từ khóa mồi`, `Facebook - Page mục tiêu`
- `Ghi chú Admin`, `Lần quét gần nhất`

Nhập `NOTION API TOKEN` và link database Notion (hoặc `DATA SOURCE ID`) trong khu vực cấu hình, bấm
**Lưu cấu hình**, sau đó bật các lịch cần dùng trên Notion. Khi quét, tool hiển
thị các nút theo `Tên lịch` của toàn bộ dòng đã bật `Đang áp dụng`; bấm lịch nào
thì bộ từ khóa của đúng dòng đó được nạp vào Shopee, TikTok và Facebook, đồng
thời `Trạng thái bơm` chuyển thành `Đang xử lý`. Khi kết thúc tuần, bấm
**Hoàn thành tuần** để đồng bộ trạng thái `Hoàn thành`; lịch đã hoàn thành sẽ
không xuất hiện trong các lần quét tiếp theo. Token chỉ được lưu trong `.env`
cục bộ và không được commit lên Git.

Tạo file `.env` tại thư mục gốc:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
ALLOWED_USER_IDS=123456789
GEMINI_API_KEY=your_gemini_api_key
SHOPEE_SHOP_NAMES=shop_a,shop_b
TIKTOK_TARGET_CHANNEL=kenh_tiktok_a,kenh_tiktok_b
FACEBOOK_TARGET_PAGE_EXACT=ten_page_day_du_tuy_chon
```

Không commit file `.env`. File này đã được khai báo trong `.gitignore`.

Các trường Telegram token, Admin ID, đường dẫn ADB và danh sách shop cũng có thể được cập nhật trong giao diện rồi bấm `LƯU`.
Danh sách kênh TikTok được phân cách bằng dấu phẩy; mỗi máy sẽ chọn ngẫu nhiên đúng một kênh để tìm kiếm.

## Bản chạy Windows

File thực thi được đặt tại:

```text
release/BoxPhoneControl.exe
```

Đây là bản portable, không cần tạo tag hoặc GitHub Release. Người dùng vẫn phải tự nhập cấu hình riêng trên máy của mình.

## Kiểm thử

```powershell
python -m unittest -v `
  test_telegram_task_routing.py `
  test_shopee_search_click.py `
  test_shopee_keyword_generation.py `
  test_tiktok_search_input.py `
  test_gui_tiktok_status.py `
  test_tiktok_telegram_tracker.py `
  test_facebook_automation.py `
  test_gui_facebook_status.py
```

## Bảo mật

- Không hardcode hoặc chia sẻ Telegram Bot Token và Gemini API Key.
- Không đưa serial thiết bị, ảnh chụp màn hình hoặc dữ liệu vận hành vào issue công khai.
- Nếu token từng bị commit, hãy thu hồi token cũ và tạo token mới.
- Chỉ sử dụng automation trên tài khoản, thiết bị và dữ liệu mà bạn có quyền quản lý.

## Lưu ý

Giao diện và tọa độ của ứng dụng bên thứ ba có thể thay đổi theo phiên bản. Nên kiểm thử trên một thiết bị trước khi chạy hàng loạt.

# BoxPhoneControl

Ứng dụng Windows chuyên nghiệp quản lý và điều khiển hàng loạt điện thoại Android (Boxphone) qua ADB. Hỗ trợ tự động hóa đa nền tảng: **Bơm Google Maps (qua Google Chrome)**, **TikTok**, **Facebook**, đồng bộ lịch từ khóa tự động từ **Notion** và điều khiển/báo cáo từ xa qua **Telegram Bot**.

---

## 🌟 Tính Năng Nổi Bật

### 1. Bơm Google Maps (Google Chrome Automation)
- **Mở Google Chrome**: Tự động xử lý popup điều khoản dịch vụ, đồng bộ tài khoản để sẵn sàng hoạt động.
- **Tự động nhận diện 3 giao diện Chrome**:
  - *Trang chủ Chrome (New Tab)*: Nhận diện ô "Tìm kiếm hoặc nhập URL" ở giữa màn hình.
  - *Trang kết quả tìm kiếm Google*: Tự động bấm nút **dấu X ❌** để xóa nhanh từ khóa cũ, xóa triệt để input và nhập từ khóa mới.
  - *Trang chi tiết địa điểm/profile*: Tự động nhận diện và bấm vào **thanh URL bar trên cùng (`y ~ 10%`)**, xóa URL cũ và nhập từ khóa mới.
- **Bộ gõ Tiếng Việt chuẩn**: Hỗ trợ gõ tiếng Việt có dấu chuẩn xác qua bộ gõ XwIME (`XW_INPUT_B64`) và xóa sạch input (`XW_CLEAR_TEXT` + phím Backspace).
- **Thuật toán tìm Profile thông minh**:
  - *Ưu tiên 1*: Quét và bấm ngay vào profile mục tiêu (*Nhà thuốc Khải Hoàn Skincare*) ngay trên trang kết quả đầu tiên.
  - *Ưu tiên 2*: Chỉ bấm *"Doanh nghiệp khác"* / *"Các địa điểm khác"* khi trang đầu chưa hiển thị profile mục tiêu.
  - *Ưu tiên 3*: Cuộn trang tự động để tìm tiếp profile nếu ở xa.
- **Lướt xem tự nhiên như người thật**: Ở lại profile trong **2 - 3 phút** (120s – 180s ngẫu nhiên), luân chuyển xem thông tin Tổng quan, Bài đánh giá và Hình ảnh.
- **Tương tác thực tế (Bước 5)**: Cuộn mượt về đầu trang profile và bấm ngẫu nhiên các nút hành động tròn (*Chỉ đường*, *Chia sẻ*, *Trang web*, *Lưu*, *Gọi điện*...) hoặc các tab tương tác.

### 2. Tự Động Hóa TikTok & Facebook
- Hỗ trợ đầy đủ các kịch bản nuôi kênh, tìm kiếm từ khóa mồi, xem clip/bài viết, dạo Newfeed và tương tác tự nhiên.
- Hỗ trợ các chế độ chạy: **Tuần tự**, **Song song**, **Thích ứng** và **Luân phiên máy**.

### 3. Đồng Bộ Lịch Từ Khóa Notion
- Tự động nạp danh sách từ khóa theo dõi từ cơ sở dữ liệu Notion:
  - `Google Maps - Từ khóa theo dõi`
  - `TikTok - Từ khóa nhiệm vụ`, `TikTok - Kênh mục tiêu`
  - `Facebook - Từ khóa mồi`, `Facebook - Page mục tiêu`
- Bốc ngẫu nhiên từ khóa theo danh sách phân tách bằng dấu phẩy.
- Nút **Hoàn thành tuần** tự động cập nhật trạng thái lên Notion.

### 4. Báo Cáo & Điều Khiển Qua Telegram
- Gửi thông báo và log tiến trình realtime đến nhóm/kênh Telegram riêng.
- Hỗ trợ các lệnh điều khiển từ xa: `/maps`, `/tiktok`, `/facebook`, `/status`, `/stop`...

---

## ⚙️ Cấu Hình Môi Trường (.env)

Tạo file `.env` cùng thư mục với file chạy `BoxPhoneControl.exe` hoặc sử dụng tính năng **Import .env** trên giao diện:

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=
TELEGRAM_NOTIFICATIONS_ENABLED=1
ALLOWED_USER_IDS=

# Đường dẫn ADB (Mặc định dùng ADB của Xiaowei hoặc Android SDK)
ADB_PATH=C:\Program Files (x86)\xiaowei\tools\adb.exe

# Cấu hình Google Maps
GOOGLE_MAPS_TARGET_NAME=Nhà thuốc Khải Hoàn Skincare
GOOGLE_MAPS_LOCATION_TEXT=Phan Thiết, Lâm Đồng
GOOGLE_MAPS_DWELL_MIN=120
GOOGLE_MAPS_DWELL_MAX=180

# Cấu hình Notion API
NOTION_API_TOKEN=
NOTION_DATA_SOURCE_ID=

# Cấu hình TikTok & Facebook
TIKTOK_TARGET_CHANNEL=
FACEBOOK_TARGET_PAGE_EXACT=
```

> ⚠️ **Lưu ý bảo mật**: Tuyệt đối không chia sẻ hoặc đẩy file `.env` chứa token/khóa bí mật lên các kho lưu trữ công khai.

---

## 🚀 Hướng Dẫn Sử Dụng

### Cách 1: Chạy trực tiếp từ file EXE (Portable)
Tải và chạy file `BoxPhoneControl.exe` tại thư mục `release/` (hoặc thư mục gốc dự án) mà không cần cài đặt môi trường Python.

### Cách 2: Chạy từ mã nguồn Python

1. **Cài đặt thư viện phụ thuộc**:
   ```powershell
   python -m pip install -r requirements.txt
   ```

2. **Khởi chạy ứng dụng**:
   ```powershell
   python gui_app.py
   ```

---

## 🧪 Kiểm Thử & Đóng Gói (Build)

### Chạy Unit Test:
```powershell
python -m unittest discover -p "test_*.py"
```

### Đóng gói file chạy EXE:
```powershell
python build_exe.py
```
File thực thi sau khi đóng gói sẽ được đặt tại `BoxPhoneControl.exe` và `release/BoxPhoneControl.exe`.

---

## 📄 Bản Quyền & Giấy Phép
Dự án được phát triển và tối ưu bởi **Khải Hoàn Skincare**.

# Box Phone Shopee Automation Bot 🤖📱

Hệ thống tự động hóa điều khiển hàng loạt điện thoại Android (Box Phone) thông qua Telegram Bot để thực hiện quy trình tìm kiếm sản phẩm, giải captcha thông minh bằng OpenCV, tìm kiếm và tương tác tự nhiên với shop có địa điểm cụ thể trên ứng dụng Shopee.

## 🌟 Tính Năng Nổi Bật

- **Điều khiển qua Telegram:** Hỗ trợ ra lệnh bằng ngôn ngữ tự nhiên tiếng Việt cho toàn bộ 20 máy cùng lúc hoặc chỉ định riêng lẻ từng máy.
- **Tự động hóa thông minh (Shopee Search & Click):**
  - Tự động tắt xoay màn hình và khóa hướng dọc thiết bị khi bắt đầu quy trình.
  - Nhập liệu tự nhiên mô phỏng người thật (gõ từng chữ với độ trễ ngẫu nhiên 0.2s - 0.4s).
  - Tự động phân tích XML cấu trúc giao diện (`uiautomator dump`) để tìm nhãn **"Tỉnh Lâm Đồng"** hoặc **"Lâm Đồng"** trên danh sách sản phẩm.
  - Tự động click mở sản phẩm và cuộn lướt xem tự nhiên (mô phỏng đọc thông tin) trong thời gian ngẫu nhiên từ 10 - 20 giây.
- **Giải quyết Captcha tự động bằng OpenCV:**
  - Tự động chụp ảnh màn hình và xử lý lọc Canny, Gaussian Blur để tìm khoảng cách mảnh ghép của slider captcha.
  - Giả lập thao tác vuốt trượt (`swipe`) có sai số quỹ đạo ngẫu nhiên để vượt qua hệ thống kiểm tra bot.
  - Nếu giải thất bại 3 lần, hệ thống tự động gửi ảnh chụp màn hình bị kẹt Captcha về Telegram kèm cảnh báo để admin xử lý thủ công.
- **Chế độ chạy tuần tự thông minh:**
  - Hỗ trợ chạy máy-qua-máy lần lượt với thời gian nghỉ ngẫu nhiên (60 - 90 giây) để ngăn chặn việc quét trùng IP/hành vi của hệ thống Shopee.
- **Bảo mật tuyệt đối:** Lưu trữ admin truy cập đầu tiên làm quản trị viên duy nhất, tự động chặn toàn bộ các tin nhắn từ người lạ.

## 🛠️ Yêu Cầu Hệ Thống

- **Hệ điều hành:** Windows (khuyên dùng chạy trên máy chủ cài đặt phần mềm xiaowei).
- **Python:** Phiên bản 3.8 trở lên.
- **ADB:** Cần cài đặt ADB tools (mặc định trỏ đến công cụ ADB của phần mềm xiaowei).
- **Thiết bị:** 20 máy Android đã bật chế độ nhà phát triển (Developer Options) và kết nối qua cổng USB. Bàn phím ảo `XwIME` cần được cài đặt trên điện thoại để nhận dữ liệu gõ tiếng Việt.

## 📦 Hướng Dẫn Cài Đặt

1. **Tải mã nguồn về máy tính:**
   ```bash
   git clone https://github.com/datdtpl-maker/BoxphoneKH.git
   cd BoxphoneKH
   ```

2. **Cài đặt các thư viện cần thiết:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Cấu hình biến môi trường (`.env`):**
   Tạo file `.env` ở thư mục gốc của dự án với nội dung:
   ```env
   TELEGRAM_BOT_TOKEN=8659016197:AAGExbDqWKRQUuxo-d8NvNINNMP3fWxc_eQ
   ALLOWED_USER_IDS=
   ```
   *(Khi bạn khởi chạy bot lần đầu tiên, tài khoản Telegram nào gửi tin nhắn `/start` đầu tiên sẽ được ghi nhận làm Admin duy nhất và lưu trực tiếp vào biến `ALLOWED_USER_IDS`)*.

4. **Kiểm tra cấu hình đường dẫn ADB (`config.py`):**
   Mặc định đường dẫn ADB được trỏ đến phần mềm xiaowei:
   ```python
   ADB_PATH = r"C:\Program Files (x86)\xiaowei\tools\adb.exe"
   ```
   Bạn có thể chỉnh sửa lại đường dẫn này nếu cài đặt phần mềm ở thư mục khác.

## 🚀 Hướng Dẫn Sử Dụng Bot Telegram

Gõ lệnh `/start` hoặc `/help` trong bot Telegram để xem hướng dẫn trực tiếp.

### 🎯 1. Quy Trình Quét Shop Lâm Đồng
- **Chạy lần lượt từng máy (Nên dùng để tránh quét IP):**
  - Lệnh: `tìm tuần tự lâm đồng [từ khóa]` hoặc `tìm lần lượt lâm đồng [từ khóa]`
  - *Ví dụ:* `tìm tuần tự lâm đồng deriva` (nghỉ 60-90 giây ngẫu nhiên giữa các máy).
  - ⏹️ Để dừng tiến trình tuần tự này, gõ: `dừng` hoặc `dừng chạy`.
- **Chạy song song tất cả các máy cùng lúc:**
  - Lệnh: `tìm lâm đồng [từ khóa]`
  - *Ví dụ:* `tìm lâm đồng deriva`.
- **Chạy trên 1 máy cụ thể:**
  - Lệnh: `máy [số] tìm lâm đồng [từ khóa]`
  - *Ví dụ:* `máy 5 tìm lâm đồng deriva`.

### 📸 2. Kiểm Tra & Giám Sát
- **Chụp ảnh màn hình:**
  - Lệnh: `chụp màn hình máy [số]` hoặc `chụp ảnh máy [số]`
  - *Ví dụ:* `chụp màn hình máy 12`.
- **Kiểm tra kết nối thiết bị:**
  - Lệnh: `trạng thái` hoặc `danh sách máy` để xem danh sách các ID máy đang kết nối với hệ thống.

### ⚙️ 3. Phím Điều Khiển Nhanh
- **Quay lại:** `quay lại` (hoặc `quay lại máy 5`).
- **Màn hình chính (Home):** `trang chủ` (hoặc `trang chủ máy 12`).
- **Tắt xoay màn hình:** `tắt xoay` (hoặc `tắt xoay máy 5`).
- **Shopee:** `mở shopee` / `đóng shopee` (cho tất cả hoặc cho máy cụ thể).

---

*Dự án được xây dựng và phát triển chuyên nghiệp, phục vụ quản trị và tối ưu hóa vận hành Box Phone.*

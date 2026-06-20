# Box Phone Shopee Automation Bot - Khải Hoàn Edition 🤖📱

Hệ thống tự động hóa điều khiển hàng loạt điện thoại Android (Box Phone) thông qua Telegram Bot chuyên nghiệp dành cho hệ thống **BOX PHONE - SHOPEE KHẢI HOÀN**. Dự án tích hợp các kịch bản tìm kiếm sản phẩm thông minh, tự động giải Captcha bằng OpenCV, đo độ phân giải động, và đặc biệt là giả lập hành vi người dùng thật 100% để tối ưu hóa SEO sản phẩm & cửa hàng.

---

## 🌟 Tính Năng Nổi Bật

### 1. Giả Lập Hành Vi Người Dùng Thật 100% (Human Simulation)
- **Giả lập quỹ đạo vuốt cong (`swipe_curved`):** Tránh các chuyển động thẳng tắp cơ học của bot. Đường vuốt dọc được chia nhỏ thành các đoạn vuốt ngắn nối tiếp nhau với điểm gãy ngẫu nhiên lệch sang trái hoặc phải để mô phỏng chính xác hướng vuốt cong tự nhiên của ngón tay người.
- **Vuốt xem album ảnh (Carousel Swipe):** Khi mở sản phẩm, bot tự động vuốt ngang ảnh đại diện từ phải qua trái 1-2 lần ở vùng 30% trên cùng để chuyển xem các góc ảnh khác nhau.
- **Tương tác ngẫu nhiên bỏ giỏ hàng (Intent Signal):** Tỷ lệ ngẫu nhiên **15%** bot sẽ nhấn nút `"Thêm vào giỏ hàng"`, chọn ngẫu nhiên phân loại (màu sắc/size) trên hộp thoại rồi bấm Back đóng lại. Hành động này tạo chỉ số tương tác và chuyển đổi giả lập mạnh mẽ trên máy chủ Shopee.
- **Tự động vào "Xem Shop" & dạo cửa hàng:** Tự động tìm và click nút `"Xem Shop"` của Khải Hoàn trong trang chi tiết, chuyển hướng sang trang chủ Shop, lướt dạo ngẫu nhiên trong 10-15 giây để tăng traffic toàn diện trước khi quay trở lại.

### 2. Tối Ưu Tương Thích & Điều Khiển Thiết Bị
- **Đo kích thước màn hình động:** Bot tự động lấy độ phân giải thực tế bằng lệnh `wm size` trước khi thực thi để tính toán tọa độ theo tỷ lệ phần trăm (phù hợp 100% với các đời Samsung 1080p, 1440p hoặc 720p).
- **Nhập liệu tự nhiên:** Thay vì dán văn bản ngay lập tức, bot mô phỏng gõ phím tiếng Việt từng từ thông qua IME ảo `XwIME` với độ trễ ngẫu nhiên từ 0.2s - 0.4s.
- **Lướt xem sản phẩm sâu:** Tăng thời gian lướt ngẫu nhiên lên **15 - 30 giây**, kết hợp cuộn xuống, dừng đọc ngẫu nhiên (4-8s) ở các phần mô tả/review, thỉnh thoảng cuộn ngược lên trên.

### 3. Tự Động Giải Captcha Bằng OpenCV
- Tự động chụp màn hình, phân tích thuật toán Canny, Gaussian Blur để phát hiện khoảng cách mảnh khuyết của slider captcha.
- Giả lập thao tác kéo trượt có thời gian kéo và độ nghiêng ngẫu nhiên.
- Tự động chụp màn hình gửi lên Telegram cảnh báo admin nếu giải captcha thất bại quá 3 lần.

### 4. Cơ Chế Dừng Khẩn Cấp Thông Minh
- **Nút bấm Inline tiện lợi:** Gắn trực tiếp dưới tin nhắn tiến trình trên Telegram chat. Khi kết thúc hoặc bị hủy, nút sẽ tự động biến mất giúp giao diện luôn sạch sẽ.
- **Lệnh điều khiển:** Hỗ trợ ra lệnh dừng nhanh bằng tin nhắn `/stop`, `dừng`, `stop` hoặc `dừng chạy`.

---

## 🛠️ Yêu Cầu Hệ Thống

- **Hệ điều hành:** Windows (chạy trên máy chủ có cài đặt phần mềm xiaowei).
- **Python:** Phiên bản 3.8 trở lên.
- **ADB:** Trỏ đến công cụ ADB của phần mềm xiaowei.
- **Thiết bị:** Các điện thoại Android đã bật gỡ lỗi USB và cấu hình bàn phím ảo `XwIME` làm mặc định.

---

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
   TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
   ALLOWED_USER_IDS=
   ```
   *(Tài khoản Telegram đầu tiên nhắn tin `/start` cho bot sẽ được đăng ký làm Admin duy nhất).*

4. **Kiểm tra cấu hình đường dẫn ADB (`config.py`):**
   Mặc định đường dẫn ADB được trỏ đến thư mục cài đặt xiaowei:
   ```python
   ADB_PATH = r"C:\Program Files (x86)\xiaowei\tools\adb.exe"
   ```

---

## 🚀 Hướng Dẫn Sử Dụng Bot Telegram

Gửi lệnh `/start` hoặc `/help` trong bot Telegram để lấy hướng dẫn sử dụng nhanh:

### 🎯 1. Quy Trình Quét Shop Lâm Đồng
- **Chạy lần lượt từng máy (Nghỉ 60-90s giữa các máy - Rất khuyên dùng để an toàn IP):**
  - Lệnh: `tìm tuần tự lâm đồng [từ khóa 1, từ khóa 2, ...]` (phân cách bằng dấu phẩy `,`, `;` hoặc `|`).
  - *Ví dụ:* `tìm tuần tự lâm đồng deriva, son môi, kem chống nắng`.
- **Chạy song song tất cả các máy cùng lúc:**
  - Lệnh: `tìm lâm đồng [từ khóa 1, từ khóa 2, ...]`
- **Chạy trên 1 máy cụ thể (ví dụ máy 5):**
  - Lệnh: `máy 5 tìm lâm đồng [từ khóa 1, từ khóa 2, ...]`

⏹️ **Dừng khẩn cấp:**
- Bấm trực tiếp nút `🛑 DỪNG CHẠY KHẨN CẤP` dạng Inline hiển thị dưới tin nhắn tiến trình.
- Hoặc gõ lệnh `/stop`, hoặc nhắn tin chữ `dừng`, `stop`.

### 📸 2. Kiểm Tra & Giám Sát
- **Chụp ảnh màn hình kiểm tra máy:**
  - Lệnh: `chụp màn hình máy [số]` (Ví dụ: `chụp màn hình máy 12`).
- **Kiểm tra kết nối thiết bị:**
  - Lệnh: `trạng thái` hoặc `danh sách máy` để liệt kê các ID máy đang kết nối.

### ⚙️ 3. Phím Điều Khiển Nhanh
- **Quay lại:** `quay lại` (hoặc `quay lại máy 5`).
- **Màn hình chính (Home):** `trang chủ` (hoặc `trang chủ máy 12`).
- **Tắt xoay màn hình:** `tắt xoay` (hoặc `tắt xoay máy 5`).
- **Ứng dụng Shopee:** `mở shopee` / `đóng shopee` (cho toàn bộ hoặc máy chỉ định).

---

*Hệ thống được phát triển chuyên nghiệp, phục vụ tối ưu hóa vận hành và SEO cho gian hàng Shopee Khải Hoàn.*

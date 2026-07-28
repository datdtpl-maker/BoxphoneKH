# HANDOFF DOCUMENTATION - KHẢI HOÀN AUTOMATION SYSTEM (BOX PHONE CONTROL)

## 📌 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)
- **Tên hệ thống**: Khải Hoàn Automation System (Box Phone Control Pro)
- **Mô tả**: Phần mềm Windows GUI và Bot Telegram điều khiển dàn điện thoại Android (Box Phone) qua ADB để tự động hóa tác vụ Shopee và Bơm TikTok 3 Bước.
- **Mã nguồn**: Python 3.14, CustomTkinter GUI (`gui_app.py`), ADB Automation (`adb_controller.py`), Telegram Bot (`main.py`), Config (`config.py`).
- **Thư mục dự án**: `C:\Users\datdt\.gemini\antigravity\scratch\phone_telegram_bot`
- **GitHub Repository**: `https://github.com/datdtpl-maker/BoxphoneKH.git` (Branch: `main`)
- **File thực thi trên Windows**: `BoxPhoneControl.exe` (Được đóng gói bằng `python build_exe.py` qua PyInstaller).

---

## 📌 2. KIẾN TRÚC MÃ NGUỒN & CẤU TRÚC FILE (FILE ARCHITECTURE)

```
phone_telegram_bot/
├── gui_app.py           # Giao diện CustomTkinter (Layout 2 cột Shopee | TikTok, Console Log ở đỉnh)
├── adb_controller.py    # Lớp ADBController điều khiển thiết bị Android qua lệnh shell ADB
├── main.py              # Xử lý Bot Telegram (/shopee, /tiktok, /start) và luồng chạy Tuần Tự/Song Song
├── config.py            # Cấu hình biến môi trường (.env), từ khóa mặc định và Gemini AI API
├── build_exe.py         # Script tự động hóa PyInstaller để đóng gói thành 1 file BoxPhoneControl.exe
├── app_icon.ico         # Icon ứng dụng
└── handoff.md           # Tài liệu bàn giao kỹ thuật (File này)
```

---

## 📌 3. CHI TIẾT CÁC TÍNH NĂNG ĐÃ TRIỂN KHAI (IMPLEMENTED FEATURES)

### A. GIAO DIỆN PHẦN MỀM WINDOWS (`gui_app.py`):
1. **Khung Nhật Ký Hoạt Động (Real-time Console Log)**:
   - Được đưa lên **TRÊN CÙNG** phần mềm (`self.log_card`), chiếm toàn bộ chiều ngang để theo dõi log ADB thời gian thực.
   - Bắt toàn bộ `sys.stdout` và `sys.stderr` qua `ConsoleRedirector`.
2. **Khung Điều Khiển Shopee (Cột Trái - 50%)**:
   - Từ khóa chính (Mỗi dòng 1 từ khóa).
   - Chế độ: Gốc (Không AI) / Mở rộng (AI) / Tầng 2 (AI sinh).
   - Nút Sinh từ khóa Tầng 1 & Tầng 2 qua Gemini AI.
   - Ô chọn máy chạy Shopee (Ví dụ: `1-5,10` hoặc trống = Tất cả).
   - Nút Chạy Tuần Tự / Song Song Shopee.
   - Nút **`🛑 DỪNG SHOPEE KHẨN CẤP`**.
3. **Khung Điều Khiển TikTok (Cột Phải - 50%)**:
   - Từ khóa mồi kênh (Phẩy cách, mặc định: `skincare, trị mụn, nặn mụn, chăm sóc da`).
   - Tên Kênh TikTok mục tiêu (Mặc định: `Khải Hoàn Skincare PT`).
   - Thời gian lướt video (Giây Min - Max, mặc định: `5` - `10`).
   - Ô chọn máy chạy TikTok riêng biệt (`self.ent_tt_selection`).
   - Nút Chạy Tuần Tự / Song Song TikTok.
   - Nút **`🛑 DỪNG TIKTOK KHẨN CẤP`**.
4. **Loại bỏ Hoàn toàn Bảng Quản Lý Thiết Bị cũ**:
   - Đã gỡ bỏ toàn bộ lưới card 20 máy rườm rà phía bên phải.

---

### B. QUY TRÌNH BƠM TIKTOK 3 BƯỚC (`adb_controller.py` -> `tiktok_automation_workflow`):
1. **Bước 1 (Dạo Feed Trang Chủ)**:
   - Khởi chạy TikTok (`com.ss.android.ugc.trill` hoặc `com.zhiliaoapp.musically`).
   - Tự động từ chối Bảng hỏi quyền vị trí Android (`dismiss_tiktok_location_popup`).
   - Vuốt 3-6 video trên For You feed, dừng xem ngẫu nhiên 1-3 video (thời gian xem từ `min_delay` đến `max_delay` giây).
2. **Bước 2 (Gõ Từ Khóa Mồi Kênh & Lướt Context Feed)**:
   - Bấm Kính lúp / Thanh tìm kiếm top header (`find_and_click_tiktok_search`).
   - Xóa sạch từ khóa cũ (`clear_tiktok_search_input`).
   - Gõ 1 từ khóa ngẫu nhiên từ danh sách từ khóa mồi (`input_text_naturally`).
   - Bấm Enter & Click nút `Search` màu đỏ ở góc trên bên phải.
   - Vuốt lướt danh sách kết quả 15-25 giây để tạo lịch sử quan tâm chủ đề cho profile.
3. **Bước 3 (Xóa Sạch Từ Khóa Mồi & Tìm Kênh Mục Tiêu)**:
   - Bấm ô tìm kiếm ở trên cùng.
   - **XÓA SẠCH 100%** từ khóa mồi cũ ở Bước 2 (`clear_tiktok_search_input`).
   - Gõ tên kênh mục tiêu (`Khải Hoàn Skincare PT`).
   - Bấm Enter & Click nút `Search` màu đỏ.
   - Click thẻ Kênh cá nhân (`find_and_click_tiktok_channel`), vào trang cá nhân -> bấm ngẫu nhiên 1-2 video trong lưới để lướt xem tương tác.

---

## 📌 4. VẤN ĐỀ KỸ THUẬT CẦN CODEX TIẾP TỤC TỐI ƯU (OUTSTANDING ISSUES TO FIX)

### ⚠️ Vấn đề focus ô nhập liệu TikTok & Gõ từ khóa từ App:
- **Hiện trạng**: Trên một số giao diện TikTok / độ phân giải màn hình khác nhau, khi bấm ô tìm kiếm `(x=45% width, y=5.5% height)`, ô tìm kiếm không ăn focus bàn phím hoặc bị dán các thẻ từ khóa xu hướng gợi ý của TikTok (`Sun Spa`, `Moji Spa`, `ngocnguyenspa`...).
- **Cơ chế gõ chữ hiện tại**:
  - `remove_vietnamese_accents(text)`: Chuyển tiếng Việt thành không dấu.
  - `input_text_naturally(device_id, text)`:
    1. Broadcast Base64 qua XwIME (`XW_INPUT_B64`).
    2. Gõ từng từ qua `adb shell input text <word>` + phím cách Space (Keyevent 62).
  - `clear_tiktok_search_input(device_id)`: Tap các tọa độ x `78%, 81%, 84%`, dump XML UI tìm nút Clear, gửi 50 keyevent backspace (`67`).
- **Nhiệm vụ cho Codex**:
  1. Kiểm tra lại việc kích hoạt focus con trỏ văn bản vào đúng ô input `EditText` của TikTok trước khi phát lệnh gõ text.
  2. Đảm bảo từ khóa bạn nhập ở phần mềm Windows (`ent_tt_seed`) được gõ chuẩn xác 100% vào ô tìm kiếm mà không bị nhảy dính thẻ gợi ý xu hướng của TikTok.

---

## 📌 5. HƯỚNG DẪN CHẠY VÀ BUILD (HOW TO RUN & BUILD)

1. **Chạy phần mềm GUI**:
   ```powershell
   python gui_app.py
   ```
2. **Chạy Bot Telegram**:
   ```powershell
   python main.py
   ```
3. **Đóng gói file EXE**:
   ```powershell
   python build_exe.py
   ```
4. **Đẩy code lên GitHub**:
   ```powershell
   git add .
   git commit -m "update: ..."
   git push origin main
   ```

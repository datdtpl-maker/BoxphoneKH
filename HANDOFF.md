# ==============================================================================
# BOXPHONECONTROL — PROJECT HANDOFF & TRANSFER GUIDE
# ==============================================================================

> **Dành cho AI Assistant / Lập trình viên tiếp quản dự án trên máy mới.**
> Tài liệu này chứa toàn bộ bối cảnh kiến trúc, quy tắc bất biến, hướng dẫn cài đặt từ đầu, quy trình kiểm thử và vận hành hệ thống điều khiển Box Phone 40 máy Android.

---

## 📋 PROMPT DÁN TRỰC TIẾP CHO AI ASSISTANT MỚI

*Khi chuyển sang máy mới, hãy copy toàn bộ đoạn prompt bên dưới dán cho AI Assistant (Cursor, Claude, Gemini, ChatGPT):*

```markdown
Bạn là Kỹ sư Tự động hóa cấp cao tiếp quản dự án BoxPhoneControl (Quản lý và điều phối Box 40 điện thoại Android qua ADB).

Dưới đây là thông tin và quy tắc tối thượng của dự án bạn BẮT BUỘC phải tuân thủ:
1. KIẾN TRÚC DỰ ÁN:
   - Ngôn ngữ: Python 3.12 64-bit trên Windows 10/11.
   - Giao diện: `gui_app.py` (CustomTkinter) hỗ trợ 4 chế độ: Tuần tự, Song song, Thích ứng (Adaptive Queue), Kết hợp (Combined 2 module ngẫu nhiên theo máy).
   - Điều khiển thiết bị: `adb_controller.py` qua ADB đa cổng (5037, 5038), hỗ trợ 40 máy đồng thời với độ trễ thấp và bộ nhớ đệm kết nối.
   - Tọa độ & Phân giải: Đa màn hình (1080x1920, 1440x2560...), tuyệt đối KHÔNG hardcode tọa độ pixel tĩnh cho nội dung động. Dùng UI Automator DOM (`ui_automator_dom.py`) và tỷ lệ phần trăm màn hình.
   - Bot & Đồng bộ: `main.py` (Telegram bot dashboard thời gian thực), `notion_keyword_sync.py`, `notion_comment_sync.py` (Notion API).
   - Đóng gói: `build_exe.py` (PyInstaller onedir) và Inno Setup 6 (`build_installer.py` -> `release\BoxPhoneControl-Setup.exe`).

2. QUY TẮC BẤT BIẾN (STRICT INVARIANTS):
   - MODULE TIKTOK ĐÃ ĐÓNG BĂNG: TikTok đang ở trạng thái ổn định tuyệt đối (baseline `BoxPhoneControl 1.0.16`). KHÔNG được sửa code/config/UI/test TikTok trừ khi người dùng yêu cầu rõ ràng. Mọi thay đổi đều phải vượt qua guard `python verify_tiktok_freeze.py`.
   - MODULE FACEBOOK (TARGET LOCK CHẶT CHẼ): Bắt buộc kiểm tra đúng Page Header, từ khóa thương hiệu (`khai` trước `hoan`), từ chối dứt khoát thương hiệu ngoại lai (sony, samsung, apple, xiaomi, honda, toyota...). Bỏ qua node EditText khi kiểm tra profile để tránh bắt nhầm truy vấn còn lưu trong thanh search. Tự động thoát (Back) nếu mở nhầm trang.
   - CƠ CHẾ CHỊU LỖI (FAULT-TOLERANCE / AUTO-RETRY): Cả Facebook và TikTok đều có cơ chế thử lại (tối đa 2 lượt) với khả năng tự phục hồi sạch sẽ (bấm Back, đóng popup chặn "Báo cáo / Report", dọn dẹp trạng thái) trước khi thử lại.
   - TOÀN BỘ UNIT TESTS (325+ tests) PHẢI PASS 100%: Trước khi hoàn thành bất kỳ task nào, lệnh `python -m unittest discover -s . -p "test_*.py"` phải đạt OK không có lỗi.

Hãy đọc kỹ file HANDOFF.md, .env.example và TIKTOK_FROZEN.md trong repo để nắm chi tiết. Hãy sẵn sàng nhận yêu cầu tiếp theo!
```

---

## 🏗️ 1. TỔNG QUAN HỆ THỐNG & CẤU TRÚC FILE

```
E:\Boxphone KH\ (hoặc thư mục clone trên máy mới)
│
├── adb_controller.py           # Core Driver điều khiển 40 máy Android qua ADB đa cổng
├── gui_app.py                  # Giao diện Desktop CustomTkinter (Tuần tự, Song song, Thích ứng, Kết hợp)
├── main.py                     # Telegram Bot điều khiển & Dashboard tiến trình thời gian thực
├── config.py                   # Cấu hình trung tâm, đọc biến môi trường từ .env
├── ui_automator_dom.py         # Parser DOM UI Automator XML cho tìm kiếm card, nút bấm thông minh
├── comment_controller.py       # Quản lý vi tương tác bình luận & gieo mầm comment
├── notion_keyword_sync.py      # Tự động nạp lịch chạy và từ khóa từ Notion Database
├── notion_comment_sync.py      # Đồng bộ kịch bản bình luận từ Notion
├── adaptive_scheduler.py       # Bộ điều phối hàng đợi thích ứng phân phối tải theo từng thiết bị
│
├── verify_tiktok_freeze.py     # Guard kiểm tra tính toàn vẹn AST của module TikTok đã đóng băng
├── tiktok_freeze_manifest.json # Hash manifest AST các hàm TikTok được bảo vệ
├── TIKTOK_FROZEN.md            # Quy ước đóng băng module TikTok
│
├── build_exe.py                # Script build PyInstaller onedir tối ưu tốc độ khởi động
├── build_installer.py          # Script đóng gói bộ cài Windows Inno Setup 6
├── installer.iss               # Kịch bản Inno Setup cấu hình đường dẫn cài đặt & shortcut
│
├── requirements.txt            # Danh sách thư viện Python phụ thuộc
├── .env.example                # File mẫu cấu hình biến môi trường
├── .gitignore                  # Cấu hình bỏ qua file rác, cache, credentials
└── test_*.py                   # 25+ file test bao phủ toàn bộ chức năng (325+ unit tests)
```

---

## ⚙️ 2. HƯỚNG DẪN CÀI ĐẶT TRÊN MÁY MỚI (STEP-BY-STEP)

### Bước 1: Cài đặt công cụ nền tảng
1. **Python 3.12 (64-bit):**
   - Tải từ [python.org](https://www.python.org/downloads/).
   - ⚠️ **LƯU Ý:** Tích chọn `"Add Python to PATH"` trong trình cài đặt.
2. **Git for Windows:**
   - Tải từ [git-scm.com](https://git-scm.com/).
3. **Inno Setup 6 (Nếu cần build bộ cài installer):**
   - Tải và cài đặt từ [jrsoftware.org](https://jrsoftware.org/isdl.php).

### Bước 2: Clone source code từ GitHub
Mở PowerShell hoặc Command Prompt:
```powershell
git clone https://github.com/datdtpl-maker/BoxphoneKH.git
cd BoxphoneKH
```

### Bước 3: Cài đặt thư viện Python
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Bước 4: Thiết lập cấu hình môi trường (.env)
1. Tạo file `.env` từ file mẫu `.env.example`:
```powershell
Copy-Item .env.example .env
```
2. Mở file `.env` và điền các thông tin:
   - `ADB_PATH`: Đường dẫn `adb.exe` trên máy mới (vd: `C:\Program Files (x86)\xiaowei_android\tools\adb.exe` hoặc thư mục platform-tools).
   - `ADB_PORTS`: `5037,5038` (hỗ trợ Box 40 máy).
   - `TELEGRAM_BOT_TOKEN`: Token bot Telegram quản lý (nếu có).
   - `NOTION_API_TOKEN`: Token tích hợp Notion (nếu có).
   - Các từ khóa mục tiêu TikTok & Facebook (đã có sẵn giá trị mặc định chuẩn y khoa Phan Thiết).

### Bước 5: Kiểm tra kết nối thiết bị Android
Cắm Box Phone vào máy tính qua cổng USB/Hub, mở phần mềm điều khiển Box (như Xiaowei) hoặc chạy lệnh:
```powershell
& "C:\Program Files (x86)\xiaowei_android\tools\adb.exe" devices
```
Đảm bảo tất cả thiết bị hiển thị ở trạng thái `device` (không phải `offline` hay `unauthorized`).

---

## 🧪 3. QUY TRÌNH KIỂM THỬ BẮT BUỘC TRƯỚC KHI BÀN GIAO

Mỗi khi chỉnh sửa mã nguồn, **BẮT BUỘC** phải chạy 2 lệnh sau:

### 1. Kiểm tra Freeze Guard TikTok:
```powershell
python verify_tiktok_freeze.py
```
👉 Kết quả hợp lệ: `TikTok freeze guard: OK`.

### 2. Chạy toàn bộ 325+ Unit Tests:
```powershell
python -m unittest discover -s . -p "test_*.py"
```
👉 Kết quả hợp lệ: `Ran 325 tests in ~80s ... OK` (0 failures, 0 errors).

---

## 🚀 4. VẬN HÀNH & ĐÓNG GÓI ỨNG DỤNG

### Chạy ứng dụng từ mã nguồn (Phát triển / Debug):
```powershell
python gui_app.py
```
- Giao diện CustomTkinter hiện đại sẽ khởi động.
- Có thể chọn máy theo dải số (ví dụ: `1-10`, `1,3,5-8`, hoặc để trống để chọn toàn bộ máy đang online).
- Nút bấm trực quan: Bơm TikTok, Bơm Facebook, Chạy thích ứng, Chạy kết hợp 2 nền tảng, Tắt xoay màn hình, Tắt âm lượng, Dừng khẩn cấp.

### Chạy Bot Telegram độc lập dưới nền (Headless):
```powershell
python main.py
```

### Đóng gói ứng dụng (.EXE & Setup Installer):
```powershell
python build_exe.py
```
- Tự động dọn dẹp thư mục build cũ.
- Biên dịch PyInstaller ở chế độ `onedir` giúp app mở tức thì không bị delay giải nén: `dist\BoxPhoneControl\BoxPhoneControl.exe`.
- Gọi Inno Setup 6 tạo bộ cài Windows chuyên nghiệp: `release\BoxPhoneControl-Setup.exe` (đồng thời copy sang thư mục `CHỈ COPY FILE NÀY\BoxPhoneControl-Setup.exe` để gửi cho khách hàng/vận hành).

---

## 🛡️ 5. CÁC ĐIỂM KỸ THUẬT QUAN TRỌNG CẦN NHỚ

1. **Khóa chiều dọc (Portrait Orientation) & Tắt âm lượng:**
   - Hệ thống tự động đẩy lệnh tắt tự động xoay (`accelerometer_rotation 0`, `user_rotation 0`) và đưa volume media về 0 trước mọi tác vụ để tránh hao pin, nóng máy và âm thanh ồn ào từ 40 thiết bị.

2. **Module TikTok (Đã đóng băng tại v1.0.16):**
   - Bước 1: Lướt For You (10-20s), tự vượt captcha/link redirect nếu bị chặn.
   - Bước 2: Tìm từ khóa mồi, kích hoạt CTR Boost nếu thấy video kênh trong kết quả tìm kiếm.
   - Bước 3: Tìm chính xác Kênh mục tiêu, chuyển tab Người dùng/Top nếu cần, xác minh đúng profile (chống tên đảo, chống kênh giả), click mở video mới nhất, xem và lướt video tiếp theo định kỳ với tỷ lệ xem lặp lại (Loop Rate).

3. **Module Facebook (Đã khóa chặt Target & Chịu lỗi):**
   - Bước 1: Nuôi Feed (10-20s).
   - Bước 2: Tìm từ khóa mồi (10-15s).
   - Bước 3: Tìm Page mục tiêu, ưu tiên tab "Trang".
   - **Xác minh Page Header:** Loại bỏ các node `EditText` trong cây DOM khi xác minh profile để không bao giờ bị nhận diện nhầm khi thanh search còn lưu chữ "Khải Hoàn Skincare".
   - **Từ chối nhãn ngoại lai:** Các trang như Sony, Samsung, Apple, Honda, Toyota... sẽ bị loại bỏ ngay lập tức ở cả bước quét card lẫn bước mở header. Nếu bấm nhầm, tự động ấn `Back` ngay.
   - **Popup blocker:** Tự động phát hiện và bấm đóng popup "Lưu thông tin", "Báo cáo trang / Report", "Lúc khác".
   - **Vòng lặp chịu lỗi:** Tự động retry tối đa 2 lần với khôi phục sạch sẽ nếu gặp sự cố mạng hoặc UI chưa tải xong.

---

## 📞 6. THÔNG TIN REPOSITORY & PHÂN NHÁNH
- **Git Remote:** `origin` -> `https://github.com/datdtpl-maker/BoxphoneKH.git`
- **Nhánh chính thức:** `main`
- **Tài khoản quản trị:** `datdtpl-maker`

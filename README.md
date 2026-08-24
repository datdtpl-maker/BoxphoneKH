# BoxPhoneControl

Ứng dụng Windows điều phối nhiều thiết bị Android qua ADB cho hai module TikTok và Facebook.

## Chức năng chính

- Chạy TikTok hoặc Facebook theo chế độ tuần tự, song song và thích ứng.
- Chạy kết hợp hai module với thứ tự ngẫu nhiên theo từng thiết bị.
- Chọn thiết bị theo vị trí, ví dụ `1-5,10`.
- Khóa màn hình dọc và tắt âm lượng toàn bộ thiết bị.
- Nhận lịch từ khóa TikTok/Facebook từ Notion.
- Báo cáo tiến trình qua Telegram và cho phép tắt thông báo.
- Lưu cấu hình cục bộ trong `.env` cạnh ứng dụng.

## Chạy từ mã nguồn

```powershell
python gui_app.py
```

## Kiểm tra

```powershell
python -m unittest discover -p "test_*.py"
```

## Đóng gói

```powershell
python build_exe.py
```

File đầu ra: `BoxPhoneControl.exe`.

## Bảo mật

Không commit `.env`, token Telegram, token Notion hoặc thông tin đăng nhập. Chỉ chia sẻ bảng Notion cho integration cần sử dụng và cấp quyền tối thiểu.

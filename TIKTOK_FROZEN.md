# TikTok Module — Frozen Baseline

Module TikTok được đóng băng tại **BoxPhoneControl 1.0.16** sau khi toàn bộ
kiểm thử đạt. Không chỉnh sửa implementation, cấu hình, UI entry point hoặc
test TikTok khi công việc chỉ liên quan Facebook.

## Interface được phép gọi

Các phần dùng chung chỉ gọi TikTok qua interface chính:

```python
ADBController.tiktok_automation_workflow(...)
```

Không sao chép logic TikTok sang Facebook và không sửa implementation TikTok
để xử lý lỗi Facebook.

## Guard bắt buộc

Trước mọi build hoặc bàn giao:

```powershell
python verify_tiktok_freeze.py
python -m unittest test_tiktok_freeze.py
```

Nếu guard báo thay đổi, phải dừng và hoàn nguyên riêng thay đổi vô tình chạm
TikTok. Chỉ được tạo baseline mới khi người dùng yêu cầu rõ ràng mở khóa/sửa
module TikTok.

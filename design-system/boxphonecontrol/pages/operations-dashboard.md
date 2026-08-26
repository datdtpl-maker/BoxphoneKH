# Operations Dashboard Page Overrides

> **PROJECT:** BoxPhoneControl
> **Generated:** 2026-08-24 14:19:54
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1400px or full-width
- **Grid:** 12-column grid for data flexibility

### Spacing Overrides

- **Content Density:** High — optimize for information display

### Typography Overrides

- **Primary UI font:** Segoe UI, 11–22px, dùng weight 600–700 cho cấp điều hướng và tiêu đề.
- **Operations copy:** ưu tiên câu ngắn, nhãn hành động trực tiếp; không dùng font monospace cho nội dung vận hành thông thường.

### Color Overrides

- **Canvas:** `#F4F7FB`
- **Surface:** `#FFFFFF`
- **Sidebar:** `#0B1220`
- **Primary action:** `#1667D9`
- **Primary text:** `#0F172A`
- **Secondary text:** `#64748B`
- **Border:** `#DDE5EF`
- Đây là dashboard **light-first**. Theme tối trong Master chỉ còn áp dụng cho vùng nhật ký thời gian thực để tăng khả năng đọc log.

### Component Overrides

- Avoid: Leave UI frozen with no feedback
- Avoid: Make dragging the only way to reorder resize or select
- Giữ nút dừng khẩn cấp cố định ở command header; không lặp lại trong từng module.
- Nhật ký hệ thống phải luôn nhìn thấy ở desktop và có chế độ toàn màn hình.
- Các module TikTok/Facebook dùng cùng một cấu trúc: dữ liệu đầu vào → lộ trình → chọn thiết bị → chế độ chạy.

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: bố cục ba vùng cố định, bo góc 10–16px, viền 1px và thay đổi màu nhẹ khi hover; không scale làm xê dịch layout
- Animation: Use skeleton screens or spinners
- Accessibility: Add buttons menus or tap-to-move controls and retain keyboard operation

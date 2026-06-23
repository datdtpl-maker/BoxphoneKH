import cv2
import numpy as np
import os
import re

class CaptchaSolver:
    def __init__(self, debug_dir=None):
        self.debug_dir = debug_dir
        if debug_dir and not os.path.exists(debug_dir):
            os.makedirs(debug_dir, exist_ok=True)

    def find_slider_distance(self, screenshot_path, device_id="device"):
        """
        Tìm khoảng cách cần kéo thanh trượt từ ảnh chụp màn hình điện thoại (1080x1920).
        Trả về khoảng cách (pixel) hoặc None nếu không tìm thấy.
        """
        # 1. Đọc ảnh màn hình
        img = cv2.imread(screenshot_path)
        if img is None:
            print(f"[{device_id}] Loi: Khong the doc anh tu {screenshot_path}")
            return None

        h_img, w_img, _ = img.shape
        
        # 2. Cắt vùng chứa Captcha (Vùng trung tâm màn hình Y từ 600 đến 1300 trên màn hình 1080x1920)
        # Nếu màn hình có độ phân giải khác, ta sẽ scale tỷ lệ tương ứng
        y_start = int(h_img * 0.3)
        y_end = int(h_img * 0.7)
        x_start = int(w_img * 0.05)
        x_end = int(w_img * 0.95)
        
        roi = img[y_start:y_end, x_start:x_end]
        
        # 3. Tiền xử lý ảnh vùng ROI
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # Áp dụng bộ lọc Gaussian Blur để giảm nhiễu
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # 4. Phát hiện cạnh bằng Canny
        canny = cv2.Canny(blurred, 50, 150)
        
        # Giãn nở cạnh để kết nối các đường nét đứt
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(canny, kernel, iterations=1)
        
        # 5. Tìm các đường bao (Contours)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 6. Lọc các contours có kích thước giống mảnh ghép captcha
        # Kích thước mảnh ghép trên màn hình 1080px thường rộng khoảng 100-160px, cao khoảng 100-160px
        # Ta quy đổi tỷ lệ theo độ rộng màn hình thực tế
        scale_factor = w_img / 1080.0
        min_size = int(80 * scale_factor)
        max_size = int(180 * scale_factor)
        
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # Kiểm tra kích thước và tỷ lệ khung hình (gần như là hình vuông)
            if min_size <= w <= max_size and min_size <= h <= max_size:
                aspect_ratio = float(w) / h
                if 0.8 <= aspect_ratio <= 1.25:
                    candidates.append({
                        'x_roi': x,
                        'y_roi': y,
                        'w': w,
                        'h': h,
                        'cx_global': x + x_start + (w // 2),
                        'cy_global': y + y_start + (h // 2),
                        'contour': contour
                    })
        
        # Vẽ ảnh debug để kiểm tra nếu có thư mục debug
        if self.debug_dir:
            debug_img = roi.copy()
            for cand in candidates:
                x, y, w, h = cand['x_roi'], cand['y_roi'], cand['w'], cand['h']
                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
            debug_path = os.path.join(self.debug_dir, f"debug_captcha_{device_id}.png")
            cv2.imwrite(debug_path, debug_img)
            # Lưu cả ảnh Canny
            canny_debug_path = os.path.join(self.debug_dir, f"debug_canny_{device_id}.png")
            cv2.imwrite(canny_debug_path, dilated)

        print(f"[{device_id}] Tim thay {len(candidates)} ung vien manh ghep Captcha.")
        
        # 7. Đối chiếu tìm cặp mảnh ghép và ô trống ở cùng độ cao Y (cy_global gần bằng nhau)
        # Mảnh ghép gốc (trái) và ô khuyết (phải) luôn nằm trên cùng một đường nằm ngang
        best_pair = None
        min_y_diff = float('inf')
        
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                c1 = candidates[i]
                c2 = candidates[j]
                
                # Tính chênh lệch Y
                y_diff = abs(c1['cy_global'] - c2['cy_global'])
                # Mảnh ghép phải cách nhau một khoảng tối thiểu (ví dụ 150px)
                x_diff = abs(c1['cx_global'] - c2['cx_global'])
                
                if y_diff < 15 * scale_factor and x_diff > 120 * scale_factor:
                    if y_diff < min_y_diff:
                        min_y_diff = y_diff
                        # c1 và c2, mảnh nào có X nhỏ hơn là mảnh ghép bắt đầu (trái), X lớn hơn là ô khuyết (phải)
                        if c1['cx_global'] < c2['cx_global']:
                            best_pair = (c1, c2)
                        else:
                            best_pair = (c2, c1)

        # 8. Tính khoảng cách kéo
        if best_pair:
            start_piece, target_gap = best_pair
            distance = target_gap['cx_global'] - start_piece['cx_global']
            print(f"[{device_id}] Nhan dien chuan xac: Manh ghep tai X={start_piece['cx_global']} -> O khuyet tai X={target_gap['cx_global']}. Khoang cach can keo = {distance}px.")
            
            # Lưu ảnh vẽ kết quả kéo để xác nhận
            if self.debug_dir:
                result_img = img.copy()
                # Vẽ mảnh ghép bắt đầu (đỏ)
                cv2.rectangle(result_img, 
                              (start_piece['cx_global'] - start_piece['w']//2, start_piece['cy_global'] - start_piece['h']//2),
                              (start_piece['cx_global'] + start_piece['w']//2, start_piece['cy_global'] + start_piece['h']//2),
                              (0, 0, 255), 3)
                # Vẽ ô khuyết đích (xanh)
                cv2.rectangle(result_img, 
                              (target_gap['cx_global'] - target_gap['w']//2, target_gap['cy_global'] - target_gap['h']//2),
                              (target_gap['cx_global'] + target_gap['w']//2, target_gap['cy_global'] + target_gap['h']//2),
                              (0, 255, 0), 3)
                # Vẽ đường kéo mũi tên
                cv2.arrowedLine(result_img, 
                                (start_piece['cx_global'], start_piece['cy_global']), 
                                (target_gap['cx_global'], target_gap['cy_global']), 
                                (255, 0, 0), 4, tipLength=0.1)
                
                result_path = os.path.join(self.debug_dir, f"result_solved_{device_id}.png")
                cv2.imwrite(result_path, result_img)
                
            return distance

        print(f"[{device_id}] Canh bao: Khong tim thay manh ghep Captcha phu hop tren anh.")
        return None

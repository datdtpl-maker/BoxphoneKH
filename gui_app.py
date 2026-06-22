import os
import sys
import time
import re
import random
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

# Đảm bảo đường dẫn module chính xác
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import main

# Thiết lập giao diện CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("🤖 BOX PHONE - SHOPEE KHẢI HOÀN (Control Panel) 📱")
        self.geometry("1200x750")
        
        # Grid layout 1x2 (Cột bên trái: Cấu hình & Điều khiển, Cột bên phải: Danh sách máy)
        self.grid_columnconfigure(0, weight=0, minsize=400)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # ================= LEFT PANEL =================
        self.left_panel = ctk.CTkFrame(self, width=400, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        # 1. Cấu hình hệ thống
        self.lbl_settings = ctk.CTkLabel(self.left_panel, text="🔒 Cấu hình Hệ thống", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_settings.pack(pady=(15, 10), padx=20, anchor="w")
        
        self.ent_token = ctk.CTkEntry(self.left_panel, placeholder_text="TELEGRAM_BOT_TOKEN", show="*")
        self.ent_token.pack(fill="x", padx=20, pady=5)
        self.ent_token.insert(0, config.TELEGRAM_BOT_TOKEN or "")
        
        admin_ids_str = ",".join(map(str, config.ALLOWED_USER_IDS or []))
        self.ent_admins = ctk.CTkEntry(self.left_panel, placeholder_text="ALLOWED_USER_IDS (Cách nhau dấu phẩy)")
        self.ent_admins.pack(fill="x", padx=20, pady=5)
        self.ent_admins.insert(0, admin_ids_str)
        
        self.ent_adb = ctk.CTkEntry(self.left_panel, placeholder_text="Đường dẫn ADB (adb.exe)")
        self.ent_adb.pack(fill="x", padx=20, pady=5)
        self.ent_adb.insert(0, config.ADB_PATH or "")
        
        self.btn_save = ctk.CTkButton(self.left_panel, text="Lưu cấu hình", command=self.save_settings)
        self.btn_save.pack(fill="x", padx=20, pady=10)
        
        # Separator line
        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=20, pady=10)
        
        # 2. Điều khiển tổng thể
        self.lbl_tasks = ctk.CTkLabel(self.left_panel, text="🚀 Điều khiển Tác vụ", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_tasks.pack(pady=(5, 10), padx=20, anchor="w")
        
        self.ent_keywords = ctk.CTkEntry(self.left_panel, placeholder_text="Từ khóa tìm kiếm (Ví dụ: deriva, son môi)")
        self.ent_keywords.pack(fill="x", padx=20, pady=5)
        
        self.ent_selection = ctk.CTkEntry(self.left_panel, placeholder_text="Chọn máy (Ví dụ: 1-5,10 hoặc để trống để chạy tất cả)")
        self.ent_selection.pack(fill="x", padx=20, pady=5)
        
        self.btn_seq = ctk.CTkButton(self.left_panel, text="Chạy Tuần Tự (Lâm Đồng)", fg_color="#2ecc71", hover_color="#27ae60", command=self.run_seq_search)
        self.btn_seq.pack(fill="x", padx=20, pady=5)
        
        self.btn_par = ctk.CTkButton(self.left_panel, text="Chạy Song Song (Lâm Đồng)", fg_color="#3498db", hover_color="#2980b9", command=self.run_par_search)
        self.btn_par.pack(fill="x", padx=20, pady=5)
        
        self.btn_stop = ctk.CTkButton(self.left_panel, text="🛑 DỪNG CHẠY KHẨN CẤP", fg_color="#e74c3c", hover_color="#c0392b", font=ctk.CTkFont(size=15, weight="bold"), command=self.stop_all)
        self.btn_stop.pack(fill="x", padx=20, pady=10)
        
        # Log console textbox
        self.lbl_log = ctk.CTkLabel(self.left_panel, text="📋 Nhật ký hoạt động", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_log.pack(padx=20, anchor="w")
        
        self.log_box = ctk.CTkTextbox(self.left_panel, height=200, state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(5, 15))
        
        # Redirect standard output
        sys.stdout = ConsoleRedirector(self.log_box)
        sys.stderr = ConsoleRedirector(self.log_box)
        
        # ================= RIGHT PANEL =================
        self.right_panel = ctk.CTkFrame(self)
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self.right_panel.grid_rowconfigure(0, weight=0)
        self.right_panel.grid_rowconfigure(1, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)
        
        # Header right panel
        self.header_frame = ctk.CTkFrame(self.right_panel, height=50, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=15, pady=10)
        
        self.lbl_devices = ctk.CTkLabel(self.header_frame, text="📱 Bảng điều khiển Box Phone (20 Thiết bị)", font=ctk.CTkFont(size=18, weight="bold"))
        self.lbl_devices.pack(side="left")
        
        self.btn_refresh = ctk.CTkButton(self.header_frame, text="Tải lại danh sách", width=120, command=self.load_devices_grid)
        self.btn_refresh.pack(side="right")
        
        # Scrollable grid frame for devices
        self.grid_frame = ctk.CTkScrollableFrame(self.right_panel)
        self.grid_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        
        # Configure columns inside grid frame
        for col in range(4):
            self.grid_frame.grid_columnconfigure(col, weight=1, minsize=180)
            
        self.load_devices_grid()
        
        # Khởi chạy bot Telegram ở luồng phụ
        self.start_bot_service()

    def run_in_thread(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def save_settings(self):
        token = self.ent_token.get().strip()
        admin_ids = self.ent_admins.get().strip()
        adb_path = self.ent_adb.get().strip()
        
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
        keys = {
            'TELEGRAM_BOT_TOKEN': token,
            'ALLOWED_USER_IDS': admin_ids,
            'ADB_PATH': adb_path
        }
        
        new_lines = []
        updated_keys = set()
        for line in lines:
            matched = False
            for k in keys:
                if line.strip().startswith(f"{k}="):
                    new_lines.append(f"{k}={keys[k]}\n")
                    updated_keys.add(k)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)
                
        for k in keys:
            if k not in updated_keys:
                new_lines.append(f"{k}={keys[k]}\n")
                
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            
        # Reload config
        config.TELEGRAM_BOT_TOKEN = token
        config.ALLOWED_USER_IDS = [int(i.strip()) for i in admin_ids.split(',') if i.strip().isdigit()]
        config.ADB_PATH = adb_path
        main.adb.adb_path = adb_path
        
        # Re-initialize bot object
        import telebot
        main.bot = telebot.TeleBot(token)
        
        print("[Hệ thống] Lưu cấu hình và tải lại thành công!")
        messagebox.showinfo("Thành công", "Đã lưu cấu hình và tự động nạp lại!")

    def load_devices_grid(self):
        # Dọn dẹp grid cũ
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
            
        print("[Hệ thống] Đang quét các cổng thiết bị...")
        devices = main.get_ordered_devices()
        
        if not devices:
            lbl_empty = ctk.CTkLabel(self.grid_frame, text="❌ Không tìm thấy thiết bị nào đang kết nối.\nHãy kiểm tra lại kết nối cáp USB và ADB.", font=ctk.CTkFont(size=14))
            lbl_empty.grid(row=0, column=0, columnspan=4, pady=100)
            return

        for idx, dev in enumerate(devices):
            row = idx // 4
            col = idx % 4
            
            # Khởi tạo card máy
            card = ctk.CTkFrame(self.grid_frame, border_width=1, border_color="gray30")
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            
            card.columnconfigure(0, weight=1)
            
            # Tên máy và ID
            lbl_name = ctk.CTkLabel(card, text=f"Máy {idx+1} (S{idx+1})", font=ctk.CTkFont(size=14, weight="bold"))
            lbl_name.grid(row=0, column=0, padx=10, pady=(8, 2))
            
            lbl_id = ctk.CTkLabel(card, text=f"ID: {dev[:12]}...", text_color="gray50", font=ctk.CTkFont(size=11))
            lbl_id.grid(row=1, column=0, padx=10, pady=(0, 8))
            
            # Panel nút bấm hành động
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
            
            btn_frame.columnconfigure(0, weight=1)
            btn_frame.columnconfigure(1, weight=1)
            btn_frame.columnconfigure(2, weight=1)
            
            # Hàng 1
            btn_cap = ctk.CTkButton(btn_frame, text="Ảnh", width=40, font=ctk.CTkFont(size=10), command=lambda d=dev, i=idx+1: self.screenshot_device(d, i))
            btn_cap.grid(row=0, column=0, padx=2, pady=2)
            
            btn_home = ctk.CTkButton(btn_frame, text="Home", width=40, font=ctk.CTkFont(size=10), command=lambda d=dev: self.run_in_thread(main.adb.keyevent, d, 3))
            btn_home.grid(row=0, column=1, padx=2, pady=2)
            
            btn_back = ctk.CTkButton(btn_frame, text="Back", width=40, font=ctk.CTkFont(size=10), command=lambda d=dev: self.run_in_thread(main.adb.keyevent, d, 4))
            btn_back.grid(row=0, column=2, padx=2, pady=2)
            
            # Hàng 2
            btn_open = ctk.CTkButton(btn_frame, text="Mở Shopee", width=62, font=ctk.CTkFont(size=9), fg_color="gray25", command=lambda d=dev: self.run_in_thread(main.adb.launch_app, d, config.SHOPEE_PACKAGE))
            btn_open.grid(row=1, column=0, columnspan=2, padx=2, pady=2)
            
            btn_close = ctk.CTkButton(btn_frame, text="Tắt app", width=62, font=ctk.CTkFont(size=9), fg_color="#c0392b", hover_color="#962d22", command=lambda d=dev: self.run_in_thread(main.adb.stop_app, d, config.SHOPEE_PACKAGE))
            btn_close.grid(row=1, column=2, padx=2, pady=2)

    def screenshot_device(self, dev_id, idx):
        def action():
            print(f"[GUI] Đang chụp màn hình Máy {idx}...")
            temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            local_path = os.path.join(temp_dir, f"gui_screenshot_{idx}.png")
            success, res = main.adb.take_screenshot(dev_id, local_path)
            if success:
                print(f"[GUI] Chụp ảnh Máy {idx} thành công! Đường dẫn: {local_path}")
                # Mở ảnh bằng Windows Photo Viewer mặc định
                os.startfile(local_path)
            else:
                print(f"[GUI] Lỗi chụp màn hình Máy {idx}: {res}")
        self.run_in_thread(action)

    def stop_all(self):
        main.cancel_flag = True
        main.cancel_sequential = True
        print("[GUI] 🛑 ĐÃ GỬI YÊU CẦU DỪNG KHẨN CẤP TOÀN BỘ CÁC MÁY!")
        
        def reset_flags():
            time.sleep(3.5)
            main.cancel_flag = False
            main.cancel_sequential = False
            print("[GUI] Bot đã sẵn sàng nhận các câu lệnh mới.")
            
        self.run_in_thread(reset_flags)

    def parse_targets(self):
        selection = self.ent_selection.get().strip()
        devices = main.get_ordered_devices()
        if not selection:
            return devices
            
        target_devices = []
        try:
            for part in selection.split(','):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    target_devices.extend(devices[start-1:end])
                else:
                    idx = int(part)
                    target_devices.append(devices[idx-1])
            return target_devices
        except Exception:
            messagebox.showerror("Lỗi", "Cú pháp chọn máy không hợp lệ (Ví dụ: 1-5,10)")
            return []

    def run_seq_search(self):
        keywords_str = self.ent_keywords.get().strip()
        if not keywords_str:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa tìm kiếm!")
            return
            
        # Tự động phát hiện cờ click_first_item trong ô từ khóa của GUI
        click_first_item = False
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        temp_str = keywords_str.lower()
        if any(ind in temp_str for ind in first_indicators):
            click_first_item = True
            
        # Làm sạch từ khóa
        for ind in first_indicators:
            keywords_str = re.sub(r"\b" + re.escape(ind) + r"\b", "", keywords_str, flags=re.IGNORECASE)
        keywords_str = re.sub(r"\s+", " ", keywords_str).strip()
            
        keywords = [k.strip() for k in re.split(r'[,;|]', keywords_str) if k.strip()]
        target_devices = self.parse_targets()
        if not target_devices:
            return
            
        def action():
            class DummyMessage:
                def __init__(self):
                    class DummyChat:
                        def __init__(self):
                            self.id = int(config.ALLOWED_USER_IDS[0]) if config.ALLOWED_USER_IDS else 0
                    self.chat = DummyChat()
            main.run_sequential_shopee_search(DummyMessage(), keywords, target_devices, click_first_item=click_first_item)
            
        self.run_in_thread(action)

    def run_par_search(self):
        keywords_str = self.ent_keywords.get().strip()
        if not keywords_str:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa tìm kiếm!")
            return
            
        # Tự động phát hiện cờ click_first_item trong ô từ khóa của GUI
        click_first_item = False
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        temp_str = keywords_str.lower()
        if any(ind in temp_str for ind in first_indicators):
            click_first_item = True
            
        # Làm sạch từ khóa
        for ind in first_indicators:
            keywords_str = re.sub(r"\b" + re.escape(ind) + r"\b", "", keywords_str, flags=re.IGNORECASE)
        keywords_str = re.sub(r"\s+", " ", keywords_str).strip()
            
        keywords = [k.strip() for k in re.split(r'[,;|]', keywords_str) if k.strip()]
        target_devices = self.parse_targets()
        if not target_devices:
            return
            
        def action():
            main.cancel_flag = False
            main.cancel_sequential = False
            keyword_str = ", ".join(keywords)
            print(f"[GUI] Bắt đầu tìm kiếm song song '{keyword_str}' (Click đầu tiên: {click_first_item}) trên {len(target_devices)} máy...")
            
            def run_search_parallel(device_id):
                devices = main.get_ordered_devices()
                dev_idx = devices.index(device_id) + 1
                current_keyword = random.choice(keywords)
                print(f"[Máy {dev_idx}] Bắt đầu tìm từ khóa `{current_keyword}`...")
                success, err = main.adb.shopee_find_and_click_lamdong(device_id, current_keyword, is_cancelled=main.is_cancelled, click_first_item=click_first_item)
                if success:
                    print(f"[Máy {dev_idx}] ✅ Đã hoàn thành trọn vẹn quy trình lướt sản phẩm và dạo Shop!")
                else:
                    print(f"[Máy {dev_idx}] ❌ Thất bại: {err}")
                    
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                list(executor.map(run_search_parallel, target_devices))
                
            print("[GUI] Tiến trình tìm kiếm song song kết thúc.")
            
        self.run_in_thread(action)

    def start_bot_service(self):
        def run():
            print("[Hệ thống] Bot Telegram đang khởi động dưới nền...")
            while True:
                try:
                    if config.TELEGRAM_BOT_TOKEN:
                        main.bot.polling(none_stop=True, interval=1, timeout=20)
                    else:
                        time.sleep(5)
                except Exception as e:
                    print(f"[Lỗi Bot] Lỗi kết nối Telegram, đang nạp lại sau 5s... Lỗi: {e}")
                    time.sleep(5)
        self.run_in_thread(run)


class ConsoleRedirector(object):
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        # Tránh in ra các chuỗi xuống dòng trống
        if string == '\n':
            try:
                self.text_widget.configure(state="normal")
                self.text_widget.insert("end", string)
                self.text_widget.see("end")
                self.text_widget.configure(state="disabled")
            except Exception:
                pass
            return
            
        # Thêm timestamp vào đầu mỗi dòng nhật ký
        timestamp = time.strftime("[%H:%M:%S] ")
        lines = string.splitlines()
        log_msg = ""
        for line in lines:
            if line.strip():
                log_msg += f"{timestamp}{line}\n"
                
        if log_msg:
            try:
                self.text_widget.configure(state="normal")
                self.text_widget.insert("end", log_msg)
                self.text_widget.see("end")
                self.text_widget.configure(state="disabled")
            except Exception:
                pass

    def flush(self):
        pass


if __name__ == "__main__":
    app = GUIApp()
    app.mainloop()

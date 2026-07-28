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

# Operations dashboard: dark, high-contrast, dense and optimized for long sessions.
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BOXPHONE AUTOMATION • OPERATIONS CONTROL CENTER")
        self.geometry("1480x940")
        self.minsize(1180, 760)
        self.configure(fg_color="#070b14")
        
        # Thiết lập app icon bitmap
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        
        # Lưu trữ các biến Checkbox điều khiển hàng loạt
        self.device_checkboxes = {}
        
        # Main Grid Layout: 1 Cột, 4 Hàng (Header, Log Console trên cùng, Operations Grid 2 cột, Bottom Config)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        
        # ================= ROW 0: TOP HEADER BANNER =================
        self.top_header = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=16, border_width=1, border_color="#243244")
        self.top_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        
        self.brand_badge = ctk.CTkFrame(self.top_header, fg_color="#111c31", corner_radius=12, border_width=0)
        self.brand_badge.pack(fill="x", padx=10, pady=10)
        
        self.lbl_brand = ctk.CTkLabel(
            self.brand_badge,
            text="BOXPHONE AUTOMATION",
            font=ctk.CTkFont(family="Segoe UI", size=19, weight="bold"),
            text_color="#f8fafc"
        )
        self.lbl_brand.pack(side="left", padx=14, pady=6)
        
        self.lbl_sub_brand = ctk.CTkLabel(
            self.brand_badge,
            text="OPERATIONS CONTROL CENTER  /  SHOPEE + TIKTOK",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#94a3b8"
        )
        self.lbl_sub_brand.pack(side="left", padx=10, pady=6)

        self.btn_refresh = ctk.CTkButton(
            self.brand_badge,
            text="QUÉT THIẾT BỊ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            width=148,
            height=36,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            corner_radius=9,
            command=self.refresh_devices_action
        )
        self.btn_refresh.pack(side="right", padx=14, pady=6)

        # ================= ROW 1: NHẬT KÝ HOẠT ĐỘNG (ĐẶT NẰM NỔI BẬT TRÊN CÙNG PHẦN MỀM) =================
        self.log_card = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=16, border_width=1, border_color="#243244")
        self.log_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        
        self.lbl_log = ctk.CTkLabel(
            self.log_card,
            text="NHẬT KÝ HOẠT ĐỘNG  •  REAL-TIME",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#e2e8f0"
        )
        self.lbl_log.pack(padx=14, anchor="w", pady=(8, 2))
        
        self.log_box = ctk.CTkTextbox(
            self.log_card,
            height=150,
            state="disabled",
            fg_color="#050914",
            text_color="#22d3ee",
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1,
            border_color="#1e293b",
            corner_radius=10
        )
        self.log_box.pack(fill="x", padx=14, pady=(0, 10))
        
        # Redirect standard output & error to log_box
        sys.stdout = ConsoleRedirector(self.log_box)
        sys.stderr = ConsoleRedirector(self.log_box)

        # ================= ROW 2: OPERATIONAL CARDS (2 DANH MỤC RIÊNG BIỆT: SHOPEE & TIKTOK) =================
        self.ops_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.ops_frame.grid(row=2, column=0, sticky="nsew", padx=18, pady=2)
        self.ops_frame.columnconfigure(0, weight=1)
        self.ops_frame.columnconfigure(1, weight=1)
        self.ops_frame.rowconfigure(0, weight=1)

        # ---------------- KHUNG 1: SHOPEE AUTOMATION ----------------
        self.shopee_scroll = ctk.CTkScrollableFrame(
            self.ops_frame, 
            corner_radius=16,
            fg_color="#0f172a",
            border_width=1, 
            border_color="#243244"
        )
        self.shopee_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)

        self.lbl_tasks = ctk.CTkLabel(
            self.shopee_scroll,
            text="SHOPEE AUTOMATION",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#fb923c"
        )
        self.lbl_tasks.pack(pady=(12, 4), padx=16, anchor="w")
        
        self.lbl_main_keywords = ctk.CTkLabel(
            self.shopee_scroll,
            text="Từ khóa chính • Mỗi dòng một từ khóa",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1"
        )
        self.lbl_main_keywords.pack(padx=16, pady=(2, 0), anchor="w")

        self.txt_main_keywords = ctk.CTkTextbox(
            self.shopee_scroll, 
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            border_width=1,
            corner_radius=10,
            height=70,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.txt_main_keywords.pack(fill="x", padx=16, pady=3)
        
        # Chế độ từ khóa
        self.keyword_mode = ctk.StringVar(value="original")
        self.mode_frame = ctk.CTkFrame(self.shopee_scroll, fg_color="#111827", corner_radius=10, border_width=1, border_color="#273449")
        self.mode_frame.pack(fill="x", padx=16, pady=4)
        
        self.rad_orig = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Gốc (Không AI)", 
            variable=self.keyword_mode, 
            value="original",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#e2e8f0",
            fg_color="#2563eb",
            hover_color="#1d4ed8"
        )
        self.rad_orig.pack(side="left", padx=(8, 4), pady=5)
        
        self.rad_ai = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Mở rộng (AI)", 
            variable=self.keyword_mode, 
            value="ai",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#e2e8f0",
            fg_color="#8b5cf6",
            hover_color="#7c3aed"
        )
        self.rad_ai.pack(side="left", padx=4, pady=5)

        self.rad_ai_t2 = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Tầng 2 (AI sinh)", 
            variable=self.keyword_mode, 
            value="ai_t2",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#e2e8f0",
            fg_color="#a855f7",
            hover_color="#9333ea"
        )
        self.rad_ai_t2.pack(side="left", padx=(4, 8), pady=5)
        
        # Nút sinh từ khóa qua AI
        self.btn_gen_ai = ctk.CTkButton(
            self.shopee_scroll,
            text="SINH TỪ KHÓA TẦNG 1  •  MỞ RỘNG SEO",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            text_color="#ffffff",
            corner_radius=8,
            height=30,
            command=self.generate_ai_keywords_action
        )
        self.btn_gen_ai.pack(fill="x", padx=16, pady=2)
        
        self.btn_gen_ai_t2 = ctk.CTkButton(
            self.shopee_scroll,
            text="SINH TỪ KHÓA TẦNG 2  •  BÓC TÁCH TIÊU ĐỀ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            text_color="#ffffff",
            corner_radius=8,
            height=30,
            command=self.generate_ai_keywords_tier2_action
        )
        self.btn_gen_ai_t2.pack(fill="x", padx=16, pady=2)
        
        self.lbl_ai_keywords = ctk.CTkLabel(
            self.shopee_scroll,
            text="Từ khóa AI đã tạo",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1"
        )
        self.lbl_ai_keywords.pack(padx=16, pady=(4, 0), anchor="w")
        
        self.txt_ai_keywords = ctk.CTkTextbox(
            self.shopee_scroll,
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#38bdf8",
            border_width=1,
            corner_radius=8,
            height=80,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.txt_ai_keywords.pack(fill="x", padx=16, pady=3)
        
        self.ent_selection = ctk.CTkEntry(
            self.shopee_scroll, 
            placeholder_text="Chọn máy chạy Shopee (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            placeholder_text_color="#94a3b8",
            corner_radius=10,
            height=38
        )
        self.ent_selection.pack(fill="x", padx=16, pady=3)
        
        self.btn_grid = ctk.CTkFrame(self.shopee_scroll, fg_color="transparent")
        self.btn_grid.pack(fill="x", padx=16, pady=(4, 6))
        self.btn_grid.columnconfigure(0, weight=1)
        self.btn_grid.columnconfigure(1, weight=1)
        
        self.btn_seq = ctk.CTkButton(
            self.btn_grid,
            text="CHẠY TUẦN TỰ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#10b981", 
            hover_color="#059669",
            text_color="#ffffff",
            corner_radius=8,
            height=40,
            command=self.run_seq_search
        )
        self.btn_seq.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        
        self.btn_par = ctk.CTkButton(
            self.btn_grid,
            text="CHẠY SONG SONG",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#2563eb", 
            hover_color="#1d4ed8",
            text_color="#ffffff",
            corner_radius=8,
            height=40,
            command=self.run_par_search
        )
        self.btn_par.grid(row=0, column=1, padx=(3, 0), sticky="ew")
        
        self.btn_stop = ctk.CTkButton(
            self.shopee_scroll,
            text="DỪNG SHOPEE KHẨN CẤP",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#ef4444", 
            hover_color="#dc2626",
            text_color="#ffffff",
            border_width=1,
            border_color="#f87171",
            corner_radius=10,
            height=42,
            command=self.stop_all
        )
        self.btn_stop.pack(fill="x", padx=16, pady=(2, 10))

        # ---------------- KHUNG 2: TIKTOK AUTOMATION 3 BƯỚC ----------------
        self.tiktok_scroll = ctk.CTkScrollableFrame(
            self.ops_frame, 
            corner_radius=16,
            fg_color="#0f172a",
            border_width=1, 
            border_color="#243244"
        )
        self.tiktok_scroll.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)

        self.lbl_tiktok_title = ctk.CTkLabel(
            self.tiktok_scroll,
            text="TIKTOK • QUY TRÌNH 3 BƯỚC",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#f472b6"
        )
        self.lbl_tiktok_title.pack(pady=(12, 4), padx=16, anchor="w")

        self.lbl_tt_seed = ctk.CTkLabel(
            self.tiktok_scroll,
            text="Từ khóa nhiệm vụ • Phân cách bằng dấu phẩy",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1"
        )
        self.lbl_tt_seed.pack(padx=16, pady=(2, 0), anchor="w")

        self.ent_tt_seed = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="skincare, trị mụn, nặn mụn, chăm sóc da",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            placeholder_text_color="#94a3b8",
            corner_radius=10,
            height=40
        )
        self.ent_tt_seed.insert(0, config.TIKTOK_SEED_KEYWORDS_DEFAULT)
        self.ent_tt_seed.pack(fill="x", padx=16, pady=3)

        self.lbl_tt_channel = ctk.CTkLabel(
            self.tiktok_scroll,
            text="Tên kênh TikTok mục tiêu",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1"
        )
        self.lbl_tt_channel.pack(padx=16, pady=(4, 0), anchor="w")

        self.ent_tt_channel = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="Tên kênh TikTok mục tiêu",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            placeholder_text_color="#94a3b8",
            corner_radius=10,
            height=40
        )
        self.ent_tt_channel.insert(0, config.TIKTOK_TARGET_CHANNEL_DEFAULT)
        self.ent_tt_channel.pack(fill="x", padx=16, pady=3)

        self.tt_timeline_card = ctk.CTkFrame(
            self.tiktok_scroll,
            fg_color="#172033",
            corner_radius=10,
            border_width=1,
            border_color="#334155",
        )
        self.tt_timeline_card.pack(fill="x", padx=16, pady=(10, 4))
        self.lbl_tt_timeline = ctk.CTkLabel(
            self.tt_timeline_card,
            text=(
                "LỘ TRÌNH TỰ ĐỘNG\n"
                "B1  Trang chủ: 15–60 giây\n"
                "B2  Từ khóa nhiệm vụ: 15–30 giây\n"
                "B3  Ở trong kênh: 3–5 phút • đổi clip mỗi 15–30 giây"
            ),
            justify="left",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#cbd5e1",
        )
        self.lbl_tt_timeline.pack(fill="x", padx=14, pady=10)

        self.ent_tt_selection = ctk.CTkEntry(
            self.tiktok_scroll, 
            placeholder_text="Chọn máy chạy TikTok (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            placeholder_text_color="#94a3b8",
            corner_radius=10,
            height=40
        )
        self.ent_tt_selection.pack(fill="x", padx=16, pady=(6, 3))

        self.tt_btn_grid = ctk.CTkFrame(self.tiktok_scroll, fg_color="transparent")
        self.tt_btn_grid.pack(fill="x", padx=16, pady=(6, 4))
        self.tt_btn_grid.columnconfigure(0, weight=1)
        self.tt_btn_grid.columnconfigure(1, weight=1)

        self.btn_tt_seq = ctk.CTkButton(
            self.tt_btn_grid,
            text="CHẠY TUẦN TỰ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#16a34a",
            hover_color="#15803d",
            text_color="#ffffff",
            corner_radius=10,
            height=40,
            command=self.run_seq_tiktok
        )
        self.btn_tt_seq.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        self.btn_tt_par = ctk.CTkButton(
            self.tt_btn_grid,
            text="CHẠY SONG SONG",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#db2777",
            hover_color="#be185d",
            text_color="#ffffff",
            corner_radius=10,
            height=40,
            command=self.run_par_tiktok
        )
        self.btn_tt_par.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        self.btn_tt_stop = ctk.CTkButton(
            self.tiktok_scroll,
            text="DỪNG TIKTOK KHẨN CẤP",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#ef4444", 
            hover_color="#dc2626",
            text_color="#ffffff",
            border_width=1,
            border_color="#f87171",
            corner_radius=10,
            height=42,
            command=self.stop_all
        )
        self.btn_tt_stop.pack(fill="x", padx=16, pady=(4, 10))

        # ================= ROW 3: BOTTOM PANEL (CẤU HÌNH HỆ THỐNG & ĐIỀU KHIỂN CHUNG) =================
        self.bottom_panel = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=16, border_width=1, border_color="#243244")
        self.bottom_panel.grid(row=3, column=0, sticky="ew", padx=18, pady=(8, 14))
        
        self.settings_card = ctk.CTkFrame(self.bottom_panel, fg_color="transparent")
        self.settings_card.pack(fill="x", padx=12, pady=6)
        
        self.lbl_settings = ctk.CTkLabel(
            self.settings_card,
            text="CẤU HÌNH HỆ THỐNG",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#e2e8f0"
        )
        self.lbl_settings.pack(side="left", padx=6)

        self.ent_token = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Telegram Bot Token", 
            show="*",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            corner_radius=6,
            height=28,
            width=200
        )
        self.ent_token.pack(side="left", padx=4)
        self.ent_token.insert(0, config.TELEGRAM_BOT_TOKEN or "")

        admin_ids_str = ",".join(map(str, config.ALLOWED_USER_IDS or []))
        self.ent_admins = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Admin IDs",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            corner_radius=6,
            height=28,
            width=120
        )
        self.ent_admins.pack(side="left", padx=4)
        self.ent_admins.insert(0, admin_ids_str)

        self.ent_adb = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="ADB Path",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            corner_radius=6,
            height=28,
            width=180
        )
        self.ent_adb.pack(side="left", padx=4)
        self.ent_adb.insert(0, config.ADB_PATH or "")

        shops_str = ",".join(config.SHOPEE_SHOP_NAMES or [])
        self.ent_shops = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Shops",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            corner_radius=6,
            height=28,
            width=160
        )
        self.ent_shops.pack(side="left", padx=4)
        self.ent_shops.insert(0, shops_str)

        self.ent_gemini_key = ctk.CTkEntry(
            self.settings_card,
            placeholder_text="Gemini Key",
            show="*",
            fg_color="#0b1220",
            border_color="#334155",
            text_color="#f8fafc",
            corner_radius=6,
            height=28,
            width=160
        )
        self.ent_gemini_key.pack(side="left", padx=4)
        self.ent_gemini_key.insert(0, config.GEMINI_API_KEY or "")

        self.btn_save = ctk.CTkButton(
            self.settings_card,
            text="LƯU",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            text_color="#ffffff",
            corner_radius=6,
            height=28,
            width=70,
            command=self.save_settings
        )
        self.btn_save.pack(side="right", padx=6)

        # Quét thiết bị khi vừa khởi động
        self.refresh_devices_action()
        # Khởi chạy bot Telegram ở luồng phụ
        self.start_bot_service()

    def run_in_thread(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def refresh_devices_action(self):
        def action():
            print("[Hệ thống] Đang quét cổng thiết bị USB/ADB...")
            devices = main.get_ordered_devices()
            if devices:
                print(f"[Hệ thống] ✅ Đã kết nối {len(devices)} thiết bị điện thoại Box Phone:")
                for idx, dev in enumerate(devices):
                    print(f"   📱 [{idx+1}] Máy {main.get_device_name(dev)} (ID: {dev})")
                self.bulk_disable_rotation(devices)
            else:
                print("[Hệ thống] ❌ Chưa phát hiện thiết bị nào. Hãy kết nối cáp USB và kiểm tra ADB.")
        self.run_in_thread(action)

    def save_settings(self):
        token = self.ent_token.get().strip()
        admin_ids = self.ent_admins.get().strip()
        adb_path = self.ent_adb.get().strip()
        shops = self.ent_shops.get().strip()
        gemini_key = self.ent_gemini_key.get().strip()
        
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
        keys = {
            'TELEGRAM_BOT_TOKEN': token,
            'ALLOWED_USER_IDS': admin_ids,
            'ADB_PATH': adb_path,
            'SHOPEE_SHOP_NAMES': shops,
            'GEMINI_API_KEY': gemini_key
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
        config.SHOPEE_SHOP_NAMES = [s.strip() for s in shops.split(',') if s.strip()]
        config.GEMINI_API_KEY = gemini_key
        
        # Re-initialize bot object
        import telebot
        main.bot = telebot.TeleBot(token)
        
        print("[Hệ thống] Lưu cấu hình và tải lại thành công!")
        messagebox.showinfo("Thành công", "Đã lưu cấu hình và tự động nạp lại!")

    def stop_all(self):
        main.cancel_flag = True
        main.cancel_sequential = True
        print("[GUI] 🛑 ĐÃ XÓA TOÀN BỘ LUỒNG VÀ DỪNG KHẨN CẤP! Phần mềm sẵn sàng nhận lệnh mới.")

    def parse_targets(self, entry_widget=None):
        if entry_widget is None:
            entry_widget = self.ent_selection
        selection = entry_widget.get().strip()
        devices = main.get_ordered_devices()
        if not devices:
            messagebox.showwarning("Cảnh báo", "Không có thiết bị nào đang kết nối!")
            return []
            
        if not selection:
            return devices
            
        selected_indices = set()
        parts = selection.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        selected_indices.add(i)
                except ValueError:
                    pass
            elif part.isdigit():
                selected_indices.add(int(part))
                
        result = []
        for idx in sorted(list(selected_indices)):
            if 1 <= idx <= len(devices):
                result.append(devices[idx - 1])
                
        if not result:
            messagebox.showwarning("Cảnh báo", f"Cú pháp chọn máy không hợp lệ hoặc vượt quá số lượng máy ({len(devices)} máy)!")
            return []
            
        return result

    def bulk_disable_rotation(self, target_devices=None):
        if target_devices is None:
            target_devices = main.get_ordered_devices()
        def action():
            def disable_rot(d):
                try:
                    main.adb.execute_adb(d, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
                    main.adb.execute_adb(d, ["shell", "settings", "put", "system", "user_rotation", "0"])
                except Exception:
                    pass
            from concurrent.futures import ThreadPoolExecutor
            if target_devices:
                with ThreadPoolExecutor(max_workers=max(1, len(target_devices))) as executor:
                    executor.map(disable_rot, target_devices)
        self.run_in_thread(action)

    # ================= CÁC TÁC VỤ CHẠY TÌM KIẾM SHOPEE =================
    def run_seq_search(self):
        click_first_item = False
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        mode = self.keyword_mode.get()
        
        if mode == "original":
            raw_text = self.txt_main_keywords.get("1.0", "end").strip()
            if not raw_text:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính Shopee!")
                return
            keywords = [line.strip() for line in raw_text.split("\n") if line.strip()]
            for kw in keywords:
                if any(ind in kw.lower() for ind in first_indicators):
                    click_first_item = True
                    break
            clean_keywords = []
            for kw in keywords:
                clean_kw = kw
                for ind in first_indicators:
                    clean_kw = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_kw, flags=re.IGNORECASE)
                clean_kw = re.sub(r"\s+", " ", clean_kw).strip()
                if clean_kw:
                    clean_keywords.append(clean_kw)
            keywords = clean_keywords
        else:
            ai_keywords_raw = self.txt_ai_keywords.get("1.0", "end").strip()
            if ai_keywords_raw:
                keywords = [line.strip() for line in ai_keywords_raw.split("\n") if line.strip()]
                for kw in keywords:
                    if any(ind in kw.lower() for ind in first_indicators):
                        click_first_item = True
                        break
            else:
                raw_text = self.txt_main_keywords.get("1.0", "end").strip()
                if not raw_text:
                    messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính trước khi chạy chế độ AI!")
                    return
                keywords = [line.strip() for line in raw_text.split("\n") if line.strip()]
                for kw in keywords:
                    if any(ind in kw.lower() for ind in first_indicators):
                        click_first_item = True
                        break
                clean_keywords = []
                for kw in keywords:
                    clean_kw = kw
                    for ind in first_indicators:
                        clean_kw = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_kw, flags=re.IGNORECASE)
                    clean_kw = re.sub(r"\s+", " ", clean_kw).strip()
                    if clean_kw:
                        clean_keywords.append(clean_kw)
                keywords = clean_keywords
            
        target_devices = self.parse_targets(entry_widget=self.ent_selection)
        if not target_devices:
            return
            
        def action():
            nonlocal keywords
            main.cancel_flag = False
            main.cancel_sequential = False
            if (mode == "ai" or mode == "ai_t2") and not ai_keywords_raw:
                def status_cb(msg):
                    self.log_message(f"[Gemini AI] {msg}")
                if mode == "ai":
                    expanded = config.generate_keywords_via_gemini(
                        config.GEMINI_API_KEY, 
                        keywords, 
                        status_cb=status_cb
                    )
                else:
                    expanded = config.generate_keywords_tier2_via_gemini(
                        config.GEMINI_API_KEY,
                        keywords,
                        status_cb=status_cb
                    )
                if click_first_item:
                    expanded = [f"{k} video" for k in expanded]
                keywords = expanded
                self.txt_ai_keywords.delete("1.0", "end")
                for k in keywords:
                    self.txt_ai_keywords.insert("end", f"{k}\n")
            
            class DummyMessage:
                def __init__(self):
                    class DummyChat:
                        def __init__(self):
                            self.id = int(config.ALLOWED_USER_IDS[0]) if config.ALLOWED_USER_IDS else 0
                    self.chat = DummyChat()
            main.run_sequential_shopee_search(DummyMessage(), keywords, target_devices, click_first_item=click_first_item, use_ai=False)
            
        self.run_in_thread(action)

    def run_par_search(self):
        click_first_item = False
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        mode = self.keyword_mode.get()
        
        if mode == "original":
            raw_text = self.txt_main_keywords.get("1.0", "end").strip()
            if not raw_text:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính!")
                return
            keywords = [line.strip() for line in raw_text.split("\n") if line.strip()]
            for kw in keywords:
                if any(ind in kw.lower() for ind in first_indicators):
                    click_first_item = True
                    break
            clean_keywords = []
            for kw in keywords:
                clean_kw = kw
                for ind in first_indicators:
                    clean_kw = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_kw, flags=re.IGNORECASE)
                clean_kw = re.sub(r"\s+", " ", clean_kw).strip()
                if clean_kw:
                    clean_keywords.append(clean_kw)
            keywords = clean_keywords
        else:
            ai_keywords_raw = self.txt_ai_keywords.get("1.0", "end").strip()
            if ai_keywords_raw:
                keywords = [line.strip() for line in ai_keywords_raw.split("\n") if line.strip()]
                for kw in keywords:
                    if any(ind in kw.lower() for ind in first_indicators):
                        click_first_item = True
                        break
            else:
                raw_text = self.txt_main_keywords.get("1.0", "end").strip()
                if not raw_text:
                    messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính trước khi chạy chế độ AI!")
                    return
                keywords = [line.strip() for line in raw_text.split("\n") if line.strip()]
                for kw in keywords:
                    if any(ind in kw.lower() for ind in first_indicators):
                        click_first_item = True
                        break
                clean_keywords = []
                for kw in keywords:
                    clean_kw = kw
                    for ind in first_indicators:
                        clean_kw = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_kw, flags=re.IGNORECASE)
                    clean_kw = re.sub(r"\s+", " ", clean_kw).strip()
                    if clean_kw:
                        clean_keywords.append(clean_kw)
                keywords = clean_keywords
            
        target_devices = self.parse_targets(entry_widget=self.ent_selection)
        if not target_devices:
            return
            
        def action():
            nonlocal keywords
            main.cancel_flag = False
            main.cancel_sequential = False
            if (mode == "ai" or mode == "ai_t2") and not ai_keywords_raw:
                def status_cb(msg):
                    self.log_message(f"[Gemini AI] {msg}")
                if mode == "ai":
                    expanded = config.generate_keywords_via_gemini(
                        config.GEMINI_API_KEY, 
                        keywords, 
                        status_cb=status_cb
                    )
                else:
                    expanded = config.generate_keywords_tier2_via_gemini(
                        config.GEMINI_API_KEY,
                        keywords,
                        status_cb=status_cb
                    )
                if click_first_item:
                    expanded = [f"{k} video" for k in expanded]
                keywords = expanded
                self.txt_ai_keywords.delete("1.0", "end")
                for k in keywords:
                    self.txt_ai_keywords.insert("end", f"{k}\n")
            
            keyword_str = ", ".join(keywords)
            print(f"[GUI] Bắt đầu tìm kiếm song song (Mở rộng từ Gemini) trên {len(target_devices)} máy...")
            
            if config.ALLOWED_USER_IDS:
                try:
                    main.bot.send_message(
                        config.ALLOWED_USER_IDS[0],
                        f"🚀 **[GUI] BẮT ĐẦU CHẠY SONG SONG SHOPEE**\n\n"
                        f"Từ khóa chính: `{', '.join(keywords)}`\n"
                        f"Từ khóa mở rộng (Gemini): Có {len(keywords)} từ khóa\n"
                        f"Tổng số máy: {len(target_devices)} máy\n"
                        f"Chế độ click đầu tiên: **{click_first_item}**"
                    )
                except Exception:
                    pass
            
            def run_search_parallel(device_id):
                devices = main.get_ordered_devices()
                dev_idx = devices.index(device_id) + 1
                current_keyword = random.choice(keywords)
                print(f"[Máy {dev_idx}] Bắt đầu tìm kiếm với từ khóa '{current_keyword}'...")
                
                success, err = main.adb.shopee_find_and_click_lamdong(
                    device_id, 
                    current_keyword, 
                    is_cancelled=lambda: main.cancel_flag or main.cancel_sequential, 
                    click_first_item=click_first_item
                )
                if success:
                    print(f"[Máy {dev_idx}] ✅ Hoàn thành trọn vẹn quy trình (Lướt sản phẩm & dạo Shop) với từ khóa '{current_keyword}'!")
                    if config.ALLOWED_USER_IDS:
                        try:
                            main.bot.send_message(
                                config.ALLOWED_USER_IDS[0], 
                                f"✅ **Máy {dev_idx}**: Đã hoàn thành trọn vẹn quy trình với từ khóa `{current_keyword}`!"
                            )
                        except Exception:
                            pass
                else:
                    print(f"[Máy {dev_idx}] ❌ Thất bại: {err}")
                    if config.ALLOWED_USER_IDS:
                        try:
                            main.bot.send_message(config.ALLOWED_USER_IDS[0], f"❌ **Máy {dev_idx}**: {err}")
                        except Exception:
                            pass
                return dev_idx, current_keyword, success, err
                
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                futures = [executor.submit(run_search_parallel, dev) for dev in target_devices]
                results = [f.result() for f in futures]
                
            success_count = sum(1 for r in results if r[2])
            fail_count = len(results) - success_count
            
            summary = f"🏁 **[GUI] KẾT QUẢ TÌM SHOPEE (SONG SONG):**\n\n"
            summary += f"✅ Hoàn thành trọn vẹn: **{success_count}/{len(target_devices)} máy**\n"
            if fail_count > 0:
                summary += f"❌ Thất bại: **{fail_count} máy**\n"
                fails_list = [f"Máy {r[0]} ({r[1]}): {r[3]}" for r in results if not r[2]]
                summary += f"⚠️ Chi tiết lỗi:\n" + "\n".join(fails_list)
                
            print("[GUI] Tiến trình tìm kiếm song song Shopee kết thúc.")
            if config.ALLOWED_USER_IDS:
                try:
                    main.bot.send_message(config.ALLOWED_USER_IDS[0], summary, parse_mode="Markdown")
                except Exception:
                    pass
            
        self.run_in_thread(action)

    # ================= CÁC TÁC VỤ BƠM TIKTOK =================
    def run_seq_tiktok(self):
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

        self.bulk_disable_rotation(target_devices=target_devices)
        main.cancel_flag = False
        main.cancel_sequential = False

        print(f"[GUI] Bắt đầu chạy TikTok Tuần Tự trên {len(target_devices)} máy...")

        def action():
            success_count = 0
            tracker = None
            chat_id = config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None
            if chat_id:
                try:
                    tracker = main.TelegramRealtimeTracker(main.bot, chat_id)
                    tracker.start_dashboard(
                        f"🎵 **[GUI] TIKTOK TUẦN TỰ**\n"
                        f"Kênh: `{channel}`\n"
                        f"Thiết bị: **{len(target_devices)} máy**"
                    )
                except Exception as exc:
                    print(f"[GUI] Không khởi tạo được Telegram Tracker TikTok: {exc}")
                    tracker = None

            for idx, dev in enumerate(target_devices):
                if main.is_cancelled():
                    print("[GUI] ⏹️ Tiến trình TikTok đã bị dừng.")
                    break
                dev_name = main.get_device_name(dev)
                print(f"[GUI] TikTok -> Máy {dev_name} ({idx+1}/{len(target_devices)})")

                if tracker:
                    tracker.set_active_device(
                        dev_name,
                        dev,
                        f"TikTok: {channel}",
                        idx + 1,
                        len(target_devices),
                        platform="TikTok",
                    )

                def tt_status_cb(d, msg):
                    self.log_message(f"[{msg}]")
                    if tracker:
                        tracker.status_callback(d, msg)

                dev_start = time.time()
                success, message = main.adb.tiktok_automation_workflow(
                    dev, 
                    seed_keywords=seed_raw, 
                    target_channel=channel, 
                    status_callback=tt_status_cb,
                    is_cancelled=main.is_cancelled
                )
                dev_duration = time.time() - dev_start
                if success:
                    success_count += 1
                else:
                    print(f"[GUI] ❌ TikTok máy {dev_name} THẤT BẠI: {message}")
                if chat_id:
                    try:
                        main.send_device_finished_card(
                            chat_id,
                            dev_name,
                            dev,
                            f"TikTok: {channel}",
                            success,
                            message,
                            dev_duration,
                        )
                    except Exception:
                        pass

            if success_count == len(target_devices):
                print("[GUI] 🏁 Hoàn tất tiến trình chạy TikTok Tuần Tự!")
            else:
                print(
                    f"[GUI] ❌ TikTok Tuần Tự KẾT THÚC CÓ LỖI: "
                    f"{success_count}/{len(target_devices)} máy thành công."
                )
            if tracker:
                tracker.finish_dashboard(
                    f"🏁 **[GUI] TIKTOK TUẦN TỰ: "
                    f"{success_count}/{len(target_devices)} MÁY THÀNH CÔNG**"
                )

        self.run_in_thread(action)

    def run_par_tiktok(self):
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

        self.bulk_disable_rotation(target_devices=target_devices)
        main.cancel_flag = False
        main.cancel_sequential = False

        print(f"[GUI] Bắt đầu chạy TikTok Song Song trên {len(target_devices)} máy...")

        def run_parallel_tt(device_id):
            dev_name = main.get_device_name(device_id)
            chat_id = config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None
            tracker = None
            if chat_id:
                try:
                    tracker = main.TelegramRealtimeTracker(main.bot, chat_id)
                    tracker.start_dashboard(
                        f"🎵 **[GUI] TIKTOK SONG SONG • MÁY {dev_name}**\n"
                        f"Kênh: `{channel}`"
                    )
                    tracker.set_active_device(
                        dev_name,
                        device_id,
                        f"TikTok: {channel}",
                        1,
                        1,
                        platform="TikTok",
                    )
                except Exception:
                    tracker = None

            def tt_status_cb(d, msg):
                self.log_message(f"[Máy {dev_name}] {msg}")
                if tracker:
                    tracker.status_callback(d, msg)

            dev_start = time.time()
            success, message = main.adb.tiktok_automation_workflow(
                device_id, 
                seed_keywords=seed_raw, 
                target_channel=channel, 
                status_callback=tt_status_cb,
                is_cancelled=main.is_cancelled
            )
            duration = time.time() - dev_start
            if tracker:
                tracker.finish_dashboard(
                    (
                        f"✅ **MÁY {dev_name} HOÀN THÀNH TIKTOK**"
                        if success
                        else f"❌ **MÁY {dev_name} TIKTOK THẤT BẠI**\n`{message}`"
                    )
                )
            if chat_id:
                try:
                    main.send_device_finished_card(
                        chat_id,
                        dev_name,
                        device_id,
                        f"TikTok: {channel}",
                        success,
                        message,
                        duration,
                    )
                except Exception:
                    pass
            return dev_name, success, message

        def action():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                results = list(executor.map(run_parallel_tt, target_devices))

            success_count = sum(1 for _, success, _ in results if success)
            for dev_name, success, message in results:
                if not success:
                    print(f"[GUI] ❌ TikTok máy {dev_name} THẤT BẠI: {message}")

            if success_count == len(target_devices):
                print("[GUI] 🏁 Hoàn tất tiến trình chạy TikTok Song Song!")
            else:
                print(
                    f"[GUI] ❌ TikTok Song Song KẾT THÚC CÓ LỖI: "
                    f"{success_count}/{len(target_devices)} máy thành công."
                )

        self.run_in_thread(action)

    def log_message(self, msg):
        print(f"[GUI] {msg}")

    def generate_ai_keywords_action(self):
        raw_text = self.txt_main_keywords.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính trước!")
            return
            
        gemini_key = self.ent_gemini_key.get().strip()
        if not gemini_key:
            gemini_key = config.GEMINI_API_KEY
            
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        keywords = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not keywords:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính hợp lệ!")
            return
            
        click_first_item = False
        clean_keywords = []
        for kw in keywords:
            if any(ind in kw.lower() for ind in first_indicators):
                click_first_item = True
            clean_kw = kw
            for ind in first_indicators:
                clean_kw = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_kw, flags=re.IGNORECASE)
            clean_kw = re.sub(r"\s+", " ", clean_kw).strip()
            if clean_kw:
                clean_keywords.append(clean_kw)
        keywords = clean_keywords
        
        self.log_message(f"Đang gửi yêu cầu sinh từ khóa Tầng 1 (Gemini AI) cho {len(keywords)} từ khóa...")
        self.btn_gen_ai.configure(state="disabled", text="🪄 Đang sinh từ khóa...")
        
        def action():
            try:
                def status_cb(msg):
                    self.log_message(msg)
                    
                expanded = config.generate_keywords_via_gemini(gemini_key, keywords, status_cb=status_cb)
                
                # Hiển thị lên Textbox
                self.txt_ai_keywords.delete("1.0", "end")
                for kw in expanded:
                    kw_to_insert = kw
                    if click_first_item:
                        kw_to_insert = f"{kw} video"
                    self.txt_ai_keywords.insert("end", f"{kw_to_insert}\n")
                    
                self.log_message(f"Đã hiển thị {len(expanded)} từ khóa lên giao diện.")
            except Exception as e:
                self.log_message(f"Gặp lỗi khi sinh từ khóa: {e}")
            finally:
                self.btn_gen_ai.configure(state="normal", text="🪄 Sinh từ khóa Tầng 1 (Mở rộng SEO)")
                
        self.run_in_thread(action)

    def generate_ai_keywords_tier2_action(self):
        raw_text = self.txt_main_keywords.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập các tiêu đề thô Shopee trong ô từ khóa chính!")
            return
            
        gemini_key = self.ent_gemini_key.get().strip()
        if not gemini_key:
            gemini_key = config.GEMINI_API_KEY
            
        first_indicators = ["video", "đầu", "đầu tiên", "top 1", "top1"]
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập các tiêu đề thô hợp lệ!")
            return
            
        click_first_item = False
        clean_titles = []
        for title in lines:
            if any(ind in title.lower() for ind in first_indicators):
                click_first_item = True
            clean_title = title
            for ind in first_indicators:
                clean_title = re.sub(r"\b" + re.escape(ind) + r"\b", "", clean_title, flags=re.IGNORECASE)
            clean_title = re.sub(r"\s+", " ", clean_title).strip()
            if clean_title:
                clean_titles.append(clean_title)
        
        self.log_message(f"Đang gửi yêu cầu sinh từ khóa Tầng 2 cho {len(clean_titles)} tiêu đề sản phẩm...")
        self.btn_gen_ai_t2.configure(state="disabled", text="🪄 Đang sinh từ khóa Tầng 2...")
        
        def action():
            try:
                def status_cb(msg):
                    self.log_message(msg)
                    
                expanded = config.generate_keywords_tier2_via_gemini(gemini_key, clean_titles, status_cb=status_cb)
                
                # Hiển thị lên Textbox
                self.txt_ai_keywords.delete("1.0", "end")
                for kw in expanded:
                    kw_to_insert = kw
                    if click_first_item:
                        kw_to_insert = f"{kw} video"
                    self.txt_ai_keywords.insert("end", f"{kw_to_insert}\n")
                    
                self.log_message(f"Đã hiển thị tổng cộng {len(expanded)} từ khóa Tầng 2 lên giao diện cho {len(clean_titles)} sản phẩm!")
            except Exception as e:
                self.log_message(f"Gặp lỗi khi sinh từ khóa Tầng 2: {e}")
            finally:
                self.btn_gen_ai_t2.configure(state="normal", text="🧠 Sinh từ khóa Tầng 2 (Bóc tách Tiêu đề thô)")
                
        self.run_in_thread(action)

    def start_bot_service(self):
        def run():
            print("[Hệ thống] Bot Telegram đang khởi động dưới nền...")
            skip_pending_on_start = True
            while True:
                try:
                    if config.TELEGRAM_BOT_TOKEN:
                        skip_pending = skip_pending_on_start
                        skip_pending_on_start = False
                        main.bot.polling(
                            none_stop=True,
                            skip_pending=skip_pending,
                            interval=1,
                            timeout=20,
                        )
                    else:
                        time.sleep(5)
                except Exception as e:
                    print(f"[Lỗi Bot] Lỗi kết nối Telegram, đang nạp lại sau 5s... Lỗi: {e}")
                    time.sleep(5)
        self.run_in_thread(run)


class ConsoleRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.buffer = ""

    def write(self, string):
        self.buffer += string
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._append_line(line)

    def _append_line(self, line):
        if not line:
            return
        def append():
            try:
                self.text_widget.configure(state="normal")
                self.text_widget.insert("end", line + "\n")
                self.text_widget.see("end")
                self.text_widget.configure(state="disabled")
            except Exception:
                pass
        if threading.current_thread() is threading.main_thread():
            append()
        else:
            try:
                self.text_widget.after(0, append)
            except Exception:
                pass

    def flush(self):
        if self.buffer:
            self._append_line(self.buffer)
            self.buffer = ""

if __name__ == "__main__":
    app = GUIApp()
    app.mainloop()

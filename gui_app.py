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

# Thiết lập giao diện CustomTkinter Sáng Sang Trọng (Light Mode Dashboard)
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🤖 KHẢI HOÁN SYSTEM - PRO AUTOMATION CONTROL CENTER 📱")
        self.geometry("1300x880")
        self.configure(fg_color="#f1f5f9") # Soft Slate Light Background
        
        # Thiết lập app icon bitmap
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        
        # Lưu trữ các biến Checkbox điều khiển hàng loạt
        self.device_checkboxes = {}
        
        # Grid layout 1x2 (Cột trái: Dashboard cấu hình & điều khiển, Cột phải: Monitor Grid quản lý máy)
        self.grid_columnconfigure(0, weight=0, minsize=460)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # ================= LEFT DASHBOARD PANEL (Cuộn tránh tràn màn hình) =================
        self.left_panel = ctk.CTkScrollableFrame(
            self, 
            width=445, 
            corner_radius=16, 
            fg_color="#ffffff", 
            border_width=1, 
            border_color="#cbd5e1",
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8"
        )
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=16)
        
        # Header Banner Cá nhân hóa (Light Premium Banner)
        self.brand_badge = ctk.CTkFrame(self.left_panel, fg_color="#eff6ff", corner_radius=14, border_width=1, border_color="#bfdbfe")
        self.brand_badge.pack(fill="x", padx=16, pady=(12, 10))
        
        self.lbl_brand = ctk.CTkLabel(
            self.brand_badge, 
            text="⚡ KHẢI HOÁN AUTOMATION ⚡", 
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color="#1d4ed8"
        )
        self.lbl_brand.pack(pady=(10, 2), padx=16, anchor="w")
        
        self.lbl_sub_brand = ctk.CTkLabel(
            self.brand_badge, 
            text="Box Phone System Pro • Tự Động Hóa Shopee", 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#475569"
        )
        self.lbl_sub_brand.pack(pady=(0, 10), padx=16, anchor="w")
        
        # Phân đoạn 1: Cấu hình hệ thống & Kết nối
        self.settings_card = ctk.CTkFrame(self.left_panel, fg_color="#f8fafc", corner_radius=14, border_width=1, border_color="#e2e8f0")
        self.settings_card.pack(fill="x", padx=16, pady=6)
        
        self.lbl_settings = ctk.CTkLabel(
            self.settings_card, 
            text="⚙️ Cấu hình hệ thống & Kết nối", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_settings.pack(pady=(10, 4), padx=16, anchor="w")
        
        self.ent_token = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Telegram Bot Token (629xxxxxx:...)", 
            show="*",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_token.pack(fill="x", padx=16, pady=3)
        self.ent_token.insert(0, config.TELEGRAM_BOT_TOKEN or "")
        
        admin_ids_str = ",".join(map(str, config.ALLOWED_USER_IDS or []))
        self.ent_admins = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Allowed Admin IDs (Cách nhau bởi dấu phẩy)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_admins.pack(fill="x", padx=16, pady=3)
        self.ent_admins.insert(0, admin_ids_str)
        
        self.ent_adb = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Đường dẫn ADB (Ví dụ: C:\\adb.exe)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_adb.pack(fill="x", padx=16, pady=3)
        self.ent_adb.insert(0, config.ADB_PATH or "")

        self.ent_shops = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Tên các Shop dự phòng (Cách nhau bởi dấu phẩy)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_shops.pack(fill="x", padx=16, pady=3)
        shops_str = ",".join(config.SHOPEE_SHOP_NAMES or [])
        self.ent_shops.insert(0, shops_str)

        self.ent_gemini_key = ctk.CTkEntry(
            self.settings_card, 
            placeholder_text="Gemini API Key",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_gemini_key.pack(fill="x", padx=16, pady=3)
        self.ent_gemini_key.insert(0, config.GEMINI_API_KEY or "")
        
        self.btn_save = ctk.CTkButton(
            self.settings_card, 
            text="💾 Lưu cấu hình hệ thống", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#4f46e5", 
            hover_color="#4338ca",
            text_color="#ffffff",
            corner_radius=8,
            height=32,
            command=self.save_settings
        )
        self.btn_save.pack(fill="x", padx=16, pady=(8, 12))
        
        # Phân đoạn 2: Bảng tác vụ tự động Shopee
        self.tasks_card = ctk.CTkFrame(self.left_panel, fg_color="#f8fafc", corner_radius=14, border_width=1, border_color="#e2e8f0")
        self.tasks_card.pack(fill="x", padx=16, pady=6)
        
        self.lbl_tasks = ctk.CTkLabel(
            self.tasks_card, 
            text="🛒 Điều khiển Tác vụ Tự động hóa Shopee", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_tasks.pack(pady=(10, 4), padx=16, anchor="w")
        
        self.lbl_main_keywords = ctk.CTkLabel(
            self.tasks_card,
            text="📌 Từ khóa chính Shopee (Mỗi dòng 1 từ khóa):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#334155"
        )
        self.lbl_main_keywords.pack(padx=16, pady=(2, 0), anchor="w")

        self.txt_main_keywords = ctk.CTkTextbox(
            self.tasks_card, 
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            border_width=1,
            corner_radius=8,
            height=75,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.txt_main_keywords.pack(fill="x", padx=16, pady=3)
        
        # Lựa chọn chế độ từ khóa (Segmented Light Radio Group)
        self.keyword_mode = ctk.StringVar(value="original")
        self.mode_frame = ctk.CTkFrame(self.tasks_card, fg_color="#f1f5f9", corner_radius=8, border_width=1, border_color="#e2e8f0")
        self.mode_frame.pack(fill="x", padx=16, pady=5)
        
        self.rad_orig = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Gốc (Không AI)", 
            variable=self.keyword_mode, 
            value="original",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#1e293b",
            fg_color="#2563eb",
            hover_color="#1d4ed8"
        )
        self.rad_orig.pack(side="left", padx=(8, 4), pady=6)
        
        self.rad_ai = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Mở rộng (AI)", 
            variable=self.keyword_mode, 
            value="ai",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#1e293b",
            fg_color="#8b5cf6",
            hover_color="#7c3aed"
        )
        self.rad_ai.pack(side="left", padx=4, pady=6)

        self.rad_ai_t2 = ctk.CTkRadioButton(
            self.mode_frame, 
            text="Tầng 2 (AI sinh)", 
            variable=self.keyword_mode, 
            value="ai_t2",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#1e293b",
            fg_color="#a855f7",
            hover_color="#9333ea"
        )
        self.rad_ai_t2.pack(side="left", padx=(4, 8), pady=6)
        
        # Nút sinh từ khóa qua AI
        self.btn_gen_ai = ctk.CTkButton(
            self.tasks_card,
            text="🪄 Sinh từ khóa Tầng 1 (Mở rộng SEO)",
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
            self.tasks_card,
            text="🧠 Sinh từ khóa Tầng 2 (Bóc tách Tiêu đề thô)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            text_color="#ffffff",
            corner_radius=8,
            height=30,
            command=self.generate_ai_keywords_tier2_action
        )
        self.btn_gen_ai_t2.pack(fill="x", padx=16, pady=2)
        
        # Textbox hiển thị danh sách từ khóa AI
        self.lbl_ai_keywords = ctk.CTkLabel(
            self.tasks_card,
            text="🤖 Từ khóa ngẫu nhiên (AI Generated):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#334155"
        )
        self.lbl_ai_keywords.pack(padx=16, pady=(4, 0), anchor="w")
        
        self.txt_ai_keywords = ctk.CTkTextbox(
            self.tasks_card,
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0284c7",
            border_width=1,
            corner_radius=8,
            height=95,
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.txt_ai_keywords.pack(fill="x", padx=16, pady=3)
        
        self.ent_selection = ctk.CTkEntry(
            self.tasks_card, 
            placeholder_text="Chọn máy chạy Shopee (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=34
        )
        self.ent_selection.pack(fill="x", padx=16, pady=3)
        
        # Panel nút chạy tác vụ Shopee
        self.btn_grid = ctk.CTkFrame(self.tasks_card, fg_color="transparent")
        self.btn_grid.pack(fill="x", padx=16, pady=(6, 8))
        self.btn_grid.columnconfigure(0, weight=1)
        self.btn_grid.columnconfigure(1, weight=1)
        
        self.btn_seq = ctk.CTkButton(
            self.btn_grid, 
            text="▶️ Chạy Tuần Tự Shopee", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#10b981", 
            hover_color="#059669",
            text_color="#ffffff",
            corner_radius=8,
            height=36,
            command=self.run_seq_search
        )
        self.btn_seq.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        
        self.btn_par = ctk.CTkButton(
            self.btn_grid, 
            text="⚡ Chạy Song Song Shopee", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#2563eb", 
            hover_color="#1d4ed8",
            text_color="#ffffff",
            corner_radius=8,
            height=36,
            command=self.run_par_search
        )
        self.btn_par.grid(row=0, column=1, padx=(3, 0), sticky="ew")
        
        self.btn_stop = ctk.CTkButton(
            self.tasks_card, 
            text="🛑 DỪNG SHOPEE KHẨN CẤP", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#ef4444", 
            hover_color="#dc2626",
            text_color="#ffffff",
            border_width=1,
            border_color="#f87171",
            corner_radius=8,
            height=38,
            command=self.stop_all
        )
        self.btn_stop.pack(fill="x", padx=16, pady=(0, 12))

        # Phân đoạn 2.5: Bảng điều khiển tác vụ Bơm TikTok 3 Bước (TÁCH BIỆT HOÀN TOÀN)
        self.tiktok_card = ctk.CTkFrame(self.left_panel, fg_color="#f8fafc", corner_radius=14, border_width=1, border_color="#e2e8f0")
        self.tiktok_card.pack(fill="x", padx=16, pady=6)
        
        self.lbl_tiktok_title = ctk.CTkLabel(
            self.tiktok_card, 
            text="🎵 Điều khiển Tác vụ Bơm TikTok 3 Bước", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_tiktok_title.pack(pady=(10, 4), padx=16, anchor="w")

        self.lbl_tt_seed = ctk.CTkLabel(
            self.tiktok_card,
            text="📌 Từ khóa nhiệm vụ (Mồi kênh - Phẩy cách):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#334155"
        )
        self.lbl_tt_seed.pack(padx=16, pady=(2, 0), anchor="w")

        self.ent_tt_seed = ctk.CTkEntry(
            self.tiktok_card,
            placeholder_text="skincare, trị mụn, nặn mụn, chăm sóc da",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=32
        )
        self.ent_tt_seed.insert(0, config.TIKTOK_SEED_KEYWORDS_DEFAULT)
        self.ent_tt_seed.pack(fill="x", padx=16, pady=3)

        self.lbl_tt_channel = ctk.CTkLabel(
            self.tiktok_card,
            text="🎯 Tên Kênh TikTok mục tiêu:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#334155"
        )
        self.lbl_tt_channel.pack(padx=16, pady=(4, 0), anchor="w")

        self.ent_tt_channel = ctk.CTkEntry(
            self.tiktok_card,
            placeholder_text="Khải Hoàn Skincare PT",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=32
        )
        self.ent_tt_channel.insert(0, config.TIKTOK_TARGET_CHANNEL_DEFAULT)
        self.ent_tt_channel.pack(fill="x", padx=16, pady=3)

        # Cài đặt thời gian dừng xem video (Min - Max)
        self.lbl_tt_delay = ctk.CTkLabel(
            self.tiktok_card,
            text="⏱️ Thời gian lướt video (Giây Min - Max):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#334155"
        )
        self.lbl_tt_delay.pack(padx=16, pady=(4, 0), anchor="w")

        self.delay_frame = ctk.CTkFrame(self.tiktok_card, fg_color="transparent")
        self.delay_frame.pack(fill="x", padx=16, pady=2)
        self.delay_frame.columnconfigure(0, weight=1)
        self.delay_frame.columnconfigure(1, weight=1)

        self.ent_tt_min_delay = ctk.CTkEntry(
            self.delay_frame,
            placeholder_text="Min (giây)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            corner_radius=8,
            height=30
        )
        self.ent_tt_min_delay.insert(0, str(config.TIKTOK_WATCH_TIME_MIN_DEFAULT))
        self.ent_tt_min_delay.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.ent_tt_max_delay = ctk.CTkEntry(
            self.delay_frame,
            placeholder_text="Max (giây)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            corner_radius=8,
            height=30
        )
        self.ent_tt_max_delay.insert(0, str(config.TIKTOK_WATCH_TIME_MAX_DEFAULT))
        self.ent_tt_max_delay.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Ô chọn máy chạy TikTok riêng biệt
        self.ent_tt_selection = ctk.CTkEntry(
            self.tiktok_card, 
            placeholder_text="Chọn máy chạy TikTok (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            fg_color="#ffffff",
            border_color="#cbd5e1",
            text_color="#0f172a",
            placeholder_text_color="#94a3b8",
            corner_radius=8,
            height=32
        )
        self.ent_tt_selection.pack(fill="x", padx=16, pady=(6, 3))

        # Nút bấm chạy TikTok Tuần tự / Song song
        self.tt_btn_grid = ctk.CTkFrame(self.tiktok_card, fg_color="transparent")
        self.tt_btn_grid.pack(fill="x", padx=16, pady=(6, 4))
        self.tt_btn_grid.columnconfigure(0, weight=1)
        self.tt_btn_grid.columnconfigure(1, weight=1)

        self.btn_tt_seq = ctk.CTkButton(
            self.tt_btn_grid,
            text="▶️ Chạy TikTok Tuần Tự",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            text_color="#ffffff",
            corner_radius=8,
            height=34,
            command=self.run_seq_tiktok
        )
        self.btn_tt_seq.grid(row=0, column=0, padx=(0, 3), sticky="ew")

        self.btn_tt_par = ctk.CTkButton(
            self.tt_btn_grid,
            text="⚡ Chạy TikTok Song Song",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            text_color="#ffffff",
            corner_radius=8,
            height=34,
            command=self.run_par_tiktok
        )
        self.btn_tt_par.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        # Nút dừng TikTok khẩn cấp riêng biệt
        self.btn_tt_stop = ctk.CTkButton(
            self.tiktok_card, 
            text="🛑 DỪNG TIKTOK KHẨN CẤP", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#ef4444", 
            hover_color="#dc2626",
            text_color="#ffffff",
            border_width=1,
            border_color="#f87171",
            corner_radius=8,
            height=36,
            command=self.stop_all
        )
        self.btn_tt_stop.pack(fill="x", padx=16, pady=(4, 10))
        
        # Phân đoạn 3: Bảng điều khiển hàng loạt thủ công
        self.bulk_card = ctk.CTkFrame(self.left_panel, fg_color="#f8fafc", corner_radius=14, border_width=1, border_color="#e2e8f0")
        self.bulk_card.pack(fill="x", padx=16, pady=6)
        
        self.lbl_bulk = ctk.CTkLabel(
            self.bulk_card, 
            text="🛠️ Điều khiển hàng loạt (Máy đã tích)", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_bulk.pack(pady=(10, 4), padx=16, anchor="w")
        
        # Hàng nút Chọn tất cả / Bỏ chọn
        self.select_options_frame = ctk.CTkFrame(self.bulk_card, fg_color="transparent")
        self.select_options_frame.pack(fill="x", padx=16, pady=2)
        self.select_options_frame.columnconfigure(0, weight=1)
        self.select_options_frame.columnconfigure(1, weight=1)
        
        self.btn_select_all = ctk.CTkButton(
            self.select_options_frame,
            text="☑️ Chọn tất cả",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=28,
            corner_radius=6,
            command=self.select_all_devices
        )
        self.btn_select_all.grid(row=0, column=0, padx=(0, 2), sticky="ew")
        
        self.btn_deselect_all = ctk.CTkButton(
            self.select_options_frame,
            text="⬜ Bỏ chọn",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=28,
            corner_radius=6,
            command=self.deselect_all_devices
        )
        self.btn_deselect_all.grid(row=0, column=1, padx=(2, 0), sticky="ew")
        
        # Hàng nút điều khiển chung Hàng 1
        self.bulk_row1 = ctk.CTkFrame(self.bulk_card, fg_color="transparent")
        self.bulk_row1.pack(fill="x", padx=16, pady=(6, 3))
        for i in range(3):
            self.bulk_row1.columnconfigure(i, weight=1)
            
        self.btn_bulk_home = ctk.CTkButton(
            self.bulk_row1,
            text="🏠 Trang chủ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=30,
            corner_radius=6,
            command=lambda: self.bulk_keyevent(3)
        )
        self.btn_bulk_home.grid(row=0, column=0, padx=2, sticky="ew")
        
        self.btn_bulk_back = ctk.CTkButton(
            self.bulk_row1,
            text="↩️ Back",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=30,
            corner_radius=6,
            command=lambda: self.bulk_keyevent(4)
        )
        self.btn_bulk_back.grid(row=0, column=1, padx=2, sticky="ew")
        
        self.btn_bulk_rot = ctk.CTkButton(
            self.bulk_row1,
            text="🔄 Tắt xoay",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=30,
            corner_radius=6,
            command=lambda: self.bulk_disable_rotation()
        )
        self.btn_bulk_rot.grid(row=0, column=2, padx=2, sticky="ew")

        # Hàng thứ 2
        self.bulk_row2 = ctk.CTkFrame(self.bulk_card, fg_color="transparent")
        self.bulk_row2.pack(fill="x", padx=16, pady=(3, 12))
        for i in range(4):
            self.bulk_row2.columnconfigure(i, weight=1)
            
        self.btn_bulk_cap = ctk.CTkButton(
            self.bulk_row2,
            text="📸 Chụp",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color="#1e293b",
            height=30,
            corner_radius=6,
            command=self.bulk_screenshot
        )
        self.btn_bulk_cap.grid(row=0, column=0, padx=2, sticky="ew")
        
        self.btn_bulk_open = ctk.CTkButton(
            self.bulk_row2,
            text="🛒 Shopee",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#ee4d2d",
            hover_color="#d73c1f",
            text_color="#ffffff",
            height=30,
            corner_radius=6,
            command=self.bulk_open_shopee
        )
        self.btn_bulk_open.grid(row=0, column=1, padx=2, sticky="ew")
        
        self.btn_bulk_close = ctk.CTkButton(
            self.bulk_row2,
            text="🛑 Tắt App",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            text_color="#ffffff",
            height=30,
            corner_radius=6,
            command=self.bulk_close_shopee
        )
        self.btn_bulk_close.grid(row=0, column=2, padx=2, sticky="ew")
        
        self.btn_bulk_reboot = ctk.CTkButton(
            self.bulk_row2,
            text="⚡ Reboot",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#ffffff",
            height=30,
            corner_radius=6,
            command=self.bulk_reboot
        )
        self.btn_bulk_reboot.grid(row=0, column=3, padx=2, sticky="ew")
        
        # Phân đoạn 4: Khung Terminal Log (High contrast slate console)
        self.lbl_log = ctk.CTkLabel(
            self.left_panel, 
            text="📟 Nhật ký hoạt động (Real-time Console)", 
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_log.pack(padx=20, anchor="w", pady=(10, 2))
        
        self.log_box = ctk.CTkTextbox(
            self.left_panel, 
            height=130, 
            state="disabled",
            fg_color="#0f172a", 
            text_color="#06b6d4", 
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1,
            border_color="#cbd5e1",
            corner_radius=10
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        
        # Redirect standard output
        sys.stdout = ConsoleRedirector(self.log_box)
        sys.stderr = ConsoleRedirector(self.log_box)
        
        # ================= RIGHT MONITOR GRID PANEL =================
        self.right_panel = ctk.CTkFrame(self, corner_radius=16, fg_color="#ffffff", border_width=1, border_color="#cbd5e1")
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=16)
        
        self.right_panel.grid_rowconfigure(0, weight=0)
        self.right_panel.grid_rowconfigure(1, weight=1)
        self.right_panel.grid_columnconfigure(0, weight=1)
        
        # Header right panel
        self.header_frame = ctk.CTkFrame(self.right_panel, height=64, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=16)
        
        self.lbl_devices = ctk.CTkLabel(
            self.header_frame, 
            text="📱 QUẢN LÝ THIẾT BỊ BOX PHONE (20 DEVICE SLOTS)", 
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#0f172a"
        )
        self.lbl_devices.pack(side="left")
        
        self.btn_refresh = ctk.CTkButton(
            self.header_frame, 
            text="🔄 Quét & Tải lại máy", 
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=150,
            height=34,
            fg_color="#e2e8f0", 
            hover_color="#cbd5e1",
            text_color="#0f172a",
            border_width=1,
            border_color="#cbd5e1",
            corner_radius=8,
            command=self.load_devices_grid
        )
        self.btn_refresh.pack(side="right")
        
        # Scrollable grid frame for devices
        self.grid_frame = ctk.CTkScrollableFrame(
            self.right_panel, 
            fg_color="#f8fafc", 
            corner_radius=12,
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8"
        )
        self.grid_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        
        # Configure columns inside grid frame
        for col in range(4):
            self.grid_frame.grid_columnconfigure(col, weight=1, minsize=190)
            
        self.load_devices_grid()
        
        # Khởi chạy bot Telegram ở luồng phụ
        self.start_bot_service()

    def run_in_thread(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

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

    def load_devices_grid(self):
        # Dọn dẹp grid cũ và dictionary checkbox cũ
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.device_checkboxes.clear()
            
        print("[Hệ thống] Đang quét các cổng thiết bị...")
        devices = main.get_ordered_devices()
        
        if not devices:
            lbl_empty = ctk.CTkLabel(
                self.grid_frame, 
                text="❌ Không tìm thấy thiết bị nào đang kết nối.\nHãy kiểm tra lại kết nối cáp USB và ADB.", 
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color="#ef4444"
            )
            lbl_empty.grid(row=0, column=0, columnspan=4, pady=140)
            return

        # Tự động tắt xoay hàng loạt cho tất cả các máy vừa phát hiện được
        self.bulk_disable_rotation(devices)

        for idx, dev in enumerate(devices):
            row = idx // 4
            col = idx % 4
            
            # Khởi tạo card máy phong cách Light Elevation
            card = ctk.CTkFrame(
                self.grid_frame, 
                border_width=1, 
                border_color="#cbd5e1", 
                fg_color="#ffffff", 
                corner_radius=14
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            card.columnconfigure(0, weight=1)
            
            # Hiệu ứng Hover viền Royal Blue mượt mà
            card.bind("<Enter>", lambda e, c=card: c.configure(border_color="#2563eb"))
            card.bind("<Leave>", lambda e, c=card: c.configure(border_color="#cbd5e1"))
            
            # Checkbox trạng thái tích chọn điều khiển hàng loạt
            cb_var = tk.BooleanVar(value=False)
            self.device_checkboxes[dev] = cb_var
            
            # Header frame chứa checkbox bên trái và chấm trạng thái bên phải
            header_frame = ctk.CTkFrame(card, fg_color="transparent")
            header_frame.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="ew")
            header_frame.columnconfigure(0, weight=1)
            
            cb_select = ctk.CTkCheckBox(
                header_frame,
                text=f"Máy {main.get_device_name(dev)}",
                variable=cb_var,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color="#0f172a",
                fg_color="#2563eb",
                hover_color="#1d4ed8",
                corner_radius=4,
                border_width=2
            )
            cb_select.grid(row=0, column=0, sticky="w")
            
            # Chấm Online phát sáng Xanh Emerald
            lbl_online = ctk.CTkLabel(
                header_frame,
                text="● Online",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color="#059669"
            )
            lbl_online.grid(row=0, column=1, sticky="e")
            
            lbl_id = ctk.CTkLabel(
                card, 
                text=f"ID: {dev[:12]}...", 
                text_color="#64748b", 
                font=ctk.CTkFont(family="Segoe UI", size=11)
            )
            lbl_id.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")
            
            # Panel nút bấm hành động tinh tế
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=2, column=0, padx=8, pady=(0, 10), sticky="ew")
            
            btn_frame.columnconfigure(0, weight=1)
            btn_frame.columnconfigure(1, weight=1)
            btn_frame.columnconfigure(2, weight=1)
            
            # Nút chụp ảnh
            btn_cap = ctk.CTkButton(
                btn_frame, 
                text="📸 Chụp", 
                width=45, 
                height=26,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#e2e8f0", 
                hover_color="#cbd5e1",
                text_color="#1e293b",
                corner_radius=6,
                command=lambda d=dev: self.screenshot_device(d, main.get_device_name(d))
            )
            btn_cap.grid(row=0, column=0, padx=1, pady=2, sticky="ew")
            
            # Nút Home
            btn_home = ctk.CTkButton(
                btn_frame, 
                text="🏠 Main", 
                width=45, 
                height=26,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#e2e8f0",
                hover_color="#cbd5e1",
                text_color="#1e293b",
                corner_radius=6,
                command=lambda d=dev: self.run_in_thread(main.adb.keyevent, d, 3)
            )
            btn_home.grid(row=0, column=1, padx=1, pady=2, sticky="ew")
            
            # Nút Back
            btn_back = ctk.CTkButton(
                btn_frame, 
                text="↩️ Back", 
                width=45, 
                height=26,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#e2e8f0",
                hover_color="#cbd5e1",
                text_color="#1e293b",
                corner_radius=6,
                command=lambda d=dev: self.run_in_thread(main.adb.keyevent, d, 4)
            )
            btn_back.grid(row=0, column=2, padx=1, pady=2, sticky="ew")
            
            # Hàng 2: Mở app / Tắt app
            app_btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            app_btn_frame.grid(row=3, column=0, padx=8, pady=(0, 12), sticky="ew")
            app_btn_frame.columnconfigure(0, weight=1)
            app_btn_frame.columnconfigure(1, weight=1)
            
            btn_open = ctk.CTkButton(
                app_btn_frame, 
                text="🛒 Mở Shopee", 
                height=26,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#ee4d2d", 
                hover_color="#d73c1f",
                text_color="#ffffff",
                corner_radius=6,
                command=lambda d=dev: self.run_in_thread(main.adb.launch_app, d, config.SHOPEE_PACKAGE)
            )
            btn_open.grid(row=0, column=0, padx=(0, 2), pady=1, sticky="ew")
            
            btn_close = ctk.CTkButton(
                app_btn_frame, 
                text="🛑 Tắt app", 
                height=26,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color="#ef4444", 
                hover_color="#dc2626",
                text_color="#ffffff",
                corner_radius=6,
                command=lambda d=dev: self.run_in_thread(main.adb.stop_app, d, config.SHOPEE_PACKAGE)
            )
            btn_close.grid(row=0, column=1, padx=(2, 0), pady=1, sticky="ew")

    def screenshot_device(self, dev_id, name):
        def action():
            print(f"[GUI] Đang chụp màn hình Máy {name}...")
            temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            local_path = os.path.join(temp_dir, f"gui_screenshot_{name}.png")
            success, res = main.adb.take_screenshot(dev_id, local_path)
            if success:
                print(f"[GUI] Chụp ảnh Máy {name} thành công! Đường dẫn: {local_path}")
                # Mở ảnh bằng Windows Photo Viewer mặc định
                os.startfile(local_path)
            else:
                print(f"[GUI] Lỗi chụp màn hình Máy {name}: {res}")
        self.run_in_thread(action)

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

    def get_selected_devices(self):
        selected = []
        for dev, var in self.device_checkboxes.items():
            if var.get():
                selected.append(dev)
        return selected

    def select_all_devices(self):
        for var in self.device_checkboxes.values():
            var.set(True)

    def deselect_all_devices(self):
        for var in self.device_checkboxes.values():
            var.set(False)

    def bulk_keyevent(self, keycode):
        selected = self.get_selected_devices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
            return
        print(f"[GUI] Đang gửi phím keyevent {keycode} đến {len(selected)} máy...")
        def action():
            for d in selected:
                main.adb.keyevent(d, keycode)
        self.run_in_thread(action)

    def bulk_open_shopee(self):
        selected = self.get_selected_devices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
            return
        print(f"[GUI] Đang mở app Shopee trên {len(selected)} máy...")
        def action():
            for d in selected:
                main.adb.launch_app(d, config.SHOPEE_PACKAGE)
        self.run_in_thread(action)

    def bulk_close_shopee(self):
        selected = self.get_selected_devices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
            return
        print(f"[GUI] Đang tắt app Shopee trên {len(selected)} máy...")
        def action():
            for d in selected:
                main.adb.stop_app(d, config.SHOPEE_PACKAGE)
        self.run_in_thread(action)

    def bulk_screenshot(self):
        selected = self.get_selected_devices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
            return
        print(f"[GUI] Đang chụp màn hình hàng loạt {len(selected)} máy...")
        def action():
            for d in selected:
                name = main.get_device_name(d)
                temp_dir = os.path.join(os.path.dirname(__file__), 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                local_path = os.path.join(temp_dir, f"gui_bulk_screenshot_{name}.png")
                main.adb.take_screenshot(d, local_path)
            print("[GUI] Đã chụp xong toàn bộ ảnh các máy đã chọn.")
        self.run_in_thread(action)

    def bulk_disable_rotation(self, target_devices=None):
        if target_devices is None:
            selected = self.get_selected_devices()
            if not selected:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
                return
        else:
            selected = target_devices
            
        def action():
            def disable_rot(d):
                try:
                    main.adb.execute_adb(d, ["shell", "settings", "put", "system", "accelerometer_rotation", "0"])
                    main.adb.execute_adb(d, ["shell", "settings", "put", "system", "user_rotation", "0"])
                except Exception:
                    pass
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max(1, len(selected))) as executor:
                executor.map(disable_rot, selected)
        self.run_in_thread(action)

    def bulk_reboot(self):
        selected = self.get_selected_devices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 thiết bị bằng checkbox!")
            return
            
        confirm = messagebox.askyesno(
            "Xác nhận", 
            f"Bạn có chắc chắn muốn khởi động lại (Reboot) {len(selected)} thiết bị đã chọn không?"
        )
        if not confirm:
            return
            
        print(f"[GUI] Đang gửi lệnh khởi động lại (Reboot) đến {len(selected)} máy...")
        
        def action():
            from concurrent.futures import ThreadPoolExecutor
            def reboot_device(d):
                dev_name = main.get_device_name(d)
                try:
                    main.adb.execute_adb(d, ["reboot"], timeout=3)
                    print(f"[GUI] Gửi lệnh Reboot đến Máy {dev_name} thành công.")
                except Exception as e:
                    print(f"[GUI] Gửi lệnh Reboot đến Máy {dev_name} gặp lỗi: {e}")
                    
            with ThreadPoolExecutor(max_workers=len(selected)) as executor:
                executor.map(reboot_device, selected)
            print("[GUI] Hoàn thành gửi lệnh reboot tới các máy.")
            
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
            
            # Gửi tin nhắn bắt đầu chạy song song về Telegram
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
        try:
            min_d = int(self.ent_tt_min_delay.get().strip() or "5")
            max_d = int(self.ent_tt_max_delay.get().strip() or "10")
        except ValueError:
            min_d, max_d = 5, 10

        self.bulk_disable_rotation(target_devices=target_devices)
        main.cancel_flag = False
        main.cancel_sequential = False

        print(f"[GUI] Bắt đầu chạy TikTok Tuần Tự trên {len(target_devices)} máy...")

        def action():
            for idx, dev in enumerate(target_devices):
                if main.is_cancelled():
                    print("[GUI] ⏹️ Tiến trình TikTok đã bị dừng.")
                    break
                dev_name = main.get_device_name(dev)
                print(f"[GUI] TikTok -> Máy {dev_name} ({idx+1}/{len(target_devices)})")
                
                def tt_status_cb(d, msg):
                    self.log_message(f"[{msg}]")

                main.adb.tiktok_automation_workflow(
                    dev, 
                    seed_keywords=seed_raw, 
                    target_channel=channel, 
                    min_delay=min_d, 
                    max_delay=max_d, 
                    status_callback=tt_status_cb,
                    is_cancelled=main.is_cancelled
                )
            print("[GUI] 🏁 Hoàn tất tiến trình chạy TikTok Tuần Tự!")

        self.run_in_thread(action)

    def run_par_tiktok(self):
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT
        try:
            min_d = int(self.ent_tt_min_delay.get().strip() or "5")
            max_d = int(self.ent_tt_max_delay.get().strip() or "10")
        except ValueError:
            min_d, max_d = 5, 10

        self.bulk_disable_rotation(target_devices=target_devices)
        main.cancel_flag = False
        main.cancel_sequential = False

        print(f"[GUI] Bắt đầu chạy TikTok Song Song trên {len(target_devices)} máy...")

        def run_parallel_tt(device_id):
            dev_name = main.get_device_name(device_id)
            def tt_status_cb(d, msg):
                self.log_message(f"[Máy {dev_name}] {msg}")

            main.adb.tiktok_automation_workflow(
                device_id, 
                seed_keywords=seed_raw, 
                target_channel=channel, 
                min_delay=min_d, 
                max_delay=max_d, 
                status_callback=tt_status_cb,
                is_cancelled=main.is_cancelled
            )

        def action():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(target_devices)) as executor:
                executor.map(run_parallel_tt, target_devices)
            print("[GUI] 🏁 Hoàn tất tiến trình chạy TikTok Song Song!")

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
        click_first_item = False
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
        
        if not keywords:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập từ khóa chính hợp lệ!")
            return
            
        self.log_message(f"Đang gửi yêu cầu sinh từ khóa phụ cho: {keywords}...")
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
        # Đảm bảo cập nhật giao diện Tkinter an toàn từ mọi thread
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

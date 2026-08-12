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
from adaptive_scheduler import PLATFORM_POLICIES, run_adaptive
from notion_keyword_sync import (
    NotionSyncError,
    fetch_enabled_keyword_schedules,
    mark_schedule_scanned,
)

# Bright operations dashboard with a lightweight iOS-inspired glass treatment.
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BoxPhoneControl")
        self.geometry("1720x960")
        self.minsize(1280, 760)
        self.configure(fg_color="#f3f6fb")

        # Design tokens: light "liquid glass" surfaces rendered with native
        # CustomTkinter layers so the dashboard remains fast with many devices.
        bg = "#f3f6fb"
        glass = "#ffffff"
        glass_tint = "#f8fafc"
        surface = "#ffffff"
        border = "#e2e8f0"
        border_hover = "#93b4ea"
        text = "#0f172a"
        muted = "#64748b"
        blue = "#1d4ed8"
        blue_hover = "#1e40af"
        blue_soft = "#eff6ff"
        orange = "#c2410c"
        orange_soft = "#fff7ed"
        pink = "#be185d"
        pink_soft = "#fdf2f8"
        violet = "#6d28d9"
        violet_soft = "#f5f3ff"
        green = "#047857"
        green_hover = "#065f46"
        red = "#c81e2b"
        red_soft = "#fff5f5"
        input_border = "#cbd5e1"

        title_font = ctk.CTkFont(family="Segoe UI", size=17, weight="bold")
        section_font = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        label_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        body_font = ctk.CTkFont(family="Segoe UI", size=12)
        button_font = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        
        # Thiết lập app icon bitmap
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        
        # Lưu trữ các biến Checkbox điều khiển hàng loạt
        self.device_checkboxes = {}
        
        # Main Grid Layout: Header, live log, two operation cards, settings.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        
        # ================= ROW 0: GLASS HEADER =================
        self.top_header = ctk.CTkFrame(
            self,
            fg_color=glass,
            corner_radius=18,
            border_width=1,
            border_color=border,
        )
        self.top_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))

        self.brand_badge = ctk.CTkFrame(
            self.top_header, fg_color="transparent", corner_radius=18
        )
        self.brand_badge.pack(fill="x", padx=18, pady=14)

        self.brand_icon = ctk.CTkLabel(
            self.brand_badge,
            text="BPC",
            width=52,
            height=52,
            corner_radius=14,
            fg_color="#0f172a",
            text_color="#ffffff",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.brand_icon.pack(side="left", padx=(0, 12))

        self.brand_copy = ctk.CTkFrame(self.brand_badge, fg_color="transparent")
        self.brand_copy.pack(side="left", fill="y")
        
        self.lbl_brand = ctk.CTkLabel(
            self.brand_copy,
            text="BoxPhoneControl",
            font=ctk.CTkFont(family="Segoe UI", size=23, weight="bold"),
            text_color=text,
        )
        self.lbl_brand.pack(anchor="w")
        
        self.lbl_sub_brand = ctk.CTkLabel(
            self.brand_copy,
            text="Trung tâm điều hành  •  Tự động hóa đa thiết bị",
            font=body_font,
            text_color=muted,
        )
        self.lbl_sub_brand.pack(anchor="w", pady=(1, 0))

        self.platform_badge = ctk.CTkLabel(
            self.brand_badge,
            text="3 QUY TRÌNH",
            height=34,
            corner_radius=17,
            fg_color="#f1f5f9",
            text_color="#334155",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self.platform_badge.pack(side="right", padx=(10, 2))

        self.device_status_badge = ctk.CTkLabel(
            self.brand_badge,
            text="ĐANG QUÉT THIẾT BỊ",
            height=34,
            corner_radius=10,
            fg_color="#ecfdf5",
            text_color=green,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self.device_status_badge.pack(side="right", padx=(8, 0))

        self.btn_refresh = ctk.CTkButton(
            self.brand_badge,
            text="Quét thiết bị",
            font=button_font,
            width=150,
            height=44,
            fg_color=blue,
            hover_color=blue_hover,
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.refresh_devices_action,
        )
        self.btn_refresh.pack(side="right", padx=(14, 0), pady=2)

        self.btn_scan_notion = ctk.CTkButton(
            self.brand_badge,
            text="Quét từ khóa Notion",
            font=button_font,
            width=168,
            height=44,
            fg_color="#0f766e",
            hover_color="#115e59",
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.scan_notion_keywords_action,
        )
        self.btn_scan_notion.pack(side="right", padx=(10, 0), pady=2)

        self.btn_mute_all = ctk.CTkButton(
            self.brand_badge,
            text="Tắt âm tất cả",
            font=button_font,
            width=145,
            height=44,
            fg_color=violet,
            hover_color="#5938b8",
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.mute_all_devices_action,
        )
        self.btn_mute_all.pack(side="right", padx=(10, 0), pady=2)

        self.btn_telegram_notifications = ctk.CTkButton(
            self.brand_badge,
            text="",
            font=button_font,
            width=155,
            height=44,
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.toggle_telegram_notifications,
        )
        self.btn_telegram_notifications.pack(
            side="right", padx=(10, 0), pady=2
        )
        self._refresh_telegram_notifications_button()

        # ================= ROW 1: REAL-TIME ACTIVITY =================
        self.log_card = ctk.CTkFrame(
            self,
            fg_color=glass,
            corner_radius=18,
            border_width=1,
            border_color=border,
        )
        self.log_card.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))

        self.log_header = ctk.CTkFrame(self.log_card, fg_color="transparent")
        self.log_header.pack(fill="x", padx=18, pady=(11, 7))
        
        self.lbl_log = ctk.CTkLabel(
            self.log_header,
            text="Trạng thái hệ thống",
            font=section_font,
            text_color=text,
        )
        self.lbl_log.pack(side="left")

        self.lbl_log_hint = ctk.CTkLabel(
            self.log_header,
            text="Luồng sự kiện trực tiếp từ thiết bị và các workflow đang chạy",
            font=body_font,
            text_color=muted,
        )
        self.lbl_log_hint.pack(side="left", padx=12)

        self.live_badge = ctk.CTkLabel(
            self.log_header,
            text="●  LIVE",
            width=68,
            height=26,
            corner_radius=10,
            fg_color="#e7f8f1",
            text_color=green,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self.live_badge.pack(side="right")

        self._log_expanded = False
        self.btn_toggle_log = ctk.CTkButton(
            self.log_header,
            text="Mở rộng",
            width=92,
            height=28,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color="#eff6ff",
            hover_color="#dbeafe",
            text_color=blue,
            border_width=1,
            border_color="#bfdbfe",
            corner_radius=9,
            cursor="hand2",
            command=self.toggle_system_log,
        )
        self.btn_toggle_log.pack(side="right", padx=(0, 8))
        
        self.log_box = ctk.CTkTextbox(
            self.log_card,
            height=78,
            state="disabled",
            fg_color="#0b1220",
            text_color="#dbeafe",
            font=ctk.CTkFont(family="Cascadia Mono", size=11),
            border_width=1,
            border_color="#1e293b",
            corner_radius=12,
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#475569",
        )
        self.log_box.pack(fill="x", padx=18, pady=(0, 14))
        
        # Redirect standard output & error to log_box
        sys.stdout = ConsoleRedirector(self.log_box)
        sys.stderr = ConsoleRedirector(self.log_box)

        # ================= ROW 2: OPERATIONAL CARDS =================
        self.ops_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.ops_frame.grid(row=2, column=0, sticky="nsew", padx=18, pady=0)
        self.ops_frame.columnconfigure(0, weight=1)
        self.ops_frame.columnconfigure(1, weight=1)
        self.ops_frame.columnconfigure(2, weight=1)
        self.ops_frame.rowconfigure(0, weight=0)
        self.ops_frame.rowconfigure(1, weight=1)

        self.workspace_header = ctk.CTkFrame(
            self.ops_frame, fg_color="transparent"
        )
        self.workspace_header.grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )
        ctk.CTkLabel(
            self.workspace_header,
            text="QUY TRÌNH TỰ ĐỘNG",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#475569",
        ).pack(side="left")
        ctk.CTkLabel(
            self.workspace_header,
            text="Chọn nền tảng, cấu hình dữ liệu và khởi chạy theo từng nhóm thiết bị",
            font=body_font,
            text_color=muted,
        ).pack(side="left", padx=12)
        ctk.CTkLabel(
            self.workspace_header,
            text="SẴN SÀNG  •  3 MÔ-ĐUN",
            height=28,
            corner_radius=9,
            fg_color="#ecfdf5",
            text_color=green,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        ).pack(side="right")

        scroll_style = {
            "corner_radius": 18,
            "fg_color": glass,
            "border_width": 1,
            "border_color": border,
            "scrollbar_button_color": "#cbd5e1",
            "scrollbar_button_hover_color": "#94a3b8",
        }
        field_style = {
            "fg_color": surface,
            "border_color": input_border,
            "text_color": text,
            "placeholder_text_color": "#94a3b8",
            "border_width": 1,
            "corner_radius": 10,
            "font": body_font,
        }

        # ---------------- SHOPEE AUTOMATION ----------------
        self.shopee_scroll = ctk.CTkScrollableFrame(
            self.ops_frame,
            **scroll_style,
        )
        self.shopee_scroll.grid(row=1, column=0, sticky="nsew", padx=(0, 6))

        self.shopee_heading = ctk.CTkFrame(
            self.shopee_scroll, fg_color=orange_soft, corner_radius=16
        )
        self.shopee_heading.pack(fill="x", padx=16, pady=(14, 10))

        self.shopee_mark = ctk.CTkLabel(
            self.shopee_heading,
            text="S",
            width=38,
            height=38,
            corner_radius=12,
            fg_color="#ffffff",
            text_color=orange,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.shopee_mark.pack(side="left", padx=10, pady=9)

        self.shopee_heading_copy = ctk.CTkFrame(
            self.shopee_heading, fg_color="transparent"
        )
        self.shopee_heading_copy.pack(side="left", fill="y", pady=8)

        ctk.CTkLabel(
            self.shopee_heading,
            text="SẴN SÀNG",
            width=76,
            height=26,
            corner_radius=8,
            fg_color="#ffffff",
            text_color=orange,
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
        ).pack(side="right", padx=10)

        self.lbl_tasks = ctk.CTkLabel(
            self.shopee_heading_copy,
            text="Shopee Automation",
            font=title_font,
            text_color=text,
        )
        self.lbl_tasks.pack(anchor="w")

        self.lbl_shopee_hint = ctk.CTkLabel(
            self.shopee_heading_copy,
            text="Tìm kiếm đa tầng và điều phối thiết bị",
            font=body_font,
            text_color=muted,
        )
        self.lbl_shopee_hint.pack(anchor="w")
        
        self.main_keywords_header = ctk.CTkFrame(
            self.shopee_scroll,
            fg_color="transparent",
        )
        self.main_keywords_header.pack(fill="x", padx=16, pady=(0, 3))

        self.lbl_main_keywords = ctk.CTkLabel(
            self.main_keywords_header,
            text="Từ khóa chính • Mỗi dòng một từ khóa",
            font=label_font,
            text_color=text,
        )
        self.lbl_main_keywords.pack(side="left")

        self.btn_toggle_main_keywords = ctk.CTkButton(
            self.main_keywords_header,
            text="Mở rộng ▼",
            width=92,
            height=28,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color=blue_soft,
            hover_color="#dce9ff",
            text_color=blue,
            corner_radius=10,
            cursor="hand2",
            command=lambda: self.toggle_shopee_keyword_box("main"),
        )
        self.btn_toggle_main_keywords.pack(side="right")

        self.txt_main_keywords = ctk.CTkTextbox(
            self.shopee_scroll,
            fg_color=surface,
            border_color=input_border,
            text_color=text,
            border_width=1,
            corner_radius=12,
            height=64,
            font=body_font,
            scrollbar_button_color="#c5d5e7",
            scrollbar_button_hover_color="#a9bfd9",
        )
        self.txt_main_keywords.pack(fill="x", padx=16, pady=(0, 8))
        
        # Chế độ từ khóa
        self.keyword_mode = ctk.StringVar(value="original")
        self.mode_frame = ctk.CTkFrame(
            self.shopee_scroll,
            fg_color=glass_tint,
            corner_radius=12,
            border_width=1,
            border_color=border,
        )
        self.mode_frame.pack(fill="x", padx=16, pady=(0, 8))
        
        self.rad_orig = ctk.CTkRadioButton(
            self.mode_frame,
            text="Gốc (Không AI)",
            variable=self.keyword_mode,
            value="original",
            font=label_font,
            text_color=text,
            fg_color=blue,
            hover_color=blue_hover,
            border_color="#9eb0c7",
        )
        self.rad_orig.pack(side="left", padx=(10, 7), pady=9)
        
        self.rad_ai = ctk.CTkRadioButton(
            self.mode_frame,
            text="Mở rộng (AI)",
            variable=self.keyword_mode,
            value="ai",
            font=label_font,
            text_color=text,
            fg_color=violet,
            hover_color="#5b3fb3",
            border_color="#9eb0c7",
        )
        self.rad_ai.pack(side="left", padx=7, pady=9)

        self.rad_ai_t2 = ctk.CTkRadioButton(
            self.mode_frame,
            text="Tầng 2 (AI sinh)",
            variable=self.keyword_mode,
            value="ai_t2",
            font=label_font,
            text_color=text,
            fg_color=violet,
            hover_color="#5b3fb3",
            border_color="#9eb0c7",
        )
        self.rad_ai_t2.pack(side="left", padx=(7, 10), pady=9)
        
        # Nút sinh từ khóa qua AI
        self.ai_btn_grid = ctk.CTkFrame(
            self.shopee_scroll, fg_color="transparent"
        )
        self.ai_btn_grid.pack(fill="x", padx=16, pady=(0, 8))
        self.ai_btn_grid.columnconfigure(0, weight=1)
        self.ai_btn_grid.columnconfigure(1, weight=1)

        self.btn_gen_ai = ctk.CTkButton(
            self.ai_btn_grid,
            text="Tạo từ khóa tầng 1",
            font=button_font,
            fg_color=violet_soft,
            hover_color="#e8e0ff",
            text_color=violet,
            border_width=1,
            border_color="#d9cdfa",
            corner_radius=12,
            height=38,
            cursor="hand2",
            command=self.generate_ai_keywords_action,
        )
        self.btn_gen_ai.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        
        self.btn_gen_ai_t2 = ctk.CTkButton(
            self.ai_btn_grid,
            text="Tạo từ khóa tầng 2",
            font=button_font,
            fg_color=violet_soft,
            hover_color="#e8e0ff",
            text_color=violet,
            border_width=1,
            border_color="#d9cdfa",
            corner_radius=12,
            height=38,
            cursor="hand2",
            command=self.generate_ai_keywords_tier2_action,
        )
        self.btn_gen_ai_t2.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        
        self.ai_keywords_header = ctk.CTkFrame(
            self.shopee_scroll,
            fg_color="transparent",
        )
        self.ai_keywords_header.pack(fill="x", padx=16, pady=(0, 3))

        self.lbl_ai_keywords = ctk.CTkLabel(
            self.ai_keywords_header,
            text="Từ khóa AI đã tạo",
            font=label_font,
            text_color=text,
        )
        self.lbl_ai_keywords.pack(side="left")

        self.btn_toggle_ai_keywords = ctk.CTkButton(
            self.ai_keywords_header,
            text="Mở rộng ▼",
            width=92,
            height=28,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color=violet_soft,
            hover_color="#e8e0ff",
            text_color=violet,
            corner_radius=10,
            cursor="hand2",
            command=lambda: self.toggle_shopee_keyword_box("ai"),
        )
        self.btn_toggle_ai_keywords.pack(side="right")
        
        self.txt_ai_keywords = ctk.CTkTextbox(
            self.shopee_scroll,
            fg_color=surface,
            border_color=input_border,
            text_color="#245ca6",
            border_width=1,
            corner_radius=12,
            height=64,
            font=body_font,
            scrollbar_button_color="#c5d5e7",
            scrollbar_button_hover_color="#a9bfd9",
        )
        self.txt_ai_keywords.pack(fill="x", padx=16, pady=(0, 8))

        self._shopee_keyword_boxes = {
            "main": {
                "textbox": self.txt_main_keywords,
                "button": self.btn_toggle_main_keywords,
                "expanded": False,
            },
            "ai": {
                "textbox": self.txt_ai_keywords,
                "button": self.btn_toggle_ai_keywords,
                "expanded": False,
            },
        }
        
        self.ent_selection = ctk.CTkEntry(
            self.shopee_scroll,
            placeholder_text="Chọn máy chạy Shopee (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            height=42,
            **field_style,
        )
        self.ent_selection.pack(fill="x", padx=16, pady=(0, 8))
        
        self.btn_grid = ctk.CTkFrame(self.shopee_scroll, fg_color="transparent")
        self.btn_grid.pack(fill="x", padx=16, pady=(0, 7))
        self.btn_grid.columnconfigure(0, weight=1)
        self.btn_grid.columnconfigure(1, weight=1)
        self.btn_grid.columnconfigure(2, weight=1)
        
        self.btn_seq = ctk.CTkButton(
            self.btn_grid,
            text="Chạy tuần tự",
            font=button_font,
            fg_color=green,
            hover_color=green_hover,
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_seq_search,
        )
        self.btn_seq.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        
        self.btn_par = ctk.CTkButton(
            self.btn_grid,
            text="Chạy song song",
            font=button_font,
            fg_color=blue,
            hover_color=blue_hover,
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_par_search,
        )
        self.btn_par.grid(row=0, column=1, padx=4, sticky="ew")

        self.btn_adaptive = ctk.CTkButton(
            self.btn_grid,
            text="Chạy thích ứng",
            font=button_font,
            fg_color=violet,
            hover_color="#5b21b6",
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=lambda: self.run_par_search(adaptive=True),
        )
        self.btn_adaptive.grid(
            row=0, column=2, padx=(4, 0), sticky="ew"
        )
        
        self.btn_stop = ctk.CTkButton(
            self.shopee_scroll,
            text="Dừng Shopee khẩn cấp",
            font=button_font,
            fg_color=red_soft,
            hover_color="#ffe1e4",
            text_color=red,
            border_width=1,
            border_color="#f4b8bd",
            corner_radius=13,
            height=42,
            cursor="hand2",
            command=self.stop_all,
        )
        self.btn_stop.pack(fill="x", padx=16, pady=(0, 12))

        # ---------------- TIKTOK AUTOMATION ----------------
        self.tiktok_scroll = ctk.CTkScrollableFrame(
            self.ops_frame,
            **scroll_style,
        )
        self.tiktok_scroll.grid(row=1, column=1, sticky="nsew", padx=6)

        self.tiktok_heading = ctk.CTkFrame(
            self.tiktok_scroll, fg_color=pink_soft, corner_radius=16
        )
        self.tiktok_heading.pack(fill="x", padx=16, pady=(14, 10))

        self.tiktok_mark = ctk.CTkLabel(
            self.tiktok_heading,
            text="T",
            width=38,
            height=38,
            corner_radius=12,
            fg_color="#ffffff",
            text_color=pink,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.tiktok_mark.pack(side="left", padx=10, pady=9)

        self.tiktok_heading_copy = ctk.CTkFrame(
            self.tiktok_heading, fg_color="transparent"
        )
        self.tiktok_heading_copy.pack(side="left", fill="y", pady=8)

        ctk.CTkLabel(
            self.tiktok_heading,
            text="SẴN SÀNG",
            width=76,
            height=26,
            corner_radius=8,
            fg_color="#ffffff",
            text_color=pink,
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
        ).pack(side="right", padx=10)

        self.lbl_tiktok_title = ctk.CTkLabel(
            self.tiktok_heading_copy,
            text="TikTok Automation",
            font=title_font,
            text_color=text,
        )
        self.lbl_tiktok_title.pack(anchor="w")

        self.lbl_tiktok_hint = ctk.CTkLabel(
            self.tiktok_heading_copy,
            text="Quy trình tương tác tự động 3 bước",
            font=body_font,
            text_color=muted,
        )
        self.lbl_tiktok_hint.pack(anchor="w")

        self.lbl_tt_seed = ctk.CTkLabel(
            self.tiktok_scroll,
            text="Từ khóa nhiệm vụ • Phân cách bằng dấu phẩy",
            font=label_font,
            text_color=text,
        )
        self.lbl_tt_seed.pack(padx=16, pady=(0, 3), anchor="w")

        self.ent_tt_seed = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="skincare, trị mụn, nặn mụn, chăm sóc da",
            height=42,
            **field_style,
        )
        self.ent_tt_seed.insert(0, config.TIKTOK_SEED_KEYWORDS_DEFAULT)
        self.ent_tt_seed.pack(fill="x", padx=16, pady=(0, 8))

        self.lbl_tt_channel = ctk.CTkLabel(
            self.tiktok_scroll,
            text="Kênh TikTok mục tiêu • Phân cách bằng dấu phẩy • Random 1 kênh",
            font=label_font,
            text_color=text,
        )
        self.lbl_tt_channel.pack(padx=16, pady=(0, 3), anchor="w")

        self.ent_tt_channel = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="Kênh TikTok A, Kênh TikTok B, Kênh TikTok C",
            height=42,
            **field_style,
        )
        self.ent_tt_channel.insert(0, config.TIKTOK_TARGET_CHANNEL_DEFAULT)
        self.ent_tt_channel.pack(fill="x", padx=16, pady=(0, 8))

        self.tt_timeline_card = ctk.CTkFrame(
            self.tiktok_scroll,
            fg_color=glass_tint,
            corner_radius=14,
            border_width=1,
            border_color=border,
        )
        self.tt_timeline_card.pack(fill="x", padx=16, pady=(0, 8))
        self.lbl_tt_timeline = ctk.CTkLabel(
            self.tt_timeline_card,
            text=(
                "LỘ TRÌNH TỰ ĐỘNG\n\n"
                "00   Nuôi Facebook Feed  •  3–5 phút\n"
                "01   Trang chủ  •  15–60 giây\n"
                "02   Từ khóa nhiệm vụ  •  15–30 giây\n"
                "03   Trong kênh  •  3–5 phút, đổi clip mỗi 15–30 giây"
            ),
            justify="left",
            anchor="w",
            font=label_font,
            text_color=text,
        )
        self.lbl_tt_timeline.pack(fill="x", padx=14, pady=12)

        self.ent_tt_selection = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="Chọn máy chạy TikTok (Ví dụ: 1-5,10 hoặc trống=Tất cả)",
            height=42,
            **field_style,
        )
        self.ent_tt_selection.pack(fill="x", padx=16, pady=(0, 8))

        self.tt_btn_grid = ctk.CTkFrame(self.tiktok_scroll, fg_color="transparent")
        self.tt_btn_grid.pack(fill="x", padx=16, pady=(0, 7))
        self.tt_btn_grid.columnconfigure(0, weight=1)
        self.tt_btn_grid.columnconfigure(1, weight=1)
        self.tt_btn_grid.columnconfigure(2, weight=1)

        self.btn_tt_seq = ctk.CTkButton(
            self.tt_btn_grid,
            text="Chạy tuần tự",
            font=button_font,
            fg_color=green,
            hover_color=green_hover,
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_seq_tiktok,
        )
        self.btn_tt_seq.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.btn_tt_par = ctk.CTkButton(
            self.tt_btn_grid,
            text="Chạy song song",
            font=button_font,
            fg_color=pink,
            hover_color="#9f1f5a",
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_par_tiktok,
        )
        self.btn_tt_par.grid(row=0, column=1, padx=4, sticky="ew")

        self.btn_tt_adaptive = ctk.CTkButton(
            self.tt_btn_grid,
            text="Chạy thích ứng",
            font=button_font,
            fg_color=violet,
            hover_color="#5b21b6",
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=lambda: self.run_par_tiktok(adaptive=True),
        )
        self.btn_tt_adaptive.grid(
            row=0, column=2, padx=(4, 0), sticky="ew"
        )

        self.btn_tt_stop = ctk.CTkButton(
            self.tiktok_scroll,
            text="Dừng TikTok khẩn cấp",
            font=button_font,
            fg_color=red_soft,
            hover_color="#ffe1e4",
            text_color=red,
            border_width=1,
            border_color="#f4b8bd",
            corner_radius=13,
            height=42,
            cursor="hand2",
            command=self.stop_all,
        )
        self.btn_tt_stop.pack(fill="x", padx=16, pady=(0, 12))

        # ---------------- FACEBOOK AUTOMATION ----------------
        self.facebook_scroll = ctk.CTkScrollableFrame(
            self.ops_frame,
            **scroll_style,
        )
        self.facebook_scroll.grid(
            row=1, column=2, sticky="nsew", padx=(6, 0)
        )

        self.facebook_heading = ctk.CTkFrame(
            self.facebook_scroll, fg_color=blue_soft, corner_radius=16
        )
        self.facebook_heading.pack(fill="x", padx=16, pady=(14, 10))

        self.facebook_mark = ctk.CTkLabel(
            self.facebook_heading,
            text="F",
            width=38,
            height=38,
            corner_radius=12,
            fg_color="#ffffff",
            text_color=blue,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.facebook_mark.pack(side="left", padx=10, pady=9)

        self.facebook_heading_copy = ctk.CTkFrame(
            self.facebook_heading, fg_color="transparent"
        )
        self.facebook_heading_copy.pack(side="left", fill="y", pady=8)
        ctk.CTkLabel(
            self.facebook_heading,
            text="SẴN SÀNG",
            width=76,
            height=26,
            corner_radius=8,
            fg_color="#ffffff",
            text_color=blue,
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
        ).pack(side="right", padx=10)
        ctk.CTkLabel(
            self.facebook_heading_copy,
            text="Facebook Automation",
            font=title_font,
            text_color=text,
        ).pack(anchor="w")
        ctk.CTkLabel(
            self.facebook_heading_copy,
            text="Nuôi Feed và tìm đúng Page mục tiêu",
            font=body_font,
            text_color=muted,
        ).pack(anchor="w")

        ctk.CTkLabel(
            self.facebook_scroll,
            text="Tầng 1 • Từ khóa mồi • Phân cách bằng dấu phẩy",
            font=label_font,
            text_color=text,
        ).pack(padx=16, pady=(0, 3), anchor="w")
        self.ent_fb_seed = ctk.CTkEntry(
            self.facebook_scroll,
            placeholder_text="nặn mụn, chăm sóc da, skincare địa phương",
            height=42,
            **field_style,
        )
        self.ent_fb_seed.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            self.facebook_scroll,
            text="Tầng 2 • Page target • Mỗi cụm cách nhau dấu phẩy",
            font=label_font,
            text_color=text,
        ).pack(padx=16, pady=(0, 3), anchor="w")
        self.ent_fb_target = ctk.CTkEntry(
            self.facebook_scroll,
            placeholder_text="Tên thương hiệu hoặc cụm tên Page mục tiêu",
            height=42,
            **field_style,
        )
        self.ent_fb_target.pack(fill="x", padx=16, pady=(0, 8))

        self.fb_timeline_card = ctk.CTkFrame(
            self.facebook_scroll,
            fg_color=glass_tint,
            corner_radius=14,
            border_width=1,
            border_color=border,
        )
        self.fb_timeline_card.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            self.fb_timeline_card,
            text=(
                "LỘ TRÌNH TỰ ĐỘNG\n\n"
                "00   Nuôi TikTok video  •  3–5 phút\n"
                "01   Nuôi Feed  •  90–120 giây\n"
                "02   Từ khóa mồi  •  30–60 giây\n"
                "03   Đúng Page target  •  2–3 phút"
            ),
            justify="left",
            anchor="w",
            font=label_font,
            text_color=text,
        ).pack(fill="x", padx=14, pady=12)

        self.ent_fb_selection = ctk.CTkEntry(
            self.facebook_scroll,
            placeholder_text=(
                "Chọn máy chạy Facebook (Ví dụ: 1-5,10 hoặc trống=Tất cả)"
            ),
            height=42,
            **field_style,
        )
        self.ent_fb_selection.pack(fill="x", padx=16, pady=(0, 8))

        self.fb_btn_grid = ctk.CTkFrame(
            self.facebook_scroll, fg_color="transparent"
        )
        self.fb_btn_grid.pack(fill="x", padx=16, pady=(0, 7))
        self.fb_btn_grid.columnconfigure(0, weight=1)
        self.fb_btn_grid.columnconfigure(1, weight=1)
        self.fb_btn_grid.columnconfigure(2, weight=1)
        self.btn_fb_seq = ctk.CTkButton(
            self.fb_btn_grid,
            text="Chạy tuần tự",
            font=button_font,
            fg_color=green,
            hover_color=green_hover,
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_seq_facebook,
        )
        self.btn_fb_seq.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.btn_fb_par = ctk.CTkButton(
            self.fb_btn_grid,
            text="Chạy song song",
            font=button_font,
            fg_color=blue,
            hover_color=blue_hover,
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=self.run_par_facebook,
        )
        self.btn_fb_par.grid(row=0, column=1, padx=4, sticky="ew")
        self.btn_fb_adaptive = ctk.CTkButton(
            self.fb_btn_grid,
            text="Chạy thích ứng",
            font=button_font,
            fg_color=violet,
            hover_color="#5b21b6",
            text_color="#ffffff",
            corner_radius=13,
            height=44,
            cursor="hand2",
            command=lambda: self.run_par_facebook(adaptive=True),
        )
        self.btn_fb_adaptive.grid(
            row=0, column=2, padx=(4, 0), sticky="ew"
        )
        self.btn_fb_stop = ctk.CTkButton(
            self.facebook_scroll,
            text="Dừng Facebook khẩn cấp",
            font=button_font,
            fg_color=red_soft,
            hover_color="#ffe1e4",
            text_color=red,
            border_width=1,
            border_color="#f4b8bd",
            corner_radius=13,
            height=42,
            cursor="hand2",
            command=self.stop_all,
        )
        self.btn_fb_stop.pack(fill="x", padx=16, pady=(0, 12))

        # ================= ROW 3: SYSTEM SETTINGS =================
        self.bottom_panel = ctk.CTkFrame(
            self,
            fg_color=glass,
            corner_radius=18,
            border_width=1,
            border_color=border,
        )
        self.bottom_panel.grid(row=3, column=0, sticky="ew", padx=18, pady=(10, 16))

        self.settings_header = ctk.CTkFrame(
            self.bottom_panel, fg_color="transparent"
        )
        self.settings_header.pack(fill="x", padx=18, pady=(10, 4))
        
        self.lbl_settings = ctk.CTkLabel(
            self.settings_header,
            text="Cấu hình & tích hợp",
            font=section_font,
            text_color=text,
        )
        self.lbl_settings.pack(side="left")

        self.lbl_settings_hint = ctk.CTkLabel(
            self.settings_header,
            text="Thông tin kết nối nhạy cảm được ẩn khi hiển thị và lưu cục bộ",
            font=body_font,
            text_color=muted,
        )
        self.lbl_settings_hint.pack(side="left", padx=12)

        self.settings_security_badge = ctk.CTkLabel(
            self.settings_header,
            text="LƯU CỤC BỘ",
            height=26,
            corner_radius=8,
            fg_color="#f1f5f9",
            text_color="#475569",
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
        )
        self.settings_security_badge.pack(side="right")

        self.settings_card = ctk.CTkFrame(
            self.bottom_panel, fg_color="transparent"
        )
        self.settings_card.pack(fill="x", padx=14, pady=(2, 12))
        for column, weight in enumerate((2, 1, 2, 2, 2, 0, 0)):
            self.settings_card.columnconfigure(column, weight=weight)

        def make_setting_field(
            column, label, placeholder, show=None, row=0, columnspan=1
        ):
            wrapper = ctk.CTkFrame(self.settings_card, fg_color="transparent")
            wrapper.grid(
                row=row,
                column=column,
                columnspan=columnspan,
                sticky="ew",
                padx=4,
                pady=(0, 7) if row == 0 else (5, 0),
            )
            ctk.CTkLabel(
                wrapper,
                text=label,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color=muted,
                anchor="w",
            ).pack(fill="x", padx=2, pady=(0, 3))
            entry = ctk.CTkEntry(
                wrapper,
                placeholder_text=placeholder,
                show=show or "",
                height=42,
                **field_style,
            )
            entry.pack(fill="x")
            return entry

        self.ent_token = make_setting_field(
            0, "TELEGRAM BOT TOKEN", "Nhập Telegram Bot Token", show="*"
        )
        self.ent_token.insert(0, config.TELEGRAM_BOT_TOKEN or "")

        admin_ids_str = ",".join(map(str, config.ALLOWED_USER_IDS or []))
        self.ent_admins = make_setting_field(
            1, "ADMIN IDS", "ID được phép dùng bot"
        )
        self.ent_admins.insert(0, admin_ids_str)

        self.ent_adb = make_setting_field(
            2, "ĐƯỜNG DẪN ADB", "Đường dẫn adb.exe"
        )
        self.ent_adb.insert(0, config.ADB_PATH or "")

        shops_str = ",".join(config.SHOPEE_SHOP_NAMES or [])
        self.ent_shops = make_setting_field(
            3, "SHOP DỰ PHÒNG", "Tên shop, phân cách bằng dấu phẩy"
        )
        self.ent_shops.insert(0, shops_str)

        self.ent_gemini_key = make_setting_field(
            4, "GEMINI API KEY", "Nhập Gemini API Key", show="*"
        )
        self.ent_gemini_key.insert(0, config.GEMINI_API_KEY or "")

        self.btn_check_gemini = ctk.CTkButton(
            self.settings_card,
            text="Kiểm tra API",
            font=button_font,
            fg_color=violet,
            hover_color="#5b21b6",
            text_color="#ffffff",
            corner_radius=10,
            height=42,
            width=112,
            cursor="hand2",
            command=self.check_gemini_api_action,
        )
        self.btn_check_gemini.grid(
            row=0, column=5, padx=(10, 4), pady=(19, 0)
        )

        self.btn_save = ctk.CTkButton(
            self.settings_card,
            text="Lưu cấu hình",
            font=button_font,
            fg_color=blue,
            hover_color=blue_hover,
            text_color="#ffffff",
            corner_radius=10,
            height=42,
            width=120,
            cursor="hand2",
            command=self.save_settings,
        )
        self.btn_save.grid(row=0, column=6, padx=(4, 4), pady=(19, 0))

        self.ent_notion_token = make_setting_field(
            0,
            "NOTION API TOKEN",
            "Dán token integration Notion",
            show="*",
            row=1,
            columnspan=2,
        )
        self.ent_notion_token.insert(0, config.NOTION_API_TOKEN or "")

        self.ent_notion_source_id = make_setting_field(
            2,
            "NOTION DATABASE URL / DATA SOURCE ID",
            "Dán link bảng Notion hoặc Data Source ID",
            row=1,
            columnspan=3,
        )
        self.ent_notion_source_id.insert(0, config.NOTION_DATA_SOURCE_ID or "")

        self.lbl_notion_hint = ctk.CTkLabel(
            self.settings_card,
            text="Bật lịch tuần trong Notion rồi bấm nút quét trên thanh công cụ",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=muted,
            anchor="w",
        )
        self.lbl_notion_hint.grid(
            row=1, column=5, columnspan=2, sticky="ew", padx=8, pady=(23, 0)
        )

        # Subtle glass border response and a short window fade-in. These are
        # presentation-only effects and do not touch automation state.
        self._bind_glass_hover(self.top_header, border, border_hover)
        self._bind_glass_hover(self.log_card, border, border_hover)
        self._bind_glass_hover(self.shopee_scroll, border, "#f1b98d")
        self._bind_glass_hover(self.tiktok_scroll, border, "#e4a7c5")
        self._bind_glass_hover(self.facebook_scroll, border, border_hover)
        self._bind_glass_hover(self.bottom_panel, border, border_hover)
        try:
            self.attributes("-alpha", 0.0)
            self.after(20, self._fade_in)
        except Exception:
            pass
        self.after(80, self._maximize_window)
        self.after_idle(self._reset_operation_scrolls)
        self.after(600, self._reset_operation_scrolls)
        self.after(1600, self._reset_operation_scrolls)
        self.after(3200, self._reset_operation_scrolls)
        self.after(5200, self._reset_operation_scrolls)

        # Quét thiết bị khi vừa khởi động
        self.refresh_devices_action()
        # Thiết bị Box Phone có thể kết nối muộn hoặc tự bật lại cảm biến xoay.
        # Kiểm tra định kỳ để Facebook, Shopee và các app luôn giữ hướng dọc.
        self.after(15000, self._portrait_guard_tick)
        # Khởi chạy bot Telegram ở luồng phụ
        self.start_bot_service()

    def _bind_glass_hover(self, widget, base_border, hover_border):
        """Tạo phản hồi viền nhẹ cho card kính, không ảnh hưởng callback nghiệp vụ."""
        widget.bind(
            "<Enter>",
            lambda _event: widget.configure(border_color=hover_border),
            add="+",
        )
        widget.bind(
            "<Leave>",
            lambda _event: widget.configure(border_color=base_border),
            add="+",
        )

    def _maximize_window(self):
        """Maximize sau khi CustomTkinter hoàn tất khởi tạo DPI scaling."""
        try:
            self.state("zoomed")
        except Exception:
            pass

    def _fade_in(self):
        """Hiệu ứng mở cửa sổ ngắn, dừng ngay khi đạt độ rõ 100%."""
        try:
            current = float(self.attributes("-alpha"))
            next_alpha = min(1.0, current + 0.1)
            self.attributes("-alpha", next_alpha)
            if next_alpha < 1.0:
                self.after(18, self._fade_in)
        except Exception:
            pass

    def _reset_operation_scrolls(self):
        """Luôn hiển thị tiêu đề hai card khi app vừa mở."""
        try:
            self.shopee_scroll._parent_canvas.yview_moveto(0)
            self.tiktok_scroll._parent_canvas.yview_moveto(0)
            self.facebook_scroll._parent_canvas.yview_moveto(0)
            # Giữ focus khởi động ở nút header để Textbox không tự yêu cầu
            # cuộn card Shopee xuống khi cửa sổ được kích hoạt lại.
            self.btn_refresh.focus_set()
        except Exception:
            pass

    def run_in_thread(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def refresh_devices_action(self):
        if "btn_refresh" in self.__dict__:
            self.btn_refresh.configure(state="disabled", text="Đang quét...")
        self._set_device_status_badge(None)

        def action():
            try:
                print("[Hệ thống] Đang quét cổng thiết bị USB/ADB...")
                devices = main.get_ordered_devices()
                self.after(
                    0,
                    lambda count=len(devices): self._set_device_status_badge(
                        count
                    ),
                )
                if devices:
                    print(f"[Hệ thống] ✅ Đã kết nối {len(devices)} thiết bị điện thoại Box Phone:")
                    for idx, dev in enumerate(devices):
                        print(f"   📱 [{idx+1}] Máy {main.get_device_name(dev)} (ID: {dev})")
                    self.bulk_disable_rotation(devices)
                else:
                    print("[Hệ thống] ❌ Chưa phát hiện thiết bị nào. Hãy kết nối cáp USB và kiểm tra ADB.")
            finally:
                if "btn_refresh" in self.__dict__:
                    self.after(
                        0,
                        lambda: self.btn_refresh.configure(
                            state="normal", text="Quét thiết bị"
                        ),
                    )
        self.run_in_thread(action)

    def _set_device_status_badge(self, count):
        badge = self.__dict__.get("device_status_badge")
        if badge is None:
            return
        if count is None:
            badge.configure(
                text="ĐANG QUÉT THIẾT BỊ",
                fg_color="#eff6ff",
                text_color="#1d4ed8",
            )
        elif count > 0:
            badge.configure(
                text=f"{count} THIẾT BỊ KẾT NỐI",
                fg_color="#ecfdf5",
                text_color="#047857",
            )
        else:
            badge.configure(
                text="CHƯA CÓ THIẾT BỊ",
                fg_color="#fff7ed",
                text_color="#c2410c",
            )

    def mute_all_devices_action(self):
        """Tắt âm lượng media của toàn bộ điện thoại đang kết nối."""
        devices = main.get_ordered_devices()
        if not devices:
            messagebox.showwarning(
                "Chưa có thiết bị",
                "Không có điện thoại nào đang kết nối!",
            )
            return

        self.btn_mute_all.configure(
            state="disabled",
            text="Đang tắt âm...",
        )

        def action():
            from concurrent.futures import ThreadPoolExecutor

            def mute_device(device_id):
                try:
                    return device_id, main.adb.mute_media_volume(device_id)
                except Exception:
                    return device_id, False

            with ThreadPoolExecutor(
                max_workers=min(8, len(devices))
            ) as executor:
                results = list(executor.map(mute_device, devices))

            succeeded = [device for device, ok in results if ok]
            failed = [device for device, ok in results if not ok]
            print(
                f"[Âm lượng] Đã tắt âm media {len(succeeded)}/{len(devices)} máy."
            )
            if failed:
                failed_names = ", ".join(
                    main.get_device_name(device) for device in failed
                )
                print(f"[Âm lượng] Không tắt được: {failed_names}.")

            self.after(
                0,
                lambda: self.btn_mute_all.configure(
                    state="normal",
                    text="Tắt âm tất cả",
                ),
            )

        self.run_in_thread(action)

    def check_gemini_api_action(self):
        """Kiểm tra key hiện có trong ô bằng một request Gemini thật."""
        api_key = self.ent_gemini_key.get().strip()
        self.btn_check_gemini.configure(
            state="disabled",
            text="Đang kiểm tra...",
            fg_color="#64748b",
        )

        def action():
            ok, code, message = config.check_gemini_api(api_key)
            print(f"[Gemini API] {message} (mã: {code})")

            def finish():
                self.btn_check_gemini.configure(
                    state="normal",
                    text=("API hoạt động" if ok else "Kiểm tra lại"),
                    fg_color=("#047857" if ok else "#c81e2b"),
                    hover_color=("#065f46" if ok else "#a91623"),
                )
                if ok:
                    messagebox.showinfo("Gemini API", message)
                else:
                    messagebox.showwarning("Gemini API", message)

            self.after(0, finish)

        self.run_in_thread(action)

    @staticmethod
    def _replace_entry_value(widget, value):
        widget.delete(0, "end")
        widget.insert(0, value)

    @staticmethod
    def _normalize_shopee_keywords(value):
        return "\n".join(
            item.strip()
            for item in re.split(r"[,\n]+", value or "")
            if item.strip()
        )

    def _apply_notion_schedule(self, schedule):
        self.txt_main_keywords.delete("1.0", "end")
        self.txt_main_keywords.insert(
            "1.0", self._normalize_shopee_keywords(schedule.shopee_keywords)
        )
        self._replace_entry_value(
            self.ent_tt_seed, schedule.tiktok_seed_keywords
        )
        self._replace_entry_value(
            self.ent_tt_channel, schedule.tiktok_target_channels
        )
        self._replace_entry_value(
            self.ent_fb_seed, schedule.facebook_seed_keywords
        )
        self._replace_entry_value(
            self.ent_fb_target, schedule.facebook_target_pages
        )

    def _load_notion_schedule(self, schedule, token):
        self._apply_notion_schedule(schedule)
        period = (
            f"{schedule.start_date:%d/%m/%Y} - "
            f"{schedule.end_date:%d/%m/%Y}"
        )
        self.log_message(
            f"[Notion] Đã nạp lịch '{schedule.title}' ({period}) "
            "vào Shopee, TikTok và Facebook."
        )
        messagebox.showinfo(
            "Đã chọn lịch Notion",
            f"Đã nạp lịch: {schedule.title}\nThời gian: {period}",
        )

        def update_scan_time():
            try:
                mark_schedule_scanned(token, schedule.page_id)
            except NotionSyncError as exc:
                self.log_message(
                    f"[Notion] Đã nạp dữ liệu nhưng chưa ghi được lần quét: {exc}"
                )

        self.run_in_thread(update_scan_time)

    def _show_notion_schedule_picker(self, schedules, token):
        picker = ctk.CTkToplevel(self)
        picker.title("Chọn lịch từ khóa Notion")
        picker.geometry("620x520")
        picker.minsize(520, 380)
        picker.configure(fg_color="#f3f6fb")
        picker.transient(self)
        picker.grab_set()

        ctk.CTkLabel(
            picker,
            text="Chọn lịch từ khóa để nạp",
            font=ctk.CTkFont(family="Segoe UI", size=21, weight="bold"),
            text_color="#0f172a",
        ).pack(anchor="w", padx=22, pady=(20, 3))
        ctk.CTkLabel(
            picker,
            text=(
                f"Đã tìm thấy {len(schedules)} lịch đang áp dụng. "
                "Bấm đúng tên lịch cần chạy."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#64748b",
        ).pack(anchor="w", padx=22, pady=(0, 12))

        schedule_list = ctk.CTkScrollableFrame(
            picker,
            fg_color="#ffffff",
            border_width=1,
            border_color="#e2e8f0",
            corner_radius=14,
        )
        schedule_list.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        def choose(schedule):
            picker.grab_release()
            picker.destroy()
            self._load_notion_schedule(schedule, token)

        for schedule in schedules:
            period = (
                f"{schedule.start_date:%d/%m/%Y} - "
                f"{schedule.end_date:%d/%m/%Y}"
            )
            ctk.CTkButton(
                schedule_list,
                text=f"{schedule.title}\n{period}",
                anchor="w",
                height=62,
                font=ctk.CTkFont(
                    family="Segoe UI", size=13, weight="bold"
                ),
                fg_color="#eff6ff",
                hover_color="#dbeafe",
                text_color="#1e3a8a",
                border_width=1,
                border_color="#bfdbfe",
                corner_radius=11,
                command=lambda item=schedule: choose(item),
            ).pack(fill="x", padx=8, pady=6)

    def scan_notion_keywords_action(self):
        token = self.ent_notion_token.get().strip()
        source_id = self.ent_notion_source_id.get().strip()
        self.btn_scan_notion.configure(
            state="disabled", text="Đang quét Notion..."
        )

        def action():
            try:
                schedules = fetch_enabled_keyword_schedules(token, source_id)
                self.after(
                    0,
                    lambda: self._show_notion_schedule_picker(
                        schedules, token
                    ),
                )
            except NotionSyncError as exc:
                self.log_message(f"[Notion] Quét thất bại: {exc}")
                self.after(
                    0,
                    lambda message=str(exc): messagebox.showwarning(
                        "Không quét được Notion", message
                    ),
                )
            finally:
                self.after(
                    0,
                    lambda: self.btn_scan_notion.configure(
                        state="normal", text="Quét từ khóa Notion"
                    ),
                )

        self.run_in_thread(action)

    def save_settings(self):
        token = self.ent_token.get().strip()
        admin_ids = self.ent_admins.get().strip()
        adb_path = self.ent_adb.get().strip()
        shops = self.ent_shops.get().strip()
        gemini_key = self.ent_gemini_key.get().strip()
        notion_token = self.ent_notion_token.get().strip()
        notion_source_id = self.ent_notion_source_id.get().strip()
        
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
        keys = {
            'TELEGRAM_BOT_TOKEN': token,
            'TELEGRAM_NOTIFICATIONS_ENABLED': (
                '1' if config.TELEGRAM_NOTIFICATIONS_ENABLED else '0'
            ),
            'ALLOWED_USER_IDS': admin_ids,
            'ADB_PATH': adb_path,
            'SHOPEE_SHOP_NAMES': shops,
            'GEMINI_API_KEY': gemini_key,
            'NOTION_API_TOKEN': notion_token,
            'NOTION_DATA_SOURCE_ID': notion_source_id,
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
        config.NOTION_API_TOKEN = notion_token
        config.NOTION_DATA_SOURCE_ID = notion_source_id
        
        # Re-initialize bot object
        import telebot
        main.bot = telebot.TeleBot(token)
        
        print("[Hệ thống] Lưu cấu hình và tải lại thành công!")
        messagebox.showinfo("Thành công", "Đã lưu cấu hình và tự động nạp lại!")

    def _persist_env_setting(self, key, value):
        """Cap nhat mot khoa .env ma khong ghi de cac cau hinh khac."""
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as env_file:
                lines = env_file.readlines()

        prefix = f"{key}="
        new_line = f"{prefix}{value}\n"
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(prefix):
                if not updated:
                    new_lines.append(new_line)
                    updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(new_line)

        with open(env_path, "w", encoding="utf-8") as env_file:
            env_file.writelines(new_lines)

    def _refresh_telegram_notifications_button(self):
        enabled = bool(config.TELEGRAM_NOTIFICATIONS_ENABLED)
        self.btn_telegram_notifications.configure(
            text="Telegram: BẬT" if enabled else "Telegram: TẮT",
            fg_color="#0f9f6e" if enabled else "#64748b",
            hover_color="#0b815a" if enabled else "#475569",
        )

    def toggle_telegram_notifications(self):
        enabled = not bool(config.TELEGRAM_NOTIFICATIONS_ENABLED)
        config.TELEGRAM_NOTIFICATIONS_ENABLED = enabled
        self._persist_env_setting(
            "TELEGRAM_NOTIFICATIONS_ENABLED", "1" if enabled else "0"
        )
        self._refresh_telegram_notifications_button()

        if enabled:
            print("[Telegram] Đã bật thông báo và kết nối bot.")
            self.start_bot_service()
        else:
            try:
                main.bot.stop_polling()
            except Exception:
                pass
            print("[Telegram] Đã tắt toàn bộ thông báo và kết nối bot.")

    def stop_all(self):
        main.cancel_all_workflows()
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
                    return main.adb.lock_portrait(d)
                except Exception:
                    return False
            from concurrent.futures import ThreadPoolExecutor
            if target_devices:
                with ThreadPoolExecutor(max_workers=max(1, len(target_devices))) as executor:
                    executor.map(disable_rot, target_devices)
        self.run_in_thread(action)

    def prepare_social_targets(
        self, target_devices, opening_platform, is_cancelled=None
    ):
        """Đưa toàn bộ máy mục tiêu khỏi Shopee trước khi xếp hàng social."""
        if not target_devices:
            return []

        def prepare_device(device_id):
            if is_cancelled and is_cancelled():
                return device_id, False
            try:
                # Máy đang chờ lượt không được giữ Shopee trên foreground.
                main.adb.stop_app(device_id, config.SHOPEE_PACKAGE)
                if is_cancelled and is_cancelled():
                    return device_id, False
                if opening_platform == "facebook":
                    ready = main.adb.ensure_facebook_ready(device_id)
                elif opening_platform == "tiktok":
                    main.adb.launch_tiktok(device_id)
                    ready = main.adb.is_tiktok_in_foreground(device_id)
                else:
                    raise ValueError(
                        f"Nền tảng mở đầu không hợp lệ: {opening_platform}"
                    )
                return device_id, bool(ready)
            except Exception:
                return device_id, False

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(
            max_workers=max(1, len(target_devices))
        ) as executor:
            results = list(executor.map(prepare_device, target_devices))

        failed = [device_id for device_id, ready in results if not ready]
        if failed and not (is_cancelled and is_cancelled()):
            failed_names = ", ".join(
                main.get_device_name(device_id) for device_id in failed
            )
            print(
                f"[GUI] Cảnh báo: chưa mở được {opening_platform} trên "
                f"máy {failed_names}; workflow sẽ thử lại và dừng an toàn "
                "nếu vẫn sai ứng dụng."
            )
        return results

    def _portrait_guard_tick(self):
        """Khóa lại hướng dọc cho mọi máy kết nối mà không chặn giao diện."""
        self.bulk_disable_rotation()
        self.after(30000, self._portrait_guard_tick)

    def toggle_shopee_keyword_box(self, box_name):
        box = self._shopee_keyword_boxes.get(box_name)
        if not box:
            return

        expanded = not box["expanded"]
        box["expanded"] = expanded
        box["textbox"].configure(height=220 if expanded else 64)
        box["button"].configure(
            text="Thu nhỏ ▲" if expanded else "Mở rộng ▼"
        )

    def toggle_system_log(self):
        """Mở rộng vùng log để xem chi tiết, bấm lại để trở về bố cục gọn."""
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            expanded_height = max(
                320,
                min(520, int(self.winfo_height() * 0.48)),
            )
            self.log_box.configure(height=expanded_height)
            self.btn_toggle_log.configure(
                text="Thu nhỏ",
                fg_color="#dbeafe",
                border_color="#93c5fd",
            )
        else:
            self.log_box.configure(height=78)
            self.btn_toggle_log.configure(
                text="Mở rộng",
                fg_color="#eff6ff",
                border_color="#bfdbfe",
            )
        self.after_idle(lambda: self.log_box.see("end"))

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
        workflow_session = main.start_workflow_session()
            
        def action():
            nonlocal keywords
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
            main.run_sequential_shopee_search(
                DummyMessage(),
                keywords,
                target_devices,
                click_first_item=click_first_item,
                use_ai=False,
                session_id=workflow_session,
            )
            
        self.run_in_thread(action)

    def run_par_search(self, adaptive=False):
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
        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )
            
        def action():
            nonlocal keywords
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
            
            run_mode = "thích ứng" if adaptive else "song song"
            print(
                f"[GUI] Bắt đầu tìm kiếm {run_mode} "
                f"(Mở rộng từ Gemini) trên {len(target_devices)} máy..."
            )

            keyword_assignments = main.assign_shopee_keywords(
                keywords,
                target_devices,
            )
            chat_id = (
                config.ALLOWED_USER_IDS[0]
                if config.ALLOWED_USER_IDS
                else None
            )
            markup = None
            if chat_id:
                markup = main.telebot.types.InlineKeyboardMarkup()
                markup.add(
                    main.telebot.types.InlineKeyboardButton(
                        "🛑 DỪNG CHẠY KHẨN CẤP",
                        callback_data="stop_all",
                    )
                )
                main.safe_send_message(
                    chat_id,
                    f"🚀 **BẮT ĐẦU CHẠY SONG SONG SHOPEE**\n\n"
                    f"🔑 Kho từ khóa: **{len(keywords)} từ khóa**\n"
                    f"📱 Tổng số profile: **{len(target_devices)}**\n"
                    f"🎲 Mỗi profile nhận một từ khóa random riêng\n"
                    f"🧭 Chế độ bấm sản phẩm đầu tiên: "
                    f"**{click_first_item}**\n\n"
                    f"_(Mỗi profile có một log thời gian thực riêng)_",
                    parse_mode="Markdown",
                    reply_markup=markup,
                )

            target_positions = {
                device_id: index + 1
                for index, device_id in enumerate(target_devices)
            }
            
            def run_search_parallel(device_id):
                dev_idx = target_positions[device_id]
                dev_name = main.get_device_name(device_id)
                current_keyword = keyword_assignments[device_id]
                tracker = None
                if chat_id:
                    tracker = main.start_shopee_profile_tracker(
                        chat_id,
                        dev_name,
                        device_id,
                        current_keyword,
                        dev_idx,
                        len(target_devices),
                    )
                print(
                    f"[Profile {dev_name}] Bắt đầu tìm kiếm với "
                    f"từ khóa '{current_keyword}'..."
                )
                
                dev_start = time.time()
                success, err = main.adb.shopee_find_and_click_lamdong(
                    device_id, 
                    current_keyword, 
                    status_callback=(
                        tracker.status_callback if tracker else None
                    ),
                    is_cancelled=session_is_cancelled,
                    click_first_item=click_first_item
                )
                dev_duration = time.time() - dev_start
                if tracker:
                    main.finish_shopee_profile_tracker(
                        tracker,
                        success,
                        err,
                        dev_duration,
                    )
                if success:
                    print(
                        f"[Profile {dev_name}] ✅ Hoàn thành trọn vẹn "
                        f"quy trình với từ khóa '{current_keyword}'!"
                    )
                else:
                    print(f"[Profile {dev_name}] ❌ Thất bại: {err}")
                return dev_name, current_keyword, success, err
                
            if adaptive:
                policy = PLATFORM_POLICIES["shopee"]
                results = run_adaptive(
                    target_devices,
                    run_search_parallel,
                    policy,
                    is_cancelled=session_is_cancelled,
                    on_wait=lambda dev, delay, position, total: print(
                        f"[GUI] Shopee thích ứng: máy "
                        f"{main.get_device_name(dev)} đang chờ {delay}s "
                        f"({position + 1}/{total})."
                    ),
                )
            else:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(
                    max_workers=len(target_devices)
                ) as executor:
                    futures = [
                        executor.submit(run_search_parallel, dev)
                        for dev in target_devices
                    ]
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
            if chat_id:
                main.safe_send_message(
                    chat_id,
                    summary,
                    parse_mode="Markdown",
                )
            
        self.run_in_thread(action)

    # ================= CÁC TÁC VỤ BƠM TIKTOK =================
    def run_seq_tiktok(self):
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

        self.bulk_disable_rotation(target_devices=target_devices)
        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )

        print(f"[GUI] Bắt đầu chạy TikTok Tuần Tự trên {len(target_devices)} máy...")

        def action():
            self.prepare_social_targets(
                target_devices,
                "facebook",
                is_cancelled=session_is_cancelled,
            )
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
                if session_is_cancelled():
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
                    is_cancelled=session_is_cancelled
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

    def run_par_tiktok(self, adaptive=False):
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

        self.bulk_disable_rotation(target_devices=target_devices)
        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )

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
                is_cancelled=session_is_cancelled
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
            self.prepare_social_targets(
                target_devices,
                "facebook",
                is_cancelled=session_is_cancelled,
            )
            if adaptive:
                policy = PLATFORM_POLICIES["tiktok"]
                results = run_adaptive(
                    target_devices,
                    run_parallel_tt,
                    policy,
                    is_cancelled=session_is_cancelled,
                    on_wait=lambda dev, delay, position, total: print(
                        f"[GUI] TikTok thích ứng: máy "
                        f"{main.get_device_name(dev)} đang chờ {delay}s "
                        f"({position + 1}/{total})."
                    ),
                )
            else:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(
                    max_workers=len(target_devices)
                ) as executor:
                    results = list(
                        executor.map(run_parallel_tt, target_devices)
                    )

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

    # ================= CÁC TÁC VỤ BƠM FACEBOOK =================
    def run_seq_facebook(self):
        seed_raw = self.ent_fb_seed.get().strip()
        target_raw = self.ent_fb_target.get().strip()
        if not seed_raw:
            messagebox.showwarning(
                "Cảnh báo", "Vui lòng nhập từ khóa mồi Facebook!"
            )
            return
        if not target_raw:
            messagebox.showwarning(
                "Cảnh báo", "Vui lòng nhập Page target Facebook!"
            )
            return
        target_devices = self.parse_targets(
            entry_widget=self.ent_fb_selection
        )
        if not target_devices:
            return

        self.bulk_disable_rotation(target_devices=target_devices)
        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )

        def action():
            self.prepare_social_targets(
                target_devices,
                "tiktok",
                is_cancelled=session_is_cancelled,
            )
            chat_id = (
                config.ALLOWED_USER_IDS[0]
                if config.ALLOWED_USER_IDS
                else None
            )
            success_count = 0
            for index, device_id in enumerate(target_devices):
                if session_is_cancelled():
                    break
                device_name = main.get_device_name(device_id)
                tracker = None
                if chat_id:
                    try:
                        tracker = main.TelegramRealtimeTracker(
                            main.bot, chat_id
                        )
                        tracker.set_active_device(
                            device_name,
                            device_id,
                            f"Facebook: {target_raw}",
                            index + 1,
                            len(target_devices),
                            platform="Facebook",
                        )
                        tracker.start_dashboard(
                            tracker.render_progress_text()
                        )
                    except Exception as exc:
                        print(
                            "[GUI] Không tạo được Telegram Tracker "
                            f"Facebook: {exc}"
                        )
                        tracker = None

                def fb_status_callback(dev, message):
                    self.log_message(f"[Máy {device_name}] {message}")
                    if tracker:
                        tracker.status_callback(dev, message)

                started_at = time.time()
                success, message = main.adb.facebook_automation_workflow(
                    device_id,
                    seed_keywords=seed_raw,
                    target_pages=target_raw,
                    status_callback=fb_status_callback,
                    is_cancelled=session_is_cancelled,
                )
                duration = time.time() - started_at
                if success:
                    success_count += 1
                if tracker:
                    duration_text = (
                        f"{int(duration // 60)} phút {int(duration % 60)} giây"
                    )
                    tracker.finish_dashboard(
                        (
                            f"✅ **PROFILE {device_name} HOÀN THÀNH FACEBOOK**\n"
                            f"🎯 Target: `{target_raw}`\n"
                            f"⏱️ Thời gian: **{duration_text}**"
                            if success
                            else
                            f"❌ **PROFILE {device_name} FACEBOOK THẤT BẠI**\n"
                            f"⚠️ `{message}`"
                        )
                    )
                if not success:
                    print(
                        f"[GUI] ❌ Facebook máy {device_name} "
                        f"THẤT BẠI: {message}"
                    )

            summary = (
                f"🏁 **FACEBOOK TUẦN TỰ HOÀN TẤT**\n\n"
                f"📱 Thành công: **{success_count}/{len(target_devices)} máy**"
            )
            if chat_id:
                main.safe_send_message(
                    chat_id, summary, parse_mode="Markdown"
                )
            print(
                f"[GUI] Facebook Tuần Tự: "
                f"{success_count}/{len(target_devices)} máy thành công."
            )

        self.run_in_thread(action)

    def run_par_facebook(self, adaptive=False):
        seed_raw = self.ent_fb_seed.get().strip()
        target_raw = self.ent_fb_target.get().strip()
        if not seed_raw:
            messagebox.showwarning(
                "Cảnh báo", "Vui lòng nhập từ khóa mồi Facebook!"
            )
            return
        if not target_raw:
            messagebox.showwarning(
                "Cảnh báo", "Vui lòng nhập Page target Facebook!"
            )
            return
        target_devices = self.parse_targets(
            entry_widget=self.ent_fb_selection
        )
        if not target_devices:
            return

        self.bulk_disable_rotation(target_devices=target_devices)
        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )
        chat_id = (
            config.ALLOWED_USER_IDS[0]
            if config.ALLOWED_USER_IDS
            else None
        )

        def run_device(device_id):
            device_name = main.get_device_name(device_id)
            tracker = None
            if chat_id:
                try:
                    tracker = main.TelegramRealtimeTracker(main.bot, chat_id)
                    tracker.set_active_device(
                        device_name,
                        device_id,
                        f"Facebook: {target_raw}",
                        1,
                        1,
                        platform="Facebook",
                    )
                    tracker.start_dashboard(tracker.render_progress_text())
                except Exception:
                    tracker = None

            def fb_status_callback(dev, message):
                self.log_message(f"[Máy {device_name}] {message}")
                if tracker:
                    tracker.status_callback(dev, message)

            success, message = main.adb.facebook_automation_workflow(
                device_id,
                seed_keywords=seed_raw,
                target_pages=target_raw,
                status_callback=fb_status_callback,
                is_cancelled=session_is_cancelled,
            )
            if tracker:
                tracker.finish_dashboard(
                    (
                        f"✅ **PROFILE {device_name} HOÀN THÀNH FACEBOOK**"
                        if success
                        else
                        f"❌ **PROFILE {device_name} FACEBOOK THẤT BẠI**\n"
                        f"⚠️ `{message}`"
                    )
                )
            return device_name, success, message

        def action():
            self.prepare_social_targets(
                target_devices,
                "tiktok",
                is_cancelled=session_is_cancelled,
            )
            if adaptive:
                policy = PLATFORM_POLICIES["facebook"]
                results = run_adaptive(
                    target_devices,
                    run_device,
                    policy,
                    is_cancelled=session_is_cancelled,
                    on_wait=lambda dev, delay, position, total: print(
                        f"[GUI] Facebook thích ứng: máy "
                        f"{main.get_device_name(dev)} đang chờ {delay}s "
                        f"({position + 1}/{total})."
                    ),
                )
            else:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(
                    max_workers=len(target_devices)
                ) as executor:
                    results = list(executor.map(run_device, target_devices))
            success_count = sum(
                1 for _, success, _ in results if success
            )
            for device_name, success, message in results:
                if not success:
                    print(
                        f"[GUI] ❌ Facebook máy {device_name} "
                        f"THẤT BẠI: {message}"
                    )
            summary = (
                f"🏁 **FACEBOOK SONG SONG HOÀN TẤT**\n\n"
                f"📱 Thành công: **{success_count}/{len(target_devices)} máy**"
            )
            if chat_id:
                main.safe_send_message(
                    chat_id, summary, parse_mode="Markdown"
                )
            print(
                f"[GUI] Facebook Song Song: "
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
        if self.__dict__.get("_bot_service_started", False):
            return
        self._bot_service_started = True

        def run():
            print("[Hệ thống] Bot Telegram đang khởi động dưới nền...")
            skip_pending_on_start = True
            while True:
                try:
                    if (
                        config.TELEGRAM_NOTIFICATIONS_ENABLED
                        and config.TELEGRAM_BOT_TOKEN
                    ):
                        skip_pending = skip_pending_on_start
                        skip_pending_on_start = False
                        main.bot.polling(
                            none_stop=True,
                            skip_pending=skip_pending,
                            interval=1,
                            timeout=20,
                        )
                    else:
                        time.sleep(1)
                except Exception as e:
                    if config.TELEGRAM_NOTIFICATIONS_ENABLED:
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

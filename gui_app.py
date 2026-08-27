import os
import sys
import time
import re
import random
import shutil
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from dotenv import dotenv_values, load_dotenv

# Đảm bảo đường dẫn module chính xác
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import main
from adaptive_scheduler import PLATFORM_POLICIES, run_adaptive
from notion_keyword_sync import (
    NotionSyncError,
    PUMP_STATUS_PROCESSING,
    fetch_enabled_keyword_schedules,
    mark_schedule_completed,
    mark_schedule_processing,
    mark_schedule_scanned,
)

# Bright operations dashboard with a lightweight iOS-inspired glass treatment.
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class GUIApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("BoxPhoneControl")
        # Mở vừa vùng làm việc thực tế thay vì dùng kích thước cố định lớn hơn
        # màn hình, tránh cắt huy hiệu và nút thao tác ngoài cùng bên phải.
        available_width = max(960, self.winfo_screenwidth() - 64)
        available_height = max(700, self.winfo_screenheight() - 96)
        window_width = min(1660, available_width)
        window_height = min(940, available_height)
        self.geometry(f"{window_width}x{window_height}")
        self.minsize(min(1280, window_width), min(720, window_height))
        self.configure(fg_color="#eef3f9")

        # Design tokens: light "liquid glass" surfaces rendered with native
        # CustomTkinter layers so the dashboard remains fast with many devices.
        bg = "#eef3f9"
        glass = "#ffffff"
        glass_tint = "#f8fafc"
        surface = "#ffffff"
        border = "#e2e8f0"
        border_hover = "#93b4ea"
        text = "#0f172a"
        muted = "#64748b"
        blue = "#2563eb"
        blue_hover = "#1d4ed8"
        blue_soft = "#eff6ff"
        orange = "#c2410c"
        orange_soft = "#fff7ed"
        pink = "#be185d"
        pink_soft = "#fdf2f8"
        violet = "#7c3aed"
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
        self._bulk_rotation_lock = threading.Lock()
        self._active_notion_schedule = None
        self._active_notion_token = ""
        # Hai công tắc thuộc hai module độc lập. Không dùng chung BooleanVar,
        # nếu không thao tác ở TikTok sẽ làm Facebook tự bật (và ngược lại).
        self.tiktok_combined_var = ctk.BooleanVar(value=False)
        self.facebook_combined_var = ctk.BooleanVar(value=False)
        self.social_combined_var = ctk.BooleanVar(value=False)
        self.auto_schedule_var = ctk.BooleanVar(value=config.AUTO_SCHEDULE_ENABLED)
        
        # Main Grid Layout: Header, live log, two operation cards, settings.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        
        # ================= ROW 0: GLASS HEADER =================
        self.top_header = ctk.CTkFrame(
            self,
            fg_color="#0f172a",
            corner_radius=18,
            border_width=1,
            border_color="#1e293b",
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
            fg_color="#2563eb",
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
            text_color="#f8fafc",
        )
        self.lbl_brand.pack(anchor="w")
        
        self.lbl_sub_brand = ctk.CTkLabel(
            self.brand_copy,
            text="Điều hành Facebook + TikTok  •  Theo dõi đa thiết bị",
            font=body_font,
            text_color="#94a3b8",
        )
        self.lbl_sub_brand.pack(anchor="w", pady=(1, 0))

        self.platform_badge = ctk.CTkLabel(
            self.brand_badge,
            text="2 QUY TRÌNH",
            height=34,
            corner_radius=17,
            fg_color="#1e293b",
            text_color="#cbd5e1",
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

        self.btn_complete_notion = ctk.CTkButton(
            self.brand_badge,
            text="Hoàn thành tuần",
            font=button_font,
            width=150,
            height=44,
            fg_color="#64748b",
            hover_color="#475569",
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            state="disabled",
            command=self.complete_notion_schedule_action,
        )
        self.btn_complete_notion.pack(side="right", padx=(10, 0), pady=2)

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
        self.ops_frame.rowconfigure(1, weight=0)
        self.ops_frame.rowconfigure(2, weight=1)

        self.workspace_header = ctk.CTkFrame(
            self.ops_frame, fg_color="transparent"
        )
        self.workspace_header.grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )
        ctk.CTkLabel(
            self.workspace_header,
            text="VẬN HÀNH FACEBOOK + TIKTOK",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#475569",
        ).pack(side="left")
        ctk.CTkLabel(
            self.workspace_header,
            text="Chọn máy  →  chọn chế độ chạy  →  theo dõi nhật ký trực tiếp",
            font=body_font,
            text_color=muted,
        ).pack(side="left", padx=12)
        ctk.CTkLabel(
            self.workspace_header,
            text="SẴN SÀNG  •  2 MÔ-ĐUN",
            height=28,
            corner_radius=9,
            fg_color="#ecfdf5",
            text_color=green,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        ).pack(side="right")

        self._module_focus_active = False
        self._module_focus_ready = False
        self.btn_restore_overview = ctk.CTkButton(
            self.workspace_header,
            text="Hiện tổng quan",
            width=124,
            height=30,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color="#ffffff",
            hover_color="#f8fafc",
            text_color=blue,
            border_width=1,
            border_color="#bfdbfe",
            corner_radius=9,
            cursor="hand2",
            command=self.restore_dashboard_overview,
        )

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

        # ---------------- FACEBOOK + TIKTOK COMBINED ----------------
        # This panel only orchestrates the two existing workflows. Their
        # internal steps and timing remain owned by each platform module.
        self.social_combined_panel = ctk.CTkFrame(
            self.ops_frame,
            fg_color="#f5f3ff",
            corner_radius=16,
            border_width=1,
            border_color="#ddd6fe",
        )
        self.social_combined_panel.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(0, 9),
        )
        self.social_combined_panel.columnconfigure(1, weight=1)

        self.social_combined_mark = ctk.CTkLabel(
            self.social_combined_panel,
            text="F + T",
            width=54,
            height=40,
            corner_radius=12,
            fg_color="#ffffff",
            text_color=violet,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.social_combined_mark.grid(row=0, column=0, padx=(12, 10), pady=10)

        self.social_combined_copy = ctk.CTkFrame(
            self.social_combined_panel, fg_color="transparent"
        )
        self.social_combined_copy.grid(
            row=0, column=1, sticky="w", padx=(0, 12), pady=8
        )
        ctk.CTkLabel(
            self.social_combined_copy,
            text="CHẠY TRỌN BỘ FACEBOOK + TIKTOK",
            font=label_font,
            text_color=text,
        ).pack(anchor="w")
        ctk.CTkLabel(
            self.social_combined_copy,
            text="Mỗi máy hoàn tất đủ 2 quy trình • Trạng thái cập nhật trong nhật ký",
            font=body_font,
            text_color=muted,
        ).pack(anchor="w")

        self.ent_social_selection = ctk.CTkEntry(
            self.social_combined_panel,
            placeholder_text="Máy cần chạy: 1-5,10 • Bỏ trống = tất cả",
            width=290,
            height=40,
            **field_style,
        )
        self.ent_social_selection.grid(
            row=0, column=2, sticky="ew", padx=(0, 8), pady=10
        )

        self.social_combined_actions = ctk.CTkFrame(
            self.social_combined_panel, fg_color="transparent"
        )
        self.social_combined_actions.grid(
            row=0, column=3, sticky="e", padx=(0, 12), pady=10
        )
        self.btn_social_combined_seq = ctk.CTkButton(
            self.social_combined_actions,
            text="Tuần tự từng máy",
            width=142,
            height=44,
            font=button_font,
            fg_color=green,
            hover_color=green_hover,
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.run_combined_social_sequential,
        )
        self.btn_social_combined_seq.pack(side="left", padx=(0, 6))
        self.btn_social_combined_par = ctk.CTkButton(
            self.social_combined_actions,
            text="Song song nhiều máy",
            width=156,
            height=44,
            font=button_font,
            fg_color=blue,
            hover_color=blue_hover,
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.run_combined_social_parallel,
        )
        self.btn_social_combined_par.pack(side="left", padx=6)
        self.btn_social_combined_adaptive = ctk.CTkButton(
            self.social_combined_actions,
            text="Tự điều phối",
            width=128,
            height=44,
            font=button_font,
            fg_color=violet,
            hover_color="#5b21b6",
            text_color="#ffffff",
            corner_radius=12,
            cursor="hand2",
            command=self.run_combined_social_adaptive,
        )
        self.btn_social_combined_adaptive.pack(side="left", padx=(6, 0))

        # Một công tắc chung thay cho các điều khiển kết hợp rời rạc. Khi bật,
        # nút chạy trong bất kỳ module nào cũng thực hiện đủ hai quy trình.
        self.ent_social_selection.grid_remove()
        self.social_combined_actions.grid_remove()
        self.social_combined_right = ctk.CTkFrame(
            self.social_combined_panel, fg_color="transparent"
        )
        self.social_combined_right.grid(
            row=0,
            column=2,
            columnspan=2,
            sticky="e",
            padx=(12, 16),
            pady=6,
        )

        self.switch_social_combined = ctk.CTkSwitch(
            self.social_combined_right,
            text="Chạy hỗn hợp chung",
            variable=self.social_combined_var,
            onvalue=True,
            offvalue=False,
            width=180,
            height=36,
            switch_width=46,
            switch_height=24,
            font=button_font,
            text_color=text,
            fg_color=violet,
            progress_color=green,
            button_color="#ffffff",
            button_hover_color="#f8fafc",
        )
        self.switch_social_combined.pack(side="left", padx=(0, 14))

        self.switch_auto_schedule = ctk.CTkSwitch(
            self.social_combined_right,
            text="Hẹn giờ chạy",
            variable=self.auto_schedule_var,
            onvalue=True,
            offvalue=False,
            width=135,
            height=36,
            switch_width=46,
            switch_height=24,
            font=button_font,
            text_color=text,
            fg_color="#0f766e",
            progress_color=green,
            button_color="#ffffff",
            button_hover_color="#f8fafc",
        )
        self.switch_auto_schedule.pack(side="left", padx=(0, 8))

        self.ent_schedule_hours = ctk.CTkEntry(
            self.social_combined_right,
            placeholder_text="11:45, 19:30, 22:30",
            width=145,
            height=34,
            **field_style,
        )
        self.ent_schedule_hours.insert(0, config.AUTO_SCHEDULE_HOURS_DEFAULT)
        self.ent_schedule_hours.pack(side="left", padx=(0, 8))

        self.lbl_schedule_countdown = ctk.CTkLabel(
            self.social_combined_right,
            text="⏰ Lên lịch: TẮT",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=muted,
        )
        self.lbl_schedule_countdown.pack(side="left", padx=(0, 4))

        # Commercial workspace: one focused module at a time. This replaces
        # the previous three cramped columns while preserving every widget and
        # callback inside each automation module.
        self.module_tabs = ctk.CTkTabview(
            self.ops_frame,
            command=self._on_module_tab_changed,
            fg_color="transparent",
            segmented_button_fg_color="#e2e8f0",
            segmented_button_selected_color="#bfdbfe",
            segmented_button_selected_hover_color="#93c5fd",
            segmented_button_unselected_color="#e2e8f0",
            segmented_button_unselected_hover_color="#cbd5e1",
            text_color="#0f172a",
            corner_radius=16,
            border_width=0,
        )
        self.module_tabs.grid(
            row=2, column=0, columnspan=3, sticky="nsew", pady=(0, 0)
        )
        self.tiktok_tab = self.module_tabs.add("TikTok")
        self.facebook_tab = self.module_tabs.add("Facebook")
        self.module_tabs.set("TikTok")
        for module_tab in (
            self.tiktok_tab,
            self.facebook_tab,
        ):
            module_tab.configure(fg_color="transparent")
            module_tab.grid_columnconfigure(0, weight=1)
            module_tab.grid_rowconfigure(0, weight=1)

        # ---------------- TIKTOK AUTOMATION ----------------
        self.tiktok_scroll = ctk.CTkScrollableFrame(
            self.tiktok_tab,
            **scroll_style,
        )
        self.tiktok_scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

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
            text="1. Từ khóa nhiệm vụ • Phân cách bằng dấu phẩy",
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
            text="2. Kênh TikTok mục tiêu • Phân cách bằng dấu phẩy • Random 1 kênh",
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
                "00   Nuôi Facebook Feed  •  10–20 giây\n"
                "01   Trang chủ  •  10–20 giây\n"
                "02   Từ khóa nhiệm vụ  •  10–15 giây\n"
                "03   Trong kênh  •  3–5 phút, đổi clip mỗi 15–30 giây"
            ),
            justify="left",
            anchor="w",
            font=label_font,
            text_color=text,
        )
        self.lbl_tt_timeline.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(
            self.tiktok_scroll,
            text="3. Thiết bị chạy • Bỏ trống để chọn tất cả",
            font=label_font,
            text_color=text,
        ).pack(padx=16, pady=(0, 3), anchor="w")
        self.ent_tt_selection = ctk.CTkEntry(
            self.tiktok_scroll,
            placeholder_text="Ví dụ: 1-5,10",
            height=42,
            **field_style,
        )
        self.ent_tt_selection.pack(fill="x", padx=16, pady=(0, 8))

        self.tt_combined_card = ctk.CTkFrame(
            self.tiktok_scroll,
            fg_color="#faf5ff",
            corner_radius=13,
            border_width=1,
            border_color="#e9d5ff",
        )
        self.tt_combined_card.pack(fill="x", padx=16, pady=(1, 9))
        self.switch_tt_combined = ctk.CTkSwitch(
            self.tt_combined_card,
            text="Chạy đủ TikTok + Facebook (thứ tự ngẫu nhiên)",
            variable=self.tiktok_combined_var,
            onvalue=True,
            offvalue=False,
            font=label_font,
            text_color=text,
            fg_color=violet,
            progress_color=violet,
            button_color="#ffffff",
            button_hover_color="#f8fafc",
        )
        self.switch_tt_combined.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self.tt_combined_card,
            text="Bật để lệnh chạy này thực hiện đủ cả hai mô-đun",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=muted,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 9))

        self.tt_btn_grid = ctk.CTkFrame(self.tiktok_scroll, fg_color="transparent")
        self.tt_btn_grid.pack(fill="x", padx=16, pady=(0, 7))
        self.tt_btn_grid.columnconfigure(0, weight=1)
        self.tt_btn_grid.columnconfigure(1, weight=1)
        self.tt_btn_grid.columnconfigure(2, weight=1)

        self.btn_tt_seq = ctk.CTkButton(
            self.tt_btn_grid,
            text="Tuần tự từng máy",
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
            text="Song song nhiều máy",
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
            text="Tự điều phối",
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
            text="Dừng toàn bộ tác vụ đang chạy",
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
            self.facebook_tab,
            **scroll_style,
        )
        self.facebook_scroll.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

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
            text="Nuôi Feed, làm mới Home an toàn và tìm đúng Page mục tiêu",
            font=body_font,
            text_color=muted,
        ).pack(anchor="w")

        ctk.CTkLabel(
            self.facebook_scroll,
            text="1. Từ khóa mồi • Phân cách bằng dấu phẩy",
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
            text="2. Page target • Mỗi cụm cách nhau dấu phẩy",
            font=label_font,
            text_color=text,
        ).pack(padx=16, pady=(0, 3), anchor="w")
        self.ent_fb_target = ctk.CTkEntry(
            self.facebook_scroll,
            placeholder_text="Tên thương hiệu hoặc cụm tên Page mục tiêu",
            height=42,
            **field_style,
        )
        self.ent_fb_target.insert(
            0, config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT or ""
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
                "00   Nuôi TikTok video  •  10–20 giây\n"
                "01   Home Facebook  •  Nuôi Feed 10–20 giây\n"
                "     Làm mới an toàn: Back → mở lại app (chỉ tại Home)\n"
                "02   Từ khóa mồi  •  10–15 giây\n"
                "03   Đúng Page target  •  3–5 phút"
            ),
            justify="left",
            anchor="w",
            font=label_font,
            text_color=text,
        ).pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(
            self.facebook_scroll,
            text="3. Thiết bị chạy • Bỏ trống để chọn tất cả",
            font=label_font,
            text_color=text,
        ).pack(padx=16, pady=(0, 3), anchor="w")
        self.ent_fb_selection = ctk.CTkEntry(
            self.facebook_scroll,
            placeholder_text="Ví dụ: 1-5,10",
            height=42,
            **field_style,
        )
        self.ent_fb_selection.pack(fill="x", padx=16, pady=(0, 8))

        self.fb_combined_card = ctk.CTkFrame(
            self.facebook_scroll,
            fg_color="#f5f3ff",
            corner_radius=13,
            border_width=1,
            border_color="#ddd6fe",
        )
        self.fb_combined_card.pack(fill="x", padx=16, pady=(1, 9))
        self.switch_fb_combined = ctk.CTkSwitch(
            self.fb_combined_card,
            text="Chạy đủ Facebook + TikTok (thứ tự ngẫu nhiên)",
            variable=self.facebook_combined_var,
            onvalue=True,
            offvalue=False,
            font=label_font,
            text_color=text,
            fg_color=violet,
            progress_color=violet,
            button_color="#ffffff",
            button_hover_color="#f8fafc",
        )
        self.switch_fb_combined.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self.fb_combined_card,
            text="Bật để lệnh chạy này thực hiện đủ cả hai mô-đun",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=muted,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 9))

        # Các card công tắc cũ vẫn được khởi tạo để giữ tương thích cấu hình,
        # nhưng được ẩn khỏi UI; người dùng chỉ thao tác công tắc chung phía trên.
        for name_parts in (("tt", "_combined_card"), ("fb", "_combined_card")):
            legacy_card = getattr(self, "".join(name_parts), None)
            if legacy_card is not None:
                legacy_card.pack_forget()

        self.fb_btn_grid = ctk.CTkFrame(
            self.facebook_scroll, fg_color="transparent"
        )
        self.fb_btn_grid.pack(fill="x", padx=16, pady=(0, 7))
        self.fb_btn_grid.columnconfigure(0, weight=1)
        self.fb_btn_grid.columnconfigure(1, weight=1)
        self.fb_btn_grid.columnconfigure(2, weight=1)
        self.btn_fb_seq = ctk.CTkButton(
            self.fb_btn_grid,
            text="Tuần tự từng máy",
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
            text="Song song nhiều máy",
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
            text="Tự điều phối",
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
            text="Dừng toàn bộ tác vụ đang chạy",
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

        self.btn_import_env = ctk.CTkButton(
            self.settings_header,
            text="Import .env",
            font=button_font,
            fg_color="#0f766e",
            hover_color="#115e59",
            text_color="#ffffff",
            corner_radius=10,
            height=34,
            width=108,
            cursor="hand2",
            command=self.import_env_action,
        )
        self.btn_import_env.pack(side="right", padx=(8, 8))

        self._settings_expanded = False
        self.btn_toggle_settings = ctk.CTkButton(
            self.settings_header,
            text="Mở cấu hình",
            font=button_font,
            fg_color="#eff6ff",
            hover_color="#dbeafe",
            text_color=blue,
            border_width=1,
            border_color="#bfdbfe",
            corner_radius=10,
            height=34,
            width=116,
            cursor="hand2",
            command=self.toggle_settings_panel,
        )
        self.btn_toggle_settings.pack(side="right", padx=(8, 0))

        self.settings_card = ctk.CTkFrame(
            self.bottom_panel, fg_color="transparent"
        )
        self.settings_card.pack(fill="x", padx=14, pady=(2, 12))
        for column, weight in enumerate((2, 1, 3, 2, 0)):
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
            2, "ĐƯỜNG DẪN ADB", "Đường dẫn adb.exe", columnspan=2
        )
        self.ent_adb.insert(0, config.ADB_PATH or "")

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
        self.btn_save.grid(row=0, column=4, padx=(6, 4), pady=(19, 0))

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
            columnspan=2,
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
            row=1, column=4, sticky="ew", padx=8, pady=(23, 0)
        )

        # Progressive disclosure: configuration is available from the fixed
        # footer but no longer consumes a large part of the operations canvas.
        self.settings_card.pack_forget()

        # V2 commercial shell: rebuild the information architecture around a
        # fixed command rail, focused workspace and persistent activity panel.
        # Existing entries/buttons/callbacks stay intact; only their visual
        # composition and presentation are changed.
        self._apply_commercial_layout()

        # Subtle glass border response and a short window fade-in. These are
        # presentation-only effects and do not touch automation state.
        self._bind_glass_hover(self.top_header, "#1e293b", "#334155")
        self._bind_glass_hover(self.log_card, border, border_hover)
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
        self.after_idle(self._finish_module_ui_setup)

        # Quét thiết bị khi vừa khởi động
        self.refresh_devices_action()
        # Thiết bị Box Phone có thể kết nối muộn hoặc tự bật lại cảm biến xoay.
        # Kiểm tra định kỳ để các app social luôn giữ hướng dọc.
        self.after(15000, self._portrait_guard_tick)
        # Khởi chạy bot Telegram ở luồng phụ
        self.start_bot_service()
        # Khởi chạy luồng đếm giờ tự động theo khung giờ vàng
        self._start_auto_scheduler()

    def _apply_commercial_layout(self):
        """Compose the commercial operations shell without touching workflows."""
        navy = "#0B1220"
        navy_2 = "#111C31"
        canvas = "#F4F7FB"
        card = "#FFFFFF"
        border = "#DDE5EF"
        text = "#0F172A"
        muted = "#64748B"
        blue = "#1667D9"
        blue_hover = "#0F55BA"
        soft_blue = "#EAF2FF"
        green = "#087A55"
        red = "#C62F3D"

        self.configure(fg_color=canvas)
        self.grid_columnconfigure(0, weight=0, minsize=258)
        self.grid_columnconfigure(1, weight=3, minsize=620)
        self.grid_columnconfigure(2, weight=1, minsize=330)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)

        for widget in (
            self.top_header,
            self.log_card,
            self.ops_frame,
            self.bottom_panel,
        ):
            widget.grid_forget()

        # Fixed command rail.
        self.top_header.configure(
            fg_color=navy,
            corner_radius=0,
            border_width=0,
            width=258,
        )
        self.top_header.grid(
            row=0,
            column=0,
            rowspan=3,
            sticky="nsew",
        )
        self.top_header.grid_propagate(False)
        self.brand_badge.pack_forget()
        self.brand_badge.configure(fg_color="transparent")
        self.brand_badge.pack(fill="both", expand=True, padx=18, pady=20)

        for child in self.brand_badge.winfo_children():
            child.pack_forget()

        self.brand_icon.configure(
            text="BP",
            width=46,
            height=46,
            corner_radius=13,
            fg_color=blue,
            text_color="#FFFFFF",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        )
        self.brand_icon.pack(anchor="w", pady=(0, 10))
        self.brand_copy.pack(fill="x", pady=(0, 8))
        self.lbl_brand.configure(
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#FFFFFF",
        )
        self.lbl_sub_brand.configure(
            text="Social operations console\nĐiều hành đa thiết bị",
            text_color="#91A4C2",
            justify="left",
        )

        if "sidebar_rule_top" not in self.__dict__:
            self.sidebar_rule_top = ctk.CTkFrame(
                self.brand_badge, height=1, fg_color="#24324A"
            )
            self.sidebar_nav_label = ctk.CTkLabel(
                self.brand_badge,
                text="KHÔNG GIAN LÀM VIỆC",
                anchor="w",
                text_color="#7186A6",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            )
            nav_style = {
                "height": 42,
                "corner_radius": 10,
                "anchor": "w",
                "font": ctk.CTkFont(
                    family="Segoe UI", size=12, weight="bold"
                ),
                "text_color": "#C8D4E6",
                "fg_color": "transparent",
                "hover_color": "#1A2942",
                "cursor": "hand2",
            }
            self.btn_nav_overview = ctk.CTkButton(
                self.brand_badge,
                text="Tổng quan vận hành",
                command=self._show_operations_overview,
                **nav_style,
            )
            self.btn_nav_tiktok = ctk.CTkButton(
                self.brand_badge,
                text="TikTok Automation",
                command=lambda: self._navigate_module("TikTok"),
                **nav_style,
            )
            self.btn_nav_facebook = ctk.CTkButton(
                self.brand_badge,
                text="Facebook Automation",
                command=lambda: self._navigate_module("Facebook"),
                **nav_style,
            )
            self.btn_nav_activity = ctk.CTkButton(
                self.brand_badge,
                text="Nhật ký hệ thống",
                command=self._open_activity_workspace,
                **nav_style,
            )
            self.sidebar_rule_middle = ctk.CTkFrame(
                self.brand_badge, height=1, fg_color="#24324A"
            )
            self.sidebar_tools_label = ctk.CTkLabel(
                self.brand_badge,
                text="CÔNG CỤ NHANH",
                anchor="w",
                text_color="#7186A6",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            )
            self.sidebar_footer = ctk.CTkLabel(
                self.brand_badge,
                text="BOXPHONE CONTROL  •  DESKTOP",
                anchor="w",
                text_color="#607392",
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            )

        self.sidebar_rule_top.pack(fill="x", pady=(10, 14))
        self.sidebar_nav_label.pack(fill="x", pady=(0, 7))
        for nav_button in (
            self.btn_nav_overview,
            self.btn_nav_tiktok,
            self.btn_nav_facebook,
            self.btn_nav_activity,
        ):
            nav_button.pack(fill="x", pady=2)

        self.sidebar_rule_middle.pack(fill="x", pady=(16, 14))
        self.sidebar_tools_label.pack(fill="x", pady=(0, 8))
        self.device_status_badge.configure(
            height=34,
            corner_radius=9,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
        )
        self.device_status_badge.pack(fill="x", pady=(0, 8))
        self.platform_badge.configure(
            text="2 MODULE SOCIAL",
            height=30,
            corner_radius=9,
            fg_color=navy_2,
            text_color="#9CB0CF",
        )
        self.platform_badge.pack(fill="x", pady=(0, 10))

        sidebar_buttons = (
            (self.btn_refresh, "Quét thiết bị", blue, blue_hover),
            (self.btn_mute_all, "Tắt âm toàn bộ", "#6447C7", "#5136AD"),
            (self.btn_scan_notion, "Đồng bộ từ Notion", "#0B7B72", "#08645E"),
            (self.btn_complete_notion, "Hoàn thành lịch tuần", "#475569", "#334155"),
        )
        for button, label, color, hover in sidebar_buttons:
            button.configure(
                text=label,
                width=0,
                height=42,
                corner_radius=10,
                fg_color=color,
                hover_color=hover,
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            )
            button.pack(fill="x", pady=3)

        self.btn_telegram_notifications.configure(
            width=0,
            height=40,
            corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
        )
        self.btn_telegram_notifications.pack(fill="x", pady=(12, 4))
        self.sidebar_footer.pack(side="bottom", fill="x", pady=(14, 0))

        # New command header for the main work area.
        self.main_header = ctk.CTkFrame(
            self,
            fg_color=card,
            corner_radius=16,
            border_width=1,
            border_color=border,
        )
        self.main_header.grid(
            row=0,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=18,
            pady=(16, 10),
        )
        self.main_header.columnconfigure(0, weight=1)
        header_copy = ctk.CTkFrame(self.main_header, fg_color="transparent")
        header_copy.grid(row=0, column=0, sticky="w", padx=18, pady=13)
        ctk.CTkLabel(
            header_copy,
            text="Trung tâm vận hành",
            anchor="w",
            text_color=text,
            font=ctk.CTkFont(family="Segoe UI", size=21, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            header_copy,
            text="Thiết lập chiến dịch, điều phối thiết bị và theo dõi tiến trình tại một nơi",
            anchor="w",
            text_color=muted,
            font=ctk.CTkFont(family="Segoe UI", size=11),
        ).pack(anchor="w", pady=(2, 0))

        header_meta = ctk.CTkFrame(self.main_header, fg_color="transparent")
        header_meta.grid(row=0, column=1, sticky="e", padx=(8, 10), pady=10)
        for label, fg, color in (
            ("2 MODULE", soft_blue, blue),
            ("ADB READY", "#ECFDF5", green),
            ("LOCAL SECURE", "#F1F5F9", "#475569"),
        ):
            ctk.CTkLabel(
                header_meta,
                text=label,
                height=30,
                corner_radius=9,
                fg_color=fg,
                text_color=color,
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            ).pack(side="left", padx=3)
        self.btn_header_stop = ctk.CTkButton(
            header_meta,
            text="Dừng khẩn cấp",
            width=130,
            height=38,
            corner_radius=10,
            fg_color="#FFF1F2",
            hover_color="#FFE4E6",
            text_color=red,
            border_width=1,
            border_color="#FECDD3",
            cursor="hand2",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self.stop_all,
        )
        self.btn_header_stop.pack(side="left", padx=(8, 0))

        # Main workspace on the left, realtime operations stream on the right.
        self.ops_frame.configure(fg_color="transparent")
        self.ops_frame.grid(
            row=1,
            column=1,
            sticky="nsew",
            padx=(18, 10),
            pady=0,
        )
        self.log_card.configure(
            fg_color=card,
            corner_radius=16,
            border_width=1,
            border_color=border,
        )
        self.log_card.grid(
            row=1,
            column=2,
            sticky="nsew",
            padx=(0, 18),
            pady=0,
        )
        self.log_box.configure(height=420, corner_radius=11)
        self.log_box.pack_configure(fill="both", expand=True, padx=14, pady=(0, 14))
        self.lbl_log.configure(text="Nhật ký trực tiếp")
        self.lbl_log_hint.configure(
            text="",
            width=0,
        )
        self.live_badge.configure(text="LIVE")
        self.btn_toggle_log.configure(text="Toàn màn hình")

        self.workspace_header.configure(fg_color="transparent")
        self.social_combined_panel.configure(
            fg_color="#F4F0FF",
            border_color="#DDD2FF",
            corner_radius=15,
        )
        self.social_combined_mark.configure(
            text="FT",
            fg_color="#FFFFFF",
            text_color="#6D42C7",
        )
        self.module_tabs.configure(
            segmented_button_fg_color="#E9EEF5",
            segmented_button_selected_color=blue,
            segmented_button_selected_hover_color=blue_hover,
            segmented_button_unselected_color="#E9EEF5",
            segmented_button_unselected_hover_color="#DCE4EE",
            text_color=text,
        )
        self.tiktok_scroll.configure(
            fg_color=card,
            border_color=border,
            corner_radius=16,
        )
        self.facebook_scroll.configure(
            fg_color=card,
            border_color=border,
            corner_radius=16,
        )
        # The commercial shell exposes one persistent emergency stop in the
        # command header. Remove duplicate module-level stop buttons so every
        # primary field and execution mode remains visible without scrolling.
        self.btn_tt_stop.pack_forget()
        self.btn_fb_stop.pack_forget()

        self.bottom_panel.configure(
            fg_color=card,
            corner_radius=16,
            border_width=1,
            border_color=border,
        )
        self.bottom_panel.grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=18,
            pady=(10, 16),
        )
        self.lbl_settings.configure(text="Cấu hình hệ thống")
        self.lbl_settings_hint.configure(
            text="Thông tin kết nối được mã hóa khi hiển thị và lưu cục bộ"
        )
        self._sync_navigation_state("overview")

    def _sync_navigation_state(self, active=None):
        """Update sidebar selection without changing any automation state."""
        if "btn_nav_overview" not in self.__dict__:
            return
        if active is None:
            active = self.module_tabs.get().casefold()
        mapping = {
            "overview": self.btn_nav_overview,
            "tiktok": self.btn_nav_tiktok,
            "facebook": self.btn_nav_facebook,
            "activity": self.btn_nav_activity,
        }
        for key, button in mapping.items():
            selected = key == active
            button.configure(
                fg_color="#1D4F91" if selected else "transparent",
                text_color="#FFFFFF" if selected else "#C8D4E6",
            )

    def _navigate_module(self, module_name):
        self.module_tabs.set(module_name)
        self._sync_navigation_state(module_name.casefold())
        scroll = {
            "TikTok": self.tiktok_scroll,
            "Facebook": self.facebook_scroll,
        }.get(module_name)
        if scroll is not None:
            self.after_idle(lambda: scroll._parent_canvas.yview_moveto(0))

    def _show_operations_overview(self):
        if self.__dict__.get("_log_expanded", False):
            self.toggle_system_log()
        self._sync_navigation_state("overview")
        self.after_idle(self._reset_operation_scrolls)

    def _open_activity_workspace(self):
        if not self.__dict__.get("_log_expanded", False):
            self.toggle_system_log()
        else:
            self._sync_navigation_state("activity")

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
            # Move focus outside the scroll containers first. Some Tk builds
            # auto-scroll a canvas to reveal the focused Entry after layout.
            self.btn_refresh.focus_set()
            self.update_idletasks()
            self.tiktok_scroll._parent_canvas.yview_moveto(0)
            self.facebook_scroll._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def _finish_module_ui_setup(self):
        """Chọn tab mặc định trước khi bật callback Focus Workspace."""
        try:
            self.module_tabs.set("TikTok")
        finally:
            self._module_focus_ready = True

    def _on_module_tab_changed(self):
        """Bung module được chọn ra toàn bộ vùng làm việc, không cần cuộn trang."""
        if not self.__dict__.get("_module_focus_ready", False):
            return
        self._set_module_focus(True)
        scroll = {
            "TikTok": self.tiktok_scroll,
            "Facebook": self.facebook_scroll,
        }.get(self.module_tabs.get())
        if scroll is not None:
            self.after_idle(lambda widget=scroll: widget._parent_canvas.yview_moveto(0))

    def _set_module_focus(self, enabled):
        # V2 keeps the activity stream and combined launcher visible while a
        # module is selected. Focus is communicated through the sidebar and
        # tab state instead of hiding surrounding context.
        self._module_focus_active = bool(enabled)
        active = self.module_tabs.get().casefold() if enabled else "overview"
        self._sync_navigation_state(active)
        self.btn_restore_overview.pack_forget()
        self.after_idle(self._reset_operation_scrolls)

    def restore_dashboard_overview(self):
        """Return the commercial shell to its full operational overview."""
        self._show_operations_overview()

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

    @staticmethod
    def _replace_entry_value(widget, value):
        widget.delete(0, "end")
        widget.insert(0, value)

    def _apply_notion_schedule(self, schedule):
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
        self._active_notion_schedule = schedule
        self._active_notion_token = token
        self.btn_complete_notion.configure(
            state="normal",
            text=f"Hoàn thành: {schedule.title[:18]}",
            fg_color="#047857",
            hover_color="#065f46",
        )
        period = (
            f"{schedule.start_date:%d/%m/%Y} - "
            f"{schedule.end_date:%d/%m/%Y}"
        )
        self.log_message(
            f"[Notion] Đã nạp lịch '{schedule.title}' ({period}) "
            "vào TikTok và Facebook."
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

    def complete_notion_schedule_action(self):
        schedule = self._active_notion_schedule
        token = self._active_notion_token
        if schedule is None:
            messagebox.showwarning(
                "Chưa chọn lịch",
                "Hãy quét Notion và chọn một lịch trước khi hoàn thành.",
            )
            return
        if not messagebox.askyesno(
            "Xác nhận hoàn thành tuần",
            f"Đánh dấu lịch '{schedule.title}' là Hoàn thành?\n\n"
            "Lịch này sẽ không xuất hiện trong các lần quét tiếp theo.",
        ):
            return

        self.btn_complete_notion.configure(
            state="disabled", text="Đang đồng bộ...", fg_color="#64748b"
        )

        def action():
            try:
                mark_schedule_completed(token, schedule.page_id)

                def finish_success():
                    self._active_notion_schedule = None
                    self._active_notion_token = ""
                    self.btn_complete_notion.configure(
                        state="disabled",
                        text="Hoàn thành tuần",
                        fg_color="#64748b",
                        hover_color="#475569",
                    )
                    self.log_message(
                        f"[Notion] Đã hoàn thành lịch '{schedule.title}'. "
                        "Lịch sẽ được loại khỏi lần quét sau."
                    )
                    messagebox.showinfo(
                        "Đồng bộ hoàn tất",
                        f"Đã chuyển '{schedule.title}' sang Hoàn thành trên Notion.",
                    )

                self.after(0, finish_success)
            except NotionSyncError as exc:
                self.log_message(f"[Notion] Không thể hoàn thành lịch: {exc}")

                def finish_error():
                    self.btn_complete_notion.configure(
                        state="normal",
                        text=f"Hoàn thành: {schedule.title[:18]}",
                        fg_color="#047857",
                        hover_color="#065f46",
                    )
                    messagebox.showwarning("Đồng bộ Notion thất bại", str(exc))

                self.after(0, finish_error)

        self.run_in_thread(action)

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
                for schedule in schedules:
                    if schedule.pump_status != PUMP_STATUS_PROCESSING:
                        mark_schedule_processing(token, schedule.page_id)
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

    @staticmethod
    def _set_entry_value(entry, value):
        entry.delete(0, "end")
        entry.insert(0, value or "")

    def _apply_imported_env(self, values):
        """Nạp các khóa .env đã import vào runtime và các ô cấu hình."""
        get_value = lambda key, fallback="": str(values.get(key) or fallback)

        config.TELEGRAM_BOT_TOKEN = get_value("TELEGRAM_BOT_TOKEN")
        config.TELEGRAM_NOTIFICATIONS_ENABLED = get_value(
            "TELEGRAM_NOTIFICATIONS_ENABLED", "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        admin_ids = get_value("ALLOWED_USER_IDS")
        config.ALLOWED_USER_IDS = [
            int(item.strip())
            for item in admin_ids.split(",")
            if item.strip().isdigit()
        ]
        config.ADB_PATH = get_value(
            "ADB_PATH", r"C:\Program Files (x86)\xiaowei\tools\adb.exe"
        )
        config.NOTION_API_TOKEN = get_value("NOTION_API_TOKEN")
        config.NOTION_DATA_SOURCE_ID = get_value("NOTION_DATA_SOURCE_ID")
        config.TIKTOK_TARGET_CHANNEL_DEFAULT = get_value("TIKTOK_TARGET_CHANNEL")
        config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT = get_value(
            "FACEBOOK_TARGET_PAGE_EXACT"
        )

        main.adb.adb_path = config.ADB_PATH
        main.configure_telegram_bot_token(config.TELEGRAM_BOT_TOKEN)

        field_values = {
            "ent_token": config.TELEGRAM_BOT_TOKEN,
            "ent_admins": admin_ids,
            "ent_adb": config.ADB_PATH,
            "ent_notion_token": config.NOTION_API_TOKEN,
            "ent_notion_source_id": config.NOTION_DATA_SOURCE_ID,
            "ent_tt_channel": config.TIKTOK_TARGET_CHANNEL_DEFAULT,
            "ent_fb_target": config.FACEBOOK_TARGET_PAGE_EXACT_DEFAULT,
        }
        for attribute, value in field_values.items():
            entry = self.__dict__.get(attribute)
            if entry is not None:
                self._set_entry_value(entry, value)

        if self.__dict__.get("btn_telegram_notifications") is not None:
            self._refresh_telegram_notifications_button()

    def _import_env_file(self, source_path):
        """Kiểm tra, sao chép và nạp một file .env mà không in secret ra log."""
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("Không tìm thấy file .env đã chọn.")
        if source.name.lower() != ".env" and source.suffix.lower() != ".env":
            raise ValueError("Vui lòng chọn đúng file .env.")

        values = dict(dotenv_values(source))
        supported_keys = {
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_NOTIFICATIONS_ENABLED",
            "ALLOWED_USER_IDS",
            "ADB_PATH",
            "NOTION_API_TOKEN",
            "NOTION_DATA_SOURCE_ID",
            "TIKTOK_TARGET_CHANNEL",
            "FACEBOOK_TARGET_PAGE_EXACT",
        }
        recognized = supported_keys.intersection(values)
        if not recognized:
            raise ValueError(
                "File .env không có khóa cấu hình nào mà BoxPhoneControl hỗ trợ."
            )

        target = Path(config.ENV_PATH).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if source != target:
            shutil.copy2(source, target)
        load_dotenv(dotenv_path=target, override=True)
        self._apply_imported_env(values)
        return len(recognized), target

    def import_env_action(self):
        source_path = filedialog.askopenfilename(
            parent=self,
            title="Chọn file cấu hình .env",
            filetypes=(("Environment file", "*.env"), ("Tất cả file", "*.*")),
        )
        if not source_path:
            return
        try:
            key_count, target = self._import_env_file(source_path)
        except Exception as exc:
            messagebox.showerror("Import .env thất bại", str(exc))
            return

        self.log_message(
            f"[Cấu hình] Đã import an toàn {key_count} nhóm cấu hình từ .env."
        )
        messagebox.showinfo(
            "Import .env thành công",
            "Đã nạp cấu hình vào BoxPhoneControl và lưu trong hồ sơ Windows.\n"
            "Các giá trị nhạy cảm không được hiển thị trong log.\n\n"
            f"Vị trí lưu: {target}",
        )

    def save_settings(self):
        token = self.ent_token.get().strip()
        admin_ids = self.ent_admins.get().strip()
        adb_path = self.ent_adb.get().strip()
        notion_token = self.ent_notion_token.get().strip()
        notion_source_id = self.ent_notion_source_id.get().strip()
        telegram_token_valid = main.is_valid_telegram_token(token)
        if not telegram_token_valid:
            config.TELEGRAM_NOTIFICATIONS_ENABLED = False

        env_path = config.ENV_PATH
        lines = []
        if env_path.exists():
            with env_path.open("r", encoding="utf-8") as env_file:
                lines = env_file.readlines()

        keys = {
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_NOTIFICATIONS_ENABLED": (
                "1" if config.TELEGRAM_NOTIFICATIONS_ENABLED else "0"
            ),
            "ALLOWED_USER_IDS": admin_ids,
            "ADB_PATH": adb_path,
            "NOTION_API_TOKEN": notion_token,
            "NOTION_DATA_SOURCE_ID": notion_source_id,
        }
        new_lines = []
        updated_keys = set()
        for line in lines:
            stripped = line.strip()
            matched = False
            for key, value in keys.items():
                if stripped.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}\n")
                    updated_keys.add(key)
                    matched = True
                    break
            if not matched:
                new_lines.append(line)

        for key, value in keys.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        with env_path.open("w", encoding="utf-8") as env_file:
            env_file.writelines(new_lines)

        config.TELEGRAM_BOT_TOKEN = token
        config.ALLOWED_USER_IDS = [
            int(item.strip())
            for item in admin_ids.split(",")
            if item.strip().isdigit()
        ]
        config.ADB_PATH = adb_path
        config.NOTION_API_TOKEN = notion_token
        config.NOTION_DATA_SOURCE_ID = notion_source_id
        main.adb.adb_path = adb_path

        main.configure_telegram_bot_token(token)
        if self.__dict__.get("btn_telegram_notifications") is not None:
            self._refresh_telegram_notifications_button()

        print("[Hệ thống] Lưu cấu hình và tải lại thành công!")
        if telegram_token_valid:
            messagebox.showinfo("Thành công", "Đã lưu cấu hình và tự động nạp lại!")
        else:
            messagebox.showwarning(
                "Đã lưu cấu hình",
                "Telegram đang tắt vì token bị trống hoặc không hợp lệ. "
                "Các cấu hình khác vẫn đã được lưu.",
            )

    def _persist_env_setting(self, key, value):
        """Cap nhat mot khoa .env ma khong ghi de cac cau hinh khac."""
        env_path = config.ENV_PATH
        lines = []
        if env_path.exists():
            with env_path.open("r", encoding="utf-8") as env_file:
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

        with env_path.open("w", encoding="utf-8") as env_file:
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
        if enabled and not main.is_valid_telegram_token(
            config.TELEGRAM_BOT_TOKEN
        ):
            config.TELEGRAM_NOTIFICATIONS_ENABLED = False
            self._persist_env_setting("TELEGRAM_NOTIFICATIONS_ENABLED", "0")
            self._refresh_telegram_notifications_button()
            messagebox.showwarning(
                "Chưa thể bật Telegram",
                "Vui lòng nhập token Telegram hợp lệ và bấm Lưu cấu hình.",
            )
            return
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

    def bulk_disable_rotation(
        self,
        target_devices=None,
        sync=False,
        skip_busy=False,
        skip_if_running=False,
    ):
        if target_devices is None:
            target_devices = main.get_ordered_devices()
        target_devices = list(target_devices)
        def action():
            bulk_lock = self.__dict__.get("_bulk_rotation_lock")
            if bulk_lock is None:
                bulk_lock = threading.Lock()
                self._bulk_rotation_lock = bulk_lock
            acquired = bulk_lock.acquire(blocking=not skip_if_running)
            if not acquired:
                return
            def disable_rot(d):
                try:
                    if (
                        skip_busy
                        and main.adb.is_device_workflow_active(d)
                    ):
                        return True
                    with main.adb.device_workflow_scope(d):
                        return main.adb.lock_portrait(d)
                except Exception:
                    return False
            try:
                from concurrent.futures import ThreadPoolExecutor
                if target_devices:
                    worker_count = min(
                        len(target_devices),
                        getattr(main.adb, "max_parallel_commands", 8),
                    )
                    with ThreadPoolExecutor(
                        max_workers=max(1, worker_count)
                    ) as executor:
                        list(executor.map(disable_rot, target_devices))
            finally:
                bulk_lock.release()
        if sync:
            action()
        else:
            self.run_in_thread(action)

    def prepare_social_targets(
        self, target_devices, opening_platform, is_cancelled=None
    ):
        """Chuẩn bị đúng ứng dụng mở đầu cho hàng đợi social."""
        if not target_devices:
            return []

        def prepare_device(device_id):
            if is_cancelled and is_cancelled():
                return device_id, False
            try:
                # Chờ workflow cũ nhả đúng thiết bị rồi mới được đổi ứng dụng.
                with main.adb.device_workflow_scope(device_id):
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
            except Exception as exc:
                print(
                    f"[GUI] Không chuẩn bị được máy "
                    f"{main.get_device_name(device_id)} cho {opening_platform}: "
                    f"{exc}"
                )
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
        """Kiểm tra dọc nhẹ, bỏ qua máy đang chạy workflow."""
        self.bulk_disable_rotation(
            skip_busy=True, skip_if_running=True
        )
        self.after(60000, self._portrait_guard_tick)

    def toggle_system_log(self):
        """Expand the activity panel across the workspace and restore it."""
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self.ops_frame.grid_remove()
            self.log_card.grid(
                row=1,
                column=1,
                columnspan=2,
                sticky="nsew",
                padx=18,
                pady=0,
            )
            expanded_height = max(
                320,
                min(680, int(self.winfo_height() * 0.66)),
            )
            self.log_box.configure(height=expanded_height)
            self.btn_toggle_log.configure(
                text="Trở về workspace",
                fg_color="#dbeafe",
                border_color="#93c5fd",
            )
            self._sync_navigation_state("activity")
        else:
            self.ops_frame.grid(
                row=1,
                column=1,
                sticky="nsew",
                padx=(18, 10),
                pady=0,
            )
            self.log_card.grid(
                row=1,
                column=2,
                columnspan=1,
                sticky="nsew",
                padx=(0, 18),
                pady=0,
            )
            self.log_box.configure(height=420)
            self.btn_toggle_log.configure(
                text="Toàn màn hình",
                fg_color="#eff6ff",
                border_color="#bfdbfe",
            )
            self._sync_navigation_state(self.module_tabs.get().casefold())
        self.after_idle(lambda: self.log_box.see("end"))

    def toggle_settings_panel(self):
        """Đóng/mở panel cấu hình mà không thay đổi giá trị người dùng đã nhập."""
        self._settings_expanded = not self._settings_expanded
        if self._settings_expanded:
            self.settings_card.pack(fill="x", padx=14, pady=(2, 12))
            self.btn_toggle_settings.configure(
                text="Thu gọn",
                fg_color="#dbeafe",
                border_color="#93c5fd",
            )
        else:
            self.settings_card.pack_forget()
            self.btn_toggle_settings.configure(
                text="Mở cấu hình",
                fg_color="#eff6ff",
                border_color="#bfdbfe",
            )
        self.after_idle(self._reset_operation_scrolls)

    def _start_auto_scheduler(self):
        """Khởi chạy luồng đếm giờ tự động theo khung giờ vàng."""
        threading.Thread(target=self._auto_scheduler_loop, daemon=True).start()

    def _auto_scheduler_loop(self):
        """Vòng lặp kiểm tra mốc giờ và tự động kích hoạt chiến dịch."""
        last_triggered_date_hour = None
        while True:
            try:
                time.sleep(10.0)
                if (
                    not hasattr(self, "auto_schedule_var")
                    or not self.auto_schedule_var.get()
                ):
                    if hasattr(self, "lbl_schedule_countdown"):
                        self.after_idle(
                            lambda: self.lbl_schedule_countdown.configure(
                                text="⏰ Lịch: TẮT"
                            )
                        )
                    continue

                hours_raw = (
                    self.ent_schedule_hours.get().strip()
                    if hasattr(self, "ent_schedule_hours")
                    else config.AUTO_SCHEDULE_HOURS_DEFAULT
                )
                scheduled_times = [
                    h.strip() for h in hours_raw.split(",") if ":" in h
                ]
                if not scheduled_times:
                    if hasattr(self, "lbl_schedule_countdown"):
                        self.after_idle(
                            lambda: self.lbl_schedule_countdown.configure(
                                text="⏰ Chưa đặt giờ"
                            )
                        )
                    continue

                now = time.localtime()
                now_str = time.strftime("%H:%M", now)
                today_str = time.strftime("%Y-%m-%d", now)

                # Tính mốc giờ tiếp theo để hiển thị đếm ngược
                current_minutes = now.tm_hour * 60 + now.tm_min
                best_diff = 24 * 60
                next_target = None
                for st in scheduled_times:
                    try:
                        sh, sm = map(int, st.split(":"))
                        target_mins = sh * 60 + sm
                        diff = target_mins - current_minutes
                        if diff <= 0:
                            diff += 24 * 60
                        if diff < best_diff:
                            best_diff = diff
                            next_target = st
                    except Exception:
                        pass

                if next_target and hasattr(self, "lbl_schedule_countdown"):
                    hours_left = best_diff // 60
                    mins_left = best_diff % 60
                    countdown_text = (
                        f"⏰ Đợt tới: {next_target} (còn {hours_left}h {mins_left:02d}m)"
                    )
                    self.after_idle(
                        lambda t=countdown_text: self.lbl_schedule_countdown.configure(
                            text=t
                        )
                    )

                # Kiểm tra kích hoạt đúng phút
                for st in scheduled_times:
                    if st == now_str:
                        trigger_key = f"{today_str}_{st}"
                        if last_triggered_date_hour != trigger_key:
                            last_triggered_date_hour = trigger_key
                            self.log_message(
                                f"⏰ [LÊN LỊCH TỰ ĐỘNG] ĐÃ ĐẾN KHUNG GIỜ VÀNG {st}! "
                                "Hệ thống đang tự động kích hoạt toàn bộ 40 máy..."
                            )
                            chat_id = (
                                config.ALLOWED_USER_IDS[0]
                                if config.ALLOWED_USER_IDS
                                else None
                            )
                            if chat_id:
                                try:
                                    main.bot.send_message(
                                        chat_id,
                                        f"⏰ [BoxPhoneControl] ĐÃ ĐẾN KHUNG GIỜ VÀNG {st}!\n"
                                        "Tự động kích hoạt toàn bộ máy chạy chiến dịch Social...",
                                    )
                                except Exception:
                                    pass

                            self.after_idle(self.run_combined_social_adaptive)
            except Exception:
                time.sleep(5.0)

    @staticmethod
    def _random_social_order():
        order = ["tiktok", "facebook"]
        random.shuffle(order)
        return order

    def _social_combined_enabled(self, source_module=None):
        """Trả trạng thái kết hợp riêng của module đã phát lệnh chạy."""
        common_variable = self.__dict__.get("social_combined_var")
        if common_variable is not None:
            return bool(common_variable.get())
        variable_name = {
            "tiktok": "tiktok_combined_var",
            "facebook": "facebook_combined_var",
        }.get(source_module)
        if variable_name is None:
            return False
        variable = self.__dict__.get(variable_name)
        return bool(variable and variable.get())

    def _log_social_adaptive_wave(
        self, label, devices, wave_number, total_devices
    ):
        device_names = ", ".join(
            main.get_device_name(device_id) for device_id in devices
        )
        self.log_message(
            f"[{label} thích ứng] Đợt {wave_number}: chọn ngẫu nhiên "
            f"{len(devices)} máy tại các vị trí {device_names} "
            f"(tổng {total_devices} máy; tất cả sẽ lần lượt được chạy)."
        )

    def run_combined_social_sequential(self):
        """Run both social modules one device at a time."""
        self.run_combined_social(self.ent_social_selection)

    def run_combined_social_parallel(self):
        """Run both social modules on all selected devices concurrently."""
        self.run_combined_social(
            self.ent_social_selection,
            parallel=True,
        )

    def run_combined_social_adaptive(self):
        """Run both social modules with the existing adaptive scheduler."""
        self.run_combined_social(
            self.ent_social_selection,
            adaptive=True,
        )

    def run_combined_social(
        self, entry_widget, parallel=False, adaptive=False
    ):
        """Run both social workflows in a random per-device order."""
        tt_seed = self.ent_tt_seed.get().strip()
        tt_channel = (
            self.ent_tt_channel.get().strip()
            or config.TIKTOK_TARGET_CHANNEL_DEFAULT
        )
        fb_seed = self.ent_fb_seed.get().strip()
        fb_target = self.ent_fb_target.get().strip()
        missing = []
        if not tt_seed:
            missing.append("từ khóa TikTok")
        if not tt_channel:
            missing.append("kênh TikTok")
        if not fb_seed:
            missing.append("từ khóa mồi Facebook")
        if not fb_target:
            missing.append("Page target Facebook")
        if missing:
            messagebox.showwarning(
                "Thiếu dữ liệu chạy kết hợp",
                "Vui lòng nhập: " + ", ".join(missing),
            )
            return

        target_devices = self.parse_targets(entry_widget=entry_widget)
        if not target_devices:
            return
        workflow_session = main.start_workflow_session()
        is_cancelled = main.make_session_cancel_checker(workflow_session)

        def run_device(device_id):
            device_started_at = time.monotonic()
            device_name = main.get_device_name(device_id)
            order = self._random_social_order()
            order_text = " → ".join(
                "TikTok" if item == "tiktok" else "Facebook"
                for item in order
            )
            self.log_message(
                f"[Máy {device_name}] Kết hợp ngẫu nhiên: {order_text}"
            )
            chat_id = (
                config.ALLOWED_USER_IDS[0]
                if config.ALLOWED_USER_IDS
                else None
            )
            tracker = None
            if chat_id:
                try:
                    tracker = main.TelegramRealtimeTracker(main.bot, chat_id)
                    tracker.set_active_device(
                        device_name,
                        device_id,
                        f"Social: {order_text}",
                        1,
                        1,
                        platform="Social",
                    )
                    tracker.start_dashboard(tracker.render_progress_text())
                except Exception:
                    tracker = None

            results = []
            for platform_index, platform in enumerate(order, start=1):
                if is_cancelled():
                    return device_name, False, "Bị dừng bởi người dùng"

                platform_label = (
                    "TIKTOK" if platform == "tiktok" else "FACEBOOK"
                )
                platform_plan = (
                    "nuôi chéo Facebook → TikTok B1-B3"
                    if platform == "tiktok"
                    else (
                        "nuôi chéo TikTok → Facebook B1-B3 "
                        "(từ khóa mồi → Page target)"
                    )
                )
                phase_message = (
                    f"[Kết hợp {platform_index}/2] BẮT ĐẦU MODULE "
                    f"{platform_label} ĐẦY ĐỦ • {platform_plan}."
                )
                self.log_message(f"[Máy {device_name}] {phase_message}")
                if tracker:
                    tracker.status_callback(device_id, phase_message)

                def status_callback(dev, message, current=platform):
                    label = "TikTok" if current == "tiktok" else "Facebook"
                    self.log_message(
                        f"[Máy {device_name}][{label}] {message}"
                    )
                    if tracker:
                        tracker.status_callback(dev, f"[{label}] {message}")

                try:
                    if platform == "tiktok":
                        success, message = main.adb.tiktok_automation_workflow(
                            device_id,
                            seed_keywords=tt_seed,
                            target_channel=tt_channel,
                            status_callback=status_callback,
                            is_cancelled=is_cancelled,
                        )
                    else:
                        success, message = main.adb.facebook_automation_workflow(
                            device_id,
                            seed_keywords=fb_seed,
                            target_pages=fb_target,
                            status_callback=status_callback,
                            is_cancelled=is_cancelled,
                        )
                except Exception as exc:
                    success = False
                    message = f"Lỗi ngoài dự kiến: {exc}"
                results.append((platform, success, message))

                result_message = (
                    f"[Kết hợp {platform_index}/2] "
                    f"{'HOÀN TẤT' if success else 'KẾT THÚC CÓ LỖI'} "
                    f"MODULE {platform_label}: {message}"
                )
                self.log_message(f"[Máy {device_name}] {result_message}")
                if tracker:
                    tracker.status_callback(device_id, result_message)

                if platform_index < len(order):
                    next_platform = (
                        "TIKTOK" if order[platform_index] == "tiktok"
                        else "FACEBOOK"
                    )
                    transition_message = (
                        f"[Kết hợp] CHUYỂN SANG MODULE {next_platform} "
                        "ĐẦY ĐỦ cho cùng máy."
                    )
                    self.log_message(
                        f"[Máy {device_name}] {transition_message}"
                    )
                    if tracker:
                        tracker.status_callback(
                            device_id, transition_message
                        )

            success = len(results) == 2 and all(item[1] for item in results)
            message = "Thành công cả TikTok và Facebook" if success else "; ".join(
                f"{platform}: {detail}"
                for platform, ok, detail in results
                if not ok
            )
            elapsed_seconds = max(0, time.monotonic() - device_started_at)
            elapsed_minutes = int(elapsed_seconds // 60)
            elapsed_remainder = int(elapsed_seconds % 60)
            duration_text = (
                f"{elapsed_minutes} phút {elapsed_remainder} giây"
                if elapsed_minutes
                else f"{elapsed_remainder} giây"
            )
            recents_cleared = False
            if success:
                def cleanup_status(dev, cleanup_message):
                    self.log_message(
                        f"[Máy {device_name}] {cleanup_message}"
                    )
                    if tracker:
                        tracker.status_callback(dev, cleanup_message)

                recents_cleared = main.clear_device_recents_after_success(
                    device_id, status_callback=cleanup_status
                )
            if tracker:
                cleanup_text = (
                    "\n🧹 Đa nhiệm: **Đã xóa**"
                    if recents_cleared
                    else "\n⚠️ Đa nhiệm: **Chưa xóa được**"
                )
                tracker.finish_dashboard(
                    f"{'✅' if success else '❌'} **MÁY {device_name} "
                    f"KẾT HỢP {'HOÀN THÀNH' if success else 'THẤT BẠI'}**\n"
                    f"Thứ tự: `{order_text}`\n`{message}`"
                    f"\n⏱️ Thời gian hoàn thành: **{duration_text}**"
                    f"{cleanup_text}"
                )
            return device_name, success, message

        def action():
            self.bulk_disable_rotation(
                target_devices=target_devices, sync=True
            )
            if adaptive:
                results = run_adaptive(
                    target_devices,
                    run_device,
                    PLATFORM_POLICIES["social"],
                    is_cancelled=is_cancelled,
                    randomize_queue=True,
                    randomize_wave_size=True,
                    on_wave=lambda devices, wave, total: (
                        self._log_social_adaptive_wave(
                            "Social kết hợp", devices, wave, total
                        )
                    ),
                    on_wait=lambda dev, delay, position, total: (
                        self.log_message(
                            f"[Social thích ứng] Máy "
                            f"{main.get_device_name(dev)} chờ {delay}s "
                            f"trước khi bắt đầu ({position + 1}/{total})."
                        )
                    ),
                )
            elif parallel:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(
                    max_workers=len(target_devices)
                ) as executor:
                    results = list(executor.map(run_device, target_devices))
            else:
                results = [run_device(device) for device in target_devices]
            success_count = sum(1 for _, success, _ in results if success)
            print(
                f"[GUI] Social kết hợp: {success_count}/"
                f"{len(target_devices)} máy hoàn thành cả hai mô-đun."
            )

        self.run_in_thread(action)

    # ================= CÁC TÁC VỤ BƠM TIKTOK =================
    def run_seq_tiktok(self):
        if self._social_combined_enabled("tiktok"):
            self.run_combined_social(self.ent_tt_selection)
            return
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )

        print(f"[GUI] Bắt đầu chạy TikTok Tuần Tự trên {len(target_devices)} máy...")

        def action():
            self.bulk_disable_rotation(
                target_devices=target_devices, sync=True
            )
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
                    main.clear_device_recents_after_success(
                        dev, status_callback=tt_status_cb
                    )
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
        if self._social_combined_enabled("tiktok"):
            self.run_combined_social(
                self.ent_tt_selection,
                parallel=not adaptive,
                adaptive=adaptive,
            )
            return
        target_devices = self.parse_targets(entry_widget=self.ent_tt_selection)
        if not target_devices:
            return
        seed_raw = self.ent_tt_seed.get().strip()
        channel = self.ent_tt_channel.get().strip() or config.TIKTOK_TARGET_CHANNEL_DEFAULT

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
            if success:
                main.clear_device_recents_after_success(
                    device_id, status_callback=tt_status_cb
                )
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
            self.bulk_disable_rotation(
                target_devices=target_devices, sync=True
            )
            self.prepare_social_targets(
                target_devices,
                "facebook",
                is_cancelled=session_is_cancelled,
            )
            if adaptive:
                policy = PLATFORM_POLICIES["social"]
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
                    randomize_queue=True,
                    randomize_wave_size=True,
                    on_wave=lambda devices, wave, total: (
                        self._log_social_adaptive_wave(
                            "TikTok", devices, wave, total
                        )
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
        if self._social_combined_enabled("facebook"):
            self.run_combined_social(self.ent_fb_selection)
            return
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

        workflow_session = main.start_workflow_session()
        session_is_cancelled = main.make_session_cancel_checker(
            workflow_session
        )

        def action():
            self.bulk_disable_rotation(
                target_devices=target_devices, sync=True
            )
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
                    main.clear_device_recents_after_success(
                        device_id, status_callback=fb_status_callback
                    )
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
        if self._social_combined_enabled("facebook"):
            self.run_combined_social(
                self.ent_fb_selection,
                parallel=not adaptive,
                adaptive=adaptive,
            )
            return
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
            if success:
                main.clear_device_recents_after_success(
                    device_id, status_callback=fb_status_callback
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
            self.bulk_disable_rotation(
                target_devices=target_devices, sync=True
            )
            self.prepare_social_targets(
                target_devices,
                "tiktok",
                is_cancelled=session_is_cancelled,
            )
            if adaptive:
                policy = PLATFORM_POLICIES["social"]
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
                    randomize_queue=True,
                    randomize_wave_size=True,
                    on_wave=lambda devices, wave, total: (
                        self._log_social_adaptive_wave(
                            "Facebook", devices, wave, total
                        )
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
                        and main.is_valid_telegram_token(
                            config.TELEGRAM_BOT_TOKEN
                        )
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
    """Gom log nền thành từng lô để không làm nghẽn Tk event loop."""

    def __init__(self, text_widget, flush_interval_ms=75, max_lines=6000):
        self.text_widget = text_widget
        self.flush_interval_ms = max(20, int(flush_interval_ms))
        self.max_lines = max(500, int(max_lines))
        self.buffer = ""
        self._pending_lines = deque()
        self._lock = threading.Lock()
        self._rendered_lines = 0
        self._schedule_drain()

    def write(self, string):
        if not string:
            return 0
        text = str(string)
        with self._lock:
            self.buffer += text
            complete = self.buffer.split("\n")
            self.buffer = complete.pop()
            self._pending_lines.extend(line for line in complete if line)
        return len(text)

    def _schedule_drain(self):
        try:
            self.text_widget.after(self.flush_interval_ms, self._drain_pending)
        except Exception:
            pass

    def _drain_pending(self):
        with self._lock:
            if self._pending_lines:
                lines = list(self._pending_lines)
                self._pending_lines.clear()
            else:
                lines = []

        if lines:
            try:
                self.text_widget.configure(state="normal")
                self.text_widget.insert("end", "\n".join(lines) + "\n")
                self._rendered_lines += len(lines)
                overflow = self._rendered_lines - self.max_lines
                if overflow > 0:
                    self.text_widget.delete("1.0", f"{overflow + 1}.0")
                    self._rendered_lines -= overflow
                self.text_widget.see("end")
                self.text_widget.configure(state="disabled")
            except Exception:
                pass
        self._schedule_drain()

    def flush(self):
        with self._lock:
            if self.buffer:
                self._pending_lines.append(self.buffer)
                self.buffer = ""

if __name__ == "__main__":
    app = GUIApp()
    app.mainloop()

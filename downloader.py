import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
import os
import shutil
import threading
import subprocess
import re
import json
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pystray
from PIL import Image, ImageDraw

# Ensure yt-dlp can find the user's local Node.js installation for n-challenge
os.environ['PATH'] += os.pathsep + r"C:\Users\Jonathan\AppData\Local\hermes\node"

DOCS_DIR = os.path.join(os.path.expanduser('~'), 'Documents')
HISTORY_FILE = os.path.join(DOCS_DIR, 'MembersDownloader_History.json')
SETTINGS_FILE = os.path.join(DOCS_DIR, 'MembersDownloader_Settings.json')
ARCHIVE_FILE = os.path.join(DOCS_DIR, 'MembersDownloader_Archive.txt')

def load_settings():
    default_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    default_cookie = os.path.join(os.path.expanduser('~'), 'Downloads', 'cookies.txt')
    default_settings = {
        "theme": "blue",
        "mode": "Dark",
        "download_dir": default_dir,
        "browser": "custom",
        "cookie_file": default_cookie,
        "embed_chapters": True,
        "preserve_mtime": True
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
                default_settings.update(data)
        except:
            pass
    return default_settings

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except:
        pass

current_settings = load_settings()
ctk.set_appearance_mode(current_settings.get("mode", "Dark"))
try:
    ctk.set_default_color_theme(current_settings.get("theme", "blue"))
except:
    pass

def create_tray_image():
    image = Image.new('RGB', (64, 64), color=(30, 30, 30))
    d = ImageDraw.Draw(image)
    d.polygon([(20, 16), (20, 48), (48, 32)], fill=(30, 136, 229))
    return image


class ToastNotification:
    def __init__(self, root, title, message):
        self.top = ctk.CTkToplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        
        screen_width = self.top.winfo_screenwidth()
        screen_height = self.top.winfo_screenheight()
        x = screen_width - 320
        y = screen_height - 120
        self.top.geometry(f"300x80+{x}+{y}")
        
        frame = ctk.CTkFrame(self.top, corner_radius=10, border_width=2, border_color="#1E88E5")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold", size=14)).pack(pady=(10, 2), padx=10, anchor="w")
        ctk.CTkLabel(frame, text=message, font=ctk.CTkFont(size=12)).pack(pady=(0, 10), padx=10, anchor="w")
        
        self.top.after(5000, self.top.destroy)


class QueueItem:
    def __init__(self, url, start_time, end_time, frame, remove_callback, app=None):
        self.url = url
        self.start_time = start_time
        self.end_time = end_time
        self.frame = frame
        self.status = "Pending"
        self.process = None
        self.remove_callback = remove_callback
        self.app = app
        self.current_percent = 0.0
        self.current_speed = ""
        self.current_eta = ""
        self.title = ""
        
        self.lbl_url = ctk.CTkLabel(self.frame, text=url, font=ctk.CTkFont(weight="bold"), anchor="w")
        self.lbl_url.pack(fill=tk.X, padx=5, pady=(5,0))
        
        time_text = ""
        if start_time or end_time:
            time_text = f" [Trim: {start_time or '00:00'} to {end_time or 'End'}]"
            
        self.lbl_status = ctk.CTkLabel(self.frame, text=f"Pending{time_text}", text_color="gray", anchor="w")
        self.lbl_status.pack(fill=tk.X, padx=5)
        
        self.progress = ctk.CTkProgressBar(self.frame, height=8)
        self.progress.set(0)
        self.progress.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.btn_remove = ctk.CTkButton(self.frame, text="X", width=30, height=20, fg_color="#C62828", hover_color="#B71C1C", command=self.on_remove)
        self.btn_remove.place(relx=0.98, rely=0.1, anchor="ne")

    def on_remove(self):
        if self.process:
            try:
                self.process.terminate()
            except:
                pass
        self.frame.destroy()
        self.remove_callback(self)
        if self.app:
            self.app.update_master_progress()

    def update_progress(self, percent, speed, eta):
        self.current_percent = percent
        self.current_speed = speed
        self.current_eta = eta
        self.progress.set(percent)
        self.lbl_status.configure(text=f"Downloading... {percent*100:.1f}% | {speed} | ETA: {eta}", text_color="cyan")
        if self.app:
            self.app.update_master_progress()

    def set_status(self, text, color="white"):
        self.lbl_status.configure(text=text, text_color=color)
        if self.app:
            self.app.update_master_progress()


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Members-Only YouTube Downloader Ultimate V3")
        self.root.geometry("1100x1000")
        self.root.resizable(False, False)
        
        # Override close button to minimize to tray
        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        self.tray_icon = pystray.Icon("Downloader", create_tray_image(), "Members Downloader", menu=pystray.Menu(
            pystray.MenuItem("Restore Window", self.show_window, default=True),
            pystray.MenuItem("Quit Application", self.quit_app)
        ))
        
        self.queue_items = []
        self.history = self.load_json(HISTORY_FILE, [])
        self.is_downloading = False
        self.executor = None
        
        self.monitored_urls = self.load_json(os.path.join(DOCS_DIR, 'MembersDownloader_Monitor.json'), [])
        self.monitoring_thread = None
        self.is_monitoring = False

        # --- Main Container ---
        self.main_container = ctk.CTkFrame(root, corner_radius=15)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        title_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        title_frame.pack(fill=tk.X, pady=(15, 10))
        title_label = ctk.CTkLabel(title_frame, text="Members-Only YouTube Downloader", font=ctk.CTkFont(size=24, weight="bold"))
        title_label.pack()
        subtitle = ctk.CTkLabel(title_frame, text="Closing the window minimizes to System Tray. Use Quit from tray to exit.", font=ctk.CTkFont(size=12), text_color="gray")
        subtitle.pack()

        # --- Save Location Bar (Always Visible) ---
        self.dir_var = ctk.StringVar(value=current_settings.get("download_dir", os.path.join(os.path.expanduser('~'), 'Downloads')))
        dir_bar = ctk.CTkFrame(self.main_container, fg_color="transparent")
        dir_bar.pack(fill=tk.X, padx=20, pady=(0, 10))
        ctk.CTkLabel(dir_bar, text="📁 Save Folder:", font=ctk.CTkFont(weight="bold", size=13)).pack(side=tk.LEFT, padx=(0, 10))
        self.dir_entry_top = ctk.CTkEntry(dir_bar, textvariable=self.dir_var, height=36, font=ctk.CTkFont(size=12))
        self.dir_entry_top.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.lbl_disk_free = ctk.CTkLabel(dir_bar, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_disk_free.pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(dir_bar, text="Browse Folder", width=110, height=36, font=ctk.CTkFont(weight="bold"), command=self.browse_dir).pack(side=tk.RIGHT)

        # --- Top Section: URL & Queue ---
        top_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        top_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        self.url_entry = ctk.CTkEntry(top_frame, placeholder_text="Paste Video or Playlist URL here...", height=45, font=ctk.CTkFont(size=14))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.trim_start = ctk.CTkEntry(top_frame, placeholder_text="Start (01:15)", width=90, height=45)
        self.trim_start.pack(side=tk.LEFT, padx=(0, 5))
        self.trim_end = ctk.CTkEntry(top_frame, placeholder_text="End (03:45)", width=90, height=45)
        self.trim_end.pack(side=tk.LEFT, padx=(0, 10))
        
        btn_add = ctk.CTkButton(top_frame, text="Add to Queue", height=45, font=ctk.CTkFont(weight="bold"), command=self.add_to_queue)
        btn_add.pack(side=tk.RIGHT)
        
        queue_action_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        queue_action_frame.pack(fill=tk.X, padx=20, pady=(0, 5))
        ctk.CTkButton(queue_action_frame, text="Import Queue (.txt)", width=120, command=self.import_queue).pack(side=tk.LEFT, padx=(0, 10))
        ctk.CTkButton(queue_action_frame, text="Export Queue (.txt)", width=120, command=self.export_queue).pack(side=tk.LEFT)
        
        self.queue_filter_var = ctk.StringVar()
        self.queue_filter_var.trace("w", lambda *args: self.filter_queue_items())
        ctk.CTkEntry(queue_action_frame, textvariable=self.queue_filter_var, placeholder_text="🔍 Filter Queue...", width=180).pack(side=tk.RIGHT)

        # --- Master Queue Progress Banner ---
        master_banner = ctk.CTkFrame(self.main_container, fg_color=("gray85", "gray20"), corner_radius=8)
        master_banner.pack(fill=tk.X, padx=20, pady=(4, 6))
        
        banner_top = ctk.CTkFrame(master_banner, fg_color="transparent")
        banner_top.pack(fill=tk.X, padx=10, pady=(5, 2))
        self.lbl_master_title = ctk.CTkLabel(banner_top, text="Queue Progress: 0 / 0 Completed (0%)", font=ctk.CTkFont(weight="bold", size=13))
        self.lbl_master_title.pack(side=tk.LEFT)
        self.lbl_master_stats = ctk.CTkLabel(banner_top, text="Idle", font=ctk.CTkFont(size=12), text_color="cyan")
        self.lbl_master_stats.pack(side=tk.RIGHT)
        
        self.master_progress = ctk.CTkProgressBar(master_banner, height=10)
        self.master_progress.set(0)
        self.master_progress.pack(fill=tk.X, padx=10, pady=(0, 6))

        # --- Queue List ---
        self.queue_frame = ctk.CTkScrollableFrame(self.main_container, height=180, corner_radius=10)
        self.queue_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        # --- Schedule ---
        schedule_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        schedule_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        self.var_schedule = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(schedule_frame, text="Schedule Start (HH:MM, 24hr):", variable=self.var_schedule).pack(side=tk.LEFT)
        self.schedule_entry = ctk.CTkEntry(schedule_frame, placeholder_text="02:00", width=80)
        self.schedule_entry.pack(side=tk.LEFT, padx=10)

        # --- Middle Section: Settings (Tabs) ---
        self.tabview = ctk.CTkTabview(self.main_container, height=380)
        self.tabview.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        tab_general = self.tabview.add("General")
        tab_auth = self.tabview.add("Authentication")
        tab_extras = self.tabview.add("Extras")
        tab_network = self.tabview.add("Network")
        tab_history = self.tabview.add("History")
        tab_monitor = self.tabview.add("Auto-Monitor")
        tab_stats = self.tabview.add("Stats")
        tab_appear = self.tabview.add("Appearance")
        
        self.setup_general_tab(tab_general)
        self.setup_auth_tab(tab_auth)
        self.setup_extras_tab(tab_extras)
        self.setup_network_tab(tab_network)
        self.setup_history_tab(tab_history)
        self.setup_monitor_tab(tab_monitor)
        self.setup_stats_tab(tab_stats)
        self.setup_appearance_tab(tab_appear)

        # --- Bottom Section: Actions ---
        action_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        action_frame.pack(fill=tk.X, padx=20, pady=(10, 15))
        
        self.btn_start = ctk.CTkButton(action_frame, text="▶ Start Downloads", font=ctk.CTkFont(size=15, weight="bold"), height=50, command=self.start_queue)
        self.btn_start.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_cancel = ctk.CTkButton(action_frame, text="⏹ Stop All", font=ctk.CTkFont(size=15, weight="bold"), height=50, fg_color="#C62828", hover_color="#B71C1C", state="disabled", command=self.cancel_downloads)
        self.btn_cancel.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.btn_clear = ctk.CTkButton(action_frame, text="🗑 Clear Done", font=ctk.CTkFont(size=15, weight="bold"), height=50, fg_color="#555555", hover_color="#333333", command=self.clear_completed)
        self.btn_clear.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.btn_clean = ctk.CTkButton(action_frame, text="🧹 Merge & Clean Leftovers", font=ctk.CTkFont(size=15, weight="bold"), height=50, fg_color="#1E88E5", hover_color="#1565C0", command=self.manual_merge_clean)
        self.btn_clean.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        self.update_disk_free_display()

    # --- System Tray ---
    def hide_window(self):
        self.root.withdraw()
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon, item):
        icon.stop()
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon=None, item=None):
        if icon:
            icon.stop()
        self.cancel_downloads()
        self.root.destroy()
        os._exit(0)

    def setup_general_tab(self, tab):
        tab.grid_columnconfigure(1, weight=1)
        
        # Directory
        ctk.CTkLabel(tab, text="Save Folder:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=(15, 0), sticky="w")
        self.dir_entry = ctk.CTkEntry(tab, textvariable=self.dir_var)
        self.dir_entry.grid(row=0, column=1, padx=10, pady=(15, 0), sticky="ew")
        ctk.CTkButton(tab, text="Browse", width=80, command=self.browse_dir).grid(row=0, column=2, padx=10, pady=(15, 0))
        ctk.CTkLabel(tab, text="Where do you want the videos to be saved? (Also shown on the main screen above)", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")
        
        # Folder Org
        ctk.CTkLabel(tab, text="Folder Organization:", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, padx=10, pady=0, sticky="w")
        self.folder_org_var = ctk.StringVar(value="None (All in one folder)")
        ctk.CTkComboBox(
            tab, variable=self.folder_org_var, 
            values=["None (All in one folder)", "By Channel Name", "By Playlist", "By Channel & Playlist"], state="readonly", width=250
        ).grid(row=2, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="Automatically create sub-folders so things don't get messy.", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=3, column=1, padx=10, pady=(0, 10), sticky="w")

        # Quality
        ctk.CTkLabel(tab, text="Video Quality:", font=ctk.CTkFont(weight="bold")).grid(row=4, column=0, padx=10, pady=0, sticky="w")
        self.quality_var = ctk.StringVar(value="Best Available (1080p+)")
        self.quality_combo = ctk.CTkComboBox(
            tab, variable=self.quality_var, 
            values=["Best Available (1080p+)", "1080p", "720p", "480p", "Audio Only"], state="readonly", width=200
        )
        self.quality_combo.grid(row=4, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="Leave on 'Best Available' for 4K/1080p. Pick 'Audio Only' for music.", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=5, column=1, padx=10, pady=(0, 10), sticky="w")
        
        # Audio Format
        ctk.CTkLabel(tab, text="Music Format:", font=ctk.CTkFont(weight="bold")).grid(row=6, column=0, padx=10, pady=0, sticky="w")
        self.audio_var = ctk.StringVar(value="MP3")
        self.audio_combo = ctk.CTkComboBox(
            tab, variable=self.audio_var, 
            values=["MP3", "FLAC", "WAV", "M4A", "Opus"], state="readonly", width=120
        )
        self.audio_combo.grid(row=6, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="Only applies if you select 'Audio Only' above. (FLAC is highest quality)", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=7, column=1, padx=10, pady=(0, 10), sticky="w")

        # Concurrent Downloads
        ctk.CTkLabel(tab, text="Simultaneous Downloads:", font=ctk.CTkFont(weight="bold")).grid(row=8, column=0, padx=10, pady=0, sticky="w")
        self.workers_var = ctk.StringVar(value="1")
        self.workers_combo = ctk.CTkComboBox(
            tab, variable=self.workers_var, values=["1", "2", "3", "4", "5"], state="readonly", width=80
        )
        self.workers_combo.grid(row=8, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="How many videos to download at the exact same time. Use 1 or 2 if your internet is slow.", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=9, column=1, padx=10, pady=(0, 10), sticky="w")
        
        # Rate Limit
        ctk.CTkLabel(tab, text="Speed Limit:", font=ctk.CTkFont(weight="bold")).grid(row=10, column=0, padx=10, pady=0, sticky="w")
        self.rate_var = ctk.StringVar(value="")
        self.rate_entry = ctk.CTkEntry(tab, textvariable=self.rate_var, placeholder_text="e.g., 5M, 500K", width=120)
        self.rate_entry.grid(row=10, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="Type '2M' to limit speed to 2 Megabytes per second. Leave blank for unlimited.", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=11, column=1, padx=10, pady=(0, 10), sticky="w")
        
        # Filename Template
        ctk.CTkLabel(tab, text="Filename Template:", font=ctk.CTkFont(weight="bold")).grid(row=12, column=0, padx=10, pady=0, sticky="w")
        self.tmpl_var = ctk.StringVar(value="%(title)s.%(ext)s")
        self.tmpl_entry = ctk.CTkEntry(tab, textvariable=self.tmpl_var, width=250)
        self.tmpl_entry.grid(row=12, column=1, padx=10, pady=0, sticky="w")
        ctk.CTkLabel(tab, text="Advanced: e.g. %(uploader)s - %(title)s.%(ext)s", text_color="gray", font=ctk.CTkFont(size=11)).grid(row=13, column=1, padx=10, pady=(0, 10), sticky="w")

    def setup_auth_tab(self, tab):
        ctk.CTkLabel(tab, text="Login Method:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        ctk.CTkLabel(tab, text="To download Members-Only videos, the app needs to borrow your browser cookies so YouTube knows you are a paid member.", text_color="gray", font=ctk.CTkFont(size=11), wraplength=900, justify="left").pack(anchor="w", padx=10, pady=(0, 5))
        
        def on_browser_change():
            val = self.browser_var.get()
            current_settings["browser"] = val
            save_settings(current_settings)
            if val == "custom":
                self.cookie_entry.configure(state='normal')
            else:
                self.cookie_entry.configure(state='disabled')

        saved_browser = current_settings.get("browser", "custom")
        saved_cookie = current_settings.get("cookie_file", os.path.join(os.path.expanduser('~'), 'Downloads', 'cookies.txt'))

        self.browser_var = ctk.StringVar(value=saved_browser)
        radio_frame = ctk.CTkFrame(tab, fg_color="transparent")
        radio_frame.pack(fill=tk.X, padx=10, pady=5)
        browsers = [("Brave", "brave"), ("Chrome", "chrome"), ("Edge", "edge"), ("Firefox", "firefox"), ("None", "none"), ("Custom cookies.txt", "custom")]
        for i, (text, val) in enumerate(browsers):
            ctk.CTkRadioButton(radio_frame, text=text, variable=self.browser_var, value=val, command=on_browser_change).grid(row=i//3, column=i%3, padx=20, pady=10, sticky="w")
            
        cookie_frame = ctk.CTkFrame(tab, fg_color="transparent")
        cookie_frame.pack(fill=tk.X, padx=10, pady=10)
        self.cookie_var = ctk.StringVar(value=saved_cookie)
        self.cookie_entry = ctk.CTkEntry(cookie_frame, textvariable=self.cookie_var, placeholder_text="Path to cookies.txt (Only needed if you selected Custom)...")
        if saved_browser != "custom":
            self.cookie_entry.configure(state='disabled')
        self.cookie_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ctk.CTkButton(cookie_frame, text="Browse", width=80, command=self.browse_cookie).pack(side=tk.RIGHT)

        # Authentication Verification Tool
        test_card = ctk.CTkFrame(tab, corner_radius=10)
        test_card.pack(fill=tk.X, padx=10, pady=(15, 5))
        
        test_inner = ctk.CTkFrame(test_card, fg_color="transparent")
        test_inner.pack(fill=tk.X, padx=15, pady=12)
        
        self.btn_test_auth = ctk.CTkButton(
            test_inner, text="⚡ Verify Authentication", font=ctk.CTkFont(weight="bold", size=13),
            height=38, width=180, fg_color="#0288D1", hover_color="#0277BD", command=self.test_authentication
        )
        self.btn_test_auth.pack(side=tk.LEFT, padx=(0, 15))
        
        self.lbl_auth_status = ctk.CTkLabel(
            test_inner, text="Click to verify whether YouTube accepts your current cookie settings.",
            text_color="gray", font=ctk.CTkFont(size=12), anchor="w"
        )
        self.lbl_auth_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tip_lbl = ctk.CTkLabel(
            tab, text="💡 Tip: If using Chrome/Edge/Brave directly, make sure the browser is fully closed before testing or downloading so its cookie database isn't locked.",
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=900, justify="left"
        )
        tip_lbl.pack(anchor="w", padx=15, pady=(5, 5))

    def setup_extras_tab(self, tab):
        tab.grid_columnconfigure((0, 1), weight=1)
        self.var_subs = ctk.BooleanVar(value=False)
        self.var_meta = ctk.BooleanVar(value=False)
        self.var_sponsor = ctk.BooleanVar(value=False)
        self.var_force_mp4 = ctk.BooleanVar(value=False)
        self.var_notify = ctk.BooleanVar(value=True)
        self.var_normalize = ctk.BooleanVar(value=False)
        
        # Row 0
        f0 = ctk.CTkFrame(tab, fg_color="transparent")
        f0.grid(row=0, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f0, text="Download Subtitles", variable=self.var_subs).pack(anchor="w")
        ctk.CTkLabel(f0, text="Embeds English subtitles into the video file.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)
        
        f1 = ctk.CTkFrame(tab, fg_color="transparent")
        f1.grid(row=0, column=1, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f1, text="Embed Thumbnail & Metadata", variable=self.var_meta).pack(anchor="w")
        ctk.CTkLabel(f1, text="Embeds the thumbnail as the file cover picture (no extra files).", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)
        
        # Row 1
        f2 = ctk.CTkFrame(tab, fg_color="transparent")
        f2.grid(row=1, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f2, text="SponsorBlock (Remove sponsors)", variable=self.var_sponsor).pack(anchor="w")
        ctk.CTkLabel(f2, text="Automatically cuts out in-video sponsored ads.", text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, justify="left").pack(anchor="w", padx=45)
        
        f3 = ctk.CTkFrame(tab, fg_color="transparent")
        f3.grid(row=1, column=1, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f3, text="Force MP4 Format", variable=self.var_force_mp4).pack(anchor="w")
        ctk.CTkLabel(f3, text="Merges directly into clean MP4 (no leftover .webm files).", text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, justify="left").pack(anchor="w", padx=45)
        
        # Row 2
        f4 = ctk.CTkFrame(tab, fg_color="transparent")
        f4.grid(row=2, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f4, text="Show Notification on Success", variable=self.var_notify).pack(anchor="w")
        ctk.CTkLabel(f4, text="Pops up a small message on your screen when finished.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)
        
        f5 = ctk.CTkFrame(tab, fg_color="transparent")
        f5.grid(row=2, column=1, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f5, text="Normalize Audio Volume", variable=self.var_normalize).pack(anchor="w")
        ctk.CTkLabel(f5, text="Makes quiet videos louder and loud videos quieter.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)

        # Row 3
        self.var_clipboard = ctk.BooleanVar(value=False)
        f6 = ctk.CTkFrame(tab, fg_color="transparent")
        f6.grid(row=3, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f6, text="Monitor Clipboard", variable=self.var_clipboard, command=self.toggle_clipboard_monitor).pack(anchor="w")
        ctk.CTkLabel(f6, text="Auto-adds YouTube links you copy to the queue.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)
        
        self.var_members_only = ctk.BooleanVar(value=False)
        f7 = ctk.CTkFrame(tab, fg_color="transparent")
        f7.grid(row=3, column=1, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f7, text="Members-Only Filter", variable=self.var_members_only).pack(anchor="w")
        ctk.CTkLabel(f7, text="If you paste a channel URL, it will skip public videos.", text_color="gray", font=ctk.CTkFont(size=11), wraplength=400, justify="left").pack(anchor="w", padx=45)
        
        # Row 4: Archival Polish
        self.var_chapters = ctk.BooleanVar(value=current_settings.get("embed_chapters", True))
        f8 = ctk.CTkFrame(tab, fg_color="transparent")
        f8.grid(row=4, column=0, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f8, text="Embed Video Chapters", variable=self.var_chapters, command=self._save_archival_settings).pack(anchor="w")
        ctk.CTkLabel(f8, text="Embeds chapter markers directly into video files.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)

        self.var_mtime = ctk.BooleanVar(value=current_settings.get("preserve_mtime", True))
        f9 = ctk.CTkFrame(tab, fg_color="transparent")
        f9.grid(row=4, column=1, padx=20, pady=10, sticky="w")
        ctk.CTkSwitch(f9, text="Preserve Upload Date", variable=self.var_mtime, command=self._save_archival_settings).pack(anchor="w")
        ctk.CTkLabel(f9, text="Matches file modified date to YouTube video upload date.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=45)

        # Playlist controls
        pl_frame = ctk.CTkFrame(tab, fg_color="transparent")
        pl_frame.grid(row=5, column=0, columnspan=2, sticky="w", padx=20, pady=10)
        ctk.CTkLabel(pl_frame, text="Playlist Start:", font=ctk.CTkFont(weight="bold")).pack(side=tk.LEFT)
        self.pl_start_entry = ctk.CTkEntry(pl_frame, placeholder_text="1", width=60)
        self.pl_start_entry.pack(side=tk.LEFT, padx=10)
        ctk.CTkLabel(pl_frame, text="Playlist End:", font=ctk.CTkFont(weight="bold")).pack(side=tk.LEFT, padx=(10, 0))
        self.pl_end_entry = ctk.CTkEntry(pl_frame, placeholder_text="10", width=60)
        self.pl_end_entry.pack(side=tk.LEFT, padx=10)
        ctk.CTkLabel(pl_frame, text="(Leave blank to download the entire playlist)", text_color="gray", font=ctk.CTkFont(size=11)).pack(side=tk.LEFT, padx=10)

        # Update yt-dlp
        update_frame = ctk.CTkFrame(tab, fg_color="transparent")
        update_frame.grid(row=6, column=0, columnspan=2, sticky="w", padx=20, pady=10)
        ctk.CTkButton(update_frame, text="Update yt-dlp", command=self.update_ytdlp).pack(side=tk.LEFT)
        ctk.CTkLabel(update_frame, text="Click occasionally to ensure YouTube hasn't blocked downloads.", text_color="gray", font=ctk.CTkFont(size=11)).pack(side=tk.LEFT, padx=10)

    def _save_archival_settings(self):
        current_settings["embed_chapters"] = self.var_chapters.get()
        current_settings["preserve_mtime"] = self.var_mtime.get()
        save_settings(current_settings)

    def setup_network_tab(self, tab):
        ctk.CTkLabel(tab, text="Proxy Server (VPN Bypass):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        ctk.CTkLabel(tab, text="Useful for bypassing geo-blocked videos. Supports HTTP/HTTPS/SOCKS5.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10, pady=(0, 10))
        
        self.proxy_var = ctk.StringVar(value="")
        self.proxy_entry = ctk.CTkEntry(tab, textvariable=self.proxy_var, placeholder_text="e.g. socks5://127.0.0.1:1080", width=300)
        self.proxy_entry.pack(anchor="w", padx=10, pady=5)
        ctk.CTkLabel(tab, text="Leave blank to use direct connection.", text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10)

    def setup_history_tab(self, tab):
        search_f = ctk.CTkFrame(tab, fg_color="transparent")
        search_f.pack(fill=tk.X, padx=10, pady=(10, 0))
        self.history_search_var = ctk.StringVar()
        self.history_search_var.trace("w", lambda *args: self.refresh_history_ui())
        ctk.CTkEntry(search_f, placeholder_text="Search history...", textvariable=self.history_search_var).pack(fill=tk.X, expand=True)

        self.history_frame = ctk.CTkScrollableFrame(tab)
        self.history_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.refresh_history_ui()
        
    def setup_monitor_tab(self, tab):
        ctk.CTkLabel(tab, text="Automatically checks a channel or playlist for new videos and downloads them in the background.", text_color="gray", font=ctk.CTkFont(size=11), wraplength=900, justify="left").pack(anchor="w", padx=10, pady=(10, 0))
        top_f = ctk.CTkFrame(tab, fg_color="transparent")
        top_f.pack(fill=tk.X, padx=10, pady=10)
        self.mon_url_entry = ctk.CTkEntry(top_f, placeholder_text="Channel/Playlist URL to monitor...")
        self.mon_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ctk.CTkButton(top_f, text="Add", width=60, command=self.add_monitor_url).pack(side=tk.LEFT)
        
        self.monitor_list_frame = ctk.CTkScrollableFrame(tab, height=100)
        self.monitor_list_frame.pack(fill=tk.X, padx=10, pady=5)
        self.refresh_monitor_ui()
        
        bot_f = ctk.CTkFrame(tab, fg_color="transparent")
        bot_f.pack(fill=tk.X, padx=10, pady=5)
        ctk.CTkLabel(bot_f, text="Check Interval (minutes):").pack(side=tk.LEFT)
        self.mon_interval = ctk.StringVar(value="15")
        ctk.CTkComboBox(bot_f, variable=self.mon_interval, values=["15", "30", "60", "120", "360", "720"], width=80).pack(side=tk.LEFT, padx=10)
        
        self.btn_monitor = ctk.CTkButton(bot_f, text="Start Background Monitor", fg_color="#388E3C", hover_color="#2E7D32", command=self.toggle_monitor)
        self.btn_monitor.pack(side=tk.RIGHT)
        self.lbl_monitor_status = ctk.CTkLabel(tab, text="Monitor is OFF", text_color="gray")
        self.lbl_monitor_status.pack(pady=5)

    def setup_stats_tab(self, tab):
        self.stats_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.stats_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        self.refresh_stats_ui()

    def refresh_stats_ui(self):
        for widget in self.stats_frame.winfo_children():
            widget.destroy()
            
        total = len(self.history)
        success = sum(1 for item in self.history if item['status'] == 'Success')
        failed = total - success
        rate = (success / total * 100) if total > 0 else 0
        
        ctk.CTkLabel(self.stats_frame, text="Lifetime Analytics", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(0, 20))
        
        ctk.CTkLabel(self.stats_frame, text=f"Total Downloads Attempted: {total}", font=ctk.CTkFont(size=14)).pack(anchor="w", pady=5)
        ctk.CTkLabel(self.stats_frame, text=f"Successful Downloads: {success}", text_color="lightgreen", font=ctk.CTkFont(size=14)).pack(anchor="w", pady=5)
        ctk.CTkLabel(self.stats_frame, text=f"Failed Downloads: {failed}", text_color="red", font=ctk.CTkFont(size=14)).pack(anchor="w", pady=5)
        ctk.CTkLabel(self.stats_frame, text=f"Overall Success Rate: {rate:.1f}%", font=ctk.CTkFont(size=14)).pack(anchor="w", pady=5)

    def setup_appearance_tab(self, tab):
        ctk.CTkLabel(tab, text="Appearance Mode:", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 5))
        self.mode_var = ctk.StringVar(value=current_settings.get("mode", "Dark"))
        mode_cb = ctk.CTkComboBox(tab, variable=self.mode_var, values=["Dark", "Light", "System"], command=self.change_mode)
        mode_cb.pack(pady=5)
        
        ctk.CTkLabel(tab, text="Color Theme (Requires restart):", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 5))
        self.theme_var = ctk.StringVar(value=current_settings.get("theme", "blue"))
        theme_cb = ctk.CTkComboBox(tab, variable=self.theme_var, values=["blue", "green", "dark-blue"], command=self.change_theme)
        theme_cb.pack(pady=5)
        
    def change_mode(self, mode):
        ctk.set_appearance_mode(mode)
        current_settings["mode"] = mode
        save_settings(current_settings)
        
    def change_theme(self, theme):
        current_settings["theme"] = theme
        save_settings(current_settings)
        messagebox.showinfo("Theme Changed", "The color theme will fully apply the next time you start the app.")

    def load_json(self, filepath, default):
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    return json.load(f)
            except:
                pass
        return default

    def save_json(self, filepath, data):
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
        except:
            pass

    def browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get())
        if d:
            self.dir_var.set(d)
            current_settings["download_dir"] = d
            save_settings(current_settings)
            self.update_disk_free_display()

    def update_disk_free_display(self):
        d = self.dir_var.get()
        try:
            if os.path.exists(d):
                usage = shutil.disk_usage(d)
                free_gb = usage.free / (1024**3)
                drive_letter = os.path.splitdrive(os.path.abspath(d))[0]
                color = "#4CAF50" if free_gb > 10 else ("#FF9800" if free_gb > 3 else "#F44336")
                self.lbl_disk_free.configure(text=f"💾 {drive_letter} {free_gb:.1f} GB Free", text_color=color)
            else:
                self.lbl_disk_free.configure(text="💾 Folder missing", text_color="#F44336")
        except:
            self.lbl_disk_free.configure(text="", text_color="gray")

    def browse_cookie(self):
        f = filedialog.askopenfilename(title="Select cookies.txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self.cookie_var.set(f)
            self.cookie_entry.configure(state="normal")
            self.cookie_entry.delete(0, tk.END)
            self.cookie_entry.insert(0, f)
            self.browser_var.set("custom")
            current_settings["cookie_file"] = f
            current_settings["browser"] = "custom"
            save_settings(current_settings)

    def test_authentication(self):
        self.btn_test_auth.configure(state="disabled", text="⏳ Probing...")
        self.lbl_auth_status.configure(text="Testing authentication against YouTube...", text_color="#0288D1")
        threading.Thread(target=self._run_auth_test, daemon=True).start()

    def _run_auth_test(self):
        config = self.get_config_sync()
        browser = config["browser"]
        cookie = config["cookie"]
        cmd = ['yt-dlp', '--dump-json', '--playlist-items', '1', '--no-download', '--newline']
        
        if browser == "custom":
            if not os.path.exists(cookie):
                self.root.after(0, lambda: self.lbl_auth_status.configure(text="❌ Error: cookies.txt file not found at specified path!", text_color="#F44336"))
                self.root.after(0, lambda: self.btn_test_auth.configure(state="normal", text="⚡ Verify Authentication"))
                return
            cmd.extend(['--cookies', cookie])
        elif browser != "none":
            cmd.extend(['--cookies-from-browser', browser])
        else:
            self.root.after(0, lambda: self.lbl_auth_status.configure(text="⚠️ Login method is 'None'. Members-only videos require cookies.", text_color="#FF9800"))
            self.root.after(0, lambda: self.btn_test_auth.configure(state="normal", text="⚡ Verify Authentication"))
            return

        cmd.extend(['--extractor-args', 'youtube:player_client=mweb,web,tv', '--js-runtimes', 'node'])
        cmd.append("https://www.youtube.com/feed/subscriptions")
        
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, errors='replace', creationflags=0x08000000)
            out = proc.stdout + proc.stderr
            if proc.returncode == 0 and len(proc.stdout.strip()) > 0:
                msg = "✅ Active & Verified! Connected to YouTube as an authenticated user."
                color = "#4CAF50"
            elif "Join this channel" in out or "Sign in to confirm" in out or "cookies are no longer valid" in out:
                msg = "❌ Expired / Invalid! YouTube rejected session. Please refresh your cookies."
                color = "#F44336"
            elif "Could not copy Chrome cookie" in out or "Permission denied" in out:
                msg = "⚠️ Browser cookie database is locked! Please close your browser and try again."
                color = "#FF9800"
            elif proc.returncode == 0:
                msg = "✅ Connection established. Cookies accepted without errors."
                color = "#4CAF50"
            else:
                first_err = [line for line in out.splitlines() if "ERROR:" in line]
                err_txt = first_err[0] if first_err else out[-100:]
                msg = f"⚠️ Probe result: {err_txt[:75]}"
                color = "#FF9800"
        except Exception as e:
            msg = f"❌ Test error: {str(e)}"
            color = "#F44336"

        self.root.after(0, lambda: self.lbl_auth_status.configure(text=msg, text_color=color))
        self.root.after(0, lambda: self.btn_test_auth.configure(state="normal", text="⚡ Verify Authentication"))

    def filter_queue_items(self):
        q = self.queue_filter_var.get().strip().lower()
        for item in self.queue_items:
            matches = not q or q in item.url.lower() or q in item.title.lower() or q in item.status.lower()
            if matches:
                item.frame.pack(fill=tk.X, pady=5)
            else:
                item.frame.pack_forget()

    def update_master_progress(self):
        total = len(self.queue_items)
        if total == 0:
            self.master_progress.set(0)
            self.lbl_master_title.configure(text="Queue Progress: 0 / 0 Completed (0%)")
            self.lbl_master_stats.configure(text="Idle")
            return
            
        completed = sum(1 for i in self.queue_items if i.status == "Success")
        failed = sum(1 for i in self.queue_items if i.status in ["Failed", "Error"])
        downloading = [i for i in self.queue_items if i.status == "Downloading"]
        
        in_prog_sum = sum(i.current_percent for i in downloading)
        fraction = (completed + in_prog_sum) / total
        fraction = max(0.0, min(1.0, fraction))
        self.master_progress.set(fraction)
        
        pct_str = f"{fraction * 100:.1f}%"
        status_txt = f"Queue Progress: {completed} / {total} Done ({pct_str})"
        if failed > 0:
            status_txt += f" • {failed} Failed"
        self.lbl_master_title.configure(text=status_txt)
        
        active_speeds = [i.current_speed for i in downloading if i.current_speed]
        active_etas = [i.current_eta for i in downloading if i.current_eta]
        if active_speeds:
            self.lbl_master_stats.configure(text=f"Speed: {active_speeds[0]} | ETA: {active_etas[0] if active_etas else '--'}")
        elif completed == total and total > 0:
            self.lbl_master_stats.configure(text="All Completed!")
        else:
            self.lbl_master_stats.configure(text="Active" if self.is_downloading else "Idle")

    def add_to_queue(self):
        url = self.url_entry.get().strip()
        start = self.trim_start.get().strip()
        end = self.trim_end.get().strip()
        if not url:
            return

        # Smart convert channel URLs to direct members-only playlist
        if "@midwestsafety" in url.lower():
            url = "https://www.youtube.com/playlist?list=UUMOazRf1jcMNZEL1MS5i_rWQQ"
        elif "youtube.com/channel/UC" in url:
            url = re.sub(r'youtube\.com/channel/UC([a-zA-Z0-9_\-]+).*', r'youtube.com/playlist?list=UUMO\1', url)

        self._add_to_queue_internal(url, start, end)
        self.url_entry.delete(0, tk.END)
        self.trim_start.delete(0, tk.END)
        self.trim_end.delete(0, tk.END)
        
    def _add_to_queue_internal(self, url, start, end):
        f = ctk.CTkFrame(self.queue_frame)
        f.pack(fill=tk.X, pady=5)
        item = QueueItem(url, start, end, f, self.remove_from_queue, app=self)
        self.queue_items.append(item)
        self.update_master_progress()
        
    def remove_from_queue(self, item):
        if item in self.queue_items:
            self.queue_items.remove(item)
        self.update_master_progress()

    def clear_completed(self):
        to_remove = [item for item in self.queue_items if item.status in ["Success", "Failed", "Canceled"]]
        for item in to_remove:
            item.frame.destroy()
            self.queue_items.remove(item)
        self.update_master_progress()

    # --- Monitor Logic ---
    def add_monitor_url(self):
        url = self.mon_url_entry.get().strip()
        if url and url not in self.monitored_urls:
            self.monitored_urls.append(url)
            self.save_json(os.path.join(DOCS_DIR, 'MembersDownloader_Monitor.json'), self.monitored_urls)
            self.mon_url_entry.delete(0, tk.END)
            self.refresh_monitor_ui()
            
    def remove_monitor_url(self, url):
        if url in self.monitored_urls:
            self.monitored_urls.remove(url)
            self.save_json(os.path.join(DOCS_DIR, 'MembersDownloader_Monitor.json'), self.monitored_urls)
            self.refresh_monitor_ui()
            
    def refresh_monitor_ui(self):
        for widget in self.monitor_list_frame.winfo_children():
            widget.destroy()
        if not self.monitored_urls:
            ctk.CTkLabel(self.monitor_list_frame, text="No channels monitored.", text_color="gray").pack(pady=5)
            return
        for url in self.monitored_urls:
            f = ctk.CTkFrame(self.monitor_list_frame, fg_color="transparent")
            f.pack(fill=tk.X, pady=2)
            ctk.CTkLabel(f, text=url, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            ctk.CTkButton(f, text="X", width=30, height=20, fg_color="#C62828", hover_color="#B71C1C", command=lambda u=url: self.remove_monitor_url(u)).pack(side=tk.RIGHT)

    def toggle_monitor(self):
        if not self.is_monitoring:
            if not self.monitored_urls:
                messagebox.showinfo("Monitor", "Add at least one channel/playlist to monitor.")
                return
            self.is_monitoring = True
            self.btn_monitor.configure(text="Stop Background Monitor", fg_color="#C62828", hover_color="#B71C1C")
            self.lbl_monitor_status.configure(text="Monitor is RUNNING", text_color="lightgreen")
            threading.Thread(target=self.monitor_loop, daemon=True).start()
        else:
            self.is_monitoring = False
            self.btn_monitor.configure(text="Start Background Monitor", fg_color="#388E3C", hover_color="#2E7D32")
            self.lbl_monitor_status.configure(text="Monitor is OFF", text_color="gray")

    def toggle_clipboard_monitor(self):
        if self.var_clipboard.get():
            self.last_clipboard = ""
            self.check_clipboard()

    def check_clipboard(self):
        if not self.var_clipboard.get():
            return
            
        try:
            content = self.root.clipboard_get()
            if content != self.last_clipboard:
                self.last_clipboard = content
                if "youtube.com/" in content or "youtu.be/" in content:
                    existing = [i.url for i in self.queue_items]
                    if content not in existing:
                        self.url_entry.delete(0, tk.END)
                        self.url_entry.insert(0, content)
                        self.add_to_queue()
                        if self.var_notify.get():
                            ToastNotification(self.root, "Clipboard Monitor", "Added copied link to queue.")
        except Exception:
            pass
            
        self.root.after(1000, self.check_clipboard)

    def monitor_loop(self):
        while self.is_monitoring:
            self.root.after(0, lambda: self.lbl_monitor_status.configure(text=f"Monitor: Checking for new videos... ({datetime.now().strftime('%H:%M:%S')})"))
            for url in self.monitored_urls:
                if not self.is_monitoring: break
                self.run_silent_archive_download(url)
            if not self.is_monitoring: break
            sleep_mins = int(self.mon_interval.get())
            self.root.after(0, lambda: self.lbl_monitor_status.configure(text=f"Monitor: Sleeping for {sleep_mins} mins..."))
            for _ in range(sleep_mins * 60):
                if not self.is_monitoring: break
                time.sleep(1)

    def run_silent_archive_download(self, url):
        config = self.get_config_sync()
        
        browser = config["browser"]
        quality = config["quality"]
        org = config["org"]
        
        tmpl = config["tmpl"]
        if not tmpl.strip():
            tmpl = "%(title)s.%(ext)s"
            
        if org == "By Channel Name":
            out_tmpl = os.path.join(config["dir"], '%(uploader)s', tmpl)
        elif org == "By Playlist":
            out_tmpl = os.path.join(config["dir"], '%(playlist)s', tmpl)
        elif org == "By Channel & Playlist":
            out_tmpl = os.path.join(config["dir"], '%(uploader)s', '%(playlist)s', tmpl)
        else:
            out_tmpl = os.path.join(config["dir"], tmpl)
        
        cmd = ['yt-dlp', '--download-archive', ARCHIVE_FILE]
        cmd.extend(['--sleep-requests', '1.5', '--sleep-interval', '3', '--max-sleep-interval', '6'])
        if browser == "custom":
            working_cookie = os.path.join(DOCS_DIR, 'working_cookies.txt')
            try:
                if os.path.exists(config["cookie"]):
                    shutil.copyfile(config["cookie"], working_cookie)
                    cmd.extend(['--cookies', working_cookie])
                else:
                    cmd.extend(['--cookies', config["cookie"]])
            except:
                cmd.extend(['--cookies', config["cookie"]])
        elif browser != "none":
            cmd.extend(['--cookies-from-browser', browser])
            
        cmd.extend(['--extractor-args', 'youtube:player_client=mweb,web,tv', '--js-runtimes', 'node'])
        
        rate = config["rate"].strip()
        if rate:
            cmd.extend(['--limit-rate', rate])
            
        if config.get("members_only"):
            cmd.extend(['--match-filters', "availability == subscriber_only"])
            
        force_mp4 = config["force_mp4"]
        if quality == "1080p":
            cmd.extend(['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'])
        elif quality == "720p":
            cmd.extend(['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'])
        elif quality == "480p":
            cmd.extend(['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'])
        elif quality == "Audio Only":
            cmd.extend(['-f', 'bestaudio/best', '--extract-audio', '--audio-format', config["audio"].lower()])
        else:
            cmd.extend(['-f', 'bestvideo+bestaudio/best'])
            
        if force_mp4 and quality != "Audio Only":
            cmd.extend(['--merge-output-format', 'mp4', '--remux-video', 'mp4'])
        elif quality != "Audio Only":
            cmd.extend(['--merge-output-format', 'mkv', '--remux-video', 'mkv'])
            
        if config.get("meta"):
            cmd.extend(['--embed-thumbnail', '--embed-metadata', '--convert-thumbnails', 'jpg'])
        if config.get("chapters", True):
            cmd.append('--embed-chapters')
        if config.get("mtime", True):
            cmd.append('--mtime')
            
        cmd.extend(['-o', out_tmpl, url])
        try:
            res = subprocess.run(cmd, creationflags=0x08000000, capture_output=True, text=True, errors='replace')
            merged = self.auto_merge_and_cleanup(config["dir"])
            downloaded_new = ("[download] Destination:" in res.stdout or "[download] 100%" in res.stdout) and "has already been recorded" not in res.stdout
            if downloaded_new or merged > 0:
                if self.var_notify.get():
                    self.root.after(0, lambda: ToastNotification(self.root, "Auto-Monitor: New Video!", f"Downloaded and archived new video from:\n{url}"))
        except: pass

    # --- Core Downloading ---
    def import_queue(self):
        f = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv")])
        if f:
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    for line in file:
                        url = line.strip()
                        if url.startswith("http"):
                            self._add_to_queue_internal(url, "", "")
                ToastNotification(self.root, "Import Successful", "Queue items added from file.")
            except Exception as e:
                messagebox.showerror("Import Error", str(e))

    def export_queue(self):
        if not self.queue_items:
            messagebox.showinfo("Export", "Queue is empty.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if f:
            try:
                with open(f, 'w', encoding='utf-8') as file:
                    for item in self.queue_items:
                        file.write(f"{item.url}\n")
                ToastNotification(self.root, "Export Successful", "Queue saved to file.")
            except Exception as e:
                messagebox.showerror("Export Error", str(e))

    def start_downloads(self):
        if not self.queue_items:
            messagebox.showinfo("Queue Empty", "Add some videos to the queue first!")
            return
            
        if self.var_schedule.get():
            try:
                target_time = datetime.strptime(self.schedule_entry.get().strip(), "%H:%M").time()
                now = datetime.now()
                target_dt = datetime.combine(now.date(), target_time)
                if target_dt < now:
                    target_dt += timedelta(days=1)
                wait_secs = (target_dt - now).total_seconds()
                
                for item in self.queue_items:
                    item.set_status(f"Scheduled for {target_time.strftime('%H:%M')}", "yellow")
                
                threading.Thread(target=self._wait_and_start, args=(wait_secs,), daemon=True).start()
                return
            except ValueError:
                messagebox.showerror("Invalid Time", "Please use HH:MM (24hr) format for scheduling.")
                return

        self._execute_downloads()

    def _wait_and_start(self, wait_secs):
        time.sleep(wait_secs)
        self.root.after(0, self._execute_downloads)

    def _execute_downloads(self):
        self.is_downloading = True
        workers = int(self.workers_var.get())
        
        self.executor = ThreadPoolExecutor(max_workers=workers)
        for item in self.queue_items:
            if item.status in ["Pending", "Failed", "Error"]:
                self.executor.submit(self.download_worker, item)
        threading.Thread(target=self.monitor_executor, daemon=True).start()

    def update_ytdlp(self):
        try:
            subprocess.Popen(['yt-dlp', '-U'], creationflags=0x08000000)
            ToastNotification(self.root, "Updating yt-dlp", "Update started in the background. It may take a minute.")
        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to start update: {e}")

    def cancel_downloads(self):
        self.is_downloading = False
        for item in self.queue_items:
            if item.process:
                try: item.process.terminate()
                except: pass
                item.set_status("Canceled", "red")
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        self.reset_ui()

    def reset_ui(self):
        self.btn_start.configure(state="normal", text="▶ Start Downloads")
        self.btn_cancel.configure(state="disabled")

    def start_queue(self):
        pending = [item for item in self.queue_items if item.status in ["Pending", "Failed"]]
        if not pending:
            messagebox.showinfo("Queue", "No pending downloads in the queue.")
            return

        # Pre-flight Disk Space Check
        download_dir = self.dir_var.get()
        try:
            if not os.path.exists(download_dir):
                os.makedirs(download_dir, exist_ok=True)
            self.update_disk_free_display()
            free_gb = shutil.disk_usage(download_dir).free / (1024**3)
            if free_gb < 2.0:
                proceed = messagebox.askyesno(
                    "Low Disk Space Warning",
                    f"The selected drive only has {free_gb:.2f} GB of free space left!\n\n"
                    f"Downloading multiple high-quality videos may fill the drive and cause errors.\n\n"
                    f"Do you want to continue anyway?"
                )
                if not proceed:
                    return
        except Exception:
            pass
            
        if self.var_schedule.get():
            time_str = self.schedule_entry.get().strip()
            try:
                datetime.strptime(time_str, "%H:%M")
            except:
                messagebox.showerror("Error", "Invalid schedule time. Use HH:MM format (e.g., 02:00, 14:30)")
                return
            
            self.btn_start.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
            self.is_downloading = True
            threading.Thread(target=self.wait_for_schedule, args=(time_str,), daemon=True).start()
            return
            
        self.execute_start_queue(pending)

    def wait_for_schedule(self, time_str):
        while self.is_downloading:
            now = datetime.now()
            current_hm = now.strftime("%H:%M")
            if current_hm == time_str:
                pending = [item for item in self.queue_items if item.status in ["Pending", "Failed"]]
                self.root.after(0, self.execute_start_queue, pending)
                break
            
            self.root.after(0, lambda: self.btn_start.configure(text=f"Waiting for {time_str}..."))
            time.sleep(10)

    def execute_start_queue(self, pending):
        self.is_downloading = True
        self.root.after(0, lambda: self.btn_start.configure(text="▶ Start Downloads", state="disabled"))
        self.root.after(0, lambda: self.btn_cancel.configure(state="normal"))
        workers = int(self.workers_var.get())
        self.executor = ThreadPoolExecutor(max_workers=workers)
        for item in pending:
            self.executor.submit(self.download_worker, item)
        threading.Thread(target=self.monitor_executor, daemon=True).start()

    def manual_merge_clean(self):
        download_dir = self.dir_var.get()
        if not os.path.exists(download_dir):
            messagebox.showerror("Error", f"Folder does not exist:\n{download_dir}")
            return
        self.btn_clean.configure(state="disabled", text="⏳ Merging...")
        threading.Thread(target=self._run_manual_clean_thread, args=(download_dir,), daemon=True).start()

    def _run_manual_clean_thread(self, download_dir):
        merged = self.auto_merge_and_cleanup(download_dir)
        self.root.after(0, lambda: self.btn_clean.configure(state="normal", text="🧹 Merge & Clean Leftovers"))
        self.root.after(0, lambda: messagebox.showinfo("Merge & Clean Complete", f"Processed {merged} videos in:\n{download_dir}"))

    def auto_merge_and_cleanup(self, download_dir):
        """Scans download_dir for any unmerged stream pairs (.f*.mp4 + .f*.webm)
        and automatically merges them with embedded thumbnail cover art using FFmpeg,
        then cleans up temporary fragments and orphan thumbnails/audio."""
        if not os.path.exists(download_dir):
            return 0
        merged_count = 0
        try:
            # 1. Merge any unmerged video/audio stream pairs
            v_files = [f for f in os.listdir(download_dir) if re.search(r'\.f\d+\.mp4$', f)]
            for v_name in v_files:
                v_path = os.path.join(download_dir, v_name)
                title = re.sub(r'\.f\d+\.mp4$', '', v_name)
                out_mp4 = os.path.join(download_dir, f"{title}.mp4")
                thumb_jpg = os.path.join(download_dir, f"{title}.jpg")
                
                audio_candidates = [f for f in os.listdir(download_dir) if f.startswith(title) and re.search(r'\.f\d+\.webm$', f)]
                if not audio_candidates:
                    continue
                a_path = os.path.join(download_dir, audio_candidates[0])
                
                if os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 1024 * 1024:
                    try: os.remove(v_path)
                    except: pass
                    try: os.remove(a_path)
                    except: pass
                    if os.path.exists(thumb_jpg):
                        try: os.remove(thumb_jpg)
                        except: pass
                    continue
                
                try:
                    orig_mtime = os.path.getmtime(v_path)
                except:
                    orig_mtime = None

                cmd = ['ffmpeg', '-y', '-i', v_path, '-i', a_path]
                if os.path.exists(thumb_jpg):
                    cmd.extend(['-i', thumb_jpg, '-map', '0:v', '-map', '1:a', '-map', '2', '-c', 'copy', '-disposition:v:1', 'attached_pic'])
                else:
                    cmd.extend(['-map', '0:v', '-map', '1:a', '-c', 'copy'])
                cmd.extend(['-map_metadata', '0'])
                cmd.append(out_mp4)
                
                res = subprocess.run(cmd, capture_output=True, creationflags=0x08000000)
                if res.returncode == 0 and os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 1024 * 1024:
                    # Integrity Verification via ffprobe
                    is_valid = True
                    try:
                        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', out_mp4]
                        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True, creationflags=0x08000000)
                        dur = float(probe_res.stdout.strip())
                        if dur <= 0:
                            is_valid = False
                    except:
                        is_valid = True

                    if is_valid:
                        merged_count += 1
                        if orig_mtime:
                            try:
                                os.utime(out_mp4, (orig_mtime, orig_mtime))
                            except:
                                pass
                        try: os.remove(v_path)
                        except: pass
                        try: os.remove(a_path)
                        except: pass
                        if os.path.exists(thumb_jpg):
                            try: os.remove(thumb_jpg)
                            except: pass

            # 2. Second pass: remove any leftover loose fragments (.jpg, .webp, .webm, .part) for completed mp4s
            all_files = os.listdir(download_dir)
            mp4_titles = {
                f[:-4]: os.path.getsize(os.path.join(download_dir, f))
                for f in all_files
                if f.endswith('.mp4') and not re.search(r'\.f\d+\.mp4$', f)
            }
            for f in all_files:
                for title, size in mp4_titles.items():
                    if size > 1024 * 1024 and f.startswith(title) and f != f"{title}.mp4":
                        if re.search(r'\.f\d+\.(webm|mp4)$', f) or f.endswith(('.jpg', '.webp', '.webm', '.part', '.ytdl')):
                            try:
                                os.remove(os.path.join(download_dir, f))
                            except:
                                pass
            self.root.after(0, self.update_disk_free_display)
            return merged_count
        except Exception:
            self.root.after(0, self.update_disk_free_display)
            return merged_count

    def monitor_executor(self):
        if self.executor:
            self.executor.shutdown(wait=True)
        if self.is_downloading:
            merged = self.auto_merge_and_cleanup(self.dir_var.get())
            self.root.after(0, self.reset_ui)
            if self.var_notify.get():
                msg = "All downloads have finished processing!"
                if merged > 0:
                    msg += f"\nAuto-merged {merged} videos."
                self.root.after(0, lambda m=msg: ToastNotification(self.root, "Queue Complete", m))
            self.is_downloading = False

    def save_history(self, url, status):
        entry = {
            "url": url,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "folder": self.dir_var.get()
        }
        self.history.insert(0, entry)
        if len(self.history) > 100:
            self.history = self.history[:100]
        self.save_json(HISTORY_FILE, self.history)
        self.root.after(0, self.refresh_history_ui)
        self.root.after(0, self.refresh_stats_ui)

    def refresh_history_ui(self):
        for widget in self.history_frame.winfo_children():
            widget.destroy()
            
        search_query = self.history_search_var.get().lower()
        filtered_history = [item for item in self.history if search_query in item['url'].lower() or search_query in item['status'].lower() or search_query in item['date'].lower()]
        
        if not filtered_history:
            ctk.CTkLabel(self.history_frame, text="No downloads found.", text_color="gray").pack(pady=10)
            return
            
        for item in filtered_history:
            f = ctk.CTkFrame(self.history_frame, fg_color="transparent")
            f.pack(fill=tk.X, pady=2)
            c = "lightgreen" if item['status'] == "Success" else "red"
            ctk.CTkLabel(f, text=f"[{item['date']}] {item['status']}", text_color=c, width=150, anchor="w").pack(side=tk.LEFT)
            ctk.CTkLabel(f, text=item['url'], anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
            if item['status'] != "Success":
                ctk.CTkButton(f, text="Retry", width=50, height=20, command=lambda u=item['url']: self.retry_history_item(u)).pack(side=tk.RIGHT)
            elif 'folder' in item:
                ctk.CTkButton(f, text="Open Folder", width=80, height=20, command=lambda d=item['folder']: self.open_history_folder(d)).pack(side=tk.RIGHT)

    def open_history_folder(self, folder):
        try:
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def retry_history_item(self, url):
        self.url_entry.delete(0, tk.END)
        self.url_entry.insert(0, url)
        self._add_to_queue_internal(url, "", "")
        self.tabview.set("General")

    def get_current_config(self):
        return {
            "browser": self.browser_var.get(),
            "quality": self.quality_var.get(),
            "org": self.folder_org_var.get(),
            "tmpl": self.tmpl_var.get(),
            "dir": self.dir_var.get(),
            "cookie": self.cookie_var.get(),
            "rate": self.rate_var.get(),
            "audio": self.audio_var.get(),
            "force_mp4": self.var_force_mp4.get(),
            "proxy": self.proxy_var.get(),
            "normalize": self.var_normalize.get(),
            "subs": self.var_subs.get(),
            "meta": self.var_meta.get(),
            "sponsor": self.var_sponsor.get(),
            "pl_start": self.pl_start_entry.get(),
            "pl_end": self.pl_end_entry.get(),
            "notify": self.var_notify.get(),
            "members_only": self.var_members_only.get(),
            "chapters": self.var_chapters.get(),
            "mtime": self.var_mtime.get()
        }

    def get_config_sync(self):
        config = []
        event = threading.Event()
        def fetch():
            config.append(self.get_current_config())
            event.set()
        self.root.after(0, fetch)
        event.wait()
        return config[0]

    def download_worker(self, item):
        if not self.is_downloading:
            return
            
        item.status = "Downloading"
        self.root.after(0, lambda: item.set_status("Initializing...", "yellow"))
        
        config = self.get_config_sync()
        
        browser = config["browser"]
        quality = config["quality"]
        org = config["org"]
        
        tmpl = config["tmpl"]
        if not tmpl.strip():
            tmpl = "%(title)s.%(ext)s"
            
        if org == "By Channel Name":
            out_tmpl = os.path.join(config["dir"], '%(uploader)s', tmpl)
        elif org == "By Playlist":
            out_tmpl = os.path.join(config["dir"], '%(playlist)s', tmpl)
        elif org == "By Channel & Playlist":
            out_tmpl = os.path.join(config["dir"], '%(uploader)s', '%(playlist)s', tmpl)
        else:
            out_tmpl = os.path.join(config["dir"], tmpl)
        
        cmd = ['yt-dlp', '--newline']
        cmd.extend(['--download-archive', ARCHIVE_FILE])
        cmd.extend(['--sleep-requests', '1.5', '--sleep-interval', '3', '--max-sleep-interval', '6'])
        
        if browser == "custom":
            working_cookie = os.path.join(DOCS_DIR, 'working_cookies.txt')
            try:
                if os.path.exists(config["cookie"]):
                    shutil.copyfile(config["cookie"], working_cookie)
                    cmd.extend(['--cookies', working_cookie])
                else:
                    cmd.extend(['--cookies', config["cookie"]])
            except:
                cmd.extend(['--cookies', config["cookie"]])
        elif browser != "none":
            cmd.extend(['--cookies-from-browser', browser])
            
        cmd.extend(['--extractor-args', 'youtube:player_client=mweb,web,tv', '--js-runtimes', 'node'])
        
        rate = config["rate"].strip()
        if rate:
            cmd.extend(['--limit-rate', rate])
        
        if config.get("members_only"):
            cmd.extend(['--match-filters', "availability == subscriber_only"])
        
        force_mp4 = config["force_mp4"]
        if quality == "1080p":
            cmd.extend(['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'])
        elif quality == "720p":
            cmd.extend(['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'])
        elif quality == "480p":
            cmd.extend(['-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'])
        elif quality == "Audio Only":
            cmd.extend(['-f', 'bestaudio/best', '--extract-audio', '--audio-format', config["audio"].lower()])
        else:
            cmd.extend(['-f', 'bestvideo+bestaudio/best'])
            
        if force_mp4 and quality != "Audio Only":
            cmd.extend(['--merge-output-format', 'mp4', '--remux-video', 'mp4'])
        elif quality != "Audio Only":
            cmd.extend(['--merge-output-format', 'mkv', '--remux-video', 'mkv'])
            
        if config["proxy"].strip():
            cmd.extend(['--proxy', config["proxy"].strip()])
            
        if config["normalize"]:
            cmd.extend(['--postprocessor-args', 'Merger:-c:v copy -c:a aac -b:a 192k -af loudnorm=I=-16:TP=-1.5:LRA=11'])
            
        if config["subs"]:
            cmd.extend(['--write-subs', '--write-auto-subs', '--embed-subs', '--sub-langs', 'en.*,all'])
        if config["meta"]:
            cmd.extend(['--embed-thumbnail', '--embed-metadata', '--convert-thumbnails', 'jpg'])
        if config.get("chapters", True):
            cmd.append('--embed-chapters')
        if config.get("mtime", True):
            cmd.append('--mtime')
        if config["sponsor"]:
            cmd.extend(['--sponsorblock-remove', 'all'])
            
        if config["pl_start"].strip().isdigit():
            cmd.extend(['--playlist-start', config["pl_start"].strip()])
        if config["pl_end"].strip().isdigit():
            cmd.extend(['--playlist-end', config["pl_end"].strip()])
            
        if item.start_time or item.end_time:
            st = item.start_time or "00:00"
            et = item.end_time or "inf"
            cmd.extend(['--download-sections', f"*{st}-{et}"])
            
        cmd.extend(['--skip-playlist-after-errors', '3'])
        cmd.extend(['-o', out_tmpl, item.url])

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if not self.is_downloading:
                return
                
            if attempt > 1:
                self.root.after(0, lambda a=attempt: item.set_status(f"Retrying ({a}/{max_retries})...", "yellow"))
                time.sleep(3)
                
            try:
                item.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    text=True, encoding='utf-8', errors='replace', creationflags=0x08000000
                )
                
                progress_regex = re.compile(r'\[download\]\s+([\d\.]+)%\s+of\s+.*?at\s+([^\s]+)\s+ETA\s+([^\s]+)')
                auth_error_detected = False
                
                for line in item.process.stdout:
                    line = line.strip()
                    if not self.is_downloading:
                        break
                    match = progress_regex.search(line)
                    if match:
                        percent_str, speed, eta = match.groups()
                        try:
                            percent = float(percent_str) / 100.0
                            self.root.after(0, item.update_progress, percent, speed, eta)
                        except ValueError:
                            pass
                    elif "Join this channel" in line or "cookies are no longer valid" in line:
                        auth_error_detected = True
                        self.root.after(0, lambda: item.set_status("Error: Expired/Invalid cookies! Membership required.", "red"))
                    elif "Destination:" in line:
                        auth_error_detected = False
                        m_dest = re.search(r'Destination:\s+(.+)', line)
                        if m_dest:
                            fname = os.path.basename(m_dest.group(1))
                            self.root.after(0, lambda f=fname: item.set_status(f"Downloading: {f[:40]}...", "lightgreen"))
                    elif "ERROR:" in line:
                        if "Sign in to confirm" in line:
                            auth_error_detected = True
                            self.root.after(0, lambda: item.set_status("Error: YouTube bot check / cookies needed", "red"))
                        else:
                            self.root.after(0, lambda l=line: item.set_status(f"Error: {l[:45]}", "red"))
                    elif "Downloading item" in line:
                        m_item = re.search(r'Downloading item\s+(\d+\s+of\s+\d+)', line)
                        txt = f"Processing video {m_item.group(1)}..." if m_item else "Processing next video..."
                        if not auth_error_detected:
                            self.root.after(0, lambda t=txt: item.set_status(t, "cyan"))
                    elif "has already been recorded in the archive" in line or "has already been downloaded" in line:
                        self.root.after(0, lambda: item.set_status("Already downloaded (skipping)...", "cyan"))
                    elif "does not pass filter" in line or "skipping" in line:
                        self.root.after(0, lambda: item.set_status("Skipping non-member video...", "yellow"))
                    elif "Permission denied" in line or "Could not copy Chrome cookie" in line:
                        self.root.after(0, lambda: item.set_status("Cookies locked! Close browser.", "red"))
                    elif "[pot:wpc]" in line:
                        self.root.after(0, lambda: item.set_status("Bypassing Bot Protection...", "yellow"))
                    elif "[jsc:node]" in line:
                        self.root.after(0, lambda: item.set_status("Solving JS Challenge...", "yellow"))
                    elif "[Merger]" in line or "Merging formats" in line:
                        self.root.after(0, lambda: item.set_status("Merging Video & Audio...", "cyan"))
                    elif "[SponsorBlock]" in line:
                        self.root.after(0, lambda: item.set_status("Removing Sponsor Segments...", "magenta"))
                    elif "[VideoConvertor]" in line:
                        self.root.after(0, lambda: item.set_status("Re-encoding to MP4...", "orange"))
                    elif "Downloading webpage" in line:
                        if not auth_error_detected:
                            self.root.after(0, lambda: item.set_status("Fetching video info...", "yellow"))
                    
                item.process.wait()
                
                # Automatically merge and clean up any loose video/audio fragments
                self.auto_merge_and_cleanup(config["dir"])
                
                if not self.is_downloading:
                    return
                    
                has_fragments = any(re.search(r'\.f\d+\.mp4$', f) for f in os.listdir(config["dir"])) if os.path.exists(config["dir"]) else False
                if item.process.returncode == 0 or not has_fragments:
                    item.status = "Success"
                    self.root.after(0, lambda: item.set_status("Completed!", "lightgreen"))
                    self.save_history(item.url, "Success")
                    if self.var_notify.get():
                        self.root.after(0, lambda u=item.url: ToastNotification(self.root, "Download Finished", f"Finished downloading:\n{u}"))
                    break # Break out of retry loop on success
                else:
                    if attempt == max_retries:
                        item.status = "Failed"
                        self.root.after(0, lambda code=item.process.returncode: item.set_status(f"Failed (Code {code})", "red"))
                        self.save_history(item.url, "Failed")
                    
            except Exception as e:
                if self.is_downloading:
                    if attempt == max_retries:
                        item.status = "Failed"
                        self.root.after(0, lambda err=str(e): item.set_status(f"Error: {err}", "red"))
                        self.save_history(item.url, "Error")

if __name__ == "__main__":
    root = ctk.CTk()
    app = DownloaderApp(root)
    root.mainloop()

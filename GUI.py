"""UI: ซ้าย (สถิติ + ปุ่ม) / ขวา (กล้อง สลับเป็นประวัติได้)"""

from collections import deque
from datetime import datetime

import customtkinter as ctk
import PIL.Image


class InspectionApp(ctk.CTk):
    MAX_LOG_ENTRIES = 500   # log ใน RAM

    def __init__(self):
        super().__init__()
        self.log_entries = deque(maxlen=self.MAX_LOG_ENTRIES)
        self._log_listbox = None

        self.title("Chicken Quality Control")

        # เต็มจอ ล็อกไม่ให้ resize/ปิดด้วย X — Esc หรือปุ่ม ✕ เท่านั้น
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.attributes("-fullscreen", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(100, self.focus_force)

        ctk.set_appearance_mode("light")
        self.configure(fg_color="#f0f0f0")

        # scale font ตามขนาดจอ
        scale = min(sw/1280, sh/720)

        self.font_title   = ("Sarabun", int(32*scale), "bold")
        self.font_status  = ("Sarabun", int(28*scale), "bold")
        self.font_labels  = ("Sarabun", int(20*scale))
        self.font_numbers = ("Sarabun", int(32*scale), "bold")

        # ซ้าย 30% / ขวา 70%
        self.grid_columnconfigure(0, weight=30)
        self.grid_columnconfigure(1, weight=70)
        self.grid_rowconfigure(0, weight=1)

        self._build_left_panel(scale)
        self._build_right_panel()

        # ปุ่มปิดมุมซ้ายบน
        ctk.CTkButton(
            self, text="✕", width=int(36*scale), height=int(36*scale),
            font=("Sarabun", int(18*scale), "bold"),
            fg_color="#d33232", hover_color="#a52525", text_color="white",
            corner_radius=18, command=self.destroy,
        ).place(x=8, y=8)

    def _build_left_panel(self, scale):
        left = ctk.CTkFrame(self, fg_color="white", corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_columnconfigure(1, weight=1)
        for r in range(7):
            left.grid_rowconfigure(r, weight=1)

        ctk.CTkLabel(
            left, text="ตรวจคุณภาพไก่",
            font=self.font_title, text_color="black"
        ).grid(row=0, column=0, columnspan=2, pady=10)

        # ปุ่มสถานะ (ไม่ได้ให้กด ใช้ฟอร์มปุ่มเพราะมีขอบโค้ง)
        self.status_button = ctk.CTkButton(
            left, text="รอตรวจ / Waiting",
            font=self.font_status, fg_color="#888888", text_color="white",
            corner_radius=15, height=int(80*scale)
        )
        self.status_button.grid(row=1, column=0, columnspan=2, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(left, text="ผ่าน",    font=self.font_labels, text_color="black").grid(row=2, column=0, sticky="s")
        ctk.CTkLabel(left, text="ไม่ผ่าน", font=self.font_labels, text_color="black").grid(row=2, column=1, sticky="s")

        self.lbl_pass_val = ctk.CTkLabel(left, text="0", font=self.font_numbers, text_color="#009951")
        self.lbl_pass_val.grid(row=3, column=0, sticky="n")

        self.lbl_fail_val = ctk.CTkLabel(left, text="0", font=self.font_numbers, text_color="#FF383C")
        self.lbl_fail_val.grid(row=3, column=1, sticky="n")

        # นับแยกตามสาเหตุที่ reject
        reject_panel = ctk.CTkFrame(left, fg_color="#f8f8f8", corner_radius=10)
        reject_panel.grid(row=4, column=0, columnspan=2, padx=15, pady=5, sticky="ew")
        for c in range(3):
            reject_panel.grid_columnconfigure(c, weight=1)

        ctk.CTkLabel(reject_panel, text="เหลือง", font=self.font_labels, text_color="#b08d00").grid(row=0, column=0)
        ctk.CTkLabel(reject_panel, text="เขียว",  font=self.font_labels, text_color="#1a8a3d").grid(row=0, column=1)
        ctk.CTkLabel(reject_panel, text="แดง",    font=self.font_labels, text_color="#b32424").grid(row=0, column=2)

        self.lbl_yellow_val = ctk.CTkLabel(reject_panel, text="0", font=self.font_numbers, text_color="#f1b500")
        self.lbl_yellow_val.grid(row=1, column=0)

        self.lbl_green_val = ctk.CTkLabel(reject_panel, text="0", font=self.font_numbers, text_color="#1aab4a")
        self.lbl_green_val.grid(row=1, column=1)

        self.lbl_red_val = ctk.CTkLabel(reject_panel, text="0", font=self.font_numbers, text_color="#d33232")
        self.lbl_red_val.grid(row=1, column=2)

        # สลับหน้ากล้อง ↔ ประวัติ
        self.toggle_btn = ctk.CTkButton(
            left, text="ดูประวัติการตรวจ",
            font=self.font_labels, fg_color="#4a6fa5", hover_color="#3a5a85",
            corner_radius=10, height=int(40*scale),
            command=self.toggle_log_page,
        )
        self.toggle_btn.grid(row=5, column=0, columnspan=2, padx=20, pady=(5, 5), sticky="ew")

        # progress bar % สีผิดปกติของชิ้นปัจจุบัน
        colour_panel = ctk.CTkFrame(left, fg_color="white")
        colour_panel.grid(row=6, column=0, columnspan=2, padx=15, pady=10, sticky="ew")
        colour_panel.grid_columnconfigure(1, weight=1)

        self.color_bars = {}
        for i, (key, label, color) in enumerate([
            ("green",  "เขียว",   "#1aab4a"),
            ("yellow", "เหลือง",  "#f1b500"),
            ("red",    "แดงเข้ม", "#d33232"),
        ]):
            ctk.CTkLabel(
                colour_panel, text=label,
                font=("Sarabun", int(16*scale)), text_color="black"
            ).grid(row=i, column=0, padx=5, pady=2)

            bar = ctk.CTkProgressBar(colour_panel, progress_color=color, height=int(14*scale))
            bar.set(0)
            bar.grid(row=i, column=1, padx=5, pady=2, sticky="ew")

            val_lbl = ctk.CTkLabel(
                colour_panel, text="0%",
                font=("Sarabun", int(14*scale)), text_color="black"
            )
            val_lbl.grid(row=i, column=2, padx=5, pady=2)

            self.color_bars[key] = (bar, val_lbl)

    def _build_right_panel(self):
        # 2 หน้าซ้อนกัน ใช้ tkraise() สลับ
        right = ctk.CTkFrame(self, fg_color="black", corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # หน้ากล้อง
        camera_frame = ctk.CTkFrame(right, fg_color="black", corner_radius=0)
        camera_frame.grid(row=0, column=0, sticky="nsew")
        camera_frame.grid_rowconfigure(0, weight=1)
        camera_frame.grid_columnconfigure(0, weight=1)
        self.camera_frame = camera_frame
        self.camera_label = ctk.CTkLabel(camera_frame, text="", image=None)
        self.camera_label.grid(row=0, column=0, sticky="nsew")

        # หน้าประวัติ
        log_page = ctk.CTkFrame(right, fg_color="white", corner_radius=0)
        log_page.grid(row=0, column=0, sticky="nsew")
        log_page.grid_rowconfigure(1, weight=1)
        log_page.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(log_page, fg_color="#4a6fa5", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        for i, (txt, w) in enumerate([("รูป", 70), ("เวลา", 90), ("ชิ้น", 110), ("ผล", 150), ("เหตุผล", 180), ("G/Y/R %", 160)]):
            ctk.CTkLabel(header, text=txt, font=self.font_labels, text_color="white",
                         width=w, anchor="w").grid(row=0, column=i, padx=8, pady=10, sticky="w")

        scroll = ctk.CTkScrollableFrame(log_page, fg_color="white")
        scroll.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        scroll.grid_columnconfigure(2, weight=1)
        self._log_listbox = scroll

        btn_row = ctk.CTkFrame(log_page, fg_color="white")
        btn_row.grid(row=2, column=0, sticky="ew", padx=8, pady=6)
        ctk.CTkButton(btn_row, text="ล้างประวัติ", fg_color="#888888",
                      command=self._clear_log).pack(side="left", padx=4)

        self._camera_page = camera_frame
        self._log_page    = log_page
        self._on_log_page = False
        camera_frame.tkraise()

    # ── API จาก main.py ─────────────────────────────────────────────────────

    def update_color_bars(self, stats: dict):
        """อัปเดต progress bar % สี"""
        for key, (bar, lbl) in self.color_bars.items():
            v = float(stats.get(key, 0.0))
            bar.set(min(1.0, v/100.0))
            lbl.configure(text=f"{v:.1f}%")

    def add_log_entry(self, verdict: str, reason: str, stats: dict = None,
                      cls_name: str = "", img_path: str = ""):
        """เพิ่ม 1 รายการลงประวัติ — img_path เป็น path รูป crop"""
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {
            "time": ts, "verdict": verdict, "reason": reason,
            "stats": stats or {}, "cls": cls_name or "-",
            "img": img_path or "",
        }
        self.log_entries.append(entry)
        self._append_log_row(entry)

    def toggle_log_page(self):
        self._on_log_page = not self._on_log_page
        if self._on_log_page:
            self._log_page.tkraise()
            self.toggle_btn.configure(text="กลับไปดูกล้อง")
        else:
            self._camera_page.tkraise()
            self.toggle_btn.configure(text="ดูประวัติการตรวจ")

    def _append_log_row(self, entry):
        row = len(self._log_listbox.grid_slaves(column=0))
        is_pass = entry["verdict"] == "PASS"
        color   = "#1a8a3d" if is_pass else "#b32424"
        bg      = "#f0f8f0" if is_pass else "#fff0f0"

        s = entry["stats"]
        stats_txt = f"{s.get('green',0):.0f}/{s.get('yellow',0):.0f}/{s.get('red',0):.0f}" if s else "-"

        # column 0: thumbnail (กดดูภาพใหญ่ได้)
        img_path = entry.get("img", "")
        thumb_btn = ctk.CTkButton(
            self._log_listbox, text="", width=64, height=48,
            fg_color=bg, hover_color="#e0e0e0", corner_radius=4,
            command=(lambda p=img_path: self._open_image(p)) if img_path else None,
        )
        if img_path:
            try:
                pil = PIL.Image.open(img_path)
                pil.thumbnail((60, 44))
                ctk_img = ctk.CTkImage(pil, size=pil.size)
                thumb_btn.configure(image=ctk_img)
                thumb_btn._image = ctk_img   # กัน GC
            except Exception:
                thumb_btn.configure(text="?")
        else:
            thumb_btn.configure(text="-")
        thumb_btn.grid(row=row, column=0, padx=4, pady=1)

        # column 1-5: ข้อความ
        for col, (txt, w) in enumerate([
            (entry["time"],         90),
            (entry.get("cls","-"), 110),
            (entry["verdict"],     150),
            (entry["reason"],      180),
            (stats_txt,            160),
        ], start=1):
            ctk.CTkLabel(self._log_listbox, text=txt, font=self.font_labels,
                         text_color=color, fg_color=bg, anchor="w", width=w
                         ).grid(row=row, column=col, padx=4, pady=1, sticky="ew")
        self._log_listbox._parent_canvas.yview_moveto(1.0)

    def _open_image(self, path: str):
        """popup โชว์ภาพใหญ่"""
        try:
            pil = PIL.Image.open(path)
            pil.thumbnail((800, 600))
            win = ctk.CTkToplevel(self)
            win.title(path.rsplit("/", 1)[-1])
            win.attributes("-topmost", True)
            ctk_img = ctk.CTkImage(pil, size=pil.size)
            lbl = ctk.CTkLabel(win, image=ctk_img, text="")
            lbl._image = ctk_img
            lbl.pack(padx=10, pady=10)
            ctk.CTkButton(win, text="ปิด", command=win.destroy).pack(pady=(0, 10))
        except Exception as e:
            print(f"open_image error: {e}")

    def _clear_log(self):
        self.log_entries.clear()
        if self._log_listbox is not None:
            for w in self._log_listbox.winfo_children():
                w.destroy()

    def set_status(self, state: str, reason: str = ""):
        """เปลี่ยนสีปุ่มสถานะ: pass / reject / idle"""
        if state == "pass":
            self.status_button.configure(text="ผ่าน / PASS", fg_color="#009951")
        elif state == "reject":
            text = f"ไม่ผ่าน - {reason}" if reason else "ไม่ผ่าน / REJECTED"
            self.status_button.configure(text=text, fg_color="#FF383C")
        else:
            self.status_button.configure(text="รอตรวจ / Waiting", fg_color="#888888")

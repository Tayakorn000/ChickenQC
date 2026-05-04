"""
หน้าจอหลักของระบบตรวจคุณภาพไก่
แบ่งเป็น 2 ฝั่ง: ซ้าย (สถิติ) / ขวา (กล้อง)
ไฟล์นี้มีหน้าที่แค่จัดวาง UI ไม่มีโค้ด logic ใดๆ
"""

import customtkinter as ctk


class InspectionApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Chicken Quality Control")

        # เปิดเต็มจอตั้งแต่แรก กด Escape เพื่อปิดโปรแกรม
        self.update_idletasks()
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.destroy())

        ctk.set_appearance_mode("light")
        self.configure(fg_color="#f0f0f0")

        # scale font ตามขนาดจอ เผื่อใช้กับหน้าจอที่ความละเอียดต่างกัน
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        scale = min(screen_w/1280, screen_h/720)

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

    def _build_left_panel(self, scale):
        left = ctk.CTkFrame(self, fg_color="white", corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_columnconfigure(1, weight=1)
        for r in range(6):
            left.grid_rowconfigure(r, weight=1)

        # หัวข้อ
        ctk.CTkLabel(
            left, text="ตรวจคุณภาพไก่",
            font=self.font_title, text_color="black"
        ).grid(row=0, column=0, columnspan=2, pady=10)

        # ปุ่มสถานะ — ใช้ Button เพราะมีขอบโค้ง ไม่ได้ให้กด
        # main.py จะเรียก set_status() เพื่อเปลี่ยนสีและข้อความ
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

        # แยกย่อยสาเหตุที่ไม่ผ่าน
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

        # progress bar แสดง % สีผิดปกติของชิ้นที่กำลังตรวจ
        colour_panel = ctk.CTkFrame(left, fg_color="white")
        colour_panel.grid(row=5, column=0, columnspan=2, padx=15, pady=10, sticky="ew")
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
        camera_frame = ctk.CTkFrame(self, fg_color="black", corner_radius=0)
        camera_frame.grid(row=0, column=1, sticky="nsew")
        camera_frame.grid_rowconfigure(0, weight=1)
        camera_frame.grid_columnconfigure(0, weight=1)

        self.camera_frame = camera_frame  # main.py ต้องอ่านขนาด panel นี้เพื่อ resize ภาพ

        self.camera_label = ctk.CTkLabel(camera_frame, text="", image=None)
        self.camera_label.grid(row=0, column=0, sticky="nsew")

    # ── ถูกเรียกจาก main.py ──────────────────────────────────────────────────

    def update_color_bars(self, stats: dict):
        """อัปเดต progress bar เปอร์เซ็นต์สี รับ dict เช่น {"green": 1.2, "yellow": 0.0, "red": 0.0}"""
        for key, (bar, lbl) in self.color_bars.items():
            v = float(stats.get(key, 0.0))
            bar.set(min(1.0, v/100.0))
            lbl.configure(text=f"{v:.1f}%")

    def set_status(self, state: str, reason: str = ""):
        """เปลี่ยนสีและข้อความปุ่มสถานะ — "pass" / "reject" / อื่นๆ"""
        if state == "pass":
            self.status_button.configure(text="ผ่าน / PASS", fg_color="#009951")
        elif state == "reject":
            text = f"ไม่ผ่าน - {reason}" if reason else "ไม่ผ่าน / REJECTED"
            self.status_button.configure(text=text, fg_color="#FF383C")
        else:
            self.status_button.configure(text="รอตรวจ / Waiting", fg_color="#888888")

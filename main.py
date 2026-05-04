"""
ระบบตรวจคุณภาพชิ้นไก่ — รันบน Raspberry Pi 5

แบ่งการทำงานเป็น 4 ส่วนที่รันพร้อมกัน:
  Thread 1 (กล้อง)    → จับภาพรัวๆ ไม่หยุดรอใคร
  Thread 2 (AI)        → รับภาพไปให้ YOLO + วิเคราะห์สีเนื้อ
  Thread 3 (วาดภาพ)   → วาดกรอบ + ข้อความลงภาพ แล้วส่งให้หน้าจอ
  Main Thread (หน้าจอ) → แค่เอาภาพที่วาดเสร็จแล้วไปแปะบนจอ

ทำแบบนี้เพราะถ้าให้ทุกอย่างรันบน main thread เดียว หน้าจอจะกระตุกทุกครั้งที่ YOLO ประมวลผล
"""

import threading
import time
from pathlib import Path
from queue import Queue, Empty
# import RPi.GPIO as GPIO  # TODO: เปิดตอนต่อนิวเมติกจริง

import cv2
import numpy as np
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
from picamera2 import Picamera2
from ultralytics import YOLO
import customtkinter as ctk

from GUI import InspectionApp

ROOT    = Path(__file__).parent
WEIGHTS = ROOT / "runs" / "detect" / "runs" / "chicken_v1" / "weights" / "best.pt"

# ข้าม 5 frame แล้วค่อยส่ง 1 frame ให้ AI — ทำให้หน้าจอลื่น AI ไม่ต้องแบกรับทุก frame
AI_SKIP_FRAMES = 5

# YOLO จะรายงานผลเฉพาะ box ที่มั่นใจเกิน 35%
CONF_THRESHOLD = 0.35

# ── TODO: นิวเมติก ────────────────────────────────────────────────────────────
# RELAY_PIN      = 17   # ขา GPIO ที่ต่อกับ relay (เปลี่ยนตามที่ต่อจริง)
# BELT_DELAY_SEC = 5.0  # วินาทีที่ชิ้นไก่ใช้เดินทางจากกล้องถึงจุดดัน (สายพานคงที่)
# PUSH_DURATION  = 0.4  # วินาทีที่กระบอกค้างไว้ก่อนเก็บกลับ
# ─────────────────────────────────────────────────────────────────────────────

# ── font ──────────────────────────────────────────────────────────────────────
# OpenCV วาดภาษาไทยไม่ได้ เลยต้องใช้ PIL แทน
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
    "/usr/share/fonts/truetype/tlwg/Sawasdee.ttf",
    "/usr/share/fonts/truetype/thaisarun/THSarabunNew.ttf",
]
_FONT_PATH  = next((p for p in _FONT_CANDIDATES if Path(p).exists()), None)
_FONT_CACHE = {}

def _font(size: int):
    if size not in _FONT_CACHE:
        _FONT_CACHE[size] = (
            PIL.ImageFont.truetype(_FONT_PATH, size) if _FONT_PATH
            else PIL.ImageFont.load_default()
        )
    return _FONT_CACHE[size]


def apply_gain(img_bgr, gain):
    """ปรับสีแต่ละ channel ตามค่า gain"""
    return np.clip(img_bgr.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def compute_wb_gain(roi_bgr):
    """
    ประมาณค่าปรับแสงจากพื้นหลัง (ถาด/สายพาน)
    หลักการคือดูสีพื้นที่สว่างๆ อิ่มตัวต่ำ แล้วคำนวณว่าต้องปรับเท่าไหร่ให้เป็น grey กลางๆ
    ถ้าหาพื้นหลังไม่เจอก็คืน [1,1,1] (ไม่ปรับอะไร)
    """
    try:
        hsv     = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        s, v    = hsv[..., 1], hsv[..., 2]
        bg_mask = (s < 80) & (v > 130)
        if int(bg_mask.sum()) < 500:
            return np.array([1.0, 1.0, 1.0], dtype=np.float32)
        bg_mean = roi_bgr[bg_mask].astype(np.float32).mean(axis=0)
        target  = float(bg_mean.mean())
        return np.clip(target / np.clip(bg_mean, 1.0, None), 0.5, 2.0).astype(np.float32)
    except:
        return np.array([1.0, 1.0, 1.0], dtype=np.float32)


def classify_color(crop_bgr):
    """
    ดูว่าชิ้นไก่มีสีผิดปกติไหม โดยนับ % ของ pixel สีเขียว/เหลือง/แดงเข้ม
    ถ้าเกิน threshold ที่กำหนด = reject

    รับ crop ที่ผ่าน white balance มาแล้ว (apply_gain)
    คืน (verdict, ข้อความ, dict สถิติ%)
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return "REJECT", "Empty", {}

    hsv     = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    chicken = ~((v > 220) & (s < 30))   # ตัด pixel สีขาว (พื้นหลัง) ออก
    n       = int(chicken.sum())
    if n < 200:
        return "REJECT", "No chicken", {}

    green    = chicken & (h >= 35)  & (h <= 85)  & (s >= 50)
    yellow   = chicken & (h >= 18)  & (h <= 32)  & (s >= 60) & (v >= 80)
    deep_red = chicken & ((h <= 8)  | (h >= 172)) & (s >= 140) & (v >= 50) & (v <= 180)

    g, y, r = 100.*green.sum()/n, 100.*yellow.sum()/n, 100.*deep_red.sum()/n
    stats   = {"green": g, "yellow": y, "red": r}

    if g >= 2.0:  return "REJECT-GREEN",  f"เขียว {g:.0f}%",  stats
    if y >= 5.0:  return "REJECT-YELLOW", f"เหลือง {y:.0f}%", stats
    if r >= 30.0: return "REJECT-RED",    f"แดง {r:.0f}%",    stats
    return "PASS", "ปกติ", stats


def annotate(frame, detections):
    """
    วาดกรอบและ label ลงภาพ
    - กรอบสี่เหลี่ยม → OpenCV (เร็วกว่า PIL เพราะ C++)
    - ข้อความภาษาไทย → PIL (OpenCV ไม่รองรับ unicode)
    ฟังก์ชันนี้รันใน RenderThread ไม่ใช่ main thread
    """
    if frame is None:
        return None

    img = frame.copy()

    for det in detections:
        x1, y1, x2, y2, _, _, verdict, _, _, _ = det
        color = (0, 200, 0) if verdict == "PASS" else (0, 0, 230)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)

    if not detections:
        return img

    # แปลงเป็น PIL แค่ครั้งเดียว วาด label ทุก box แล้วแปลงกลับ
    pil  = PIL.Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = PIL.ImageDraw.Draw(pil)
    font = _font(22)

    for det in detections:
        x1, y1, _, _, _, _, verdict, reason, _, _ = det
        color = (0, 200, 0) if verdict == "PASS" else (230, 0, 0)
        tw    = draw.textlength(reason, font=font)
        draw.rectangle([x1, max(0, y1-30), x1+tw+10, max(0, y1)], fill=color)
        draw.text((x1+5, max(0, y1-28)), reason, font=font, fill=(255, 255, 255))

    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


class YOLOProcessor:
    def __init__(self, model_path, app):
        self.app     = app
        self.model   = YOLO(str(model_path))
        self.running = True

        # Lock กันหลาย thread อ่าน/เขียนตัวแปรเดียวกันพร้อมกัน
        self._frame_lock   = threading.Lock()
        self._latest_frame = None

        self._det_lock          = threading.Lock()
        self._latest_detections = []

        self._ai_queue      = Queue(maxsize=2)   # ส่งภาพให้ AI (เก็บแค่ 2 ใบ ไม่ค้างมาก)
        self._display_queue = Queue(maxsize=1)   # ส่งภาพให้หน้าจอ (1 ใบ = ล่าสุดเสมอ)

        self.counts      = {"pass": 0, "fail": 0, "yellow": 0, "green": 0, "red": 0}
        self.counted_ids = set()  # tracking ID ที่นับแล้ว กันนับซ้ำ

        # TODO: เปิดตอนต่อนิวเมติกจริง
        # GPIO.setmode(GPIO.BCM)
        # GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

        self._init_camera()

        threading.Thread(target=self._camera_worker, daemon=True, name="CameraThread").start()
        threading.Thread(target=self._ai_worker,     daemon=True, name="AIThread").start()
        threading.Thread(target=self._render_worker, daemon=True, name="RenderThread").start()

        self._update_display()

    def _init_camera(self):
        if hasattr(self, '_picam2') and self._picam2:
            try: self._picam2.stop(); self._picam2.close()
            except: pass

        self._picam2 = Picamera2()
        cfg = self._picam2.create_video_configuration(
            main={"format": "BGR888", "size": (640, 480)}
        )
        self._picam2.configure(cfg)
        self._picam2.start()
        print("เปิดกล้องสำเร็จ")

    def _camera_worker(self):
        """จับภาพเร็วที่สุด แล้วส่งให้ AI ทุก AI_SKIP_FRAMES+1 frame"""
        ai_skip = 0
        while self.running:
            try:
                frame = self._picam2.capture_array()
            except Exception as e:
                print(f"กล้องมีปัญหา: {e} รีสตาร์ท...")
                time.sleep(0.5)
                self._init_camera()
                continue

            with self._frame_lock:
                self._latest_frame = frame  # เขียนทับตลอด RenderThread ได้ภาพใหม่เสมอ

            ai_skip += 1
            if ai_skip >= AI_SKIP_FRAMES + 1:
                ai_skip = 0
                if self._ai_queue.empty():
                    try:
                        self._ai_queue.put_nowait(frame.copy())  # copy() กัน race condition
                    except:
                        pass

    def _ai_worker(self):
        """
        รับภาพ → YOLO track → วิเคราะห์สีทีละ box
        ใช้ tracking ID กันนับชิ้นเดิมซ้ำ (ชิ้นหนึ่งอยู่ในเฟรมหลาย frame แต่นับแค่ครั้งแรก)
        """
        while self.running:
            try:
                frame   = self._ai_queue.get(timeout=1)
                results = self.model.track(
                    frame, conf=CONF_THRESHOLD, persist=True, verbose=False
                )[0]

                wb_gain = compute_wb_gain(frame)  # คำนวณ white balance ครั้งเดียวต่อ frame

                new_dets = []
                for box in results.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    cls = int(box.cls.item())
                    tid = int(box.id.item()) if box.id is not None else -1

                    crop = frame[max(0, y1):y2, max(0, x1):x2]
                    if crop.size == 0:
                        continue

                    # วิเคราะห์แค่ 60% ตรงกลาง เพราะขอบ box มักมีสีสายพานปนอยู่
                    h, w        = crop.shape[:2]
                    cw, ch      = int(w*0.6), int(h*0.6)
                    cx, cy      = (w-cw)//2, (h-ch)//2
                    center_crop = crop[cy:cy+ch, cx:cx+cw]

                    verdict, reason, stats = classify_color(apply_gain(center_crop, wb_gain))
                    new_dets.append((x1, y1, x2, y2, self.model.names[cls],
                                     float(box.conf.item()), verdict, reason, tid, stats))

                    if tid >= 0 and tid not in self.counted_ids:
                        self.counted_ids.add(tid)
                        self._increment_count(verdict)

                        # TODO: เปิดตอนต่อนิวเมติกจริง
                        # if verdict != "PASS":
                        #     threading.Timer(BELT_DELAY_SEC, self._trigger_pneumatic).start()

                with self._det_lock:
                    self._latest_detections = new_dets

                self.app.after(0, lambda d=new_dets: self._update_gui_stats(d))

            except Empty:
                continue
            except Exception as e:
                print(f"AI error: {e}")
                continue

    def _render_worker(self):
        """
        วาดภาพ + resize → ส่งให้ main thread แปะบนจอ
        ถ้าหน้าจอยังแสดงภาพเก่าอยู่ ก็ทิ้งแล้วแทนด้วยภาพใหม่เลย (ไม่สะสม lag)
        """
        display_w, display_h = 640, 480

        while self.running:
            with self._frame_lock:
                frame = self._latest_frame
            if frame is None:
                time.sleep(0.016)
                continue

            with self._det_lock:
                dets = list(self._latest_detections)

            annotated = annotate(frame, dets)

            panel_w = self.app.camera_frame.winfo_width()
            panel_h = self.app.camera_frame.winfo_height()
            if panel_w > 10 and panel_h > 10:
                display_w, display_h = panel_w-4, panel_h-4

            resized = cv2.resize(annotated, (display_w, display_h), interpolation=cv2.INTER_LINEAR)
            pil_img = PIL.Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))

            if self._display_queue.full():
                try: self._display_queue.get_nowait()
                except: pass
            try:
                self._display_queue.put_nowait(pil_img)
            except:
                pass

            time.sleep(0.005)  # ยอมให้ AI thread ได้ใช้ CPU บ้าง

    def _update_display(self):
        """
        main thread loop — แค่ดึงภาพจากคิวแล้วแปะ ไม่ทำอะไรหนักเลย
        ถ้าคิวว่างก็ข้ามไป รอรอบหน้า (ไม่ block)
        """
        try:
            pil_img = self._display_queue.get_nowait()
            w, h    = pil_img.size
            ctk_img = ctk.CTkImage(pil_img, size=(w, h))
            self.app.camera_label.configure(image=ctk_img, text="")
            self.app.camera_label._image = ctk_img  # ถ้าไม่เก็บ reference Python จะ GC ทิ้ง
        except Empty:
            pass

        self.app.after(16, self._update_display)

    # TODO: เปิดตอนต่อนิวเมติกจริง
    # def _trigger_pneumatic(self):
    #     GPIO.output(RELAY_PIN, GPIO.HIGH)
    #     time.sleep(PUSH_DURATION)
    #     GPIO.output(RELAY_PIN, GPIO.LOW)

    def _increment_count(self, verdict):
        if verdict == "PASS":
            self.counts["pass"] += 1
        else:
            self.counts["fail"] += 1
            if "YELLOW" in verdict:   self.counts["yellow"] += 1
            elif "GREEN" in verdict:  self.counts["green"]  += 1
            elif "RED"   in verdict:  self.counts["red"]    += 1
        self.app.after(0, self._refresh_counts_ui)

    def _refresh_counts_ui(self):
        self.app.lbl_pass_val.configure(text=str(self.counts["pass"]))
        self.app.lbl_fail_val.configure(text=str(self.counts["fail"]))
        self.app.lbl_yellow_val.configure(text=str(self.counts["yellow"]))
        self.app.lbl_green_val.configure(text=str(self.counts["green"]))
        self.app.lbl_red_val.configure(text=str(self.counts["red"]))

    def _update_gui_stats(self, dets):
        """อัปเดต status button + แถบสี ถ้ามีชิ้นไม่ผ่านให้แสดงชิ้นที่แย่ที่สุดก่อน"""
        if not dets:
            self.app.set_status("idle")
            self.app.update_color_bars({})
            return
        worst = next((d for d in dets if d[6] != "PASS"), dets[0])
        self.app.set_status("pass" if worst[6] == "PASS" else "reject", worst[7])
        self.app.update_color_bars(dets[-1][9])


if __name__ == "__main__":
    app  = InspectionApp()
    proc = YOLOProcessor(WEIGHTS, app)
    app.mainloop()
    proc.running = False

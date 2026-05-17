"""ตรวจคุณภาพชิ้นไก่บน Pi 5 — 4 thread: กล้อง / AI / วาดภาพ / หน้าจอ"""

import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
import RPi.GPIO as GPIO

import cv2
import numpy as np
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
from picamera2 import Picamera2
from ultralytics import YOLO
import customtkinter as ctk

from GUI import InspectionApp

ROOT     = Path(__file__).parent
WEIGHTS  = ROOT / "runs" / "detect" / "runs" / "chicken_v2" / "weights" / "best.onnx"
LOG_ROOT = ROOT / "rejects"   # crop ของชิ้น reject แยกตามวัน
TXT_LOG  = ROOT / "logs"      # txt log ทุกชิ้น แยกตามวัน
SNAPS    = ROOT / "snapshots" # ภาพ thumbnail ทุกชิ้น สำหรับโชว์ในหน้าประวัติ

AI_SKIP_FRAMES = 2     # ส่งให้ AI ทุก ๆ N+1 frame
CONF_THRESHOLD = 0.35  # ความมั่นใจขั้นต่ำของ YOLO

CLASS_TH = {           # อังกฤษ → ไทย สำหรับ label
    "chicken-drumstick": "น่องไก่",
    "chicken-breast":    "อกไก่",
}

# นิวเมติก: GPIO24 → relay → solenoid valve 24V
RELAY_PIN         = 24
BELT_DELAY_SEC    = 3.0   # เวลาเดินจากกล้องถึงจุดดัน
PUSH_DURATION     = 2.5   # เวลากระบอกค้าง
RELAY_ACTIVE_HIGH = True  # เปลี่ยนเป็น False ถ้า relay active LOW

# Pi font ไทย — OpenCV ไม่รองรับ unicode ต้องใช้ PIL
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",   # Thai + Latin + ตัวเลข
    "/usr/share/fonts/truetype/tlwg/Sawasdee.ttf",
    "/usr/share/fonts/truetype/thaisarun/THSarabunNew.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
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
    """คูณ gain ทีละ channel"""
    return np.clip(img_bgr.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def compute_wb_gain(roi_bgr):
    """White balance จากพื้นหลัง — คืน gain ที่ทำให้พื้นหลังเทากลาง"""
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
    """นับ % pixel สีผิดปกติ — คืน (verdict, ข้อความ, stats%)"""
    if crop_bgr is None or crop_bgr.size == 0:
        return "REJECT", "Empty", {}

    hsv     = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    chicken = ~((v > 220) & (s < 30))   # ตัดพื้นหลังขาว
    n       = int(chicken.sum())
    if n < 200:
        return "REJECT", "No chicken", {}

    green    = chicken & (h >= 35)  & (h <= 85)  & (s >= 50)
    yellow   = chicken & (h >= 22)  & (h <= 30)  & (s >= 140) & (v >= 120)
    deep_red = chicken & ((h <= 12) | (h >= 168)) & (s >= 90)  & (v >= 40) & (v <= 200)

    g, y, r = 100.*green.sum()/n, 100.*yellow.sum()/n, 100.*deep_red.sum()/n
    stats   = {"green": g, "yellow": y, "red": r}

    if g >= 2.0:  return "REJECT-GREEN",  f"เขียว {g:.0f}%",  stats
    if y >= 25.0: return "REJECT-YELLOW", f"เหลือง {y:.0f}%", stats
    if r >= 5.0:  return "REJECT-RED",    f"แดง {r:.0f}%",    stats
    return "PASS", "ปกติ", stats


def annotate(frame, detections):
    """วาดกรอบ (OpenCV) + label ไทย (PIL) — รันใน RenderThread"""
    if frame is None:
        return None

    img = frame.copy()
    if not detections:
        return img

    pil  = PIL.Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = PIL.ImageDraw.Draw(pil)
    font = _font(22)

    for det in detections:
        x1, y1, _, _, cls_name, _, verdict, reason, _, _ = det
        color   = (0, 200, 0) if verdict == "PASS" else (230, 0, 0)
        th_name = CLASS_TH.get(cls_name, cls_name)
        label   = f"{th_name} - {reason}"
        tw      = draw.textlength(label, font=font)
        draw.rectangle([x1, max(0, y1-30), x1+tw+10, max(0, y1)], fill=color)
        draw.text((x1+5, max(0, y1-28)), label, font=font, fill=(255, 255, 255))

    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


class YOLOProcessor:
    def __init__(self, model_path, app):
        self.app     = app
        self.model   = YOLO(str(model_path))
        self.running = True

        self._frame_lock   = threading.Lock()
        self._latest_frame = None
        self._det_lock          = threading.Lock()
        self._latest_detections = []

        self._ai_queue      = Queue(maxsize=2)   # ภาพให้ AI
        self._display_queue = Queue(maxsize=1)   # ภาพให้หน้าจอ (ล่าสุดเท่านั้น)

        self.counts      = {"pass": 0, "fail": 0, "yellow": 0, "green": 0, "red": 0}
        self.counted_ids = set()   # tracking ID ที่นับแล้ว กันนับซ้ำ

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(RELAY_PIN, GPIO.OUT,
                   initial=GPIO.LOW if RELAY_ACTIVE_HIGH else GPIO.HIGH)

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
            main={"format": "RGB888", "size": (640, 480)}
        )
        self._picam2.configure(cfg)
        self._picam2.start()
        # AWB warmup 2 วิ แล้วล็อก — สีคงที่ไม่ drift
        try:
            self._picam2.set_controls({"AwbEnable": True, "AeEnable": True})
            time.sleep(2.0)
            md = self._picam2.capture_metadata()
            gains = md.get("ColourGains")
            if gains:
                self._picam2.set_controls({
                    "AwbEnable":   False,
                    "ColourGains": (float(gains[0]), float(gains[1])),
                })
                print(f"AWB locked at gains={gains}")
        except Exception as e:
            print(f"camera control warn: {e}")
        print("เปิดกล้องสำเร็จ")

    def _camera_worker(self):
        """จับภาพรัว ๆ ส่งให้ AI ตามรอบ"""
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
                self._latest_frame = frame

            ai_skip += 1
            if ai_skip >= AI_SKIP_FRAMES + 1:
                ai_skip = 0
                if self._ai_queue.empty():
                    try:
                        self._ai_queue.put_nowait(frame.copy())
                    except:
                        pass

    def _ai_worker(self):
        """YOLO track + วิเคราะห์สีแต่ละ box — ใช้ tracking ID กันนับซ้ำ"""
        while self.running:
            try:
                frame   = self._ai_queue.get(timeout=1)
                results = self.model.track(
                    frame, conf=CONF_THRESHOLD, persist=True, verbose=False
                )[0]

                wb_gain = compute_wb_gain(frame)

                new_dets = []
                for box in results.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    cls = int(box.cls.item())
                    tid = int(box.id.item()) if box.id is not None else -1

                    crop = frame[max(0, y1):y2, max(0, x1):x2]
                    if crop.size == 0:
                        continue

                    # วิเคราะห์แค่ 60% ตรงกลาง — ขอบ box มักมีสีพื้นหลังปน
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
                        self._write_txt_log(tid, verdict, reason, stats)
                        snap_path = self._save_snapshot(crop, tid, verdict)
                        th_cls = CLASS_TH.get(self.model.names[cls], self.model.names[cls])
                        self.app.after(0, lambda v=verdict, r=reason, s=stats, c=th_cls, p=snap_path:
                                       self.app.add_log_entry(v, r, s, c, p))
                        if verdict != "PASS":
                            self._log_reject(frame, crop, tid, verdict, reason, stats)
                            # ไก่เสีย → เตะออกหลัง BELT_DELAY_SEC
                            threading.Timer(BELT_DELAY_SEC, self._trigger_pneumatic).start()

                with self._det_lock:
                    self._latest_detections = new_dets

                self.app.after(0, lambda d=new_dets: self._update_gui_stats(d))

            except Empty:
                continue
            except Exception as e:
                print(f"AI error: {e}")
                continue

    def _render_worker(self):
        """วาด + resize → คิวให้ main thread (ทิ้งเฟรมเก่าถ้าค้าง)"""
        display_w, display_h = 640, 480

        while self.running:
            with self._frame_lock:
                frame = self._latest_frame
            if frame is None:
                time.sleep(0.016)
                continue

            with self._det_lock:
                dets = list(self._latest_detections)

            # เร่งความอิ่มตัวก่อนวาด — ให้ตามองเห็นสีจริงชัด ไม่กระทบ AI
            hsv_disp = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.int16)
            hsv_disp[..., 1] = np.clip(hsv_disp[..., 1] * 1.6, 0, 255)
            boosted = cv2.cvtColor(hsv_disp.astype(np.uint8), cv2.COLOR_HSV2BGR)
            annotated = annotate(boosted, dets)

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

            time.sleep(0.005)  # ยอม CPU ให้ AI thread

    def _update_display(self):
        """ดึงภาพจากคิวแล้วแปะหน้าจอ — non-blocking"""
        try:
            pil_img = self._display_queue.get_nowait()
            w, h    = pil_img.size
            ctk_img = ctk.CTkImage(pil_img, size=(w, h))
            self.app.camera_label.configure(image=ctk_img, text="")
            self.app.camera_label._image = ctk_img   # กัน GC
        except Empty:
            pass

        self.app.after(16, self._update_display)

    def _trigger_pneumatic(self):
        """relay ON → ค้าง PUSH_DURATION → OFF"""
        on_state, off_state = (GPIO.HIGH, GPIO.LOW) if RELAY_ACTIVE_HIGH else (GPIO.LOW, GPIO.HIGH)
        try:
            GPIO.output(RELAY_PIN, on_state)
            time.sleep(PUSH_DURATION)
            GPIO.output(RELAY_PIN, off_state)
        except Exception as e:
            print(f"pneumatic error: {e}")

    def _save_snapshot(self, crop, tid, verdict):
        """บันทึก crop ทุกชิ้นลง snapshots/YYYY-MM-DD/ คืน path หรือ None"""
        if crop is None or crop.size == 0:
            return None
        try:
            now     = datetime.now()
            day_dir = SNAPS / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            ts   = now.strftime("%H%M%S_%f")[:-3]
            path = day_dir / f"{ts}_id{tid}_{verdict}.jpg"
            cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return str(path)
        except Exception as e:
            print(f"snapshot error: {e}")
            return None

    def _write_txt_log(self, tid, verdict, reason, stats):
        """log ทุกชิ้นลง logs/YYYY-MM-DD.txt"""
        try:
            now = datetime.now()
            TXT_LOG.mkdir(parents=True, exist_ok=True)
            line = (f"{now.strftime('%Y-%m-%d %H:%M:%S')}  id={tid:<4}  "
                    f"{verdict:<14}  {reason:<20}  "
                    f"G={stats.get('green',0):.1f}%  "
                    f"Y={stats.get('yellow',0):.1f}%  "
                    f"R={stats.get('red',0):.1f}%\n")
            with (TXT_LOG / f"{now.strftime('%Y-%m-%d')}.txt").open("a") as f:
                f.write(line)
        except Exception as e:
            print(f"txt log error: {e}")

    def _log_reject(self, frame, crop, tid, verdict, reason, stats):
        """เก็บภาพ + CSV ของชิ้น reject ลง rejects/YYYY-MM-DD/"""
        try:
            now     = datetime.now()
            day_dir = LOG_ROOT / now.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            ts      = now.strftime("%H%M%S_%f")[:-3]
            base    = f"{ts}_id{tid}_{verdict}"

            cv2.imwrite(str(day_dir / f"{base}_full.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if crop is not None and crop.size > 0:
                cv2.imwrite(str(day_dir / f"{base}_crop.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])

            with (day_dir / "log.csv").open("a") as f:
                if f.tell() == 0:
                    f.write("time,tid,verdict,reason,green%,yellow%,red%\n")
                f.write(f"{now.isoformat()},{tid},{verdict},{reason},"
                        f"{stats.get('green',0):.2f},{stats.get('yellow',0):.2f},{stats.get('red',0):.2f}\n")
        except Exception as e:
            print(f"log_reject error: {e}")

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
        """อัปเดตปุ่มสถานะ + แถบสี — โชว์ชิ้นที่แย่สุดก่อน"""
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
    try:
        app.mainloop()
    finally:
        proc.running = False
        try: GPIO.cleanup()
        except: pass

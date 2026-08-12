"""
WeightReceiver — รับน้ำหนักจาก ESP8266 (plain-text กรัม/บรรทัด ที่ 10Hz)
  MODE = "serial" : ESP ต่อ USB     |     MODE = "udp" : ESP บน WiFi เดียวกัน

Peak-hold: idle → tracking (จับค่าสูงสุดตอนของวิ่งผ่าน) → commit ตอนของออก → ค้างแสดง
"""

import socket
import threading
import time

import serial
import serial.tools.list_ports

MODE             = "udp"          # "serial" | "udp"

SERIAL_PORT      = "auto"
SERIAL_BAUD      = 115200
SERIAL_TIMEOUT   = 2.0

UDP_PORT         = 5005

# Peak-hold detection (สำหรับของวิ่งผ่านบนสายพาน)
IDLE_THRESHOLD   = 30.0           # กรัม — เกินค่านี้ถือว่ามีของบนจุดชั่ง (> baseline สายพาน)
MIN_DWELL_SEC    = 0.5            # ของต้องอยู่บนจุดชั่งอย่างน้อยเท่านี้ ถึงนับ
MIN_WEIGHT_G     = 50.0           # ค่าสูงสุดต่ำกว่านี้ → ไม่นับ
PEAK_HOLD_SEC    = 3.0            # ค้างแสดงค่าสูงสุดนานเท่านี้ ก่อนกลับมาแสดงค่าปัจจุบัน


def _find_serial_port():
    for p in serial.tools.list_ports.comports():
        if "USB" in p.device or "ACM" in p.device:
            return p.device
    return None


class WeightReceiver:
    def __init__(self, on_peak=None, on_live=None):
        self.on_peak       = on_peak
        self.on_live       = on_live

        self.total_g       = 0.0
        self.last_peak     = 0.0
        self.peak_clear_at = 0.0
        self.running       = True
        self.connected     = False

        self._current_g    = 0.0

    def start(self):
        if MODE == "serial":
            threading.Thread(target=self._serial_loop, daemon=True,
                             name="WeightSerial").start()
        else:
            threading.Thread(target=self._udp_loop, daemon=True,
                             name="WeightUDP").start()
        threading.Thread(target=self._peak_loop, daemon=True,
                         name="WeightPeak").start()

    def clear_total(self):
        self.total_g       = 0.0
        self.last_peak     = 0.0
        self.peak_clear_at = 0.0
        if self.on_live:
            try: self.on_live(0.0, 0.0)
            except: pass

    def arm_pass(self):
        """no-op (กัน error จาก main.py ที่เรียก)"""
        pass

    def _serial_loop(self):
        while self.running:
            port = SERIAL_PORT if SERIAL_PORT != "auto" else _find_serial_port()
            if not port:
                time.sleep(3); continue
            print(f"weight: เชื่อมต่อ {port} @ {SERIAL_BAUD}", flush=True)
            try:
                ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT)
                self.connected = True
                while self.running:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self._handle_line(line)
            except Exception as e:
                print(f"weight serial err: {e}", flush=True)
                self.connected = False
                time.sleep(2)

    def _udp_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", UDP_PORT)); sock.settimeout(2.0)
        print(f"weight: UDP listen port {UDP_PORT}", flush=True)
        self.connected = True
        while self.running:
            try:
                data, _ = sock.recvfrom(64)
                line = data.decode("utf-8", errors="ignore").strip()
                if line:
                    self._handle_line(line)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"weight udp err: {e}", flush=True)
        sock.close()

    def _handle_line(self, line: str):
        try:
            for pfx in ("weight:", "w:", "g:"):
                if line.lower().startswith(pfx):
                    line = line[len(pfx):]; break
            g = float(line)
        except ValueError:
            return

        self._current_g = max(0.0, g)

        # ระหว่าง hold → ค้างแสดงค่าสูงสุด ไม่อัปเดตด้วยค่าปัจจุบัน
        if self.on_live:
            now = time.time()
            if self.peak_clear_at > 0 and now < self.peak_clear_at:
                disp = self.last_peak
            else:
                disp = self._current_g
            try: self.on_live(disp, self.total_g / 1000.0)
            except: pass

    def _peak_loop(self):
        """จับค่าสูงสุดตอนของวิ่งผ่านจุดชั่ง → commit เมื่อของออก → ค้างแสดง"""
        state       = "idle"    # idle | tracking
        max_g       = 0.0
        above_since = 0.0

        while self.running:
            time.sleep(0.05)    # 20Hz — จับ peak ให้ทันของวิ่ง
            g   = self._current_g
            now = time.time()

            # หมดเวลา hold → กลับมาแสดงค่าปัจจุบัน
            if self.peak_clear_at > 0 and now > self.peak_clear_at:
                self.peak_clear_at = 0.0
                if self.on_live:
                    try: self.on_live(self._current_g, self.total_g / 1000.0)
                    except: pass

            if state == "idle":
                if g > IDLE_THRESHOLD:
                    state       = "tracking"
                    max_g       = g
                    above_since = now

            elif state == "tracking":
                if g > IDLE_THRESHOLD:
                    max_g = max(max_g, g)
                else:
                    # ของออกจากจุดชั่งแล้ว → ตัดสินใจ commit
                    dwell = now - above_since
                    if max_g >= MIN_WEIGHT_G and dwell >= MIN_DWELL_SEC:
                        self._commit(max_g)
                    else:
                        print(f"weight: skip (max={max_g:.1f}g dwell={dwell:.2f}s)",
                              flush=True)
                    state = "idle"
                    max_g = 0.0

    def _commit(self, grams: float):
        self.total_g      += grams
        self.last_peak     = grams
        self.peak_clear_at = time.time() + PEAK_HOLD_SEC
        print(f"weight: PEAK {grams:.1f}g  total={self.total_g/1000.0:.3f}kg",
              flush=True)
        if self.on_peak:
            try: self.on_peak(grams, self.total_g / 1000.0)
            except Exception as e: print(f"on_peak err: {e}")
        if self.on_live:
            try: self.on_live(grams, self.total_g / 1000.0)
            except: pass

"""Test weight measurement flow manually"""
import time
import weight as _w
_w.CAM_TO_SCALE_SEC = 15.0   # ขยายเวลาให้ user วางของทัน
from weight import WeightReceiver

def on_peak(g, total_kg):
    print(f"\n✅ COMMIT: {g:.1f}g  total={total_kg:.3f}kg\n", flush=True)

w = WeightReceiver(on_peak=on_peak, on_live=None)
w.start()

print("รอ 5 วิ — load cell ต้องว่าง...", flush=True)
time.sleep(5)
print(f"baseline = {w._current_baseline():.1f}g", flush=True)

print("\n🟡 ARM! รอ 15 วินาที — เตรียมวางขวดได้เลย", flush=True)
w.arm_pass()

start = time.time()
while time.time() - start < 20:
    elapsed = time.time() - start
    if w._measuring:
        print(f"  [t={elapsed:4.1f}s] current={w._current_g:6.1f}g  ⏺️ MEASURING — วางค้างไว้!", flush=True)
    else:
        remain = 15 - elapsed
        if remain > 0:
            tag = "💤 รอ..." if remain > 5 else "⚠️  วางขวดได้เลย!" if remain > 2 else "🔴 วางตอนนี้!!"
            print(f"  [t={elapsed:4.1f}s] current={w._current_g:6.1f}g  T-{remain:4.1f}s  {tag}", flush=True)
        else:
            print(f"  [t={elapsed:4.1f}s] current={w._current_g:6.1f}g  done", flush=True)
    time.sleep(0.5)

print(f"\nผลรวม total = {w.total_g:.1f}g  last_peak = {w.last_peak:.1f}g")

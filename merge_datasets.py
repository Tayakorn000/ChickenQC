"""
Merge 3-class dataset: drumstick(0) / breast(1) / foreign(2)
Balance: cap each class to the smallest = breast count.
80/20 train/val split, seed 42.
"""
import random, shutil
from pathlib import Path

random.seed(42)
ROOT = Path("/Users/tayakornwet/Documents/chicken")
OUT  = ROOT / "dataset"
VAL_RATIO = 0.20

# ── sources ────────────────────────────────────────────────────────────────
DRUM_IMG   = ROOT / "data 1" / "train" / "น่อง"
DRUM_LBL   = ROOT / "data 1" / "train" / "labels_น่อง"
BREAST_IMG = ROOT / "data 2" / "train" / "อกไก่"
BREAST_LBL = ROOT / "data 2" / "train" / "labels_อกไก่"
FOREIGN_DIRS = [
    (ROOT / "data_foreign" / "train" / "images", ROOT / "data_foreign" / "train" / "labels"),
    (ROOT / "data_foreign" / "valid" / "images", ROOT / "data_foreign" / "valid" / "labels"),
]
# เศษไข่ + เศษกระดาษลัง — foreign จริงในไลน์ ใช้ก่อน garbage
EGG_DIRS = [
    (ROOT / "rf_eggshell" / "train" / "images", ROOT / "rf_eggshell" / "train" / "labels"),
    (ROOT / "rf_eggshell" / "valid" / "images", ROOT / "rf_eggshell" / "valid" / "labels"),
]
CARD_DIRS = [(ROOT / "rf_cardboard" / "train" / "images", ROOT / "rf_cardboard" / "train" / "labels")]
CARD_KEEP = {1, 3}   # CARDBOARD, PAPER เท่านั้น (ตัด METAL/PLASTIC/BIODEGRADABLE)

# ── clean output ───────────────────────────────────────────────────────────
for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
    p = OUT / sub
    if p.exists(): shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)

# ── helpers ────────────────────────────────────────────────────────────────
def collect_pairs(img_dir, lbl_dir, keep=None):
    pairs = []
    if not img_dir.exists(): return pairs
    for img in img_dir.iterdir():
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}: continue
        lbl = lbl_dir / (img.stem + ".txt")
        if not lbl.exists(): continue
        lines = [ln for ln in lbl.read_text().strip().splitlines() if len(ln.split()) >= 5]
        if not lines: continue   # drop รูปที่ label ว่าง (ไม่เอา background)
        # keep=set → drop รูปที่ไม่มี label ใน class ที่ต้องการเลย
        if keep is not None and not any(int(ln.split()[0]) in keep for ln in lines):
            continue
        pairs.append((img, lbl, keep))
    return pairs

def poly_to_bbox(parts, cls):
    coords = [float(x) for x in parts[1:]]
    if len(coords) == 4:   # already bbox
        return f"{cls} {coords[0]:.6f} {coords[1]:.6f} {coords[2]:.6f} {coords[3]:.6f}"
    xs, ys = coords[0::2], coords[1::2]
    xmin,xmax = max(0.,min(xs)), min(1.,max(xs))
    ymin,ymax = max(0.,min(ys)), min(1.,max(ys))
    return f"{cls} {(xmin+xmax)/2:.6f} {(ymin+ymax)/2:.6f} {xmax-xmin:.6f} {ymax-ymin:.6f}"

def convert(src, dst, cls, keep=None):
    out = []
    for line in src.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) < 5: continue
        if keep is not None and int(parts[0]) not in keep: continue
        out.append(poly_to_bbox(parts, cls))
    dst.write_text("\n".join(out) + ("\n" if out else ""))

def write_split(pairs, cls, prefix):
    random.shuffle(pairs)
    n_val = int(len(pairs) * VAL_RATIO)
    for split, items in [("val", pairs[:n_val]), ("train", pairs[n_val:])]:
        for img, lbl, keep in items:
            stem = f"{prefix}_{img.stem}"
            shutil.copy2(img, OUT / "images" / split / (stem + img.suffix.lower()))
            convert(lbl, OUT / "labels" / split / (stem + ".txt"), cls, keep)
    return len(pairs) - n_val, n_val

# ── collect ────────────────────────────────────────────────────────────────
drum_pairs    = collect_pairs(DRUM_IMG, DRUM_LBL)
breast_pairs  = collect_pairs(BREAST_IMG, BREAST_LBL)

# foreign: เศษไข่+เศษลัง (priority) แล้วค่อยเติม garbage
egg_pairs  = []
for img_d, lbl_d in EGG_DIRS:  egg_pairs  += collect_pairs(img_d, lbl_d)
card_pairs = []
for img_d, lbl_d in CARD_DIRS: card_pairs += collect_pairs(img_d, lbl_d, keep=CARD_KEEP)
garbage_pairs = []
for img_d, lbl_d in FOREIGN_DIRS: garbage_pairs += collect_pairs(img_d, lbl_d)
priority = egg_pairs + card_pairs
random.shuffle(priority); random.shuffle(garbage_pairs)
print(f"drum={len(drum_pairs)}  breast={len(breast_pairs)}  "
      f"egg={len(egg_pairs)} card={len(card_pairs)} garbage={len(garbage_pairs)}")

# balance to smallest class
cap = min(len(drum_pairs), len(breast_pairs), len(priority) + len(garbage_pairs))
random.shuffle(drum_pairs);   drum_pairs   = drum_pairs[:cap]
random.shuffle(breast_pairs); breast_pairs = breast_pairs[:cap]
# foreign = egg+card เป็นหลัก + garbage 35% ไว้ generalize
n_gar = min(int(cap * 0.35), len(garbage_pairs))
n_pri = cap - n_gar
foreign_pairs = priority[:n_pri] + garbage_pairs[:n_gar]
print(f"balanced to {cap} each | foreign = {n_pri} egg+card + {n_gar} garbage")

# ── write ──────────────────────────────────────────────────────────────────
d_tr, d_val = write_split(drum_pairs,    0, "drum")
b_tr, b_val = write_split(breast_pairs,  1, "breast")
f_tr, f_val = write_split(foreign_pairs, 2, "foreign")

print(f"\n=== Final ===")
print(f"drumstick: train={d_tr} val={d_val}")
print(f"breast:    train={b_tr} val={b_val}")
print(f"foreign:   train={f_tr} val={f_val}")
print(f"TOTAL train={d_tr+b_tr+f_tr} val={d_val+b_val+f_val}")

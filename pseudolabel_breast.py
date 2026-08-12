"""
Pseudo-label the new breast images (LINE_ALBUM_*) that have no label yet,
using the current best.pt. Writes YOLO bbox labels (class 0, matching the
existing labels_อกไก่ convention; merge remaps to breast). Review before training.
"""
from pathlib import Path
from ultralytics import YOLO

ROOT   = Path("/Users/tayakornwet/Documents/chicken")
IMG    = ROOT / "data 2" / "train" / "อกไก่"
LBL    = ROOT / "data 2" / "train" / "labels_อกไก่"
MODEL  = ROOT / "runs" / "detect" / "runs" / "chicken_v2" / "weights" / "best.pt"
BREAST_CLS = 1     # model's breast class id
CONF       = 0.40

m = YOLO(str(MODEL))
todo = [p for p in IMG.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and not (LBL / (p.stem + ".txt")).exists()]
print(f"to label: {len(todo)}")

labeled = empty = 0
for p in todo:
    r = m.predict(str(p), conf=CONF, verbose=False)[0]
    lines = []
    for b in r.boxes:
        if int(b.cls.item()) != BREAST_CLS:
            continue
        cx, cy, w, h = b.xywhn[0].tolist()      # normalized bbox
        lines.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    (LBL / (p.stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
    if lines: labeled += 1
    else:     empty += 1

print(f"labeled={labeled}  empty(no breast found)={empty}")
# ponytail: pseudo-labels from the old model — eyeball a few before trusting them

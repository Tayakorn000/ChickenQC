"""
Merge data 1 (drumstick, bbox) + data 2 (breast, polygon) into one YOLO detection dataset.
- data 1: subsample to 2000, class id stays 0 -> chicken-drumstick
- data 2: all images, polygon -> bbox, class remap 0 -> 1 -> chicken-breast
- 80/20 train/val split (deterministic seed)
"""

import random
import shutil
from pathlib import Path

random.seed(42)

ROOT = Path("/Users/tayakornwet/Documents/chicken")
D1_IMG = ROOT / "data 1" / "train" / "images"
D1_LBL = ROOT / "data 1" / "train" / "labels"
D2_DIR = ROOT / "data 2"
OUT = ROOT / "dataset"

D1_SAMPLE = 2000
VAL_RATIO = 0.20

for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
    p = OUT / sub
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def poly_to_bbox(parts):
    """parts: [cls, x1, y1, x2, y2, ...] normalized -> [cls, cx, cy, w, h]"""
    cls = parts[0]
    coords = [float(x) for x in parts[1:]]
    xs = coords[0::2]
    ys = coords[1::2]
    xmin, xmax = max(0.0, min(xs)), min(1.0, max(xs))
    ymin, ymax = max(0.0, min(ys)), min(1.0, max(ys))
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    w = xmax - xmin
    h = ymax - ymin
    return f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def convert_label_d1(src_txt, dst_txt):
    """data 1: bbox already, class id stays 0."""
    lines_out = []
    for line in src_txt.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        lines_out.append(line)
    dst_txt.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))


def convert_label_d2(src_txt, dst_txt):
    """data 2: polygon -> bbox, remap class 0 -> 1."""
    lines_out = []
    for line in src_txt.read_text().strip().splitlines():
        parts = line.split()
        if len(parts) < 7 or len(parts) % 2 == 0:
            continue
        parts[0] = "1"  # remap to chicken-breast
        lines_out.append(poly_to_bbox(parts))
    dst_txt.write_text("\n".join(lines_out) + ("\n" if lines_out else ""))


def collect_pairs(img_dir, lbl_dir):
    pairs = []
    for img in img_dir.iterdir():
        if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
            continue
        lbl = lbl_dir / (img.stem + ".txt")
        if lbl.exists():
            pairs.append((img, lbl))
    return pairs


# data 1: subsample
d1_pairs = collect_pairs(D1_IMG, D1_LBL)
print(f"data 1 total pairs: {len(d1_pairs)}")
random.shuffle(d1_pairs)
d1_pairs = d1_pairs[:D1_SAMPLE]
print(f"data 1 after subsample: {len(d1_pairs)}")

# data 2: combine train + valid + test
d2_pairs = []
for split in ["train", "valid", "test"]:
    img_dir = D2_DIR / split / "images"
    lbl_dir = D2_DIR / split / "labels"
    if img_dir.exists():
        d2_pairs += collect_pairs(img_dir, lbl_dir)
print(f"data 2 total pairs: {len(d2_pairs)}")


def split_and_write(pairs, convert_fn, prefix):
    random.shuffle(pairs)
    n_val = int(len(pairs) * VAL_RATIO)
    val = pairs[:n_val]
    train = pairs[n_val:]
    for split_name, items in [("train", train), ("val", val)]:
        for img, lbl in items:
            new_stem = f"{prefix}_{img.stem}"
            new_img = OUT / "images" / split_name / (new_stem + img.suffix.lower())
            new_lbl = OUT / "labels" / split_name / (new_stem + ".txt")
            shutil.copy2(img, new_img)
            convert_fn(lbl, new_lbl)
    return len(train), len(val)


d1_tr, d1_val = split_and_write(d1_pairs, convert_label_d1, "d1")
d2_tr, d2_val = split_and_write(d2_pairs, convert_label_d2, "d2")

print(f"\n=== Final ===")
print(f"data 1 (drumstick): train={d1_tr}, val={d1_val}")
print(f"data 2 (breast):    train={d2_tr}, val={d2_val}")
print(f"TOTAL train={d1_tr + d2_tr}, val={d1_val + d2_val}")

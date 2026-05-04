# Chicken Quality Control System

A real-time poultry quality inspection system built for **Raspberry Pi 5**, combining YOLOv11 object detection with HSV-based color analysis to identify defective chicken pieces on a production line.

## Overview

The system captures video from a Pi Camera, runs YOLO tracking to locate individual chicken pieces, then classifies each piece by color to detect spoilage indicators (abnormal green, yellow, or deep-red discoloration). Results are displayed on a full-screen GUI with live statistics.

```
Camera Thread  →  AI Thread (YOLO + Color)  →  Render Thread  →  Main Thread (Display)
```

This multi-threaded pipeline ensures the display remains smooth even while the AI processes each frame.

## Features

- **Real-time object detection** — YOLOv11s tracking (`chicken-drumstick`, `chicken-breast`)
- **Color-based QC** — Per-piece HSV analysis with adaptive white balance from belt/tray background
- **Non-blocking UI** — 4-thread pipeline; camera and AI never stall the display
- **Deduplication** — Tracking IDs prevent counting the same piece multiple times across frames
- **Pneumatic actuator support** — GPIO relay code stubbed in, ready to enable for physical reject gate
- **Responsive layout** — Font and widget sizes scale to screen resolution

## Rejection Criteria

| Verdict        | Condition                          |
|----------------|------------------------------------|
| `REJECT-GREEN` | Green pixels ≥ 2% of piece area    |
| `REJECT-YELLOW`| Yellow pixels ≥ 5% of piece area   |
| `REJECT-RED`   | Deep-red pixels ≥ 30% of piece area|
| `PASS`         | None of the above                  |

## Requirements

- Raspberry Pi 5 (tested) or compatible Linux SBC
- Pi Camera Module
- Python 3.11+

```
pip install ultralytics picamera2 customtkinter opencv-python pillow
```

A Thai-compatible font (Noto Sans Thai, Loma, Sawasdee, or TH Sarabun New) must be installed for on-frame Thai text rendering.

## Project Structure

```
chicken/
├── main.py              # Entry point — camera, AI, render pipeline
├── GUI.py               # CustomTkinter UI layout (no business logic)
├── merge_datasets.py    # Dataset preparation utility
├── data.yaml            # YOLO dataset config
├── yolo11s.pt           # Pre-trained YOLOv11s base weights
└── runs/                # Training output (ignored by git)
```

## Usage

```bash
python main.py
```

Press `Escape` to exit the full-screen display.

## Training

```bash
yolo detect train model=yolo11s.pt data=data.yaml epochs=100 imgsz=640
```

Trained weights will be saved to `runs/detect/*/weights/best.pt`. Update the `WEIGHTS` path in `main.py` accordingly.

## Planned Features

- [ ] Enable GPIO relay for pneumatic reject gate (`RELAY_PIN`, `BELT_DELAY_SEC`)
- [ ] Configurable rejection thresholds via GUI
- [ ] Session export (CSV / PDF report)
- [ ] Remote monitoring dashboard

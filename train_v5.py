from ultralytics import YOLO
m = YOLO("yolo11s.pt")
m.train(data="data.yaml", epochs=100, imgsz=640, batch=16,
        device="mps", project="runs", name="train_v5", exist_ok=True,
        patience=20)
# export ONNX
best = "runs/train_v5/weights/best.pt"
YOLO(best).export(format="onnx", opset=12, imgsz=640)
print("EXPORT DONE:", best.replace("best.pt","best.onnx"))

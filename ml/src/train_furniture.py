"""Generate synthetic training dataset and train custom YOLOv8 model for indoor furniture (P6b).
Targeting >85% overall detection recall / mAP across furniture classes.
"""
import os
import json
import math
import cv2
import numpy as np
from pathlib import Path

CLASSES = [
    "chair", "table", "sofa", "shelf", "lamp",
    "tv", "bed", "potted_plant", "desk", "cabinet", "fridge"
]

def render_furniture_scene(width=640, height=640):
    """Draw procedural furniture items with varied colours, angles and backgrounds."""
    # Varied background wall tone
    bg_color = np.random.randint(190, 245, size=3, dtype=np.uint8)
    img = np.full((height, width, 3), bg_color, dtype=np.uint8)

    # Floor boundary
    floor_y = int(height * np.random.uniform(0.60, 0.75))
    floor_color = np.array([45, 65, 95], dtype=np.uint8) + np.random.randint(-15, 15, size=3, dtype=np.int16)
    img[floor_y:, :] = np.clip(floor_color, 0, 255).astype(np.uint8)
    
    boxes = []
    # 2 to 4 objects per scene with non-overlapping bounds
    n_obj = np.random.randint(2, 5)
    placed_boxes = []
    
    for _ in range(n_obj):
        cls_idx = np.random.randint(0, len(CLASSES))
        cls_name = CLASSES[cls_idx]
        
        bw = np.random.randint(80, 180)
        bh = np.random.randint(80, 200)
        
        # Position along floor level
        bx1 = np.random.randint(15, max(16, width - bw - 15))
        by1 = max(15, floor_y - bh + np.random.randint(-20, 30))
        by2 = min(height - 10, by1 + bh)
        bx2 = min(width - 10, bx1 + bw)
        
        # Distinct class styling for feature learning
        col = (int(np.random.randint(30, 210)), int(np.random.randint(30, 210)), int(np.random.randint(30, 210)))
        
        if cls_name in ("chair", "stool"):
            # Backrest + seat + legs
            cv2.rectangle(img, (bx1, by1), (bx2, by2), col, -1)
            cv2.rectangle(img, (bx1 + 8, by1 + 8), (bx2 - 8, by1 + (by2-by1)//2), (240, 240, 240), -1)
        elif cls_name in ("table", "desk"):
            # Tabletop + legs
            cv2.rectangle(img, (bx1, by1), (bx2, by1 + (by2-by1)//4), col, -1)
            cv2.rectangle(img, (bx1 + 6, by1 + (by2-by1)//4), (bx1 + 18, by2), (30, 30, 30), -1)
            cv2.rectangle(img, (bx2 - 18, by1 + (by2-by1)//4), (bx2 - 6, by2), (30, 30, 30), -1)
        elif cls_name == "sofa":
            # Couch frame + cushions
            cv2.rectangle(img, (bx1, by1), (bx2, by2), col, -1)
            cv2.rectangle(img, (bx1 + 8, by1 + 8), (bx2 - 8, by2 - 15), (col[0]//2, col[1]//2, col[2]//2), -1)
        elif cls_name == "lamp":
            # Lampshade + stand + base
            mid_x = (bx1 + bx2) // 2
            cv2.ellipse(img, (mid_x, by1 + 25), ((bx2-bx1)//2, 20), 0, 0, 360, (250, 245, 150), -1)
            cv2.line(img, (mid_x, by1 + 25), (mid_x, by2), (40, 40, 40), 4)
            cv2.ellipse(img, (mid_x, by2), ((bx2-bx1)//3, 8), 0, 0, 360, (40, 40, 40), -1)
        elif cls_name == "tv":
            # Screen + border + stand
            cv2.rectangle(img, (bx1, by1), (bx2, by2 - 10), (20, 20, 20), -1)
            cv2.rectangle(img, (bx1 + 6, by1 + 6), (bx2 - 6, by2 - 16), (70, 90, 120), -1)
            mid_x = (bx1 + bx2) // 2
            cv2.rectangle(img, (mid_x - 8, by2 - 10), (mid_x + 8, by2), (40, 40, 40), -1)
        elif cls_name == "potted_plant":
            # Pot + green foliage
            pot_top = by1 + (by2 - by1) // 2
            cv2.rectangle(img, (bx1 + 15, pot_top), (bx2 - 15, by2), (40, 80, 160), -1)
            cv2.circle(img, ((bx1 + bx2)//2, by1 + (by2-by1)//3), (bx2 - bx1)//3, (35, 170, 45), -1)
        elif cls_name == "bed":
            # Bed headboard + mattress + pillow
            cv2.rectangle(img, (bx1, by1), (bx1 + 20, by2), (80, 50, 30), -1)
            cv2.rectangle(img, (bx1 + 20, by1 + 25), (bx2, by2), col, -1)
            cv2.rectangle(img, (bx1 + 25, by1 + 30), (bx1 + 55, by1 + 55), (250, 250, 250), -1)
        elif cls_name == "fridge":
            # Fridge upper door + lower door + handle
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (230, 230, 235), -1)
            cv2.line(img, (bx1, by1 + (by2-by1)//3), (bx2, by1 + (by2-by1)//3), (120, 120, 120), 2)
            cv2.line(img, (bx2 - 10, by1 + 15), (bx2 - 10, by1 + (by2-by1)//3 - 15), (60, 60, 60), 3)
            cv2.line(img, (bx2 - 10, by1 + (by2-by1)//3 + 15), (bx2 - 10, by2 - 15), (60, 60, 60), 3)
        elif cls_name == "cabinet":
            # Cabinet doors + knobs
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (60, 90, 130), -1)
            mid_x = (bx1 + bx2) // 2
            cv2.line(img, (mid_x, by1), (mid_x, by2), (30, 50, 80), 2)
            cv2.circle(img, (mid_x - 10, (by1 + by2)//2), 4, (240, 220, 100), -1)
            cv2.circle(img, (mid_x + 10, (by1 + by2)//2), 4, (240, 220, 100), -1)
        elif cls_name == "shelf":
            # Outer frame + shelves
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (100, 70, 40), 3)
            h_step = (by2 - by1) // 3
            cv2.line(img, (bx1, by1 + h_step), (bx2, by1 + h_step), (100, 70, 40), 3)
            cv2.line(img, (bx1, by1 + 2*h_step), (bx2, by1 + 2*h_step), (100, 70, 40), 3)
        else:
            cv2.rectangle(img, (bx1, by1), (bx2, by2), col, -1)
            
        x_c = ((bx1 + bx2) / 2.0) / width
        y_c = ((by1 + by2) / 2.0) / height
        w_norm = (bx2 - bx1) / width
        h_norm = (by2 - by1) / height
        boxes.append((cls_idx, x_c, y_c, w_norm, h_norm))
        
    return img, boxes

def prepare_dataset(base_dir: Path, n_train=240, n_val=60):
    images_train = base_dir / "images" / "train"
    images_val = base_dir / "images" / "val"
    labels_train = base_dir / "labels" / "train"
    labels_val = base_dir / "labels" / "val"
    
    for p in (images_train, images_val, labels_train, labels_val):
        p.mkdir(parents=True, exist_ok=True)
        
    for i in range(n_train):
        img, boxes = render_furniture_scene()
        img_path = images_train / f"train_{i:04d}.jpg"
        lbl_path = labels_train / f"train_{i:04d}.txt"
        cv2.imwrite(str(img_path), img)
        with open(lbl_path, "w") as f:
            for b in boxes:
                f.write(f"{b[0]} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f} {b[4]:.6f}\n")
                
    for i in range(n_val):
        img, boxes = render_furniture_scene()
        img_path = images_val / f"val_{i:04d}.jpg"
        lbl_path = labels_val / f"val_{i:04d}.txt"
        cv2.imwrite(str(img_path), img)
        with open(lbl_path, "w") as f:
            for b in boxes:
                f.write(f"{b[0]} {b[1]:.6f} {b[2]:.6f} {b[3]:.6f} {b[4]:.6f}\n")
                
    yaml_content = f"""path: {base_dir.resolve().as_posix()}
train: images/train
val: images/val

names:
""" + "\n".join([f"  {i}: {name}" for i, name in enumerate(CLASSES)])

    data_yaml = base_dir / "dataset.yaml"
    data_yaml.write_text(yaml_content, encoding="utf-8")
    return data_yaml

def train(out_weights_path: Path):
    from ultralytics import YOLO
    
    dataset_dir = Path("storage/datasets/furniture_yolo")
    print(f"Generating expanded furniture dataset (240 train / 60 val) in {dataset_dir}...")
    yaml_path = prepare_dataset(dataset_dir, n_train=240, n_val=60)
    
    print("Loading YOLOv8n backbone...")
    model = YOLO("yolov8n.pt")
    
    print("Training custom furniture model for high accuracy (6 epochs)...")
    results = model.train(
        data=str(yaml_path),
        epochs=6,
        imgsz=640,
        batch=12,
        device="cpu",
        workers=0,
        project="storage/runs",
        name="furniture",
        verbose=True
    )
    
    out_weights_path.parent.mkdir(parents=True, exist_ok=True)
    best_weights = Path(model.trainer.best) if hasattr(model, "trainer") and model.trainer else None
    if best_weights and best_weights.exists():
        import shutil
        shutil.copy(best_weights, out_weights_path)
    else:
        model.save(str(out_weights_path))
        
    print(f"Exported model to: {out_weights_path}")
    return out_weights_path

if __name__ == "__main__":
    out_file = Path("ml/models/yolo_furniture_v1.pt")
    train(out_file)

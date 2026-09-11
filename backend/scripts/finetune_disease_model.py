"""
NOT YET RUN — no Jharkhand-specific disease image dataset exists locally.

This is the transfer-learning script referenced in the plan: freeze the
ResNet50 backbone (already trained to 99%+ on PlantVillage's 38 classes, see
ml-model/notebooks/plant-disease-classification-resnet-99-2.ipynb in the
Crop-AI source repo) and fine-tune only the final classification layer on
photos of diseases affecting Jharkhand's priority crops (Rice Blast, Maize
Blight, pulse wilts, etc).

To use once you have a labeled image folder (ImageFolder layout: data_dir/
<class_name>/*.jpg):

    python finetune_disease_model.py --data_dir /path/to/jharkhand_diseases --epochs 10

This requires torch + torchvision (not in requirements.txt, since the served
app only needs onnxruntime for inference) — install with:
    pip install torch torchvision
"""

import argparse
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

BASE_DIR = Path(__file__).parent.parent
PYTORCH_CHECKPOINT = BASE_DIR.parent / "Crop-AI" / "ml-model" / "models" / "plant-disease" / "resnet50_best.pth"
OUTPUT_ONNX = BASE_DIR / "ml_models" / "plant-disease" / "resnet50_plant_disease.onnx"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True, help="ImageFolder-structured dataset of Jharkhand crop diseases")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(BASE_DIR.parent / "Crop-AI" / "apps" / "ml-server"))
    from app.utils.model import get_model  # ResNet50 architecture from the source repo

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    transform = transforms.Compose([
        transforms.Resize((256, 256)),
        transforms.ToTensor(),
    ])
    train_ds = datasets.ImageFolder(str(Path(args.data_dir) / "train"), transform=transform)
    val_ds = datasets.ImageFolder(str(Path(args.data_dir) / "valid"), transform=transform)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)

    # Load the pretrained 38-class PlantVillage backbone.
    model = get_model("resnet50", num_classes=38)
    checkpoint = torch.load(PYTORCH_CHECKPOINT, map_location=device)
    model.load_state_dict(checkpoint.get("model_state_dict", checkpoint))

    # Freeze everything except the final fc layer, then replace it with a
    # head sized for the new Jharkhand disease classes.
    for param in model.parameters():
        param.requires_grad = False
    model.fc = nn.Linear(model.fc.in_features, len(train_ds.classes))
    model = model.to(device)

    optimizer = optim.Adam(model.fc.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(args.epochs):
        model.train()
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()

        model.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                preds = model(images).argmax(dim=1)
                correct += (preds == labels).sum().item()
                total += labels.size(0)
        print(f"Epoch {epoch + 1}/{args.epochs} - val acc: {correct / total:.4f}")

    dummy = torch.randn(1, 3, 256, 256).to(device)
    torch.onnx.export(
        model, dummy, str(OUTPUT_ONNX),
        input_names=["input"], output_names=["output"],
        dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
        opset_version=11,
    )
    print(f"Exported fine-tuned model -> {OUTPUT_ONNX}")
    print(f"New class list (update DISEASE_CLASSES in services/ml_service.py): {train_ds.classes}")


if __name__ == "__main__":
    main()

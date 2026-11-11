"""Synthetic two-color media fixtures through the bundled Pillow runtime."""

import sys
from pathlib import Path

from PIL import Image

if __name__ == "__main__":
    root = Path(sys.argv[1])
    Image.new("RGB", (64, 64), (255, 0, 0)).save(root / "first.png")
    Image.new("RGB", (64, 64), (0, 0, 255)).save(root / "second.png")

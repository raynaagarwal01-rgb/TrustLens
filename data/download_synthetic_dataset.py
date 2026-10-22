"""
download_synthetic_dataset.py — TrustLens Dataset Fetcher & Scaler

Utilities to:
  1. Fetch additional synthetic/AI-generated faces (StyleGAN / Diffusion / open mirrors)
  2. Fetch real face samples (for balanced binary classification: Real vs Fake)
  3. Validate image integrity, standardize sizes, and generate train/val splits
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
FAKE_DIR = BASE_DIR / "fake"
REAL_DIR = BASE_DIR / "real"

# Curated open URLs for benchmark real face samples (public domain / open license)
SAMPLE_REAL_FACES = [
    ("https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1024&q=80", "real_01.jpg"),
    ("https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=1024&q=80", "real_02.jpg"),
    ("https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=1024&q=80", "real_03.jpg"),
    ("https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=1024&q=80", "real_04.jpg"),
    ("https://images.unsplash.com/photo-1517841905240-472988babdf9?w=1024&q=80", "real_05.jpg"),
    ("https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=1024&q=80", "real_06.jpg"),
    ("https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=1024&q=80", "real_07.jpg"),
    ("https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=1024&q=80", "real_08.jpg"),
]


def download_file(url: str, dest_path: Path, max_retries: int = 3) -> bool:
    headers = {"User-Agent": "TrustLens-Research/1.0"}
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                dest_path.write_bytes(data)
            # Verify image is valid
            with Image.open(dest_path) as img:
                img.verify()
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1.0)
            else:
                print(f"  [!] Failed to download {url}: {e}")
                if dest_path.exists():
                    dest_path.unlink()
                return False


def setup_real_faces():
    """Downloads sample real faces to balance the synthetic face dataset."""
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[*] Downloading reference real faces to {REAL_DIR}...")
    success_count = 0
    for url, filename in SAMPLE_REAL_FACES:
        target = REAL_DIR / filename
        if target.exists():
            print(f"  [+] {filename} already exists, skipping.")
            success_count += 1
            continue
        print(f"  [-] Downloading {filename}...")
        if download_file(url, target):
            print(f"  [+] Saved {filename}")
            success_count += 1
    print(f"[*] Real faces downloaded: {success_count}/{len(SAMPLE_REAL_FACES)}")


def summarize_dataset():
    """Prints a summary of the current dataset structure."""
    fake_images = list(FAKE_DIR.glob("*.jpg")) + list(FAKE_DIR.glob("*.png"))
    real_images = list(REAL_DIR.glob("*.jpg")) + list(REAL_DIR.glob("*.png"))
    
    print("\n" + "=" * 50)
    print("TrustLens Face Dataset Summary:")
    print(f"  • AI-Generated (Fake) Faces : {len(fake_images)} images ({FAKE_DIR})")
    print(f"  • Real Reference Faces      : {len(real_images)} images ({REAL_DIR})")
    print(f"  • Total Samples             : {len(fake_images) + len(real_images)}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    setup_real_faces()
    summarize_dataset()

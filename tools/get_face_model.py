"""
Download the pretrained face-swap model and convert it for TrustLens.

    python tools/get_face_model.py

Fetches the official checkpoint (267 MB) from its author's GitHub release (Selim Seferbekov,
MIT licence), converts it to models/face_swap/*.npz
(BatchNorm folded in, no PyTorch needed), and deletes the download. Run it once; restart TrustLens after.
"""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import face_model  # noqa: E402


def main():
    if face_model.available():
        print(f"Already installed: {face_model.NPZ}")
        return
    face_model.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    raw = face_model.MODEL_DIR / "checkpoint.download"
    print("Downloading the face-swap model checkpoint (267 MB) from GitHub...")
    t0 = time.time()

    def progress(blocks, block_size, total):
        done = min(blocks * block_size, total)
        if total > 0:
            print(f"\r  {done / 1e6:6.0f} / {total / 1e6:.0f} MB", end="", flush=True)

    urllib.request.urlretrieve(face_model.SOURCE_URL, raw, progress)
    print(f"\n  done in {time.time() - t0:.0f}s. Converting...")
    face_model.convert(raw)
    raw.unlink()
    print("  checking it runs...")
    import numpy as np
    t0 = time.time()
    with np.errstate(over="ignore"):
        face_model.fake_probability(np.full((300, 240, 3), 128, np.uint8))
    print(f"  works: one face takes {time.time() - t0:.1f}s on this computer.")
    print(f"Installed: {face_model.NPZ}. Restart TrustLens; the sidebar shows 'Face-swap model: on'.")


if __name__ == "__main__":
    main()

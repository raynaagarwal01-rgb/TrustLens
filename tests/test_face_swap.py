"""Run with: python tests/test_face_swap.py. Needs the model (python tools/get_face_model.py); skips otherwise."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import face_model  # noqa: E402
import face_swap  # noqa: E402
import faces  # noqa: E402
import torch_free  # noqa: E402


def test_confident_strategy():
    assert face_model.confident_strategy([0.99] * 16) > 0.98
    assert face_model.confident_strategy([0.01] * 16) < 0.02
    assert 0.3 < face_model.confident_strategy([0.9, 0.1, 0.5, 0.6]) < 0.6


def test_same_padding_matches_tensorflow():
    x = np.zeros((1, 380, 380), np.float32)
    xp, oh, ow = face_model._same_pad(x, 3, 2)
    assert (oh, ow) == (190, 190) and xp.shape == (1, 381, 381)  # TF pads 0 before, 1 after


def test_real_portraits_score_low():
    if not face_model.available():
        print("  (skipped: model not installed)")
        return
    for f in sorted((ROOT / "data" / "real").glob("*.jpg"))[:3]:
        im = Image.open(f).convert("RGB")
        boxes = faces.detect(im)
        if boxes:
            r = face_swap.check_image(im, boxes)
            assert r["score"] < 0.1, (f.name, r["score"])


def test_signal_and_floor():
    sig, note, floor = face_swap.verdict_inputs({"available": True, "n": 8, "score": 0.99, "fake_frames": 8, "seconds": 9}, video=True)
    assert sig["severity"] == "high" and note and floor == 88
    sig, note, floor = face_swap.verdict_inputs({"available": True, "n": 8, "score": 0.03, "fake_frames": 0, "seconds": 9}, video=True)
    assert sig["severity"] == "info" and not note and floor == 0 and "doesn't clear" in sig["detail"]
    sig, note, floor = face_swap.verdict_inputs({"available": False}, video=False)
    assert "get_face_model" in sig["detail"] and floor == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

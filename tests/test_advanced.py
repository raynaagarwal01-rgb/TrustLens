"""Run with: python tests/test_advanced.py   (or pytest). Locks in the calibration results."""

import glob
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import advanced as A  # noqa: E402

REAL = sorted(glob.glob(str(ROOT / "data" / "real" / "*.jpg"))) + sorted(glob.glob(str(ROOT / "samples" / "Au_*.jpg")))
AI = sorted(glob.glob(str(ROOT / "data" / "fake" / "*.jpg")))


def _resave(im, q, crop=(0, 0)):
    im = im.convert("RGB").crop((crop[0], crop[1], im.width, im.height))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue()))


def test_grid_no_false_alarms_on_real_or_ai_images():
    for p in REAL + AI:
        assert not A.grid_alignment(Image.open(p))[1], p


def test_grid_detects_high_quality_crop():
    hits = sum(bool(A.grid_alignment(_resave(Image.open(p), 98, (3, 5)))[1]) for p in REAL[:10])
    assert hits >= 4


def test_copy_move_finds_casia_clone_and_spares_photos():
    s, sig, vis = A.copy_move(Image.open(ROOT / "samples" / "Tp_S_NNN_S_O_pla00077_pla00077_11212.jpg"))
    if s.get("status") == "skipped":
        return  # OpenCV not installed
    assert sig and sig[0]["severity"] in ("medium", "high") and vis is not None
    for p in REAL + AI[:5]:
        sig = A.copy_move(Image.open(p))[1]
        assert not [x for x in sig if x["severity"] != "low"], p


def test_ghost_finds_low_quality_splice():
    base = Image.open(ROOT / "samples" / "Au_jolla_phone_photo.jpg").convert("RGB")
    W, H = base.size
    donor = _resave(Image.open(REAL[4]).resize((W // 4, H // 4)), 60)
    base.paste(donor, (W // 2, H // 3))
    stats, sig, _ = A.jpeg_ghost(_resave(base, 90))
    x0, y0, x1, y1 = stats["region"]["box"]
    assert sig and x0 < W // 2 + W // 4 and x1 > W // 2 and y0 < H // 3 + H // 4 and y1 > H // 3
    assert not A.jpeg_ghost(Image.open(ROOT / "samples" / "Au_jolla_phone_photo.jpg"))[1]


def test_compare_images():
    a = Image.open(ROOT / "samples" / "Au_iphone_photo.jpg")
    assert A.compare_images(Image.open(ROOT / "samples" / "Edited_iphone_photo_demo.jpg"), a)[0]["verdict"] == "edited"
    assert A.compare_images(a, a.resize((800, 600)))[0]["verdict"] == "same"
    assert A.compare_images(a, Image.open(ROOT / "samples" / "Au_jolla_phone_photo.jpg"))[0]["verdict"] == "different"


def test_structure_layers_histogram():
    data = (ROOT / "samples" / "Tp_S_NNN_S_O_pla00077_pla00077_11212.jpg").read_bytes()
    st = A.jpeg_structure(data)
    assert any("Photoshop" in s["marker"] for s in st["segments"]) and st["quant_tables"]
    img = Image.open(io.BytesIO(data))
    for k in A.LAYERS:
        assert A.layer(img, k).size == img.size
    assert len(A.histogram(img)["l"]) == 256


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

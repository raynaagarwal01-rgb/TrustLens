"""Run with: python tests/test_custody.py   (or pytest)"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import custody  # noqa: E402
import forensics  # noqa: E402


def _log():
    d = Path(tempfile.mkdtemp())
    p = d / "log.jsonl"
    for a in ("analysed", "vtop_notice_check", "report_exported"):
        custody.record(a, "ab" * 32, {"verdict": "likely_fake"}, path=p)
    return p


def test_chain_verifies():
    v = custody.verify(_log())
    assert v["ok"] and v["entries"] == 3 and len(v["head"]) == 64


def test_edit_delete_reorder_detected():
    p = _log()
    lines = p.read_text().splitlines()
    e = json.loads(lines[1]); e["details"]["verdict"] = "no_evidence"
    for bad in ([lines[0], json.dumps(e), lines[2]], [lines[0], lines[2]], [lines[1], lines[0], lines[2]]):
        p.write_text("\n".join(bad) + "\n")
        assert not custody.verify(p)["ok"]


def test_thumbnail_reveals_edit_and_authentic_matches():
    edited = forensics.analyse_image((ROOT / "samples" / "Edited_iphone_photo_demo.jpg").read_bytes())
    assert any(s["check"] == "Embedded thumbnail shows the original" for s in edited["signals"])
    x0, y0, x1, y1 = edited["thumbnail"]["changed_region"]
    W, H = 3264, 2448
    assert x0 < 0.75 * W and x1 > 0.55 * W and y0 < 0.55 * H and y1 > 0.3 * H  # overlaps the cloned area
    real = forensics.analyse_image((ROOT / "samples" / "Au_iphone_photo.jpg").read_bytes())
    assert any(s["check"] == "Embedded thumbnail matches" for s in real["signals"])
    assert real["gps"] and abs(real["gps"]["lat"] - 40.447) < 0.01


def test_perceptual_hash_survives_resave():
    from PIL import Image
    import io
    data = (ROOT / "samples" / "Au_jolla_phone_photo.jpg").read_bytes()
    im = Image.open(io.BytesIO(data))
    buf = io.BytesIO(); im.convert("RGB").resize((im.width // 2, im.height // 2)).save(buf, "JPEG", quality=70)
    a = forensics.perceptual_hashes(im)["phash"]
    b = forensics.perceptual_hashes(Image.open(io.BytesIO(buf.getvalue())))["phash"]
    assert forensics.hash_distance(a, b) <= 6


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

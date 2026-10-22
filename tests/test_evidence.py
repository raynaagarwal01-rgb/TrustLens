"""Run with: python tests/test_evidence.py   (or pytest)
Uses the real dataset samples in samples/ (CASIA v2 forgeries with ground-truth masks,
authentic phone photos)."""

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evidence_analyser as ea  # noqa: E402
import forensics  # noqa: E402
from report import build_report_html, result_to_json  # noqa: E402

SAMPLES = ROOT / "samples"
TAMPERED = sorted(p for p in SAMPLES.glob("Tp_*.jpg"))
AUTHENTIC = sorted(SAMPLES.glob("Au_*.jpg"))


def _ai_png() -> bytes:
    rng = np.random.default_rng(0)
    arr = (np.linspace(0, 255, 256)[None, :, None] * np.ones((256, 1, 3)) + rng.normal(0, 4, (256, 256, 3)))
    meta = PngImagePlugin.PngInfo()
    meta.add_text("parameters", "a photo of a student, Steps: 30, Sampler: DPM++ 2M, CFG scale: 7, Seed: 42")
    buf = io.BytesIO()
    Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(buf, "PNG", pnginfo=meta)
    return buf.getvalue()


def test_ela_localises_real_casia_forgeries():
    assert len(TAMPERED) == 4
    for p in TAMPERED:
        r = forensics.analyse_image(p.read_bytes(), p.name)
        region = r["ela"]["region"]
        assert region, f"no region for {p.name}"
        gt = np.asarray(Image.open(p.with_name(p.stem + "_gt.png")).convert("L")) > 127
        x0, y0, x1, y1 = region["box"]
        inside = gt[y0:y1, x0:x1].mean()
        assert inside > 5 * gt.mean(), f"{p.name}: box only {inside:.0%} inside the edit"


def test_no_false_alarm_on_authentic_phone_photos():
    assert AUTHENTIC
    for p in AUTHENTIC:
        r = ea.analyse(p.read_bytes(), p.name, use_llm=False)
        assert r["verdict"] == "no_evidence", (p.name, r["manipulation_score"])
        assert any(s["check"] == "Camera metadata present" for s in r["forensic_signals"])


def test_ai_metadata_cannot_be_overridden_by_llm():
    ea_call = ea.call_llm
    ea.call_llm = lambda *a, **k: json.dumps({"manipulation_score": 5, "fake_type": "none", "confidence": "high"})
    try:
        r = ea.analyse(_ai_png(), "gen.png")
    finally:
        ea.call_llm = ea_call
    assert r["verdict"] == "fake" and r["fake_type"] == "ai_generated"
    assert any("AI image generator" in n for n in r["rule_notes"])


def test_llm_receives_image_and_heatmap():
    seen = {}
    ea_call = ea.call_llm

    def fake(system, user, temperature=0.2, images=None):
        seen["images"] = [m for _, m in images]
        seen["has_tests"] = "Automated test signals" in user
        return json.dumps({"manipulation_score": 70, "fake_type": "spliced_or_object_edited",
                           "confidence": "medium", "visual_findings": [
                               {"finding": "halo around child", "location": "right", "evidence": "x", "severity": "high"}]})
    ea.call_llm = fake
    try:
        r = ea.analyse(TAMPERED[1].read_bytes(), TAMPERED[1].name)
    finally:
        ea.call_llm = ea_call
    assert seen == {"images": ["image/jpeg", "image/jpeg"], "has_tests": True}
    assert r["verdict"] == "likely_fake" and r["visual_findings"][0]["finding"] == "halo around child"


def test_llm_failure_falls_back_to_forensics():
    ea_call = ea.call_llm
    ea.call_llm = lambda *a, **k: "not json"
    try:
        r = ea.analyse(TAMPERED[0].read_bytes(), TAMPERED[0].name)
    finally:
        ea.call_llm = ea_call
    assert not r["llm_used"] and r["error"] and r["manipulation_score"] <= 79


def test_rejects_non_images():
    try:
        ea.analyse(b"definitely not an image", "x.jpg", use_llm=False)
        assert False
    except ValueError:
        pass


def test_report_contains_hash_and_findings():
    r = ea.analyse(TAMPERED[0].read_bytes(), TAMPERED[0].name, use_llm=False)
    html = build_report_html(r)
    assert r["integrity"]["sha256"] in html and "Evidence integrity" in html
    assert "images" not in json.loads(result_to_json(r))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

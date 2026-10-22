"""
faces.py: find faces and prepare them for close inspection.

Calibration (tests/test_faces.py, scratch experiments): comparing a face's noise level and error
level with its surroundings did NOT separate 91 synthetic face swaps (feathered blend, re-saved
once) from 8 real and 13 AI-generated portraits, so those readings are shown as experimental
context and never change the verdict. What the face view adds is (1) where the faces are, for the
markers, and (2) zoomed close-ups sent to the vision model, which sees blending seams, warped
teeth or eyes and mismatched skin far better at full resolution than in a downscaled whole image.

Detector: OpenCV Haar cascade (frontal faces). Uses cv2.data when the pip package ships it,
otherwise the copy in models/ (BSD licence, from the OpenCV repository).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

_MODEL = Path(__file__).resolve().parent / "models" / "haarcascade_frontalface_alt.xml"
_cascade = None
MAX_FACES = 6


_missing = False


def _detector():
    """The face detector, or None when this OpenCV build doesn't include it (some OpenCV 5 builds
    moved CascadeClassifier out): then the face step is skipped instead of failing the analysis."""
    global _cascade, _missing
    if _missing:
        return None
    if cv2 is None or not hasattr(cv2, "CascadeClassifier"):
        _missing = True
        return None
    if _cascade is None:
        candidates = [_MODEL]
        data = getattr(cv2, "data", None)
        if data is not None:
            candidates.insert(0, Path(data.haarcascades) / "haarcascade_frontalface_alt.xml")
        for p in candidates:
            if p.exists():
                try:
                    c = cv2.CascadeClassifier(str(p))
                except Exception:
                    continue
                if not c.empty():
                    _cascade = c
                    break
        if _cascade is None:
            _missing = True
    return _cascade


def available() -> bool:
    return _detector() is not None


def detect(img: Image.Image) -> list[list[int]]:
    """Face boxes [x0, y0, x1, y1] in image pixels, largest first."""
    casc = _detector()
    if casc is None:
        return []
    gray = np.asarray(img.convert("L"))
    h, w = gray.shape
    s = min(1.0, 1024 / max(w, h))
    small = cv2.resize(gray, (max(1, int(w * s)), max(1, int(h * s)))) if s < 1 else gray
    small = cv2.equalizeHist(small)
    min_side = max(24, int(0.05 * min(small.shape)))
    found = casc.detectMultiScale(small, scaleFactor=1.1, minNeighbors=5, minSize=(min_side, min_side))
    boxes = [[int(x / s), int(y / s), int((x + fw) / s), int((y + fh) / s)] for x, y, fw, fh in found]
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    return boxes[:MAX_FACES]


def _expand(box, img_size, factor):
    x0, y0, x1, y1 = box
    cx, cy, half = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * factor / 2
    W, H = img_size
    return [int(max(0, cx - half)), int(max(0, cy - half * 1.1)), int(min(W, cx + half)), int(min(H, cy + half * 1.1))]


def closeups(img: Image.Image, boxes: list[list[int]], size: int = 512, limit: int = 3) -> list[Image.Image]:
    """Face crops with some context (hairline, jaw, neck), scaled to `size` for the vision model."""
    out = []
    for b in boxes[:limit]:
        crop = img.convert("RGB").crop(_expand(b, img.size, 1.6))
        if max(crop.size) > size:
            crop.thumbnail((size, size), Image.LANCZOS)
        elif max(crop.size) < size:
            k = size / max(crop.size)
            crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
        out.append(crop)
    return out


def _readings(gray: np.ndarray, box) -> dict:
    """Experimental: noise and fine detail inside the face compared with a ring around it."""
    H, W = gray.shape
    x0, y0, x1, y1 = box
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    pad = int(max(rx, ry) * 1.7)
    X0, Y0, X1, Y1 = max(0, int(cx - pad)), max(0, int(cy - pad)), min(W, int(cx + pad)), min(H, int(cy + pad))
    g = gray[Y0:Y1, X0:X1]
    if g.size < 400:
        return {}
    yy, xx = np.mgrid[Y0:Y1, X0:X1]
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    blur = cv2.GaussianBlur(g, (0, 0), 1.0)
    hp = np.abs(g - blur)
    grad = cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), 2) + 1
    inner, ring = r < 0.6, (r > 1.1) & (r < 1.6)
    if inner.sum() < 50 or ring.sum() < 50:
        return {}
    lo, hi = np.percentile(grad[inner], [25, 75])
    si, sr = inner & (grad >= lo) & (grad <= hi), ring & (grad >= lo) & (grad <= hi)
    if si.sum() < 30 or sr.sum() < 30:
        return {}
    noise = float(np.log((np.median(hp[si]) + 0.05) / (np.median(hp[sr]) + 0.05)))
    sharp_in = float(np.median(grad[inner])) / (float(np.median(g[inner])) + 1)
    sharp_out = float(np.median(grad[ring])) / (float(np.median(g[ring])) + 1)
    return {"noise_vs_surroundings": round(noise, 2),
            "detail_vs_surroundings": round(float(np.log((sharp_in + 1e-3) / (sharp_out + 1e-3))), 2)}


def analyse(img: Image.Image) -> tuple[dict, list[Image.Image], Image.Image | None]:
    """(stats, close-ups for the vision model, overlay image or None)."""
    if not available():
        return {"status": "skipped", "faces": [],
                "detail": "Face detection isn't available in this OpenCV build (pip install opencv-contrib-python-headless)."}, [], None
    rgb = img.convert("RGB")
    boxes = detect(rgb)
    if not boxes:
        return {"status": "ok", "count": 0, "faces": []}, [], None
    gray = np.asarray(rgb.convert("L"), np.float32)
    W, H = rgb.size
    faces = []
    for i, b in enumerate(boxes):
        area = (b[2] - b[0]) * (b[3] - b[1]) / (W * H)
        faces.append({"n": i + 1, "box": b, "share_of_image": round(area, 4), **_readings(gray, b),
                      "closeup": i < 3})
    return {"status": "ok", "count": len(faces), "faces": faces}, closeups(rgb, boxes), overlay(rgb, boxes)


def overlay(img: Image.Image, boxes: list[list[int]]) -> Image.Image:
    """The image dimmed outside the faces, so the faces stand out when wiped against the photo."""
    rgb = img.convert("RGB")
    dim = Image.blend(rgb, Image.new("RGB", rgb.size, (20, 32, 43)), 0.62)
    mask = Image.new("L", rgb.size, 0)
    d = ImageDraw.Draw(mask)
    for b in boxes:
        e = _expand(b, rgb.size, 1.25)
        d.ellipse(e, fill=255)
    out = Image.composite(rgb, dim, mask)
    d2 = ImageDraw.Draw(out)
    lw = max(2, rgb.width // 400)
    for b in boxes:
        d2.ellipse(_expand(b, rgb.size, 1.25), outline=(242, 194, 48), width=lw)
    return out
